"""System-altitude gate lifecycle — per-epic gate orchestration (§10).

Provisions an ephemeral environment (minimal/full), runs system-tier
collectors against it, evaluates the gate, and routes the epic-level
verdict. Reuses existing crash recovery, reuse validation, and
verdict engine infrastructure.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .collector_registry import CollectorRegistry
from .collector_runner import run_gate_collectors
from .evidence_io import clear_gate_marker, get_gate_lock, write_gate_marker
from .gate_audit import (
    EpicGateDecisionAudit,
    SystemGateStartedAudit,
    emit_gate_audit,
)
from .gate_orchestrator import (
    _recover_from_crash_locked,
    check_gate_reuse,
    recover_from_crash,  # noqa: F401  back-compat: existing tests patch this name
)
from .gate_remediation import failing_categories_from_gate, prepare_remediation_tasks
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
    """
    assert_host_context("run_system_gate")

    # L1 follow-up: serialize the marker lifecycle under the same lock
    # the production gate uses. The 3600s timeout matches
    # run_production_gate — system gates can run for many seconds while
    # collectors execute against a provisioned environment.
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
        try:
            with system_env(env_config, str(project_root)) as env_info:
                if not env_info.provisioned:
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
                    return gate_file

                enriched = _inject_runtime_env(profile, env_info)
                run_gate_collectors(
                    project_root, gate_id, commit_sha, enriched, registry,
                    audit_policy=audit_policy, audit_path=audit_path,
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
            clear_gate_marker(project_root)

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
