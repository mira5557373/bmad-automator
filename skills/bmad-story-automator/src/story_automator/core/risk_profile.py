"""Risk profile schema, validation, and scoring (§6.1, §8 module 1).

Parses the structured risk profile emitted by TEA *risk generators.
Maps Probability×Impact scores (1–9) to priorities (P0–P3) which
drive downstream coverage/level requirements via profile.matrix.
"""
from __future__ import annotations

from typing import Any


class RiskProfileError(ValueError):
    pass


VALID_RISK_CATEGORIES = frozenset({"TECH", "SEC", "PERF", "DATA", "BUS", "OPS"})

_PROBABILITY_RANGE = range(1, 4)  # 1–3
_IMPACT_RANGE = range(1, 4)       # 1–3


def validate_risk_entry(entry: dict[str, Any]) -> None:
    if not isinstance(entry, dict):
        raise RiskProfileError("risk entry must be a dict")
    category = entry.get("category")
    if not isinstance(category, str) or category not in VALID_RISK_CATEGORIES:
        raise RiskProfileError(
            f"risk entry category must be one of "
            f"{sorted(VALID_RISK_CATEGORIES)}; got {category!r}"
        )
    _validate_int_range(entry, "probability", _PROBABILITY_RANGE)
    _validate_int_range(entry, "impact", _IMPACT_RANGE)
    score = entry.get("score")
    if not isinstance(score, int) or isinstance(score, bool):
        raise RiskProfileError("risk entry score must be an integer")
    expected = entry["probability"] * entry["impact"]
    if score != expected:
        raise RiskProfileError(
            f"risk entry score must equal probability × impact "
            f"({expected}); got {score}"
        )
    rationale = entry.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        raise RiskProfileError("risk entry rationale must be a string")


def validate_risk_profile(entries: Any) -> None:
    if not isinstance(entries, list):
        raise RiskProfileError("risk profile must be a list of entries")
    if not entries:
        raise RiskProfileError("risk profile must have at least one entry")
    seen: set[str] = set()
    for entry in entries:
        validate_risk_entry(entry)
        cat = entry["category"]
        if cat in seen:
            raise RiskProfileError(f"duplicate risk category: {cat}")
        seen.add(cat)


def make_risk_entry(
    category: str,
    probability: int,
    impact: int,
    *,
    rationale: str = "",
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "category": category,
        "probability": probability,
        "impact": impact,
        "score": probability * impact,
    }
    if rationale:
        entry["rationale"] = rationale
    validate_risk_entry(entry)
    return entry


def _validate_int_range(
    obj: dict[str, Any], key: str, valid_range: range,
) -> None:
    val = obj.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise RiskProfileError(f"risk entry {key} must be an integer")
    if val not in valid_range:
        raise RiskProfileError(
            f"risk entry {key} must be {valid_range.start}–"
            f"{valid_range.stop - 1}; got {val}"
        )
