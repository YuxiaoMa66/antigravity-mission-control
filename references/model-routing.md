# Dynamic model routing

Always discover models at run time with:

```bash
agy-mc models
```

The wrapper uses strategy- and role-oriented preferences rather than assuming a permanent catalog. Use `select` to prepare three proposals; execution always pins the user's approved model.

## Three proposal strategies

| Strategy | Objective | Routing behavior |
| --- | --- | --- |
| A — Lightweight | Use role-appropriate reasoning for the smallest adequate team | Scout tries Hydrogen Low, Medium, then High. Other roles try Medium, High, then Low. |
| B — Quality-first | Use faster workers for execution and deeper models for planning and review | Scout and implementer try Hydrogen High, Medium, then Low. Planner and reviewer prefer Argon High. |
| C — Quality-first Gemini High | Use one execution model for every role | Use the newest Hydrogen High or, when unavailable, the newest Flash High. |

Example proposal lookups:

```bash
agy-mc select --strategy A --role implementer
agy-mc select --strategy B --role reviewer --avoid-family claude
agy-mc select --strategy C --role planner
```

Where A and B propose Hydrogen, they try the listed effort order within Hydrogen first, then within Flash. B planners and reviewers try Argon High, other non-Hydrogen and non-Flash Gemini High models, Claude Opus, and Claude Sonnet before trying Hydrogen and Flash. Consider Carbon for complex work when the catalog lists its exact slug.

When the B planning or review proposal is a deep-reasoning Gemini and Claude Opus is also available, offer the Gemini proposal and Opus as a choice for each role. Use `agy-mc select --strategy B --role reviewer --avoid-family gemini` to look up the review alternative.

A and B may propose Hydrogen or Flash Medium and Low. These variants require explicit confirmation and `--non-high-gemini-confirmed` on the manifest. Pin a catalog-listed Gemini XHigh model explicitly under A or B using normal roster approval. C uses High for every role.

The selector reads the live catalog and orders versions numerically within each series and effort, so a slug such as `gemini-4.10-hydrogen-high` takes precedence over `gemini-4.9-hydrogen-high` regardless of catalog order. A new series name or slug format needs a routing review before joining the Hydrogen/Flash route. Use the exact discovered slug when pinning another available model. Existing approvals and follow-ups keep their pinned model while that slug remains available.

For independent review, pass `--avoid-family` matching the implementer's family (`gemini`, `claude`, or `gpt`) when another suitable family is available. If no alternative exists, use a separate conversation with an adversarial review prompt and disclose that the review was same-family.

`--avoid-family` does not apply to C because C requires Gemini for every AGY call. Gain independence there through separate conversations, adversarial prompts, and host verification. C is the quality-first B shape with the provider route fixed to Gemini Hydrogen High with Flash High fallback.

Do not select a model by its display label. Use the exact slug returned by `agy models`. A pinned unknown slug fails instead of silently falling back; preserve that behavior.

## AGY parameter compatibility

The official [Headless mode documentation](https://antigravity.google/docs/cli/headless/) lists `--model` and `--effort` as separate optional overrides but does not define how `--effort` maps to Claude or GPT-OSS. Meanwhile, `agy models` exposes provider-specific variants directly in the available model slugs and labels.

For compatibility, this skill pins only the exact `--model` slug and never passes `--effort`:

- Gemini High and XHigh use exact slugs ending in `-high` and `-xhigh`, respectively.
- Claude uses the exact advertised Sonnet/Opus Thinking slug without extra reasoning parameters.
- GPT-OSS uses its exact advertised slug without extra reasoning parameters.

Do not infer provider parameters from another CLI or API. If a future AGY version documents a provider-specific control, update this rule only after checking the installed `agy --help` and official documentation.
