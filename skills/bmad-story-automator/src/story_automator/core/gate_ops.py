"""Gate operations — operational helpers for day-to-day gate management.

Query, health-check, metrics, and remediation-bridge functions that
build on the M10 gate primitives without modifying them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "list_verdicts",
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
