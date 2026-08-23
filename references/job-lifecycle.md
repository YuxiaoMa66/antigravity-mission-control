# AGY job lifecycle

Use the job mode when a worker may run longer than the current turn, when several read-only workers should proceed independently, or when the user explicitly asks for background execution. Keep editing workers serial in one workspace; the wrapper rejects a second active `accept-edits` job for the same canonical workspace.

## Start

Add `--background` to an otherwise fully approved `run` command:

```bash
python3 scripts/agy_delegate.py run \
  --strategy A \
  --role planner \
  --model <approved-model> \
  --roster-approved \
  --cwd /absolute/path/to/project \
  --prompt-file /tmp/agy-prompt.txt \
  --mode plan \
  --background \
  --timeout-seconds 900
```

The command returns JSON with `job_id`, role, model, workspace, result path, log path, and a collect hint. It still performs all normal preflight checks before queuing the worker. `--background` does not bypass roster approval, exact model validation, pre-existing exact workspace trust, or the separate unrestricted approval.

## Collect

Use one wait command per job. The wait command prints the complete result envelope when the worker reaches a terminal state:

```bash
python3 scripts/agy_delegate.py wait <job-id> --timeout 100s
```

Exit codes are machine-readable:

- `0` — completed, including `done_with_warnings`;
- `2` — still running when this wait budget expired; run the same wait again;
- `3` — worker error or crash;
- `4` — canceled;
- `1` — invalid or unknown job request.

Use `status` for a snapshot, `result` to reprint a terminal result, and `cancel` only when the user or the approved workflow calls for stopping the worker:

```bash
python3 scripts/agy_delegate.py status [<job-id>]
python3 scripts/agy_delegate.py result <job-id>
python3 scripts/agy_delegate.py cancel <job-id>
python3 scripts/agy_delegate.py continue <job-id> \
  --prompt-file /tmp/agy-follow-up.txt \
  --roster-approved
```

`continue` reuses only the exact role, model, workspace, mode, and AGY conversation recorded by the selected completed job. It still requires roster approval, and an unrestricted continuation still requires the separate unrestricted approval flags. Job specs, logs, prompts, and result envelopes live under `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control/jobs` by default, not in the target repository. Treat the result envelope as evidence to inspect, not as proof that acceptance criteria passed; Codex still reads the changed files and runs the relevant checks.
