# Releasing

[English](RELEASING.md) · [简体中文](RELEASING.zh-CN.md)

Mission Control has two version strings by ecosystem:

- Python and Git tag: `0.1.0a2` / `v0.1.0a2`
- npm SemVer: `0.1.0-alpha.2`

Both identify the same release. Update `VERSION`, `__version__`, `pyproject.toml`, `package.json`, npm bootstrap constants, changelog and release notes together.

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

## Publication order

1. Push the reviewed `main` commit to GitHub.
2. Create tag `v0.1.0a2` at that exact commit.
3. Create a GitHub Pre-release from the bilingual notes.
4. Verify Git installation from the tag in an isolated environment.
5. Run `npm publish --tag next --access public`.
6. Verify `npm view antigravity-mission-control dist-tags` and `npx antigravity-mission-control status`.

The npm bootstrap default source points at the Git tag, so npm must be published only after the GitHub tag is reachable. PyPI publication is intentionally deferred for the Alpha; direct Python installs use GitHub.

## Rollback

Do not move or overwrite a published Git tag. Deprecate a broken npm version with a reason, publish a fixed version, and update the `next` tag. GitHub releases can be marked as withdrawn, but evidence and unfavorable release notes must remain available.
