"""Audit-trail payload carriers (M04).

These are intentionally separate from the M01 typed-telemetry taxonomy in
``telemetry_events.py``: they are minimal, structurally-typed payloads consumed
by the audit subsystem (``audit.AuditLog`` accepts anything exposing
``event_name`` + ``to_dict()`` via a runtime ``Protocol``). Kept in their own
module so the audit feature does not collide with or depend on the telemetry
event registry.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True, kw_only=True)
class EscalationRaised:
    """Operator-visible escalation raised by ``commands/orchestrator.py``."""

    event_name: str = dataclasses.field(default="EscalationRaised", init=False)
    trigger: str
    reason: str
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "reason": self.reason,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True, kw_only=True)
class StoryStateChanged:
    """State-doc frontmatter transition written by the state-update path."""

    event_name: str = dataclasses.field(default="StoryStateChanged", init=False)
    story: str
    from_status: str
    to_status: str
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "story": self.story,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True, kw_only=True)
class RetroAgentDispatched:
    """Retro-agent selection emitted by ``orchestrator_epic_agents.py``."""

    event_name: str = dataclasses.field(default="RetroAgentDispatched", init=False)
    primary: str
    fallback: str
    model: str
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "fallback": self.fallback,
            "model": self.model,
            "correlation_id": self.correlation_id,
        }
