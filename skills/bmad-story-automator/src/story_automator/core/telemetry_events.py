"""Typed telemetry events for bmad-automator (M01 wedge atom).

This module provides the `Event` base @dataclass with a registry-based
discriminator mechanism (auto-registration via __init_subclass__), the
shared envelope fields (timestamp, run_id), the serialization helpers
(to_dict, to_json_line), the `UnknownEvent` forward-compatibility
fallback, the `parse_event(line) -> Event` dispatch function with the
documented error matrix (ValueError on missing event_type,
json.JSONDecodeError on malformed input, TypeError on typed-event field
mismatch), and the 13 concrete typed event classes spanning the BMAD
story lifecycle (StoryStarted, StoryCompleted, StoryFailed,
StoryDeferred, RetryAttempt, EscalationTriggered, ReviewCycle,
RetroFired, TmuxSessionSpawned, TmuxSessionCompleted,
TmuxSessionCrashed, CostCharged, BudgetAlert). The full round-trip
invariant test suite plus the coverage / import-allowlist / module-size
quality gates land in m01-m4.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .common import compact_json, iso_now


@dataclass
class Event:
    """Base for all typed telemetry events.

    Concrete events declare an EVENT_TYPE classvar and become auto-
    registered via __init_subclass__, with duplicate-EVENT_TYPE detection
    (raises RuntimeError) and identity-check idempotency under re-import.
    The to_dict and to_json_line helpers emit JSON with event_type
    sourced from the EVENT_TYPE classvar (never an instance field).
    """

    EVENT_TYPE: ClassVar[str] = ""
    _REGISTRY: ClassVar[dict[str, type[Event]]] = {}

    timestamp: str
    run_id: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.EVENT_TYPE:
            return
        existing = Event._REGISTRY.get(cls.EVENT_TYPE)
        if existing is not None and existing is not cls:
            raise RuntimeError(
                f"duplicate EVENT_TYPE {cls.EVENT_TYPE!r}: "
                f"{existing.__qualname__} vs {cls.__qualname__}"
            )
        Event._REGISTRY[cls.EVENT_TYPE] = cls

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict with event_type injected from the
        EVENT_TYPE classvar.

        `event_type` is never an instance field. Subclasses cannot
        accidentally desync the discriminator from the class — the
        classvar is the single source of truth, and to_dict is the
        only place it's read into the payload.
        """
        data: dict[str, Any] = {"event_type": self.EVENT_TYPE}
        data.update(asdict(self))
        return data

    def to_json_line(self) -> str:
        """Compact single-line JSON suitable for JSONL emission.

        No trailing newline — the emitter (M02, out of scope here)
        is responsible for appending `\n` per JSONL convention.
        Uses `compact_json` from `story_automator.core.common` so the
        separator policy (",", ":") and `ensure_ascii=False` matches
        the rest of the codebase. The helper is NOT duplicated.
        """
        return compact_json(self.to_dict())


@dataclass
class UnknownEvent(Event):
    """Forward-compatibility fallback for unrecognized event_type strings.

    Carries the raw event_type and the unrecognized payload fields so a
    JSONL stream produced by a newer codebase can be read by an older
    parser without data loss. NOT auto-registered: `EVENT_TYPE = ""` so
    `__init_subclass__` skips it via the empty-string early return.
    """

    EVENT_TYPE: ClassVar[str] = ""

    raw_event_type: str
    raw_fields: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Re-emit the original ``event_type`` and unrecognized fields.

        Returns a dict shaped like the wire form of any other Event:
        ``{"event_type": <raw>, "timestamp": ..., "run_id": ..., **raw_fields}``.
        The internal ``raw_event_type`` and ``raw_fields`` field names do
        NOT appear in the output — they are implementation details that
        capture the unrecognized payload, not part of the JSONL contract.
        Key order is event_type -> timestamp -> run_id -> raw_fields-in-
        insertion-order, which is the canonical order produced by every
        other Event subclass's ``to_dict``. This is the contract that
        lets REQ-04's "byte-equal to the original input line" hold for
        canonically-ordered inputs (which is everything that came out of
        ``to_json_line``).
        """
        data: dict[str, Any] = {
            "event_type": self.raw_event_type,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
        }
        data.update(self.raw_fields)
        return data


@dataclass(kw_only=True)
class StoryStarted(Event):
    """Emitted when a tmux session spawns to begin work on a story."""

    EVENT_TYPE: ClassVar[str] = "story_started"

    epic: str
    story_key: str
    agent: str
    model: str
    complexity: str


@dataclass(kw_only=True)
class StoryCompleted(Event):
    """Emitted when a story is verified commit-ready."""

    EVENT_TYPE: ClassVar[str] = "story_completed"

    epic: str
    story_key: str
    duration_s: float
    cost_usd: float
    tokens_in: int
    tokens_out: int
    attempts: int


@dataclass(kw_only=True)
class StoryFailed(Event):
    """Emitted when all retries on a story have been exhausted."""

    EVENT_TYPE: ClassVar[str] = "story_failed"

    epic: str
    story_key: str
    error_class: str
    reason: str
    attempts: int
    final_session: str


@dataclass(kw_only=True)
class StoryDeferred(Event):
    """Emitted when plateau detection or a complexity cap defers a story."""

    EVENT_TYPE: ClassVar[str] = "story_deferred"

    epic: str
    story_key: str
    reason: str
    tasks_completed: int


@dataclass(kw_only=True)
class RetryAttempt(Event):
    """Emitted when starting a retry attempt (attempts 2 through 5)."""

    EVENT_TYPE: ClassVar[str] = "retry_attempt"

    epic: str
    story_key: str
    attempt_num: int
    agent: str
    model: str
    prev_error_class: str


@dataclass(kw_only=True)
class EscalationTriggered(Event):
    """Emitted when one of the escalation rules fires for a story."""

    EVENT_TYPE: ClassVar[str] = "escalation_triggered"

    epic: str
    story_key: str
    trigger_id: int
    severity: str
    message: str


@dataclass(kw_only=True)
class ReviewCycle(Event):
    """Emitted per code-review cycle (up to five per story)."""

    EVENT_TYPE: ClassVar[str] = "review_cycle"

    epic: str
    story_key: str
    cycle_num: int
    issues_found: int
    blocking: bool


@dataclass(kw_only=True)
class RetroFired(Event):
    """Emitted when an epic retrospective runs."""

    EVENT_TYPE: ClassVar[str] = "retro_fired"

    epic: str
    stories_completed: int
    total_cost_usd: float
    duration_s: float


@dataclass(kw_only=True)
class TmuxSessionSpawned(Event):
    """Emitted when a tmux session is created for a story."""

    EVENT_TYPE: ClassVar[str] = "tmux_session_spawned"

    session_name: str
    story_key: str
    pid: int
    pane_geometry: str


@dataclass(kw_only=True)
class TmuxSessionCompleted(Event):
    """Emitted when a tmux session exits normally."""

    EVENT_TYPE: ClassVar[str] = "tmux_session_completed"

    session_name: str
    story_key: str
    exit_code: int
    duration_s: float


@dataclass(kw_only=True)
class TmuxSessionCrashed(Event):
    """Emitted when a tmux session terminates abnormally."""

    EVENT_TYPE: ClassVar[str] = "tmux_session_crashed"

    session_name: str
    story_key: str
    exit_code: int
    last_capture_chars: int


@dataclass(kw_only=True)
class CostCharged(Event):
    """Emitted when each ``claude -p`` invocation completes."""

    EVENT_TYPE: ClassVar[str] = "cost_charged"

    epic: str
    story_key: str
    phase: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    model: str


@dataclass(kw_only=True)
class BudgetAlert(Event):
    """Emitted when crossing a 50/75/90/100 percent budget threshold."""

    EVENT_TYPE: ClassVar[str] = "budget_alert"

    threshold_pct: int
    total_cost_usd: float
    max_budget_usd: float
    epic: str
    story_key: str


def parse_event(line: str) -> Event:
    """Parse a single JSONL line into a typed ``Event`` instance.

    Dispatches by the ``event_type`` field. Known event_types route to the
    matching concrete subclass in ``Event._REGISTRY``; unknown event_types
    route to ``UnknownEvent`` (preserving the original event_type string
    and the unrecognized payload fields). Error semantics are documented
    in the M01 spec (REQ-07) and validated by the test matrix.
    """
    payload = json.loads(line)
    if "event_type" not in payload:
        raise ValueError(f"event missing 'event_type' field: {line[:80]!r}")
    event_type = payload.pop("event_type")
    cls = Event._REGISTRY.get(event_type)
    if cls is None:
        return UnknownEvent(
            timestamp=payload.pop("timestamp", ""),
            run_id=payload.pop("run_id", ""),
            raw_event_type=event_type,
            raw_fields=payload,
        )
    return cls(**payload)


__all__ = [
    "BudgetAlert",
    "CostCharged",
    "EscalationTriggered",
    "Event",
    "RetroFired",
    "RetryAttempt",
    "ReviewCycle",
    "StoryCompleted",
    "StoryDeferred",
    "StoryFailed",
    "StoryStarted",
    "TmuxSessionCompleted",
    "TmuxSessionCrashed",
    "TmuxSessionSpawned",
    "UnknownEvent",
    "compact_json",
    "iso_now",
    "parse_event",
]
