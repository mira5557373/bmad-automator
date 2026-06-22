"""Gate orchestrator — lifecycle management for production-readiness gate.

Wires the gate step into the orchestrator loop: crash recovery, reuse
validation, drift detection, collect -> adjudicate -> verdict routing,
and atomic-marker semantics.
"""
from __future__ import annotations

import shutil
import socket
from pathlib import Path
from typing import Any

import psutil

from .collector_registry import CollectorRegistry
from .collector_runner import run_gate_collectors
from .evidence_io import (
    GateMarkerCorruptedError,
    best_effort_extract_gate_id,
    can_reuse_gate_file,
    clear_gate_marker,
    compute_evidence_bundle_merkle_root,
    get_gate_lock,
    load_evidence_bundle,
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
from .lie_detector import detect_baseline_drift
from .pre_gate_verifier import verify_pre_gate
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


def _quarantine_corrupted_marker(
    root: Path,
    marker_path: Path,
    exc: GateMarkerCorruptedError,
) -> dict[str, Any]:
    """Targeted quarantine for a corrupted gate marker (bug L2 variant).

    The legacy implementation moved EVERY child of ``_bmad/gate/evidence/``
    into quarantine — that broke Merkle reverification of all historical
    gates whenever a single marker went bad. The new policy:

    - Best-effort extract ``gate_id`` from the marker's raw bytes.
    - If extractable: quarantine ONLY ``evidence/<gate_id>/`` (the
      in-flight gate's bundle).
    - If not extractable: quarantine ONLY the marker file. Leave the
      entire evidence/ tree untouched.

    Either way, the audit-floor MarkerCorruptionInvariant contract is
    preserved: ``recovered=False, quarantined=True, quarantine_dir,
    corruption_reason`` — only the SCOPE of what moves changes.
    """
    quarantine_root = (
        root / "_bmad" / "gate" / "quarantine" / iso_now().replace(":", "-")
    )

    # Try to salvage a gate_id from the corrupted bytes. Errors here are
    # non-fatal; missing gate_id just means we narrow further (marker only).
    salvaged_gate_id: str | None = None
    try:
        salvaged_gate_id = best_effort_extract_gate_id(marker_path.read_bytes())
    except OSError:
        salvaged_gate_id = None

    # Fix C-1 (Lens M): track ACTUAL quarantine progress instead of
    # blindly returning quarantined=True. The audit-floor
    # MarkerCorruptionInvariant asserts quarantined=True implies
    # the evidence has been moved; if mkdir fails we never moved
    # anything, so claiming True is an operator-misleading lie.
    quarantine_error: str | None = None
    marker_moved = False
    try:
        quarantine_root.mkdir(parents=True, exist_ok=True)
        if marker_path.is_file():
            marker_path.rename(quarantine_root / "gate-in-progress.json")
            marker_moved = True
        # Targeted quarantine: only the named gate's evidence dir.
        if salvaged_gate_id is not None:
            evidence_dir = (
                root / "_bmad" / "gate" / "evidence" / salvaged_gate_id
            )
            if evidence_dir.is_dir():
                quar_evidence = quarantine_root / "evidence"
                quar_evidence.mkdir(exist_ok=True)
                try:
                    evidence_dir.rename(quar_evidence / salvaged_gate_id)
                except OSError as inner_exc:
                    # Marker is in quarantine; evidence rename failed.
                    # Surface but do not flip quarantined to False —
                    # the marker move was the primary obligation.
                    quarantine_error = (
                        f"evidence rename failed: {inner_exc}"
                    )
    except OSError as outer_exc:
        # Quarantine setup itself failed (e.g., disk full on mkdir).
        # Nothing was moved → quarantined=False is the honest answer.
        quarantine_error = str(outer_exc)

    result: dict[str, Any] = {
        "recovered": False,
        "quarantined": marker_moved,
        "quarantine_dir": str(quarantine_root),
        "corruption_reason": str(exc),
    }
    if quarantine_error is not None:
        result["quarantine_error"] = quarantine_error
    return result


def _recover_from_crash_locked(project_root: str | Path) -> dict[str, Any]:
    """Inner body of :func:`recover_from_crash`, executed under the file lock.

    Split out so the lock acquisition lives in a single context-manager
    block while keeping the legacy single-function contract for callers.
    """
    root = Path(project_root)
    marker_path = root / "_bmad" / "gate" / "gate-in-progress.json"

    try:
        marker = read_gate_marker(project_root)
    except GateMarkerCorruptedError as exc:
        return _quarantine_corrupted_marker(root, marker_path, exc)

    if marker is None:
        return {"recovered": False}

    # L1 + J-03 fix: composite-identity liveness check. If the marker
    # carries a pid that is still running AND the recorded hostname +
    # start_time still identify the SAME process, the gate is in-flight —
    # DO NOT touch its evidence dir, DO NOT clear its marker. The owning
    # process will clean up itself. Otherwise (PID recycled, foreign
    # host, or pid dead) the marker is dead and recovery proceeds.
    pid = marker.get("pid")
    if isinstance(pid, int) and pid > 0:
        marker_host = marker.get("hostname")
        marker_start_time = marker.get("start_time")
        # Foreign-host marker: the local PID table is meaningless. The
        # marker is dead from this host's perspective — recover.
        if (
            isinstance(marker_host, str)
            and marker_host
            and marker_host != socket.gethostname()
        ):
            alive = False
        else:
            try:
                alive = psutil.pid_exists(pid)
            except (psutil.Error, OSError):
                # Fail-closed when psutil can't answer about the PID
                # itself: assume alive so we don't wipe a live gate's
                # evidence. (Legacy markers without pid fall through to
                # the recover path; this branch only runs when pid is
                # present and an integer.)
                alive = True
            # PID-recycle defense: when the marker recorded a
            # start_time, the live PID must ALSO match that
            # process-creation timestamp (1.0s tolerance bridges the
            # resolution gap between time.time-derived recordings and
            # psutil's create_time). Mismatch → PID was recycled by an
            # unrelated process → original owner is gone → recover.
            if alive and isinstance(marker_start_time, (int, float)):
                try:
                    proc_start = psutil.Process(pid).create_time()
                    if abs(proc_start - float(marker_start_time)) >= 1.0:
                        alive = False
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    alive = False
                except (psutil.Error, OSError):
                    # Can't inspect the process — keep alive=True to
                    # stay fail-closed against the L1 wipe scenario.
                    pass
        if alive:
            return {
                "recovered": False,
                "reason": "live-pid-still-running",
                "pid": pid,
                "gate_id": marker.get("gate_id", ""),
            }

    gate_id = marker.get("gate_id", "")
    commit_sha = marker.get("commit_sha", "")

    verdict_path = root / "_bmad" / "gate" / "verdicts" / f"{gate_id}.json"
    had_verdict = verdict_path.is_file()

    # Fix C-3 (Lens M): surface partial rmtree failures instead of
    # silently swallowing the OSError. A partial cleanup leaves
    # half-deleted evidence behind; the marker gets cleared
    # regardless (the recovery contract is "never leave a stale
    # marker"), but the operator now sees ``cleanup_failed=True``
    # + ``cleanup_error`` so they can investigate the half-deleted
    # state.
    cleanup_error: str | None = None
    if not had_verdict:
        evidence_dir = root / "_bmad" / "gate" / "evidence" / gate_id
        if evidence_dir.is_dir():
            try:
                shutil.rmtree(evidence_dir)
            except OSError as exc:
                cleanup_error = str(exc)

    clear_gate_marker(project_root)

    result: dict[str, Any] = {
        "recovered": True,
        "gate_id": gate_id,
        "had_verdict": had_verdict,
        "commit_sha": commit_sha,
    }
    if cleanup_error is not None:
        result["cleanup_failed"] = True
        result["cleanup_error"] = cleanup_error
    return result


def recover_from_crash(
    project_root: str | Path,
) -> dict[str, Any]:
    """Recover from a crashed gate run.

    Reads the gate-in-progress marker.  If present, checks whether a
    verdict was already persisted.  Orphan evidence directories (no
    matching verdict) are removed.  The marker is always cleared.

    Liveness (bug L1): when the marker carries a ``pid`` and that
    process is still alive, recovery is refused with
    ``{recovered: False, reason: "live-pid-still-running", pid: ...}``.
    The owning process owns its own cleanup. Legacy markers without
    ``pid`` are treated as dead (the orchestrator was a single-instance
    affair before this fix).

    Corruption (per §9.2 "loud, not silent"): when the marker file
    exists but cannot be parsed, only the in-flight gate's evidence
    dir (if its gate_id is salvageable from the raw bytes) is moved
    under ``_bmad/gate/quarantine/<timestamp>/``. Historical evidence
    dirs are NOT touched (bug L2 variant — preserves Merkle
    reverification of completed gates). The returned dict still
    carries ``recovered=False, quarantined=True, quarantine_dir,
    corruption_reason`` per the audit-floor invariant.

    The whole operation runs under ``_bmad/gate/.gate.lock`` so it
    cannot race a concurrent ``run_production_gate`` (bug L1).

    Returns a dict describing what was recovered.
    """
    assert_host_context("recover_from_crash")
    with get_gate_lock(project_root):
        return _recover_from_crash_locked(project_root)


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


def _collect_error_evidence(
    project_root: str | Path, gate_id: str,
) -> list[str]:
    """Return ``"<category>/<collector>"`` labels for every error-status
    evidence record persisted under ``gate_id``. Used by the
    ``fail_closed`` policy to decide whether to override the verdict to
    FAIL. Returns ``[]`` if the evidence dir is missing — fail_closed
    cannot meaningfully fire without persisted evidence.
    """
    try:
        bundle = load_evidence_bundle(project_root, gate_id)
    except FileNotFoundError:
        return []
    labels: list[str] = []
    for record in bundle:
        if not isinstance(record, dict):
            continue
        if record.get("status") == "error":
            cat = record.get("category", "?")
            collector = record.get("collector", "?")
            labels.append(f"{cat}/{collector}")
    return labels


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
    enable_lie_detector: bool = False,
    baseline_sha: str | None = None,
    fail_closed: bool = False,
    enable_pre_gate_verifier: bool = False,
    result_json_path: str | Path | None = None,
) -> dict[str, Any]:
    """Full gate lifecycle: crash recovery -> reuse -> [lie-detect] -> collect -> evaluate.

    ``enable_lie_detector`` (Phase 1, default ``False``) toggles the
    baseline-commit drift check before collectors run. When enabled and
    HEAD does not match ``commit_sha``, the call returns a tiny
    descriptor ``{"action": "baseline_drift", "verify": <wire form>,
    "gate_id": ...}`` instead of a full gate file — the orchestrator
    loop interprets this as "re-dispatch the dev session, do not
    persist a verdict". The default-off behavior preserves every
    existing call site exactly; Phase 3 will switch the default once
    the wider pre-gate verifier suite is in place.

    ``baseline_sha`` is the commit the session started from; when
    provided, the lie-detector distinguishes "no commit was made" from
    "branched somewhere unexpected" (see :func:`detect_baseline_drift`).

    ``fail_closed`` (Phase 2, default ``False``) — when True, any
    evidence record with ``status="error"`` forces ``overall=FAIL``
    regardless of the verdict_engine's decision. The override is
    auditable: the returned gate file gains
    ``fail_closed_triggered=True`` and a sorted
    ``fail_closed_categories`` list. ``status="error"`` is what the
    collector_runner stamps on a crashed collector (Phase 1) and what
    timeouts produce — both situations where fail-open might
    let a real bug ship. ``False`` (default) preserves prior behavior:
    error-evidence is still surfaced in categories but the
    verdict_engine decides whether it sinks the gate.

    ``enable_pre_gate_verifier`` (Phase 3, default ``False``) — when
    True, the six inline pre-gate checks
    (``result_present / result_schema / baseline_commit /
    files_present / no_critical_escalations / claimed_files_in_diff``)
    run before any other lifecycle step. ``result_json_path`` is
    required when the verifier is enabled. On the first failing check
    the call returns a descriptor
    ``{"action": "pre_gate_failed", "gate_id": ...,
    "failed_check": "<one of CHECK_NAMES>",
    "verify": <wire form>}`` and never writes a marker or runs
    collectors. The default-off behavior preserves every existing call
    site; flip the default in a future milestone after operator
    confidence is built.
    """
    assert_host_context("run_production_gate")

    if enable_pre_gate_verifier:
        if result_json_path is None:
            raise TypeError(
                "enable_pre_gate_verifier=True requires result_json_path"
            )
        descriptor = verify_pre_gate(
            project_root,
            result_path=result_json_path,
            baseline_sha=baseline_sha,
        )
        if not descriptor["ok"]:
            return {
                "action": "pre_gate_failed",
                "gate_id": gate_id,
                "failed_check": descriptor["failed_check"],
                "verify": descriptor["verify"],
            }

    # L1 fix: serialize the full marker → collectors → clear lifecycle
    # under the gate file lock so concurrent run_production_gate /
    # recover_from_crash calls cannot race on gate-in-progress.json.
    # The timeout is generous (collectors may run for many seconds);
    # callers that need a shorter ceiling can wrap with a shorter
    # acquired lock externally.
    with get_gate_lock(project_root, timeout=3600.0):
        # Recovery runs under the same lock — use the *_locked variant
        # so we don't try to re-acquire (filelock is not re-entrant
        # across separate FileLock instances).
        _recover_from_crash_locked(project_root)

        existing, _ = check_gate_reuse(
            project_root, gate_id, commit_sha, profile, factory_version,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        if existing is not None:
            return existing

        if enable_lie_detector:
            outcome = detect_baseline_drift(
                project_root,
                expected_sha=commit_sha,
                baseline_sha=baseline_sha,
            )
            if not outcome.ok:
                return {
                    "action": "baseline_drift",
                    "gate_id": gate_id,
                    "verify": outcome.to_dict(),
                }

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

    # N5 (G5): export Merkle root so auditors can externally verify the
    # evidence bundle without trusting the factory. Empty bundle returns
    # an empty-string sentinel — distinguishable from a real 64-hex root.
    bundle = load_evidence_bundle(project_root, gate_id)
    if bundle:
        gate_file["evidence_merkle_root"] = compute_evidence_bundle_merkle_root(bundle)
    else:
        gate_file["evidence_merkle_root"] = ""

    if fail_closed:
        error_labels = _collect_error_evidence(project_root, gate_id)
        if error_labels:
            # Audit trail: we always emit the markers when fail_closed
            # is on AND error evidence exists, even if the verdict
            # engine had already sunk the gate to FAIL — the operator
            # needs to see that fail_closed was a factor.
            gate_file["fail_closed_triggered"] = True
            gate_file["fail_closed_categories"] = sorted(set(error_labels))
            gate_file["overall"] = "FAIL"

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
