"""Typed telemetry events for bmad-automator (M01 wedge atom).

Provides the abstract Event base class with registry-based discriminator
dispatch, 13 concrete event types for the story lifecycle, an UnknownEvent
forward-compat fallback, and parse_event() with a documented round-trip
protocol. Emitter and reader live in M02.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

from story_automator.core.common import compact_json

__all__ = [
    "Event",
    "UnknownEvent",
    "StoryStarted",
    "StoryCompleted",
    "StoryFailed",
    "StoryDeferred",
    "RetryAttempt",
    "EscalationTriggered",
    "ReviewCycle",
    "RetroFired",
    "TmuxSessionSpawned",
    "TmuxSessionCompleted",
    "TmuxSessionCrashed",
    "CostCharged",
    "BudgetAlert",
    "parse_event",
]


@dataclass
class Event:
    """Abstract base class for typed events."""

    EVENT_TYPE: ClassVar[str] = "event"
    _REGISTRY: ClassVar[dict[str, type[Event]]] = {}

    timestamp: str
    run_id: str

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Skip auto-registration for UnknownEvent
        if cls.__name__ == "UnknownEvent":
            return
        event_type = cls.EVENT_TYPE
        existing = Event._REGISTRY.get(event_type)
        if existing is not None and existing is not cls:
            raise RuntimeError(
                f"Duplicate EVENT_TYPE {event_type!r}: "
                f"existing {existing.__qualname__} conflicts with {cls.__qualname__}"
            )
        Event._REGISTRY[event_type] = cls

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dict with event_type injected first."""
        d = asdict(self)
        # Build new dict with event_type first to ensure deterministic key order
        return {"event_type": self.EVENT_TYPE, **d}

    def to_json_line(self) -> str:
        """Serialize to compact single-line JSON without trailing newline."""
        return compact_json(self.to_dict())


@dataclass(kw_only=True)
class UnknownEvent(Event):
    """Forward-compatibility fallback for unrecognized event types."""

    raw_event_type: str = ""
    raw_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Re-emit original event_type, timestamp, run_id, and all raw_fields."""
        return {
            "event_type": self.raw_event_type,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            **self.raw_fields,
        }

    def to_json_line(self) -> str:
        """Return compact JSON without newline."""
        return compact_json(self.to_dict())


@dataclass
class StoryStarted(Event):
    EVENT_TYPE: ClassVar[str] = "story_started"
    epic: str
    story_key: str
    agent: str
    model: str
    complexity: str


@dataclass
class StoryCompleted(Event):
    EVENT_TYPE: ClassVar[str] = "story_completed"
    epic: str
    story_key: str
    duration_s: float
    cost_usd: float
    tokens_in: int
    tokens_out: int
    attempts: int


@dataclass
class StoryFailed(Event):
    EVENT_TYPE: ClassVar[str] = "story_failed"
    epic: str
    story_key: str
    error_class: str
    reason: str
    attempts: int
    final_session: str


@dataclass
class StoryDeferred(Event):
    EVENT_TYPE: ClassVar[str] = "story_deferred"
    epic: str
    story_key: str
    reason: str
    tasks_completed: int


@dataclass
class RetryAttempt(Event):
    EVENT_TYPE: ClassVar[str] = "retry_attempt"
    epic: str
    story_key: str
    attempt_num: int
    agent: str
    model: str
    prev_error_class: str


@dataclass
class EscalationTriggered(Event):
    EVENT_TYPE: ClassVar[str] = "escalation_triggered"
    epic: str
    story_key: str
    trigger_id: int
    severity: str
    message: str


@dataclass
class ReviewCycle(Event):
    EVENT_TYPE: ClassVar[str] = "review_cycle"
    epic: str
    story_key: str
    cycle_num: int
    issues_found: int
    blocking: bool


@dataclass
class RetroFired(Event):
    EVENT_TYPE: ClassVar[str] = "retro_fired"
    epic: str
    stories_completed: int
    total_cost_usd: float
    duration_s: float


@dataclass
class TmuxSessionSpawned(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_spawned"
    session_name: str
    story_key: str
    pid: int
    pane_geometry: str


@dataclass
class TmuxSessionCompleted(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_completed"
    session_name: str
    story_key: str
    exit_code: int
    duration_s: float


@dataclass
class TmuxSessionCrashed(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_crashed"
    session_name: str
    story_key: str
    exit_code: int
    last_capture_chars: int


@dataclass
class CostCharged(Event):
    EVENT_TYPE: ClassVar[str] = "cost_charged"
    epic: str
    story_key: str
    phase: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    model: str


@dataclass
class BudgetAlert(Event):
    EVENT_TYPE: ClassVar[str] = "budget_alert"
    threshold_pct: int
    total_cost_usd: float
    max_budget_usd: float
    epic: str
    story_key: str


def parse_event(line: str) -> Event:
    """Parse a single JSONL line into a typed Event."""
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
    # Validate field types before instantiation
    _validate_event_fields(cls, payload)
    return cls(**payload)


def _is_optional_type(tp: Any) -> bool:
    """Check if a type hint includes None (e.g., str | None or Optional[str])."""
    origin = typing.get_origin(tp)
    if origin is typing.Union:
        args = typing.get_args(tp)
        return type(None) in args
    return False


def _validate_event_fields(cls: type[Event], payload: dict[str, Any]) -> None:
    """Validate that payload fields match expected types for the event class."""
    field_types = {}
    for f in dataclasses.fields(cls):
        # Use get_type_hints to resolve string annotations from __future__ import
        field_types[f.name] = f.type

    # Get resolved type hints
    type_hints = typing.get_type_hints(cls)

    for key, value in payload.items():
        if key not in field_types:
            # Unknown field will be caught by dataclass constructor
            continue
        expected_type = type_hints.get(key, field_types[key])
        # Reject None for non-optional fields (no union with None)
        if value is None and not _is_optional_type(expected_type):
            raise TypeError(f"Field {key!r} does not accept None")
        if value is None:
            continue
        # Reject floats for int fields
        if expected_type is int and isinstance(value, float):
            raise TypeError(f"Field {key!r} expects int, got float: {value}")
        # Accept ints for float fields (Python standard coercion)
        if (
            expected_type is float
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            # Will be coerced by Python; no error
            pass
        # Reject strings for bool fields
        if expected_type is bool and isinstance(value, str):
            raise TypeError(f"Field {key!r} expects bool, got string: {value!r}")
        # Reject strings for int fields
        if expected_type is int and isinstance(value, str):
            raise TypeError(f"Field {key!r} expects int, got string: {value!r}")
