"""Workspace trust settings and before/after change evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .common import utc_now


SETTINGS_PATH = Path(
    os.environ.get(
        "AGY_MC_SETTINGS_PATH",
        str(Path.home() / ".gemini" / "antigravity-cli" / "settings.json"),
    )
).expanduser()


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
    home = Path.home().resolve()
    broad = {home, *home.parents, Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve()}
    if workspace == Path(workspace.anchor) or workspace in broad:
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


def workspace_snapshot(cwd: Path) -> dict:
    """Read Git evidence without hooks, external diffs, textconv or index refresh."""
    deadline = time.monotonic() + 10

    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=cwd,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
                              capture_output=True, timeout=max(0.01, deadline - time.monotonic()), check=False)

    snapshot = {"schema": "agy-mc-workspace.v1", "captured_at": utc_now(),
                "cwd": str(cwd), "status": "unknown", "limitations": []}
    try:
        root = git("rev-parse", "--show-toplevel")
        if root.returncode:
            snapshot["limitations"].append("Git repository unavailable; no Git baseline")
            return snapshot
        repo = Path(os.fsdecode(root.stdout).strip())
        snapshot["repository"] = str(repo)
        head = git("rev-parse", "--verify", "HEAD")
        snapshot["head"] = head.stdout.decode().strip() if head.returncode == 0 else None
        status = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", ".")
        if status.returncode:
            snapshot["limitations"].append("git status failed")
            return snapshot
        entries = status.stdout.split(b"\0")
        paths = {}
        budget = 64 * 1024 * 1024
        index = 0
        while index < len(entries) and entries[index]:
            if time.monotonic() >= deadline:
                snapshot["limitations"].append("Snapshot time budget reached")
                break
            entry = entries[index]
            code, raw_path = entry[:2].decode("ascii"), entry[3:]
            name = os.fsdecode(raw_path)
            detail = {"status": code}
            index += 1
            if "R" in code or "C" in code:
                detail["original_path"] = os.fsdecode(entries[index])
                index += 1
            if len(paths) >= 5000:
                snapshot["limitations"].append("Path fingerprint limit reached (5000)")
                break
            path = repo / name
            try:
                if path.is_symlink():
                    detail["sha256"] = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
                    detail["kind"] = "symlink"
                elif path.is_file():
                    size = path.stat().st_size
                    if size > min(budget, 8 * 1024 * 1024):
                        detail["fingerprint"] = "skipped: file or total byte limit"
                        snapshot["limitations"].append(f"Fingerprint unavailable: {name}")
                    else:
                        # Bound the read even if a concurrently written file grows.
                        with path.open("rb") as handle:
                            data = handle.read(min(budget, 8 * 1024 * 1024) + 1)
                        if len(data) > min(budget, 8 * 1024 * 1024):
                            detail["fingerprint"] = "skipped: file grew beyond limit"
                            snapshot["limitations"].append(f"Fingerprint unavailable: {name}")
                        else:
                            budget -= len(data)
                            detail["sha256"] = hashlib.sha256(data).hexdigest()
                            detail["kind"] = "file"
                elif path.exists():
                    detail["kind"] = "directory or submodule; no content fingerprint"
                    snapshot["limitations"].append(f"Directory contents not fingerprinted: {name}")
                else:
                    detail["kind"] = "missing"
            except OSError:
                detail["fingerprint"] = "unavailable"
                snapshot["limitations"].append(f"Fingerprint unavailable: {name}")
            paths[name] = detail
        snapshot["paths"] = paths
        snapshot["status_sha256"] = hashlib.sha256(status.stdout).hexdigest()
        for label, flags in (("unstaged", []), ("staged", ["--cached"])):
            diff = git("diff", "--no-ext-diff", "--no-textconv", "--binary", *flags, "--", ".")
            snapshot[f"{label}_diff_sha256"] = hashlib.sha256(diff.stdout).hexdigest() if not diff.returncode else None
            if diff.returncode:
                snapshot["limitations"].append(f"{label} diff unavailable")
        snapshot["status"] = "partial" if snapshot["limitations"] else "ok"
    except (OSError, subprocess.SubprocessError) as exc:
        snapshot["limitations"].append(type(exc).__name__)
    return snapshot


def workspace_delta(before: dict, after: dict) -> dict:
    old, new = before.get("paths", {}), after.get("paths", {})
    return {"changed_paths": sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name)),
            "head_changed": before.get("head") != after.get("head"),
            "staged_diff_changed": before.get("staged_diff_sha256") != after.get("staged_diff_sha256"),
            "unstaged_diff_changed": before.get("unstaged_diff_sha256") != after.get("unstaged_diff_sha256"),
            "limitations": before.get("limitations", []) + after.get("limitations", []),
            "acceptance": "not_evaluated"}
