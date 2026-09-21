# Installation

[English](INSTALL.md) · [简体中文](INSTALL.zh-CN.md)

## Requirements

- macOS or Linux
- Node.js 18+ for the npm bootstrapper
- Python 3.10+
- Antigravity CLI (`agy`); the bootstrapper can install it from Google's official script when missing
- Codex or Claude Code for the bundled Skill

Mission Control never reads or copies AGY OAuth material. A fresh AGY installation still requires you to run `agy` and complete Google's interactive sign-in.

## Recommended: npm package

`@latest` follows the stable npm release. Pin `@0.4.1` when reproducibility matters; the npm bootstrapper then resolves the matching verified Git tag internally. Pre-releases are published under `@next`; pin `@0.4.2-rc.1` to reproduce the v0.4.2rc1 pre-release.

Preview exact paths without writing:

```bash
npx antigravity-mission-control@latest install --dry-run
```

Interactive install:

```bash
npx antigravity-mission-control@latest install
```

If AGY is already installed, the bootstrapper uses it. If AGY is missing, interactive mode asks whether it should run Google's official installer from `https://antigravity.google/cli/install.sh`.

Install both AGY and Mission Control:

```bash
npx antigravity-mission-control@latest install --install-agy
agy
agy-mc doctor
```

The bootstrapper downloads the official script to a private temporary file, performs basic response checks, and invokes `bash` with an argument array. It does not pipe a network response into a shell. The Google installer may update your shell PATH. Mission Control removes its temporary copy afterward.

Non-interactive installation requires separate flags for Mission Control confirmation and AGY installation:

```bash
npx antigravity-mission-control@latest install --yes --install-agy
```

Omit `--install-agy` when automation has already provisioned and authenticated AGY.

Default managed paths:

| Artifact | Path |
|---|---|
| Python environment | `~/.local/share/antigravity-mission-control/venv` |
| CLI symlink | `~/.local/bin/agy-mc` |
| Codex Skill | `${CODEX_HOME:-~/.codex}/skills/antigravity-mission-control` |
| Claude Code Skill | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills/antigravity-mission-control` |
| Runtime state | `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control` |
| Recoverable Skill backups | `${CODEX_HOME:-~/.codex}/skill-backups/` or `${CLAUDE_CONFIG_DIR:-~/.claude}/skill-backups/` |

Add `~/.local/bin` to `PATH` if the installer reports that it is missing.

## Choosing the host

`--host auto` (the default) installs for every host whose config directory exists (`~/.codex`, `~/.claude`); `update` and `uninstall` act on hosts that already have a managed Skill. Choose explicitly with `--host codex`, `--host claude` or `--host all`. If neither host is detected the installer stops and asks for `--host`.

```bash
npx antigravity-mission-control@latest install --host claude
```

Existing Codex installations keep their paths, marker file and `CODEX_HOME` behavior. `agents/openai.yaml` is Codex-only and is not copied for Claude Code. If no host has a managed Skill, `uninstall` still removes the managed runtime and CLI link. `agy-mc doctor` warns when an installed Skill is older than the CLI.

## Upgrade and status

```bash
npx antigravity-mission-control@latest status
npx antigravity-mission-control@latest update
npx antigravity-mission-control@latest doctor
```

`update` refreshes the managed Python package first, then atomically deploys the bundled Skill and preserves the previous Skill as a timestamped backup.

## Recoverable uninstall

```bash
npx antigravity-mission-control@latest uninstall
```

The Skill is moved to the host's backup directory. The managed Python environment is renamed to a timestamped backup beside its original path. User-owned AGY settings, trust entries, OAuth state and Mission Control job evidence are not deleted.

## Direct Python installation

```bash
python3 -m pip install "git+https://github.com/YuxiaoMa66/antigravity-mission-control.git@v0.4.1"
agy-mc skill install
```

For the v0.4.2rc1 pre-release, use `@v0.4.2rc1` instead of `@v0.4.1`.

Use `agy-mc skill install --dry-run`, `status`, `update`, or `uninstall`. The Python installer operates only on the Skill; it does not create the npm-managed virtual environment or CLI symlink.

## Local development source

```bash
npx antigravity-mission-control install \
  --source "/absolute/path/to/antigravity-mission-control"
```

For automated local testing, add `--yes` and point `HOME`, `CODEX_HOME`, `AGY_MC_INSTALL_ROOT`, `AGY_MC_BIN_DIR`, or `AGY_MC_SKILL_TARGET` at an isolated directory.

## Existing unmanaged Skill

The installer refuses to overwrite an existing directory without its `.agy-mc-install.json` marker. Inspect it first, then use `--force` only if replacement is intended. The old directory is backed up before replacement.

Restart or refresh Codex, or start a new Claude Code session, after installation or upgrade so skill discovery reloads the new files.
