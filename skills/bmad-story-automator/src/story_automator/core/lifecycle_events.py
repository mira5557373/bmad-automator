"""Lifecycle macro-layer telemetry events (W0-M02).

Subclasses of ``core.telemetry_events.Event`` that auto-register into the
shared ``Event._REGISTRY`` via the inherited ``__init_subclass__``. The hard
guardrail forbids editing ``core/telemetry_events.py`` outside M01, so the
new event types live in this sibling module and re-use the existing base.
Auto-registration still flows through the base's ``__init_subclass__``, so
``parse_event`` and ``TelemetryReader`` dispatch them like any other typed
event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from story_automator.core.telemetry_events import Event

__all__ = [
    "LifecyclePhaseCompleted",
    "LifecyclePhaseFailed",
    "LifecyclePhaseStarted",
]


@dataclass(kw_only=True)
class LifecyclePhaseStarted(Event):
    """Emitted when the phase runner commits a node to RUNNING."""

    EVENT_TYPE: ClassVar[str] = "lifecycle_phase_started"

    node_id: str
    phase: int
    track: str
    skill: str
    agent_role: str


@dataclass(kw_only=True)
class LifecyclePhaseCompleted(Event):
    """Emitted when a node verifier passes (state advances to COMPLETE
    or AWAITING_APPROVAL when gate=human)."""

    EVENT_TYPE: ClassVar[str] = "lifecycle_phase_completed"

    node_id: str
    phase: int
    track: str
    duration_s: float
    gate_decision: str


@dataclass(kw_only=True)
class LifecyclePhaseFailed(Event):
    """Emitted when a node fails (agent crashed, monitor timeout, or
    verifier returned verified=False)."""

    EVENT_TYPE: ClassVar[str] = "lifecycle_phase_failed"

    node_id: str
    phase: int
    track: str
    reason: str
    error_class: str
    attempt: int
