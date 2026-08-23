#!/usr/bin/env python3
"""Antigravity Mission Control: bounded AGY orchestration and quota telemetry."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import hmac
from importlib import resources
import json
import os
import re
import secrets
import signal
import shutil
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
VERSION = "0.1.0a2"
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
LOCK_ROOT = STATE_ROOT / "locks"
APPROVAL_ROOT = STATE_ROOT / "approvals"
APPROVAL_KEY_PATH = STATE_ROOT / "approval.key"
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


def atomic_write_private_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.write(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def approval_key(create: bool = False) -> bytes:
    if APPROVAL_KEY_PATH.is_file():
        key = APPROVAL_KEY_PATH.read_bytes()
        if len(key) != 32:
            raise RuntimeError(f"Approval key is invalid: {APPROVAL_KEY_PATH}")
        return key
    if not create:
        raise RuntimeError("Approval key is missing; create a new approval manifest on this machine")
    key = secrets.token_bytes(32)
    atomic_write_private_bytes(APPROVAL_KEY_PATH, key)
    return key


def approval_signature(payload: dict, key: bytes) -> str:
    unsigned = {name: value for name, value in payload.items() if name != "signature"}
    encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key, encoded, hashlib.sha256).hexdigest()


def load_approval(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Approval manifest does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Approval manifest is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "agy-mc-approval.v1":
        raise RuntimeError(f"Unsupported approval manifest: {path}")
    signature = payload.get("signature")
    expected = approval_signature(payload, approval_key(create=False))
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise RuntimeError("Approval manifest signature does not match this machine or its contents")
    try:
        expires_at = datetime.fromisoformat(str(payload["expires_at"]))
    except (KeyError, ValueError) as exc:
        raise RuntimeError("Approval manifest has an invalid expiration") from exc
    if expires_at.tzinfo is None or datetime.now(timezone.utc) >= expires_at.astimezone(timezone.utc):
        raise RuntimeError(f"Approval manifest expired at {payload.get('expires_at')}")
    return payload


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
    lines = [
        "╭────────────────────────────────────────────────────────────────────────────────╮",
        "│  ANTIGRAVITY MISSION CONTROL · LIVE QUOTA                                       │",
        "╰────────────────────────────────────────────────────────────────────────────────╯",
        f"Fetched {snapshot['fetched_at']} · status={snapshot['status']}",
        "",
    ]
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
    session = run_capture([AGY_BIN, "--output-format", "json", "models"], timeout=30)
    session_ok = False
    model_count = 0
    if session.returncode == 0:
        try:
            payload = json.loads(session.stdout)
            models = _command_data(payload).get("models", [])
            session_ok = isinstance(models, list) and bool(models)
            model_count = len(models) if isinstance(models, list) else 0
        except (json.JSONDecodeError, TypeError):
            pass
    checks.append(
        {
            "name": "agy-session",
            "ok": session_ok,
            "detail": f"authenticated model catalog: {model_count} models" if session_ok else "run `agy` and complete Google sign-in",
        }
    )
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


def default_skill_target() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    return codex_home / "skills" / "antigravity-mission-control"


def skill_backup_path(target: Path) -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return codex_home / "skill-backups" / f"antigravity-mission-control-{stamp}"


def skill_marker(target: Path) -> dict | None:
    marker = target / ".agy-mc-install.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def render_skill_result(payload: dict, language: str) -> str:
    zh = language == "zh"
    labels = {
        "installed": ("安装完成", "Installed"),
        "updated": ("更新完成", "Updated"),
        "uninstalled": ("已卸载并保留备份", "Uninstalled with recoverable backup"),
        "present": ("已安装", "Installed"),
        "missing": ("未安装", "Not installed"),
        "dry-run": ("预演完成，未修改文件", "Dry run complete; no files changed"),
    }
    title = labels.get(payload["status"], (payload["status"], payload["status"]))[0 if zh else 1]
    border = "─" * 60
    lines = [f"╭{border}╮", "│  ANTIGRAVITY MISSION CONTROL · Route · Guard · Verify       │", f"╰{border}╯", "", f"  ✓ {title}"]
    if payload.get("target"):
        label = "目标" if zh else "Target"
        lines.extend([f"  ◇ {label}", f"    {payload['target']}"])
    if payload.get("backup"):
        label = "备份" if zh else "Backup"
        lines.extend([f"  ↪ {label}", f"    {payload['backup']}"])
    if payload.get("version"):
        lines.extend(["  ◇ Version", f"    {payload['version']}"])
    return "\n".join(lines)


def emit_skill_result(payload: dict, args: argparse.Namespace) -> None:
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    language = args.lang
    if language == "auto":
        language = "zh" if any(token in os.environ.get("LANG", "").lower() for token in ("zh", "cn")) else "en"
    print(render_skill_result(payload, language))


def cmd_skill(args: argparse.Namespace) -> int:
    requested = Path(args.target).expanduser().absolute() if args.target else default_skill_target().absolute()
    if requested.is_symlink():
        raise RuntimeError(f"Refusing a symlink Skill target: {requested}")
    target = requested.parent.resolve() / requested.name
    if target == Path.home().resolve() or target == Path(target.anchor):
        raise RuntimeError(f"Refusing broad skill target: {target}")
    marker = skill_marker(target)
    if args.action == "status":
        status = "present" if target.is_dir() else "missing"
        payload = {"schema": "agy-mc-skill-operation.v1", "status": status, "target": str(target), "version": (marker or {}).get("version")}
        emit_skill_result(payload, args)
        return 0 if status == "present" else 1

    if args.action == "uninstall":
        if not target.is_dir():
            raise RuntimeError(f"Skill is not installed: {target}")
        backup = skill_backup_path(target)
        payload = {"schema": "agy-mc-skill-operation.v1", "status": "dry-run" if args.dry_run else "uninstalled", "target": str(target), "backup": str(backup), "version": (marker or {}).get("version")}
        if not args.dry_run:
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(target, backup)
        emit_skill_result(payload, args)
        return 0

    exists = target.exists()
    if args.action == "install" and exists and not args.force:
        raise RuntimeError(f"Skill target already exists: {target}; use update or install --force")
    if args.action == "update" and not exists:
        raise RuntimeError(f"Skill is not installed: {target}; use install")
    if exists and not target.is_dir():
        raise RuntimeError(f"Skill target is not a directory: {target}")
    if exists and marker is None and not args.force:
        raise RuntimeError(f"Existing skill is not managed by agy-mc: {target}; use --force only after inspection")

    status = "installed" if args.action == "install" else "updated"
    backup = skill_backup_path(target) if exists else None
    payload = {"schema": "agy-mc-skill-operation.v1", "status": "dry-run" if args.dry_run else status, "target": str(target), "backup": str(backup) if backup else None, "version": VERSION}
    if args.dry_run:
        emit_skill_result(payload, args)
        return 0

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex[:8]}"
    bundle = resources.files("antigravity_mission_control").joinpath("skill_bundle")
    with resources.as_file(bundle) as bundle_path:
        shutil.copytree(bundle_path, staging)
    atomic_write_json(
        staging / ".agy-mc-install.json",
        {"schema": "agy-mc-skill-install.v1", "version": VERSION, "installed_at": utc_now(), "source": "python-package"},
    )
    try:
        if exists:
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(target, backup)
        os.replace(staging, target)
    except Exception:
        if backup and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    emit_skill_result(payload, args)
    return 0


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


def cmd_approve(args: argparse.Namespace) -> int:
    if not args.confirmed:
        raise RuntimeError("Creating an approval manifest requires --confirmed after explicit user confirmation")
    if args.expires_minutes < 1 or args.expires_minutes > 1440:
        raise RuntimeError("--expires-minutes must be between 1 and 1440")
    if args.permission_profile == "unrestricted" and not args.unrestricted_confirmed:
        raise RuntimeError("Unrestricted approval requires separate confirmation and --unrestricted-confirmed")
    if args.unrestricted_confirmed and args.permission_profile != "unrestricted":
        raise RuntimeError("--unrestricted-confirmed requires --permission-profile unrestricted")

    cwd = canonical_workspace(args.cwd)
    prompt_path = Path(args.prompt_file).expanduser().resolve()
    if not prompt_path.is_file():
        raise RuntimeError(f"Prompt file does not exist: {prompt_path}")
    prompt_text = prompt_path.read_text(encoding="utf-8")
    models = available_models()
    model_ids = {model["id"] for model in models}
    if args.model not in model_ids:
        raise RuntimeError(f"Requested model is unavailable: {args.model}")
    if args.strategy == "C":
        required_model = select_model(args.role, models, strategy="C")
        if args.model != required_model:
            raise RuntimeError(f"Strategy C requires {required_model}; got {args.model}")
    allow_non_high = bool(args.non_high_gemini_confirmed)
    if is_non_high_gemini(args.model) and not allow_non_high:
        raise RuntimeError("A Gemini medium/low approval requires --non-high-gemini-confirmed")

    created = datetime.now(timezone.utc)
    approval_id = f"approval-{created.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    payload = {
        "schema": "agy-mc-approval.v1",
        "approval_id": approval_id,
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(minutes=args.expires_minutes)).isoformat(),
        "strategy": args.strategy,
        "role": args.role,
        "model": args.model,
        "cwd": str(cwd),
        "prompt_sha256": sha256_text(prompt_text),
        "mode": args.mode,
        "permission_profile": args.permission_profile,
        "allow_non_high_gemini": allow_non_high,
        "conversation": args.conversation,
    }
    payload["signature"] = approval_signature(payload, approval_key(create=True))
    if args.output:
        output = Path(args.output).expanduser().resolve()
    else:
        APPROVAL_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(APPROVAL_ROOT, 0o700)
        output = APPROVAL_ROOT / f"{approval_id}.json"
    atomic_write_json(output, payload)
    print(
        json.dumps(
            {
                "schema": "agy-mc-approval-created.v1",
                "status": "created",
                "approval_id": approval_id,
                "approval_file": str(output),
                "expires_at": payload["expires_at"],
                "binding": {
                    "strategy": args.strategy,
                    "role": args.role,
                    "model": args.model,
                    "cwd": str(cwd),
                    "prompt_sha256": payload["prompt_sha256"],
                    "mode": args.mode,
                    "permission_profile": args.permission_profile,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def validate_approval_binding(args: argparse.Namespace, cwd: Path, prompt_text: str) -> dict | None:
    raw_path = getattr(args, "approval_file", None)
    if not raw_path:
        return None
    path = Path(raw_path).expanduser().resolve()
    approval = load_approval(path)
    expected = {
        "strategy": args.strategy,
        "role": args.role,
        "model": args.model,
        "cwd": str(cwd),
        "prompt_sha256": sha256_text(prompt_text),
        "mode": args.mode,
        "permission_profile": "unrestricted" if args.unrestricted else "standard",
        "conversation": getattr(args, "conversation", None),
    }
    mismatches = [name for name, value in expected.items() if approval.get(name) != value]
    if mismatches:
        raise RuntimeError("Approval manifest does not match this run: " + ", ".join(mismatches))
    return approval


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
        "trust_added": False,
        "approval_path": Path(args.approval_file).expanduser().resolve() if has_manifest else None,
        "approval_id": approval.get("approval_id") if approval else None,
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


def build_child_run_args(
    args: argparse.Namespace,
    prepared: dict,
    prompt_path: Path,
    schema_path: Path | None,
    approval_path: Path | None,
) -> list[str]:
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
        "--workspace-lock-held",
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
        "started_at": utc_now(),
        "result_path": str(job_result_path(job_id)),
        "log_path": str(directory / "worker.log"),
        "workspace_lock": str(lock_path) if lock_path else None,
        "approval_id": prepared.get("approval_id"),
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
            pass_fds=(lock_fd,) if lock_fd is not None else (),
        )
    current = read_job(job_id)
    current["pid"] = child.pid
    current["status"] = "running"
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
        current = read_job(args.job_id)
        if current.get("status") not in {"canceled", "canceling"}:
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
    terminated = terminate_process_group(pid, args.grace_seconds)
    final_status = "canceled" if terminated else "cancel_failed"
    job["status"] = final_status
    job["finished_at"] = utc_now()
    write_job(job)
    atomic_write_json(
        job_result_path(args.job_id),
        {
            "job_id": args.job_id,
            "status": final_status,
            "exit_code": JOB_EXIT_CODES[final_status],
            "role": job.get("role"),
            "model": job.get("model"),
            "cwd": job.get("cwd"),
            "error": "Job canceled and process exit confirmed" if terminated else "Process did not exit after TERM and KILL",
        },
    )
    print(json.dumps(job, ensure_ascii=False, indent=2))
    return JOB_EXIT_CODES[final_status]


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"agy-mc {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser("doctor", help="Check AGY, authenticated model access, and Mission Control runtime capabilities")
    doctor_parser.set_defaults(func=cmd_doctor)
    skill_parser = subparsers.add_parser("skill", help="Install, update, inspect, or uninstall the bundled Codex skill")
    skill_parser.add_argument("action", choices=["install", "update", "status", "uninstall"])
    skill_parser.add_argument("--target", help="Override the exact Codex skill directory")
    skill_parser.add_argument("--force", action="store_true", help="Back up and replace an unmanaged existing target")
    skill_parser.add_argument("--dry-run", action="store_true")
    skill_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    skill_parser.add_argument("--lang", choices=["auto", "en", "zh"], default="auto")
    skill_parser.set_defaults(func=cmd_skill)
    models_parser = subparsers.add_parser("models", help="List currently available AGY models as JSON")
    models_parser.set_defaults(func=cmd_models)
    approve_parser = subparsers.add_parser("approve", help="Create a signed, expiring approval manifest")
    approve_parser.add_argument("--strategy", choices=STRATEGY_PATTERNS, required=True)
    approve_parser.add_argument("--role", choices=ROLES, required=True)
    approve_parser.add_argument("--model", required=True)
    approve_parser.add_argument("--cwd", required=True)
    approve_parser.add_argument("--prompt-file", required=True)
    approve_parser.add_argument("--mode", choices=["plan", "accept-edits"], default="plan")
    approve_parser.add_argument("--permission-profile", choices=["standard", "unrestricted"], default="standard")
    approve_parser.add_argument("--conversation")
    approve_parser.add_argument("--expires-minutes", type=int, default=60)
    approve_parser.add_argument("--output")
    approve_parser.add_argument("--confirmed", action="store_true")
    approve_parser.add_argument("--unrestricted-confirmed", action="store_true")
    approve_parser.add_argument("--non-high-gemini-confirmed", action="store_true")
    approve_parser.set_defaults(func=cmd_approve)
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
    run_parser.add_argument("--approval-file", help="Signed approval manifest created by the approve command")
    run_parser.add_argument(
        "--roster-approved",
        action="store_true",
        help="Assert that the user explicitly approved this role and exact model before execution",
    )
    run_parser.add_argument("--workspace-lock-held", action="store_true", help=argparse.SUPPRESS)
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
    cancel_parser.add_argument("--grace-seconds", type=float, default=5.0)
    cancel_parser.set_defaults(func=cmd_cancel)

    continue_parser = subparsers.add_parser("continue", help="Continue a completed job's AGY conversation")
    continue_parser.add_argument("job_id")
    continue_parser.add_argument("--prompt-file", required=True)
    continue_parser.add_argument("--approval-file")
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
    if getattr(args, "grace_seconds", 1) <= 0:
        parser.error("--grace-seconds must be positive")
    try:
        return args.func(args)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
