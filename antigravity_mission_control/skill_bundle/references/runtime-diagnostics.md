# AGY runtime diagnostics

Use this reference before a first run in a new environment, after a wrapper error, or before deciding whether a retry is justified.

## Classify the failure

1. Confirm `command -v agy`, `agy --version`, and `agy models`. A model-list success does not prove that generation is authorized for the current account.
2. Inspect the wrapper's stderr and temporary diagnostics. Do not rely on a generic `Agent execution terminated due to error` message when a log contains a more specific cause.
3. Distinguish the result shape:
   - `SUCCESS` with a response: worker produced output; inspect the workspace independently.
   - non-success with an empty response: worker failed; do not claim partial completion.
   - non-success with a complete response: `done_with_warnings`; deliver the response, surface the warning, and verify it independently.

The wrapper starts in standard permission handling. If the confirmed roster needs unrestricted tool access, obtain the separate explicit confirmation, create an approval with `--permission-profile unrestricted --unrestricted-confirmed`, then run with `--unrestricted --approval-file <manifest>`. Never infer this from workspace trust or silently fall back to unrestricted after a denial.

## Common classes

- `operation not permitted`, `bind`, hidden OAuth state, or a false authentication failure: the harness sandbox may be blocking AGY's localhost language server or credential access. If unrestricted execution has been separately approved, use the wrapper's explicit unrestricted profile; otherwise run the approved command outside that sandbox or ask the user for the specific access. Do not retry the same sandboxed command or add a blanket bypass implicitly.
- `403`, `PERMISSION_DENIED`, or a pre-invocation authorization failure: treat it as an account/service permission problem unless the diagnostic clearly identifies a local sandbox. Do not change the prompt or silently switch models. Ask the user to refresh/login or confirm model/service entitlement, then rerun the same approved roster only after the environment changes.
- Expired authentication: ask the user to complete the interactive AGY login flow. Do not expose tokens or copy credential files.
- Unknown or unavailable model: rerun `agy models`, stop, and reconfirm the affected roster entry before changing the model.
- Soft-denied tool permission after trust: treat the run as failed. Codex may perform the safe in-scope check directly; do not infer that workspace trust authorizes unrelated commands.
- Timeout: inspect whether useful output or edits exist, then retry at most once with a larger timeout or a narrower task. Use the exact prior conversation id when a continuation is appropriate.

## Retry rule

Retry only when the diagnostic names a transient timeout or the user has corrected the named environment/authentication issue. Do not retry with a different role, model, permission profile, workspace, or scope without roster reconfirmation. Preserve the original error and the exact corrective condition in the final report.
