# Host notes

Codex and Claude Code follow the same workflow in `SKILL.md`; only these mechanics differ. In this file "Claude" is the host, not an AGY worker model.

## Claude Code

- **Roster choice (strict):** write the full A/B/C role tables in your message first, then ask with `AskUserQuestion`: options A, B, C, plus the automatic "Other" for revisions. Option text is too short to carry a roster. Confirm any changed scope, permission profile or executor the same way; a separate decision such as workspace trust can ride in the same `AskUserQuestion` call as a second question, but never fold it into the roster choice.
- **Long jobs:** start the worker with `agy-mc run --background` (it detaches itself; do not also use the Bash tool's background mode), then collect with `agy-mc wait <job-id> --timeout 100s`. The Bash tool times out at 2 minutes by default, so keep each wait under that or raise the tool timeout; on exit code `2` run the same wait again.
- **Permissions:** Claude Code prompts for each new Bash command shape. Suggest the user allow only `Bash(agy-mc *)` in project settings. Never suggest allowing `agy` directly, bypassing permissions, or the `unrestricted` profile to avoid prompts; those need their own explicit confirmation.
- **Sandbox:** job state lives under `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control`, outside the project. If a sandboxed Bash call cannot write there or reach AGY, report the block and let the user decide; do not retry with a wider profile.
- **Discovery:** the skill lives in `${CLAUDE_CONFIG_DIR:-~/.claude}/skills/antigravity-mission-control`. A running session usually lists a newly installed skill after a moment; if it does not, start a new Claude Code session.

## Codex

- **Roster choice (strict):** present the A/B/C tables in chat and wait for the user's reply.
- **Discovery:** the skill lives in `${CODEX_HOME:-~/.codex}/skills/antigravity-mission-control`; invoke it as `$antigravity-mission-control`. Restart or refresh Codex after install or update.
