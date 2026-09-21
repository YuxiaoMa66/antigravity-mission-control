"""Quota telemetry."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from .common import AGY_BIN, command_data, run_capture, utc_now


def normalize_usage(payload: dict) -> dict:
    """Return a stable, account-free view of AGY's evolving /usage response."""
    data = command_data(payload)
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


def usage_error(message: str) -> tuple[dict, int]:
    return {"schema": "agy-mc-usage.v1", "status": "error", "source": "agy-cli:/usage",
            "fetched_at": utc_now(), "groups": None, "errors": [message]}, 1


def fetch_usage(timeout_seconds: int = 15) -> tuple[dict, int]:
    try:
        proc = run_capture([AGY_BIN, "-p", "/usage", "--output-format", "json"], timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        return usage_error(f"agy /usage timed out after {timeout_seconds}s")
    if proc.returncode != 0:
        return usage_error(f"agy /usage failed with exit code {proc.returncode}")
    try:
        payload = json.loads(proc.stdout)
        if not isinstance(payload, dict):
            raise ValueError("top-level value is not an object")
        return normalize_usage(payload), 0
    except (json.JSONDecodeError, ValueError, RuntimeError) as exc:
        return usage_error(f"cannot parse agy /usage: {exc}")


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
