"""Minimal telemetry-event payload carriers used by the audit subsystem.

This module ships only what M04 needs: three frozen kw-only dataclasses
covering the three audit hook sites (escalation, state transition, retro
dispatch). Each class exposes:

  - ``event_name``: a class attribute equal to the class name; used by
    ``audit.AuditLog.append`` as the ``event`` field of the JSONL record.
  - ``to_dict()``: returns an instance-as-dict mapping in declaration
    order, suitable for ``audit.AuditLog`` to embed as ``payload``.

The classes intentionally satisfy ``audit.Event`` (structural Protocol)
without importing it — keeping the dependency edge one-way.
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
