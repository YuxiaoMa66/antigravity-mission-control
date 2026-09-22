"""Job storage, the workspace editor lock and background worker launch."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .common import STATE_ROOT, atomic_write_json, utc_now


LOCK_ROOT = STATE_ROOT / "locks"


JOB_ROOT = Path(
    os.environ.get(
        "AGY_MC_JOB_ROOT",
        os.environ.get("AGY_ORCHESTRATOR_JOB_ROOT", str(STATE_ROOT / "jobs")),
    )
).expanduser()


JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,127}$")


JOB_EXIT_CODES = {
    "done": 0,
    "done_with_warnings": 0,
    "starting": 2,
    "running": 2,
    "canceling": 2,
    "error": 3,
    "crashed": 3,
    "cancel_failed": 3,
    "canceled": 4,
}


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
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def job_lock(job_id: str):
    """Serialize one job's read-check-write updates across launcher, worker, cancel and refresh.

    Not reentrant: never call refresh_job or take this lock again while holding it.
    """
    fd = os.open(job_dir(job_id) / "job.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def write_terminal_result(job: dict, status: str, error: str) -> None:
    atomic_write_json(
        job_result_path(job["job_id"]),
        {
            "job_id": job["job_id"],
            "status": status,
            "exit_code": JOB_EXIT_CODES[status],
            "role": job.get("role"),
            "model": job.get("model"),
            "cwd": job.get("cwd"),
            "error": error,
        },
    )


def refresh_job(job: dict) -> dict:
    if job.get("status") not in {"starting", "running", "canceling"}:
        return job
    with job_lock(job["job_id"]):
        job = read_job(job["job_id"])
        status = job.get("status")
        if status not in {"starting", "running", "canceling"} or pid_alive(job.get("pid") or job.get("launcher_pid")):
            return job
        if job_result_path(job["job_id"]).is_file():
            try:
                result = json.loads(job_result_path(job["job_id"]).read_text(encoding="utf-8"))
                job["status"] = result.get("status", "error")
            except (OSError, json.JSONDecodeError):
                job["status"] = "crashed"
        elif status == "canceling":
            # The cancel command was interrupted, but the worker is gone: the cancel took effect.
            job["status"] = "canceled"
            write_terminal_result(job, "canceled", "Cancel requested and process exit confirmed on recovery")
        else:
            job["status"] = "crashed"
            write_terminal_result(job, "crashed", "Worker exited without writing a result" if status == "running"
                                  else "Launcher exited before the worker started")
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


def workspace_lock_path(cwd: Path) -> Path:
    canonical = str(cwd.expanduser().resolve())
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return LOCK_ROOT / f"{digest}.lock"


def acquire_workspace_lock(cwd: Path, owner: dict) -> tuple[int, Path]:
    """Atomically lock one canonical workspace for an editing process."""
    LOCK_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(LOCK_ROOT, 0o700)
    path = workspace_lock_path(cwd)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        active = active_edit_job(cwd)
        detail = f" job={active['job_id']}" if active else ""
        raise RuntimeError(f"Workspace already has an active editing lock: {cwd}.{detail}") from exc
    payload = {
        "schema": "agy-mc-workspace-lock.v1",
        "workspace": str(cwd.expanduser().resolve()),
        "acquired_at": utc_now(),
        **owner,
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, encoded)
    os.fsync(fd)
    os.chmod(path, 0o600)
    return fd, path


def release_workspace_lock(fd: int | None) -> None:
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def build_child_run_args(
    args: argparse.Namespace,
    prepared: dict,
    prompt_path: Path,
    schema_path: Path | None,
    approval_path: Path | None,
) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve().with_name("cli.py")),
        "run",
        "--strategy", args.strategy,
        "--role", args.role,
        "--cwd", str(prepared["cwd"]),
        "--prompt-file", str(prompt_path),
        "--model", prepared["model"],
        "--roster-approved",
        "--mode", args.mode,
        "--timeout-seconds", str(args.timeout_seconds),
        "--workspace-lock-held",
        "--evidence-dir", str(prompt_path.parent / "workspace-evidence"),
    ]
    if args.allow_non_high_gemini:
        command.append("--allow-non-high-gemini")
    if args.unrestricted:
        command.extend(["--unrestricted", "--unrestricted-approved"])
    if args.conversation:
        command.extend(["--conversation", args.conversation])
    if schema_path:
        command.extend(["--json-schema", str(schema_path)])
    if approval_path:
        command.extend(["--approval-file", str(approval_path)])
    return command


def start_background_job(args: argparse.Namespace, prepared: dict) -> int:
    JOB_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(JOB_ROOT, 0o700)
    job_id = f"{args.role}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    lock_fd = None
    lock_path = None
    if args.mode == "accept-edits":
        lock_fd, lock_path = acquire_workspace_lock(
            prepared["cwd"],
            {"kind": "background", "pid": os.getpid(), "job_id": job_id, "role": args.role},
        )
    try:
        result = launch_background_job(args, prepared, job_id, lock_fd, lock_path)
        if lock_fd is not None:
            # The worker inherited the same open file description. Closing only
            # this duplicate transfers lock lifetime to the worker process;
            # calling LOCK_UN here would release the worker's lock as well.
            os.close(lock_fd)
            lock_fd = None
        return result
    finally:
        release_workspace_lock(lock_fd)


def launch_background_job(
    args: argparse.Namespace,
    prepared: dict,
    job_id: str,
    lock_fd: int | None,
    lock_path: Path | None,
) -> int:
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

    approval_path = None
    if prepared.get("approval_path"):
        approval_path = directory / "approval.json"
        approval_path.write_text(prepared["approval_path"].read_text(encoding="utf-8"), encoding="utf-8")
        os.chmod(approval_path, 0o600)

    command = build_child_run_args(args, prepared, prompt_path, schema_path, approval_path)
    job = {
        "job_id": job_id,
        "status": "starting",
        "role": args.role,
        "strategy": args.strategy,
        "model": prepared["model"],
        "cwd": str(prepared["cwd"]),
        "mode": args.mode,
        "conversation_id": args.conversation,
        "pid": None,
        "launcher_pid": os.getpid(),
        "started_at": utc_now(),
        "result_path": str(job_result_path(job_id)),
        "log_path": str(directory / "worker.log"),
        "workspace_lock": str(lock_path) if lock_path else None,
        "evidence_path": str(directory / "workspace-evidence"),
        "approval_id": prepared.get("approval_id"),
        "policy": prepared.get("policy"),
        "correction_of": prepared.get("correction_of"),
        "follow_up_of": prepared.get("follow_up_of"),
        "correction_round": prepared.get("correction_round"),
        "permission_profile": "unrestricted" if args.unrestricted else "standard",
    }
    atomic_write_json(job_spec_path(job_id), {"command": command})
    write_job(job)

    log_fd = os.open(job["log_path"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(log_fd, "a", encoding="utf-8") as log_handle:
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve().with_name("cli.py")), "_worker", job_id],
            cwd=str(prepared["cwd"]),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            pass_fds=(lock_fd,) if lock_fd is not None else (),
        )
    with job_lock(job_id):
        current = read_job(job_id)
        launched = current.get("status") == "starting"
        if launched:
            current["pid"] = child.pid
            current["status"] = "running"
            write_job(current)
    if not launched:
        # Canceled during launch: the job never recorded this worker, so stop it here.
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
        print(json.dumps(current, ensure_ascii=False, indent=2))
        return JOB_EXIT_CODES.get(current.get("status"), 1)

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
                "evidence_path": job["evidence_path"],
                "collect": f"agy-mc wait {job_id} --timeout 300s",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


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
