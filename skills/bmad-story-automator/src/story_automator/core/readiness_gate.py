"""Readiness gate — pre-build story readiness evaluation (§8 module 1, §9.1).

Evaluates whether a story is ready to enter ready-for-dev:
1. Risk profile parsed and scored → priority (P0–P3)
2. forbidden_until ADR dependencies resolved → no open blockers
3. Readiness verdict: READY / BLOCKED / NEEDS_RISK
"""
from __future__ import annotations

import fnmatch
from typing import Any


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
