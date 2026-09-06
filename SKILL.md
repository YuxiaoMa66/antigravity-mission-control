---
name: antigravity-mission-control
description: Coordinate bounded Antigravity CLI workers with approved model rosters and independent acceptance; inspect AGY jobs and live quota. Use for AGY delegation, job follow-ups, quota checks, or multi-model projects. Not for an ordinary single AGY command without orchestration.
---

# Antigravity Mission Control

Codex owns the user's objective and final acceptance. AGY workers own bounded assignments; their responses are evidence to inspect.

## Choose the route first

| Request | Action |
| --- | --- |
| Quota or reset time | Run `agy-mc usage`; use `--format json` when needed. No roster, workspace trust, or model discovery is needed. |
| Existing job status, result, wait or cancellation | Use the exact job id and [job lifecycle](references/job-lifecycle.md). No new roster is needed. |
| Existing job follow-up or correction | Preserve the approved scope and model; read [approvals](references/approvals.md). A new prompt needs a new manifest, not renewed approval of unchanged choices. |
| New worker assignment | Follow the dispatch workflow below. |
| Launch, permission, authentication or routing failure | Read [runtime diagnostics](references/runtime-diagnostics.md); preserve the evidence before retrying. |

Unknown or failed quota values stay `unknown`, never zero. Quota telemetry does not establish a call budget. Watch only when requested: `agy-mc usage --watch --interval 60`.

## Dispatch workflow

1. Inspect the exact workspace and existing changes. Run `agy-mc doctor` and `agy-mc models` before a new dispatch session; refresh discovery when availability changes or a routing error occurs.
2. Read [model routing](references/model-routing.md) and [collaboration protocol](references/collaboration-protocol.md). The default is `strict`: present A/B/C role-model rosters and obtain selection. Use `balanced` only when the user has chosen lighter confirmation; it still requires approval of the exact assignment. Inspect either with `agy-mc policy <name>`.
3. Reuse existing authorization for unchanged choices. Confirm only a changed model, role, executor, scope or permission profile. Workspace trust and unrestricted execution require separate exact authorization; standard permissions remain the default.
4. Compose a bounded assignment using [role contracts](references/role-prompts.md), then create the prompt-bound manifest using [approvals](references/approvals.md). Keep prompts outside the project and send them through the CLI, which uses stdin.
5. Dispatch with the exact model and `--approval-file`. Use background execution for long tasks and collect every started job. Editing workers share one canonical-workspace lock; parallel edits require isolated worktrees and explicit integration.
6. Independently inspect the actual changes and relevant checks against the original objective. Separate infrastructure errors, worker findings and acceptance. `done` or `done_with_warnings` does not mean the task passed acceptance.

## Workspace evidence and correction

The CLI records private before/after Git snapshots, changed-path fingerprints and diff hashes outside the project. It injects a bounded summary of pre-existing changes as context. Inspect the reported evidence path plus real diffs: snapshots are not a sandbox, proof of ownership, or an automatic acceptance test. Missing, oversized or concurrent evidence is a limitation, not a clean result.

Use `approve --correction-of <job-id>` for a correction and `--follow-up-of <job-id>` for an ordinary in-scope follow-up. Both retain the recorded policy and assignment. Two corrections are allowed along a recorded chain; ordinary follow-ups retain its count. At the limit, diagnose the failure and obtain a new scoped decision rather than starting an unrecorded retry. See [approvals](references/approvals.md) for legacy and enforcement limits.

Finish with the result, exact models, checked evidence and unresolved limits. Let workers choose their own steps within scope; ask about alternatives only when they materially change the user's outcome, cost, scope or reversibility.
