# Approval and continuation

Read for a new dispatch, in-scope follow-up, correction, or a change to approved scope. Confirmation flags assert an existing user decision; they do not create authorization or prove human consent. Record consequential choices in the task's durable decision log.

## Effective policy

`agy-mc policy strict` and `agy-mc policy balanced` report the bundled settings. New manifests bind the complete policy; execution rejects a changed policy. Both require an exact model and separate unrestricted approval. The strict policy additionally requires the caller to assert that A/B/C were presented. `balanced` omits that assertion only after the user chooses the lighter flow.

The CLI validates the assertion and manifest fields, not whether a conversation actually contained three complete proposals. Assignment ownership remains a prompt contract; workspace trust and the editing lock do not enforce per-file permissions. The two-correction limit applies to a recorded lineage, not a global account budget or all branches of a conversation.

## New assignment

After approval of a strict roster, create a short-lived manifest:

```bash
agy-mc approve \
  --policy strict --three-rosters-presented \
  --strategy A --role implementer --model <exact-approved-slug> \
  --cwd /absolute/project/path --prompt-file /private/path/prompt.txt \
  --mode accept-edits --expires-minutes 60 --confirmed
```

For an approved balanced flow, use `--policy balanced` and omit `--three-rosters-presented`. The `--confirmed` assertion still applies.

Use the returned `--approval-file` with `run`. The signed manifest binds strategy, role, model, canonical workspace, original prompt hash, mode, permission profile, non-high Gemini exception, conversation, policy, lineage and expiration. If a bound field changes, create a new manifest. The CLI appends observed workspace context after checking the original prompt; its evidence records both original and dispatched prompt hashes.

## Signed workspace scope and required checks

Opt into signed workspace-scope enforcement by supplying `--allowed-path` options during `approve`. Scoped bindings require `accept-edits` mode, `--cwd` set to the Git repository root with a valid HEAD, and a complete workspace snapshot without limitations:

```bash
agy-mc approve \
  --policy balanced \
  --strategy A --role implementer --model <exact-approved-slug> \
  --cwd /absolute/project/path --prompt-file /private/path/prompt.txt \
  --mode accept-edits --expires-minutes 60 --confirmed \
  --allowed-path src/ \
  --allowed-path package.json \
  --forbidden-path src/secret/ \
  --required-check test \
  --base-commit <exact-40-hex-HEAD>
```

- `--allowed-path <rule>`: repeatable. At least one rule activates scoped enforcement.
- `--forbidden-path <rule>`: repeatable. Forbidden rules override allowed rules. Reject if no `--allowed-path` is passed.
- `--required-check <id>`: repeatable check IDs defined in `.agy-mc/checks.json` (`agy-mc-checks.v1`). Reject if no `--allowed-path` is passed. `.agy-mc/checks.json` is automatically added as a forbidden exact path when checks are selected.
- `--base-commit <hash>`: optional exact 40-hex commit hash matching current Git HEAD.
- **Path rule syntax**: Repository-root-relative POSIX strings only. Reject absolute paths, backslashes, empty/root rules, traversal (`.`, `..`), duplicate separators (`//`), and glob metacharacters (`*`, `?`, `[]`, `{}`). A trailing slash denotes a directory prefix; otherwise the rule is an exact file. Directory semantics are never inferred from filesystem state.
- **System-forbidden paths**: Every scoped approval automatically forbids both `.git` and `.git/`. These rules also reject allowed-scope symlinks resolving to Git metadata. Required checks additionally forbid `.agy-mc/checks.json`.
- **Preflight digest**: Signs `base_commit` and deterministic `preflight_sha256` covering repository, HEAD, status sha256, diff hashes, and sorted path details (untracked content fingerprints and symlink targets), excluding timestamps. Run preflight recomputes this snapshot and rejects before worker invocation on commit drift or dirty/untracked workspace drift. Foreground edits re-verify after obtaining the workspace lock, and background workers validate while holding the inherited lock.

## Follow-up and correction

For a completed policy-bound job, preserve its exact recorded assignment and conversation. Use `approve` with the same fields and either:

- `--correction-of <parent-job-id>`: increments the parent's correction count and rejects a count above two;
- `--follow-up-of <parent-job-id>`: preserves the count for an ordinary in-scope follow-up.

Pass `--conversation <recorded-id>`. The policy must match the parent. These operations reuse the prior roster decision, so `--three-rosters-presented` is unnecessary. Use `--confirmed` backed by the existing authorization; changed scope still requires a new decision.

When the parent job is scoped, the approval inherits the parent's exact `allowed_paths`, `forbidden_paths`, and frozen `required_checks` without requiring duplicated CLI flags, while capturing a fresh `base_commit` and preflight snapshot for the new run. Scope lineage authority is derived from and verified against the parent's private signed `approval.json` and its HMAC (permitting reading expired completed approvals for lineage verification). Any tampering with or mismatch in mutable `job.json` scope metadata is rejected. If scope flags are provided, they must equal the parent's exact scope; widening or altering rules is rejected. Corrections of unscoped jobs cannot add scope rules.

Continuing a policy-bound job always requires a signed `--approval-file` created with `--correction-of` or `--follow-up-of`; legacy `--roster-approved` cannot downgrade a recorded lineage to an unscoped run.

Then collect a new background job:

```bash
agy-mc continue <parent-job-id> \
  --prompt-file /private/path/follow-up.txt \
  --approval-file /private/path/new-approval.json --background
```

For an already approved unrestricted profile, include `--unrestricted` on continue as on run. Creating its manifest requires `--permission-profile unrestricted --unrestricted-confirmed`. Do not silently widen or downgrade the approved profile.

Corrections must be labelled honestly. The CLI cannot infer semantic scope or prevent a caller from declaring a new root task. Do not reset the count by mislabelling a correction, branching from an older job, or using legacy flags. At the limit, diagnose and record the revised user decision.

## Separate trust

Only after authorization of the exact workspace trust mutation:

```bash
agy-mc workspace --cwd /absolute/project/path \
  --mode accept-edits --grant --trust-approved
```

Unrestricted execution is separate from trust. A non-high Gemini exception is also separately bound with `--non-high-gemini-confirmed`.

## Legacy compatibility

Pre-policy signed manifests and deprecated boolean run flags remain usable for migration; their policy and correction lineage are unrecorded. Do not claim runtime correction enforcement for these runs. Start a newly approved root task to establish policy tracking; existing historical jobs and evidence are preserved.
