# Story Automator (BMAD) — Claude Code Project Guide

## Project Overview

**Name:** bmad-story-automator (Python port)  
**Tech Stack:** Python 3.11+ | pytest | ruff | hatchling | dataclasses  
**Primary Language:** Python  
**Scope:** Python helper runtime for BMAD story orchestration skill/plugin bundle

This repo is the Python port of the Go `bma-d/bmad-story-automator-go`. It packages the runtime helper and two skills under `skills/` following Claude Code skill conventions.

## Module Map

```
skills/bmad-story-automator/
├── src/story_automator/
│   ├── __init__.py                         # Version export
│   ├── cli.py                              # CLI entry point
│   ├── commands/                           # Orchestrator commands
│   │   ├── orchestrator.py
│   │   ├── orchestrator_epic_agents.py
│   │   └── ...
│   ├── core/                               # Core runtime modules
│   │   ├── common.py                       # Utilities: iso_now, compact_json, etc.
│   │   ├── agent_config.py                 # Agent configuration models
│   │   ├── epic_parser.py                  # Epic parsing logic
│   │   ├── tmux_runtime.py                 # tmux session management
│   │   ├── sprint.py                       # Sprint state model
│   │   ├── runtime_layout.py                # File layout conventions
│   │   ├── runtime_policy.py                # Runtime validation rules
│   │   ├── review_verify.py                 # Review gating logic
│   │   ├── stop_hooks.py                    # Stop marker handling
│   │   ├── story_keys.py                    # Story key parsing
│   │   ├── success_verifiers.py             # Verification logic
│   │   └── [NEW] telemetry_events.py       # M01: Event types (WEDGE ATOM)
│   ├── tests/                              # Test suite
│   └── SKILL.md
├── pyproject.toml                          # Project manifest
└── README.md
```

## Dependencies

**Direct:**
- Python 3.11+ (stdlib only plus filelock, psutil per pyproject.toml)
- hatchling (build)
- pytest (test)
- ruff (lint/format)

**Allowlist (pyproject.toml):**
- filelock
- psutil

Anything else is out of scope unless explicitly added to `[project.optional-dependencies]`.

## Conventions

### Code Style
- PEP 604 union type hints (e.g., `str | None`)
- `from __future__ import annotations` at module top
- No mutable default arguments
- Dataclasses for data-carrying types
- Black-compatible formatting via ruff

### Module Size
- Max 500 lines per source file (excluding tests/docstrings)
- See `CONTRIBUTING.md`

### Testing
- pytest with unittest.TestCase
- Location: `tests/test_<module>.py`
- Run: `python -m pytest tests/test_telemetry_events.py -q`
- Coverage gate: ≥85% per `pytest --cov`

### Quality Gates
All modules must pass:
- `ruff check` (lint)
- `ruff format --check` (format)
- `pytest` (tests)
- Coverage ≥85%
- No new imports outside stdlib + filelock/psutil

### Round-Trip Protocol
- JSON serialization must be deterministic
- `obj.to_json_line()` → parse → `obj2.to_json_line()` must match byte-for-byte
- Idempotent under re-import (especially for class registry patterns)

## Telemetry M01 (Wedge Atom)

**New Module:** `core/telemetry_events.py`  
**Scope:** Event dataclass hierarchy with discriminator-based registry and JSON round-trip serialization

**Requirements:**
1. Abstract `Event` base class with `EVENT_TYPE: ClassVar[str]` and auto-registering subclasses
2. 13 concrete event classes: StoryStarted, StoryCompleted, StoryFailed, StoryDeferred, RetryAttempt, EscalationTriggered, ReviewCycle, RetroFired, TmuxSessionSpawned, TmuxSessionCompleted, TmuxSessionCrashed, CostCharged, BudgetAlert
3. `UnknownEvent` for forward-compatible unrecognized types
4. `parse_event(line: str) -> Event` with error handling
5. Round-trip invariant: `Event → to_json_line() → parse_event() → to_json_line()` = byte-identical

**Out of Scope (M02+):**
- TelemetryEmitter with threading.Lock
- TelemetryReader aggregations
- Wiring into existing log sites
- HMAC chaining
- Typed severity/error_class/reason enums
- Runtime validation of timestamp format

**Key Helpers:**
- `iso_now()` from `core.common` for timestamps
- `compact_json()` from `core.common` for JSON serialization

## Hard Guardrails

1. **Imports Only:** stdlib + filelock + psutil — no exceptions
2. **Module Size:** ≤500 lines (excluding tests)
3. **Python 3.11+:** No newer-syntax assumptions
4. **Round-Trip Determinism:** Byte-identical after parse cycle
5. **Registry Idempotence:** Duplicate registration detection + re-import safety
6. **Test Coverage:** ≥85% line coverage required
7. **Linting:** Zero ruff violations (lint + format)

## Hard Non-Guardrails

- No comments required; code should be self-documenting
- Avoid over-abstraction; premature generalization is tech debt
- Data-carrying types use dataclasses, not generic dicts
- Validation only at system boundaries (input from CLI/JSON); trust internal code

---

**Last Updated:** 2026-06-14  
**Author:** BMAD / Claude Code
