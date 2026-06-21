"""Profile calibrator — auto-tuning proposals with safety bounds.

Analyzes gate metrics and proposes profile adjustments: timeout
increases for recurring timeouts, burn-in N for flaky tests.
All proposals carry a confidence score and change_type classification
(feature vs breaking).

Safety: breaking changes are never auto-applied by default; max change
bounds prevent runaway calibration.
"""
from __future__ import annotations

import dataclasses
from typing import Any

from .product_profile import DEFAULT_TIMEOUT_FALLBACK, DEFAULT_TIMEOUTS


MAX_TIMEOUT_MULTIPLIER = 2.0
TIMEOUT_INCREASE_FACTOR = 1.5
MIN_TIMEOUT = 30


@dataclasses.dataclass(frozen=True)
class CalibrationProposal:
    category: str
    field_path: str
    old_value: Any
    new_value: Any
    rationale: str
    confidence: float
    change_type: str  # "feature" or "breaking"


def propose_timeout_calibrations(
    metrics: dict[str, Any],
    profile: dict[str, Any],
) -> list[CalibrationProposal]:
    """Propose timeout increases for categories with recurring timeouts."""
    timeout_cats = metrics.get("timeout_categories", [])
    if not timeout_cats:
        return []

    profile_timeouts = profile.get("timeouts") or {}
    proposals: list[CalibrationProposal] = []
    for cat in timeout_cats:
        current = profile_timeouts.get(
            cat, DEFAULT_TIMEOUTS.get(cat, DEFAULT_TIMEOUT_FALLBACK),
        )
        cat_stats = (metrics.get("per_category") or {}).get(cat, {})
        total = sum(
            cat_stats.get(k, 0)
            for k in ("pass_count", "fail_count", "concerns_count")
        )
        timeout_count = cat_stats.get("timeout_count", 0)
        if total == 0:
            continue
        timeout_rate = timeout_count / total
        proposed = min(
            int(current * TIMEOUT_INCREASE_FACTOR),
            int(current * MAX_TIMEOUT_MULTIPLIER),
        )
        if proposed <= current:
            continue
        proposals.append(CalibrationProposal(
            category=cat,
            field_path=f"timeouts.{cat}",
            old_value=current,
            new_value=proposed,
            rationale=f"timeout rate {timeout_rate:.0%} over {total} runs",
            confidence=min(0.5 + timeout_rate, 0.95),
            change_type="feature",
        ))
    return proposals
