"""Failure-triage taxonomy foundation for bmad-automator (M07a).

This module defines the pure-data substrate that downstream triage
(M07b classify dispatch), adaptive retry (M08), gate decisions (M09),
and the retrospective summariser (M10) consume:

- ``FailureClass`` — the closed 13-member taxonomy of failure shapes.
- ``Confidence`` — three-level confidence ordinal (HIGH/MEDIUM/LOW).
- ``Classification`` — frozen, kw-only result record paired with each
  failure-shaped event.
- ``IMPLIES_GRAPH`` — the static implication edges between members of
  ``FailureClass``. Runtime classifiers may extend the per-event
  ``implies`` tuple based on payload hints (e.g. transport hints on a
  tmux crash) — those extensions live in ``classify`` (M07b) and are
  not encoded here.

M07a is data-only: no ``classify`` function, no dispatch logic, no I/O,
no third-party imports. The classify dispatch and per-event helpers
land in M07b.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator  # noqa: F401  # used in stringified annotations only under `from __future__ import annotations`
from dataclasses import dataclass
import enum

from story_automator.core.telemetry_events import (
    EscalationTriggered,
    Event,
    StoryDeferred,
    StoryFailed,
    TmuxSessionCrashed,
)


class FailureClass(enum.Enum):
    """Closed taxonomy of failure shapes consumed by triage.

    Exactly thirteen members. Declaration order is the canonical order
    asserted by the taxonomy-completeness gate (REQ-02). String values
    equal the member name so JSONL serialisations in M07b round-trip
    cleanly.
    """

    CRASH = "CRASH"
    TIMEOUT = "TIMEOUT"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    TEST_FAILURE = "TEST_FAILURE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PARSE_ERROR = "PARSE_ERROR"
    AGENT_REFUSED = "AGENT_REFUSED"
    NETWORK_ERROR = "NETWORK_ERROR"
    GATE_DEFER = "GATE_DEFER"
    PLATEAU = "PLATEAU"
    REPEATED_RETRY = "REPEATED_RETRY"
    UNKNOWN = "UNKNOWN"


class Confidence(enum.Enum):
    """Three-level confidence ordinal for a classification.

    Case-sensitive member names mirror the value strings; serialisations
    in M07b emit the bare member name so downstream policy engines (M08
    adaptive retry, M09 gate) can match on string equality without
    needing to import this enum.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, kw_only=True)
class Classification:
    """Frozen verdict produced by ``classify`` (M07b) for one event.

    Fields:

    - ``primary`` — the leading ``FailureClass`` for this event.
    - ``implies`` — additional ``FailureClass`` entries downstream policy
      should treat as concurrently true (e.g. ``POLICY_VIOLATION``
      always implies ``REVIEW_REJECTED``). Empty tuple when no
      implications apply. Order is stable per-classifier to keep
      ``Classification`` instances hashable-equivalent.
    - ``confidence`` — operator-facing certainty level.
    - ``reason`` — short snake-case string explaining the verdict.
      Used by M10 retro summaries; never user-facing prose.
    - ``event_id`` — the originating event's identifier when available,
      else ``None``. M01 events do not yet carry an ``event_id`` field
      so this is currently always ``None`` in practice; reserved so
      downstream consumers can correlate verdicts back to source events
      once the field lands.
    """

    primary: FailureClass
    implies: tuple[FailureClass, ...]
    confidence: Confidence
    reason: str
    event_id: str | None


IMPLIES_GRAPH: dict[FailureClass, tuple[FailureClass, ...]] = {
    FailureClass.POLICY_VIOLATION: (FailureClass.REVIEW_REJECTED,),
    FailureClass.BUDGET_EXCEEDED: (FailureClass.GATE_DEFER,),
    FailureClass.REPEATED_RETRY: (FailureClass.PLATEAU,),
}
# Spec REQ-05 also mentions a conditional CRASH -> (NETWORK_ERROR,) edge
# "when transport hints are present". That edge is *runtime conditional*
# on the tmux-crash payload, not a static implication of CRASH itself
# (most crashes are not network-shaped). It is therefore applied inside
# `_classify_tmux_crash` (M07b), not encoded here.


__all__ = [
    "Classification",
    "Confidence",
    "FailureClass",
    "IMPLIES_GRAPH",
]


def classify(event: Event) -> Classification:
    """Classify a single telemetry event into a ``Classification`` verdict.

    Pure-functional: no I/O, no clock reads, no allocations beyond the
    returned ``Classification`` and the implies tuple. Never raises on a
    well-formed concrete event subclass shipped in M01 — unknown shapes
    return the ``UNKNOWN`` sentinel with ``LOW`` confidence rather than
    propagating an exception (REQ-06).

    Dispatch order matches the spec REQ-07 list: ``StoryFailed`` →
    ``_classify_story_failed``, ``StoryDeferred`` →
    ``_classify_story_deferred``, ``TmuxSessionCrashed`` →
    ``_classify_tmux_crash``, ``EscalationTriggered`` →
    ``_classify_escalation``. Every other event subtype — including
    ``UnknownEvent`` and the success-shaped events — short-circuits to
    the ``non_failure_event`` UNKNOWN verdict.
    """
    event_id = getattr(event, "event_id", None)
    if isinstance(event, StoryFailed):
        return _classify_story_failed(event)
    if isinstance(event, StoryDeferred):
        return _classify_story_deferred(event)
    if isinstance(event, TmuxSessionCrashed):
        return _classify_tmux_crash(event)
    if isinstance(event, EscalationTriggered):
        return _classify_escalation(event)
    return Classification(
        primary=FailureClass.UNKNOWN,
        implies=(),
        confidence=Confidence.LOW,
        reason="non_failure_event",
        event_id=event_id,
    )


def _classify_story_failed(event: StoryFailed) -> Classification:
    raise NotImplementedError  # implemented in Task 5


def _classify_story_deferred(event: StoryDeferred) -> Classification:
    raise NotImplementedError  # implemented in Task 9


def _classify_tmux_crash(event: TmuxSessionCrashed) -> Classification:
    raise NotImplementedError  # implemented in Task 7


def _classify_escalation(event: EscalationTriggered) -> Classification:
    raise NotImplementedError  # implemented in Task 11
