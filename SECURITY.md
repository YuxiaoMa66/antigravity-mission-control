# Security Policy

Only the newest alpha is supported while the project is pre-1.0. Do not open a public issue containing credentials, prompts, account data, or an exploitable path; contact the maintainer privately.

## Current boundaries

- Job evidence can contain sensitive prompts and responses. State directories are private by default, but the operator remains responsible for filesystem and backup access.
- Workspace trust mutates AGY settings only after an explicit grant command. Review the exact canonical directory first.
- Unrestricted AGY execution disables provider permission prompts. It is a separate, high-impact approval and should be exceptional.
- Signed approval manifests bind the exact run with a machine-local HMAC and expiration. They prove local integrity after creation, not human identity; retain the user's approval in the project decision log.
- Legacy boolean approval assertions remain temporarily available for Alpha migration and should not be used in new automation.
- Editing serialization relies on Unix `flock`; this Alpha supports macOS and Linux, not Windows.
- Quota output is normalized and account-free; diagnostic errors intentionally omit raw stderr.
- `--install-agy` is a separate privileged choice. It downloads Google's official installer from `https://antigravity.google/cli/install.sh` into a private temporary file, rejects empty, oversized, or non-script responses, invokes `bash` with an argument array, and removes the temporary copy. The mutable upstream installer remains a supply-chain dependency and may update the user's shell PATH. `--yes` alone never enables this path.
