# Changelog

## 0.4.2rc1 - 2026-09-21

- Pre-release (npm `0.4.2-rc.1`, published under the `next` tag; `latest` stays on 0.4.1). Split the 1938-line `antigravity_mission_control/cli.py` into `common`, `routing`, `workspace`, `jobstore`, `approvals`, `usage`, `skill` and `jobs` modules; `cli.py` keeps `doctor`, the argument parser and `main`. No behavior change: `--help` output is byte-identical and every definition is AST-equal to the original apart from the two places that name `cli.py` for worker launch.
- Background workers are still re-run by path, not with `-m`, because their working directory is the user's workspace and `-m` would put it first on `sys.path`. `cli.py` gains a `__package__` shim so its relative imports resolve when it runs as a script.
- Tests patch module state where it is read: `JOB_ROOT` lives only in `jobstore`, `SETTINGS_PATH` in `workspace` and `APPROVAL_KEY_PATH` in `approvals`.

## 0.4.1 - 2026-09-21

- Fix npm `uninstall`: with no managed Skill found it errored out and left the runtime behind (regression in v0.4.0); it now removes the runtime and CLI link again.
- Fix npm `status`: an unrelated host's config directory that is a symlink outside HOME no longer aborts it.
- Narrow the Claude Code allowlist advice in `references/host-notes.md` from `Bash(agy-mc *)` to read-only subcommands, because the broad rule would auto-approve `approve`, `run` and `workspace --grant`. Document that allow rules need every part of a `&&`/`;`/`|` chain to match, and that sandboxed state writes belong in `sandbox.filesystem.allowWrite`. Checked against the Claude Code permissions and sandbox documentation.
- Regression tests for both npm fixes. No routing, approval or worker-execution changes.

## 0.4.0 - 2026-09-21

- Run the Skill in Claude Code as well as Codex: one host-neutral Skill, deployed to `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` or `${CODEX_HOME:-~/.codex}/skills`.
- Add `--host auto|codex|claude|all` to `agy-mc skill` and the npm bootstrapper. `auto` (default) targets every host whose config directory exists; existing Codex installs keep their paths, marker file and `CODEX_HOME` behavior.
- Add `CLAUDE_CONFIG_DIR`, per-host recoverable backups, and a per-host `status` listing. `agents/openai.yaml` is copied for Codex only.
- Rewrite Skill prose from "Codex" to "host agent" and add `references/host-notes.md` (roster choice with `AskUserQuestion`, `--background` plus bounded `wait`, minimal `Bash(agy-mc *)` allowlist).
- `agy-mc doctor` warns when an installed Skill is older than the CLI.
- No routing, approval or worker-execution changes.

## 0.3.1 - 2026-09-18

- Publish the coordinated GitHub tag, GitHub Release and npm package for the corrected stable handoff.
- Replace stale Git-source installation instructions with `npx antigravity-mission-control@latest install` and an explicit `@0.3.1` pin.
- Keep Codex as the acceptance authority and make that boundary explicit in the copy-ready agent prompt.
- Synchronize runtime versions, current release assets, bilingual documentation and release checks; no routing behavior changes.

## 0.3.0 - 2026-09-18

- Make A lightweight and Flash-first, with lower Flash intensity for low-risk roles and GPT models last.
- Make B quality-first while routing implementers to Gemini Flash before other providers; retain cross-family review when available.
- Make C reuse B's quality objective while routing every AGY role to the newest Gemini Flash High model.
- Keep exact-model approval and the separate non-High Gemini confirmation boundary.
- Refresh the repository visuals with a graphite, off-white and safety-orange operational control-board system.
- Update the terminal preview, interface plates, bilingual documentation and release cover to the v0.3.0 routing model.

## 0.2.0 - 2026-09-06

- Route quota and existing-job requests directly without starting a roster workflow.
- Bind effective strict/balanced policy to new signed approvals; require an A/B/C presentation assertion for strict root assignments.
- Preserve parent assignment and correction count across follow-ups; reject a third correction along a recorded chain.
- Capture private Git workspace baselines, changed-file fingerprints and diff hashes; inject bounded existing-change context and retain both prompt hashes.
- Keep provider completion separate from acceptance, and make collect commands independent of repository-relative launcher paths.
- Consolidate role contracts and document migration/enforcement limits; add isolated fake-AGY coverage.

## 0.1.0a4 - 2026-08-23

- Added a copy-ready Agent installation prompt to both READMEs.
- Explained the A recommended, B best-result and C Gemini Flash High routing strategies with use cases and tradeoffs.
- Added required roster-selection and roster-change confirmation formats to the collaboration protocol.
- Added two matching interface captures for selecting and revising a roster.
- Bound roster changes to explicit reconfirmation while preserving separate workspace-trust and unrestricted-permission approvals.

## 0.1.0a3 - 2026-08-23

- Made npm `install` idempotent when a managed Mission Control Skill already exists.
- Added an early unmanaged-target check so collisions cannot leave a partial Python runtime.
- Added regression coverage for both managed and unmanaged pre-existing Skill targets.
- Added four consistent interface captures for guided installation, live quota, bound approvals and background jobs.
- Expanded both READMEs with a truthful CLI interface gallery using sanitized examples.

## 0.1.0a2 - 2026-08-23

- Added an explicit `--install-agy` path backed by Google's official installer.
- Added interactive AGY detection and first-login guidance without reading OAuth state.
- Reworked the English and Chinese project pitch around a familiar Codex harness supervising fast AGY workers.
- Kept existing-AGY and new-AGY installation paths distinct for automation and auditability.

## 0.1.0a1 - 2026-08-23

- Renamed the project to Antigravity Mission Control.
- Added `agy-mc` packaging and retained the legacy script entrypoint.
- Added sanitized `usage` snapshots and real-time `--watch` mode.
- Moved worker prompts from process arguments to AGY stream-json stdin.
- Moved persistent job state out of shared temporary storage and enforced private permissions.
- Added runtime doctor, strict and balanced policy profiles, bilingual documentation, tests, and CI.
- Added HMAC-signed, expiring approval manifests bound to the exact run.
- Replaced scan-based edit serialization with an inherited OS-level atomic lock.
- Added TERM/KILL cancellation confirmation and fake-AGY lifecycle tests.
- Added recoverable Python Skill management and a dependency-free npm bootstrap.
- Added bilingual terminal UI, installation/reference/release documentation, logo, and terminal preview.
- Retained legacy approval assertions only as a documented Alpha migration path.
