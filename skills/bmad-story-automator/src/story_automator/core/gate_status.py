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
import os
import pathlib
from pathlib import Path
from typing import Any, Mapping

from .gate_audit import GateParkedAudit, emit_gate_audit
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


# ── Park / resume ───────────────────────────────────────────────────


def park_story(
    project_root: str | Path,
    gate_id: str,
    story_key: str,
    reason: str,
    overall_verdict: str,
    *,
    audit_policy: Mapping[str, Any] | None = None,
    audit_path: pathlib.Path | None = None,
) -> Path:
    """Park a story due to exhaustion or unmitigated risk.

    Stores to ``_bmad/gate/parked/<gate_id>.json``.  Optionally emits
    a ``GateParkedAudit`` event when *audit_policy* and *audit_path*
    are both provided.
    """
    assert_host_context("park_story")
    root = Path(project_root)
    parked_dir = root / "_bmad" / "gate" / "parked"
    ensure_dir(parked_dir)
    record: dict[str, Any] = {
        "gate_id": gate_id,
        "story_key": story_key,
        "reason": reason,
        "overall_verdict": overall_verdict,
        "parked_at": iso_now(),
    }
    target = parked_dir / f"{gate_id}.json"
    write_atomic(target, canonical_json(record) + "\n")
    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy,
            audit_path,
            GateParkedAudit(
                gate_id=gate_id,
                story_key=story_key,
                reason=reason,
                overall_verdict=overall_verdict,
            ),
        )
    return target


def list_parked(
    project_root: str | Path,
    *,
    state_filter: str | None = None,
) -> list[dict[str, Any]]:
    """List parked stories, optionally filtered by reason."""
    parked_dir = Path(project_root) / "_bmad" / "gate" / "parked"
    if not parked_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(parked_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        if state_filter is not None and data.get("reason") != state_filter:
            continue
        records.append(data)
    return records


def resume_story(
    project_root: str | Path,
    gate_id: str,
) -> dict[str, Any] | None:
    """Resume a parked story: remove and return its record."""
    assert_host_context("resume_story")
    target = Path(project_root) / "_bmad" / "gate" / "parked" / f"{gate_id}.json"
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    target.unlink(missing_ok=True)
    return data if isinstance(data, dict) else None


# ── Gate invalidation ───────────────────────────────────────────────


def invalidate_gate(
    project_root: str | Path,
    gate_id: str,
) -> tuple[bool, str]:
    """Invalidate a gate verdict by renaming it to ``<gate_id>.invalidated.json``.

    Returns ``(True, "")`` on success, ``(False, reason)`` when the
    gate file does not exist.
    """
    assert_host_context("invalidate_gate")
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    source = verdicts_dir / f"{gate_id}.json"
    if not source.is_file():
        return False, f"gate file not found: {gate_id}"
    dest = verdicts_dir / f"{gate_id}.invalidated.json"
    os.replace(source, dest)
    return True, ""


def invalidate_gates_for_target(
    project_root: str | Path,
    target_id: str,
) -> list[str]:
    """Invalidate all gate verdicts whose ``target.id`` matches *target_id*.

    Returns the list of gate_ids that were invalidated.
    """
    assert_host_context("invalidate_gates_for_target")
    verdicts_dir = Path(project_root) / "_bmad" / "gate" / "verdicts"
    if not verdicts_dir.is_dir():
        return []
    invalidated: list[str] = []
    for path in sorted(verdicts_dir.glob("*.json")):
        # Skip already-invalidated files
        if path.name.endswith(".invalidated.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        target = data.get("target")
        if isinstance(target, dict) and target.get("id") == target_id:
            gate_id = data.get("gate_id", path.stem)
            dest = verdicts_dir / f"{path.stem}.invalidated.json"
            os.replace(path, dest)
            invalidated.append(gate_id)
    return invalidated
