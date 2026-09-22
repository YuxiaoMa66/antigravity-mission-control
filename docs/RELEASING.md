# Releasing

[English](RELEASING.md) · [简体中文](RELEASING.zh-CN.md)

Mission Control keeps one coordinated release version across its ecosystems:

- Python and Git tag: `0.5.0` / `v0.5.0`
- npm SemVer: `0.5.0`

Both identify the same release. Update `__version__`, `pyproject.toml`, `package.json`, npm bootstrap constants, changelog and bilingual release notes together. Keep historical release notes and assets immutable.

## Release gates

```bash
python3 scripts/sync_skill_bundle.py
python3 -m unittest discover -s tests -v
npm test
python3 -m compileall -q antigravity_mission_control scripts tests
npm pack --dry-run
python3 scripts/agy_delegate.py doctor
python3 scripts/agy_delegate.py usage --format json
git diff --check
git status --short
```

Also run Skill Creator's `quick_validate.py`, inspect the wheel contents, perform npm install/update/uninstall against an isolated `HOME`, and scan the tracked tree for credentials and generated state.

## Real AGY acceptance

The unit tests drive a fake AGY and can only confirm the wrapper matches its own assumptions. Before a stable release, run the acceptance suite against the installed `agy` from the release commit:

```bash
python3 scripts/real_agy_check.py --report real-agy-report.json
```

It covers the offline guards (doctor, unavailable model, non-high Gemini, approval binding, broad workspaces, quota snapshot) and, with one AGY turn each on the latest Gemini Flash High, a foreground run, background collection, `continue`, cancel, a killed worker, an interrupted cancel, a wait timeout, parallel read-only jobs, `--json-schema`, AGY's print timeout, writes in `plan` mode, the editor lock and workspace evidence. Every scenario must pass. Job state lives in a temporary directory; the edit scenarios trust a temporary workspace next to the repository and remove that trust entry afterwards. If a run is killed, the next run (or `--cleanup-only`) removes what it left behind. Use `--offline-only` to check the guards without spending quota, and `-k <name>` to rerun one scenario. When AGY changes its output, fix the wrapper and update `tests/fake_agy.py` to the new shape, so the unit tests keep tracking the real CLI.

## Publication order

1. Push the reviewed `main` commit to GitHub.
2. Create tag `v0.5.0` at that exact commit.
3. Create a GitHub Release from the bilingual notes.
4. Verify Git installation from the tag in an isolated environment.
5. Run `npm publish --tag latest --access public`.
6. Verify `npm view antigravity-mission-control dist-tags` and `npx antigravity-mission-control status`.

The npm bootstrap default source points at the Git tag, so npm must be published only after the GitHub tag is reachable. Trusted Publisher/OIDC is optional; if no publish workflow exists, publish interactively with the maintainer's 2FA. PyPI publication is intentionally deferred; direct Python installs use GitHub.

## Pre-releases

A pre-release spells the version `X.Y.ZrcN` for Python and the Git tag, and `X.Y.Z-rc.N` for npm SemVer. Tag the reviewed commit on its branch and mark the GitHub Release as a pre-release; `main` moves only when the stable version is cut. Publish npm with `npm publish --tag next --access public`, so `latest`, the stable npm package and the stable install instructions stay on the last stable version. Promote a pre-release by cutting the stable version through the gates above.

## Rollback

Do not move or overwrite a published Git tag. Deprecate a broken npm version with a reason, publish a fixed version, and update the `latest` tag. GitHub releases can be marked as withdrawn, but evidence and unfavorable release notes must remain available.
