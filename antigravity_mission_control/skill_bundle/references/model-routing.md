# Dynamic model routing

Always discover models at run time with:

```bash
agy-mc models
```

The wrapper uses strategy- and role-oriented preferences rather than assuming a permanent catalog. Use `select` to prepare three proposals; execution always pins the user's approved model.

## Three proposal strategies

| Strategy | Objective | Routing behavior |
| --- | --- | --- |
| A — Recommended | Best project-specific quality/cost balance | Use the smallest adequate team; prefer efficient models and let Codex own roles where another AGY pass adds little value. |
| B — Best result | Maximize correctness, depth, and independent checking | Prefer the strongest suitable models and cross-family review; accept higher cost and latency. |
| C — Gemini Flash High | Keep every AGY call on one latest fast Gemini tier | Dynamically select the numerically newest available slug matching `gemini-.*flash-high` for every AGY role and follow-up. |

Example proposal lookups:

```bash
agy-mc select --strategy A --role implementer
agy-mc select --strategy B --role reviewer --avoid-family claude
agy-mc select --strategy C --role planner
```

These are routing heuristics, not benchmark claims. Increase capability only when task ambiguity, blast radius, or failed attempts justify it. Prefer the newest available member within the same family and tier.

Gemini has a user-defined hard default: automatically select only slugs ending in `-high`. Do not select or explicitly pin a Gemini medium/low slug until Codex asks the user and receives explicit confirmation. After confirmation, create that run's approval with `--non-high-gemini-confirmed`; the exception is bound to the manifest and does not apply to later calls.

For independent review, pass `--avoid-family` matching the implementer's family (`gemini`, `claude`, or `gpt`) when another suitable family is available. If no alternative exists, use a separate conversation with an adversarial review prompt and disclose that the review was same-family.

`--avoid-family` does not apply to C because C requires Gemini for every AGY call. Gain independence there through separate conversations, adversarial prompts, and Codex verification.

Do not select a model by its display label. Use the exact slug returned by `agy models`. A pinned unknown slug fails instead of silently falling back; preserve that behavior.

## AGY parameter compatibility

The official [Headless mode documentation](https://antigravity.google/docs/cli/headless/) lists `--model` and `--effort` as separate optional overrides but does not define how `--effort` maps to Claude or GPT-OSS. Meanwhile, `agy models` exposes provider-specific variants directly in the available model slugs and labels.

For compatibility, this skill pins only the exact `--model` slug and never passes `--effort`:

- Gemini High is expressed by a slug ending in `-high`.
- Claude uses the exact advertised Sonnet/Opus Thinking slug without extra reasoning parameters.
- GPT-OSS uses its exact advertised slug without extra reasoning parameters.

Do not infer provider parameters from another CLI or API. If a future AGY version documents a provider-specific control, update this rule only after checking the installed `agy --help` and official documentation.
