"""Gate audit events for hash-chaining into the HMAC audit log.

Minimal dataclasses satisfying the audit.Event protocol (event_name +
to_dict).  These do NOT live in telemetry_events.py (owned by M01).
Dedicated GateDecision/GateRendered telemetry events land in M18.
"""
from __future__ import annotations

import dataclasses
import pathlib
from typing import Any, Mapping

from .audit import audit_for_policy

__all__ = [
    "GateStartedAudit",
    "EvidenceCollectedAudit",
    "GateBoundaryViolation",
    "GateDecisionAudit",
    "GateRenderedAudit",
    "GateProfileDriftAudit",
    "GateParkedAudit",
    "GateReadinessAudit",
    "emit_gate_audit",
]


@dataclasses.dataclass(frozen=True)
class GateStartedAudit:
    """Audit event: gate evaluation started for a commit."""
    event_name: str = dataclasses.field(default="GateStarted", init=False)
    gate_id: str = ""
    commit_sha: str = ""
    profile_hash: str = ""
    tier: str = "code"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "commit_sha": self.commit_sha,
            "profile_hash": self.profile_hash,
            "tier": self.tier,
        }


@dataclasses.dataclass(frozen=True)
class EvidenceCollectedAudit:
    """Audit event: a single evidence collector completed."""
    event_name: str = dataclasses.field(default="EvidenceCollected", init=False)
    gate_id: str = ""
    category: str = ""
    collector: str = ""
    tool: str = ""
    status: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "category": self.category,
            "collector": self.collector,
            "tool": self.tool,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }


@dataclasses.dataclass(frozen=True)
class GateBoundaryViolation:
    """Audit event: a trust boundary violation was detected."""
    event_name: str = dataclasses.field(default="GateBoundaryViolation", init=False)
    operation: str = ""
    context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "context": self.context,
        }


@dataclasses.dataclass(frozen=True)
class GateDecisionAudit:
    """Audit event: adjudicator produced a verdict."""
    event_name: str = dataclasses.field(default="GateDecision", init=False)
    gate_id: str = ""
    overall: str = ""
    commit_sha: str = ""
    profile_hash: str = ""
    categories_summary: str = ""
    tier: str = "code"

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "overall": self.overall,
            "commit_sha": self.commit_sha,
            "profile_hash": self.profile_hash,
            "categories_summary": self.categories_summary,
            "tier": self.tier,
        }


@dataclasses.dataclass(frozen=True)
class GateRenderedAudit:
    """Audit event: gate file persisted to disk."""
    event_name: str = dataclasses.field(default="GateRendered", init=False)
    gate_id: str = ""
    gate_file_path: str = ""
    evidence_bundle_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "gate_file_path": self.gate_file_path,
            "evidence_bundle_hash": self.evidence_bundle_hash,
        }


@dataclasses.dataclass(frozen=True)
class GateProfileDriftAudit:
    """Audit event: gate reuse rejected due to profile/version drift."""
    event_name: str = dataclasses.field(default="GateProfileDrift", init=False)
    gate_id: str = ""
    old_hash: str = ""
    new_hash: str = ""
    old_factory_version: str = ""
    new_factory_version: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "old_hash": self.old_hash,
            "new_hash": self.new_hash,
            "old_factory_version": self.old_factory_version,
            "new_factory_version": self.new_factory_version,
            "reason": self.reason,
        }


@dataclasses.dataclass(frozen=True)
class GateParkedAudit:
    """Audit event: story parked due to exhaustion or unmitigated risk-9."""
    event_name: str = dataclasses.field(default="GateParked", init=False)
    gate_id: str = ""
    story_key: str = ""
    reason: str = ""
    overall_verdict: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "story_key": self.story_key,
            "reason": self.reason,
            "overall_verdict": self.overall_verdict,
        }


@dataclasses.dataclass(frozen=True)
class GateReadinessAudit:
    """Audit event: readiness check completed for a story."""
    event_name: str = dataclasses.field(default="GateReadinessCheck", init=False)
    story_id: str = ""
    verdict: str = ""
    priority: str = ""
    blocker_count: int = 0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "story_id": self.story_id,
            "verdict": self.verdict,
            "priority": self.priority,
            "blocker_count": self.blocker_count,
            "reason": self.reason,
        }


_AuditEvent = (
    GateStartedAudit | EvidenceCollectedAudit | GateBoundaryViolation
    | GateDecisionAudit | GateRenderedAudit
    | GateProfileDriftAudit | GateParkedAudit
    | GateReadinessAudit
)


def emit_gate_audit(
    policy: Mapping[str, Any],
    audit_path: pathlib.Path,
    event: _AuditEvent,
) -> None:
    """Emit a gate audit event through the HMAC audit chain.

    No-op when audit is disabled in policy (zero I/O).  Follows
    the same pattern as commands._audit_hooks._maybe_audit_event.
    """
    log = audit_for_policy(policy, audit_path)
    if log is None:
        return
    log.append(event)
