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
- `1` — invalid or unknown job request.

Use `status` for a snapshot, `result` to reprint a terminal result, and `cancel` only when the user or the approved workflow calls for stopping the worker:

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

## Workspace evidence

Each new run records private `before.json`, `after.json`, `delta.json` and `dispatch.json` outside the project. Background jobs expose `evidence_path`; foreground runs print `amc_evidence` on stderr. A canceled or killed run may have only its before snapshot. Git evidence includes HEAD, staged/unstaged diff hashes and fingerprints of changed paths, including untracked files. It does not store full file contents. Fingerprints are capped at 5000 paths, 8 MiB per file and 64 MiB total; omissions are labelled. Concurrent writers and submodule contents require direct inspection. `acceptance: not_evaluated` remains true even when provider execution succeeds.

Use the collect command returned by the launcher (`agy-mc wait ...`), independent of the current working directory. A wait timeout is only an observation timeout. For continuation approvals and correction limits, read [approvals](approvals.md).
