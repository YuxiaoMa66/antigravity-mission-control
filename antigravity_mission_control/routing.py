"""Model discovery and role-based model selection."""

from __future__ import annotations

import argparse
import json
import re

from .common import AGY_BIN, command_data, run_capture


FLASH_LOW = r"gemini-.*flash-low$"


FLASH_MEDIUM = r"gemini-.*flash-medium$"


FLASH_HIGH = r"gemini-.*flash-high$"


STRATEGY_PATTERNS = {
    "A": {
        "scout": [FLASH_LOW, FLASH_MEDIUM, FLASH_HIGH, r"claude.*sonnet", r"gemini-.*pro-high$", r"claude.*opus", r"gpt-oss"],
        "planner": [FLASH_MEDIUM, FLASH_HIGH, FLASH_LOW, r"claude.*sonnet", r"gemini-.*pro-high$", r"claude.*opus", r"gpt-oss"],
        "implementer": [FLASH_MEDIUM, FLASH_HIGH, FLASH_LOW, r"gemini-.*pro-high$", r"claude.*sonnet", r"claude.*opus", r"gpt-oss"],
        "reviewer": [FLASH_MEDIUM, FLASH_HIGH, FLASH_LOW, r"gemini-.*pro-high$", r"claude.*sonnet", r"claude.*opus", r"gpt-oss"],
    },
    "B": {
        "scout": [r"claude.*opus", r"gemini-.*pro-high$", r"claude.*sonnet", FLASH_HIGH, FLASH_MEDIUM, FLASH_LOW, r"gpt-oss"],
        "planner": [r"claude.*opus", r"gemini-.*pro-high$", r"claude.*sonnet", FLASH_HIGH, FLASH_MEDIUM, FLASH_LOW, r"gpt-oss"],
        "implementer": [FLASH_HIGH, FLASH_MEDIUM, FLASH_LOW, r"gemini-.*pro-high$", r"claude.*opus", r"claude.*sonnet", r"gpt-oss"],
        "reviewer": [r"claude.*opus", r"gemini-.*pro-high$", r"claude.*sonnet", FLASH_HIGH, FLASH_MEDIUM, FLASH_LOW, r"gpt-oss"],
    },
    "C": {
        "scout": [FLASH_HIGH],
        "planner": [FLASH_HIGH],
        "implementer": [FLASH_HIGH],
        "reviewer": [FLASH_HIGH],
    },
}


ROLES = tuple(STRATEGY_PATTERNS["A"])


def available_models() -> list[dict[str, str]]:
    proc = run_capture([AGY_BIN, "--output-format", "json", "models"])
    if proc.returncode == 0:
        try:
            payload = json.loads(proc.stdout)
            models = command_data(payload).get("models", [])
            if models:
                return [{"id": str(m["id"]), "label": str(m.get("label", m["id"]))} for m in models]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    fallback = run_capture([AGY_BIN, "models"])
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
    return family(model_id) == "gemini" and not model_id.lower().endswith("-high")


def select_model(role: str, models: list[dict[str, str]], avoid_family: str | None = None, strategy: str = "A") -> str:
    candidates = [
        m for m in models
        if not is_non_high_gemini(m["id"])
        or re.search(FLASH_LOW, m["id"], re.IGNORECASE)
        or re.search(FLASH_MEDIUM, m["id"], re.IGNORECASE)
    ]
    if strategy == "C":
        if avoid_family:
            raise RuntimeError("Strategy C does not support --avoid-family; every AGY call must use Gemini")
        candidates = [m for m in candidates if re.search(FLASH_HIGH, m["id"], re.IGNORECASE)]
        if not candidates:
            raise RuntimeError("Strategy C is unavailable: no Gemini Flash High model is currently available")
    if avoid_family:
        alternatives = [m for m in candidates if family(m["id"]) != avoid_family.lower()]
        if alternatives:
            candidates = alternatives
    for pattern in STRATEGY_PATTERNS[strategy][role]:
        matches = [m["id"] for m in candidates if re.search(pattern, m["id"], re.IGNORECASE)]
        if matches:
            return max(matches, key=version_key)
    if candidates:
        return candidates[0]["id"]
    raise RuntimeError("No AGY models are available")


def cmd_models(_args: argparse.Namespace) -> int:
    print(json.dumps({"models": available_models()}, ensure_ascii=False, indent=2))
    return 0


def cmd_select(args: argparse.Namespace) -> int:
    print(select_model(args.role, available_models(), args.avoid_family, args.strategy))
    return 0
