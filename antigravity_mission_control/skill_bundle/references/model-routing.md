# Dynamic model routing

Always discover models at run time with:

```bash
agy-mc models
```

The wrapper uses strategy- and role-oriented preferences rather than assuming a permanent catalog. Use `select` to prepare three proposals; execution always pins the user's approved model.

## Three proposal strategies

| Strategy | Objective | Routing behavior |
| --- | --- | --- |
| A — Lightweight Flash-first | Control cost with the smallest adequate team | Prefer Gemini Flash at role-appropriate intensity; let the host agent own roles where another AGY pass adds little value; keep GPT last. |
| B — Quality-first Flash implementer | Maximize correctness, depth, and independent checking | Prefer Gemini Flash for implementation, use stronger planning/review when needed, and keep GPT last. |
| C — Quality-first Gemini Flash High | Keep B's quality objective while using one Gemini tier | Use the newest exact `gemini-.*flash-high` slug for every AGY role and follow-up; review separation comes from process and host verification. |

Example proposal lookups:

```bash
agy-mc select --strategy A --role implementer
agy-mc select --strategy B --role reviewer --avoid-family claude
agy-mc select --strategy C --role planner
```

These are routing heuristics, not benchmark claims. Increase capability only when task ambiguity, blast radius, or failed attempts justify it. The default A route uses lower Flash intensity for low-risk roles and a stronger Flash fallback for implementation; B puts Flash first for implementation and uses the strongest suitable roles elsewhere. The host agent may pin another available Flash intensity in the approved roster when the task warrants it. Among the listed model tiers, GPT-OSS remains the final fallback in A and B. B implementation proposals try Flash High, then Medium, then Low as preceding tiers become unavailable, before Pro High or Claude; this is catalog-based fallback, not automatic task-risk assessment.

The A and B proposals may surface Gemini Flash medium or low. Other non-High Gemini variants remain excluded from automatic proposals. A proposal is not execution authority: approving a medium/low model still requires explicit confirmation and `--non-high-gemini-confirmed`; the exception is bound to that manifest and does not apply to later calls. C always requires High.

For independent review, pass `--avoid-family` matching the implementer's family (`gemini`, `claude`, or `gpt`) when another suitable family is available. If no alternative exists, use a separate conversation with an adversarial review prompt and disclose that the review was same-family.

`--avoid-family` does not apply to C because C requires Gemini for every AGY call. Gain independence there through separate conversations, adversarial prompts, and host verification. C is the quality-first B shape with the provider route fixed to Gemini Flash High.

Do not select a model by its display label. Use the exact slug returned by `agy models`. A pinned unknown slug fails instead of silently falling back; preserve that behavior.

## AGY parameter compatibility

The official [Headless mode documentation](https://antigravity.google/docs/cli/headless/) lists `--model` and `--effort` as separate optional overrides but does not define how `--effort` maps to Claude or GPT-OSS. Meanwhile, `agy models` exposes provider-specific variants directly in the available model slugs and labels.

For compatibility, this skill pins only the exact `--model` slug and never passes `--effort`:

- Gemini High is expressed by a slug ending in `-high`.
- Claude uses the exact advertised Sonnet/Opus Thinking slug without extra reasoning parameters.
- GPT-OSS uses its exact advertised slug without extra reasoning parameters.

Do not infer provider parameters from another CLI or API. If a future AGY version documents a provider-specific control, update this rule only after checking the installed `agy --help` and official documentation.
