#!/usr/bin/env python3
"""Render versioned command and workflow illustrations as dependency-free SVG assets."""

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
    Screen('guided-install.svg', 'Install with intent.', 'Inspect the exact target before installing the CLI and skill.', 'install', (
        Line('$ npx antigravity-mission-control@latest install --dry-run', 'prompt'),
        Line('', 'text'),
        Line('CLI version       0.3.1', 'text'),
        Line('Skill target      ~/.codex/skills/antigravity-mission-control', 'text'),
        Line('Runtime           ~/.local/share/antigravity-mission-control/venv', 'text'),
        Line('Source tag        v0.3.1', 'text'),
        Line('', 'text'),
        Line('$ npx antigravity-mission-control@latest install', 'prompt'),
        Line('', 'text'),
        Line('Inspect targets. Approve installation. Keep a recovery path.', 'text'),
    )),
    Screen('live-quota.svg', 'Quota, without a kickoff.', 'Usage queries go straight to telemetry. No roster workflow.', 'usage', (
        Line('$ agy-mc usage', 'prompt'),
        Line('', 'text'),
        Line('GROUP                   WINDOW     REMAINING', 'accent'),
        Line('Gemini Models           weekly     62.50%', 'text'),
        Line('Claude and GPT models   weekly     unknown', 'text'),
        Line('', 'text'),
        Line('$ agy-mc usage --watch --interval 60', 'prompt'),
        Line('', 'text'),
        Line('Unknown stays unknown. Watch only when requested.', 'text'),
        Line('Sample values. Account identity is excluded.', 'text'),
    )),
    Screen('bound-approval.svg', 'Make the policy explicit.', 'New manifests bind the effective policy and the approved task.', 'policy / approve', (
        Line('$ agy-mc policy strict', 'prompt'),
        Line('require_three_rosters: true', 'text'),
        Line('max_correction_rounds: 2', 'text'),
        Line('', 'text'),
        Line('$ agy-mc approve --policy strict \\', 'prompt'),
        Line('    --three-rosters-presented --strategy A --role implementer \\', 'prompt'),
        Line('    --model <approved-slug> --cwd /project \\', 'prompt'),
        Line('    --prompt-file /private/task.txt --mode accept-edits --confirmed', 'prompt'),
        Line('', 'text'),
        Line('Bound: model / workspace / prompt / permissions / policy / expiry', 'text'),
        Line("Confirmation flags record the caller's assertion.", 'text'),
    )),
    Screen('roster-selection.svg', 'Choose the right team.', 'Strict is the default. Balanced is an explicit user choice.', 'assignment policy', (
        Line('STRICT-YUXIAO', 'accent'),
        Line('A   Lightweight Flash-first team', 'text'),
        Line('B   Quality-first Flash implementer', 'text'),
        Line('C   Every role on Gemini Flash High', 'text'),
        Line('', 'text'),
        Line('BALANCED', 'accent'),
        Line('One exact assignment for approval', 'text'),
        Line('', 'text'),
        Line('Both retain exact model and scope approval.', 'text'),
        Line('Unrestricted execution requires separate authorization.', 'text'),
    )),
    Screen('roster-change.svg', 'Confirm what changed.', 'Reuse existing decisions when the assignment stays the same.', 'scope / continuation', (
        Line('UNCHANGED ASSIGNMENT', 'accent'),
        Line('Same model, workspace, role and permissions', 'text'),
        Line('New prompt: create a fresh bound manifest', 'text'),
        Line('', 'text'),
        Line('CHANGED ASSIGNMENT', 'accent'),
        Line('Present the affected entry and its tradeoff', 'text'),
        Line('Confirm the change before dispatch', 'text'),
        Line('', 'text'),
        Line('Ordinary follow-up: --follow-up-of <job-id>', 'text'),
        Line('Correction:         --correction-of <job-id>', 'text'),
    )),
    Screen('background-job.svg', 'Dispatch. Collect. Inspect.', 'A completed worker still needs independent acceptance.', 'run / wait / result', (
        Line('$ agy-mc run <approved-run-fields> --background', 'prompt'),
        Line('', 'text'),
        Line('job_id:          implementer-<timestamp>-<id>', 'text'),
        Line('evidence_path:   <private-job-dir>/workspace-evidence', 'text'),
        Line('', 'text'),
        Line('$ agy-mc wait <job-id> --timeout 300s', 'prompt'),
        Line('', 'text'),
        Line('status:          done', 'text'),
        Line('acceptance:      not_evaluated', 'text'),
        Line('', 'text'),
        Line('Inspect the real diff and checks against the original task.', 'text'),
    )),
    Screen('workspace-evidence.svg', 'Know what was already there.', 'Private Git baselines help separate existing and new changes.', 'workspace evidence', (
        Line('BEFORE DISPATCH', 'accent'),
        Line('before.json     HEAD / Git status / changed-file fingerprints', 'text'),
        Line('dispatch.json   original and dispatched prompt hashes', 'text'),
        Line('', 'text'),
        Line('AFTER EXECUTION', 'accent'),
        Line('after.json      fresh workspace snapshot', 'text'),
        Line('delta.json      changed paths / diff changes / limitations', 'text'),
        Line('', 'text'),
        Line('Existing changes enter the worker prompt as observed context.', 'text'),
        Line('Missing evidence stays visible. Ownership still needs review.', 'text'),
    )),
    Screen('correction-chain.svg', 'Keep the correction history.', 'Ordinary follow-ups retain the count. Corrections increment it.', 'recorded job lineage', (
        Line('Initial job                  correction_round: 0', 'text'),
        Line('  -> first correction        correction_round: 1', 'text'),
        Line('  -> ordinary follow-up      correction_round: 1', 'text'),
        Line('  -> second correction       correction_round: 2', 'text'),
        Line('', 'text'),
        Line('Third correction             rejected', 'accent'),
        Line('', 'text'),
        Line('Diagnose the failure before approving a new scoped task.', 'text'),
        Line('', 'text'),
        Line('Limit applies to recorded chains; legacy runs are uncounted.', 'text'),
    )),
)

PALETTE = {
    "text": "#d8d4ca", "heading": "#f2eee5", "prompt": "#e6a15d",
    "accent": "#e6a15d", "success": "#c7d5b7", "muted": "#a4a59c", "dim": "#555b53",
}


def render(screen: Screen) -> str:
    rows = []
    y = 286
    for index, line in enumerate(screen.lines, start=1):
        rows.append(f'<text x="92" y="{y}" fill="{PALETTE["dim"]}">{index:02d}</text>')
        rows.append(f'<text x="142" y="{y}" fill="{PALETTE[line.tone]}">{escape(line.text)}</text>')
        y += 34
    content = "\n".join(rows)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="0 0 1280 800" role="img" aria-labelledby="title desc">
<title id="title">{escape(screen.title)}</title>
<desc id="desc">{escape(screen.description)} Illustrative command and field excerpts, not a live screenshot.</desc>
<rect width="1280" height="800" rx="12" fill="#141615"/>
<path d="M48 48H1232M48 748H1232" stroke="#30352f"/>
<rect x="64" y="48" width="7" height="94" fill="#e6a15d"/>
<text x="92" y="76" font-family="Menlo, Consolas, monospace" font-size="15" letter-spacing="2" fill="#e6a15d">MISSION CONTROL  /  V0.3.1</text>
<text x="92" y="122" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="700" letter-spacing="-1.2" fill="#f2eee5">{escape(screen.title)}</text>
<text x="92" y="162" font-family="Arial, Helvetica, sans-serif" font-size="22" fill="#a4a59c">{escape(screen.description)}</text>
<text x="1232" y="76" text-anchor="end" font-family="Menlo, Consolas, monospace" font-size="14" letter-spacing="1.4" fill="#a4a59c">OPERATIONAL EVIDENCE PLATE</text>
<rect x="64" y="208" width="1152" height="502" rx="8" fill="#20231f" stroke="#454a42"/>
<rect x="64" y="208" width="8" height="502" fill="#e6a15d"/>
<text x="92" y="244" font-family="Menlo, Consolas, monospace" font-size="16" fill="#a4a59c">{escape(screen.tab)}</text>
<rect x="978" y="222" width="210" height="32" rx="6" fill="#2b302a" stroke="#555b53"/>
<text x="1083" y="243" text-anchor="middle" font-family="Menlo, Consolas, monospace" font-size="13" letter-spacing="1" fill="#e6a15d">ROUTE / GUARD / VERIFY</text>
<path d="M92 260H1188" stroke="#343a33"/>
<g xml:space="preserve" font-family="Menlo, Consolas, monospace" font-size="20">{content}</g>
<text x="92" y="774" font-family="Menlo, Consolas, monospace" font-size="14" letter-spacing="1" fill="#a4a59c">ANTIGRAVITY MISSION CONTROL  /  STATIC ILLUSTRATION</text>
<text x="1232" y="774" text-anchor="end" font-family="Menlo, Consolas, monospace" font-size="14" fill="#a4a59c">TEXT AND VALUES ARE EXAMPLES</text>
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
