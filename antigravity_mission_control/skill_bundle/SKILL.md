---
name: antigravity-mission-control
description: Coordinate Antigravity CLI workers with explicit model rosters, bounded permissions, independent acceptance, background job control, and live quota telemetry. Use for multi-model AGY projects, AGY worker delegation, quota checks, or durable orchestration workflows. Not for a single ordinary AGY command that needs no orchestration.
---

# Antigravity Mission Control

Codex is mission control; AGY models are bounded workers. A worker response is evidence, not acceptance. Codex retains scope, checks the real diff and tests, and makes the completion claim.

## Preflight

1. Run `agy-mc doctor` and `agy-mc models`. The compatibility launcher in `scripts/agy_delegate.py` delegates to the installed CLI.
2. Confirm the exact target workspace and inspect its existing changes.
3. For multi-role work, read [references/model-routing.md](references/model-routing.md) and [references/collaboration-protocol.md](references/collaboration-protocol.md).
4. Present A (cost-effective), B (best result), and C (latest Gemini Flash High only) rosters and wait for explicit selection. Pin every AGY model to the returned exact slug.
5. Workspace trust and unrestricted execution are separate mutations. Explain each exact target and obtain its own confirmation. Standard permission handling is the default.
6. Before a worker call, record role, owned and forbidden paths, acceptance criteria, checks, execution profile, and correction limit.

When exact workspace trust is approved, grant it separately:

```bash
agy-mc workspace --cwd /absolute/project/path \
  --mode accept-edits --grant --trust-approved
```

The bundled `strict-yuxiao` policy preserves the mandatory three-roster flow. `balanced` is available for projects where the user explicitly prefers a lighter confirmation gate.

## Dispatch and acceptance

- Use [references/role-prompts.md](references/role-prompts.md) for scout, planner, implementer, and reviewer contracts.
- Run editing workers serially in one workspace. Parallelize only read-only or genuinely disjoint work.
- Use `--mode plan` for read-only roles and `--mode accept-edits` only for an approved write scope.
- Keep prompts outside the project. Mission Control sends them to AGY over standard input, not the process argument list.
- Use `--background` for long work, then `status`, `wait`, `result`, or `cancel`. Read [references/job-lifecycle.md](references/job-lifecycle.md).
- Limit ordinary correction loops to two. Diagnose recurring infrastructure failures instead of cycling models.
- Independently inspect outputs, changed files, untracked files, diagnostics, and relevant tests. Do not let an implementer approve its own work.

After the exact roster and permission profile are approved, create a short-lived bound manifest. Treat `--confirmed` as an assertion backed by the durable decision log:

```bash
agy-mc approve \
  --strategy A --role implementer --model <exact-approved-slug> \
  --cwd /absolute/project/path --prompt-file /private/path/prompt.txt \
  --mode accept-edits --expires-minutes 60 --confirmed
```

Run with the returned `--approval-file`. The manifest is signed by a machine-local key and binds strategy, role, model, canonical workspace, prompt hash, mode, permission profile, conversation and expiration. Never reuse it after any bound field changes. Legacy boolean approval flags are deprecated migration compatibility.

## Live quota

Use `agy-mc usage` for a sanitized snapshot or:

```bash
agy-mc usage --watch --interval 60
agy-mc usage --format json
```

Unknown and failed values remain `unknown`; they must never be reported as zero. The adapter outputs quota groups, windows, remaining percentages, reset times, and disabled state without OAuth data, email addresses, or raw account payloads. Quota telemetry is operational context only and does not replace explicit call budgets.

Read [references/runtime-diagnostics.md](references/runtime-diagnostics.md) after launch, authentication, permission, or model-routing errors. Finish only when direct evidence maps to every acceptance criterion, and report the exact models, ownership, checks, and unresolved limits.
