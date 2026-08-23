#!/usr/bin/env python3
"""Render faithful, sanitized CLI captures as dependency-free SVG assets."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "interfaces"


@dataclass(frozen=True)
class Line:
    text: str
    tone: str = "text"


@dataclass(frozen=True)
class Screen:
    filename: str
    title: str
    description: str
    tab: str
    lines: tuple[Line, ...]


SCREENS = (
    Screen(
        filename="guided-install.svg",
        title="Guided installation",
        description="Mission Control installation with exact targets shown before changes.",
        tab="install",
        lines=(
            Line("$ npx antigravity-mission-control@next install", "prompt"),
            Line(""),
            Line("ANTIGRAVITY MISSION CONTROL  v0.1.0-alpha.3", "heading"),
            Line("Route / Guard / Verify", "muted"),
            Line(""),
            Line("◆ Install", "accent"),
            Line("  Skill target     ~/.codex/skills/antigravity-mission-control"),
            Line("  Managed runtime  ~/.local/share/antigravity-mission-control/"),
            Line("                   venv"),
            Line("  Package source   github.com/YuxiaoMa66/...@v0.1.0a3", "muted"),
            Line(""),
            Line("✓ Python  python3 3.13.9", "success"),
            Line("✓ AGY     1.1.19", "success"),
            Line("? Continue with these exact changes?  y", "prompt"),
            Line("✓ Installed  /  recoverable backup enabled", "success"),
            Line("✓ Mission accomplished", "success"),
        ),
    ),
    Screen(
        filename="live-quota.svg",
        title="Live quota telemetry",
        description="Sanitized example of the live quota table, including windows and reset state.",
        tab="usage --watch",
        lines=(
            Line("$ agy-mc usage --watch --interval 60", "prompt"),
            Line(""),
            Line("ANTIGRAVITY MISSION CONTROL / LIVE QUOTA", "heading"),
            Line("SANITIZED SAMPLE  status=ok", "muted"),
            Line(""),
            Line("GROUP                    WINDOW       REMAINING   RESET / STATE", "muted"),
            Line("──────────────────────────────────────────────────────────────", "dim"),
            Line("Gemini Models            weekly           62.50%   Tue 08:25", "accent"),
            Line("                         5h              100.00%   02:05"),
            Line(""),
            Line("Claude and GPT models    weekly           35.86%   Tue 20:47", "accent"),
            Line("                         5h              100.00%   02:05"),
            Line(""),
            Line("↻ refreshing every 60 seconds  /  Ctrl+C to stop", "muted"),
            Line("Account identity and OAuth material are excluded.", "success"),
        ),
    ),
    Screen(
        filename="bound-approval.svg",
        title="Bound approval",
        description="A signed approval manifest binding model, role, workspace, prompt and expiry.",
        tab="approve",
        lines=(
            Line("$ agy-mc approve --strategy A --role implementer \\", "prompt"),
            Line("    --model gemini-3.7-flash-high --mode accept-edits \\", "prompt"),
            Line("    --cwd ~/Projects/app --prompt-file /private/task.txt \\", "prompt"),
            Line("    --expires-minutes 60 --confirmed", "prompt"),
            Line(""),
            Line("{", "muted"),
            Line('  "schema": "agy-mc-approval.v1",'),
            Line('  "strategy": "A",'),
            Line('  "role": "implementer",'),
            Line('  "model": "gemini-3.7-flash-high",', "accent"),
            Line('  "cwd": "~/Projects/app",'),
            Line('  "mode": "accept-edits",'),
            Line('  "prompt_sha256": "8ad7...b421",', "muted"),
            Line('  "expires_at": "2026-08-23T23:20:00Z"'),
            Line("}", "muted"),
            Line("✓ Scope, authority and evidence are bound before dispatch.", "success"),
        ),
    ),
    Screen(
        filename="background-job.svg",
        title="Background job control",
        description="A bounded worker running in the background with durable status and collection commands.",
        tab="status",
        lines=(
            Line("$ agy-mc run ... --background", "prompt"),
            Line(""),
            Line('{  "status": "queued",', "muted"),
            Line('   "job_id": "job-20260823-8f31",', "accent"),
            Line('   "role": "implementer",'),
            Line('   "model": "gemini-3.7-flash-high",'),
            Line('   "mode": "accept-edits"  }'),
            Line(""),
            Line("$ agy-mc status job-20260823-8f31", "prompt"),
            Line('{  "status": "running",  "pid": 48317  }', "accent"),
            Line(""),
            Line("$ agy-mc wait job-20260823-8f31 --timeout 10m", "prompt"),
            Line('{  "status": "done",  "exit_code": 0  }', "success"),
            Line(""),
            Line("Worker result is evidence, not acceptance.", "heading"),
            Line("Codex still checks the real diff, tests and task criteria.", "muted"),
        ),
    ),
)


PALETTE = {
    "text": "#e6edf7",
    "heading": "#f8fafc",
    "prompt": "#67e8f9",
    "accent": "#22d3ee",
    "success": "#86efac",
    "muted": "#94a3b8",
    "dim": "#334155",
}


def render(screen: Screen) -> str:
    rows = []
    y = 145
    for line in screen.lines:
        color = PALETTE[line.tone]
        weight = "700" if line.tone in {"heading", "success"} else "500"
        rows.append(
            f'    <text x="92" y="{y}" fill="{color}" font-weight="{weight}">{escape(line.text)}</text>'
        )
        y += 31
    content = "\n".join(rows)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720" role="img" aria-labelledby="title desc">
  <title id="title">{escape(screen.title)}</title>
  <desc id="desc">{escape(screen.description)} Paths and values are sanitized examples rendered from the real CLI format.</desc>
  <defs>
    <linearGradient id="page" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#e8edf5"/><stop offset="1" stop-color="#d7e2ea"/></linearGradient>
    <linearGradient id="terminal" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#111827"/><stop offset="1" stop-color="#08151d"/></linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="22" stdDeviation="24" flood-color="#0f172a" flood-opacity=".28"/></filter>
  </defs>
  <rect width="1280" height="720" rx="30" fill="url(#page)"/>
  <rect x="42" y="34" width="1196" height="652" rx="20" fill="url(#terminal)" filter="url(#shadow)"/>
  <rect x="42" y="34" width="1196" height="58" rx="20" fill="#172033"/>
  <path d="M42 72h1196v20H42z" fill="#172033"/>
  <circle cx="76" cy="63" r="7" fill="#fb7185"/><circle cx="100" cy="63" r="7" fill="#fbbf24"/><circle cx="124" cy="63" r="7" fill="#4ade80"/>
  <text x="640" y="69" text-anchor="middle" fill="#cbd5e1" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="16" font-weight="700">{escape(screen.tab)}</text>
  <g xml:space="preserve" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-size="18">
{content}
  </g>
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if checked-in assets differ from the renderer")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    mismatches = []
    for screen in SCREENS:
        target = OUTPUT / screen.filename
        expected = render(screen)
        if args.check:
            if not target.is_file() or target.read_text(encoding="utf-8") != expected:
                mismatches.append(screen.filename)
        else:
            target.write_text(expected, encoding="utf-8")
    if mismatches:
        raise SystemExit(f"interface assets are stale: {', '.join(mismatches)}")
    if args.check:
        print(f"verified {len(SCREENS)} interface assets")
        return
    print(f"rendered {len(SCREENS)} interface assets in {OUTPUT}")


if __name__ == "__main__":
    main()
