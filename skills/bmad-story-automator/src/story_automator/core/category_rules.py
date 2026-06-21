"""Per-category rule functions for verdict engine (section 6.2, section 12).

Each rule interprets evidence metrics against profile thresholds and
returns a CategoryResult dict: {verdict, required, actual, rationale}.
Pure functions, no I/O.
"""
from __future__ import annotations

from typing import Any

from .product_profile import VALID_PRIORITIES, required_for_priority

_P1_CONCERNS_FLOOR = 80
_DEFAULT_PRIORITY = "P1"


def coverage_verdict(actual_pct: float, target_pct: int, priority: str) -> str:
    """Section 12 TEA coverage thresholds.

    P0: must hit target exactly (100%); below = FAIL.
    P1: >= target = PASS; >= 80% = CONCERNS; < 80% = FAIL.
    P2/P3: >= target = PASS; below = FAIL.
    """
    if target_pct == 0:
        return "PASS"
    if actual_pct >= target_pct:
        return "PASS"
    if priority == "P1" and actual_pct >= _P1_CONCERNS_FLOOR:
        return "CONCERNS"
    return "FAIL"


def risk_to_requirements(
    priority: str, profile: dict[str, Any],
) -> dict[str, Any]:
    """Map risk priority to coverage/level requirements from profile.matrix."""
    if priority not in VALID_PRIORITIES:
        priority = _DEFAULT_PRIORITY
    req = required_for_priority(profile, priority)
    req["priority"] = priority
    return req


_STATUS_SEVERITY = {"ok": 0, "violation": 1, "timeout": 2, "error": 3}


def worst_evidence_status(records: list[dict[str, Any]]) -> str:
    """Find worst status across records. Empty = error (fail-closed)."""
    if not records:
        return "error"
    worst = "ok"
    worst_sev = 0
    for record in records:
        status = record.get("status", "error")
        sev = _STATUS_SEVERITY.get(status, 3)
        if sev > worst_sev:
            worst_sev = sev
            worst = status
    return worst
