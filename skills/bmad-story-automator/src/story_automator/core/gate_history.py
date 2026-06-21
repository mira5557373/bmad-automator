"""Gate history store — persistent record of gate results for learning.

Records gate outcomes for cross-story/cross-sprint analysis, pattern
detection, and profile auto-tuning.  Storage layout:
    _bmad/gate/history/<timestamp>-<gate_id>.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gate_schema import canonical_json
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic


_HISTORY_DIR = Path("_bmad") / "gate" / "history"


def make_history_record(
    gate_file: dict[str, Any],
    *,
    story_key: str,
    remediation_cycle: int = 0,
) -> dict[str, Any]:
    """Extract learning-relevant fields from a gate file."""
    profile = gate_file.get("profile") or {}
    categories_raw = gate_file.get("categories") or {}
    categories = {}
    for cat, info in categories_raw.items():
        if isinstance(info, dict):
            categories[cat] = {
                "verdict": info.get("verdict", ""),
                "rationale": info.get("rationale", ""),
            }
    return {
        "gate_id": gate_file.get("gate_id", ""),
        "story_key": story_key,
        "commit_sha": gate_file.get("commit_sha", ""),
        "overall": gate_file.get("overall", ""),
        "categories": categories,
        "profile_id": profile.get("id", ""),
        "profile_hash": profile.get("hash", ""),
        "factory_version": gate_file.get("factory_version", ""),
        "recorded_at": iso_now(),
        "remediation_cycle": remediation_cycle,
        "evidence_bundle_hash": gate_file.get("evidence_bundle_hash", ""),
    }


def record_gate_result(
    project_root: str | Path,
    gate_file: dict[str, Any],
    *,
    story_key: str,
    remediation_cycle: int = 0,
) -> Path:
    """Persist a gate result to the history store."""
    assert_host_context("record_gate_result")
    record = make_history_record(
        gate_file, story_key=story_key,
        remediation_cycle=remediation_cycle,
    )
    history_dir = Path(project_root) / _HISTORY_DIR
    ensure_dir(history_dir)
    timestamp = (
        record["recorded_at"]
        .replace("-", "").replace(":", "")
        .replace("T", "-").replace("Z", "")
    )
    gate_id = record["gate_id"]
    filename = f"{timestamp}-{gate_id}.json"
    target = history_dir / filename
    write_atomic(target, canonical_json(record) + "\n")
    return target


def load_gate_history(
    project_root: str | Path,
    *,
    since: str | None = None,
    profile_id: str | None = None,
    story_key: str | None = None,
    overall: str | None = None,
) -> list[dict[str, Any]]:
    """Load history records, optionally filtered."""
    history_dir = Path(project_root) / _HISTORY_DIR
    if not history_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if profile_id and data.get("profile_id") != profile_id:
            continue
        if story_key and data.get("story_key") != story_key:
            continue
        if overall and data.get("overall") != overall:
            continue
        if since and data.get("recorded_at", "") < since:
            continue
        records.append(data)
    return records


def count_gate_history(project_root: str | Path) -> int:
    """Count history entries without parsing JSON."""
    history_dir = Path(project_root) / _HISTORY_DIR
    if not history_dir.is_dir():
        return 0
    return len(list(history_dir.glob("*.json")))


def prune_gate_history(
    project_root: str | Path,
    *,
    max_age_days: int = 90,
    max_records: int = 1000,
) -> int:
    """Remove old history entries. Returns count pruned.

    Prunes entries older than max_age_days AND trims to max_records
    (keeping the newest). Age pruning runs first.
    """
    assert_host_context("prune_gate_history")
    history_dir = Path(project_root) / _HISTORY_DIR
    if not history_dir.is_dir():
        return 0

    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    files = sorted(history_dir.glob("*.json"))
    pruned = 0

    surviving: list[Path] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            surviving.append(path)
            continue
        recorded = data.get("recorded_at", "") if isinstance(data, dict) else ""
        if recorded and recorded < cutoff_iso:
            path.unlink(missing_ok=True)
            pruned += 1
        else:
            surviving.append(path)

    if len(surviving) > max_records:
        to_remove = surviving[: len(surviving) - max_records]
        for path in to_remove:
            path.unlink(missing_ok=True)
            pruned += 1

    return pruned
