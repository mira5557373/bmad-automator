"""System-altitude gate lifecycle — per-epic gate orchestration (§10).

Provisions an ephemeral environment (minimal/full), runs system-tier
collectors against it, evaluates the gate, and routes the epic-level
verdict. Reuses existing crash recovery, reuse validation, and
verdict engine infrastructure.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Literal

from typing import TYPE_CHECKING

from .collector_isolation import _validate_isolation_kwargs
from .collector_registry import CollectorRegistry
from .collector_runner import run_gate_collectors
from filelock import Timeout

if TYPE_CHECKING:
    from .usage_parsers import UsageMetrics

from .evidence_io import (
    clear_gate_marker,
    gate_lock_path,
    get_gate_lock,
    run_cleanup_janitor,
    write_gate_marker,
)
from .gate_lock_observability import _handle_gate_lock_timeout
from .gate_audit import (
    EpicGateDecisionAudit,
    SystemGateStartedAudit,
    emit_gate_audit,
)
from .gate_orchestrator import (
    _recover_from_crash_locked,
    _rmtree_quarantined_dirs,
    check_gate_reuse,
    recover_from_crash,  # noqa: F401  back-compat: existing tests patch this name
)
from .gate_remediation import failing_categories_from_gate, prepare_remediation_tasks
from .innovation.cost_evidence import emit_gate_cost_report
from .gate_status import park_story, record_mitigation_debt
from .product_profile import compute_profile_hash
from .system_env import build_env_config, system_env
from .trust_boundary import assert_host_context
from .verdict_engine import evaluate_gate


def run_system_gate(
    project_root: str | Path,
    gate_id: str,
    *,
    epic_id: str,
    commit_sha: str,
    epic_metadata: dict[str, Any],
    profile: dict[str, Any],
    factory_version: str,
    registry: CollectorRegistry,
    priority: str = "P1",
    waivers: list[dict[str, Any]] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
    session_usage: "UsageMetrics | None" = None,
    isolation_mode: Literal["shared", "per_unit"] = "shared",
    max_workers: int = 4,
) -> dict[str, Any]:
    """Full system-altitude gate lifecycle.

    crash recovery -> reuse check -> provision env ->
    inject _runtime_env -> run system collectors ->
    evaluate (tier=system) -> teardown env -> return gate file.

    L1 follow-up: the recover -> reuse -> marker -> collectors -> clear
    window runs under the SAME ``_bmad/gate/.gate.lock`` envelope used by
    :func:`gate_orchestrator.run_production_gate` (timeout 3600s), so
    concurrent system + production gate invocations against one
    ``project_root`` cannot race on ``gate-in-progress.json``. Recovery
    delegates to :func:`gate_orchestrator._recover_from_crash_locked`
    because ``filelock`` is not re-entrant across separate ``FileLock``
    instances.

    G2 (additive): ``isolation_mode`` + ``max_workers`` mirror
    :func:`gate_orchestrator.run_production_gate`. Default
    ``"shared"`` preserves byte-identical behavior. ``"per_unit"``
    drives each system collector into its own fresh worktree inside a
    bounded ``ThreadPoolExecutor``. Both kwargs are type/value
    validated EARLY — before ``assert_host_context`` and before the
    gate-lock acquisition — so invalid values raise without leaving
    any marker or partial state on disk (HIGH #6).
    """
    # HIGH #6 — validate isolation kwargs BEFORE any other work, so
    # invalid values raise without acquiring the gate lock and without
    # leaving a partial marker on disk. Validated in BOTH modes.
    _validate_isolation_kwargs(isolation_mode, max_workers)

    assert_host_context("run_system_gate")

    # K-5: best-effort janitor pass before locking. Same rationale as
    # run_production_gate — the cleanup root is a sibling of evidence/
    # and contains only unreferenced renamed subdirs.
    try:
        run_cleanup_janitor(project_root)
    except OSError:
        pass

    # L1 follow-up: serialize the marker lifecycle under the same lock
    # the production gate uses. The 3600s timeout matches
    # run_production_gate — system gates can run for many seconds while
    # collectors execute against a provisioned environment.
    _gate_lock = get_gate_lock(project_root, timeout=3600.0)
    try:
        _gate_lock.acquire()
    except Timeout as _exc:
        _handle_gate_lock_timeout(
            project_root, gate_lock_path(project_root),
            _gate_lock.timeout, _exc,
        )
    _pending_cleanup: list[Path] = []
    try:
        try:
            # Recovery runs under the same lock — use the *_locked variant
            # so we don't try to re-acquire (filelock is not re-entrant
            # across separate FileLock instances). K-5: capture renamed
            # cleanup paths so we can rmtree them outside the lock below.
            _, _pending_cleanup = _recover_from_crash_locked(project_root)

            existing, _ = check_gate_reuse(
                project_root, gate_id, commit_sha, profile, factory_version,
                audit_policy=audit_policy, audit_path=audit_path,
            )
            if existing is not None:
                # Reuse path must populate the same UNCONDITIONAL in-memory
                # additive fields the fresh path always sets (the
                # ``lineage_root`` embed at the end of this function) so
                # callers see a consistent return shape regardless of
                # cache hit / miss. The on-disk gate JSON is by design
                # byte-identical between fresh and reused (persist_gate_file
                # ran at verdict_engine.py BEFORE this mutation on the
                # original fresh run), so we re-derive the unconditional
                # field here without rewriting disk. Conditional fields
                # (``cost_total_usd``) stay opt-in via ``session_usage``
                # and are NOT recomputed on reuse — the caller's
                # session_usage pertains to the current call, not the
                # cached run. Mirrors gate_orchestrator.run_production_gate
                # reuse-path block.
                from .innovation.lineage_ledger import load_lineage_root
                existing["lineage_root"] = load_lineage_root(project_root)
                return existing

            env_config = build_env_config(
                str(project_root), commit_sha, epic_metadata, profile,
            )

            if audit_policy is not None and audit_path is not None:
                emit_gate_audit(
                    audit_policy, audit_path,
                    SystemGateStartedAudit(
                        gate_id=gate_id, epic_id=epic_id,
                        commit_sha=commit_sha,
                        profile_hash=compute_profile_hash(profile),
                        env_tier=env_config.tier,
                    ),
                )

            write_gate_marker(project_root, gate_id, commit_sha)
            collector_outcomes: list = []
            try:
                with system_env(env_config, str(project_root)) as env_info:
                    if not env_info.provisioned:
                        # Bug fix (round 1, item 32): do NOT early-return
                        # here. Returning bypasses the EpicGateDecisionAudit
                        # emission + lineage_root embed below, leaving a
                        # SystemGateStartedAudit with no matching decision
                        # event (an audit-trail asymmetry) and a gate_file
                        # missing the orchestrator-level fields its PASS
                        # sibling carries. Construct the FAIL gate_file
                        # and fall through to the unified post-lock block.
                        from .gate_schema import make_gate_file as _make_gate_file

                        gate_file = _make_gate_file(
                            gate_id=gate_id, tier="system",
                            target={"kind": "epic", "id": epic_id},
                            commit_sha=commit_sha,
                            profile={
                                "id": profile.get("id", ""),
                                "version": profile.get("version", 1),
                                "hash": compute_profile_hash(profile),
                            },
                            factory_version=factory_version,
                            categories={}, overall="FAIL",
                        )
                        gate_file["_provision_failed"] = True
                    else:
                        enriched = _inject_runtime_env(profile, env_info)
                        collector_outcomes = run_gate_collectors(
                            project_root, gate_id, commit_sha, enriched, registry,
                            audit_policy=audit_policy, audit_path=audit_path,
                            isolation_mode=isolation_mode,
                            max_workers=max_workers,
                        )

                        target = {"kind": "epic", "id": epic_id}
                        gate_file = evaluate_gate(
                            project_root, gate_id,
                            commit_sha=commit_sha, target=target,
                            profile=profile, factory_version=factory_version,
                            priority=priority, waivers=waivers,
                            audit_policy=audit_policy, audit_path=audit_path,
                            tier="system",
                        )
            finally:
                # R2 fix #17 (mirror of gate_orchestrator.py): swallow any
                # OSError raised by ``clear_gate_marker`` so a
                # ``KeyboardInterrupt`` / ``SystemExit`` propagating from
                # ``run_gate_collectors`` or ``evaluate_gate`` is not
                # clobbered by a secondary unlink failure (read-only fs,
                # permission denied, IsADirectoryError, etc.).
                # ``clear_gate_marker`` only handles ``FileNotFoundError``;
                # any other OSError raised inside a ``finally`` would
                # override the operator's SIGINT, breaking shutdown
                # handlers that match ``except KeyboardInterrupt``. The
                # startup janitor / ``recover_from_crash`` mops up
                # orphan markers.
                try:
                    clear_gate_marker(project_root)
                except OSError:
                    pass
        finally:
            _gate_lock.release()
    finally:
        # K-5: outside-lock rmtree of orphan evidence dirs renamed
        # during recovery. Slow bulk delete must not block other gates.
        # Wrapped in a function-level finally so EVERY exit path — the
        # reuse-shortcut ``return existing``, the provision-failed
        # ``return gate_file``, the main fall-through, and any
        # exception — runs the rmtree pass. Without this, the
        # early-return paths would leak the renamed orphan into
        # ``_bmad/gate/cleanup/`` until the next startup janitor
        # swept it. Failures are intentionally swallowed.
        if _pending_cleanup:
            _rmtree_quarantined_dirs(_pending_cleanup)

    if audit_policy is not None and audit_path is not None:
        cats_summary = ",".join(
            f"{c}:{v['verdict']}"
            for c, v in sorted(gate_file.get("categories", {}).items())
            if isinstance(v, dict) and "verdict" in v
        )
        emit_gate_audit(
            audit_policy, audit_path,
            EpicGateDecisionAudit(
                gate_id=gate_id, epic_id=epic_id,
                overall=gate_file["overall"],
                commit_sha=commit_sha,
                env_tier=env_config.tier,
                categories_summary=cats_summary,
            ),
        )

    # C2 follow-up: symmetry with run_production_gate — embed the disk
    # lineage root onto the system-gate file too. Empty string sentinel
    # when no chain exists on disk.
    from .innovation.lineage_ledger import load_lineage_root
    gate_file["lineage_root"] = load_lineage_root(project_root)

    # C3: per-collector cost evidence (symmetric with run_production_gate).
    # Best-effort emission — never break gate completion. Additive optional
    # ``cost_total_usd`` field present only when emission succeeds.
    if session_usage is not None and collector_outcomes:
        try:
            _cost_report = emit_gate_cost_report(
                project_root, gate_id, session_usage, collector_outcomes,
            )
            gate_file["cost_total_usd"] = _cost_report.total_cost_usd
        except Exception:
            pass

    return gate_file


def route_epic_verdict(
    project_root: str | Path,
    gate_file: dict[str, Any],
    *,
    epic_id: str,
    story_keys: list[str],
    remediation_cycle: int = 0,
    max_cycles: int = 3,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    """Route epic-level system gate verdict to action."""
    assert_host_context("route_epic_verdict")
    overall = gate_file.get("overall", "FAIL")
    gate_id = gate_file.get("gate_id", "")

    if overall == "PASS":
        return {"action": "done", "overall": "PASS"}

    if overall == "WAIVED":
        return {"action": "done", "overall": "WAIVED", "waived": True}

    if overall == "CONCERNS":
        concerns_cats = [
            cat for cat, info in gate_file.get("categories", {}).items()
            if isinstance(info, dict) and info.get("verdict") == "CONCERNS"
        ]
        record_mitigation_debt(project_root, gate_id, epic_id, concerns_cats)
        return {
            "action": "done", "overall": "CONCERNS",
            "mitigation_debt": concerns_cats,
        }

    if remediation_cycle >= max_cycles:
        park_story(
            project_root, gate_id, epic_id,
            "exhausted", overall,
            audit_policy=audit_policy, audit_path=audit_path,
        )
        return {
            "action": "park", "reason": "exhausted",
            "overall": overall, "gate_id": gate_id,
        }

    failing = failing_categories_from_gate(gate_file)
    to_reopen = stories_to_reopen(gate_file, story_keys)
    tasks = prepare_remediation_tasks(gate_file)
    return {
        "action": "reopen", "overall": overall,
        "gate_id": gate_id,
        "failing_categories": failing,
        "stories_to_reopen": to_reopen,
        "remediation_tasks": tasks,
        "cycle": remediation_cycle + 1,
    }


def stories_to_reopen(
    gate_file: dict[str, Any],
    story_keys: list[str],
) -> list[str]:
    """Identify stories to reopen when the epic gate fails."""
    overall = gate_file.get("overall", "")
    if overall != "FAIL":
        return []
    return list(story_keys)


def _inject_runtime_env(
    profile: dict[str, Any],
    env_info: Any,
) -> dict[str, Any]:
    """Inject transient _runtime_env into a profile copy for system collectors."""
    enriched = copy.deepcopy(profile)
    enriched["_runtime_env"] = {
        "env_id": env_info.env_id,
        "tier": env_info.tier,
        "namespace": env_info.namespace,
        "endpoints": dict(env_info.endpoints) if env_info.endpoints else {},
    }
    return enriched
