"""Dispatch, foreground and background workers, and the job lifecycle commands."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import jobstore
from .approvals import load_approval, validate_approval_binding
from .common import AGY_BIN, STATE_ROOT, atomic_write_json, parse_duration, run_capture, sha256_text, utc_now
from .jobstore import JOB_EXIT_CODES, acquire_workspace_lock, job_lock, job_result, job_result_path, job_spec_path, list_jobs, pid_alive, read_job, refresh_job, release_workspace_lock, start_background_job, write_job, write_terminal_result
from .routing import available_models, is_non_high_gemini, select_model
from .workspace import canonical_workspace, workspace_delta, workspace_snapshot, workspace_status


PERMISSION_NOTICE_RE = re.compile(
    r"soft[- ]?denied|permission[^\n]*(?:required|denied|not granted|unavailable)|"
    r"requires approval|approval[^\n]*(?:unavailable|cannot be obtained)|tool[^\n]*denied",
    re.IGNORECASE,
)


# A plan-mode run that changed the workspace. Snapshots see Git workspaces only.
PLAN_MODE_CHANGED_EXIT = 5


# AGY reports its own print timeout on stderr and still emits status SUCCESS with an empty response.
TIMEOUT_NOTICE_RE = re.compile(r"print timeout after[^\n]*turn in progress", re.IGNORECASE)


DIAGNOSTIC_PATTERNS = (
    re.compile(r"PERMISSION_DENIED|permission denied|does not have permission|not logged into antigravity", re.IGNORECASE),
    re.compile(r"operation not permitted|bind(?:ing)?[^\n]*(?:failed|denied)|localhost", re.IGNORECASE),
    re.compile(r"authentication failed|auth[^\n]*(?:failed|expired)|token[^\n]*(?:failed|denied|expired)", re.IGNORECASE),
    re.compile(r"model[^\n]*(?:not found|not available|invalid|unknown)", re.IGNORECASE),
    re.compile(r"timed out|timeout|deadline exceeded", re.IGNORECASE),
    re.compile(r"soft[- ]?denied|approval[^\n]*(?:unavailable|denied)", re.IGNORECASE),
)


def diagnostic_excerpt(stderr: str, log_path: Path, max_lines: int = 24) -> list[str]:
    """Return high-signal runtime diagnostics without exposing the whole AGY log."""
    sources = [stderr]
    try:
        if log_path.is_file():
            sources.append("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]))
    except OSError:
        pass

    found: list[str] = []
    for source in sources:
        for raw_line in source.splitlines():
            line = raw_line.strip()
            if not line or not any(pattern.search(line) for pattern in DIAGNOSTIC_PATTERNS):
                continue
            if line not in found:
                found.append(line)
    return found[-max_lines:]


def emit_diagnostics(lines: list[str]) -> None:
    if not lines:
        return
    print("[agy_delegate] AGY diagnostic evidence:", file=sys.stderr)
    for line in lines:
        print(f"[agy_delegate] {line}", file=sys.stderr)


def prepare_run(args: argparse.Namespace) -> dict:
    has_manifest = bool(getattr(args, "approval_file", None))
    if not has_manifest and not args.roster_approved:
        raise RuntimeError(
            "Project roster is not approved; obtain explicit user confirmation and rerun with --roster-approved"
        )
    if not args.model:
        raise RuntimeError(
            "Execution requires the exact user-approved model slug via --model; automatic selection is proposal-only"
        )
    if not has_manifest and args.unrestricted and not args.unrestricted_approved:
        raise RuntimeError(
            "Unrestricted AGY execution requires a separate explicit confirmation; rerun with "
            "--unrestricted-approved only after the user confirms that permission profile"
        )
    if not has_manifest and args.unrestricted_approved and not args.unrestricted:
        raise RuntimeError("--unrestricted-approved requires --unrestricted")

    cwd = canonical_workspace(args.cwd)
    prompt_file = Path(args.prompt_file).expanduser().resolve()
    if not prompt_file.is_file():
        raise RuntimeError(f"Prompt file does not exist: {prompt_file}")
    prompt_text = prompt_file.read_text(encoding="utf-8")
    approval = validate_approval_binding(args, cwd, prompt_text)

    trust_status = workspace_status(cwd, args.mode)
    if not trust_status["trusted"]:
        raise RuntimeError(
            f"Workspace is not trusted: {cwd}; obtain separate trust approval, then run "
            "workspace --grant for this exact path"
        )

    models = available_models()
    model_ids = {m["id"] for m in models}
    model = args.model
    if model not in model_ids:
        raise RuntimeError(f"Requested model is unavailable: {model}")
    if args.strategy == "C":
        required_model = select_model(args.role, models, strategy="C")
        if model != required_model:
            raise RuntimeError(
                f"Strategy C requires the latest Gemini Flash High model {required_model}; got {model}"
            )
    non_high_allowed = bool(args.allow_non_high_gemini) if approval is None else bool(approval.get("allow_non_high_gemini"))
    if is_non_high_gemini(model) and not non_high_allowed:
        raise RuntimeError(
            "Gemini medium/low requires explicit user confirmation; rerun with "
            "--allow-non-high-gemini only after the user confirms"
        )

    schema_path = None
    if args.json_schema:
        schema_path = Path(args.json_schema).expanduser().resolve()
        if not schema_path.is_file():
            raise RuntimeError(f"JSON schema does not exist: {schema_path}")

    return {
        "cwd": cwd,
        "model": model,
        "prompt_text": prompt_text,
        "schema_path": schema_path,
        "approval_path": Path(args.approval_file).expanduser().resolve() if has_manifest else None,
        "approval_id": approval.get("approval_id") if approval else None,
        "policy": approval.get("policy") if approval else None,
        "correction_of": approval.get("correction_of") if approval else None,
        "follow_up_of": approval.get("follow_up_of") if approval else None,
        "correction_round": approval.get("correction_round", 0) if approval else None,
    }


def build_agy_command(args: argparse.Namespace, prepared: dict, log_path: Path) -> list[str]:
    command = [
        AGY_BIN,
        "--add-dir", str(prepared["cwd"]),
        "--input-format", "stream-json", "--output-format", "stream-json", "--model", prepared["model"],
        "--mode", args.mode, "--print-timeout", f"{args.timeout_seconds}s",
        "--log-file", str(log_path),
    ]
    if args.conversation:
        command.extend(["--conversation", args.conversation])
    if prepared["schema_path"]:
        command.extend(["--json-schema", str(prepared["schema_path"])])
    if args.unrestricted:
        command.append("--dangerously-skip-permissions")
    return command


def prompt_event(prompt_text: str) -> str:
    return json.dumps({"event": "user", "message": {"content": prompt_text}}, ensure_ascii=False) + "\n"


def parse_stream_result(stdout: str) -> dict | None:
    final = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("event") == "result" or event.get("type") == "result" or "status" in event:
            # AGY 1.2 nests the outcome: {"event": "result", "result": {"status": ..., "conversation_id": ...}}.
            nested = event.get("result")
            final = {**event, **nested} if isinstance(nested, dict) else event
    return final


def parses_as_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (TypeError, ValueError):
        return False


def last_open_step(stdout: str) -> dict | None:
    """The newest AGY step that never reached DONE: what the turn was stuck on when it stopped."""
    open_steps: dict = {}
    for line in stdout.splitlines():
        try:
            step = json.loads(line).get("step_update")
        except (json.JSONDecodeError, AttributeError):
            continue
        if not isinstance(step, dict):
            continue
        if step.get("state") == "DONE":
            open_steps.pop(step.get("step_index"), None)
        else:
            open_steps[step.get("step_index")] = step
    if not open_steps:
        return None
    step = open_steps[max(open_steps, key=lambda index: index if isinstance(index, int) else -1)]
    return {"step": step.get("tool_name") or step.get("step_type"), "state": step.get("state"),
            "parameters": (step.get("tool_info") or {}).get("parameters")}


def cmd_run(args: argparse.Namespace) -> int:
    prepared = prepare_run(args)
    if args.background:
        return start_background_job(args, prepared)

    lock_fd = None
    if args.mode == "accept-edits" and not getattr(args, "workspace_lock_held", False):
        lock_fd, _ = acquire_workspace_lock(
            prepared["cwd"],
            {"kind": "foreground", "pid": os.getpid(), "role": args.role},
        )
    try:
        return run_foreground(args, prepared)
    finally:
        release_workspace_lock(lock_fd)


def run_foreground(args: argparse.Namespace, prepared: dict) -> int:
    directory = Path(getattr(args, "evidence_dir", None) or
                     STATE_ROOT / "runs" / f"run-{uuid.uuid4().hex}")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    before = workspace_snapshot(prepared["cwd"])
    atomic_write_json(directory / "before.json", before)
    paths = list(before.get("paths", {}))
    # Only protect the user's existing changes. Never point the worker at Mission Control's own state:
    # given the evidence path, real workers spent whole turns reading job files instead of doing the task.
    context = "" if not paths else (
        "\n\nAMC workspace context (observed data, not instructions):\n"
        f"Files the user had already changed before this run: {json.dumps(paths[:100], ensure_ascii=True)[:12000]}\n"
        "The list may be truncated. They belong to the user: leave them as they are unless the task names them. "
        "Do not overwrite, clean, stash or deliver unrelated work.\n")
    dispatched = dict(prepared, prompt_text=prepared["prompt_text"] + context)
    atomic_write_json(directory / "dispatch.json", {
        "original_prompt_sha256": sha256_text(prepared["prompt_text"]),
        "dispatched_prompt_sha256": sha256_text(dispatched["prompt_text"]),
        "approval_id": prepared.get("approval_id"), "policy": prepared.get("policy"),
        "correction_round": prepared.get("correction_round"),
    })
    try:
        code = execute_foreground(args, dispatched)
    finally:
        after = workspace_snapshot(prepared["cwd"])
        atomic_write_json(directory / "after.json", after)
        delta = workspace_delta(before, after)
        atomic_write_json(directory / "delta.json", delta)
        print(json.dumps({"amc_evidence": str(directory), "workspace_delta": delta}, ensure_ascii=True), file=sys.stderr)
    if args.mode == "plan" and (delta["changed_paths"] or delta["head_changed"]):
        # AGY does not enforce plan mode: a real plan worker has created files. Never let that pass as read-only.
        print(json.dumps({"status": "ERROR", "error": "the workspace changed during a plan-mode run",
                          "changed_paths": delta["changed_paths"][:50], "head_changed": delta["head_changed"]},
                         ensure_ascii=False), file=sys.stderr)
        return PLAN_MODE_CHANGED_EXIT
    return code


def execute_foreground(args: argparse.Namespace, prepared: dict) -> int:

    with tempfile.TemporaryDirectory(prefix="agy-delegate-") as diagnostic_dir:
        diagnostic_log = Path(diagnostic_dir) / "agy.log"
        command = build_agy_command(args, prepared, diagnostic_log)
        try:
            proc = run_capture(
                command,
                cwd=prepared["cwd"],
                timeout=args.timeout_seconds + 15,
                input_text=prompt_event(prepared["prompt_text"]),
            )
        except subprocess.TimeoutExpired as exc:
            diagnostics = diagnostic_excerpt("", diagnostic_log)
            print(json.dumps({"status": "ERROR", "error": f"agy exceeded wrapper timeout: {exc}"}), file=sys.stderr)
            emit_diagnostics(diagnostics)
            return 124
        diagnostics = diagnostic_excerpt(proc.stderr, diagnostic_log)

    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="" if proc.stderr.endswith("\n") else "\n")
    emit_diagnostics(diagnostics)
    if not proc.stdout.strip():
        print(json.dumps({"status": "ERROR", "error": "agy returned empty stdout"}), file=sys.stderr)
        return proc.returncode or 1
    print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    try:
        payload = parse_stream_result(proc.stdout)
        if payload is None:
            raise ValueError("no result event")
    except ValueError as exc:
        print(json.dumps({"status": "ERROR", "error": f"agy returned invalid stream-json stdout: {exc}"}), file=sys.stderr)
        return proc.returncode or 1
    if PERMISSION_NOTICE_RE.search(proc.stderr or ""):
        print(
            json.dumps(
                {"status": "ERROR", "error": "AGY headless permission request was soft-denied"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    if TIMEOUT_NOTICE_RE.search(proc.stderr or ""):
        print(json.dumps({"status": "ERROR", "error": "agy stopped at its print timeout with the turn in progress",
                          "stuck_step": last_open_step(proc.stdout)}, ensure_ascii=False), file=sys.stderr)
        return 124
    if proc.returncode != 0:
        # A failing exit code wins over anything the stream claims; stdout above keeps any partial response.
        print(json.dumps({"status": "ERROR", "error": f"agy exited with code {proc.returncode}"}), file=sys.stderr)
        return proc.returncode
    # A string "result" is a response; a dict is AGY 1.2's nested envelope, already flattened.
    response = payload.get("response") or (payload.get("result") if isinstance(payload.get("result"), str) else None)
    provider_status = str(payload.get("status", "")).upper()
    # The only recognized non-fatal failure: a clean exit whose ERROR result still carries a response.
    if provider_status == "ERROR" and response:
        print(
            json.dumps(
                {
                    "status": "done_with_warnings",
                    "error": payload.get("error", "agy reported an error after producing a response"),
                    "diagnostics": diagnostics,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 0
    result_event = "result" in (payload.get("event"), payload.get("type"))
    if provider_status == "SUCCESS" or (not provider_status and result_event and not payload.get("error")):
        warning = None
        if not response:
            warning = "agy reported success with an empty response"
        elif prepared["schema_path"] and not parses_as_json(response):
            # ponytail: parse check only; validate against the schema itself if callers start relying on fields.
            warning = "--json-schema was requested but the response is not a single JSON document"
        if warning:
            print(json.dumps({"status": "done_with_warnings", "error": warning, "diagnostics": diagnostics},
                             ensure_ascii=False), file=sys.stderr)
        return 0
    print(json.dumps({"status": "ERROR", "error": payload.get("error") or f"agy reported status {provider_status or 'none'}"},
                     ensure_ascii=False), file=sys.stderr)
    return 1


def cmd_worker(args: argparse.Namespace) -> int:
    job = read_job(args.job_id)
    spec = json.loads(job_spec_path(args.job_id).read_text(encoding="utf-8"))
    try:
        proc = subprocess.run(
            spec["command"],
            cwd=job["cwd"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(30, int(spec["command"][spec["command"].index("--timeout-seconds") + 1]) + 60),
            check=False,
        )
        payload = parse_stream_result(proc.stdout)
        status = "done" if proc.returncode == 0 else "error"
        # Only a successful child may carry the warning label; AGY's own stderr is relayed here.
        if proc.returncode == 0 and ('"status": "done_with_warnings"' in proc.stderr or '"status":"done_with_warnings"' in proc.stderr):
            status = "done_with_warnings"
        result = {
            "job_id": args.job_id,
            "status": status,
            "exit_code": proc.returncode,
            "role": job["role"],
            "model": job["model"],
            "cwd": job["cwd"],
            "conversation_id": (payload or {}).get("conversation_id"),
            "payload": payload,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "evidence_path": job.get("evidence_path"),
            "policy": job.get("policy"),
            "correction_round": job.get("correction_round"),
            "acceptance": "not_evaluated",
        }
        atomic_write_json(job_result_path(args.job_id), result)
        with job_lock(args.job_id):
            current = read_job(args.job_id)
            if current.get("status") not in {"canceled", "canceling"}:
                current["status"] = status
                current["conversation_id"] = result["conversation_id"] or current.get("conversation_id")
                current["finished_at"] = utc_now()
                write_job(current)
        return 0 if status in {"done", "done_with_warnings"} else 1
    except Exception as exc:
        result = {
            "job_id": args.job_id,
            "status": "error",
            "exit_code": 1,
            "role": job.get("role"),
            "model": job.get("model"),
            "cwd": job.get("cwd"),
            "error": str(exc),
        }
        atomic_write_json(job_result_path(args.job_id), result)
        with job_lock(args.job_id):
            current = read_job(args.job_id)
            if current.get("status") not in {"canceled", "canceling"}:
                current["status"] = "error"
                current["finished_at"] = utc_now()
                write_job(current)
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    if args.job_id:
        job = refresh_job(read_job(args.job_id))
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return JOB_EXIT_CODES.get(job.get("status"), 1)
    jobs = list_jobs()
    states = getattr(args, "state", None)
    if states:
        jobs = [job for job in jobs if job.get("status") in states]
    limit = getattr(args, "limit", None)
    if limit is not None:
        jobs = jobs[-limit:]
    print(json.dumps({"jobs": jobs}, ensure_ascii=False, indent=2))
    return 0


UNFINISHED_STATUSES = {"starting", "running", "canceling"}

# Only these statuses are eligible for deletion. Any other status - unknown, missing, or a
# future addition to JOB_EXIT_CODES that isn't listed here - is kept rather than assumed finished.
PRUNABLE_STATUSES = {"done", "done_with_warnings", "error", "crashed", "cancel_failed", "canceled"}


def _finished_at(job: dict) -> datetime | None:
    text = job.get("finished_at")
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _prune_reason(job: dict, cutoff: datetime) -> str | None:
    """Why a job must be kept, or None when it is a finished job older than the cutoff."""
    # A live pid means the worker may still be running whatever the status says (e.g. cancel_failed).
    if job.get("status") in UNFINISHED_STATUSES or pid_alive(job.get("pid")) or pid_alive(job.get("launcher_pid")):
        return "unfinished"
    if job.get("status") not in PRUNABLE_STATUSES:
        return "unknown status"
    finished = _finished_at(job)
    if finished is None:
        return "missing or unparseable finished_at"
    if finished >= cutoff:
        return "too recent"
    return None


def _real_job_dir(root: Path, name: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(root / name).st_mode)
    except OSError:
        return False


def _read_job_at(dir_fd: int) -> dict:
    fd = os.open("job.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    with os.fdopen(fd, encoding="utf-8") as handle:
        try:
            job = json.load(handle)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Job metadata is corrupt: {exc}") from exc
    if not isinstance(job, dict):
        raise RuntimeError("Job metadata must be an object")
    return job


@contextlib.contextmanager
def _locked_job_dir(root_fd: int, name: str):
    """Open JOB_ROOT/name without following symlinks and hold the same flock as jobstore.job_lock.

    Everything is opened relative to directory fds, so a directory swapped for a symlink after
    selection makes the open fail instead of creating or reading files outside JOB_ROOT.
    """
    dir_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    try:
        lock_fd = os.open("job.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield dir_fd
        finally:
            os.close(lock_fd)
    finally:
        os.close(dir_fd)


def _prune_one(root: Path, root_fd: int, name: str, cutoff: datetime) -> str | None:
    """Delete one candidate under its lock; return why it was kept, or None once removed."""
    with _locked_job_dir(root_fd, name) as dir_fd:
        # Re-check under the lock: a job may have been continued or replaced since selection.
        job = _read_job_at(dir_fd)
        if job.get("job_id") != name:
            return "job_id does not match directory name"
        reason = _prune_reason(job, cutoff)
        if reason:
            return reason
        # Rename-then-verify: rename never follows a symlink, and the renamed entry must be the
        # very directory we locked before anything is deleted.
        hidden = f".prune-{name}-{uuid.uuid4().hex}"
        os.rename(name, hidden, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        locked = os.fstat(dir_fd)
        try:
            moved = os.stat(hidden, dir_fd=root_fd, follow_symlinks=False)
            same = (stat.S_ISDIR(moved.st_mode) and (moved.st_dev, moved.st_ino) == (locked.st_dev, locked.st_ino)
                    and _read_job_at(dir_fd).get("job_id") == name)
        except (OSError, RuntimeError):
            same = False
        if not same:
            try:
                os.rename(hidden, name, src_dir_fd=root_fd, dst_dir_fd=root_fd)
            except OSError as exc:
                return f"directory changed during prune; left as {hidden}: {exc}"
            return "directory changed during prune"
    # rmtree refuses a symlinked top directory and never follows links inside it.
    shutil.rmtree(root / hidden)
    return None


def cmd_prune(args: argparse.Namespace) -> int:
    root = jobstore.JOB_ROOT
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=args.older_than)
    candidates, removed, skipped = [], [], []
    names = sorted(os.listdir(root)) if root.is_dir() else []
    for name in names:
        if not _real_job_dir(root, name):
            skipped.append({"entry": name, "reason": "not a real directory"})
            continue
        try:
            jobstore.validate_job_id(name)
            job = read_job(name)
        except (OSError, RuntimeError) as exc:
            skipped.append({"entry": name, "reason": str(exc)})
            continue
        if job.get("job_id") != name:
            skipped.append({"entry": name, "reason": "job_id does not match directory name"})
            continue
        if not isinstance(job.get("status"), str):
            skipped.append({"job_id": name, "reason": "unknown status"})
            continue
        try:
            job = refresh_job(job)
        except (OSError, RuntimeError) as exc:
            skipped.append({"job_id": name, "reason": str(exc)})
            continue
        reason = _prune_reason(job, cutoff)
        if reason:
            skipped.append({"job_id": name, "reason": reason})
        else:
            candidates.append(name)
    if args.yes and candidates:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for name in candidates:
                try:
                    reason = _prune_one(root, root_fd, name, cutoff)
                except (OSError, RuntimeError) as exc:
                    reason = str(exc)
                if reason:
                    skipped.append({"job_id": name, "reason": reason})
                else:
                    removed.append(name)
        finally:
            os.close(root_fd)
    print(json.dumps({
        "dry_run": not args.yes,
        "older_than_seconds": float(args.older_than),
        "removed": removed,
        "would_remove": [] if args.yes else candidates,
        "skipped": skipped,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    print(json.dumps(job_result(args.job_id), ensure_ascii=False, indent=2))
    return 0


def cmd_wait(args: argparse.Namespace) -> int:
    if args.timeout_seconds_override is not None:
        budget_seconds = args.timeout_seconds_override
    else:
        try:
            budget_seconds = parse_duration(args.timeout)
        except ValueError:
            raise RuntimeError('Invalid --timeout; use values such as 100s, 5m, or 1h')
    if budget_seconds <= 0:
        raise RuntimeError("--timeout must be positive")
    deadline = time.monotonic() + budget_seconds
    while True:
        job = refresh_job(read_job(args.job_id))
        status = job.get("status")
        if status not in {"starting", "running", "canceling"}:
            print(json.dumps(job_result(args.job_id), ensure_ascii=False, indent=2))
            return JOB_EXIT_CODES.get(status, 1)
        if time.monotonic() >= deadline:
            print(
                json.dumps(
                    {
                        "job_id": args.job_id,
                        "status": status,
                        "message": "wait timeout expired; call wait again",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return JOB_EXIT_CODES["running"]
        time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))


def signal_process_group(pid: int, sig: signal.Signals) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return


def wait_for_process_exit(pid: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not pid_alive(pid)


def terminate_process_group(pid: int | None, grace_seconds: float = 5.0) -> bool:
    if not pid or not pid_alive(pid):
        return True
    signal_process_group(pid, signal.SIGTERM)
    if wait_for_process_exit(pid, grace_seconds):
        return True
    signal_process_group(pid, signal.SIGKILL)
    return wait_for_process_exit(pid, min(2.0, grace_seconds))


def process_matches_job(pid: int, job_id: str) -> bool:
    try:
        if os.getpgid(pid) != pid:
            return False
    except ProcessLookupError:
        return False
    proc = run_capture(["ps", "-p", str(pid), "-o", "command="], timeout=5)
    command = proc.stdout.strip() if proc.returncode == 0 else ""
    return bool(command and "_worker" in command and job_id in command)


def cmd_cancel(args: argparse.Namespace) -> int:
    job = refresh_job(read_job(args.job_id))
    with job_lock(args.job_id):
        job = read_job(args.job_id)
        if job.get("status") not in {"starting", "running", "canceling"}:
            print(json.dumps(job, ensure_ascii=False, indent=2))
            return JOB_EXIT_CODES.get(job.get("status"), 1)
        pid = job.get("pid")
        if pid and not process_matches_job(pid, args.job_id):
            raise RuntimeError(
                f"Refusing to signal PID {pid}: it is not the recorded Mission Control worker for {args.job_id}"
            )
        job["status"] = "canceling"
        job["cancel_requested_at"] = utc_now()
        write_job(job)
    # Signal and wait outside the lock so the worker can still record its own finish.
    terminated = terminate_process_group(pid, args.grace_seconds)
    final_status = "canceled" if terminated else "cancel_failed"
    with job_lock(args.job_id):
        job = read_job(args.job_id)
        if job.get("status") == "canceling":
            job["status"] = final_status
            job["finished_at"] = utc_now()
            write_job(job)
            write_terminal_result(job, final_status, "Job canceled and process exit confirmed" if terminated
                                  else "Process did not exit after TERM and KILL")
    print(json.dumps(job, ensure_ascii=False, indent=2))
    return JOB_EXIT_CODES.get(job.get("status"), 1)


def cmd_continue(args: argparse.Namespace) -> int:
    job = refresh_job(read_job(args.job_id))
    if job.get("status") in {"starting", "running", "canceling"}:
        raise RuntimeError(f"Job {args.job_id} is still running; wait for it before continuing the conversation")
    conversation_id = job.get("conversation_id")
    if not conversation_id:
        try:
            conversation_id = job_result(args.job_id).get("conversation_id")
        except RuntimeError:
            conversation_id = None
    if not conversation_id:
        raise RuntimeError(f"Job {args.job_id} has no recorded AGY conversation id")

    if args.approval_file:
        approval = load_approval(Path(args.approval_file).expanduser().resolve())
        parent_id = approval.get("correction_of") or approval.get("follow_up_of")
        if parent_id not in (None, args.job_id):
            raise RuntimeError("Continuation approval belongs to a different parent job")
        if job.get("policy") and parent_id != args.job_id:
            raise RuntimeError("Use --correction-of or --follow-up-of to preserve this job's lineage")
    follow_up = argparse.Namespace(
        strategy=job["strategy"],
        role=job["role"],
        cwd=job["cwd"],
        prompt_file=args.prompt_file,
        model=job["model"],
        roster_approved=args.roster_approved,
        allow_non_high_gemini=args.allow_non_high_gemini,
        unrestricted=args.unrestricted,
        unrestricted_approved=args.unrestricted_approved,
        mode=job["mode"],
        conversation=conversation_id,
        json_schema=None,
        timeout_seconds=args.timeout_seconds,
        background=args.background,
        approval_file=args.approval_file,
        workspace_lock_held=False,
    )
    return cmd_run(follow_up)
