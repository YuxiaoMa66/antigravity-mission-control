# Collaboration protocol

## Confirmation gate

For a new strict-yuxiao assignment, use read-only scope inspection, model discovery, and `agy-mc workspace --cwd <path>` to draft exactly three complete role/model rosters: A recommended/cost-effective, B best result, and C all AGY calls on the latest Gemini Flash High. Include AGY and Codex roles when useful. Present the executor, exact model, responsibility, and access for every role in each option, then wait for the user to select or revise one. The access cell must name both filesystem scope and execution profile. Standard permission handling is the default; unrestricted execution requires a concrete need and separate explicit confirmation. If the workspace is untrusted, disclose the exact trust mutation and request separate approval.

Approval is roster-specific. A replacement model, added role, executor change, broader write scope, or execution-profile change requires reconfirmation of the affected entry. After approval, create a short-lived `agy-mc approve` manifest and pin every AGY run to the approved slug. Roster approval alone never authorizes `--dangerously-skip-permissions`; an unrestricted manifest requires both `--permission-profile unrestricted` and the separate `--unrestricted-confirmed` assertion.

## Required roster interface

Use the following structure whenever the three-roster gate applies. Do not replace it with model names alone.

```text
Objective: <one sentence>
Catalog: <agy-mc models check time and model count>

### A: Recommended
Intent: smallest adequate team and best project-specific quality/cost balance
| Role | Executor | Exact model | Responsibility | Filesystem scope | Execution profile |
| ...  | ...      | ...         | ...            | ...              | plan|accept-edits |
Tradeoff: <specific cost, latency and review-independence effect>

### B: Best result
Intent: strongest suitable roles and cross-family review when available
<same table and tradeoff fields>

### C: Gemini Flash High
Intent: every AGY call uses the newest exact gemini-.*flash-high slug
<same table and tradeoff fields>

Reply with A, B or C, or name the entries you want changed. No worker has been dispatched.
```

Every role row must name both the filesystem scope and execution profile. Use `Codex / current session` when Codex owns a role. Mark omitted roles as omitted and explain who retains that responsibility. The tradeoff line must cover expected quota use, latency and reviewer independence without presenting routing heuristics as benchmark results.

## Required roster-change interface

Use this structure before changing any approved model, role, executor, ownership, filesystem scope or execution profile:

```text
Roster change requires confirmation
Approved strategy: <A|B|C|custom>

| Field | Approved | Proposed |
| Affected role | ... | ... |
| Executor | ... | ... |
| Exact model | ... | ... |
| Ownership | ... | ... |
| Filesystem scope | ... | ... |
| Execution profile | ... | ... |

Reason: <concrete evidence for the change>
Effect: <quota, latency, scope and review-independence impact>
Unchanged: <entries that remain approved>

Reply "approve change", "keep original", or provide another proposal. Work on the changed entry remains paused.
```

Reconfirm only the affected roster entry when the rest stays identical. A broader workspace, workspace trust mutation or unrestricted profile still needs its own approval even after the roster change is accepted. Preserve the original and revised roster in the decision log.

## Assignment contract

Compose prompts from [role contracts](role-prompts.md), the single source for shared fields and role-specific evidence requirements. Use [approvals](approvals.md) for manifest creation and follow-ups.

## Recommended sequence

1. Codex establishes the minimal read-only baseline needed to define acceptance criteria and propose roles.
2. For strict-yuxiao, Codex presents A/B/C and obtains selection. With a user-selected balanced policy, confirm the exact proposed assignment without requiring three alternatives. Reuse unchanged prior decisions.
3. A confirmed planner is optional. Use one when the design is ambiguous or the code area is unfamiliar; require a plan with risks and verification points, not edits.
   The planner may choose its own steps inside the approved objective. Require explicit alternatives only when a choice changes scope, cost, reversibility, or product behavior.
4. The confirmed implementer owns named paths. Codex inspects the actual resulting diff immediately after the run.
5. A confirmed reviewer is optional for meaningful risk. Give it the original objective, criteria, and actual diff/current files, not the implementer's conclusions. Require it to check both scope drift and completion quality.
6. Codex triages reviewer findings against source evidence. Do not forward every speculative comment into a correction loop.
7. Corrections use `approve --correction-of`; ordinary in-scope follow-ups use `--follow-up-of`. Resume the exact job with `continue` and the new prompt-bound manifest. Both retain the policy and correction count; only changed approved choices need renewed confirmation.
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
