"""Gate operations — operational helpers for day-to-day gate management.

Query, health-check, metrics, and remediation-bridge functions that
build on the M10 gate primitives without modifying them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .evidence_io import read_gate_marker
from .gate_remediation import write_remediation_to_story

__all__ = [
    "list_verdicts",
    "gate_doctor",
    "apply_remediation",
]


def list_verdicts(
    project_root: str | Path,
    *,
    target_filter: str | None = None,
    verdict_filter: str | None = None,
) -> list[dict[str, Any]]:
    """List all gate verdict summaries, optionally filtered."""
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    if not verdicts_dir.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(verdicts_dir.glob("*.json")):
        if path.name.endswith(".invalidated.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        target = data.get("target", {})
        target_id = target.get("id", "") if isinstance(target, dict) else ""
        overall = data.get("overall", "")
        if target_filter is not None and target_id != target_filter:
            continue
        if verdict_filter is not None and overall != verdict_filter:
            continue
        profile = data.get("profile", {})
        results.append({
            "gate_id": data.get("gate_id", path.stem),
            "target": target,
            "overall": overall,
            "commit_sha": data.get("commit_sha", ""),
            "factory_version": data.get("factory_version", ""),
            "profile_id": profile.get("id", "") if isinstance(profile, dict) else "",
        })
    return results


def gate_doctor(project_root: str | Path) -> dict[str, Any]:
    """Validate gate infrastructure consistency."""
    root = Path(project_root)
    gate_dir = root / "_bmad" / "gate"
    checks: list[str] = []
    issues: list[dict[str, str]] = []

    checks.append("orphan_marker")
    marker = read_gate_marker(project_root)
    if marker is not None:
        issues.append({
            "type": "orphan_marker",
            "detail": f"gate-in-progress marker exists for gate_id={marker.get('gate_id', '?')}",
        })

    checks.append("orphan_evidence")
    evidence_dir = gate_dir / "evidence"
    verdicts_dir = gate_dir / "verdicts"
    if evidence_dir.is_dir():
        for child in sorted(evidence_dir.iterdir()):
            if child.is_dir():
                verdict_path = verdicts_dir / f"{child.name}.json"
                if not verdict_path.is_file():
                    issues.append({
                        "type": "orphan_evidence",
                        "detail": f"evidence dir '{child.name}' has no matching verdict",
                    })

    checks.append("verdict_validity")
    if verdicts_dir.is_dir():
        for path in sorted(verdicts_dir.glob("*.json")):
            if path.name.endswith(".invalidated.json"):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "gate_id" not in data:
                    issues.append({
                        "type": "invalid_verdict",
                        "detail": f"verdict '{path.name}' missing required fields",
                    })
            except (json.JSONDecodeError, OSError):
                issues.append({
                    "type": "invalid_verdict",
                    "detail": f"verdict '{path.name}' contains invalid JSON",
                })

    return {
        "healthy": len(issues) == 0,
        "checks": checks,
        "issues": issues,
    }


def apply_remediation(
    story_path: str | Path,
    route_result: dict[str, Any],
) -> dict[str, Any]:
    """Bridge route_gate_verdict's remediate action to story write-back."""
    if route_result.get("action") != "remediate":
        raise ValueError(
            f"apply_remediation requires action='remediate', got '{route_result.get('action')}'"
        )
    tasks = route_result.get("remediation_tasks", [])
    write_remediation_to_story(story_path, tasks)
    return {
        "applied": True,
        "tasks_written": len(tasks),
        "review_continuation": route_result.get("review_continuation", {}),
    }
