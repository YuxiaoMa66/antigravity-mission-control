# Contributing

Keep changes small, testable, and policy-neutral. Personal workflow preferences belong in `policies/`, not the core runtime. Do not add model slugs as permanent truth; discover them from AGY.

Before submitting a change, run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q antigravity_mission_control scripts tests
npm test
npm pack --dry-run
```

Security-sensitive changes need negative tests for permission scope, prompt exposure, account-data leakage, or lifecycle races as applicable. Do not commit prompts, job state, OAuth material, AGY settings, or provider logs.

Documentation is maintained in pairs: `README.md` / `README.zh-CN.md`, `docs/INSTALL.md` / `docs/INSTALL.zh-CN.md`, `docs/REFERENCE.md` / `docs/REFERENCE.zh-CN.md`, and `docs/RELEASING.md` / `docs/RELEASING.zh-CN.md`.

After changing `SKILL.md`, `agents/`, `policies/`, `references/`, or the compatibility launcher, run `python3 scripts/sync_skill_bundle.py` and include the synchronized package bundle in the same change.
