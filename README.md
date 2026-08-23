<p align="center"><img src="assets/logo/mission-control.svg" width="720" alt="Antigravity Mission Control"></p>

<p align="center"><a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a></p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-7c3aed" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/Node.js-18%2B-0891b2" alt="Node.js 18+">
  <img src="https://img.shields.io/badge/AGY-tested_1.1.19-22d3ee" alt="AGY tested 1.1.19">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-a78bfa" alt="MIT License"></a>
</p>

Policy-aware orchestration for the Antigravity CLI (`agy`): route work to exact models, bind approvals to the task, serialize editing workers, verify cancellation, and watch live quota—while Codex remains responsible for acceptance.

<p align="center"><img src="assets/terminal-preview.svg" width="920" alt="Mission Control terminal preview"></p>

> **Alpha:** ready for public pre-release evaluation, not a stable security boundary. Independent community project; not affiliated with Google or Antigravity.

## Install

Install AGY first and verify `agy --version`. Then use the npm bootstrapper:

```bash
npx antigravity-mission-control install
```

It shows every target before writing, creates a private managed Python environment, installs `agy-mc`, deploys the Codex Skill, and runs without shell interpolation. For CI or agents, add `--yes`; inspect first with `--dry-run`.

```bash
npx antigravity-mission-control install --dry-run
npx antigravity-mission-control install --yes
npx antigravity-mission-control status
```

Direct Python installation is also supported:

```bash
python3 -m pip install "git+https://github.com/YuxiaoMa66/antigravity-mission-control.git@v0.1.0a1"
agy-mc skill install
agy-mc doctor
```

Full setup, upgrade, uninstall, local-source and PATH notes: [Installation guide](docs/INSTALL.md).

## What Mission Control adds

| Layer | Responsibility |
|---|---|
| Codex Skill | Roster choice, scope, permission boundaries, independent acceptance |
| `agy-mc` core | Model discovery, signed approvals, AGY transport, jobs, locks, evidence, quota |
| npm bootstrap | Managed Python environment, Skill deployment, update and recoverable uninstall |
| AGY | Executes the exact bounded worker assignment |

The npm layer is deliberately thin. The Python companion is the single behavioral implementation, so npm and direct Python installs cannot drift into different orchestration rules.

## Live quota

```bash
agy-mc usage
agy-mc usage --watch --interval 60
agy-mc usage --format json
```

The normalized `agy-mc-usage.v1` output includes model groups, quota windows, remaining percentage, reset time and disabled state. Missing data stays `unknown`; it is never rewritten as `0%`. Raw provider payloads, OAuth material and account identity are excluded.

## Bound approvals

After the user approves the exact roster and permission profile, create a short-lived manifest:

```bash
agy-mc approve \
  --strategy A --role implementer --model gemini-3.7-flash-high \
  --cwd /absolute/project --prompt-file /private/prompt.txt \
  --mode accept-edits --expires-minutes 60 --confirmed
```

Pass the returned file to `run`. The machine-local HMAC binds strategy, role, model, canonical workspace, prompt hash, mode, permission profile, conversation and expiration. Changing any bound field invalidates the run.

```bash
agy-mc run \
  --strategy A --role implementer --model gemini-3.7-flash-high \
  --cwd /absolute/project --prompt-file /private/prompt.txt \
  --mode accept-edits --approval-file ~/.local/state/antigravity-mission-control/approvals/<id>.json
```

Legacy boolean approval flags remain for migration in this Alpha and are deprecated.

## Background jobs

Add `--background`, then use:

```bash
agy-mc status [job-id]
agy-mc wait <job-id> --timeout 10m
agy-mc result <job-id>
agy-mc cancel <job-id>
agy-mc continue <job-id> --prompt-file /private/follow-up.txt
```

Editing jobs use an OS-level non-blocking lock per canonical workspace. `cancel` records `canceling`, waits after TERM, escalates to KILL if required, and reports `canceled` only after process exit is confirmed.

## Design principles

- Exact models are discovered from the current AGY session; no remembered slug is treated as truth.
- Workspace trust and unrestricted execution are separate user-approved mutations.
- Worker success is not task acceptance. Codex checks the real diff, diagnostics and tests.
- Prompts travel over `stream-json` stdin, never in process arguments.
- State directories are `0700`; prompts, manifests, locks and results are `0600`.
- Installation and uninstall preserve recoverable backups.

See [Reference](docs/REFERENCE.md), [Security](SECURITY.md), [Contributing](CONTRIBUTING.md), and [Release process](docs/RELEASING.md).

## Validate

```bash
python3 -m unittest discover -s tests -v
npm test
npm pack --dry-run
python3 -m compileall -q antigravity_mission_control scripts tests
```

## License

MIT. Role-contract patterns were adapted from [keli-wen/agy-staff](https://github.com/keli-wen/agy-staff) under its MIT license; see [NOTICE](NOTICE).
