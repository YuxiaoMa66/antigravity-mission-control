# Changelog

## 0.1.0a1 - 2026-08-23

- Renamed the project to Antigravity Mission Control.
- Added `agy-mc` packaging and retained the legacy script entrypoint.
- Added sanitized `usage` snapshots and real-time `--watch` mode.
- Moved worker prompts from process arguments to AGY stream-json stdin.
- Moved persistent job state out of shared temporary storage and enforced private permissions.
- Added runtime doctor, strict and balanced policy profiles, bilingual documentation, tests, and CI.
- Documented the legacy approval-assertion limitation for replacement before stable release.
