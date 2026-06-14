# M01 — Event types (wedge atom)

## Context

M01 is the wedge atom for the typed-telemetry substrate of the bmad-automator port. It introduces the abstract `Event` base class, a discriminator-based registry, 13 concrete typed event dataclasses spanning bmad-automator's story lifecycle, an `UnknownEvent` forward-compatibility fallback, and a `parse_event` function with a documented round-trip protocol. M01 explicitly defers the `TelemetryEmitter`, the `TelemetryReader`, and the wiring of existing log sites — those land in M02. The companion design doc (`2026-06-14-m01-event-types-design.md`) records the operator's brainstorming decisions and is the canonical reference for the rationale behind every choice listed below.

## Out of scope

The `TelemetryEmitter` with `threading.Lock` serialization, the `TelemetryReader` aggregations, the wiring of existing log sites in `commands/orchestrator.py` / `commands/orchestrator_epic_agents.py` / `core/tmux_runtime.py`, the `cost_usd` capture path in `commands/orchestrator_parse.py`, HMAC chaining of the event stream, typed enums for `severity`/`error_class`/`reason`/`phase`, and validation of the timestamp format at parse time are all out of scope for M01. M01 lands the data definitions and the parsing protocol only — no emitter, no readers, no wiring.

## Functional requirements

1. REQ-01 a new module must exist at `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` and must be importable under Python 3.11, 3.12, 3.13, and 3.14 without errors.
2. REQ-02 the module must define an abstract `Event` base `@dataclass` with a `EVENT_TYPE: ClassVar[str]` discriminator field, a `_REGISTRY: ClassVar[dict[str, type[Event]]]` registry field, instance fields `timestamp: str` and `run_id: str`, an `__init_subclass__` method that must auto-register concrete subclasses by `EVENT_TYPE`, a `to_dict` method that must inject `event_type` from the classvar, and a `to_json_line` method that must return a compact single-line JSON string with no trailing newline.
3. REQ-03 when two concrete subclasses declare the same `EVENT_TYPE` string the module import must raise `RuntimeError` with both class qualnames embedded in the message.
4. REQ-04 the module must define an `UnknownEvent` `@dataclass` subclass that must NOT be auto-registered into `_REGISTRY`, must carry `raw_event_type: str` and `raw_fields: dict[str, Any]`, and must override `to_dict` to re-emit the original `event_type` and unrecognized fields byte-equal to the original input line.
5. REQ-05 the module must define exactly 13 concrete event classes named `StoryStarted`, `StoryCompleted`, `StoryFailed`, `StoryDeferred`, `RetryAttempt`, `EscalationTriggered`, `ReviewCycle`, `RetroFired`, `TmuxSessionSpawned`, `TmuxSessionCompleted`, `TmuxSessionCrashed`, `CostCharged`, and `BudgetAlert`, each declaring an `EVENT_TYPE` classvar matching the snake_case form of its class name and the additional fields documented in the companion design doc.
6. REQ-06 after module import `Event._REGISTRY` must contain exactly 13 entries keyed by the concrete classes' `EVENT_TYPE` strings, and `UnknownEvent` must NOT be present in `_REGISTRY`.
7. REQ-07 the module must export a `parse_event(line: str) -> Event` function such that when the parsed JSON contains a known `event_type` the function must return an instance of the matching concrete class; when the parsed JSON contains an unrecognized `event_type` the function must return an `UnknownEvent` preserving the original `event_type` value and all unrecognized fields; when the parsed JSON is missing the `event_type` field the function must raise `ValueError`; when the input string is not valid JSON the function must propagate `json.JSONDecodeError`; when a typed event is missing a required field the function must raise `TypeError` from dataclass construction; when a typed event has unexpected extra fields the function must raise `TypeError`.
8. REQ-08 for every concrete event class the round-trip invariant must hold such that when an instance is constructed with the required fields, `to_json_line` is called, and `parse_event` is invoked on the resulting string, the returned instance must compare equal to the original via dataclass `__eq__` and its own `to_json_line` output must be byte-equal to the original line.
9. REQ-09 for `UnknownEvent` the round-trip invariant must hold for arbitrary unrecognized `event_type` strings and arbitrary JSON-primitive `raw_fields` such that `parse_event` followed by `to_json_line` must return the original line byte-for-byte.
10. REQ-10 a new test file at `tests/test_telemetry_events.py` must contain approximately 30 tests across the four `TestCase` classes documented in the companion design doc and must pass when invoked as `python -m pytest tests/test_telemetry_events.py -q`.
11. REQ-11 the new module must use only the Python standard library plus `filelock` and `psutil` (the dependency allowlist documented in `pyproject.toml`); when grepped for new imports the file must yield zero matches outside that allowlist.
12. REQ-12 the module must import `iso_now` and `compact_json` from `story_automator.core.common` for timestamp formatting and compact-JSON serialization and must NOT duplicate either helper.

## Non-functional requirements

- The module file size is no more than 500 source lines of code excluding tests and docstrings, per the project's `CONTRIBUTING.md` guideline.
- All public functions, methods, and dataclass field types carry PEP 604 union-typed annotations; the module begins with `from __future__ import annotations`.
- The module and its test file pass `ruff check` and `ruff format --check` under the project's existing ruff configuration with no additional rule disables.
- Line coverage of `core/telemetry_events.py` measured by `pytest --cov` meets or exceeds 85 percent.
- The test suite runs on Windows, WSL, and Linux without modification; no subprocess invocations, no tmux dependency, no network requirement. Total wall-clock under one second.
- The round-trip serialization is deterministic: identical input fields produce byte-identical JSON output across Python 3.11, 3.12, 3.13, and 3.14 runtimes.
- No mutable default arguments and no shared mutable class attributes on concrete event classes; the registry on `Event._REGISTRY` is the single shared mutable state and is populated only at class-creation time.
- The `__init_subclass__` registration is idempotent under module re-import (the identity check `existing is not cls` avoids spurious duplicate errors during test setup).

## Quality gates

- The lint gate passes under `python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` with zero violations.
- The format gate passes under `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` with zero files needing reformat.
- The test gate passes under `python -m pytest tests/test_telemetry_events.py -q` with zero failing tests.
- The coverage gate passes under `python -m pytest --cov=story_automator.core.telemetry_events --cov-fail-under=85 tests/test_telemetry_events.py`.
- The import-allowlist gate passes: a grep for new imports beyond stdlib + `filelock` + `psutil` in the new module returns zero matches.
- The module size gate passes: `wc -l` on the new module returns 500 or fewer lines, excluding tests.
- All quality gates run on Windows git-bash, WSL Ubuntu, and Linux CI without modification.
