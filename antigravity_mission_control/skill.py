"""Skill installation for Codex and Claude Code hosts."""

from __future__ import annotations

import argparse
from datetime import datetime
from importlib import resources
import json
import os
import shutil
import uuid
from pathlib import Path

from .common import VERSION, atomic_write_json, utc_now


HOSTS = {"codex": ("CODEX_HOME", ".codex"), "claude": ("CLAUDE_CONFIG_DIR", ".claude")}


def host_home(host: str) -> Path:
    env, default = HOSTS[host]
    return Path(os.environ.get(env) or Path.home() / default).expanduser()


def default_skill_target(host: str = "codex") -> Path:
    return host_home(host) / "skills" / "antigravity-mission-control"


def skill_backup_path(host: str = "codex") -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return host_home(host) / "skill-backups" / f"antigravity-mission-control-{stamp}"


def resolve_skill_hosts(args: argparse.Namespace) -> list[str]:
    if args.host in HOSTS:
        hosts = [args.host]
    elif args.host == "all":
        hosts = list(HOSTS)
    elif args.target:
        hosts = ["codex"]
    elif args.action == "status":
        hosts = list(HOSTS)
    elif args.action == "install":
        hosts = [h for h in HOSTS if host_home(h).is_dir()]
    else:
        hosts = [h for h in HOSTS if skill_marker(default_skill_target(h))]
    if not hosts:
        raise RuntimeError("No supported host detected; pass --host codex|claude")
    if args.target and len(hosts) > 1:
        raise RuntimeError("--target names one directory; pass a single --host")
    return hosts


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
    lines = [f"╭{border}╮", "│  ANTIGRAVITY MISSION CONTROL / Route / Guard / Verify       │", f"╰{border}╯", "", f"  ✓ {title}"]
    if payload.get("target"):
        label = "目标" if zh else "Target"
        lines.extend([f"  ◇ {label}", f"    {payload['target']}"])
    if payload.get("backup"):
        label = "备份" if zh else "Backup"
        lines.extend([f"  ↪ {label}", f"    {payload['backup']}"])
    if payload.get("host"):
        lines.extend(["  ◇ Host", f"    {payload['host']}"])
    if payload.get("version"):
        lines.extend(["  ◇ Version", f"    {payload['version']}"])
    return "\n".join(lines)


def emit_skill_results(payloads: list[dict], args: argparse.Namespace) -> None:
    if args.format == "json":
        body = payloads[0] if len(payloads) == 1 else {"schema": "agy-mc-skill-operations.v1", "results": payloads}
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return
    language = args.lang
    if language == "auto":
        language = "zh" if any(token in os.environ.get("LANG", "").lower() for token in ("zh", "cn")) else "en"
    for payload in payloads:
        print(render_skill_result(payload, language))


def cmd_skill(args: argparse.Namespace) -> int:
    results = [skill_operation(args, host) for host in resolve_skill_hosts(args)]
    emit_skill_results([payload for payload, _ in results], args)
    return min(code for _, code in results)


def skill_operation(args: argparse.Namespace, host: str) -> tuple[dict, int]:
    requested = Path(args.target).expanduser().absolute() if args.target else default_skill_target(host).absolute()
    if requested.is_symlink():
        raise RuntimeError(f"Refusing a symlink Skill target: {requested}")
    target = requested.parent.resolve() / requested.name
    if target == Path.home().resolve() or target == Path(target.anchor):
        raise RuntimeError(f"Refusing broad skill target: {target}")
    marker = skill_marker(target)
    if args.action == "status":
        status = "present" if target.is_dir() else "missing"
        payload = {"schema": "agy-mc-skill-operation.v1", "host": host, "status": status, "target": str(target), "version": (marker or {}).get("version")}
        return payload, 0 if status == "present" else 1

    if args.action == "uninstall":
        if not target.is_dir():
            raise RuntimeError(f"Skill is not installed: {target}")
        backup = skill_backup_path(host)
        payload = {"schema": "agy-mc-skill-operation.v1", "host": host, "status": "dry-run" if args.dry_run else "uninstalled", "target": str(target), "backup": str(backup), "version": (marker or {}).get("version")}
        if not args.dry_run:
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.replace(target, backup)
        return payload, 0

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
    backup = skill_backup_path(host) if exists else None
    payload = {"schema": "agy-mc-skill-operation.v1", "host": host, "status": "dry-run" if args.dry_run else status, "target": str(target), "backup": str(backup) if backup else None, "version": VERSION}
    if args.dry_run:
        return payload, 0

    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = target.parent / f".{target.name}.staging-{uuid.uuid4().hex[:8]}"
    bundle = resources.files("antigravity_mission_control").joinpath("skill_bundle")
    with resources.as_file(bundle) as bundle_path:
        # agents/ holds Codex-only interface metadata
        skip = ("__pycache__", "*.py[co]") if host == "codex" else ("__pycache__", "*.py[co]", "agents")
        shutil.copytree(bundle_path, staging, ignore=shutil.ignore_patterns(*skip))
    atomic_write_json(
        staging / ".agy-mc-install.json",
        {"schema": "agy-mc-skill-install.v1", "version": VERSION, "host": host, "installed_at": utc_now(), "source": "python-package"},
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
    return payload, 0
