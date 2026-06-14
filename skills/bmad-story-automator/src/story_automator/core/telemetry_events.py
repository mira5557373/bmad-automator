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


# Placeholder implementations - to be properly defined in later tasks
@dataclass(kw_only=True)
class UnknownEvent(Event):
    EVENT_TYPE: ClassVar[str] = ""
    raw_event_type: str = ""
    raw_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True)
class StoryStarted(Event):
    EVENT_TYPE: ClassVar[str] = "story_started"
    epic: str = ""
    story_key: str = ""
    agent: str = ""
    model: str = ""
    complexity: str = ""


@dataclass(kw_only=True)
class StoryCompleted(Event):
    EVENT_TYPE: ClassVar[str] = "story_completed"
    epic: str = ""
    story_key: str = ""
    duration_s: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: int = 0


@dataclass(kw_only=True)
class StoryFailed(Event):
    EVENT_TYPE: ClassVar[str] = "story_failed"
    epic: str = ""
    story_key: str = ""
    error_class: str = ""
    reason: str = ""
    attempts: int = 0
    final_session: str = ""


@dataclass(kw_only=True)
class StoryDeferred(Event):
    EVENT_TYPE: ClassVar[str] = "story_deferred"
    epic: str = ""
    story_key: str = ""
    reason: str = ""
    tasks_completed: int = 0


@dataclass(kw_only=True)
class RetryAttempt(Event):
    EVENT_TYPE: ClassVar[str] = "retry_attempt"
    epic: str = ""
    story_key: str = ""
    attempt_num: int = 0
    agent: str = ""
    model: str = ""
    prev_error_class: str = ""


@dataclass(kw_only=True)
class EscalationTriggered(Event):
    EVENT_TYPE: ClassVar[str] = "escalation_triggered"
    epic: str = ""
    story_key: str = ""
    trigger_id: int = 0
    severity: str = ""
    message: str = ""


@dataclass(kw_only=True)
class ReviewCycle(Event):
    EVENT_TYPE: ClassVar[str] = "review_cycle"
    epic: str = ""
    story_key: str = ""
    cycle_num: int = 0
    issues_found: int = 0
    blocking: bool = False


@dataclass(kw_only=True)
class RetroFired(Event):
    EVENT_TYPE: ClassVar[str] = "retro_fired"
    epic: str = ""
    stories_completed: int = 0
    total_cost_usd: float = 0.0
    duration_s: float = 0.0


@dataclass(kw_only=True)
class TmuxSessionSpawned(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_spawned"
    session_name: str = ""
    story_key: str = ""
    pid: int = 0
    pane_geometry: str = ""


@dataclass(kw_only=True)
class TmuxSessionCompleted(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_completed"
    session_name: str = ""
    story_key: str = ""
    exit_code: int = 0
    duration_s: float = 0.0


@dataclass(kw_only=True)
class TmuxSessionCrashed(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_crashed"
    session_name: str = ""
    story_key: str = ""
    exit_code: int = 0
    last_capture_chars: int = 0


@dataclass(kw_only=True)
class CostCharged(Event):
    EVENT_TYPE: ClassVar[str] = "cost_charged"
    epic: str = ""
    story_key: str = ""
    phase: str = ""
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


@dataclass(kw_only=True)
class BudgetAlert(Event):
    EVENT_TYPE: ClassVar[str] = "budget_alert"
    threshold_pct: int = 0
    total_cost_usd: float = 0.0
    max_budget_usd: float = 0.0
    epic: str = ""
    story_key: str = ""


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
