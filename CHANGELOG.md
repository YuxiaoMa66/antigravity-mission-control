# Changelog

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
