"""Verdict engine — pure adjudication pipeline (section 6).

Takes collected evidence + profile + risk priority and produces
a deterministic gate file. LLM generates; code decides.

Flow: evidence bundle -> group by category -> per-category rules ->
      aggregate -> waivers -> gate file.
"""
from __future__ import annotations

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
