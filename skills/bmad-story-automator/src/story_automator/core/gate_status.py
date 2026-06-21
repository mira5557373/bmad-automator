"""Gate status helpers: mitigation debt, park/resume, invalidation.

Manages persistent state for stories that have been parked (gated but
not yet remediated), tracks mitigation debt (categories that were
accepted with caveats), and handles gate invalidation on drift.

Artifact layout:
  _bmad/gate/mitigation/<gate_id>.json
  _bmad/gate/parked/<gate_id>.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .gate_schema import canonical_json
from .trust_boundary import assert_host_context
from .utils import ensure_dir, iso_now, write_atomic


# ── Mitigation debt ─────────────────────────────────────────────────


def record_mitigation_debt(
    project_root: str | Path,
    gate_id: str,
    story_key: str,
    categories: list[str],
) -> Path:
    """Record mitigation debt for a gate result.

    Stores to ``_bmad/gate/mitigation/<gate_id>.json``.
    """
    assert_host_context("record_mitigation_debt")
    root = Path(project_root)
    mitigation_dir = root / "_bmad" / "gate" / "mitigation"
    ensure_dir(mitigation_dir)
    record: dict[str, Any] = {
        "gate_id": gate_id,
        "story_key": story_key,
        "categories": categories,
        "recorded_at": iso_now(),
    }
    target = mitigation_dir / f"{gate_id}.json"
    write_atomic(target, canonical_json(record) + "\n")
    return target


def load_mitigation_debt(project_root: str | Path) -> list[dict[str, Any]]:
    """Load all mitigation debt records."""
    mitigation_dir = Path(project_root) / "_bmad" / "gate" / "mitigation"
    if not mitigation_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(mitigation_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            records.append(data)
    return records


def clear_mitigation_debt(
    project_root: str | Path,
    gate_id: str,
) -> bool:
    """Remove a mitigation debt record.  Returns True if removed."""
    assert_host_context("clear_mitigation_debt")
    target = Path(project_root) / "_bmad" / "gate" / "mitigation" / f"{gate_id}.json"
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False
