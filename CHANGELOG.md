# Changelog

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
