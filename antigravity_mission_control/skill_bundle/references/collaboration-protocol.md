# Collaboration protocol

## Confirmation gate

Before dispatch, use read-only scope inspection, model discovery, and `agy-mc workspace --cwd <path>` to draft exactly three complete role/model rosters: A recommended/cost-effective, B best result, and C all AGY calls on the latest Gemini Flash High. Include AGY and Codex roles when useful. Present the executor, exact model, responsibility, and access for every role in each option, then wait for the user to select or revise one. The access cell must name both filesystem scope and execution profile. Standard permission handling is the default; unrestricted execution requires a concrete need and separate explicit confirmation. If the workspace is untrusted, disclose the exact trust mutation and request separate approval.

Approval is roster-specific. A replacement model, added role, executor change, broader write scope, or execution-profile change requires reconfirmation of the affected entry. After approval, create a short-lived `agy-mc approve` manifest and pin every AGY run to the approved slug. Roster approval alone never authorizes `--dangerously-skip-permissions`; an unrestricted manifest requires both `--permission-profile unrestricted` and the separate `--unrestricted-confirmed` assertion.

## Assignment contract

Each AGY prompt should contain:

```text
Role: <planner | implementer | reviewer>
Objective: <one bounded outcome>
Workspace: <absolute path>
Ownership: <paths this worker may change>
Do not touch: <unrelated/user-owned paths and prohibited actions>
Known context: <facts already verified by Codex>
Acceptance criteria:
- <observable criterion>
Checks: <commands or inspections to attempt>
Final response: list changed paths, checks and results, limitations, and remaining risks.
```

For a reviewer, explicitly say: “Read-only review. Do not edit files. Look for concrete correctness, security, compatibility, and test gaps. Rank findings by severity and cite paths/lines.”

## Recommended sequence

1. Codex establishes the minimal read-only baseline needed to define acceptance criteria and propose roles.
2. Codex presents A, B, and C with complete role/model rosters and waits for the user to select or revise one.
3. A confirmed planner is optional. Use one when the design is ambiguous or the code area is unfamiliar; require a plan with risks and verification points, not edits.
4. The confirmed implementer owns named paths. Codex inspects the actual resulting diff immediately after the run.
5. A confirmed reviewer is optional for meaningful risk. Give it the original criteria and the actual diff/current files, not the implementer's conclusions.
6. Codex triages reviewer findings against source evidence. Do not forward every speculative comment into a correction loop.
7. Corrections use a new prompt-bound approval and resume the exact implementer conversation with `--conversation`, or require roster reconfirmation if ownership, executor, model, or permission profile changes.
8. Codex runs final tests and checks repository cleanliness/scope before reporting completion.

For a long-running worker or independent read-only work, pass `--background` to the already-approved `run` command. Collect each returned job with its own `wait <job-id>` command; a wait timeout is not a worker failure and should be retried. `status`, `result`, and `cancel` are lifecycle operations, not substitutes for acceptance checks. Job prompts, logs, and result envelopes are kept outside the repository by default.

## Concurrency

Do not run multiple editing models in the same working tree. If parallel editing is valuable, create separate worktrees or isolated copies, give each one explicit ownership, and integrate deliberately. Parallel read-only runs may share a workspace.

The wrapper enforces this boundary for queued `accept-edits` jobs by rejecting a second active editor for the same canonical workspace. Do not work around that guard by broadening paths or launching a second wrapper process manually.

## Failure handling

- Nonzero exit or non-`SUCCESS` status: preserve the error, diagnose authentication/model/timeout separately, and retry once only when the cause is transient or corrected.
- Untrusted workspace: after separate trust approval, run `workspace --cwd <exact-path> --mode <mode> --grant --trust-approved`. Never broaden to its parent. If an explicit matching `deny` or `ask` exists, stop for manual resolution rather than overriding it.
- `SUCCESS` with no expected diff: treat as incomplete, inspect permission diagnostics, and send one precise correction.
- Soft-denied file access after trust: treat the run as failed and inspect project/shared/global permission rules. Soft-denied commands: have Codex run the safe check directly; do not escalate to blanket approval.
- Conflicting model recommendations: Codex resolves them using repository evidence, tests, and user priorities.
- Timeout: inspect whether useful edits exist before retrying. Avoid overlapping a timed-out worker with a new editor in the same tree.
