# Reference

[English](REFERENCE.md) · [简体中文](REFERENCE.zh-CN.md)

## Command map

| Command | Purpose |
|---|---|
| `doctor` | Verify AGY version, headless flags, authenticated model access and private state |
| `models` | Discover exact current model IDs |
| `usage [--watch]` | Sanitized quota snapshot or live terminal view |
| `workspace` | Inspect or separately grant exact workspace trust |
| `approve` | Create a signed, expiring run approval |
| `select` | Produce proposal candidates for A/B/C rosters |
| `run` | Execute one foreground or background worker |
| `status`, `wait`, `result` | Observe and collect jobs |
| `cancel` | Confirmed TERM/KILL cancellation |
| `continue` | Continue one exact recorded conversation |
| `skill` | Install, update, inspect or recoverably uninstall the Codex Skill |

## Job states and exit codes

| State | Exit | Meaning |
|---|---:|---|
| `starting`, `running`, `canceling` | 2 | Incomplete; observe again |
| `done`, `done_with_warnings` | 0 | Provider execution finished; acceptance still belongs to Codex |
| `error`, `crashed`, `cancel_failed` | 3 | Infrastructure or execution failure |
| `canceled` | 4 | Process exit confirmed after caller cancellation |

Job evidence is stored outside target repositories. Results retain provider output and diagnostics and may contain sensitive project content.

## Workspace serialization

Foreground and background `accept-edits` runs acquire a non-blocking OS `flock` keyed by SHA-256 of the canonical workspace. A background launcher transfers the inherited file descriptor to its worker; the lock is released automatically when that worker exits. Read-only `plan` jobs do not take the edit lock.

## Approval manifests

`approve` creates `agy-mc-approval.v1` with a machine-local HMAC-SHA256. It binds strategy, role, exact model, canonical workspace, prompt SHA-256, AGY mode, permission profile, non-high Gemini exception, conversation and expiration. Maximum validity is 24 hours.

The signing key is created at `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control/approval.key` with mode `0600`. A manifest copied to another machine does not validate. This proves local integrity after creation; it does not prove that a human actually approved the command, so the durable project decision log remains authoritative.

## Environment overrides

| Variable | Purpose |
|---|---|
| `AGY_MC_BIN` | Exact AGY executable |
| `AGY_MC_SETTINGS_PATH` | AGY settings JSON |
| `AGY_MC_STATE_ROOT` | Mission Control state root |
| `AGY_MC_JOB_ROOT` | Job evidence root |
| `CODEX_HOME` | Codex home used for Skill deployment |
| `XDG_STATE_HOME` | Standard state parent |
| `NO_COLOR` | Disable npm terminal colors |

Legacy `AGY_ORCHESTRATOR_BIN` and `AGY_ORCHESTRATOR_JOB_ROOT` remain fallback aliases for migration.

## Quota schema

`agy-mc-usage.v1` returns `status`, `source`, `fetched_at`, normalized `groups`, and safe `errors`. Each bucket has `id`, `name`, `window`, `remaining_fraction`, `remaining_percent`, `reset_time`, and `disabled`. Errors never expose raw AGY stderr.

## Permission boundaries

Exact workspace trust is a separate `workspace --grant --trust-approved` operation. It refuses filesystem root, the home directory, and matching `deny` or `ask` rules. Unrestricted execution requires its own approval profile and is never inferred from trust.

## Policy, follow-ups and workspace evidence

`policy [strict|balanced]` reports the effective settings without calling AGY. New `approve` manifests bind the policy. Strict root approvals require `--three-rosters-presented`; balanced roots still require `--confirmed`, exact models and separate unrestricted authorization. Choose balanced only with the user's approval.

Use `approve --correction-of <job-id>` for corrections or `--follow-up-of <job-id>` for ordinary in-scope follow-ups, preserving the parent's exact assignment, policy and conversation. Corrections increment a recorded chain counter; a third correction is rejected. Follow-ups retain the count. A newly approved task is required when the scope changes. Flags record the caller's assertion, not proof of human approval; lineage does not enforce a global call budget. Legacy manifests/boolean runs remain uncounted for migration.

Run evidence records private before/after Git snapshots, changed-path fingerprints and staged/unstaged diff hashes outside the project, with paths available in background job results and foreground stderr. The original signed prompt remains intact; observed context is appended and both prompt hashes are recorded. Missing/oversized evidence and snapshot timeouts are explicit limitations. A killed job can lack its after snapshot. Evidence is not a per-file sandbox or automatic ownership/acceptance proof. Provider success retains `acceptance: not_evaluated` in background results.

See [approval workflow](../references/approvals.md) and [job lifecycle](../references/job-lifecycle.md) for exact commands and evidence limits.
