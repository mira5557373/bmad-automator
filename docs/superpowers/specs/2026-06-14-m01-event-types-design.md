# M01 — Event types (wedge atom) — Design

**Date:** 2026-06-14
**Milestone:** M01 of the bmad-automator port
**Source feature:** #2 (typed telemetry — wedge atom)
**Author:** mira5557373 (operator) + Claude Opus 4.7 (assistant, superpowers:brainstorming)
**Status:** Draft — pending operator review before transformation to sw-lint-passing spec

## Purpose

M01 is the wedge atom for the typed-telemetry substrate that subsequent milestones build on. It introduces an `Event` base class with a registry-based discriminator system, 13 concrete typed event dataclasses spanning bmad-automator's story lifecycle, an `UnknownEvent` forward-compatibility fallback, and a `parse_event` function with a documented round-trip protocol. M01 explicitly defers the `TelemetryEmitter`, the `TelemetryReader`, and the wiring of existing log sites — those land in M02. M01's contract is "these are the typed events as of M01; round-trip is byte-equal for known types and forward-preserving for unknown types."

## Scope

In scope:

- New module `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` (~300–400 LOC)
- New test file `tests/test_telemetry_events.py` (~30 tests, ~85% line coverage target)
- 13 concrete typed event classes covering the BMAD story lifecycle, tmux session lifecycle, cost charging, and budget alerts
- `UnknownEvent` forward-compat fallback
- `parse_event(line: str) -> Event` parsing function with documented failure modes
- Round-trip invariant: byte-equal re-emission for any typed event

Out of scope (deferred to subsequent milestones):

- `TelemetryEmitter` (locked JSONL writer) — M02
- `TelemetryReader` aggregations (`cost_by_story`, `attempts_by_story`, etc.) — M02
- Wiring existing log sites to emit typed events — M02
- Cost field on the Haiku parser output — M03
- HMAC chaining on the event stream — M04 (separate substrate)
- Failure classification consuming event_type — M07

## Module layout

```
skills/bmad-story-automator/src/story_automator/core/
  telemetry_events.py     ← NEW (M01)
                          (Event, UnknownEvent, 13 concrete classes, parse_event)

tests/
  test_telemetry_events.py ← NEW (M01)
                          (~30 tests across 4 TestCase classes)
```

The new module follows existing core/ conventions:

- `from __future__ import annotations` at top
- Plain `@dataclass` decorator (matching `agent_config.py`)
- PEP 604 union types (`str | None`)
- Imports `iso_now` and `compact_json` from `.common`
- snake_case Python attributes, snake_case JSON keys
- Estimated 300-400 LOC — well under the CONTRIBUTING.md ~500 LOC guideline

## Event base class

```python
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, ClassVar
from .common import iso_now, compact_json
import json


@dataclass
class Event:
    """Base for all typed telemetry events.

    Concrete events declare an EVENT_TYPE classvar and become
    auto-registered via __init_subclass__. Round-trip protocol:
    event.to_json_line() → JSONL line → parse_event(line) → typed
    instance. Unknown event_type strings route to UnknownEvent.
    """

    EVENT_TYPE: ClassVar[str] = ""               # set by subclass
    _REGISTRY: ClassVar[dict[str, type[Event]]] = {}

    timestamp: str                                # iso_now() format: "%Y-%m-%dT%H:%M:%SZ"
    run_id: str                                   # e.g. "20260614-051234"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.EVENT_TYPE and cls is not UnknownEvent:
            existing = Event._REGISTRY.get(cls.EVENT_TYPE)
            if existing is not None and existing is not cls:
                raise RuntimeError(
                    f"duplicate EVENT_TYPE {cls.EVENT_TYPE!r}: "
                    f"{existing.__qualname__} vs {cls.__qualname__}"
                )
            Event._REGISTRY[cls.EVENT_TYPE] = cls

    def to_dict(self) -> dict[str, Any]:
        """Inject event_type from classvar; serialize fields via asdict."""
        d: dict[str, Any] = {"event_type": self.EVENT_TYPE}
        d.update(asdict(self))
        return d

    def to_json_line(self) -> str:
        """Compact single-line JSON for JSONL emission (no trailing newline)."""
        return compact_json(self.to_dict())
```

**Design notes:**

- Duplicate `EVENT_TYPE` strings across subclasses raise `RuntimeError` at import time (not silent overwrite — caught early)
- Identity check `existing is not cls` lets the module be safely reimported in tests
- `event_type` is NEVER an instance field — it comes from the classvar via `to_dict`. Subclasses cannot desynchronize.
- `UnknownEvent` is excluded from auto-registration so its `EVENT_TYPE = ""` doesn't collide.

## The 13 concrete event types

Each row is a `@dataclass` subclass of `Event`. All fields are required (no defaults — M01 strictness). All field types are JSON-serializable stdlib primitives (str / int / float / bool / list / dict).

| # | Class | `EVENT_TYPE` | Additional fields | Emitted when |
|---|---|---|---|---|
| 1 | `StoryStarted` | `story_started` | `epic: str`, `story_key: str`, `agent: str`, `model: str`, `complexity: str` | tmux session spawns for a story |
| 2 | `StoryCompleted` | `story_completed` | `epic: str`, `story_key: str`, `duration_s: float`, `cost_usd: float`, `tokens_in: int`, `tokens_out: int`, `attempts: int` | story commit-ready verified |
| 3 | `StoryFailed` | `story_failed` | `epic: str`, `story_key: str`, `error_class: str`, `reason: str`, `attempts: int`, `final_session: str` | all retries exhausted |
| 4 | `StoryDeferred` | `story_deferred` | `epic: str`, `story_key: str`, `reason: str`, `tasks_completed: int` | plateau detection fires |
| 5 | `RetryAttempt` | `retry_attempt` | `epic: str`, `story_key: str`, `attempt_num: int`, `agent: str`, `model: str`, `prev_error_class: str` | starting a retry (attempts 2-5) |
| 6 | `EscalationTriggered` | `escalation_triggered` | `epic: str`, `story_key: str`, `trigger_id: int`, `severity: str`, `message: str` | escalation rule fires |
| 7 | `ReviewCycle` | `review_cycle` | `epic: str`, `story_key: str`, `cycle_num: int`, `issues_found: int`, `blocking: bool` | per code-review cycle (up to 5) |
| 8 | `RetroFired` | `retro_fired` | `epic: str`, `stories_completed: int`, `total_cost_usd: float`, `duration_s: float` | per-epic retrospective runs |
| 9 | `TmuxSessionSpawned` | `tmux_session_spawned` | `session_name: str`, `story_key: str`, `pid: int`, `pane_geometry: str` | tmux session created |
| 10 | `TmuxSessionCompleted` | `tmux_session_completed` | `session_name: str`, `story_key: str`, `exit_code: int`, `duration_s: float` | tmux session exits normally |
| 11 | `TmuxSessionCrashed` | `tmux_session_crashed` | `session_name: str`, `story_key: str`, `exit_code: int`, `last_capture_chars: int` | tmux session abnormal exit |
| 12 | `CostCharged` | `cost_charged` | `epic: str`, `story_key: str`, `phase: str`, `cost_usd: float`, `tokens_in: int`, `tokens_out: int`, `model: str` | each `claude -p` invocation completes |
| 13 | `BudgetAlert` | `budget_alert` | `threshold_pct: int`, `total_cost_usd: float`, `max_budget_usd: float`, `epic: str`, `story_key: str` | crossing 50/75/90/100% budget threshold |

Reserved values for string fields (documented but not enforced in M01 — enforcement lives in M07 for `severity`/`error_class`/`reason` and in the orchestrator for `phase`):

- `severity` ∈ `{"CRITICAL", "PREFERENCE"}`
- `reason` for `StoryDeferred` ∈ `{"plateau", "complexity_cap"}`
- `threshold_pct` ∈ `{50, 75, 90, 100}`
- `trigger_id` ∈ `{1, 2, 3, 4, 5, 6, 7, 8}` (matches the 8 escalation triggers in `data/escalation-triggers.md`)

## UnknownEvent forward-compatibility fallback

```python
@dataclass
class UnknownEvent(Event):
    """Fallback for unrecognized event_type strings.

    Preserves the original event_type string and all unrecognized fields
    so a JSONL stream produced by a newer codebase can still be read by
    an older parser without data loss.
    """

    EVENT_TYPE: ClassVar[str] = ""   # not registered; never matched directly

    raw_event_type: str              # the event_type from the JSON line
    raw_fields: dict[str, Any]       # everything except event_type/timestamp/run_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.raw_event_type,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            **self.raw_fields,
        }
```

## parse_event() contract

```python
def parse_event(line: str) -> Event:
    """Parse a single JSONL line into a typed Event.

    Contract:
    - Valid JSON, valid event_type in registry  → typed subclass instance
    - Valid JSON, unrecognized event_type       → UnknownEvent
    - Valid JSON, missing event_type field      → raises ValueError
    - Invalid JSON                              → raises json.JSONDecodeError
    - Missing required field on typed event     → raises TypeError (dataclass)
    - Extra field on typed event                → raises TypeError (dataclass)
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
```

### Failure-mode table

| Input | Result |
|---|---|
| Well-formed typed event | Typed instance (e.g., `StoryStarted(...)`) |
| Well-formed unknown event_type | `UnknownEvent` with `raw_event_type` + `raw_fields` preserved |
| Missing `event_type` field | `ValueError` — structural error, NOT forward-compat |
| Missing `timestamp` or `run_id` on UnknownEvent | Empty-string sentinel (defensive — lets old code read newer streams) |
| Missing required field on typed event | `TypeError` from dataclass `__init__` (strict) |
| Extra field on typed event | `TypeError` from dataclass `__init__` (strict) |
| Invalid JSON | `json.JSONDecodeError` |

## Round-trip protocol invariants

For every concrete event class `E` other than `UnknownEvent`:

```python
instance = E(...)                          # constructed with required fields
line = instance.to_json_line()             # single-line JSON string
parsed = parse_event(line)
assert type(parsed) is E                   # dispatched to correct class
assert parsed == instance                  # dataclass equality
assert parsed.to_json_line() == line       # byte-equal re-serialization
```

For `UnknownEvent`:

```python
raw = '{"event_type":"future_thing_M99","timestamp":"...","run_id":"...","fancy_field":42}'
parsed = parse_event(raw)
assert isinstance(parsed, UnknownEvent)
assert parsed.raw_event_type == "future_thing_M99"
assert parsed.raw_fields == {"fancy_field": 42}
assert parsed.to_json_line() == raw        # byte-equal preserve
```

## Serialization rules

1. Field ordering in JSON output: `event_type` first, then `timestamp`, then `run_id`, then class-specific fields in dataclass declaration order. Achieved naturally because `to_dict` returns `{"event_type": ..., **asdict(self)}` and `asdict` preserves declaration order with base-class fields first.
2. No null values for required fields. M01 has no field defaults. M02+ may introduce defaults if needed — that's an evolution decision then.
3. No nested dataclasses in M01. Fields are stdlib primitives only (str, int, float, bool, list, dict). Keeps `asdict` round-trip trivial. M02 may introduce nested types.
4. String encoding via `compact_json` uses `ensure_ascii=False` so non-ASCII story keys serialize natively (matches existing codebase convention).
5. No trailing newline in `to_json_line` — the emitter (M02) is responsible for appending `\n` per JSONL convention.

## Public API surface

| Name | Kind | Purpose |
|---|---|---|
| `Event` | class | Base, shared envelope, registry mechanism |
| `UnknownEvent` | class | Forward-compat fallback |
| `StoryStarted` … `BudgetAlert` (13 classes) | class | Concrete typed events |
| `parse_event(line: str) -> Event` | function | JSONL line → typed instance |
| `EVENT_REGISTRY` | dict (read-only alias for `Event._REGISTRY`) | Introspection of registered types |

No emit functions, no reader functions, no aggregations. Those land in M02.

## Test plan

Pure `unittest.TestCase` style, cross-platform (no tmux dependency), matching `tests/test_agent_config_model.py` conventions.

### `EventBaseTests`

- `test_event_type_classvar_required` — subclass without EVENT_TYPE: still works but is not registered
- `test_duplicate_event_type_raises` — two subclasses declaring the same EVENT_TYPE raise `RuntimeError` at import
- `test_registry_lookup_by_event_type` — `Event._REGISTRY["story_started"]` is `StoryStarted`
- `test_registry_excludes_unknown_event` — `UnknownEvent` is not in `_REGISTRY`
- `test_to_dict_injects_event_type` — subclass instance's `to_dict` has the correct event_type
- `test_to_json_line_is_single_line` — no embedded newline
- `test_to_json_line_uses_compact_separators` — no whitespace (matches `compact_json`)

### `ConcreteEventRoundTripTests`

One test per concrete event class (13 tests), each constructing with required fields, serializing, parsing back, asserting type identity + equality + byte-equal re-emission:

- `test_story_started_round_trip`
- `test_story_completed_round_trip`
- `test_story_failed_round_trip`
- `test_story_deferred_round_trip`
- `test_retry_attempt_round_trip`
- `test_escalation_triggered_round_trip`
- `test_review_cycle_round_trip`
- `test_retro_fired_round_trip`
- `test_tmux_session_spawned_round_trip`
- `test_tmux_session_completed_round_trip`
- `test_tmux_session_crashed_round_trip`
- `test_cost_charged_round_trip`
- `test_budget_alert_round_trip`

### `ParseEventTests`

- `test_parse_valid_typed_event` — known event_type routes to correct subclass
- `test_parse_unknown_event_type` — routes to `UnknownEvent`, preserves `raw_event_type` + `raw_fields`
- `test_parse_unknown_event_round_trip` — `UnknownEvent` re-serializes byte-equal to the original line
- `test_parse_missing_event_type_field_raises` — `ValueError` on structural error
- `test_parse_invalid_json_raises` — `json.JSONDecodeError` surfaces
- `test_parse_missing_required_field_raises` — `TypeError` from dataclass when a typed event is missing a field
- `test_parse_extra_field_raises` — `TypeError` from dataclass on extra fields (strict)
- `test_parse_preserves_unicode_in_story_key` — non-ASCII passes through correctly

### `FieldTypeTests`

- `test_int_field_rejects_float` — `tokens_in=1.5` should fail at construction
- `test_float_field_accepts_int` — `cost_usd=0` (int) is accepted, becomes `0.0` in instance (Python's int↔float coercion is acceptable)
- `test_string_field_rejects_int` — `epic=42` should fail at construction
- `test_boolean_field_strict` — `blocking="yes"` should fail; only `bool` is accepted
- `test_timestamp_format_documented_not_validated` — M01 trusts the caller for timestamp format; M02 may add validation

**Coverage target:** ≥85% line coverage on `telemetry_events.py` (per port-guide NFR). Easy to achieve because the module is mostly dataclass declarations plus 2 helper functions.

**Total test count:** ~30 tests. Runs in well under 1 second. No network, no subprocess, no tmux. Windows-compatible.

## Open decisions deferred to M02 and beyond

- The `TelemetryEmitter` (`threading.Lock` around write, atomic-append semantics, batch flush) — M02
- The `TelemetryReader` (typed aggregations like `cost_by_story`, `attempts_by_story`) — M02
- Wiring every existing log site in `commands/orchestrator.py`, `commands/orchestrator_epic_agents.py`, `core/tmux_runtime.py` to emit typed events — M02
- The `cost_usd` capture path in `commands/orchestrator_parse.py` — M03
- HMAC-chaining of the event stream — M04 (separate substrate, not on telemetry events)
- Typed enums for `severity`, `error_class`, `reason`, `phase` — M07 (failure_triage taxonomy)
- Validation of `timestamp` format at parse time — M02 or later

## Acceptance criteria

The M01 implementation is complete when:

- The module `core/telemetry_events.py` exists and imports cleanly under Python 3.11, 3.12, 3.13, and 3.14
- All 13 concrete event classes are present, each with `EVENT_TYPE` classvar and the documented fields
- `Event._REGISTRY` contains exactly 13 entries after module import
- `UnknownEvent` is defined but is NOT in `_REGISTRY`
- `parse_event` round-trips every concrete event byte-equal
- `parse_event` round-trips `UnknownEvent` byte-equal for arbitrary unknown event_types
- `parse_event` raises the documented exceptions for the documented inputs
- `tests/test_telemetry_events.py` passes (`python -m pytest tests/test_telemetry_events.py -q` returns 0)
- `ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` passes
- `ruff format --check` passes
- Line coverage on the new module ≥ 85% measured by `pytest --cov`
- No new third-party imports (`filelock`/`psutil`/stdlib only)
