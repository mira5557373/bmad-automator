"""Readiness gate — pre-build story readiness evaluation (§8 module 1, §9.1).

Evaluates whether a story is ready to enter ready-for-dev:
1. Risk profile parsed and scored → priority (P0–P3)
2. forbidden_until ADR dependencies resolved → no open blockers
3. Readiness verdict: READY / BLOCKED / NEEDS_RISK
"""
from __future__ import annotations

import fnmatch
from typing import Any

from .product_profile import required_for_priority
from .risk_profile import (
    aggregate_risk_priority,
    has_unmitigated_risk_9,
    risk_score_to_priority,
    validate_risk_profile,
)

READINESS_VERDICTS = frozenset({"READY", "BLOCKED", "NEEDS_RISK"})


def resolve_story_blockers(
    profile: dict[str, Any],
    story_id: str,
) -> list[dict[str, Any]]:
    mapping = profile.get("forbidden_until") or {}
    blockers: list[dict[str, Any]] = []
    for adr_id in sorted(mapping):
        patterns = mapping[adr_id]
        if not isinstance(patterns, list):
            continue
        for pattern in patterns:
            if fnmatch.fnmatchcase(story_id, pattern):
                blockers.append({
                    "adr_id": adr_id,
                    "patterns": list(patterns),
                    "story_id": story_id,
                })
                break
    return blockers


def format_blocker_summary(blockers: list[dict[str, Any]]) -> str:
    if not blockers:
        return "no blockers"
    parts = [f"{b['adr_id']} blocks {b['story_id']}" for b in blockers]
    return "; ".join(parts)


def check_readiness(
    story_id: str,
    *,
    profile: dict[str, Any],
    risk_entries: list[dict[str, Any]] | None = None,
    thresholds: dict[int, str] | None = None,
) -> dict[str, Any]:
    blockers = resolve_story_blockers(profile, story_id)

    if blockers:
        return {
            "verdict": "BLOCKED",
            "priority": "",
            "blockers": blockers,
            "risk_summary": {},
            "requirements": {},
            "reason": format_blocker_summary(blockers),
        }

    if not risk_entries:
        return {
            "verdict": "NEEDS_RISK",
            "priority": "",
            "blockers": [],
            "risk_summary": {},
            "requirements": {},
            "reason": "no risk profile provided; run TEA risk assessment first",
        }

    validate_risk_profile(risk_entries)
    priority = aggregate_risk_priority(risk_entries)
    if thresholds:
        scores = [e["score"] for e in risk_entries]
        priorities = [risk_score_to_priority(s, thresholds=thresholds) for s in scores]
        priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        priority = min(priorities, key=lambda p: priority_order.get(p, 3))

    max_score = max(e["score"] for e in risk_entries)
    unmitigated = has_unmitigated_risk_9(risk_entries)
    requirements = required_for_priority(profile, priority)

    return {
        "verdict": "READY",
        "priority": priority,
        "blockers": [],
        "risk_summary": {
            "max_score": max_score,
            "entry_count": len(risk_entries),
            "unmitigated_risk_9": unmitigated,
        },
        "requirements": requirements,
        "reason": f"ready for dev at priority {priority}",
    }
