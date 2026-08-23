# Contributing

Keep changes small, testable, and policy-neutral. Personal workflow preferences belong in `policies/`, not the core runtime. Do not add model slugs as permanent truth; discover them from AGY.

Before submitting a change, run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q antigravity_mission_control scripts tests
```

Security-sensitive changes need negative tests for permission scope, prompt exposure, account-data leakage, or lifecycle races as applicable. Do not commit prompts, job state, OAuth material, AGY settings, or provider logs.
