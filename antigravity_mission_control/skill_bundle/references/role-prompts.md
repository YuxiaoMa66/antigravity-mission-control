# Role-specific assignment contracts

Read this reference when composing an AGY worker prompt. It is a compact contract, not a replacement for the user's request. Preserve the user's wording, workspace, and requested scope; add only the role framing and evidence requirements that make the assignment verifiable.

## Shared contract

Every prompt should state:

```text
Role: <scout | planner | implementer | reviewer>
Objective: <one bounded outcome>
Workspace: <absolute canonical path>
Ownership: <named paths the worker may change; say "none" for read-only work>
Do not touch: <unrelated paths, prohibited actions, and authority not granted>
Known context: <facts already verified by Codex; label assumptions>
Acceptance criteria:
- <observable criterion>
Checks: <safe commands or inspections to attempt>
Final response: changed paths, checks/results, limitations, and remaining risks.
```

Keep prompts and captured output in a temporary directory, not in the repository. Do not include secrets, credentials, or tokens in a prompt.

## Scout

Use for a small, well-defined read-only question. Ask for concrete observations, exact paths or symbols, commands attempted, and open questions. The scout must not edit files, create artifacts, change settings, or turn an absence of evidence into a negative claim.

## Planner

Use when the work is ambiguous, unfamiliar, or has meaningful risk. Require a bounded plan, dependencies, risks, alternatives considered, and verification points. Let the planner choose its own route inside the approved objective. It should offer explicit options when a decision changes scope, cost, reversibility, or product behavior. Planning is read-only: no implementation, refactor, generated files, commits, or configuration changes.

## Implementer

Use only for a confirmed write scope. Require a minimal diff, existing project conventions, no drive-by cleanup or dependency additions, and relevant tests/build/lint checks. The worker leaves changes uncommitted; Codex inspects the actual diff and decides whether to keep or correct it. If ambiguity would materially change the diff, choose the most conservative interpretation and flag the alternatives.

## Reviewer

Use as an independent second opinion. State the review subject precisely (working tree, ref, PR, patch, files, plan, or decision); if it is ambiguous, the reviewer must stop and report what is missing. Do not forward the implementer's verdict as evidence.

For code reviews, require findings ranked `critical`, `high`, `medium`, `low`, or `nit`, each with a path/line (or hunk), concrete failure mode, and inspected evidence. Check the original objective and acceptance criteria before judging implementation details. Cover scope drift, completion quality, correctness, project standards, specification alignment, security, and relevant callers/error/concurrency paths. Drop an axis only when the subject plainly has none and say so.

For plan/design reviews, require concrete challenges from first principles, hidden assumptions, simpler alternatives, realistic failure modes/blast radius, evidence quality, and any domain-specific cost, timeline, reversibility, or security concern. Avoid generic caution and manufactured objections.

In every review, separate confirmed findings from unverified concerns. Never edit files, commit, push, or post external comments unless that exact side effect was explicitly authorized and included in the confirmed scope.
