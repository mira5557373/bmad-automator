"""Verdict engine — pure adjudication pipeline (section 6).

Takes collected evidence + profile + risk priority and produces
a deterministic gate file. LLM generates; code decides.

Flow: evidence bundle -> group by category -> per-category rules ->
      aggregate -> waivers -> gate file.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def group_evidence_by_category(
    evidence: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group evidence records by their category field."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in evidence:
        cat = record.get("category", "unknown")
        grouped.setdefault(cat, []).append(record)
    return grouped


def has_llm_low_confidence(records: list[dict[str, Any]]) -> bool:
    """True if any non-deterministic evidence has confidence < 5."""
    for record in records:
        if not record.get("deterministic", True):
            confidence = record.get("confidence")
            if isinstance(confidence, int) and confidence < 5:
                return True
    return False


def compute_category_verdict(
    category: str,
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Compute verdict for a single category.

    Applies category rule, then checks LLM confidence.
    FAIL from rule is never upgraded; PASS may downgrade to CONCERNS.
    """
    from .category_rules import apply_category_rule
    from .evidence_io import evidence_filename

    result = apply_category_rule(category, evidence, profile, required)
    refs = [evidence_filename(r) for r in evidence]
    result["evidence_refs"] = refs

    if result["verdict"] == "PASS" and has_llm_low_confidence(evidence):
        result["verdict"] = "CONCERNS"
        result["rationale"] = "low LLM confidence (<5) on evidence; " + result.get("rationale", "")

    return result


def compute_all_verdicts(
    evidence_bundle: list[dict[str, Any]],
    profile: dict[str, Any],
    priority: str,
) -> dict[str, dict[str, Any]]:
    """Compute verdicts for all categories.

    Categories in categories_na -> NA.
    Categories with evidence -> computed verdict.
    Active categories without evidence -> fail-closed.
    """
    from .category_rules import risk_to_requirements
    from .gate_rules import verdict_na

    required = risk_to_requirements(priority, profile)
    grouped = group_evidence_by_category(evidence_bundle)
    na_cats = set(profile.get("categories_na") or [])
    active_cats: set[str] = set()
    for tier_cats in (profile.get("categories") or {}).values():
        if isinstance(tier_cats, list):
            active_cats.update(tier_cats)
    all_cats = active_cats | set(grouped.keys()) | na_cats

    verdicts: dict[str, dict[str, Any]] = {}
    for cat in sorted(all_cats):
        if cat in na_cats:
            na_result = verdict_na()
            na_result["required"] = {}
            na_result["actual"] = {}
            na_result["evidence_refs"] = []
            verdicts[cat] = na_result
            continue
        cat_evidence = grouped.get(cat, [])
        if not cat_evidence and cat in active_cats:
            verdicts[cat] = {
                "verdict": "FAIL",
                "required": {},
                "actual": {"status": "missing"},
                "rationale": f"no evidence collected for active category {cat}",
                "evidence_refs": [],
            }
            continue
        if cat_evidence:
            verdicts[cat] = compute_category_verdict(cat, cat_evidence, profile, required)

    return verdicts


def adjudicate(
    evidence_bundle: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    priority: str = "P1",
    has_unmitigated_risk_9: bool = False,
) -> dict[str, Any]:
    """Section 6.3: pure verdict engine.

    evidence -> per-category verdicts -> aggregate -> result.
    Deterministic: same inputs -> same output.
    """
    from .evidence_io import compute_evidence_bundle_hash
    from .gate_rules import aggregate_verdicts
    from .product_profile import compute_profile_hash

    categories = compute_all_verdicts(evidence_bundle, profile, priority)
    flat_verdicts = {cat: info["verdict"] for cat, info in categories.items()}
    overall = aggregate_verdicts(flat_verdicts, has_unmitigated_risk_9=has_unmitigated_risk_9)

    return {
        "categories": categories,
        "overall": overall,
        "evidence_bundle_hash": compute_evidence_bundle_hash(evidence_bundle),
        "profile_hash": compute_profile_hash(profile),
    }


def apply_waivers(
    adjudication: dict[str, Any],
    waivers: list[dict[str, Any]],
    gate_file_stub: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    """Section 6.4: validate waivers and apply if valid.

    Returns (overall_verdict, valid_waivers, rationale).
    WAIVED only if original overall is FAIL and all failing
    categories are covered by valid, unexpired waivers.
    """
    from .gate_rules import validate_waiver_for_gate

    original_overall = adjudication.get("overall", "FAIL")
    if original_overall == "PASS":
        return "PASS", [], ""
    if not waivers:
        return original_overall, [], "no waivers provided"

    valid_waivers: list[dict[str, Any]] = []
    rejection_reasons: list[str] = []
    for waiver in waivers:
        ok, reason = validate_waiver_for_gate(waiver, gate_file_stub, now=now)
        if ok:
            valid_waivers.append(waiver)
        else:
            rejection_reasons.append(f"waiver {waiver.get('waiver_id', '?')}: {reason}")

    if valid_waivers and original_overall == "FAIL":
        return "WAIVED", valid_waivers, "all failing categories waived"

    rationale = "; ".join(rejection_reasons) if rejection_reasons else "waivers not applicable"
    return original_overall, valid_waivers, rationale
