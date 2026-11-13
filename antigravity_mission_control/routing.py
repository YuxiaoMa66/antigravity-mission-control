"""Model discovery and role-based model selection."""

from __future__ import annotations

import argparse
import json
import re

from .common import AGY_BIN, command_data, run_capture


def execution_models(*efforts: str) -> list[str]:
    return [
        rf"^gemini-\d+(?:[.-]\d+)*-{series}-{effort}$"
        for series in ("hydrogen", "flash")
        for effort in efforts
    ]


GEMINI_HIGH = r"^gemini-(?!.*-(?:flash|hydrogen)-).*-high$"
ARGON_HIGH = r"^gemini-\d+(?:[.-]\d+)*-argon-high$"
EXECUTION_HIGH = execution_models("high")
EXECUTION_REDUCED = execution_models("low", "medium")
A_SCOUT = execution_models("low", "medium", "high")
A_WORK = execution_models("medium", "high", "low")
B_WORK = execution_models("high", "medium", "low")
SONNET = r"claude.*sonnet"
OPUS = r"claude.*opus"
GPT = r"gpt-oss"


STRATEGY_PATTERNS = {
    "A": {
        "scout": [*A_SCOUT, SONNET, GEMINI_HIGH, OPUS, GPT],
        "planner": [*A_WORK, SONNET, GEMINI_HIGH, OPUS, GPT],
        "implementer": [*A_WORK, GEMINI_HIGH, SONNET, OPUS, GPT],
        "reviewer": [*A_WORK, GEMINI_HIGH, SONNET, OPUS, GPT],
    },
    "B": {
        "scout": [*B_WORK, GEMINI_HIGH, SONNET, OPUS, GPT],
        "planner": [ARGON_HIGH, GEMINI_HIGH, OPUS, SONNET, *B_WORK, GPT],
        "implementer": [*B_WORK, GEMINI_HIGH, OPUS, SONNET, GPT],
        "reviewer": [ARGON_HIGH, GEMINI_HIGH, OPUS, SONNET, *B_WORK, GPT],
    },
    "C": dict.fromkeys(("scout", "planner", "implementer", "reviewer"), EXECUTION_HIGH),
}


ROLES = tuple(STRATEGY_PATTERNS["A"])
MODELS_TIMEOUT_SECONDS = 90  # AGY 1.2.9 model listing took about 62 seconds in measurements.


def available_models() -> list[dict[str, str]]:
    proc = run_capture([AGY_BIN, "--output-format", "json", "models"], timeout=MODELS_TIMEOUT_SECONDS)
    if proc.returncode == 0:
        try:
            payload = json.loads(proc.stdout)
            models = command_data(payload).get("models", [])
            if models:
                return [{"id": str(m["id"]), "label": str(m.get("label", m["id"]))} for m in models]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    fallback = run_capture([AGY_BIN, "models"], timeout=MODELS_TIMEOUT_SECONDS)
    models = []
    for line in fallback.stdout.splitlines():
        parts = line.split("\t", 1)
        if parts and re.fullmatch(r"[A-Za-z0-9._-]+", parts[0]):
            models.append({"id": parts[0], "label": parts[1] if len(parts) > 1 else parts[0]})
    if models:
        return models
    detail = (proc.stderr or fallback.stderr or "agy returned no models").strip()
    raise RuntimeError(detail)


def version_key(model_id: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", model_id)[:4])


def family(model_id: str) -> str:
    lowered = model_id.lower()
    for known in ("claude", "gemini", "gpt"):
        if known in lowered:
            return known
    return lowered.split("-", 1)[0]


def is_non_high_gemini(model_id: str) -> bool:
    return family(model_id) == "gemini" and not model_id.lower().endswith(("-high", "-xhigh"))


def is_reduced_claude(model_id: str) -> bool:
    return family(model_id) == "claude" and re.search(r"-(low|medium)$", model_id, re.IGNORECASE) is not None


def select_model(role: str, models: list[dict[str, str]], avoid_family: str | None = None, strategy: str = "A") -> str:
    candidates = [
        m for m in models
        if (
            not is_reduced_claude(m["id"])
            and not is_non_high_gemini(m["id"])
            and not (family(m["id"]) == "gemini" and m["id"].lower().endswith("-xhigh"))
        )
        or any(re.search(pattern, m["id"], re.IGNORECASE) for pattern in EXECUTION_REDUCED)
    ]
    if strategy == "C":
        if avoid_family:
            raise RuntimeError("Strategy C does not support --avoid-family; every AGY call must use Gemini")
    if avoid_family:
        alternatives = [m for m in candidates if family(m["id"]) != avoid_family.lower()]
        if alternatives:
            candidates = alternatives
    for pattern in STRATEGY_PATTERNS[strategy][role]:
        matches = [m["id"] for m in candidates if re.search(pattern, m["id"], re.IGNORECASE)]
        if matches:
            return max(matches, key=lambda slug: (version_key(slug), slug))
    if strategy == "C":
        raise RuntimeError("Strategy C is unavailable: no Gemini Hydrogen High or Flash High model is currently available")
    if candidates:
        return candidates[0]["id"]
    raise RuntimeError("No AGY models are available")


def cmd_models(_args: argparse.Namespace) -> int:
    print(json.dumps({"models": available_models()}, ensure_ascii=False, indent=2))
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    print(select_model(args.role, available_models(), args.avoid_family, args.strategy))
    return 0
