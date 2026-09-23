"""Shared constants and small helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from . import __version__

VERSION = __version__


def parse_duration(text: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", text)
    if not match:
        raise ValueError(f"Invalid duration: {text!r}")
    multiplier = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return float(match.group(1)) * multiplier


AGY_BIN = os.environ.get("AGY_MC_BIN", os.environ.get("AGY_ORCHESTRATOR_BIN", "agy"))


STATE_ROOT = Path(
    os.environ.get(
        "AGY_MC_STATE_ROOT",
        str(Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "antigravity-mission-control"),
    )
).expanduser()


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


def atomic_write_json(path: Path, payload: dict, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
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


def command_data(payload: dict) -> dict:
    data = payload.get("command", {}).get("data")
    if not isinstance(data, dict):
        data = payload.get("response", {}).get("command", {}).get("data")
    return data if isinstance(data, dict) else {}
