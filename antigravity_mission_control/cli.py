#!/usr/bin/env python3
"""Antigravity Mission Control: bounded AGY orchestration and quota telemetry."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


STRATEGY_PATTERNS = {
    "A": {
        "scout": [r"gemini-.*flash-high$", r"gpt-oss", r"claude.*sonnet"],
        "planner": [r"gemini-.*flash-high$", r"claude.*sonnet", r"gemini-.*pro-high$", r"claude.*opus"],
        "implementer": [r"claude.*sonnet", r"gemini-.*flash-high$", r"gemini-.*pro-high$", r"gpt-oss", r"claude.*opus"],
        "reviewer": [r"gpt-oss", r"gemini-.*pro-high$", r"claude.*sonnet", r"claude.*opus", r"gemini-.*flash-high$"],
    },
    "B": {
        "scout": [r"claude.*opus", r"gemini-.*pro-high$", r"claude.*sonnet", r"gemini-.*flash-high$"],
        "planner": [r"claude.*opus", r"gemini-.*pro-high$", r"claude.*sonnet", r"gemini-.*flash-high$"],
        "implementer": [r"claude.*opus", r"gemini-.*pro-high$", r"claude.*sonnet", r"gemini-.*flash-high$"],
        "reviewer": [r"claude.*opus", r"gemini-.*pro-high$", r"claude.*sonnet", r"gpt-oss", r"gemini-.*flash-high$"],
    },
    "C": {
        "scout": [r"gemini-.*flash-high$"],
        "planner": [r"gemini-.*flash-high$"],
        "implementer": [r"gemini-.*flash-high$"],
        "reviewer": [r"gemini-.*flash-high$"],
    },
}

ROLES = tuple(STRATEGY_PATTERNS["A"])
VERSION = "0.1.0a1"
AGY_BIN = os.environ.get("AGY_MC_BIN", os.environ.get("AGY_ORCHESTRATOR_BIN", "agy"))
SETTINGS_PATH = Path(
    os.environ.get(
        "AGY_MC_SETTINGS_PATH",
        str(Path.home() / ".gemini" / "antigravity-cli" / "settings.json"),
    )
).expanduser()
STATE_ROOT = Path(
    os.environ.get(
        "AGY_MC_STATE_ROOT",
        str(Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "antigravity-mission-control"),
    )
).expanduser()
JOB_ROOT = Path(
    os.environ.get(
        "AGY_MC_JOB_ROOT",
        os.environ.get("AGY_ORCHESTRATOR_JOB_ROOT", str(STATE_ROOT / "jobs")),
    )
).expanduser()
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$")
JOB_EXIT_CODES = {"done": 0, "done_with_warnings": 0, "running": 2, "error": 3, "crashed": 3, "canceled": 4}
PERMISSION_NOTICE_RE = re.compile(
    r"soft[- ]?denied|permission[^\n]*(?:required|denied|not granted|unavailable)|"
    r"requires approval|approval[^\n]*(?:unavailable|cannot be obtained)|tool[^\n]*denied",
    re.IGNORECASE,
)
DIAGNOSTIC_PATTERNS = (
    re.compile(r"PERMISSION_DENIED|permission denied|does not have permission|not logged into antigravity", re.IGNORECASE),
    re.compile(r"operation not permitted|bind(?:ing)?[^\n]*(?:failed|denied)|localhost", re.IGNORECASE),
    re.compile(r"authentication failed|auth[^\n]*(?:failed|expired)|token[^\n]*(?:failed|denied|expired)", re.IGNORECASE),
    re.compile(r"model[^\n]*(?:not found|not available|invalid|unknown)", re.IGNORECASE),
    re.compile(r"timed out|timeout|deadline exceeded", re.IGNORECASE),
    re.compile(r"soft[- ]?denied|approval[^\n]*(?:unavailable|denied)", re.IGNORECASE),
)


def run_capture(
    command: list[str],
    cwd: Path | None = None,
    timeout: int = 30,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        raise RuntimeError(f"Invalid job id: {job_id}")
    return job_id


def job_dir(job_id: str) -> Path:
    return JOB_ROOT / validate_job_id(job_id)


def job_meta_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def job_result_path(job_id: str) -> Path:
    return job_dir(job_id) / "result.json"


def job_spec_path(job_id: str) -> Path:
    return job_dir(job_id) / "spec.json"


def read_job(job_id: str) -> dict:
    path = job_meta_path(job_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"No job {job_id} in {JOB_ROOT}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Job metadata is corrupt: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Job metadata must be an object: {path}")
    return payload


def write_job(job: dict) -> None:
    atomic_write_json(job_meta_path(job["job_id"]), job)


def pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def refresh_job(job: dict) -> dict:
    if job.get("status") == "running" and not pid_alive(job.get("pid")):
        if job_result_path(job["job_id"]).is_file():
            try:
                result = json.loads(job_result_path(job["job_id"]).read_text(encoding="utf-8"))
                job["status"] = result.get("status", "error")
            except (OSError, json.JSONDecodeError):
                job["status"] = "crashed"
        else:
            job["status"] = "crashed"
            atomic_write_json(
                job_result_path(job["job_id"]),
                {
                    "job_id": job["job_id"],
                    "status": "crashed",
                    "exit_code": JOB_EXIT_CODES["crashed"],
                    "role": job.get("role"),
                    "model": job.get("model"),
                    "cwd": job.get("cwd"),
                    "error": "Worker exited without writing a result",
                },
            )
        job["finished_at"] = job.get("finished_at") or utc_now()
        write_job(job)
    return job


def list_jobs() -> list[dict]:
    if not JOB_ROOT.is_dir():
        return []
    jobs = []
    for path in JOB_ROOT.glob("*/job.json"):
        try:
            jobs.append(refresh_job(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, KeyError, RuntimeError):
            continue
    return sorted(jobs, key=lambda job: job.get("started_at", ""))


def active_edit_job(cwd: Path) -> dict | None:
    canonical = str(cwd.expanduser().resolve())
    for job in list_jobs():
        if job.get("status") == "running" and job.get("cwd") == canonical and job.get("mode") == "accept-edits":
            return job
    return None


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


def available_models() -> list[dict[str, str]]:
    proc = run_capture([AGY_BIN, "--output-format", "json", "models"])
    if proc.returncode == 0:
        try:
            payload = json.loads(proc.stdout)
            models = payload.get("command", {}).get("data", {}).get("models", [])
            if models:
                return [{"id": str(m["id"]), "label": str(m.get("label", m["id"]))} for m in models]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    fallback = run_capture([AGY_BIN, "models"])
    models = []
    for line in fallback.stdout.splitlines():
        parts = line.split("\t", 1)
        if parts and re.fullmatch(r"[A-Za-z0-9._-]+", parts[0]):
            models.append({"id": parts[0], "label": parts[1] if len(parts) > 1 else parts[0]})
    if models:
        return models
    detail = (proc.stderr or fallback.stderr or "agy returned no models").strip()
    raise RuntimeError(detail)


def version_key(model_id: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", model_id)[:4])


def family(model_id: str) -> str:
    lowered = model_id.lower()
    for known in ("claude", "gemini", "gpt"):
        if known in lowered:
            return known
    return lowered.split("-", 1)[0]


def is_non_high_gemini(model_id: str) -> bool:
    return family(model_id) == "gemini" and not model_id.lower().endswith("-high")


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Cannot parse AGY settings {SETTINGS_PATH}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"AGY settings must contain a JSON object: {SETTINGS_PATH}")
    return data


def canonical_workspace(raw_path: str) -> Path:
    workspace = Path(raw_path).expanduser().resolve()
    if not workspace.is_dir():
        raise RuntimeError(f"Workspace does not exist: {workspace}")
    if workspace == Path(workspace.anchor) or workspace == Path.home().resolve():
        raise RuntimeError(f"Refusing to trust a broad workspace: {workspace}")
    return workspace


def workspace_is_trusted(workspace: Path, settings: dict) -> bool:
    workspace = workspace.expanduser().resolve()
    for raw in settings.get("trustedWorkspaces", []) or []:
        try:
            if Path(str(raw)).expanduser().resolve() == workspace:
                return True
        except OSError:
            continue
    return False


def matching_root_rule(settings: dict, list_name: str, workspace: Path, actions: tuple[str, ...]) -> str | None:
    workspace = workspace.expanduser().resolve()
    permissions = settings.get("permissions") or {}
    if not isinstance(permissions, dict):
        return None
    for rule in permissions.get(list_name, []) or []:
        match = re.fullmatch(r"([a-z_]+)\((.*)\)", str(rule).strip())
        if not match or match.group(1) not in actions:
            continue
        target = match.group(2).strip()
        if target == "*" or target in (".", "./"):
            return str(rule)
        path = Path(target).expanduser()
        if path.is_absolute():
            try:
                resolved = path.resolve()
                if resolved == workspace or resolved in workspace.parents:
                    return str(rule)
            except OSError:
                continue
    return None


def workspace_status(workspace: Path, mode: str = "plan") -> dict:
    workspace = workspace.expanduser().resolve()
    settings = load_settings()
    actions = ("read_file", "write_file") if mode == "accept-edits" else ("read_file",)
    return {
        "workspace": str(workspace),
        "trusted": workspace_is_trusted(workspace, settings),
        "blocking_deny": matching_root_rule(settings, "deny", workspace, actions),
        "blocking_ask": matching_root_rule(settings, "ask", workspace, actions),
        "settings": str(SETTINGS_PATH),
    }


def write_settings_atomic(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    original_mode = SETTINGS_PATH.stat().st_mode & 0o777 if SETTINGS_PATH.exists() else 0o600
    fd, temp_name = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=SETTINGS_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, original_mode)
        os.replace(temp_name, SETTINGS_PATH)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def ensure_workspace_trusted(workspace: Path, mode: str, approved: bool) -> bool:
    workspace = workspace.expanduser().resolve()
    status = workspace_status(workspace, mode)
    if status["trusted"]:
        return False
    if status["blocking_deny"]:
        raise RuntimeError(f"Explicit permission deny blocks workspace trust: {status['blocking_deny']}")
    if status["blocking_ask"]:
        raise RuntimeError(f"Explicit permission ask requires manual resolution: {status['blocking_ask']}")
    if not approved:
        raise RuntimeError(
            f"Workspace is not trusted: {workspace}; obtain roster approval before granting exact workspace trust"
        )
    settings = load_settings()
    trusted = list(settings.get("trustedWorkspaces", []) or [])
    trusted.append(str(workspace) + os.sep)
    settings["trustedWorkspaces"] = trusted
    write_settings_atomic(settings)
    return True


def select_model(role: str, models: list[dict[str, str]], avoid_family: str | None = None, strategy: str = "A") -> str:
    candidates = [m for m in models if not is_non_high_gemini(m["id"])]
    if strategy == "C":
        if avoid_family:
            raise RuntimeError("Strategy C does not support --avoid-family; every AGY call must use Gemini")
        candidates = [m for m in candidates if re.search(r"gemini-.*flash-high$", m["id"], re.IGNORECASE)]
        if not candidates:
            raise RuntimeError("Strategy C is unavailable: no Gemini Flash High model is currently available")
    if avoid_family:
        alternatives = [m for m in candidates if family(m["id"]) != avoid_family.lower()]
        if alternatives:
            candidates = alternatives
    for pattern in STRATEGY_PATTERNS[strategy][role]:
        matches = [m["id"] for m in candidates if re.search(pattern, m["id"], re.IGNORECASE)]
        if matches:
            return max(matches, key=version_key)
    if candidates:
        return candidates[0]["id"]
    raise RuntimeError("No AGY models are available")


def cmd_models(_args: argparse.Namespace) -> int:
    print(json.dumps({"models": available_models()}, ensure_ascii=False, indent=2))
    return 0


def _command_data(payload: dict) -> dict:
    data = payload.get("command", {}).get("data")
    if not isinstance(data, dict):
        data = payload.get("response", {}).get("command", {}).get("data")
    return data if isinstance(data, dict) else {}


def normalize_usage(payload: dict) -> dict:
    """Return a stable, account-free view of AGY's evolving /usage response."""
    data = _command_data(payload)
    raw_groups = data.get("groups")
    if not isinstance(raw_groups, list):
        raise RuntimeError("agy /usage response does not contain command.data.groups")
    groups = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            continue
        buckets = []
        for raw_bucket in raw_group.get("buckets", []):
            if not isinstance(raw_bucket, dict):
                continue
            remaining = raw_bucket.get("remaining_fraction")
            if not isinstance(remaining, (int, float)) or isinstance(remaining, bool):
                remaining = None
            elif 0 <= float(remaining) <= 1:
                remaining = round(float(remaining), 6)
            else:
                remaining = None
            buckets.append(
                {
                    "id": raw_bucket.get("id"),
                    "name": raw_bucket.get("name"),
                    "window": raw_bucket.get("window"),
                    "remaining_fraction": remaining,
                    "remaining_percent": round(remaining * 100, 2) if remaining is not None else None,
                    "reset_time": raw_bucket.get("reset_time"),
                    "disabled": bool(raw_bucket.get("disabled", False)),
                }
            )
        groups.append({"name": raw_group.get("name") or "Unknown", "buckets": buckets})
    return {
        "schema": "agy-mc-usage.v1",
        "status": "ok",
        "source": "agy-cli:/usage",
        "fetched_at": utc_now(),
        "groups": groups,
        "errors": [],
    }


def fetch_usage(timeout_seconds: int = 15) -> tuple[dict, int]:
    try:
        proc = run_capture([AGY_BIN, "-p", "/usage", "--output-format", "json"], timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return {
            "schema": "agy-mc-usage.v1",
            "status": "error",
            "source": "agy-cli:/usage",
            "fetched_at": utc_now(),
            "groups": None,
            "errors": [f"agy /usage timed out after {timeout_seconds}s"],
        }, 1
    if proc.returncode != 0:
        return {
            "schema": "agy-mc-usage.v1",
            "status": "error",
            "source": "agy-cli:/usage",
            "fetched_at": utc_now(),
            "groups": None,
            "errors": [f"agy /usage failed with exit code {proc.returncode}"],
        }, 1
    try:
        payload = json.loads(proc.stdout)
        if not isinstance(payload, dict):
            raise ValueError("top-level value is not an object")
        return normalize_usage(payload), 0
    except (json.JSONDecodeError, ValueError, RuntimeError) as exc:
        return {
            "schema": "agy-mc-usage.v1",
            "status": "error",
            "source": "agy-cli:/usage",
            "fetched_at": utc_now(),
            "groups": None,
            "errors": [f"cannot parse agy /usage: {exc}"],
        }, 1


def render_usage_table(snapshot: dict) -> str:
    lines = [f"Antigravity quota  {snapshot['fetched_at']}  status={snapshot['status']}"]
    lines.append("GROUP                    WINDOW        REMAINING   RESET / STATE")
    lines.append("-" * 82)
    groups = snapshot.get("groups")
    if isinstance(groups, list):
        for group in groups:
            buckets = group.get("buckets") or [{}]
            for index, bucket in enumerate(buckets):
                group_name = str(group.get("name", "Unknown")) if index == 0 else ""
                window = str(bucket.get("window") or bucket.get("name") or bucket.get("id") or "unknown")
                percent = bucket.get("remaining_percent")
                remaining = "unknown" if percent is None else f"{percent:6.2f}%"
                state = "disabled" if bucket.get("disabled") else str(bucket.get("reset_time") or "unknown")
                lines.append(f"{group_name[:24]:24} {window[:13]:13} {remaining:>10}   {state}")
    if snapshot.get("errors"):
        lines.append("Errors: " + "; ".join(str(error) for error in snapshot["errors"]))
    return "\n".join(lines)


def cmd_usage(args: argparse.Namespace) -> int:
    iteration = 0
    last_code = 0
    try:
        while True:
            snapshot, last_code = fetch_usage(args.timeout_seconds)
            if args.format == "json":
                print(json.dumps(snapshot, ensure_ascii=False, indent=2), flush=True)
            else:
                if args.watch and sys.stdout.isatty():
                    print("\033[2J\033[H", end="")
                print(render_usage_table(snapshot), flush=True)
            iteration += 1
            if not args.watch or (args.count is not None and iteration >= args.count):
                return last_code
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 130


def cmd_doctor(_args: argparse.Namespace) -> int:
    checks = []
    version = run_capture([AGY_BIN, "--version"])
    checks.append({"name": "agy-version", "ok": version.returncode == 0, "detail": version.stdout.strip()})
    help_result = run_capture([AGY_BIN, "--help"])
    required = ("--add-dir", "--input-format", "--output-format", "--model")
    help_text = help_result.stdout + "\n" + help_result.stderr
    missing = [flag for flag in required if flag not in help_text]
    checks.append({"name": "headless-capabilities", "ok": help_result.returncode == 0 and not missing, "missing": missing})
    state_ok = True
    detail = str(STATE_ROOT)
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(STATE_ROOT, 0o700)
    except OSError as exc:
        state_ok, detail = False, str(exc)
    checks.append({"name": "private-state", "ok": state_ok, "detail": detail})
    result = {"schema": "agy-mc-doctor.v1", "version": VERSION, "status": "ok" if all(c["ok"] for c in checks) else "error", "checks": checks}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


def cmd_select(args: argparse.Namespace) -> int:
    print(select_model(args.role, available_models(), args.avoid_family, args.strategy))
    return 0


def cmd_workspace(args: argparse.Namespace) -> int:
    workspace = canonical_workspace(args.cwd)
    if args.grant:
        changed = ensure_workspace_trusted(workspace, args.mode, args.trust_approved or args.roster_approved)
        result = workspace_status(workspace, args.mode)
        result["changed"] = changed
    else:
        result = workspace_status(workspace, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def prepare_run(args: argparse.Namespace) -> dict:
    if not args.roster_approved:
        raise RuntimeError(
            "Project roster is not approved; obtain explicit user confirmation and rerun with --roster-approved"
        )
    if not args.model:
        raise RuntimeError(
            "Execution requires the exact user-approved model slug via --model; automatic selection is proposal-only"
        )
    if args.unrestricted and not args.unrestricted_approved:
        raise RuntimeError(
            "Unrestricted AGY execution requires a separate explicit confirmation; rerun with "
            "--unrestricted-approved only after the user confirms that permission profile"
        )
    if args.unrestricted_approved and not args.unrestricted:
        raise RuntimeError("--unrestricted-approved requires --unrestricted")

    cwd = canonical_workspace(args.cwd)
    prompt_file = Path(args.prompt_file).expanduser().resolve()
    if not prompt_file.is_file():
        raise RuntimeError(f"Prompt file does not exist: {prompt_file}")
    prompt_text = prompt_file.read_text(encoding="utf-8")

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
    if is_non_high_gemini(model) and not args.allow_non_high_gemini:
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
        "trust_added": False,
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
            final = event
    return final


def cmd_run(args: argparse.Namespace) -> int:
    prepared = prepare_run(args)
    if prepared["trust_added"]:
        print(f"Added exact AGY workspace trust: {prepared['cwd']}", file=sys.stderr)
    if args.background:
        return start_background_job(args, prepared)

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
    response = payload.get("response") or payload.get("result")
    if payload.get("status") == "ERROR" and response:
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
    provider_status = str(payload.get("status", "")).upper()
    event_success = payload.get("event") == "result" and not payload.get("error")
    return 0 if proc.returncode == 0 and (provider_status == "SUCCESS" or event_success) else (proc.returncode or 1)


def build_child_run_args(args: argparse.Namespace, prepared: dict, prompt_path: Path, schema_path: Path | None) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "run",
        "--strategy", args.strategy,
        "--role", args.role,
        "--cwd", str(prepared["cwd"]),
        "--prompt-file", str(prompt_path),
        "--model", prepared["model"],
        "--roster-approved",
        "--mode", args.mode,
        "--timeout-seconds", str(args.timeout_seconds),
    ]
    if args.allow_non_high_gemini:
        command.append("--allow-non-high-gemini")
    if args.unrestricted:
        command.extend(["--unrestricted", "--unrestricted-approved"])
    if args.conversation:
        command.extend(["--conversation", args.conversation])
    if schema_path:
        command.extend(["--json-schema", str(schema_path)])
    return command


def start_background_job(args: argparse.Namespace, prepared: dict) -> int:
    if args.mode == "accept-edits":
        active = active_edit_job(prepared["cwd"])
        if active:
            raise RuntimeError(
                f"An editing AGY job is already running for {prepared['cwd']}: {active['job_id']}. "
                "Wait for it or cancel it before starting another editor."
            )

    JOB_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(JOB_ROOT, 0o700)
    job_id = f"{args.role}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    directory = job_dir(job_id)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    prompt_path = directory / "prompt.txt"
    prompt_path.write_text(prepared["prompt_text"], encoding="utf-8")
    os.chmod(prompt_path, 0o600)

    schema_path = None
    if prepared["schema_path"]:
        schema_path = directory / "schema.json"
        schema_path.write_text(prepared["schema_path"].read_text(encoding="utf-8"), encoding="utf-8")
        os.chmod(schema_path, 0o600)

    command = build_child_run_args(args, prepared, prompt_path, schema_path)
    job = {
        "job_id": job_id,
        "status": "running",
        "role": args.role,
        "strategy": args.strategy,
        "model": prepared["model"],
        "cwd": str(prepared["cwd"]),
        "mode": args.mode,
        "conversation_id": args.conversation,
        "pid": None,
        "started_at": utc_now(),
        "result_path": str(job_result_path(job_id)),
        "log_path": str(directory / "worker.log"),
    }
    atomic_write_json(job_spec_path(job_id), {"command": command})
    write_job(job)

    log_fd = os.open(job["log_path"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(log_fd, "a", encoding="utf-8") as log_handle:
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_worker", job_id],
            cwd=str(prepared["cwd"]),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    current = read_job(job_id)
    current["pid"] = child.pid
    write_job(current)

    print(
        json.dumps(
            {
                "status": "queued",
                "job_id": job_id,
                "role": job["role"],
                "model": job["model"],
                "cwd": job["cwd"],
                "mode": job["mode"],
                "result_path": job["result_path"],
                "log_path": job["log_path"],
                "collect": f"python3 scripts/agy_delegate.py wait {job_id} --timeout 100s",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_child_payload(stdout: str) -> dict | None:
    return parse_stream_result(stdout)


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
            timeout=max(30, int(spec["command"][spec["command"].index("--timeout-seconds") + 1]) + 30),
            check=False,
        )
        payload = parse_child_payload(proc.stdout)
        status = "done" if proc.returncode == 0 else "error"
        if '"status": "done_with_warnings"' in proc.stderr or '"status":"done_with_warnings"' in proc.stderr:
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
        }
        atomic_write_json(job_result_path(args.job_id), result)
        current = read_job(args.job_id)
        if current.get("status") != "canceled":
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
        current = read_job(args.job_id)
        if current.get("status") != "canceled":
            current["status"] = "error"
            current["finished_at"] = utc_now()
            write_job(current)
        return 1


def job_result(job_id: str) -> dict:
    path = job_result_path(job_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Job {job_id} has no result yet") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Job result is corrupt: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Job result must be an object: {path}")
    return payload


def cmd_status(args: argparse.Namespace) -> int:
    if args.job_id:
        job = refresh_job(read_job(args.job_id))
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return JOB_EXIT_CODES.get(job.get("status"), 1)
    print(json.dumps({"jobs": list_jobs()}, ensure_ascii=False, indent=2))
    return 0


def cmd_result(args: argparse.Namespace) -> int:
    print(json.dumps(job_result(args.job_id), ensure_ascii=False, indent=2))
    return 0


def cmd_wait(args: argparse.Namespace) -> int:
    if args.timeout_seconds_override is not None:
        budget_seconds = args.timeout_seconds_override
    else:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h)", args.timeout)
        if not match:
            raise RuntimeError('Invalid --timeout; use values such as 100s, 5m, or 1h')
        multiplier = {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[match.group(2)]
        budget_seconds = float(match.group(1)) * multiplier
    if budget_seconds <= 0:
        raise RuntimeError("--timeout must be positive")
    deadline = time.monotonic() + budget_seconds
    while True:
        job = refresh_job(read_job(args.job_id))
        status = job.get("status")
        if status != "running":
            print(json.dumps(job_result(args.job_id), ensure_ascii=False, indent=2))
            return JOB_EXIT_CODES.get(status, 1)
        if time.monotonic() >= deadline:
            print(
                json.dumps(
                    {
                        "job_id": args.job_id,
                        "status": "running",
                        "message": "wait timeout expired; call wait again",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return JOB_EXIT_CODES["running"]
        time.sleep(min(2.0, max(0.1, deadline - time.monotonic())))


def cmd_cancel(args: argparse.Namespace) -> int:
    job = refresh_job(read_job(args.job_id))
    if job.get("status") != "running":
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return JOB_EXIT_CODES.get(job.get("status"), 1)
    pid = job.get("pid")
    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    job["status"] = "canceled"
    job["finished_at"] = utc_now()
    write_job(job)
    atomic_write_json(
        job_result_path(args.job_id),
        {
            "job_id": args.job_id,
            "status": "canceled",
            "exit_code": JOB_EXIT_CODES["canceled"],
            "role": job.get("role"),
            "model": job.get("model"),
            "cwd": job.get("cwd"),
            "error": "Job canceled by the caller",
        },
    )
    print(json.dumps(job, ensure_ascii=False, indent=2))
    return JOB_EXIT_CODES["canceled"]


def cmd_continue(args: argparse.Namespace) -> int:
    job = refresh_job(read_job(args.job_id))
    if job.get("status") == "running":
        raise RuntimeError(f"Job {args.job_id} is still running; wait for it before continuing the conversation")
    conversation_id = job.get("conversation_id")
    if not conversation_id:
        try:
            conversation_id = job_result(args.job_id).get("conversation_id")
        except RuntimeError:
            conversation_id = None
    if not conversation_id:
        raise RuntimeError(f"Job {args.job_id} has no recorded AGY conversation id")

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
    )
    return cmd_run(follow_up)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"agy-mc {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser("doctor", help="Check AGY and Mission Control runtime capabilities")
    doctor_parser.set_defaults(func=cmd_doctor)
    models_parser = subparsers.add_parser("models", help="List currently available AGY models as JSON")
    models_parser.set_defaults(func=cmd_models)
    usage_parser = subparsers.add_parser("usage", help="Show a sanitized AGY quota snapshot")
    usage_parser.add_argument("--watch", action="store_true", help="Refresh continuously until interrupted")
    usage_parser.add_argument("--interval", type=float, default=60.0, help="Watch refresh interval in seconds")
    usage_parser.add_argument("--count", type=int, help="Stop after N refreshes (useful for automation)")
    usage_parser.add_argument("--format", choices=["table", "json"], default="table")
    usage_parser.add_argument("--timeout-seconds", type=int, default=15)
    usage_parser.set_defaults(func=cmd_usage)
    workspace_parser = subparsers.add_parser("workspace", help="Check or grant exact AGY workspace trust")
    workspace_parser.add_argument("--cwd", required=True)
    workspace_parser.add_argument("--mode", choices=["plan", "accept-edits"], default="plan")
    workspace_parser.add_argument("--grant", action="store_true")
    workspace_parser.add_argument(
        "--roster-approved",
        action="store_true",
        help="Deprecated compatibility alias for --trust-approved",
    )
    workspace_parser.add_argument(
        "--trust-approved",
        action="store_true",
        help="Required with --grant; asserts separate user approval for this exact workspace trust mutation",
    )
    workspace_parser.set_defaults(func=cmd_workspace)
    select_parser = subparsers.add_parser("select", help="Select a model for a role")
    select_parser.add_argument("--strategy", choices=STRATEGY_PATTERNS, default="A")
    select_parser.add_argument("--role", choices=ROLES, required=True)
    select_parser.add_argument("--avoid-family", choices=["gemini", "claude", "gpt"])
    select_parser.set_defaults(func=cmd_select)
    run_parser = subparsers.add_parser("run", help="Run one bounded AGY worker")
    run_parser.add_argument("--strategy", choices=STRATEGY_PATTERNS, required=True)
    run_parser.add_argument("--role", choices=ROLES, required=True)
    run_parser.add_argument("--cwd", required=True)
    run_parser.add_argument("--prompt-file", required=True)
    run_parser.add_argument("--model")
    run_parser.add_argument(
        "--roster-approved",
        action="store_true",
        help="Assert that the user explicitly approved this role and exact model before execution",
    )
    run_parser.add_argument(
        "--allow-non-high-gemini",
        action="store_true",
        help="Use only after the user explicitly confirms a Gemini medium/low exception",
    )
    run_parser.add_argument(
        "--unrestricted",
        action="store_true",
        help="Use AGY's unrestricted permission profile; requires --unrestricted-approved",
    )
    run_parser.add_argument(
        "--unrestricted-approved",
        action="store_true",
        help="Assert the user's separate explicit approval for unrestricted AGY execution",
    )
    run_parser.add_argument("--mode", choices=["plan", "accept-edits"], default="plan")
    run_parser.add_argument("--conversation")
    run_parser.add_argument("--json-schema")
    run_parser.add_argument("--timeout-seconds", type=int, default=600)
    run_parser.add_argument(
        "--background",
        action="store_true",
        help="Queue a detached worker and return a job envelope; collect it with wait/result",
    )
    run_parser.set_defaults(func=cmd_run)

    status_parser = subparsers.add_parser("status", help="Show one job or list recent jobs")
    status_parser.add_argument("job_id", nargs="?")
    status_parser.set_defaults(func=cmd_status)

    result_parser = subparsers.add_parser("result", help="Print a completed job result")
    result_parser.add_argument("job_id")
    result_parser.set_defaults(func=cmd_result)

    wait_parser = subparsers.add_parser("wait", help="Wait for a job and print its result")
    wait_parser.add_argument("job_id")
    wait_parser.add_argument("--timeout", default="100s")
    wait_parser.add_argument("--timeout-seconds", dest="timeout_seconds_override", type=int)
    wait_parser.set_defaults(func=cmd_wait)

    cancel_parser = subparsers.add_parser("cancel", help="Cancel a running job")
    cancel_parser.add_argument("job_id")
    cancel_parser.set_defaults(func=cmd_cancel)

    continue_parser = subparsers.add_parser("continue", help="Continue a completed job's AGY conversation")
    continue_parser.add_argument("job_id")
    continue_parser.add_argument("--prompt-file", required=True)
    continue_parser.add_argument("--roster-approved", action="store_true")
    continue_parser.add_argument("--allow-non-high-gemini", action="store_true")
    continue_parser.add_argument("--unrestricted", action="store_true")
    continue_parser.add_argument("--unrestricted-approved", action="store_true")
    continue_parser.add_argument("--background", action="store_true")
    continue_parser.add_argument("--timeout-seconds", type=int, default=600)
    continue_parser.set_defaults(func=cmd_continue)

    worker_parser = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("job_id")
    worker_parser.set_defaults(func=cmd_worker)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "interval", 1) <= 0:
        parser.error("--interval must be positive")
    if getattr(args, "count", 1) is not None and getattr(args, "count", 1) <= 0:
        parser.error("--count must be positive")
    if getattr(args, "timeout_seconds", 1) < 1:
        parser.error("--timeout-seconds must be positive")
    try:
        return args.func(args)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
