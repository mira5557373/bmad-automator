"""Gate orchestrator — lifecycle management for production-readiness gate.

Wires the gate step into the orchestrator loop: crash recovery, reuse
validation, drift detection, collect -> adjudicate -> verdict routing,
and atomic-marker semantics.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .collector_registry import CollectorRegistry
from .collector_runner import run_gate_collectors
from .evidence_io import (
    GateMarkerCorruptedError,
    can_reuse_gate_file,
    clear_gate_marker,
    load_gate_file,
    read_gate_marker,
    write_gate_marker,
)
from .gate_audit import (
    GateProfileDriftAudit,
    GateReadinessAudit,
    GateStartedAudit,
    emit_gate_audit,
)
from .gate_schema import GateSchemaError
from .gate_remediation import (
    EditAuthorizationError,
    failing_categories_from_gate,
    prepare_remediation_tasks,
    request_review_continuation,
    write_remediation_to_story,
)
from .gate_status import park_story, record_mitigation_debt
from .product_profile import compute_profile_hash
from .trust_boundary import assert_host_context
from .utils import iso_now
from .verdict_engine import evaluate_gate


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

    Corruption (per §9.2 "loud, not silent"): when the marker file
    exists but cannot be parsed, the partial evidence directory is
    QUARANTINED under ``_bmad/gate/quarantine/<timestamp>/`` instead
    of being deleted, the marker is moved to the quarantine alongside
    it, and the returned dict has ``recovered=False, quarantined=True``
    so the operator can see something needs investigation.

    Returns a dict describing what was recovered.
    """
    assert_host_context("recover_from_crash")

    root = Path(project_root)
    marker_path = root / "_bmad" / "gate" / "gate-in-progress.json"

    try:
        marker = read_gate_marker(project_root)
    except GateMarkerCorruptedError as exc:
        # Don't delete anything. Move the corrupted marker plus any
        # evidence dirs under _bmad/gate/evidence/ into a quarantine
        # bucket so the operator can investigate.
        quarantine_root = root / "_bmad" / "gate" / "quarantine" / iso_now().replace(":", "-")
        try:
            quarantine_root.mkdir(parents=True, exist_ok=True)
            if marker_path.is_file():
                marker_path.rename(quarantine_root / "gate-in-progress.json")
            evidence_root = root / "_bmad" / "gate" / "evidence"
            if evidence_root.is_dir():
                # Move whole evidence root contents under quarantine so the
                # operator can inspect which gate_id was in flight.
                quar_evidence = quarantine_root / "evidence"
                quar_evidence.mkdir(exist_ok=True)
                for child in evidence_root.iterdir():
                    try:
                        (child).rename(quar_evidence / child.name)
                    except OSError:
                        pass
        except OSError:
            # Quarantine itself failing is a separate operator-alertable
            # situation; still surface the corruption.
            pass
        return {
            "recovered": False,
            "quarantined": True,
            "quarantine_dir": str(quarantine_root),
            "corruption_reason": str(exc),
        }

    if marker is None:
        return {"recovered": False}

    gate_id = marker.get("gate_id", "")
    commit_sha = marker.get("commit_sha", "")

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


def run_readiness_gate(
    project_root: str | Path,
    story_id: str,
    *,
    profile: dict[str, Any],
    risk_entries: list[dict[str, Any]] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """§9.1: full readiness lifecycle — risk + blockers → verdict."""
    from .readiness_gate import check_readiness, persist_readiness_result
    from .risk_profile import (
        RiskProfileError,
        compute_risk_profile_ref,
        load_risk_profile,
        persist_risk_profile,
        risk_profile_exists,
    )

    assert_host_context("run_readiness_gate")

    resolved_entries = risk_entries
    if resolved_entries:
        persist_risk_profile(project_root, story_id, resolved_entries)
    elif risk_entries is None and risk_profile_exists(project_root, story_id):
        try:
            risk_data = load_risk_profile(project_root, story_id)
            resolved_entries = risk_data.get("entries")
        except RiskProfileError:
            resolved_entries = None

    result = check_readiness(
        story_id, profile=profile, risk_entries=resolved_entries,
    )

    if resolved_entries:
        result["risk_profile_ref"] = compute_risk_profile_ref(
            resolved_entries, story_id,
        )
    else:
        result["risk_profile_ref"] = ""

    persist_readiness_result(project_root, story_id, result)

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy, audit_path,
            GateReadinessAudit(
                story_id=story_id,
                verdict=result["verdict"],
                priority=result.get("priority", ""),
                blocker_count=len(result.get("blockers", [])),
                reason=result.get("reason", ""),
            ),
        )

    return result


def run_epic_readiness_gate(
    project_root: str | Path,
    epic_id: str,
    story_ids: list[str],
    *,
    profile: dict[str, Any],
    risk_map: dict[str, list[dict[str, Any]]] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """§8 M1: Epic-level readiness lifecycle."""
    from .readiness_gate import check_epic_readiness, persist_readiness_result
    from .risk_profile import persist_risk_profile

    assert_host_context("run_epic_readiness_gate")

    if risk_map:
        for story_id, entries in risk_map.items():
            if entries:
                persist_risk_profile(project_root, story_id, entries)

    result = check_epic_readiness(
        epic_id, story_ids, profile=profile, risk_map=risk_map,
    )

    persist_readiness_result(project_root, epic_id, result)

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy, audit_path,
            GateReadinessAudit(
                story_id=epic_id,
                verdict=result["verdict"],
                priority=result.get("priority", ""),
                blocker_count=len(result.get("blockers", [])),
                reason=result.get("reason", ""),
            ),
        )

    return result


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
    story_path: str | Path | None = None,
) -> dict[str, Any]:
    """Route verdict to action: done, remediate, or park.

    Calling-convention:
    - cycle 0 = first evaluation of a story.
    - On verdict == FAIL with cycle < max_cycles, returns
      {action: "remediate", cycle: cycle+1, ...}. The caller MUST then
      drive a fresh dev-story cycle and call route_gate_verdict again
      with remediation_cycle=cycle+1.
    - When cycle reaches max_cycles, the story is PARKed.
    - When ``story_path`` is provided AND the verdict triggers remediation,
      the [AI-Review] tasks are persisted into that file (§9.2 closes the
      BMAD code-review → review_continuation loop). When omitted, the
      tasks are still returned in the descriptor for the caller to write
      itself — backward-compatible.
    """
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

    # §9.2: persist [AI-Review] tasks to the dev-story file so the next
    # cycle of bmad-dev-story picks them up. Honors edit-authorization
    # (only the Tasks section is touched).
    tasks_persisted = False
    persist_error: str | None = None
    if story_path is not None and tasks:
        try:
            write_remediation_to_story(story_path, tasks)
            tasks_persisted = True
        except (EditAuthorizationError, OSError) as exc:
            # Don't silently swallow — surface in the descriptor so the
            # caller can decide whether to escalate. Verdict-routing
            # continues so the orchestrator gets a usable response.
            persist_error = str(exc)

    descriptor: dict[str, Any] = {
        "action": "remediate", "overall": overall,
        "gate_id": gate_id, "cycle": next_cycle,
        "failing_categories": failing,
        "remediation_tasks": tasks,
        "review_continuation": continuation,
        "tasks_persisted": tasks_persisted,
    }
    if persist_error is not None:
        descriptor["persist_error"] = persist_error
    return descriptor


def resolve_factory_version() -> str:
    """Return the current factory version from the package."""
    from story_automator import __version__
    return __version__
