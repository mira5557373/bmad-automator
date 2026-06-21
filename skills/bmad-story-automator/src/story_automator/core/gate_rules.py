"""Gate verdict rules and waiver validation (§6.3, §6.4).

Pure functions that compute verdicts from evidence and validate waivers.
No I/O — the adjudicator feeds data in, this module returns decisions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .gate_schema import (
    MAX_WAIVER_TTL_DAYS,
    GateSchemaError,
    compute_waiver_signature,
    validate_waiver,
)


class WaiverError(ValueError):
    pass


# TEA priority-threshold semantics (M26).
# Each entry maps priority → (required_pct, fail_floor).
#   coverage >= required_pct      → PASS
#   fail_floor <= coverage < required_pct → CONCERNS
#   coverage < fail_floor         → FAIL
# P3 has a 0 floor so coverage below "required" lands at CONCERNS, never FAIL.
PRIORITY_THRESHOLDS: dict[str, tuple[int, int]] = {
    "P0": (100, 100),
    "P1": (95, 90),
    "P2": (85, 80),
    "P3": (70, 0),
}

# Collection statuses reported per category before adjudication.
# Only COLLECTED categories are eligible to contribute a verdict; the rest
# block gate eligibility (fail-closed).
COLLECTION_STATUSES: frozenset[str] = frozenset(
    {"COLLECTED", "MISSING", "ERROR", "TIMEOUT"},
)


def evaluate_priority_threshold(coverage_pct: float, priority: str) -> str:
    """Map a coverage percentage to a verdict for a given priority band.

    Returns PASS / CONCERNS / FAIL per :data:`PRIORITY_THRESHOLDS`.
    Raises ValueError if the priority is not recognized.
    """
    try:
        required_pct, fail_floor = PRIORITY_THRESHOLDS[priority]
    except KeyError as exc:
        raise ValueError(
            f"unknown priority {priority!r}; "
            f"expected one of {sorted(PRIORITY_THRESHOLDS)}"
        ) from exc
    if coverage_pct >= required_pct:
        return "PASS"
    if coverage_pct >= fail_floor:
        return "CONCERNS"
    return "FAIL"


def gate_eligible(
    category_collection_status: dict[str, str],
    required_categories: set[str],
) -> tuple[bool, str]:
    """Return (eligible, reason).

    Every required category must report ``COLLECTED``. A missing entry,
    a non-COLLECTED status, or an unknown status value blocks gate
    eligibility (fail-closed). Categories outside ``required_categories``
    are ignored.
    """
    blockers: list[str] = []
    for category in sorted(required_categories):
        status = category_collection_status.get(category)
        if status is None:
            blockers.append(f"{category}:MISSING")
            continue
        if status not in COLLECTION_STATUSES:
            blockers.append(f"{category}:UNKNOWN({status})")
            continue
        if status != "COLLECTED":
            blockers.append(f"{category}:{status}")
    if blockers:
        return False, "; ".join(blockers)
    return True, ""


def verdict_for_collector_status(status: str) -> str:
    """Map a collector evidence status to a verdict contribution.

    §6.3: collector status in {error, timeout} → fail-closed (never silent PASS).
    """
    if status in ("error", "timeout"):
        return "FAIL"
    if status == "violation":
        return "FAIL"
    if status == "ok":
        return "PASS"
    return "FAIL"


def verdict_for_llm_confidence(confidence: int) -> str:
    """§6.4: LLM confidence < 5 forces CONCERNS/needs-human."""
    if confidence < 5:
        return "CONCERNS"
    return "PASS"


def verdict_for_invariant_severity(
    severity: str,
    has_violation: bool,
) -> str:
    """§6.4: FAIL-severity invariant violation is a hard FAIL."""
    if not has_violation:
        return "PASS"
    if severity == "FAIL":
        return "FAIL"
    return "CONCERNS"


def verdict_for_cost_tier(
    cost_tier: dict[str, Any] | None,
    forbidden_until: dict[str, Any] | None,
) -> str:
    """§6.4: cost_to_serve renders CONCERNS until DG-2 SKU is defined."""
    if forbidden_until and "DG-2" in forbidden_until:
        return "CONCERNS"
    if cost_tier is None:
        return "CONCERNS"
    if not cost_tier.get("sku_id"):
        return "CONCERNS"
    return "PASS"


def verdict_na(
    rationale: str = "profile-declared N/A",
) -> dict[str, str]:
    """§6.4: emit per-category verdict NA with rationale."""
    return {"verdict": "NA", "rationale": rationale}


def aggregate_verdicts(
    category_verdicts: dict[str, str],
    *,
    has_unmitigated_risk_9: bool = False,
) -> str:
    """§6.3 deterministic verdict aggregation.

    category_verdicts maps category name → per-category verdict
    (PASS | CONCERNS | FAIL | NA).
    """
    active = {
        cat: v for cat, v in category_verdicts.items() if v != "NA"
    }
    if has_unmitigated_risk_9:
        return "FAIL"
    if any(v == "FAIL" for v in active.values()):
        return "FAIL"
    if any(v == "CONCERNS" for v in active.values()):
        return "CONCERNS"
    return "PASS"


def is_waiver_expired(waiver: dict[str, Any], now: datetime | None = None) -> bool:
    """§6.4(e): re-check expires_at on every gate-file reuse."""
    now = now or datetime.now(timezone.utc)
    try:
        expires = _parse_iso(waiver["expires_at"])
    except (KeyError, ValueError) as exc:
        raise WaiverError(f"invalid waiver expires_at: {exc}") from exc
    return now >= expires


def validate_waiver_for_gate(
    waiver: dict[str, Any],
    gate_file: dict[str, Any],
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Full waiver validation per §6.4.

    Returns (valid, reason). Checks:
    (a) expires_at - issued_at <= MAX_WAIVER_TTL
    (b) failing_categories exactly match gate file's failing categories
    (c) signature deterministically computed over canonical-JSON
    (d) profile_hash matches gate file's profile.hash
    (e) expires_at re-checked against current time
    """
    try:
        validate_waiver(waiver)
    except GateSchemaError as exc:
        return False, f"schema: {exc}"

    if is_waiver_expired(waiver, now):
        return False, "waiver expired"

    ok, reason = _check_ttl(waiver)
    if not ok:
        return False, reason

    ok, reason = _check_categories(waiver, gate_file)
    if not ok:
        return False, reason

    ok, reason = _check_signature(waiver)
    if not ok:
        return False, reason

    ok, reason = _check_profile_hash(waiver, gate_file)
    if not ok:
        return False, reason

    return True, ""


def _check_ttl(waiver: dict[str, Any]) -> tuple[bool, str]:
    """§6.4(a): expires_at - issued_at <= MAX_WAIVER_TTL."""
    try:
        issued = _parse_iso(waiver["issued_at"])
        expires = _parse_iso(waiver["expires_at"])
    except (KeyError, ValueError) as exc:
        return False, f"invalid dates: {exc}"
    delta = expires - issued
    max_delta = timedelta(days=MAX_WAIVER_TTL_DAYS)
    if delta > max_delta:
        return False, (
            f"waiver TTL {delta.days}d exceeds max {MAX_WAIVER_TTL_DAYS}d"
        )
    if delta < timedelta(0):
        return False, "expires_at before issued_at"
    return True, ""


def _check_categories(
    waiver: dict[str, Any], gate_file: dict[str, Any],
) -> tuple[bool, str]:
    """§6.4(b): failing_categories must exactly match gate's failing."""
    gate_cats = gate_file.get("categories", {})
    gate_failing = sorted(
        cat for cat, info in gate_cats.items()
        if isinstance(info, dict) and info.get("verdict") == "FAIL"
    )
    waiver_cats = sorted(waiver.get("failing_categories", []))
    if waiver_cats != gate_failing:
        return False, (
            f"waiver categories {waiver_cats} != "
            f"gate failing {gate_failing}"
        )
    return True, ""


def _check_signature(waiver: dict[str, Any]) -> tuple[bool, str]:
    """§6.4(c): signature deterministically computed over canonical-JSON."""
    expected = compute_waiver_signature(waiver)
    actual = waiver.get("signature", "")
    if actual != expected:
        return False, "waiver signature mismatch"
    return True, ""


def _check_profile_hash(
    waiver: dict[str, Any], gate_file: dict[str, Any],
) -> tuple[bool, str]:
    """§6.4(d): profile_hash must equal gate file's profile.hash."""
    gate_hash = (gate_file.get("profile") or {}).get("hash", "")
    waiver_hash = waiver.get("profile_hash", "")
    if not gate_hash:
        return False, "gate file missing profile.hash"
    if waiver_hash != gate_hash:
        return False, (
            f"waiver profile_hash {waiver_hash!r} != "
            f"gate profile.hash {gate_hash!r}"
        )
    return True, ""


def _parse_iso(value: str) -> datetime:
    """Parse ISO 8601 datetime string to timezone-aware datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)
