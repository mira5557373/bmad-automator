"""Collector runner — orchestrates evidence collection for gate evaluation.

Runs individual collectors via run_collector_with_timeout (§6.4),
persists evidence via persist_evidence_record, and emits audit events.
Full gate loop and diff-scoped mode added in subsequent tasks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .adjudicator import resolve_timeout, run_collector_with_timeout
from .collector_config import CollectorConfig, CollectorOutcome
from .evidence_io import persist_evidence_record
from .gate_audit import EvidenceCollectedAudit, emit_gate_audit
from .gate_schema import make_evidence_record
from .trust_boundary import assert_host_context

__all__ = [
    "run_single_collector",
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
    )

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
