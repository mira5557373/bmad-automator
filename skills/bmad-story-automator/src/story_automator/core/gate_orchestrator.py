"""Gate orchestrator — lifecycle management for production-readiness gate.

Wires the gate step into the orchestrator loop: crash recovery, reuse
validation, drift detection, collect -> adjudicate -> verdict routing,
and atomic-marker semantics.
"""
from __future__ import annotations

import os
import shutil
import socket
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import psutil
from filelock import Timeout

if TYPE_CHECKING:
    from .innovation.spec_drift_watcher import SpecDriftWatcher
    from .innovation.threshold_proposer import ThresholdProposer
    from .usage_parsers import UsageMetrics

from .collector_isolation import _validate_isolation_kwargs
from .collector_registry import CollectorRegistry
from .collector_runner import run_gate_collectors
from .evidence_io import (
    GateMarkerCorruptedError,
    _validate_gate_id,
    best_effort_extract_gate_id,
    can_reuse_gate_file,
    clear_gate_marker,
    compute_evidence_bundle_merkle_root,
    gate_lock_path,
    get_gate_cleanup_root,
    get_gate_lock,
    load_gate_file,
    read_gate_marker,
    run_cleanup_janitor,
    write_gate_marker,
)
from .gate_lock_observability import _handle_gate_lock_timeout
from .gate_audit import (
    GateProfileDriftAudit,
    GateReadinessAudit,
    GateStartedAudit,
    emit_gate_audit,
)
from .gate_schema import GateSchemaError
# C3: per-collector cost evidence emission. Imported at module scope so
# tests can ``patch.object(gate_orchestrator, "emit_gate_cost_report", ...)``
# to simulate a disk-emission failure without affecting other callers.
from .innovation.cost_evidence import emit_gate_cost_report
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


# B1 — legacy-marker PID-reuse hardening constants.
#
# When ``_recover_from_crash_locked`` encounters a marker that has
# ``started_at`` (ISO8601 from ``core/utils.iso_now``) but no
# ``start_time`` (the post-J-03 ``psutil.Process().create_time()`` field
# omitted by markers written before the L1+J-03 fix landed), liveness
# falls back to a two-sided bound on the live PID's ``create_time()``.
#
# ISO_TRUNCATION_S covers up to 1.0s of ``iso_now()`` second-precision
# rounding (``"%Y-%m-%dT%H:%M:%SZ"`` — the recorded value may be up to
# 1.0s earlier than the actual wall-clock moment).
ISO_TRUNCATION_S = 1.0

# MAX_ORCHESTRATOR_UPTIME_S — orchestrator processes are not meant to
# live longer than a day; a PID seen alive for >24h relative to its
# marker is strong evidence of recycling.
MAX_ORCHESTRATOR_UPTIME_S = 86400.0


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
                    # Bug fix: the on-disk bundle for ``salvaged_gate_id``
                    # has just been moved out from under any in-process
                    # cache entry warmed before quarantine. The cache
                    # module's contract (evidence_cache.py:11-17) names
                    # ``persist_evidence_record`` as the SINGLE source of
                    # invalidation; a quarantine rename violates that
                    # invariant silently unless we mirror the
                    # invalidation hook here. Lazy import matches the
                    # rest of this module's evidence_cache call sites.
                    from .evidence_cache import invalidate_evidence_cache
                    invalidate_evidence_cache(root, salvaged_gate_id)
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


def _recover_from_crash_locked(
    project_root: str | Path,
) -> tuple[dict[str, Any], list[Path]]:
    """Inner body of :func:`recover_from_crash`, executed under the file lock.

    Split out so the lock acquisition lives in a single context-manager
    block while keeping the legacy single-function contract for callers.

    K-5: returns ``(descriptor, pending_cleanup_paths)``. The descriptor
    is the historical recovery dict (``recovered``, ``gate_id``, …); the
    pending list contains absolute paths under ``_bmad/gate/cleanup/``
    that the caller must ``shutil.rmtree`` OUTSIDE the gate lock. The
    rename into ``cleanup/`` happened under the lock — the rmtree no
    longer does, so concurrent gate runs are not blocked by a slow
    delete on a multi-gigabyte evidence bundle.
    """
    root = Path(project_root)
    marker_path = root / "_bmad" / "gate" / "gate-in-progress.json"

    try:
        marker = read_gate_marker(project_root)
    except GateMarkerCorruptedError as exc:
        return _quarantine_corrupted_marker(root, marker_path, exc), []

    if marker is None:
        return {"recovered": False}, []

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
            elif alive:
                # B1 — legacy-marker fallback. Marker has no start_time
                # (was written before the L1+J-03 fix) but may carry
                # ``started_at`` (iso_now() wall-clock at marker write).
                # Use a two-sided bound to defend against PID reuse:
                #
                #   proc_start > started_at + ISO_TRUNCATION_S → PID
                #     started AFTER the marker was stamped → reuse.
                #   proc_start < started_at - MAX_ORCHESTRATOR_UPTIME_S
                #     → PID has been alive longer than the longest
                #     reasonable orchestrator lifetime → recycled.
                #
                # The pre-J-03 fast path (just ``start_time``) is wide
                # of 1.0s; the B1 fallback is conservatively wide of
                # ``[-24h, +1s]`` because ``started_at`` is wall-clock,
                # not process-creation time, and the orchestrator may
                # have been running for any duration <24h before the
                # marker was written. Markers without either field fall
                # through to the legacy ``pid_exists``-only path
                # (full back-compat).
                marker_started_at = marker.get("started_at")
                if isinstance(marker_started_at, str) and marker_started_at:
                    try:
                        started_at_epoch = datetime.fromisoformat(
                            marker_started_at.replace("Z", "+00:00")
                        ).timestamp()
                        proc_start = psutil.Process(pid).create_time()
                        if proc_start > started_at_epoch + ISO_TRUNCATION_S:
                            # Live PID started AFTER marker → reuse.
                            alive = False
                        elif proc_start < (
                            started_at_epoch - MAX_ORCHESTRATOR_UPTIME_S
                        ):
                            # Live PID alive >24h before marker → recycled.
                            alive = False
                        # else: proc_start within bound → live (no-op).
                    except (
                        psutil.NoSuchProcess, psutil.AccessDenied,
                        psutil.ZombieProcess,
                    ):
                        # gap B-M1 — zombies count as dead (the PID
                        # slot no longer holds gate state). AccessDenied
                        # matches the start_time branch above.
                        alive = False
                    except (psutil.Error, OSError, ValueError):
                        # ValueError covers a malformed started_at; keep
                        # alive=True conservatively. Do not crash
                        # recovery on parse failure.
                        pass
        if alive:
            return {
                "recovered": False,
                "reason": "live-pid-still-running",
                "pid": pid,
                "gate_id": marker.get("gate_id", ""),
            }, []

    gate_id = marker.get("gate_id", "")
    commit_sha = marker.get("commit_sha", "")

    # Bug fix: a marker that parses as valid JSON but is MISSING / has an
    # empty / has a path-unsafe ``gate_id`` was previously accepted here.
    # That let ``evidence_dir = evidence / gate_id`` collapse to
    # ``evidence/`` itself (Pathlib semantics: ``Path('.../evidence') / ''``
    # is a no-op) and ``os.rename`` then moved the ENTIRE historical
    # ``evidence/`` tree into ``cleanup/`` where it was rmtree'd —
    # silently destroying every historical gate's bundle. Such a marker
    # IS structurally corrupted (the marker contract requires gate_id);
    # treat it like any other corruption per §9.2 ("loud, not silent")
    # and route through ``_quarantine_corrupted_marker`` so the targeted
    # L2-variant quarantine semantics apply (marker moved to quarantine;
    # historical evidence dirs left intact).
    try:
        _validate_gate_id(gate_id)
    except GateSchemaError as exc:
        return _quarantine_corrupted_marker(
            root,
            marker_path,
            GateMarkerCorruptedError(
                f"gate marker missing or has invalid gate_id: {exc}"
            ),
        ), []

    verdict_path = root / "_bmad" / "gate" / "verdicts" / f"{gate_id}.json"
    had_verdict = verdict_path.is_file()

    # K-5 (Lens K): the rmtree formerly executed here while the gate
    # lock was held. Large evidence bundles can take seconds to delete,
    # blocking concurrent ``run_production_gate`` callers on the same
    # project. Instead, we atomically RENAME the orphan into
    # ``_bmad/gate/cleanup/<gate_id>-<uuid4>/`` (an O(1) inode rename on
    # the same filesystem) and surface the path so the caller can
    # rmtree it after releasing the lock. A crash between rename and
    # outside-lock rmtree leaves the subdir for ``run_cleanup_janitor``
    # to mop up on the next startup.
    #
    # Fix C-3 honesty is preserved: the rename itself can fail (e.g.
    # disk full creating the cleanup root); rmtree failures arising
    # post-lock are surfaced separately by the caller. Both paths
    # populate ``cleanup_failed`` / ``cleanup_error`` so the operator
    # always sees a half-deleted state.
    cleanup_error: str | None = None
    pending_cleanup: list[Path] = []
    if not had_verdict:
        evidence_dir = root / "_bmad" / "gate" / "evidence" / gate_id
        if evidence_dir.is_dir():
            try:
                cleanup_root = get_gate_cleanup_root(project_root)
                # uuid4 suffix ⇒ even back-to-back recoveries of the same
                # gate_id (e.g. operator retries after a crash) cannot
                # collide on the destination path.
                target = cleanup_root / f"{gate_id}-{uuid.uuid4().hex}"
                os.rename(evidence_dir, target)
                pending_cleanup.append(target)
                # Bug fix: a long-running orchestrator (or any other
                # in-process caller) that previously warmed the cache
                # for ``gate_id`` via ``cached_load_evidence_bundle``
                # would otherwise keep serving the pre-rename records.
                # The cache contract (evidence_cache.py:11-17) names
                # ``persist_evidence_record`` as the SINGLE source of
                # invalidation, so we mirror the hook here whenever
                # recovery atomically relocates a bundle. Lazy import
                # matches the rest of this module's evidence_cache
                # call sites.
                from .evidence_cache import invalidate_evidence_cache
                invalidate_evidence_cache(project_root, gate_id)
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
    return result, pending_cleanup


def _attach_recovery_signal(
    gate_file: dict[str, Any],
    descriptor: dict[str, Any],
) -> None:
    """Surface mid-startup recovery signals on ``run_production_gate``'s return.

    Bug fix (round 2 #19): without this, a corrupted marker quarantined
    mid-`run_production_gate` succeeded only on-disk under a
    timestamp-named ``_bmad/gate/quarantine/`` directory the operator had
    no reason to inspect — the return dict carried a green PASS with no
    trace. The §9.2 "loud, not silent" contract is preserved by surfacing
    the descriptor as an additive ``recovery`` subdict.

    The subdict is attached ONLY when the descriptor indicates something
    operator-actionable: ``quarantined=True`` (corruption was loud and
    moved), ``cleanup_failed`` (orphan-cleanup failed mid-recovery), or
    ``quarantine_error`` present without ``quarantined=True`` (the C-1
    fix's third descriptor shape: corruption detected but quarantine
    setup itself failed mid-mkdir — e.g. ENOSPC/EACCES/EROFS — leaving
    the corrupted marker on disk for the NEXT run to re-trip on). The
    common ``{"recovered": False}`` (no marker) and the routine
    ``{"recovered": True, ...}`` (clean orphan reaper) cases add NOTHING
    — preserving byte-identical pre-fix behavior on the
    frozen-gate-surface and keeping the change purely additive.

    Mutates ``gate_file`` in place. Tolerates the empty-dict default
    populated by ``run_production_gate`` when the lock was acquired but
    the recovery path was not reached (no signal to surface).
    """
    if not descriptor:
        return
    quarantined = bool(descriptor.get("quarantined"))
    cleanup_failed = bool(descriptor.get("cleanup_failed"))
    quarantine_error_present = bool(descriptor.get("quarantine_error"))
    # Round-3 fix: the C-1 hardening of ``_quarantine_corrupted_marker``
    # made the descriptor honest about a third shape — ``quarantined=False``
    # plus ``quarantine_error=<msg>`` — when the outer mkdir itself fails
    # (ENOSPC, EACCES on quarantine dir, EROFS). The previous gating
    # predicate dropped that shape entirely, silently swallowing the
    # WORST case (corrupted marker still on disk + I/O failure during
    # recovery, both hidden behind a green PASS). Including
    # ``quarantine_error`` in the gate honors the §9.2 "loud, not silent"
    # contract at the integration boundary where C-1 left it half-fixed.
    if not (quarantined or cleanup_failed or quarantine_error_present):
        return
    recovery: dict[str, Any] = {}
    if quarantined:
        recovery["quarantined"] = True
        if "quarantine_dir" in descriptor:
            recovery["quarantine_dir"] = descriptor["quarantine_dir"]
        if "corruption_reason" in descriptor:
            recovery["corruption_reason"] = descriptor["corruption_reason"]
        if "quarantine_error" in descriptor:
            recovery["quarantine_error"] = descriptor["quarantine_error"]
    elif quarantine_error_present:
        # C-1 third shape: corruption detected, quarantine setup
        # failed → corrupted marker is STILL on disk. Surface
        # quarantined=False explicitly so the operator can distinguish
        # "moved successfully" from "failed to move", plus the disk
        # error message and (when known) the corruption reason.
        recovery["quarantined"] = False
        recovery["quarantine_error"] = descriptor["quarantine_error"]
        if "quarantine_dir" in descriptor:
            recovery["quarantine_dir"] = descriptor["quarantine_dir"]
        if "corruption_reason" in descriptor:
            recovery["corruption_reason"] = descriptor["corruption_reason"]
    if cleanup_failed:
        recovery["cleanup_failed"] = True
        if "cleanup_error" in descriptor:
            recovery["cleanup_error"] = descriptor["cleanup_error"]
    gate_file["recovery"] = recovery


def _rmtree_quarantined_dirs(
    paths: list[Path],
) -> str | None:
    """Best-effort outside-lock rmtree pass for K-5.

    Receives the absolute paths returned by ``_recover_from_crash_locked``
    (each living under ``_bmad/gate/cleanup/``) and ``shutil.rmtree``-s
    them with per-path ``try/except OSError`` so one stubborn dir can't
    derail the others.

    Returns ``None`` on full success or the first error string for the
    caller to surface as ``cleanup_error`` (preserves Fix C-3 honesty:
    operators still see a single, real failure reason; the rest of the
    paths get swept by the janitor on the next startup).
    """
    first_error: str | None = None
    for target in paths:
        try:
            shutil.rmtree(target)
        except OSError as exc:
            if first_error is None:
                first_error = str(exc)
    return first_error


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

    The marker-read + decision phase runs under
    ``_bmad/gate/.gate.lock`` so it cannot race a concurrent
    ``run_production_gate`` (bug L1). For K-5, orphan evidence dirs are
    RENAMED into ``_bmad/gate/cleanup/`` under the lock (fast); the
    actual ``shutil.rmtree`` happens AFTER the lock is released so
    concurrent gates are no longer blocked by a multi-second delete on
    large evidence bundles.

    Returns a dict describing what was recovered.
    """
    assert_host_context("recover_from_crash")
    lock = get_gate_lock(project_root)
    try:
        with lock:
            descriptor, pending_cleanup = _recover_from_crash_locked(
                project_root,
            )
    except Timeout as exc:
        _handle_gate_lock_timeout(
            project_root, gate_lock_path(project_root), lock.timeout, exc,
        )
    # Lock released — perform the slow rmtree(s) here so we never block
    # a concurrent gate run on bulk I/O. Failures only update the
    # descriptor's cleanup_failed/cleanup_error fields; they never
    # propagate (the inside-lock rename was the load-bearing step).
    if pending_cleanup:
        cleanup_error = _rmtree_quarantined_dirs(pending_cleanup)
        if cleanup_error is not None and not descriptor.get("cleanup_failed"):
            descriptor["cleanup_failed"] = True
            descriptor["cleanup_error"] = cleanup_error
    return descriptor


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
    isolation_mode: Literal["shared", "per_unit"] = "shared",
    max_workers: int = 4,
) -> list[Any]:
    """Wrapper for testability — delegates to run_gate_collectors.

    G2 (additive): forwards ``isolation_mode`` + ``max_workers`` to
    ``run_gate_collectors``. Defaults preserve byte-identical behavior.
    """
    return run_gate_collectors(
        project_root, gate_id, commit_sha, profile, registry,
        diff_categories=diff_categories,
        audit_policy=audit_policy, audit_path=audit_path,
        isolation_mode=isolation_mode,
        max_workers=max_workers,
    )


def _collect_error_evidence(
    project_root: str | Path, gate_id: str,
) -> list[str]:
    """Return ``"<category>/<collector>"`` labels for every
    error-or-timeout-status evidence record persisted under
    ``gate_id``. Used by the ``fail_closed`` policy to decide whether
    to override the verdict to FAIL. Returns ``[]`` if the evidence
    dir is missing — fail_closed cannot meaningfully fire without
    persisted evidence.

    Both ``status="error"`` (crashed collector, stamped by
    :mod:`collector_runner`) and ``status="timeout"`` (stamped by
    :func:`gate_schema.make_timeout_evidence` when ``subprocess.run``
    raises ``TimeoutExpired``) are treated identically here — they are
    distinct, equally fail-closed-relevant statuses per
    ``VALID_EVIDENCE_STATUSES`` and the shared collector invariant
    "fail-closed: error/timeout never count as PASS". This matches the
    parallel treatment in :mod:`category_rules` (`status in ("error",
    "timeout")` checked at every category aggregator) so the
    operator-facing audit trail (``fail_closed_triggered`` +
    ``fail_closed_categories``) stays consistent with the verdict
    engine's category-level fail-closed semantics.
    """
    try:
        # K-2: same gate_id is read by the Merkle exporter and verdict
        # engine on the same run; share the cached bundle.
        from .evidence_cache import cached_load_evidence_bundle
        bundle = cached_load_evidence_bundle(project_root, gate_id)
    except FileNotFoundError:
        return []
    labels: list[str] = []
    for record in bundle:
        if not isinstance(record, dict):
            continue
        if record.get("status") in ("error", "timeout"):
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
    drift_watcher: "SpecDriftWatcher | None" = None,
    session_usage: "UsageMetrics | None" = None,
    threshold_proposer: "ThresholdProposer | None" = None,
    isolation_mode: Literal["shared", "per_unit"] = "shared",
    max_workers: int = 4,
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
    evidence record with ``status="error"`` OR ``status="timeout"``
    forces ``overall=FAIL`` regardless of the verdict_engine's
    decision. The override is auditable: the returned gate file gains
    ``fail_closed_triggered=True`` and a sorted
    ``fail_closed_categories`` list. ``status="error"`` is what the
    collector_runner stamps on a crashed collector (Phase 1);
    ``status="timeout"`` is what :func:`gate_schema.make_timeout_evidence`
    stamps when ``subprocess.run`` raises ``TimeoutExpired`` — both
    situations where fail-open might let a real bug ship. ``False``
    (default) preserves prior behavior: error/timeout evidence is still
    surfaced in categories but the verdict_engine decides whether it
    sinks the gate.

    ``drift_watcher`` (C1 follow-up, default ``None``) — when a
    :class:`SpecDriftWatcher` is provided, the orchestrator calls
    ``watcher.poll()`` twice per FULL gate run: once after the
    in-progress marker is written and once after ``evaluate_gate``
    returns but before any ``fail_closed`` override. Both calls are
    wrapped in ``try/except`` so a drift-detector failure can never
    abort the gate — drift is strictly advisory telemetry. Early-return
    paths skip BOTH polls because the anchoring lifecycle events
    (marker-written / evaluate_gate-returned) do not occur: the
    pre-gate-verifier failure, the reuse cache-hit, and the
    lie-detector ``baseline_drift`` short-circuit all return before
    any marker is written. Operators relying on poll counts as a
    dashboard signal must therefore filter on ``action != "pre_gate_failed"``
    AND fresh-run gate files (cache hits return the cached gate file
    without re-polling). Default ``None`` preserves byte-identical
    behavior for every existing call site.

    ``session_usage`` (C3, default ``None``) — when a
    :class:`UsageMetrics` from the host session is provided, the
    orchestrator distributes the session's tokens/cost/duration across
    the collectors that ran and persists per-collector cost evidence
    under ``_bmad/gate/cost/<gate_id>/``. On success the gate file
    gains an additive ``cost_total_usd: float`` field. Emission is
    best-effort: any exception (disk full, mid-write crash, etc.) is
    swallowed and the gate completes normally without the
    ``cost_total_usd`` field. Default ``None`` preserves
    byte-identical behavior for every existing call site — no cost
    directory is created.

    ``threshold_proposer`` (C5, default ``None``) — when a
    :class:`ThresholdProposer` is provided, the orchestrator calls
    ``proposer.observe_gate(project_root, gate_file)`` AFTER
    ``evaluate_gate`` returns and AFTER the existing ``lineage_root`` +
    ``cost_total_usd`` blocks, but BEFORE returning the gate file. The
    call site is wrapped in a broad ``try/except`` so a proposer failure
    can never abort the gate — drift-to-proposal is strictly advisory
    telemetry. On success the in-memory gate file gains
    ``threshold_proposal_ref: str`` (a 16-hex proposal id, or ``""``
    when no proposal was emitted). On failure the gate file gains
    ``threshold_proposal_ref=""`` PLUS
    ``threshold_proposer_error=<ExceptionClassName>`` so the operator
    can distinguish "no proposal needed" from "proposer crashed". Both
    fields are IN-MEMORY ONLY; the on-disk gate JSON under
    ``_bmad/gate/verdicts/`` is byte-identical because
    ``persist_gate_file`` ran inside ``evaluate_gate`` BEFORE this
    mutation, matching the existing
    ``evidence_merkle_root`` / ``lineage_root`` / ``cost_total_usd``
    pattern. Default ``None`` preserves byte-identical behavior for
    every existing call site.

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

    ``isolation_mode`` (G2, default ``"shared"``) — selects the
    collector-execution shape. ``"shared"`` runs the historical
    single-checkout sequential loop (byte-identical to pre-G2).
    ``"per_unit"`` drives each collector into its own fresh worktree
    inside a bounded ``ThreadPoolExecutor``. ``max_workers`` (default
    ``4``) sizes the parallel pool; it is RAM- and CPU-clamped by
    ``_clamp_max_workers``. Both kwargs are type/value validated
    EARLY — before ``assert_host_context`` and before the gate-lock
    acquisition — so invalid values raise without leaving any
    marker or partial state on disk (HIGH #6).
    """
    # HIGH #6 — validate isolation kwargs BEFORE any other work, so
    # invalid values raise without acquiring the gate lock and without
    # leaving a partial marker on disk. Validated in BOTH modes
    # (``max_workers="four"`` in ``shared`` still raises) to prevent
    # operator footguns when flipping mode later.
    _validate_isolation_kwargs(isolation_mode, max_workers)

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

    # K-5: best-effort janitor pass BEFORE acquiring the gate lock. The
    # cleanup root contains orphaned post-rename / pre-rmtree subdirs
    # left by prior crashes; they are by construction unreferenced so
    # the janitor needs no lock. Failures are non-fatal — next startup
    # will retry.
    try:
        run_cleanup_janitor(project_root)
    except OSError:
        pass

    # L1 fix: serialize the full marker → collectors → clear lifecycle
    # under the gate file lock so concurrent run_production_gate /
    # recover_from_crash calls cannot race on gate-in-progress.json.
    # The timeout is generous (collectors may run for many seconds);
    # callers that need a shorter ceiling can wrap with a shorter
    # acquired lock externally.
    #
    # R2 fix #25: ``acquire()`` MUST be the first statement of the try
    # whose ``finally:`` releases the lock — otherwise a SIGINT /
    # KeyboardInterrupt arriving in the bytecode-gap between
    # ``acquire()`` returning and ``SETUP_FINALLY`` of a separate inner
    # try would hold the OS-level lock without registering the release
    # cleanup. ``_pending_cleanup`` + ``_recovery_descriptor`` are
    # hoisted ABOVE the lock acquisition so the outermost ``finally:``
    # (which runs ``_rmtree_quarantined_dirs``) sees them on every exit
    # path. ``release()`` is a no-op when ``is_locked`` is False
    # (filelock/_api.py:562), so a Timeout-raising or interrupted
    # ``acquire()`` runs the finally safely.
    _pending_cleanup: list[Path] = []
    _recovery_descriptor: dict[str, Any] = {}
    _gate_lock = get_gate_lock(project_root, timeout=3600.0)
    try:
        try:
            _gate_lock.acquire()
            # Recovery runs under the same lock — use the *_locked variant
            # so we don't try to re-acquire (filelock is not re-entrant
            # across separate FileLock instances). K-5: capture the renamed
            # cleanup paths so we can rmtree them outside the lock below.
            # Bug fix (round 2 #19): capture the descriptor so the operator
            # sees the §9.2 "loud, not silent" quarantine signal at the
            # orchestrator's single integration point. Without this, a
            # mid-startup corrupted-marker quarantine succeeded only
            # on-disk under a timestamp dir the operator had no reason to
            # inspect — `run_production_gate` returned a green PASS with
            # no trace. The descriptor is surfaced via an additive
            # ``recovery`` subdict only when actually meaningful
            # (quarantined OR cleanup_failed); the common no-marker
            # ``{"recovered": False}`` path adds nothing — preserving
            # byte-identical behavior on the frozen-gate-surface.
            _recovery_descriptor, _pending_cleanup = (
                _recover_from_crash_locked(project_root)
            )

            existing, _ = check_gate_reuse(
                project_root, gate_id, commit_sha, profile, factory_version,
                audit_policy=audit_policy, audit_path=audit_path,
            )
            if existing is not None:
                # Reuse path must populate the same UNCONDITIONAL in-memory
                # additive fields the fresh path always sets (lines 887-928
                # below) so callers see a consistent return shape regardless
                # of cache hit/miss. The on-disk gate JSON is by design
                # byte-identical between fresh and reused (persist_gate_file
                # ran at verdict_engine.py:272 BEFORE these mutations on
                # the original fresh run), so we re-derive the two unconditional
                # fields here without rewriting disk. Conditional fields
                # (cost_total_usd / threshold_proposal_ref) stay opt-in via
                # the corresponding kwargs and are NOT recomputed on reuse —
                # the caller's session_usage/threshold_proposer pertain to
                # the current call, not the cached run.
                from .evidence_cache import cached_load_evidence_bundle
                from .innovation.lineage_ledger import load_lineage_root
                try:
                    _bundle = cached_load_evidence_bundle(
                        project_root, gate_id,
                    )
                except FileNotFoundError:
                    _bundle = []
                if _bundle:
                    existing["evidence_merkle_root"] = (
                        compute_evidence_bundle_merkle_root(_bundle)
                    )
                else:
                    existing["evidence_merkle_root"] = ""
                existing["lineage_root"] = load_lineage_root(project_root)
                # Bug fix: ``fail_closed`` MUST apply to the reuse path
                # too. Without this block the docstring contract
                # ("forces overall=FAIL regardless of the verdict_engine's
                # decision") was honored on cache miss but silently
                # ignored on cache hit — same (gate_id, commit, profile,
                # factory_version) + same fail_closed=True yielded
                # different verdicts depending on whether the gate file
                # was already on disk. Unlike the opt-in
                # session_usage/threshold_proposer kwargs (which pertain
                # to THIS call, not the cached run), ``fail_closed`` is
                # a SAFETY OVERRIDE driven by on-disk error-status
                # evidence — that evidence is by construction the same
                # on disk whether the gate is fresh or reused, so the
                # override decision is identical between modes. Mirrors
                # the fresh-path block at lines 985-994 verbatim.
                if fail_closed:
                    error_labels = _collect_error_evidence(
                        project_root, gate_id,
                    )
                    if error_labels:
                        existing["fail_closed_triggered"] = True
                        existing["fail_closed_categories"] = sorted(
                            set(error_labels),
                        )
                        existing["overall"] = "FAIL"
                _attach_recovery_signal(existing, _recovery_descriptor)
                return existing

            if enable_lie_detector:
                outcome = detect_baseline_drift(
                    project_root,
                    expected_sha=commit_sha,
                    baseline_sha=baseline_sha,
                )
                if not outcome.ok:
                    # R3 fix: the lie-detector early-return path runs
                    # AFTER ``_recover_from_crash_locked`` so it MUST
                    # surface ``_recovery_descriptor`` to preserve the
                    # §9.2 "loud, not silent" contract that the reuse
                    # path (line 1011) and fresh-success path (line 1202)
                    # both honor. Without this call, a mid-startup
                    # corrupted-marker quarantine succeeded only on-disk
                    # under a timestamp-named ``_bmad/gate/quarantine/``
                    # directory the operator had no reason to inspect,
                    # while the return dict carried only an opaque
                    # ``baseline_drift`` action. ``_attach_recovery_signal``
                    # is a no-op for empty / no-op descriptors, so this
                    # is purely additive on the common (no marker / clean
                    # orphan reaper) paths.
                    drift_return: dict[str, Any] = {
                        "action": "baseline_drift",
                        "gate_id": gate_id,
                        "verify": outcome.to_dict(),
                    }
                    _attach_recovery_signal(
                        drift_return, _recovery_descriptor,
                    )
                    return drift_return

            if audit_policy is not None and audit_path is not None:
                emit_gate_audit(
                    audit_policy, audit_path,
                    GateStartedAudit(
                        gate_id=gate_id, commit_sha=commit_sha,
                        profile_hash=compute_profile_hash(profile),
                    ),
                )

            write_gate_marker(project_root, gate_id, commit_sha)
            # C1 follow-up: optional spec-drift watcher polled at lifecycle
            # start. Failures are strictly advisory and must never abort
            # the gate — drift is telemetry, not gating.
            if drift_watcher is not None:
                try:
                    drift_watcher.poll()
                except Exception:
                    pass
            try:
                collector_outcomes = _run_collectors(
                    project_root, gate_id, commit_sha, profile, registry,
                    audit_policy=audit_policy, audit_path=audit_path,
                    isolation_mode=isolation_mode,
                    max_workers=max_workers,
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
                # R2 fix #17: raising in a ``finally`` clobbers a
                # propagating ``KeyboardInterrupt`` (or any other in-flight
                # exception). ``clear_gate_marker`` only handles
                # ``FileNotFoundError`` — a permission / read-only-fs /
                # IsADirectoryError on the unlink would override the
                # operator's SIGINT, silently converting it to OSError and
                # contradicting the contract pinned by
                # ``test_marker_cleared_when_collectors_raise``. The
                # original exception (Ctrl+C) is preserved only as
                # ``__context__`` and ``except KeyboardInterrupt`` clauses
                # will NOT match. Swallow the secondary OSError so the
                # primary exception keeps propagating; the K-5 startup
                # janitor / ``recover_from_crash`` already mops up orphan
                # markers, so the marker-not-cleared edge is the lesser
                # evil.
                try:
                    clear_gate_marker(project_root)
                except OSError:
                    pass
        except Timeout as _exc:
            # R2 fix #25: Timeout from the ``acquire()`` at the top of
            # this protected try lands here. ``_handle_gate_lock_timeout``
            # is ``NoReturn`` (re-raises ``GateLockTimeoutError``), so the
            # ``finally:`` below runs ``release()`` — which is a no-op
            # because the lock was never acquired (``is_locked`` is False;
            # filelock/_api.py:562).
            _handle_gate_lock_timeout(
                project_root, gate_lock_path(project_root),
                _gate_lock.timeout, _exc,
            )
        finally:
            # R2 fix #25: every exit path from the protected try (success,
            # exception, SIGINT/KeyboardInterrupt arriving in the
            # bytecode-gap immediately after ``acquire()`` returns) lands
            # here. ``release()`` is idempotent + ``is_locked``-gated so a
            # Timeout-raising / interrupted ``acquire()`` is safe.
            _gate_lock.release()
    finally:
        # K-5: rmtree the quarantined orphan evidence dirs OUTSIDE the
        # gate lock so the slow bulk delete does not block any other
        # gate run that may now want the lock. Wrapped in a function-
        # level finally so EVERY exit path — the reuse-shortcut
        # ``return existing``, the lie-detector ``return
        # {"action": "baseline_drift", ...}``, the main fall-through,
        # and any exception — runs the rmtree pass. Skipping it here
        # would leak the renamed orphan into ``_bmad/gate/cleanup/``
        # until the next startup janitor swept it, contradicting the
        # K-5 inline-drain contract on these reachable early-return
        # paths. Failures are intentionally swallowed — the next
        # startup's janitor will mop up any leftover dirs.
        if _pending_cleanup:
            _rmtree_quarantined_dirs(_pending_cleanup)

    # N5 (G5): export Merkle root so auditors can externally verify the
    # evidence bundle without trusting the factory. Empty bundle returns
    # an empty-string sentinel — distinguishable from a real 64-hex root.
    # K-2: cached read — verdict_engine already populated this entry for
    # the same gate_id earlier in this call.
    from .evidence_cache import cached_load_evidence_bundle
    bundle = cached_load_evidence_bundle(project_root, gate_id)
    if bundle:
        gate_file["evidence_merkle_root"] = compute_evidence_bundle_merkle_root(bundle)
    else:
        gate_file["evidence_merkle_root"] = ""

    # C1 follow-up: optional spec-drift watcher polled at lifecycle
    # end (after evaluate_gate, before any fail_closed override).
    # Failures are non-fatal — see start-of-lifecycle poll above.
    if drift_watcher is not None:
        try:
            drift_watcher.poll()
        except Exception:
            pass

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

    # C2 follow-up: embed the disk-derived cross-genre lineage root so
    # auditors can prove "this gate verdict descends from brief X via
    # kernel Y". Empty string when no chain exists on disk —
    # distinguishable from a real 64-hex root, mirroring the
    # ``evidence_merkle_root`` empty-sentinel convention above.
    from .innovation.lineage_ledger import load_lineage_root
    gate_file["lineage_root"] = load_lineage_root(project_root)

    # C3: per-collector cost evidence. Best-effort emission — wrapped
    # in a broad except so a disk failure (ENOSPC, permission error,
    # collector-list mismatch) can never break gate completion. The
    # ``cost_total_usd`` field is ADDITIVE + OPTIONAL: present only
    # when session_usage was provided AND emission succeeded.
    if session_usage is not None and collector_outcomes:
        try:
            _cost_report = emit_gate_cost_report(
                project_root, gate_id, session_usage, collector_outcomes,
            )
            gate_file["cost_total_usd"] = _cost_report.total_cost_usd
        except Exception:
            # Cost evidence is observability, not gating — never
            # propagate. The absence of ``cost_total_usd`` on the gate
            # file is the operator's signal that emission failed.
            pass

    # C5: optional threshold-proposer observe-hook. Default-None call
    # sites are byte-identical to today. The hook is purely advisory
    # (proposals are written to ``_bmad/calibration/proposals/`` for
    # human review; nothing in ``core/`` may auto-apply them) so a
    # proposer crash is swallowed and surfaced via the in-memory
    # ``threshold_proposer_error`` diagnostic field — never propagated.
    # Both fields are in-memory only; the on-disk gate JSON already
    # persisted at verdict_engine.py:272 is NOT rewritten (matches the
    # evidence_merkle_root / lineage_root / cost_total_usd pattern).
    if threshold_proposer is not None:
        try:
            proposal = threshold_proposer.observe_gate(
                project_root, gate_file,
            )
            gate_file["threshold_proposal_ref"] = (
                proposal.proposal_id if proposal is not None else ""
            )
        except Exception as _exc:
            gate_file["threshold_proposal_ref"] = ""
            gate_file["threshold_proposer_error"] = type(_exc).__name__

    # Bug fix (round 2 #19): surface the §9.2 "loud, not silent"
    # mid-startup recovery signal. The recovery descriptor was previously
    # discarded at the `_recover_from_crash_locked` call, so a corrupted
    # marker quarantined mid-`run_production_gate` left no trace on the
    # operator-facing return dict — the operator only saw a green PASS
    # while the quarantine record lived under a timestamp-named directory
    # they had no reason to inspect. The additive ``recovery`` subdict is
    # ONLY present when meaningful (``quarantined`` OR ``cleanup_failed``)
    # so the common no-marker fast path is byte-identical to pre-fix.
    _attach_recovery_signal(gate_file, _recovery_descriptor)

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
