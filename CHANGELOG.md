# Changelog

## Unreleased

- New: `agy-mc status --limit N` and repeatable `--state` filter the job list by recency and state.
- New: `agy-mc prune --older-than DURATION [--yes]` deletes finished jobs (`done`, `done_with_warnings`, `error`, `crashed`, `cancel_failed`, `canceled`) whose `finished_at` is older than the cutoff; it keeps unfinished jobs, jobs with a live pid, and jobs with an unknown or unparseable status or `finished_at`, never follows symlinks, and is a dry run unless `--yes` is given.
- New: `agy-mc wait --timeout` also accepts `d` (days), alongside `ms`, `s`, `m`, and `h`.
- Fix: a job whose `job.json` or `result.json` holds a malformed `status` (not a known status string, or a `result.json` that is not an object) crashed `agy-mc status`, `status <id>`, `wait`, `cancel` and `prune`. A stale job with such a result, or a `result.json` with no `status`, now resolves to `crashed`, a malformed status is never written into `job.json`, and every command that reads malformed job metadata reports it as an error.

## 0.5.0 - 2026-09-22

- Stable release (npm `0.5.0` on `latest`) of the module split and every fix from the v0.4.2 release candidates; rc3 was not published on its own. Runtime routing is unchanged.
- New: `scripts/real_agy_check.py`, an acceptance suite with 19 scenarios that runs the installed AGY CLI through Mission Control. It needs no fake, keeps job state in a temporary directory and removes the trust it grants. `docs/RELEASING.md` requires a clean run before a stable release. 19 of 19 pass against AGY 1.2.8 with `gemini-3.8-flash-high`.
- Change: `done_with_warnings` now also covers a `SUCCESS` with an empty response. A nonzero exit, an `ERROR` without a response, an unknown status and AGY's print timeout are failures.
- Fix: the workspace note appended to every worker prompt included the path of Mission Control's private evidence and asked the worker to inspect diffs. Real workers sometimes spent the whole turn reading job files and hit the timeout. The note is now sent only when the workspace has pre-existing changes, lists only those paths, and names no private path.
- Change: a `--json-schema` run whose response is not a single JSON document is `done_with_warnings`; a print-timeout error carries `stuck_step`, the tool step AGY was still waiting on.
- Fix: AGY does not enforce `plan` mode; a real plan worker created a file. A `plan` run whose Git snapshots differ now fails with exit 5 and lists the changed paths (previously a clean success, documented as read-only).
- Behavior note: jobs recorded before 0.5.0 carry `conversation_id: null` when they ran on AGY 1.2, so they cannot be continued. New jobs can.

## 0.4.2rc3 - 2026-09-22

- Release candidate, not published on its own: its changes ship in 0.5.0. Third candidate of the module split, with fixes from a review of rc2.
- Fix: a nonzero AGY exit code was reported as success when the stream carried an `ERROR` result with a partial response, and an `ERROR` result without a response or `error` field returned 0. A nonzero exit now always fails and keeps the partial response as evidence; only SUCCESS, or a result event with no status and no error, succeeds; `done_with_warnings` requires a clean exit and a response.
- Fix: launch, cancel, worker completion and `refresh_job` re-read and write `job.json` under a per-job `flock`, so a cancel between the launcher's read and write is no longer overwritten with `running`.
- Fix: a `canceling` job whose cancel command was interrupted after the worker exited stayed `canceling` forever. `refresh_job` now resolves it to the worker's own result, or to `canceled` with a result file.
- Fix: AGY 1.2 nests the result envelope (`{"event": "result", "result": {...}}`). `status` and `conversation_id` were read from the top level only, so a nested `ERROR` was judged a success and every real job recorded `conversation_id: null`, which made `agy-mc continue` unusable. The parser now flattens both shapes.
- Fix: AGY's print timeout cuts the turn but still reports `SUCCESS` with an empty response and exit 0; it is now a failure with exit 124. A `SUCCESS` with no response is reported as `done_with_warnings`.
- CI: lifecycle tests on macOS; npm tests on Node 18 and 20 with a packed-tarball install.

## 0.4.2rc2 - 2026-09-22

- Pre-release (npm `0.4.2-rc.2`, published under the `next` tag; `latest` stays on 0.4.1). Second candidate of the module split, with fixes from a review of rc1.
- Fix: a background worker whose run failed (for example a soft-denied permission, exit 3) was labeled `done_with_warnings` with exit 0 whenever the relayed AGY stderr contained that status text. The label now requires a successful exit.
- Fix: workspace trust, `approve` and `run` refused only `/` and HOME. Ancestors of HOME such as `/Users`, and the system temp roots, are now refused as broad workspaces.
- Fix: a job left in `starting` by a launcher that died before the worker started is now marked `crashed` instead of blocking `wait`; jobs record `launcher_pid`. A cancel that lands during launch is no longer overwritten with `running`, and the unrecorded worker is stopped.
- Change: `agy-mc skill uninstall` refuses a target without the `.agy-mc-install.json` marker unless `--force` is given, matching install and update. The npm bootstrapper checks every target before changing anything, so `uninstall --host all` can no longer remove one Skill and then stop with the runtime left behind; it forwards `--force`.
- Internal: remove split leftovers (dead `trust_added` branch, `parse_child_payload` alias, duplicate settings writer and usage error envelopes); `common.VERSION` now derives from `__version__`, and atomic JSON writes set the final mode before the rename.

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
