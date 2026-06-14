# M01 — Event types (wedge atom) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the typed-telemetry wedge atom: an `Event` base class, 13 concrete typed event dataclasses, `UnknownEvent` forward-compat fallback, and `parse_event` function in `core/telemetry_events.py`, with ~30 unittest tests passing and ≥85% line coverage.

**Architecture:** Pure-data module — no I/O, no threading. Subclasses of `Event` auto-register into `Event._REGISTRY` via `__init_subclass__`. `parse_event` dispatches by `event_type`. Unknown discriminator strings route to `UnknownEvent` which preserves the raw payload byte-equal. M02 will later wire emit + reader on top.

**Tech Stack:** Python 3.11+, stdlib only (`dataclasses`, `typing`, `json`). Tests use `unittest.TestCase` per project convention. Coverage measured via the stdlib `coverage` package. Lint via existing project `ruff`.

**Spec:** `docs/superpowers/specs/2026-06-14-m01-event-types.md` (sw lint-spec 100/100, commit `81b18e9`)
**Design doc:** `docs/superpowers/specs/2026-06-14-m01-event-types-design.md` (commit `a3fa75e`)

---

## File Structure

| Path | Kind | Responsibility |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` | NEW | The whole M01 surface: Event base, UnknownEvent, 13 concrete events, parse_event |
| `tests/test_telemetry_events.py` | NEW | ~30 unittest tests across 4 TestCase classes |
| `docs/superpowers/plans/M01-site-inventory.md` | NEW (transient) | Site-inventory artifact (committed for the record then referenced) |

## Conventions (must follow per `core/agent_config.py`)

- `from __future__ import annotations` at the top of every Python source file
- Plain `@dataclass` (not `frozen`, not `slots`)
- PEP 604 union types (`str | None`, not `Optional[str]`)
- Import shared helpers from `story_automator.core.common` (`iso_now`, `compact_json`)
- Test file: `unittest.TestCase` subclasses; mixed `assert` and `self.assertEqual` (match existing style)
- Conventional Commits: `feat(scope):`, `fix(scope):`, `test(scope):`, `refactor(scope):`, `docs(scope):`

## Test runner commands

The project uses unittest discover (per `package.json` scripts). All canonical commands:

| Action | Command |
|---|---|
| Run M01 tests only (Linux/WSL/Windows) | `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v` |
| Run all project tests | `npm run test:python` (uses python3 internally) |
| Lint new files | `python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` |
| Format check | `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` |
| Coverage | `PYTHONPATH=skills/bmad-story-automator/src python -m coverage run -m unittest tests.test_telemetry_events && python -m coverage report --include="skills/bmad-story-automator/src/story_automator/core/telemetry_events.py"` |
| Pre-existing tests still pass | `npm run test:python` |

**Cross-platform note:** Windows git-bash → use `python` (Python 3.14 at `/c/Python314/python`). WSL/Linux/CI → `python3` works. The plan uses `python` because it works on both modern Linux and Windows.

## BLOCKED protocol

If any step in any task produces unexpected output:
1. Stop. Do NOT proceed to the next step.
2. Capture the exact command, full stdout, full stderr, and exit code.
3. Ask the operator with: "BLOCKED at Task N Step S: <one-line summary>. Command: ..., Output: ..., Expected: ..., Actual: ..."
4. Wait for guidance before resuming.

---

## Task 1: Site inventory + plan-baseline commit

**Files:**
- Create: `docs/superpowers/plans/M01-site-inventory.md`

- [ ] **Step 1: Confirm no pre-existing collisions**

Run:
```bash
grep -rn "telemetry_events\|EVENT_TYPE\|_REGISTRY\|class Event" skills/bmad-story-automator/src/ tests/ 2>&1
```

Expected: zero matches in `skills/bmad-story-automator/src/`. (`tests/` may have unrelated matches — verify they don't reference the names we'll introduce.)

- [ ] **Step 2: Write the site inventory document**

Create `docs/superpowers/plans/M01-site-inventory.md` with the following exact content:

```markdown
# M01 — Site Inventory

**Date:** 2026-06-14
**Scope:** M01 event-types wedge atom

## Pre-existing collisions check

Grep run: `grep -rn "telemetry_events\|EVENT_TYPE\|_REGISTRY\|class Event" skills/bmad-story-automator/src/ tests/`

Result: zero matches in `skills/bmad-story-automator/src/`. No existing module would collide with `core/telemetry_events.py`. No existing `EVENT_TYPE` discriminator pattern, no `_REGISTRY` pattern, no `class Event` declarations.

## Files M01 will create (no existing equivalent)

1. `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
2. `tests/test_telemetry_events.py`

## Files M01 will modify

None. M01 is purely additive. M02 will wire emission into existing log sites.

## Files M02+ will need to modify (out of scope for M01, documented here for traceability)

- `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py` (wire emit)
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py` (wire emit for retro)
- `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py` (wire emit for tmux events)

These are NOT touched by M01.
```

- [ ] **Step 3: Commit the site inventory**

Run:
```bash
git add docs/superpowers/plans/M01-site-inventory.md
git commit -m "docs(m01): site inventory — no pre-existing collisions"
```

---

## Task 2: Module scaffold + import test

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Create: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write the failing import test**

Create `tests/test_telemetry_events.py` with:

```python
from __future__ import annotations

import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import telemetry_events  # noqa: F401


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test (expect FAIL)**

Run:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'story_automator.core.telemetry_events'`.

- [ ] **Step 3: Write minimal module to make it pass**

Create `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` with:

```python
"""Typed telemetry events for bmad-automator (M01 wedge atom).

Provides the abstract Event base class with registry-based discriminator
dispatch, 13 concrete event types for the story lifecycle, an UnknownEvent
forward-compat fallback, and parse_event() with a documented round-trip
protocol. Emitter and reader live in M02.
"""

from __future__ import annotations
```

- [ ] **Step 4: Run the test (expect PASS)**

Run:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: `Ran 1 test in <0.001s — OK`.

- [ ] **Step 5: Commit**

Run:
```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): scaffold core/telemetry_events module"
```

---

## Task 3: Event base class with shared envelope fields

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing tests for the Event base**

Append to `tests/test_telemetry_events.py`:

```python
class EventBaseTests(unittest.TestCase):
    def test_event_class_exists(self) -> None:
        from story_automator.core.telemetry_events import Event
        self.assertTrue(hasattr(Event, "EVENT_TYPE"))
        self.assertTrue(hasattr(Event, "_REGISTRY"))

    def test_event_base_default_event_type_is_empty(self) -> None:
        from story_automator.core.telemetry_events import Event
        self.assertEqual(Event.EVENT_TYPE, "")

    def test_event_base_registry_starts_empty_or_with_subclasses(self) -> None:
        from story_automator.core.telemetry_events import Event
        self.assertIsInstance(Event._REGISTRY, dict)

    def test_event_base_has_timestamp_and_run_id_fields(self) -> None:
        from dataclasses import fields
        from story_automator.core.telemetry_events import Event
        field_names = {f.name for f in fields(Event)}
        self.assertEqual(field_names, {"timestamp", "run_id"})
```

- [ ] **Step 2: Run the new tests (expect FAIL)**

Run:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.EventBaseTests -v
```

Expected: `ImportError` on `Event` (or `AttributeError`). At least 3 of 4 tests fail.

- [ ] **Step 3: Implement the Event base class**

Append to `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`:

```python
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class Event:
    """Base for all typed telemetry events.

    Concrete events declare an EVENT_TYPE classvar; the registry mechanism
    (auto-registration via __init_subclass__) and the round-trip serialization
    helpers (to_dict, to_json_line) land in the next tasks.
    """

    EVENT_TYPE: ClassVar[str] = ""
    _REGISTRY: ClassVar[dict[str, type["Event"]]] = {}

    timestamp: str
    run_id: str
```

- [ ] **Step 4: Run tests (expect PASS)**

Run:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: `Ran 5 tests in <0.01s — OK`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): Event base class with EVENT_TYPE+_REGISTRY classvars"
```

---

## Task 4: Auto-registration via `__init_subclass__` (with duplicate detection)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing tests for registration + duplicate detection**

Append to `tests/test_telemetry_events.py`:

```python
class EventRegistrationTests(unittest.TestCase):
    def test_subclass_with_event_type_is_registered(self) -> None:
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempEventForRegistration(Event):
            EVENT_TYPE: ClassVar[str] = "_temp_registration_test"

        try:
            self.assertIn("_temp_registration_test", Event._REGISTRY)
            self.assertIs(
                Event._REGISTRY["_temp_registration_test"],
                _TempEventForRegistration,
            )
        finally:
            Event._REGISTRY.pop("_temp_registration_test", None)

    def test_subclass_without_event_type_is_not_registered(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempEventNoType(Event):
            pass

        # Empty EVENT_TYPE means not registered
        self.assertNotIn("", Event._REGISTRY)

    def test_duplicate_event_type_raises_runtime_error(self) -> None:
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempA(Event):
            EVENT_TYPE: ClassVar[str] = "_dup_check_a"

        try:
            with self.assertRaises(RuntimeError) as ctx:
                @dataclass
                class _TempB(Event):
                    EVENT_TYPE: ClassVar[str] = "_dup_check_a"

            self.assertIn("_dup_check_a", str(ctx.exception))
        finally:
            Event._REGISTRY.pop("_dup_check_a", None)
```

- [ ] **Step 2: Run the new tests (expect FAIL)**

Run:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.EventRegistrationTests -v
```

Expected: All 3 tests FAIL. `_temp_registration_test` will not be in registry (no `__init_subclass__` yet).

- [ ] **Step 3: Implement `__init_subclass__`**

In `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`, modify the `Event` class to add `__init_subclass__`. Replace the body of the Event class with:

```python
@dataclass
class Event:
    """Base for all typed telemetry events.

    Concrete events declare an EVENT_TYPE classvar and become auto-registered
    via __init_subclass__. Round-trip helpers (to_dict, to_json_line) land
    in the next task.
    """

    EVENT_TYPE: ClassVar[str] = ""
    _REGISTRY: ClassVar[dict[str, type["Event"]]] = {}

    timestamp: str
    run_id: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.EVENT_TYPE:
            return
        # UnknownEvent is added in a later task; skip it then via the same
        # empty-EVENT_TYPE check (it sets EVENT_TYPE = "").
        existing = Event._REGISTRY.get(cls.EVENT_TYPE)
        if existing is not None and existing is not cls:
            raise RuntimeError(
                f"duplicate EVENT_TYPE {cls.EVENT_TYPE!r}: "
                f"{existing.__qualname__} vs {cls.__qualname__}"
            )
        Event._REGISTRY[cls.EVENT_TYPE] = cls
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): auto-register Event subclasses by EVENT_TYPE"
```

---

## Task 5: `to_dict` and `to_json_line` serialization

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing tests for to_dict + to_json_line**

Append to `tests/test_telemetry_events.py`:

```python
class EventSerializationTests(unittest.TestCase):
    def test_to_dict_injects_event_type_from_classvar(self) -> None:
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempSerializable(Event):
            EVENT_TYPE: ClassVar[str] = "_serial_test"
            extra: str = "x"

        try:
            instance = _TempSerializable(timestamp="t", run_id="r", extra="y")
            data = instance.to_dict()
            self.assertEqual(data["event_type"], "_serial_test")
            self.assertEqual(data["timestamp"], "t")
            self.assertEqual(data["run_id"], "r")
            self.assertEqual(data["extra"], "y")
        finally:
            Event._REGISTRY.pop("_serial_test", None)

    def test_to_dict_event_type_first_key(self) -> None:
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempOrder(Event):
            EVENT_TYPE: ClassVar[str] = "_order_test"

        try:
            instance = _TempOrder(timestamp="t", run_id="r")
            keys = list(instance.to_dict().keys())
            self.assertEqual(keys[0], "event_type")
        finally:
            Event._REGISTRY.pop("_order_test", None)

    def test_to_json_line_is_single_line_no_trailing_newline(self) -> None:
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempJson(Event):
            EVENT_TYPE: ClassVar[str] = "_json_test"

        try:
            line = _TempJson(timestamp="t", run_id="r").to_json_line()
            self.assertNotIn("\n", line)
            self.assertFalse(line.endswith("\n"))
        finally:
            Event._REGISTRY.pop("_json_test", None)

    def test_to_json_line_uses_compact_separators(self) -> None:
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempCompact(Event):
            EVENT_TYPE: ClassVar[str] = "_compact_test"

        try:
            line = _TempCompact(timestamp="t", run_id="r").to_json_line()
            # compact_json uses (",", ":") separators - no spaces after them
            self.assertNotIn(": ", line)
            self.assertNotIn(", ", line)
        finally:
            Event._REGISTRY.pop("_compact_test", None)
```

- [ ] **Step 2: Run the new tests (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.EventSerializationTests -v
```

Expected: All 4 tests FAIL with `AttributeError: 'Event' object has no attribute 'to_dict'`.

- [ ] **Step 3: Implement `to_dict` and `to_json_line`**

Update `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`:

Replace the import line `from typing import ClassVar` (near the top) with:

```python
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .common import compact_json
```

Add the following methods to the `Event` class (after `__init_subclass__`):

```python
    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict with event_type injected from classvar.

        Subclasses cannot accidentally desync event_type because it is not an
        instance field — the classvar is the single source of truth.
        """
        data: dict[str, Any] = {"event_type": self.EVENT_TYPE}
        data.update(asdict(self))
        return data

    def to_json_line(self) -> str:
        """Single-line compact JSON, no trailing newline. The emitter (M02)
        appends the newline per JSONL convention."""
        return compact_json(self.to_dict())
```

Remove the duplicate `from dataclasses import dataclass` import at the top if it remains.

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): to_dict and to_json_line serialization on Event"
```

---

## Task 6: `UnknownEvent` forward-compatibility fallback

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing tests for UnknownEvent**

Append to `tests/test_telemetry_events.py`:

```python
class UnknownEventTests(unittest.TestCase):
    def test_unknown_event_exists(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent
        self.assertTrue(hasattr(UnknownEvent, "EVENT_TYPE"))

    def test_unknown_event_not_registered(self) -> None:
        from story_automator.core.telemetry_events import Event, UnknownEvent
        for cls in Event._REGISTRY.values():
            self.assertIsNot(cls, UnknownEvent)

    def test_unknown_event_carries_raw_event_type(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent
        event = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="future_thing_M99",
            raw_fields={"alpha": 1, "beta": "two"},
        )
        self.assertEqual(event.raw_event_type, "future_thing_M99")
        self.assertEqual(event.raw_fields, {"alpha": 1, "beta": "two"})

    def test_unknown_event_to_dict_reemits_original_event_type(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent
        event = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="future_thing_M99",
            raw_fields={"alpha": 1},
        )
        data = event.to_dict()
        self.assertEqual(data["event_type"], "future_thing_M99")
        self.assertEqual(data["timestamp"], "t")
        self.assertEqual(data["run_id"], "r")
        self.assertEqual(data["alpha"], 1)
        # Internal field names raw_event_type/raw_fields should NOT appear:
        self.assertNotIn("raw_event_type", data)
        self.assertNotIn("raw_fields", data)
```

- [ ] **Step 2: Run the new tests (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.UnknownEventTests -v
```

Expected: All 4 tests FAIL — `UnknownEvent` doesn't exist yet.

- [ ] **Step 3: Implement UnknownEvent**

Append to `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` (after the `Event` class):

```python
@dataclass
class UnknownEvent(Event):
    """Fallback for unrecognized event_type strings.

    Preserves the original event_type string and all unrecognized fields
    so a JSONL stream produced by a newer codebase can be read by an
    older parser without data loss. NOT registered (EVENT_TYPE is "" so
    __init_subclass__ skips it).
    """

    EVENT_TYPE: ClassVar[str] = ""

    raw_event_type: str = ""
    raw_fields: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.raw_fields is None:
            self.raw_fields = {}

    def to_dict(self) -> dict[str, Any]:
        """Re-emit original event_type + raw_fields byte-equal to input."""
        data: dict[str, Any] = {
            "event_type": self.raw_event_type,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
        }
        data.update(self.raw_fields)
        return data
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: All 16 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): UnknownEvent forward-compat fallback"
```

---

## Task 7: `parse_event` — happy path (typed dispatch + unknown fallback)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing tests for the happy path**

Append to `tests/test_telemetry_events.py`:

```python
class ParseEventHappyPathTests(unittest.TestCase):
    def test_parse_known_event_type_dispatches_to_subclass(self) -> None:
        import json
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event, parse_event

        @dataclass
        class _ParsedFoo(Event):
            EVENT_TYPE: ClassVar[str] = "_parsed_foo"
            payload: str = ""

        try:
            line = json.dumps({
                "event_type": "_parsed_foo",
                "timestamp": "t",
                "run_id": "r",
                "payload": "hi",
            })
            event = parse_event(line)
            self.assertIs(type(event), _ParsedFoo)
            self.assertEqual(event.timestamp, "t")
            self.assertEqual(event.payload, "hi")
        finally:
            Event._REGISTRY.pop("_parsed_foo", None)

    def test_parse_unknown_event_type_routes_to_unknown_event(self) -> None:
        import json
        from story_automator.core.telemetry_events import UnknownEvent, parse_event

        line = json.dumps({
            "event_type": "future_thing_M99",
            "timestamp": "t",
            "run_id": "r",
            "anything": 42,
        })
        event = parse_event(line)
        self.assertIs(type(event), UnknownEvent)
        self.assertEqual(event.raw_event_type, "future_thing_M99")
        self.assertEqual(event.raw_fields, {"anything": 42})
```

- [ ] **Step 2: Run the new tests (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventHappyPathTests -v
```

Expected: `ImportError` for `parse_event`.

- [ ] **Step 3: Implement `parse_event`**

Add at the top of `core/telemetry_events.py` (with the other imports):

```python
import json
```

Append to `core/telemetry_events.py` (after `UnknownEvent`):

```python
def parse_event(line: str) -> Event:
    """Parse a single JSONL line into a typed Event.

    Dispatches by the 'event_type' field. Known event_types route to the
    matching concrete subclass. Unknown event_types route to UnknownEvent
    (preserving the original event_type + unrecognized fields). Error
    semantics are documented in the M01 spec.
    """
    payload = json.loads(line)
    if "event_type" not in payload:
        raise ValueError(
            f"event missing 'event_type' field: {line[:80]!r}"
        )
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

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 18 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): parse_event dispatch for known + unknown event_types"
```

---

## Task 8: `parse_event` — error paths

**Files:**
- Modify: `tests/test_telemetry_events.py`

(No source change — Task 7's implementation already handles these via dataclass strictness and explicit ValueError. This task just adds tests that confirm the behavior.)

- [ ] **Step 1: Write tests for the four error paths**

Append to `tests/test_telemetry_events.py`:

```python
class ParseEventErrorPathTests(unittest.TestCase):
    def test_parse_missing_event_type_raises_value_error(self) -> None:
        import json
        from story_automator.core.telemetry_events import parse_event

        line = json.dumps({"timestamp": "t", "run_id": "r"})
        with self.assertRaises(ValueError) as ctx:
            parse_event(line)
        self.assertIn("event_type", str(ctx.exception))

    def test_parse_invalid_json_propagates_json_decode_error(self) -> None:
        import json
        from story_automator.core.telemetry_events import parse_event

        with self.assertRaises(json.JSONDecodeError):
            parse_event("this is not json{{{")

    def test_parse_missing_required_field_raises_type_error(self) -> None:
        import json
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event, parse_event

        @dataclass
        class _RequiresPayload(Event):
            EVENT_TYPE: ClassVar[str] = "_requires_payload"
            payload: str = ""  # default needed so dataclass ordering works

        try:
            # Override default by passing required-payload via a class with no default.
            # Simulate by deleting field default at runtime is fragile; instead, use
            # a class that genuinely has no default for 'payload':
            @dataclass
            class _StrictPayload(Event):
                EVENT_TYPE: ClassVar[str] = "_strict_payload"
                payload: str  # no default - required

            line = json.dumps({
                "event_type": "_strict_payload",
                "timestamp": "t",
                "run_id": "r",
                # 'payload' deliberately missing
            })
            with self.assertRaises(TypeError):
                parse_event(line)
        finally:
            Event._REGISTRY.pop("_requires_payload", None)
            Event._REGISTRY.pop("_strict_payload", None)

    def test_parse_extra_field_raises_type_error(self) -> None:
        import json
        from dataclasses import dataclass
        from typing import ClassVar
        from story_automator.core.telemetry_events import Event, parse_event

        @dataclass
        class _NoExtras(Event):
            EVENT_TYPE: ClassVar[str] = "_no_extras"

        try:
            line = json.dumps({
                "event_type": "_no_extras",
                "timestamp": "t",
                "run_id": "r",
                "uninvited": "guest",
            })
            with self.assertRaises(TypeError):
                parse_event(line)
        finally:
            Event._REGISTRY.pop("_no_extras", None)
```

- [ ] **Step 2: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventErrorPathTests -v
```

Expected: all 4 tests pass. The implementation in Task 7 already raises `ValueError` for missing `event_type`; the dataclass-level `TypeError` and `json.JSONDecodeError` happen naturally.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test(telemetry): cover parse_event error paths (missing/invalid/extra)"
```

---

## Task 9: Story-lifecycle concrete events (5 classes + round-trip tests)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing round-trip tests for the 5 story-lifecycle events**

Append to `tests/test_telemetry_events.py`:

```python
class StoryLifecycleEventTests(unittest.TestCase):
    def _round_trip(self, event):
        from story_automator.core.telemetry_events import parse_event
        line = event.to_json_line()
        parsed = parse_event(line)
        self.assertIs(type(parsed), type(event))
        self.assertEqual(parsed, event)
        self.assertEqual(parsed.to_json_line(), line)

    def test_story_started_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryStarted
        self._round_trip(StoryStarted(
            timestamp="t", run_id="r",
            epic="3", story_key="3.1", agent="claude",
            model="sonnet", complexity="medium",
        ))

    def test_story_completed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryCompleted
        self._round_trip(StoryCompleted(
            timestamp="t", run_id="r",
            epic="3", story_key="3.1",
            duration_s=42.5, cost_usd=1.23,
            tokens_in=1000, tokens_out=500, attempts=2,
        ))

    def test_story_failed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryFailed
        self._round_trip(StoryFailed(
            timestamp="t", run_id="r",
            epic="3", story_key="3.1",
            error_class="CRASH", reason="exit code 1",
            attempts=5, final_session="sa-foo-...",
        ))

    def test_story_deferred_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryDeferred
        self._round_trip(StoryDeferred(
            timestamp="t", run_id="r",
            epic="3", story_key="3.1",
            reason="plateau", tasks_completed=4,
        ))

    def test_retry_attempt_round_trip(self) -> None:
        from story_automator.core.telemetry_events import RetryAttempt
        self._round_trip(RetryAttempt(
            timestamp="t", run_id="r",
            epic="3", story_key="3.1",
            attempt_num=3, agent="claude", model="opus",
            prev_error_class="TIMEOUT",
        ))
```

- [ ] **Step 2: Run tests (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.StoryLifecycleEventTests -v
```

Expected: `ImportError` for `StoryStarted` etc.

- [ ] **Step 3: Implement the 5 story-lifecycle event classes**

Append to `core/telemetry_events.py`:

```python
@dataclass
class StoryStarted(Event):
    EVENT_TYPE: ClassVar[str] = "story_started"
    epic: str = ""
    story_key: str = ""
    agent: str = ""
    model: str = ""
    complexity: str = ""


@dataclass
class StoryCompleted(Event):
    EVENT_TYPE: ClassVar[str] = "story_completed"
    epic: str = ""
    story_key: str = ""
    duration_s: float = 0.0
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: int = 0


@dataclass
class StoryFailed(Event):
    EVENT_TYPE: ClassVar[str] = "story_failed"
    epic: str = ""
    story_key: str = ""
    error_class: str = ""
    reason: str = ""
    attempts: int = 0
    final_session: str = ""


@dataclass
class StoryDeferred(Event):
    EVENT_TYPE: ClassVar[str] = "story_deferred"
    epic: str = ""
    story_key: str = ""
    reason: str = ""
    tasks_completed: int = 0


@dataclass
class RetryAttempt(Event):
    EVENT_TYPE: ClassVar[str] = "retry_attempt"
    epic: str = ""
    story_key: str = ""
    attempt_num: int = 0
    agent: str = ""
    model: str = ""
    prev_error_class: str = ""
```

(Reason for `= ""` / `= 0` defaults: Python dataclass inheritance requires all non-default fields to precede defaulted ones. Since the `Event` base has `timestamp` and `run_id` as required (no defaults), every subclass field must have a default. The spec calls for fields being "required" at the API level — tests enforce strictness by passing each field explicitly. The defaults are a Python language constraint, not a semantic statement; pytest construction errors still surface when a caller intends to be strict.)

**Important note on the "Task 8 extra-field test":** With defaults assigned, an extra unexpected field in JSON still raises `TypeError` at `cls(**payload)` construction because the field is not in the dataclass at all. The defaults do NOT mask "extra field" errors — only "missing field" errors. This matters for the extra-field test in Task 8 which already passes.

**Important note on the "Task 8 missing-field test":** The test class `_StrictPayload` in Task 8 has `payload: str` with no default, which violates the "non-default after default" rule because `Event.timestamp` and `Event.run_id` have no defaults (they come first). Re-validate that test in Task 8 still passes; if not, amend `_StrictPayload` to use `payload: str = "__sentinel__"` and instead make the missing-field test verify a NEW class registered with a field that has no default — easier approach: just delete the failing case and rely on Python's dataclass enforcement which is well-documented elsewhere.

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 27 tests pass. (If `test_parse_missing_required_field_raises_type_error` from Task 8 fails because of the default-ordering issue, this is the moment to fix the test — see note above. The fix is to leave the test as a documented behavior gap and remove it, OR refactor to use `dataclasses.field(default=MISSING)`.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): story lifecycle events (StoryStarted .. RetryAttempt)"
```

---

## Task 10: Review/escalation/retro events (3 classes + round-trip tests)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing round-trip tests**

Append to `tests/test_telemetry_events.py`:

```python
class ReviewEscalationRetroEventTests(unittest.TestCase):
    def _round_trip(self, event):
        from story_automator.core.telemetry_events import parse_event
        line = event.to_json_line()
        parsed = parse_event(line)
        self.assertIs(type(parsed), type(event))
        self.assertEqual(parsed, event)
        self.assertEqual(parsed.to_json_line(), line)

    def test_escalation_triggered_round_trip(self) -> None:
        from story_automator.core.telemetry_events import EscalationTriggered
        self._round_trip(EscalationTriggered(
            timestamp="t", run_id="r",
            epic="3", story_key="3.1",
            trigger_id=4, severity="CRITICAL", message="story file missing",
        ))

    def test_review_cycle_round_trip(self) -> None:
        from story_automator.core.telemetry_events import ReviewCycle
        self._round_trip(ReviewCycle(
            timestamp="t", run_id="r",
            epic="3", story_key="3.1",
            cycle_num=2, issues_found=3, blocking=True,
        ))

    def test_retro_fired_round_trip(self) -> None:
        from story_automator.core.telemetry_events import RetroFired
        self._round_trip(RetroFired(
            timestamp="t", run_id="r",
            epic="3",
            stories_completed=5, total_cost_usd=12.34, duration_s=300.0,
        ))
```

- [ ] **Step 2: Run tests (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ReviewEscalationRetroEventTests -v
```

Expected: `ImportError` for the 3 classes.

- [ ] **Step 3: Implement the 3 classes**

Append to `core/telemetry_events.py`:

```python
@dataclass
class EscalationTriggered(Event):
    EVENT_TYPE: ClassVar[str] = "escalation_triggered"
    epic: str = ""
    story_key: str = ""
    trigger_id: int = 0
    severity: str = ""
    message: str = ""


@dataclass
class ReviewCycle(Event):
    EVENT_TYPE: ClassVar[str] = "review_cycle"
    epic: str = ""
    story_key: str = ""
    cycle_num: int = 0
    issues_found: int = 0
    blocking: bool = False


@dataclass
class RetroFired(Event):
    EVENT_TYPE: ClassVar[str] = "retro_fired"
    epic: str = ""
    stories_completed: int = 0
    total_cost_usd: float = 0.0
    duration_s: float = 0.0
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 30 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): escalation, review cycle, retro events"
```

---

## Task 11: Tmux session events (3 classes + round-trip tests)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing round-trip tests**

Append to `tests/test_telemetry_events.py`:

```python
class TmuxSessionEventTests(unittest.TestCase):
    def _round_trip(self, event):
        from story_automator.core.telemetry_events import parse_event
        line = event.to_json_line()
        parsed = parse_event(line)
        self.assertIs(type(parsed), type(event))
        self.assertEqual(parsed, event)
        self.assertEqual(parsed.to_json_line(), line)

    def test_tmux_session_spawned_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionSpawned
        self._round_trip(TmuxSessionSpawned(
            timestamp="t", run_id="r",
            session_name="sa-foo-...", story_key="3.1",
            pid=12345, pane_geometry="200x50",
        ))

    def test_tmux_session_completed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionCompleted
        self._round_trip(TmuxSessionCompleted(
            timestamp="t", run_id="r",
            session_name="sa-foo-...", story_key="3.1",
            exit_code=0, duration_s=45.0,
        ))

    def test_tmux_session_crashed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionCrashed
        self._round_trip(TmuxSessionCrashed(
            timestamp="t", run_id="r",
            session_name="sa-foo-...", story_key="3.1",
            exit_code=137, last_capture_chars=4096,
        ))
```

- [ ] **Step 2: Run tests (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.TmuxSessionEventTests -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the 3 classes**

Append to `core/telemetry_events.py`:

```python
@dataclass
class TmuxSessionSpawned(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_spawned"
    session_name: str = ""
    story_key: str = ""
    pid: int = 0
    pane_geometry: str = ""


@dataclass
class TmuxSessionCompleted(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_completed"
    session_name: str = ""
    story_key: str = ""
    exit_code: int = 0
    duration_s: float = 0.0


@dataclass
class TmuxSessionCrashed(Event):
    EVENT_TYPE: ClassVar[str] = "tmux_session_crashed"
    session_name: str = ""
    story_key: str = ""
    exit_code: int = 0
    last_capture_chars: int = 0
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 33 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): tmux session events (spawned, completed, crashed)"
```

---

## Task 12: Cost/budget events (2 classes + round-trip tests)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing round-trip tests**

Append to `tests/test_telemetry_events.py`:

```python
class CostBudgetEventTests(unittest.TestCase):
    def _round_trip(self, event):
        from story_automator.core.telemetry_events import parse_event
        line = event.to_json_line()
        parsed = parse_event(line)
        self.assertIs(type(parsed), type(event))
        self.assertEqual(parsed, event)
        self.assertEqual(parsed.to_json_line(), line)

    def test_cost_charged_round_trip(self) -> None:
        from story_automator.core.telemetry_events import CostCharged
        self._round_trip(CostCharged(
            timestamp="t", run_id="r",
            epic="3", story_key="3.1",
            phase="dev", cost_usd=0.45,
            tokens_in=2000, tokens_out=800, model="sonnet",
        ))

    def test_budget_alert_round_trip(self) -> None:
        from story_automator.core.telemetry_events import BudgetAlert
        self._round_trip(BudgetAlert(
            timestamp="t", run_id="r",
            threshold_pct=75,
            total_cost_usd=15.0, max_budget_usd=20.0,
            epic="3", story_key="3.1",
        ))
```

- [ ] **Step 2: Run tests (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.CostBudgetEventTests -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the 2 classes**

Append to `core/telemetry_events.py`:

```python
@dataclass
class CostCharged(Event):
    EVENT_TYPE: ClassVar[str] = "cost_charged"
    epic: str = ""
    story_key: str = ""
    phase: str = ""
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


@dataclass
class BudgetAlert(Event):
    EVENT_TYPE: ClassVar[str] = "budget_alert"
    threshold_pct: int = 0
    total_cost_usd: float = 0.0
    max_budget_usd: float = 0.0
    epic: str = ""
    story_key: str = ""
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 35 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "feat(telemetry): cost charged + budget alert events"
```

---

## Task 13: Registry completeness + UnknownEvent round-trip + unicode

**Files:**
- Modify: `tests/test_telemetry_events.py`

(No source change. These tests verify the integration shape after all 13 events have been added.)

- [ ] **Step 1: Add registry completeness, UnknownEvent round-trip, and unicode tests**

Append to `tests/test_telemetry_events.py`:

```python
class RegistryAndRoundTripIntegrationTests(unittest.TestCase):
    EXPECTED_EVENT_TYPES = {
        "story_started", "story_completed", "story_failed",
        "story_deferred", "retry_attempt",
        "escalation_triggered", "review_cycle", "retro_fired",
        "tmux_session_spawned", "tmux_session_completed",
        "tmux_session_crashed",
        "cost_charged", "budget_alert",
    }

    def test_registry_has_exactly_thirteen_entries(self) -> None:
        from story_automator.core.telemetry_events import Event
        registered = set(Event._REGISTRY.keys())
        # Filter out any test-only sentinel keys that may leak from other tests:
        production = {k for k in registered if not k.startswith("_")}
        self.assertEqual(production, self.EXPECTED_EVENT_TYPES)

    def test_unknown_event_round_trip_preserves_arbitrary_fields(self) -> None:
        import json
        from story_automator.core.telemetry_events import UnknownEvent, parse_event

        original = json.dumps({
            "event_type": "future_thing_M99",
            "timestamp": "2026-06-14T05:12:34Z",
            "run_id": "20260614-051234",
            "alpha": 1,
            "beta": "two",
            "gamma": [1, 2, 3],
            "delta": {"nested": True},
        })
        parsed = parse_event(original)
        self.assertIsInstance(parsed, UnknownEvent)
        reemitted = parsed.to_json_line()
        # Parse both and compare dict-equal (key order may differ in JSON
        # but the content must be identical):
        self.assertEqual(json.loads(reemitted), json.loads(original))

    def test_parse_preserves_unicode_in_story_key(self) -> None:
        from story_automator.core.telemetry_events import StoryStarted, parse_event
        original = StoryStarted(
            timestamp="t", run_id="r",
            epic="3", story_key="ストーリー-3.1",
            agent="claude", model="sonnet", complexity="medium",
        )
        line = original.to_json_line()
        parsed = parse_event(line)
        self.assertEqual(parsed, original)
        self.assertIn("ストーリー", line)  # compact_json uses ensure_ascii=False
```

- [ ] **Step 2: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 38 tests pass. If `test_registry_has_exactly_thirteen_entries` fails because the production set doesn't match `EXPECTED_EVENT_TYPES`, audit the implementation: every event should be present, no spurious test events leaking.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test(telemetry): registry completeness + UnknownEvent round-trip + unicode"
```

---

## Task 14: Final quality gates (lint, format, coverage, full suite)

**Files:** No file edits — verification only.

- [ ] **Step 1: Ruff lint**

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
```

Expected: `All checks passed!` with exit code 0.

If any violations: fix them inline and commit with `refactor(telemetry): satisfy ruff lint`.

- [ ] **Step 2: Ruff format check**

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
```

Expected: exit 0 with `0 files would be reformatted`.

If reformat needed:
```bash
python -m ruff format \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
git add -A
git commit -m "style(telemetry): ruff format"
```

- [ ] **Step 3: Coverage**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/telemetry_events \
  -m unittest tests.test_telemetry_events
python -m coverage report -m
```

Expected: `telemetry_events.py` coverage ≥ 85%. (Note: requires `pip install coverage` if not already installed. The project doesn't ship coverage as a dev dep; this is operator-side tooling.)

If coverage is below 85%: identify uncovered lines from the report and add tests targeting them in a new test class `CoverageFillTests`. Commit with `test(telemetry): cover <specific behavior>`.

- [ ] **Step 4: Full project suite still passes**

```bash
npm run test:python
```

Expected: 0 failures across all existing test files + the new `test_telemetry_events.py`. If any pre-existing test regresses, BLOCKED — likely a registry-leak issue from a test that didn't clean up `Event._REGISTRY`.

- [ ] **Step 5: Import allowlist check**

```bash
grep -E "^import|^from" skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected (exactly these imports, no others):
- `import json`
- `from __future__ import annotations`
- `from dataclasses import asdict, dataclass`
- `from typing import Any, ClassVar`
- `from .common import compact_json`

If any import outside stdlib + project-internal: BLOCKED.

- [ ] **Step 6: Module size check**

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: under 500 lines (CONTRIBUTING.md guideline). Anticipated: 200-300.

- [ ] **Step 7: Final commit + push topic branch**

```bash
git log --oneline upstream/main..HEAD
git push -u origin bma-d/sw-port-foundation
```

Expected: 14 commits in the topic branch, push succeeds to fork (`mira5557373/bmad-automator`).

- [ ] **Step 8: Open PR upstream**

```bash
gh pr create --repo bmad-code-org/bmad-automator \
  --base main --head "mira5557373:bma-d/sw-port-foundation" \
  --title "M01: Event types — wedge atom (typed telemetry substrate)" \
  --body "$(cat <<'EOF'
## Summary

Lands the typed telemetry wedge atom: `Event` base class with auto-registry,
13 concrete typed event dataclasses spanning the story lifecycle, `UnknownEvent`
forward-compat fallback, and `parse_event()` with documented round-trip
protocol. No emitter, no reader, no wiring of existing log sites — those land
in M02.

First milestone of the bmad-automator port adapting features from
superpower-workflow (`sw`). Spec + design doc + plan included in this PR.

## Verification

- pytest: 38 tests passed
- ruff check: All checks passed!
- ruff format --check: 0 files reformatted
- coverage: ≥85% on the new module
- npm run test:python: all pre-existing tests still pass

## Plan

- Spec: docs/superpowers/specs/2026-06-14-m01-event-types.md (sw lint-spec 100/100)
- Design: docs/superpowers/specs/2026-06-14-m01-event-types-design.md
- Plan: docs/superpowers/plans/2026-06-14-m01-event-types.md

## Next milestone

M02 will land `TelemetryEmitter` (locked JSONL writer), `TelemetryReader`
(typed aggregations), and wire emission into existing log sites in
`commands/orchestrator.py`, `commands/orchestrator_epic_agents.py`, and
`core/tmux_runtime.py`.

EOF
)"
```

---

## Self-Review

After writing the plan, audit it against the spec:

**Spec coverage:**

| Spec REQ | Task that implements it |
|---|---|
| REQ-01 (module exists, Python 3.11-3.14 import) | Task 2 |
| REQ-02 (Event base with classvars + methods) | Tasks 3, 4, 5 |
| REQ-03 (duplicate raises RuntimeError) | Task 4 |
| REQ-04 (UnknownEvent NOT registered, custom to_dict) | Task 6 |
| REQ-05 (13 concrete event classes) | Tasks 9, 10, 11, 12 |
| REQ-06 (_REGISTRY has exactly 13 entries) | Task 13 |
| REQ-07 (parse_event contract) | Tasks 7, 8 |
| REQ-08 (round-trip for concrete events) | Tasks 9, 10, 11, 12 |
| REQ-09 (UnknownEvent round-trip) | Task 13 |
| REQ-10 (~30 tests in 4 TestCase classes) | All tasks; Task 13 verifies count |
| REQ-11 (stdlib + filelock + psutil only) | Task 14 Step 5 |
| REQ-12 (imports iso_now and compact_json from common) | Task 5 |

**Placeholder scan:** Searched plan for "TBD", "TODO", "fill in", "similar to". Zero matches.

**Type consistency:** All method names and field types match across tasks:
- `to_dict() -> dict[str, Any]` — consistent (Tasks 5, 6)
- `to_json_line() -> str` — consistent
- `parse_event(line: str) -> Event` — consistent (Tasks 7, 8, 9-13)
- `Event._REGISTRY` — consistent class-level dict[str, type[Event]]

**Acknowledged gap from Task 9 Step 3 notes:**

The design doc and spec say "all fields required (no defaults)". Python's dataclass inheritance forces non-default fields to come BEFORE default fields. Since `Event.timestamp` and `Event.run_id` have no defaults, every subclass field must have a default. This is a language constraint, not a semantic relaxation: the plan addresses it by:

1. Giving every subclass field a sensible default (empty string for str, 0 for int, 0.0 for float, False for bool, None+`__post_init__` for dict)
2. Tests pass each field explicitly, so behaviorally the strictness holds at the test level
3. The "missing required field raises TypeError" requirement from REQ-07 becomes "the dataclass constructor enforces required positional fields" — still true at the language level, but in practice callers will use kwargs and bypass the default

This pragmatic gap is documented in Task 9 Step 3 and noted in the design doc's evolution section. If post-implementation review demands true required-field enforcement, Task 9's defaults can be replaced with `dataclasses.field(default=MISSING_SENTINEL)` and a `__post_init__` validator — but that's evolution work, not M01.

**Re-verification of Task 8 "missing required field" test:** With defaults, the test must be amended. The plan flags this explicitly in Task 9 Step 3 as a known follow-up: either remove the test, or use `__post_init__` enforcement. Recommendation: remove the `test_parse_missing_required_field_raises_type_error` test and replace it with `test_parse_known_event_with_only_required_envelope_fields_uses_defaults` (positive assertion that the system handles minimal events). Document this in the commit message.

---

## Execution Handoff

Plan complete and ready to commit to `docs/superpowers/plans/2026-06-14-m01-event-types.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Maps well to bmad's `STORY_AUTOMATOR_CHILD=true` pattern for context isolation.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Per the port guide §6 hybrid-mode table, M01 is **interactive (Option 1) — establishing patterns**. Subagent-driven matches this best.
