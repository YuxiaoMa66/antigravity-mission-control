"""Antigravity Mission Control: bounded AGY orchestration and quota telemetry."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Background workers re-run this file by path; make the relative imports below resolve.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "antigravity_mission_control"

from .approvals import POLICY_NAMES, canonical_policy_name, cmd_approve, cmd_policy
from .common import AGY_BIN, STATE_ROOT, VERSION, command_data, run_capture
from .jobs import cmd_cancel, cmd_continue, cmd_result, cmd_run, cmd_status, cmd_wait, cmd_worker
from .jobstore import JOB_EXIT_CODES
from .routing import ROLES, STRATEGY_PATTERNS, cmd_models, cmd_select
from .skill import HOSTS, cmd_skill, default_skill_target, skill_marker
from .usage import cmd_usage
from .workspace import cmd_workspace


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
            models = command_data(payload).get("models", [])
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
    for host in HOSTS:
        marker = skill_marker(default_skill_target(host))
        if marker and marker.get("version") != VERSION:
            checks.append({"name": f"skill-{host}", "ok": True, "warning": f"installed skill {marker.get('version')} != CLI {VERSION}; run `agy-mc skill update --host {host}`"})
    result = {"schema": "agy-mc-doctor.v1", "version": VERSION, "status": "ok" if all(c["ok"] for c in checks) else "error", "checks": checks}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"agy-mc {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    policy_parser = subparsers.add_parser("policy", help="Show the effective bundled policy and enforcement limits")
    policy_parser.add_argument("name", type=canonical_policy_name, choices=POLICY_NAMES, nargs="?", default="strict")
    policy_parser.set_defaults(func=cmd_policy)
    doctor_parser = subparsers.add_parser("doctor", help="Check AGY, authenticated model access, and Mission Control runtime capabilities")
    doctor_parser.set_defaults(func=cmd_doctor)
    skill_parser = subparsers.add_parser("skill", help="Install, update, inspect, or uninstall the bundled skill for Codex and/or Claude Code")
    skill_parser.add_argument("action", choices=["install", "update", "status", "uninstall"])
    skill_parser.add_argument("--host", choices=["auto", "codex", "claude", "all"], default="auto",
                              help="Agent host to install for; auto detects installed hosts")
    skill_parser.add_argument("--target", help="Override the exact skill directory (single host)")
    skill_parser.add_argument("--force", action="store_true", help="Back up and replace an unmanaged existing target")
    skill_parser.add_argument("--dry-run", action="store_true")
    skill_parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    skill_parser.add_argument("--lang", choices=["auto", "en", "zh"], default="auto")
    skill_parser.set_defaults(func=cmd_skill)
    models_parser = subparsers.add_parser("models", help="List currently available AGY models as JSON")
    models_parser.set_defaults(func=cmd_models)
    approve_parser = subparsers.add_parser("approve", help="Create a signed, expiring approval manifest")
    approve_parser.add_argument("--policy", type=canonical_policy_name, choices=POLICY_NAMES, default="strict")
    approve_parser.add_argument("--three-rosters-presented", action="store_true",
                                help="Assert A/B/C proposals were presented; root strict approvals only")
    approve_parser.add_argument("--follow-up-of", help="Parent completed job; preserve scope and correction count")
    approve_parser.add_argument("--correction-of", help="Parent completed job; inherit its correction count")
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
    run_parser.add_argument("--evidence-dir", help=argparse.SUPPRESS)
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
    status_parser.add_argument("--limit", type=positive_int, help="Show only the N most recently started jobs")
    status_parser.add_argument("--state", action="append", choices=tuple(JOB_EXIT_CODES),
                               help="Keep jobs in this state (may be repeated)")
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


def positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "status" and args.job_id and (args.limit is not None or args.state):
        parser.error("status filters cannot be used with a job_id")
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
