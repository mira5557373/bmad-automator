"""Gate orchestrator — lifecycle management for production-readiness gate.

Wires the gate step into the orchestrator loop: crash recovery, reuse
validation, drift detection, collect -> adjudicate -> verdict routing,
and atomic-marker semantics.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from .collector_registry import CollectorRegistry
from .collector_runner import run_gate_collectors
from .evidence_io import (
    can_reuse_gate_file,
    clear_gate_marker,
    load_gate_file,
    read_gate_marker,
    write_gate_marker,
)
from .gate_audit import (
    GateCompletedAudit,
    GateProfileDriftAudit,
    GateStartedAudit,
    emit_gate_audit,
)
from .gate_schema import GateSchemaError
from .gate_remediation import (
    failing_categories_from_gate,
    prepare_remediation_tasks,
    request_review_continuation,
)
from .gate_status import park_story, record_mitigation_debt
from .product_profile import compute_profile_hash
from .trust_boundary import assert_host_context
from .verdict_engine import evaluate_gate


_VERDICT_RUNBOOK_REFS: dict[str, str] = {
    "FAIL": "section-4",
    "CONCERNS": "section-2",
    "WAIVED": "section-6",
}


def _runbook_ref_for_verdict(overall: str) -> str:
    return _VERDICT_RUNBOOK_REFS.get(overall, "")


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
            try:
                shutil.rmtree(evidence_dir)
            except OSError:
                pass

    clear_gate_marker(project_root)

    return {
        "recovered": True,
        "gate_id": gate_id,
        "had_verdict": had_verdict,
        "commit_sha": commit_sha,
    }


def _run_collectors(
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
    profile: dict[str, Any],
    registry: CollectorRegistry,
    *,
    diff_categories: set[str] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> list[Any]:
    """Wrapper for testability — delegates to run_gate_collectors."""
    return run_gate_collectors(
        project_root, gate_id, commit_sha, profile, registry,
        diff_categories=diff_categories,
        audit_policy=audit_policy, audit_path=audit_path,
    )


def run_production_gate(
    project_root: str | Path,
    gate_id: str,
    *,
    commit_sha: str,
    target: dict[str, str],
    profile: dict[str, Any],
    factory_version: str,
    registry: CollectorRegistry,
    priority: str = "P1",
    has_unmitigated_risk_9: bool = False,
    waivers: list[dict[str, Any]] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Full gate lifecycle: crash recovery -> reuse -> collect -> evaluate."""
    assert_host_context("run_production_gate")

    recover_from_crash(project_root)

    existing, _ = check_gate_reuse(
        project_root, gate_id, commit_sha, profile, factory_version,
        audit_policy=audit_policy, audit_path=audit_path,
    )
    if existing is not None:
        return existing

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy, audit_path,
            GateStartedAudit(
                gate_id=gate_id, commit_sha=commit_sha,
                profile_hash=compute_profile_hash(profile),
            ),
        )

    _start = time.monotonic()
    write_gate_marker(project_root, gate_id, commit_sha)
    try:
        _run_collectors(
            project_root, gate_id, commit_sha, profile, registry,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        gate_file = evaluate_gate(
            project_root, gate_id,
            commit_sha=commit_sha, target=target,
            profile=profile, factory_version=factory_version,
            priority=priority,
            has_unmitigated_risk_9=has_unmitigated_risk_9,
            waivers=waivers,
            audit_policy=audit_policy, audit_path=audit_path,
        )
    finally:
        clear_gate_marker(project_root)

    duration_ms = int((time.monotonic() - _start) * 1000)
    gate_file["duration_ms"] = duration_ms

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy, audit_path,
            GateCompletedAudit(
                gate_id=gate_id,
                overall=gate_file.get("overall", ""),
                duration_ms=duration_ms,
                commit_sha=commit_sha,
                runbook_ref=_runbook_ref_for_verdict(
                    gate_file.get("overall", ""),
                ),
            ),
        )

    return gate_file


def route_gate_verdict(
    project_root: str | Path,
    gate_file: dict[str, Any],
    *,
    story_key: str,
    remediation_cycle: int = 0,
    max_cycles: int = 3,
    has_unmitigated_risk_9: bool = False,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Route verdict to action: done, remediate, or park."""
    assert_host_context("route_gate_verdict")
    overall = gate_file.get("overall", "FAIL")
    gate_id = gate_file.get("gate_id", "")

    if overall == "PASS":
        return {"action": "done", "commit": True, "overall": "PASS"}

    if overall == "WAIVED":
        return {"action": "done", "commit": True, "waived": True, "overall": "WAIVED"}

    if overall == "CONCERNS":
        concerns_cats = [
            cat for cat, info in gate_file.get("categories", {}).items()
            if isinstance(info, dict) and info.get("verdict") == "CONCERNS"
        ]
        record_mitigation_debt(project_root, gate_id, story_key, concerns_cats)
        return {
            "action": "done", "commit": True,
            "overall": "CONCERNS", "mitigation_debt": concerns_cats,
        }

    # Fail-closed: unrecognized verdicts are treated as FAIL
    if overall not in ("FAIL", "PASS", "WAIVED", "CONCERNS"):
        overall = "FAIL"

    if has_unmitigated_risk_9:
        park_story(
            project_root, gate_id, story_key,
            "risk-9", overall,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        return {
            "action": "park", "reason": "risk-9",
            "overall": overall, "gate_id": gate_id,
        }

    if remediation_cycle >= max_cycles:
        park_story(
            project_root, gate_id, story_key,
            "exhausted", overall,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        return {
            "action": "park", "reason": "exhausted",
            "overall": overall, "gate_id": gate_id,
        }

    failing = failing_categories_from_gate(gate_file)
    tasks = prepare_remediation_tasks(gate_file)
    next_cycle = remediation_cycle + 1
    continuation = request_review_continuation(
        story_key=story_key,
        gate_id=gate_id,
        cycle=next_cycle,
        failing_categories=failing,
    )
    return {
        "action": "remediate", "overall": overall,
        "gate_id": gate_id, "cycle": next_cycle,
        "failing_categories": failing,
        "remediation_tasks": tasks,
        "review_continuation": continuation,
    }


def resolve_factory_version() -> str:
    """Return the current factory version from the package."""
    from story_automator import __version__
    return __version__
