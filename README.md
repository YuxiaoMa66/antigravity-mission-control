# Antigravity Mission Control

Mission Control is a policy-aware orchestration layer for the Antigravity CLI (`agy`). It gives Codex a disciplined way to route work to multiple models, keep permissions and ownership bounded, manage background jobs, independently accept results, and watch remaining AGY quota in real time.

> Alpha: the CLI and policy surface may change before 1.0. This is an independent community project, not an official Google or Antigravity product.

## What it adds

- Dynamic model discovery and A/B/C role routing rather than stale model names.
- Exact-workspace trust checks and separate unrestricted-execution confirmation.
- Synchronous and background jobs with status, wait, result, cancel, and conversation continuation.
- Prompts sent through AGY `stream-json` stdin, keeping task text out of process arguments.
- Private local state (`0700` directories and `0600` evidence files).
- Sanitized quota snapshots and a terminal watch mode.
- A Codex skill with strict and balanced policy profiles.

## Install for development

Requirements: Python 3.10+ and a working `agy` CLI. The current alpha was developed against AGY 1.1.19 on macOS.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
agy-mc doctor
```

The compatibility entrypoint needs no package install:

```bash
python3 scripts/agy_delegate.py doctor
```

## Real-time quota display

```bash
agy-mc usage
agy-mc usage --watch
agy-mc usage --watch --interval 30
agy-mc usage --format json
```

The watch refreshes every 60 seconds by default. It displays each model group and quota window, remaining percentage, reset time, and disabled state. A failed or missing value is `unknown`, never a misleading `0%`. JSON uses the stable `agy-mc-usage.v1` envelope and excludes raw provider payloads and account identity.

`/usage` is a fixed built-in command; ordinary worker prompts use stdin. Quota telemetry does not replace explicit project call budgets.

## Skill installation

Copy this directory to your Codex skills directory as `antigravity-mission-control`, restart or refresh Codex, then invoke `$antigravity-mission-control`. The bundled profiles are:

- `policies/strict-yuxiao.json`: mandatory A/B/C roster gate and Gemini High default.
- `policies/balanced.json`: lighter roster process while retaining exact models and separate unrestricted approval.

## Security model

Mission Control narrows orchestration mistakes and makes permission changes visible. Workspace trust edits AGY's user settings. `--dangerously-skip-permissions` is never implied by trust and requires separate confirmation. Do not delegate credentials, production mutation, publishing, or deletion without explicit authority.

Local job evidence may contain prompts and model responses. It is stored below `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control` with private permissions. Override paths with `AGY_MC_STATE_ROOT`, `AGY_MC_JOB_ROOT`, `AGY_MC_SETTINGS_PATH`, and `AGY_MC_BIN`.

See [SECURITY.md](SECURITY.md) for current alpha limitations.

## Validate

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q antigravity_mission_control scripts tests
```

Remote repository creation, pushing, and package publication are intentionally separate user-authorized steps.
