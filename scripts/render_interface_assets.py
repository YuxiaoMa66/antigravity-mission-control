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
        Line('CLI version       0.2.0', 'text'),
        Line('Skill target      ~/.codex/skills/antigravity-mission-control', 'text'),
        Line('Runtime           ~/.local/share/antigravity-mission-control/venv', 'text'),
        Line('Source tag        v0.2.0', 'text'),
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
        Line('$ agy-mc policy strict-yuxiao', 'prompt'),
        Line('require_three_rosters: true', 'text'),
        Line('max_correction_rounds: 2', 'text'),
        Line('', 'text'),
        Line('$ agy-mc approve --policy strict-yuxiao \\', 'prompt'),
        Line('    --three-rosters-presented --strategy A --role implementer \\', 'prompt'),
        Line('    --model <approved-slug> --cwd /project \\', 'prompt'),
        Line('    --prompt-file /private/task.txt --mode accept-edits --confirmed', 'prompt'),
        Line('', 'text'),
        Line('Bound: model / workspace / prompt / permissions / policy / expiry', 'text'),
        Line("Confirmation flags record the caller's assertion.", 'text'),
    )),
    Screen('roster-selection.svg', 'Choose the right team.', 'Strict is the default. Balanced is an explicit user choice.', 'assignment policy', (
        Line('STRICT-YUXIAO', 'accent'),
        Line('A   Smallest adequate team', 'text'),
        Line('B   Capability and independent review', 'text'),
        Line('C   Latest available Gemini Flash High', 'text'),
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
    "text": "#dce5e9", "heading": "#f3f7f8", "prompt": "#79d8e2",
    "accent": "#79d8e2", "success": "#79d8e2", "muted": "#9cabb2", "dim": "#3b4a52",
}


def render(screen: Screen) -> str:
    rows = []
    y = 254
    for line in screen.lines:
        rows.append(f'<text x="72" y="{y}" fill="{PALETTE[line.tone]}">{escape(line.text)}</text>')
        y += 34
    content = "\n".join(rows)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="800" viewBox="0 0 1280 800" role="img" aria-labelledby="title desc">
<title id="title">{escape(screen.title)}</title>
<desc id="desc">{escape(screen.description)} Illustrative command and field excerpts, not a live screenshot.</desc>
<rect width="1280" height="800" rx="20" fill="#10191e"/>
<rect x="48" y="48" width="5" height="96" fill="#79d8e2"/>
<text x="72" y="88" font-family="Arial, Helvetica, sans-serif" font-size="42" font-weight="700" letter-spacing="-1" fill="#f3f7f8">{escape(screen.title)}</text>
<text x="72" y="133" font-family="Arial, Helvetica, sans-serif" font-size="23" fill="#acbbc2">{escape(screen.description)}</text>
<rect x="48" y="182" width="1184" height="524" rx="10" fill="#162229" stroke="#2d3e47"/>
<text x="72" y="215" font-family="Menlo, monospace" font-size="17" fill="#9cabb2">{escape(screen.tab)}</text>
<g xml:space="preserve" font-family="Menlo, Consolas, monospace" font-size="21">{content}</g>
<text x="72" y="756" font-family="Arial, Helvetica, sans-serif" font-size="17" fill="#9cabb2">Antigravity Mission Control  /  v0.2.0</text>
<text x="1208" y="756" text-anchor="end" font-family="Arial, Helvetica, sans-serif" font-size="17" fill="#9cabb2">Illustrative commands and fields</text>
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
