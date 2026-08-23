# Security Policy

Only the newest alpha is supported while the project is pre-1.0. Do not open a public issue containing credentials, prompts, account data, or an exploitable path; contact the maintainer privately.

## Current boundaries

- Job evidence can contain sensitive prompts and responses. State directories are private by default, but the operator remains responsible for filesystem and backup access.
- Workspace trust mutates AGY settings only after an explicit grant command. Review the exact canonical directory first.
- Unrestricted AGY execution disables provider permission prompts. It is a separate, high-impact approval and should be exceptional.
- The alpha still accepts legacy boolean approval assertions. They are not cryptographic proof. A bound, expiring approval manifest is required before stable release.
- Quota output is normalized and account-free; diagnostic errors intentionally omit raw stderr.
