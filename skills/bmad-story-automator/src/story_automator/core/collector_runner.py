"""Collector runner — orchestrates evidence collection for gate evaluation.

Runs individual collectors via run_collector_with_timeout (§6.4),
persists evidence via persist_evidence_record, and emits audit events.
Full gate collector loop creates a fresh checkout, iterates applicable
collectors, persists evidence, and returns collected outcomes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .adjudicator import resolve_timeout, run_collector_with_timeout
from .collector_checkout import collector_checkout
from .collector_config import CollectorConfig, CollectorOutcome
from .collector_registry import CollectorRegistry
from .evidence_io import persist_evidence_record
from .gate_audit import EvidenceCollectedAudit, emit_gate_audit
from .gate_schema import make_evidence_record
from .trust_boundary import assert_host_context

__all__ = [
    "run_single_collector",
    "run_gate_collectors",
]


def run_single_collector(
    config: CollectorConfig,
    checkout_path: str,
    profile: dict[str, Any],
    gate_id: str,
    project_root: str | Path,
    *,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> CollectorOutcome:
    """Run one collector, persist evidence, emit audit event.

    §7: asserts host context before any write.
    §6.4: resolves per-category timeout from profile.
    Fail-closed: build_cmd exceptions produce error evidence.
    """
    assert_host_context("run_single_collector")
    timeout = resolve_timeout(profile, config.category)

    try:
        cmd = config.build_cmd(checkout_path, profile)
    except Exception as exc:
        evidence = make_evidence_record(
            collector=config.collector_id,
            tool=config.tool,
            category=config.category,
            status="error",
            findings=[f"cmd builder error: {exc}"],
            exit_code=-1,
            deterministic=config.deterministic,
        )
        persisted = persist_evidence_record(project_root, gate_id, evidence)
        if audit_policy is not None and audit_path is not None:
            emit_gate_audit(
                audit_policy,
                audit_path,
                EvidenceCollectedAudit(
                    gate_id=gate_id,
                    category=config.category,
                    collector=config.collector_id,
                    tool=config.tool,
                    status="error",
                    duration_ms=0,
                ),
            )
        return CollectorOutcome(
            config=config, evidence=evidence, persisted_path=persisted,
        )

    evidence = run_collector_with_timeout(
        cmd,
        collector=config.collector_id,
        tool=config.tool,
        category=config.category,
        timeout_s=timeout,
        cwd=checkout_path,
        parse_metrics=config.parse_metrics,
    )
    if not config.deterministic:
        evidence["deterministic"] = False

    persisted_path = persist_evidence_record(project_root, gate_id, evidence)

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy,
            audit_path,
            EvidenceCollectedAudit(
                gate_id=gate_id,
                category=config.category,
                collector=config.collector_id,
                tool=config.tool,
                status=evidence["status"],
                duration_ms=evidence.get("duration_ms", 0),
            ),
        )

    return CollectorOutcome(
        config=config,
        evidence=evidence,
        persisted_path=persisted_path,
    )


def run_gate_collectors(
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
    profile: dict[str, Any],
    registry: CollectorRegistry,
    *,
    diff_categories: set[str] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> list[CollectorOutcome]:
    """Run all applicable collectors for a gate evaluation.

    Creates a fresh checkout at commit_sha (§7), iterates applicable
    collectors from the registry, and returns collected evidence.

    Phase 1 crash isolation: each collector invocation is wrapped in a
    narrow ``except Exception`` so a bug in one collector cannot bring
    down the whole gate. ``BaseException`` (KeyboardInterrupt, SIGTERM)
    still propagates — operator signals must remain authoritative. The
    failure surfaces as an evidence record with ``status="error"`` and
    a synthetic ``exit_code=-1`` so the verdict engine treats it as
    real evidence rather than missing evidence.
    """
    assert_host_context("run_gate_collectors")
    collectors = registry.applicable(profile)
    if diff_categories is not None:
        collectors = [
            c for c in collectors if c.category in diff_categories
        ]
    if not collectors:
        return []

    outcomes: list[CollectorOutcome] = []
    with collector_checkout(project_root, commit_sha) as checkout:
        for config in collectors:
            try:
                outcome = run_single_collector(
                    config=config,
                    checkout_path=str(checkout),
                    profile=profile,
                    gate_id=gate_id,
                    project_root=project_root,
                    audit_policy=audit_policy,
                    audit_path=audit_path,
                )
            except Exception as exc:
                evidence = make_evidence_record(
                    collector=config.collector_id,
                    tool=config.tool,
                    category=config.category,
                    status="error",
                    findings=[f"collector crashed: {exc!r}"],
                    exit_code=-1,
                    deterministic=config.deterministic,
                )
                try:
                    persisted = persist_evidence_record(
                        project_root, gate_id, evidence,
                    )
                except Exception:
                    persisted = None
                outcome = CollectorOutcome(
                    config=config,
                    evidence=evidence,
                    persisted_path=persisted,
                )
            outcomes.append(outcome)
    return outcomes
