"""Outcome-reifier helpers for ``collector_isolation`` (G2 fold-in).

Extracted from ``collector_isolation.py`` to keep that module under
the 500-LOC soft limit after the AC-I-13 / AC-I-14 fold-in. These are
PURE helpers — they DO NOT call ``run_collectors_per_unit`` and so do
NOT need to be exempted by the audit-floor dispatch invariant.

The four reifier functions match ``collector_runner``'s error-path
shape (persist evidence + best-effort audit-emit) so per-unit error
records are byte-equivalent to shared-mode error records.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .collector_config import CollectorConfig, CollectorOutcome
from .evidence_io import persist_evidence_record
from .gate_audit import EvidenceCollectedAudit, emit_gate_audit
from .gate_schema import make_evidence_record

__all__ = [
    "make_error_outcome",
    "error_outcome",
    "crash_outcome",
    "audit_timeout_outcome",
]


def make_error_outcome(
    config: CollectorConfig,
    findings: list[str],
    project_root: str | Path,
    gate_id: str,
    audit_policy: dict[str, Any] | None,
    audit_path: Path | None,
) -> CollectorOutcome:
    """Mirror ``collector_runner``'s error path: persist evidence + emit audit."""
    evidence = make_evidence_record(
        collector=config.collector_id,
        tool=config.tool,
        category=config.category,
        status="error",
        findings=findings,
        exit_code=-1,
        deterministic=config.deterministic,
    )
    try:
        persisted = persist_evidence_record(project_root, gate_id, evidence)
    except Exception:
        persisted = None
    if audit_policy is not None and audit_path is not None:
        try:
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
        except Exception:
            # Audit emission failure here is observability-only and
            # must not corrupt the outcome.
            pass
    return CollectorOutcome(
        config=config,
        evidence=evidence,
        persisted_path=persisted,
    )


def error_outcome(
    config: CollectorConfig,
    exc: BaseException,
    project_root: str | Path,
    gate_id: str,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> CollectorOutcome:
    """Reify a checkout-creation failure as an ``error`` outcome."""
    return make_error_outcome(
        config,
        [f"checkout failed: {exc}"],
        project_root,
        gate_id,
        audit_policy,
        audit_path,
    )


def crash_outcome(
    config: CollectorConfig,
    exc: BaseException,
    project_root: str | Path,
    gate_id: str,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> CollectorOutcome:
    """Reify a worker-thread Exception / BaseException as ``error`` outcome.

    The finding string carries the exception type name so operators can
    distinguish a crash from a slow-disk audit timeout.
    """
    return make_error_outcome(
        config,
        [f"worker terminated: {type(exc).__name__}: {exc}"],
        project_root,
        gate_id,
        audit_policy,
        audit_path,
    )


def audit_timeout_outcome(
    config: CollectorConfig,
    exc: BaseException,
    project_root: str | Path,
    gate_id: str,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> CollectorOutcome:
    """Reify an ``AuditLockTimeout`` (after retry) as an ``error`` outcome.

    Finding string is intentionally distinct from ``crash_outcome``.
    """
    return make_error_outcome(
        config,
        [f"audit lock timeout after retry: {exc}"],
        project_root,
        gate_id,
        audit_policy,
        audit_path,
    )
