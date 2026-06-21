"""Risk profile schema, validation, and scoring (§6.1, §8 module 1).

Parses the structured risk profile emitted by TEA *risk generators.
Maps Probability×Impact scores (1–9) to priorities (P0–P3) which
drive downstream coverage/level requirements via profile.matrix.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gate_schema import canonical_json
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic


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


_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_SCORE_RANGE = range(1, 10)  # 1–9

DEFAULT_RISK_THRESHOLDS: dict[int, str] = {9: "P0", 6: "P1", 3: "P2", 1: "P3"}


def risk_score_to_priority(
    score: int,
    *,
    thresholds: dict[int, str] | None = None,
) -> str:
    if not isinstance(score, int) or isinstance(score, bool) or score not in _SCORE_RANGE:
        raise RiskProfileError(f"risk score must be 1–9; got {score}")
    thr = thresholds or DEFAULT_RISK_THRESHOLDS
    for threshold in sorted(thr, reverse=True):
        if score >= threshold:
            return thr[threshold]
    return "P3"


def aggregate_risk_priority(entries: list[dict[str, Any]]) -> str:
    validate_risk_profile(entries)
    worst = "P3"
    worst_order = _PRIORITY_ORDER["P3"]
    for entry in entries:
        priority = risk_score_to_priority(entry["score"])
        order = _PRIORITY_ORDER.get(priority, 3)
        if order < worst_order:
            worst = priority
            worst_order = order
    return worst


def has_unmitigated_risk_9(entries: list[dict[str, Any]]) -> bool:
    for entry in entries:
        if entry.get("score", 0) == 9:
            rationale = entry.get("rationale", "")
            if not rationale or not rationale.strip():
                return True
    return False


_RISK_DIR = "risk"
_RISK_PROFILE_VERSION = 1


def _risk_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "_bmad" / "gate" / _RISK_DIR


def persist_risk_profile(
    project_root: str | Path,
    target_id: str,
    entries: list[dict[str, Any]],
    *,
    tier: str = "code",
) -> Path:
    assert_host_context("persist_risk_profile")
    validate_risk_profile(entries)
    risk_d = _risk_dir(project_root)
    ensure_dir(risk_d)
    record: dict[str, Any] = {
        "version": _RISK_PROFILE_VERSION,
        "target_id": target_id,
        "tier": tier,
        "entries": entries,
        "created_at": iso_now(),
    }
    target = risk_d / f"{target_id}.json"
    write_atomic(target, canonical_json(record) + "\n")
    return target


def load_risk_profile(
    project_root: str | Path,
    target_id: str,
) -> dict[str, Any]:
    path = _risk_dir(project_root) / f"{target_id}.json"
    if not path.is_file():
        raise RiskProfileError(f"risk profile not found: {target_id}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RiskProfileError(
            f"risk profile corrupt: {target_id}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RiskProfileError(f"risk profile must be a dict: {target_id}")
    validate_risk_profile(data.get("entries", []))
    return data


def risk_profile_exists(
    project_root: str | Path,
    target_id: str,
) -> bool:
    return (_risk_dir(project_root) / f"{target_id}.json").is_file()


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
