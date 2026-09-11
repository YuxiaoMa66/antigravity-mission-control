# AGY job lifecycle

Use the job mode when a worker may run longer than the current turn, when several read-only workers should proceed independently, or when the user explicitly asks for background execution. Keep editing workers serial in one workspace; the wrapper rejects a second active `accept-edits` job for the same canonical workspace.

## Start

Add `--background` to an otherwise fully approved `run` command:

```bash
agy-mc run \
  --strategy A \
  --role planner \
  --model <approved-model> \
  --approval-file /private/approval.json \
  --cwd /absolute/path/to/project \
  --prompt-file /tmp/agy-prompt.txt \
  --mode plan \
  --background \
  --timeout-seconds 900
```

The command returns JSON with `job_id`, role, model, workspace, result path, log path, approval identity, and a collect hint. It still performs all normal preflight checks before queuing the worker. `--background` does not bypass signed approval validation, exact model validation, pre-existing exact workspace trust, or the separate unrestricted profile.

## Collect

Use one wait command per job. The wait command prints the complete result envelope when the worker reaches a terminal state:

```bash
agy-mc wait <job-id> --timeout 300s
```

Exit codes are machine-readable:

- `0` — completed, including `done_with_warnings`;
- `2` — still running when this wait budget expired; run the same wait again;
- `3` — worker error or crash;
- `4` — canceled;
- `5` — policy or workspace-scope enforcement failure (`scope_violation`, `check_failed`, `incomplete_evidence`);
- `1` — invalid or unknown job request.

Use `status` for a snapshot, `result` to reprint a terminal result and return its exact exit code (such as 5 on enforcement failure), and `cancel` only when the user or the approved workflow calls for stopping the worker:

```bash
agy-mc status [<job-id>]
agy-mc result <job-id>
agy-mc cancel <job-id>
agy-mc continue <job-id> \
  --prompt-file /tmp/agy-follow-up.txt \
  --approval-file /private/follow-up-approval.json
```

`continue` reuses only the exact role, model, workspace, mode, and AGY conversation recorded by the selected completed job. A new prompt requires a new bound approval; alternatively call `run --conversation <exact-id> --approval-file <new-manifest>`. Job specs, logs, prompts, and result envelopes live under `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control/jobs` by default, not in the target repository. Treat the result envelope as evidence to inspect, not as proof that acceptance criteria passed; Codex still reads changed files and runs the relevant checks.

Editing runs use an OS-level non-blocking lock keyed by canonical workspace. Background workers inherit the lock descriptor, so simultaneous launchers cannot pass a scan race. `cancel` transitions through `canceling`, waits for TERM, escalates to KILL, and reports `canceled` only after confirmed exit; otherwise it records `cancel_failed`.

## Workspace evidence and scope enforcement

Each new run records private `before.json`, `after.json`, `delta.json` and `dispatch.json` outside the project. Background jobs expose `evidence_path`; foreground runs print `amc_evidence` on stderr. A canceled or killed run may have only its before snapshot. Git evidence includes HEAD, staged/unstaged diff hashes and fingerprints of changed paths, including untracked files. It does not store full file contents. Fingerprints are capped at 5000 paths, 8 MiB per file and 64 MiB total; omissions are labelled. Concurrent writers and submodule contents require direct inspection.

When a run uses a scoped approval (`--allowed-path`), Mission Control performs post-run scope evaluation against actual before/after evidence:
- Evaluates changed destination and original rename paths, tracked deletions and untracked additions.
- Any change to Git HEAD is a scope violation.
- Any changed symlink resolving outside the repository, into a forbidden rule, or encountering resolution loops is a scope violation.
- Snapshot limitations produce `incomplete_evidence` and cannot pass.
- Provider failures never hide workspace violations: if provider failure also changed a forbidden/out-of-scope path or HEAD, `scope_violation` (or `incomplete_evidence`) is reported with `provider_exit_code` preserved; otherwise `provider_error` is reported.
- Top-level `acceptance: not_evaluated` is strictly preserved. A separate `enforcement` object records `status`: `not_configured`, `scope_passed`, `passed`, `scope_violation`, `check_failed`, `incomplete_evidence`, `provider_error`, or `canceled`. Neither `scope_passed` nor `passed` implies semantic or business acceptance.
- When required checks are configured, they run only after provider success and clean initial scope, executing frozen argv directly (`shell=False`, `stdin=DEVNULL`) in a dedicated process group. Timeouts terminate the group so descendants do not survive the check. Launch failures (missing executable exit 127, permission denied exit 126, timeout exit 124, invalid argv/NUL) are converted into deterministic private check evidence in `checks.json` without leaking uncaught exceptions. Full-output hashes and truncated stdout/stderr are stored in private `checks.json`. A final snapshot and scope re-evaluation are always captured after check execution: a failed check that also produces out-of-scope changes reports `scope_violation` with check evidence; only scope-clean failed checks report `check_failed`.
- Configured violations, check failures or incomplete evidence return distinct exit code `5` while preserving provider diagnostics. Foreground stderr and background result/wait expose the same `enforcement` object and evidence path. Canceled runs record `enforcement.status: canceled`.

Use the collect command returned by the launcher (`agy-mc wait ...`), independent of the current working directory. A wait timeout is only an observation timeout. For continuation approvals and correction limits, read [approvals](approvals.md).
