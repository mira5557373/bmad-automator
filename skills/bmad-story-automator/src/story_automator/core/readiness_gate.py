"""Readiness gate — pre-build story readiness evaluation (§8 module 1, §9.1).

Evaluates whether a story is ready to enter ready-for-dev:
1. Risk profile parsed and scored → priority (P0–P3)
2. forbidden_until ADR dependencies resolved → no open blockers
3. Readiness verdict: READY / BLOCKED / NEEDS_RISK
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Any

from .gate_schema import canonical_json
from .product_profile import required_for_priority
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic
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


def check_epic_readiness(
    epic_id: str,
    story_ids: list[str],
    *,
    profile: dict[str, Any],
    risk_map: dict[str, list[dict[str, Any]]] | None = None,
    thresholds: dict[int, str] | None = None,
) -> dict[str, Any]:
    """§8 M1: Epic-level implementation-readiness check."""
    if not story_ids:
        return {
            "verdict": "NEEDS_RISK",
            "epic_id": epic_id,
            "priority": "",
            "story_results": {},
            "blockers": [],
            "reason": "no stories provided for epic readiness check",
        }

    _risk_map = risk_map or {}
    story_results: dict[str, dict[str, Any]] = {}
    worst_verdict = "READY"
    worst_priority = "P3"
    _order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    all_blockers: list[dict[str, Any]] = []

    for story_id in story_ids:
        result = check_readiness(
            story_id, profile=profile,
            risk_entries=_risk_map.get(story_id),
            thresholds=thresholds,
        )
        story_results[story_id] = result
        v = result["verdict"]
        if v == "BLOCKED":
            worst_verdict = "BLOCKED"
            all_blockers.extend(result.get("blockers", []))
        elif v == "NEEDS_RISK" and worst_verdict != "BLOCKED":
            worst_verdict = "NEEDS_RISK"
        p = result.get("priority", "")
        if p and _order.get(p, 3) < _order.get(worst_priority, 3):
            worst_priority = p

    return {
        "verdict": worst_verdict,
        "epic_id": epic_id,
        "priority": worst_priority if worst_verdict == "READY" else "",
        "story_results": story_results,
        "blockers": all_blockers,
        "reason": _epic_readiness_reason(worst_verdict, story_ids, story_results),
    }


def _epic_readiness_reason(
    verdict: str,
    story_ids: list[str],
    story_results: dict[str, dict[str, Any]],
) -> str:
    total = len(story_ids)
    if verdict == "READY":
        return f"all {total} stories ready"
    if verdict == "BLOCKED":
        blocked = sum(
            1 for r in story_results.values() if r["verdict"] == "BLOCKED"
        )
        return f"{blocked} of {total} stories blocked"
    needs = sum(
        1 for r in story_results.values() if r["verdict"] == "NEEDS_RISK"
    )
    return f"{needs} of {total} stories need risk assessment"


def validate_story_creation(
    story_id: str,
    *,
    profile: dict[str, Any],
    risk_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """§8 M1: Validate prerequisites for story creation."""
    result = check_readiness(
        story_id, profile=profile, risk_entries=risk_entries,
    )
    return {
        "can_create": result["verdict"] == "READY",
        "verdict": result["verdict"],
        "reason": result["reason"],
        "priority": result.get("priority", ""),
        "requirements": result.get("requirements", {}),
        "blockers": result.get("blockers", []),
    }


_READINESS_DIR = "readiness"


def _readiness_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "_bmad" / "gate" / _READINESS_DIR


def persist_readiness_result(
    project_root: str | Path,
    story_id: str,
    result: dict[str, Any],
) -> Path:
    assert_host_context("persist_readiness_result")
    readiness_d = _readiness_dir(project_root)
    ensure_dir(readiness_d)
    record: dict[str, Any] = {
        "story_id": story_id,
        "checked_at": iso_now(),
    }
    record.update(result)
    target = readiness_d / f"{story_id}.json"
    write_atomic(target, canonical_json(record) + "\n")
    return target


def load_readiness_result(
    project_root: str | Path,
    story_id: str,
) -> dict[str, Any] | None:
    path = _readiness_dir(project_root) / f"{story_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None
