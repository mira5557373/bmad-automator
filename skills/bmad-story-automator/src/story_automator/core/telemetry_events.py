"""Typed telemetry events for bmad-automator (M01 wedge atom).

Provides the abstract Event base class with registry-based discriminator
dispatch, 13 concrete event types for the story lifecycle, an UnknownEvent
forward-compat fallback, and parse_event() with a documented round-trip
protocol. Emitter and reader live in M02.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

from story_automator.core.common import compact_json, iso_now


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


@dataclass(kw_only=True)
class UnknownEvent(Event):
    """Forward-compatibility fallback for unrecognized event types."""

    raw_event_type: str = ""
    raw_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Re-emit original event_type and all raw_fields."""
        return {"event_type": self.raw_event_type, **self.raw_fields}

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
    return cls(**payload)
