# Installation

[English](INSTALL.md) · [简体中文](INSTALL.zh-CN.md)

## Requirements

- macOS or Linux
- Node.js 18+ for the npm bootstrapper
- Python 3.10+
- Antigravity CLI (`agy`); the bootstrapper can install it from Google's official script when missing
- Codex for the bundled Skill

Mission Control never reads or copies AGY OAuth material. A fresh AGY installation still requires you to run `agy` and complete Google's interactive sign-in.

## Recommended: npm bootstrap

Preview exact paths without writing:

```bash
npx antigravity-mission-control@next install --dry-run
```

Interactive install:

```bash
npx antigravity-mission-control@next install
```

If AGY is already installed, the bootstrapper uses it. If AGY is missing, interactive mode asks whether it should run Google's official installer from `https://antigravity.google/cli/install.sh`.

Install both AGY and Mission Control:

```bash
npx antigravity-mission-control@next install --install-agy
agy
agy-mc doctor
```

The bootstrapper downloads the official script to a private temporary file, performs basic response checks, and invokes `bash` with an argument array. It does not pipe a network response into a shell. The Google installer may update your shell PATH. Mission Control removes its temporary copy afterward.

Non-interactive installation requires separate flags for Mission Control confirmation and AGY installation:

```bash
npx antigravity-mission-control@next install --yes --install-agy
```

Omit `--install-agy` when automation has already provisioned and authenticated AGY.

Default managed paths:

| Artifact | Path |
|---|---|
| Python environment | `~/.local/share/antigravity-mission-control/venv` |
| CLI symlink | `~/.local/bin/agy-mc` |
| Codex Skill | `${CODEX_HOME:-~/.codex}/skills/antigravity-mission-control` |
| Runtime state | `${XDG_STATE_HOME:-~/.local/state}/antigravity-mission-control` |
| Recoverable Skill backups | `${CODEX_HOME:-~/.codex}/skill-backups/` |

Add `~/.local/bin` to `PATH` if the installer reports that it is missing.

## Upgrade and status

```bash
npx antigravity-mission-control@next status
npx antigravity-mission-control@next update
npx antigravity-mission-control@next doctor
```

`update` refreshes the managed Python package first, then atomically deploys the bundled Skill and preserves the previous Skill as a timestamped backup.

## Recoverable uninstall

```bash
npx antigravity-mission-control@next uninstall
```

The Skill is moved to Codex's backup directory. The managed Python environment is renamed to a timestamped backup beside its original path. User-owned AGY settings, trust entries, OAuth state and Mission Control job evidence are not deleted.

## Direct Python installation

```bash
python3 -m pip install "git+https://github.com/YuxiaoMa66/antigravity-mission-control.git@v0.1.0a4"
agy-mc skill install
```

Use `agy-mc skill install --dry-run`, `status`, `update`, or `uninstall`. The Python installer operates only on the Skill; it does not create the npm-managed virtual environment or CLI symlink.

## Local development source

```bash
npx antigravity-mission-control install \
  --source "/absolute/path/to/antigravity-mission-control"
```

For automated local testing, add `--yes` and point `HOME`, `CODEX_HOME`, `AGY_MC_INSTALL_ROOT`, `AGY_MC_BIN_DIR`, or `AGY_MC_SKILL_TARGET` at an isolated directory.

## Existing unmanaged Skill

The installer refuses to overwrite an existing directory without its `.agy-mc-install.json` marker. Inspect it first, then use `--force` only if replacement is intended. The old directory is backed up before replacement.

Restart or refresh Codex after installation or upgrade so skill discovery reloads the new files.
