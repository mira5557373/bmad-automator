"""Gate orchestrator: reuse checks with drift detection and crash recovery.

Coordinates gate lifecycle at the top level. Before running a full
collector loop, ``check_gate_reuse`` determines whether a prior gate
file can be reused (same commit, profile, and factory version).
``recover_from_crash`` cleans up stale markers and orphan evidence
left by an interrupted gate run.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .evidence_io import (
    can_reuse_gate_file,
    clear_gate_marker,
    load_gate_file,
    read_gate_marker,
)
from .gate_audit import GateProfileDriftAudit, emit_gate_audit
from .gate_schema import GateSchemaError
from .product_profile import compute_profile_hash
from .trust_boundary import assert_host_context


def check_gate_reuse(
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
    profile: dict[str, Any],
    factory_version: str,
    *,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Check whether an existing gate file can be reused.

    Returns ``(gate_file, "")`` when reusable, or ``(None, reason)``
    when the gate must be re-evaluated.  Emits a
    :class:`GateProfileDriftAudit` when audit args are supplied and
    reuse is rejected.
    """
    try:
        gate_file = load_gate_file(project_root, gate_id)
    except GateSchemaError:
        return None, f"gate file not found or invalid: {gate_id}"

    current_hash = compute_profile_hash(profile)
    reusable, reason = can_reuse_gate_file(
        gate_file,
        commit_sha=commit_sha,
        profile_hash=current_hash,
        factory_version=factory_version,
    )
    if reusable:
        return gate_file, ""

    if audit_policy is not None and audit_path is not None:
        old_hash = (gate_file.get("profile") or {}).get("hash", "")
        old_fv = gate_file.get("factory_version", "")
        emit_gate_audit(
            audit_policy,
            audit_path,
            GateProfileDriftAudit(
                gate_id=gate_id,
                old_hash=old_hash,
                new_hash=current_hash,
                old_factory_version=old_fv,
                new_factory_version=factory_version,
                reason=reason,
            ),
        )

    return None, reason


def recover_from_crash(
    project_root: str | Path,
) -> dict[str, Any]:
    """Recover from a crashed gate run.

    Reads the gate-in-progress marker.  If present, checks whether a
    verdict was already persisted.  Orphan evidence directories (no
    matching verdict) are removed.  The marker is always cleared.

    Returns a dict describing what was recovered.
    """
    assert_host_context("recover_from_crash")

    marker = read_gate_marker(project_root)
    if marker is None:
        return {"recovered": False}

    gate_id = marker.get("gate_id", "")
    commit_sha = marker.get("commit_sha", "")
    root = Path(project_root)

    verdict_path = root / "_bmad" / "gate" / "verdicts" / f"{gate_id}.json"
    had_verdict = verdict_path.is_file()

    if not had_verdict:
        evidence_dir = root / "_bmad" / "gate" / "evidence" / gate_id
        if evidence_dir.is_dir():
            shutil.rmtree(evidence_dir)

    clear_gate_marker(project_root)

    return {
        "recovered": True,
        "gate_id": gate_id,
        "had_verdict": had_verdict,
        "commit_sha": commit_sha,
    }
