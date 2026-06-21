"""Profile calibrator — auto-tuning proposals with safety bounds.

Analyzes gate metrics and proposes profile adjustments: timeout
increases for recurring timeouts, burn-in N for flaky tests.
All proposals carry a confidence score and change_type classification
(feature vs breaking).

Safety: breaking changes are never auto-applied by default; max change
bounds prevent runaway calibration.
"""
from __future__ import annotations

import copy as _copy
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


MAX_BURNIN_RUNS = 20
BURNIN_INCREMENT = 2
DEFAULT_BURNIN_RUNS = 5


def propose_burnin_calibrations(
    metrics: dict[str, Any],
    profile: dict[str, Any],
) -> list[CalibrationProposal]:
    """Propose burn-in N increase when flaky tests detected."""
    flaky_cats = metrics.get("flaky_categories", [])
    if not flaky_cats:
        return []

    rules = profile.get("rules") or {}
    tq_rules = rules.get("test_quality") or {}
    current_burnin = tq_rules.get("burn_in_runs", DEFAULT_BURNIN_RUNS)
    proposed = min(current_burnin + BURNIN_INCREMENT, MAX_BURNIN_RUNS)
    if proposed <= current_burnin:
        return []

    return [CalibrationProposal(
        category=cat,
        field_path="rules.test_quality.burn_in_runs",
        old_value=current_burnin,
        new_value=proposed,
        rationale=(
            f"flaky category {cat} detected; "
            f"raising burn-in from {current_burnin} to {proposed}"
        ),
        confidence=0.8,
        change_type="breaking",
    ) for cat in flaky_cats]


def propose_all_calibrations(
    metrics: dict[str, Any],
    profile: dict[str, Any],
) -> list[CalibrationProposal]:
    """Aggregate all calibration proposals."""
    proposals: list[CalibrationProposal] = []
    proposals.extend(propose_timeout_calibrations(metrics, profile))
    proposals.extend(propose_burnin_calibrations(metrics, profile))
    return proposals


def apply_calibrations(
    profile: dict[str, Any],
    proposals: list[CalibrationProposal],
    *,
    auto_apply_breaking: bool = False,
) -> tuple[dict[str, Any], list[CalibrationProposal], list[CalibrationProposal]]:
    """Apply calibration proposals to a profile copy.

    Feature-type proposals auto-apply. Breaking-type proposals are
    deferred unless auto_apply_breaking is True. Returns
    (updated_profile, applied_proposals, deferred_proposals).
    """
    result = _copy.deepcopy(profile)
    applied: list[CalibrationProposal] = []
    deferred: list[CalibrationProposal] = []

    for proposal in proposals:
        if proposal.change_type == "breaking" and not auto_apply_breaking:
            deferred.append(proposal)
            continue
        _set_nested(result, proposal.field_path, proposal.new_value)
        applied.append(proposal)

    return result, applied, deferred


def _set_nested(obj: dict[str, Any], path: str, value: Any) -> None:
    """Set a value at a dotted path in a nested dict, creating intermediates."""
    parts = path.split(".")
    for part in parts[:-1]:
        if part not in obj or not isinstance(obj[part], dict):
            obj[part] = {}
        obj = obj[part]
    obj[parts[-1]] = value
