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


def emit_gate_audit(
    policy: Mapping[str, Any],
    audit_path: pathlib.Path,
    event: GateStartedAudit | EvidenceCollectedAudit | GateBoundaryViolation,
) -> None:
    """Emit a gate audit event through the HMAC audit chain.

    No-op when audit is disabled in policy (zero I/O).  Follows
    the same pattern as commands._audit_hooks._maybe_audit_event.
    """
    log = audit_for_policy(policy, audit_path)
    if log is None:
        return
    log.append(event)
