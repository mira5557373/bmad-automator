# M01-M2 — Event Parsing (UnknownEvent + parse_event) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `core/telemetry_events.py` with the `UnknownEvent` forward-compatibility fallback (REQ-04) and the `parse_event(line: str) -> Event` dispatch function (REQ-07) with the full documented error matrix. Verified via throw-away test-local typed subclasses; the 13 production concrete events land in m01-m3.

**Architecture:** Still pure-data. `UnknownEvent` extends `Event` with two more required instance fields (`raw_event_type`, `raw_fields`) and overrides `to_dict` to re-emit the original `event_type` string and the captured `raw_fields` byte-equal to canonically-ordered input. `parse_event` is a single function: `json.loads` the line → pop `event_type` (raise `ValueError` if absent) → look up in `Event._REGISTRY` → if known, construct concrete instance via `cls(**payload)` (which raises `TypeError` naturally on missing/extra fields); if unknown, construct `UnknownEvent` with remaining payload as `raw_fields`. Invalid JSON propagates `json.JSONDecodeError` from `json.loads`. No new helper modules, no new dependencies.

**Tech Stack:** Python 3.11+ (`requires-python` in `pyproject.toml`). Stdlib only — adds the `json` import to the existing module. Tests use `unittest.TestCase` per project convention. Tests register typed sentinel subclasses inside test methods, isolated by the `_RegistryIsolationMixin` already in `tests/test_telemetry_events.py` from m01-m1.

**Slice scope:** This plan covers **m01-m2-event-parsing ONLY**: REQ-04 + REQ-07. It does NOT add any of the 13 production concrete event classes (REQ-05 / REQ-06 → m01-m3). It does NOT add the full round-trip invariant test suite (REQ-08 / REQ-09 → m01-m4), the coverage gate (NFR → m01-m4), the import-allowlist grep gate (REQ-11 → m01-m4), or the module-size gate (NFR → m01-m4). It DOES add a small byte-equal preservation test for `UnknownEvent` that closes REQ-04's "byte-equal to the original input line" sub-clause; the broader REQ-09 sweep across arbitrary unrecognized event_types belongs to m01-m4.

**Parent artifacts:**
- Spec: `docs/superpowers/specs/2026-06-14-m01-event-types.md` (focus on REQ-04, REQ-07)
- Design doc: `docs/superpowers/specs/2026-06-14-m01-event-types-design.md` (UnknownEvent class definition + parse_event contract + failure-mode table)
- Parent plan (full M01): `docs/superpowers/plans/2026-06-14-m01-event-types.md` (v2)
- Predecessor slice: `docs/superpowers/plans/2026-06-14-m01-m1-event-base.md`
- Workflow milestone: `.claude/workflow.json` → `milestones[1]` (`m01-m2-event-parsing`)

---

## File Structure

| Path | Kind | Responsibility (this slice) |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` | MODIFY | Add `import json` to the stdlib import block. Append the `UnknownEvent(Event)` `@dataclass` with `raw_event_type: str`, `raw_fields: dict[str, Any]`, and the overridden `to_dict`. Append the `parse_event(line: str) -> Event` function with the documented error matrix. Update `__all__` to add `"UnknownEvent"` and `"parse_event"`. |
| `tests/test_telemetry_events.py` | MODIFY | Append `UnknownEventTests` (4 tests across Tasks 2+3), `UnknownEventToDictTests` (5 tests in Task 4), `ParseEventHappyPathTests` (2 tests across Tasks 5+6 using `_RegistryIsolationMixin` + test-local sentinel subclasses), `ParseEventErrorPathTests` (5 tests across Tasks 7+8+9+10 covering ValueError, JSONDecodeError×2, TypeError×2), `UnknownEventByteEqualPreservationTests` (1 narrow byte-equal test for REQ-04 closure in Task 11), and `ParseEventExportContractTests` (3 tests in Task 12). **Total +20 tests across 6 new test classes.** No edits to existing m01-m1 test classes. The m01-m1 baseline is **24 tests**; m01-m2 brings the file to **44 tests** total. |

**Out of scope (DO NOT add in this slice):**
- The 13 production concrete event classes (`StoryStarted`, …, `BudgetAlert`) — m01-m3 owns REQ-05 + REQ-06.
- The 13 round-trip integration tests (REQ-08) — m01-m4.
- The full REQ-09 byte-equal sweep across arbitrary unrecognized event_types and unicode payloads — m01-m4.
- The 85% coverage gate (`pytest --cov-fail-under=85`) — m01-m4.
- The import-allowlist grep gate — m01-m4.
- The module-size `wc -l` gate — m01-m4.
- Module re-exports beyond `UnknownEvent` + `parse_event` (e.g., the production event classes' names).

## Conventions

- `from __future__ import annotations` is already present at the top of the module — do not duplicate.
- Plain `@dataclass` for `UnknownEvent` (no `kw_only=True`, no `frozen=True`). All four instance fields (`timestamp`, `run_id`, `raw_event_type`, `raw_fields`) are required and have no defaults, so Python's dataclass-inheritance ordering rule is satisfied without `kw_only`.
- PEP 604 union types where applicable. None are needed in this slice (no `Optional`-shaped fields).
- Import shared helpers from `story_automator.core.common` (already in place from m01-m1; this slice does not add any new shared helpers).
- The new `json` import goes in the stdlib block (alphabetically after `dataclasses`, before `typing` would conflict — see Task 5 for exact placement matching ruff's default isort behavior).
- Tests: `unittest.TestCase` subclasses; inline `from ... import ...` per test method matches existing m01-m1 style.
- Test sentinel subclasses are prefixed `_` and live inside the test method that defines them. Any test that defines a `_temp_*` typed subclass with an `EVENT_TYPE` MUST inherit from `_RegistryIsolationMixin` (already defined in `tests/test_telemetry_events.py` from m01-m1) to snapshot/restore `Event._REGISTRY`. Forgetting this leaks keys across tests and causes spurious failures.
- Conventional Commits with `Generated-By: claude-opus-4-7` trailer. One commit per task (the commit message is provided verbatim in each task's final step).

## Test runner commands (cross-platform)

| Action | Command (Windows git-bash / WSL / Linux all OK) |
|---|---|
| Run this slice's tests only | `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v` |
| Run a single new test class | `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventHappyPathTests -v` |
| Lint new+modified files | `python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` |
| Format check | `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` |
| Full suite still passes | `npm run test:python` |

The `python` command on Windows resolves to Python 3.14 at `/c/Python314/python`; on WSL/Linux it resolves to whatever `python3` is configured (3.11/3.12/3.13). REQ-01's multi-version import-cleanliness criterion remains satisfied for the platforms available to the executor (no new syntax requiring 3.13/3.14 is introduced — all features used are 3.11+).

## BLOCKED protocol

If any step produces unexpected output:
1. Stop. Do NOT proceed to the next step.
2. Capture the exact command, full stdout, full stderr, exit code.
3. Report: `BLOCKED at Task N Step S: <one-line summary>. Command: ..., Expected: ..., Actual: ...`
4. Wait for guidance before resuming.

Common blockers anticipated for this slice:
- **Registry leakage:** an earlier test forgot `_RegistryIsolationMixin` and a `_temp_*` key persists into the next test, causing `RuntimeError: duplicate EVENT_TYPE`. Fix: add the mixin to the offending class and re-run.
- **Field ordering:** if a future maintainer adds a defaulted instance field to `Event` (e.g., `timestamp: str = ""`), `UnknownEvent`'s required `raw_event_type: str` would violate Python's "non-default after default" rule. Fix: use `@dataclass(kw_only=True)` on `UnknownEvent`. For this slice, the base has no defaults, so plain `@dataclass` works.
- **JSON ordering:** `UnknownEvent.to_dict` emits `event_type, timestamp, run_id, **raw_fields` in that order; if a caller hand-builds JSON in a non-canonical order, byte-equal preservation will not hold. This is documented in REQ-04's "byte-equal to the original input line" — interpreted as "byte-equal when the original input was already canonically ordered (which is true for everything that comes out of `to_json_line`)". The narrow byte-equal test in Task 11 builds the original via `compact_json` to satisfy this interpretation.

---

## Task 1: Site inventory grep — confirm no pre-existing `UnknownEvent` / `parse_event` collisions

**Files:** None modified — verification only.

- [ ] **Step 1: Grep the source tree for the new names**

Run:

```bash
grep -rnE "\bUnknownEvent\b|\bparse_event\b" \
  skills/bmad-story-automator/src/ tests/ 2>&1
```

Expected: zero matches under `skills/bmad-story-automator/src/`. The current `tests/test_telemetry_events.py` from m01-m1 may have zero matches as well (m01-m1 did not anticipate these names yet). If any hit appears outside this slice's intended files, read its context — semantic collision would block the slice; an unrelated identifier hit (e.g., a `parse_event_log` helper elsewhere) is acceptable but should be noted in the BLOCKED report.

- [ ] **Step 2: Confirm `_RegistryIsolationMixin` is available**

Run:

```bash
grep -n "_RegistryIsolationMixin" tests/test_telemetry_events.py
```

Expected: a class definition near the top and several uses by m01-m1 test classes. If absent, BLOCKED — m01-m1 was supposed to land this mixin. (We use it without redefining.)

- [ ] **Step 3: Confirm the existing module exports**

Run:

```bash
grep -n "^__all__" skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: a line near the bottom listing at least `"Event"`, `"compact_json"`, `"iso_now"`. We will append `"UnknownEvent"` and `"parse_event"` to this list in Task 12.

- [ ] **Step 4: Confirm the slice's parent commits exist on the current branch**

Run:

```bash
git log --oneline -n 10
```

Expected: recent commits include m01-m1's `feat(telemetry): ...` and `test(telemetry): ...` entries plus the `Event.to_json_line` and `iso_now`/`compact_json` re-export commits. If the predecessor commits are missing, this slice cannot proceed — BLOCKED.

No commit for this task — it is a verification gate only. Proceed to Task 2.

---

## Task 2: `UnknownEvent` class skeleton with fields

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing tests for the `UnknownEvent` class shape**

Append the following to `tests/test_telemetry_events.py` (above the `if __name__ == "__main__":` line):

```python
class UnknownEventTests(unittest.TestCase):
    def test_unknown_event_class_exists(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        self.assertTrue(hasattr(UnknownEvent, "EVENT_TYPE"))
        self.assertEqual(UnknownEvent.EVENT_TYPE, "")

    def test_unknown_event_dataclass_fields(self) -> None:
        from dataclasses import fields
        from story_automator.core.telemetry_events import UnknownEvent

        field_names = {f.name for f in fields(UnknownEvent)}
        # Inherits timestamp + run_id from Event; adds raw_event_type + raw_fields.
        self.assertEqual(
            field_names,
            {"timestamp", "run_id", "raw_event_type", "raw_fields"},
        )

    def test_unknown_event_constructs_with_required_fields(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        instance = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="future_thing_M99",
            raw_fields={"alpha": 1, "beta": "two"},
        )
        self.assertEqual(instance.timestamp, "t")
        self.assertEqual(instance.run_id, "r")
        self.assertEqual(instance.raw_event_type, "future_thing_M99")
        self.assertEqual(instance.raw_fields, {"alpha": 1, "beta": "two"})
```

- [ ] **Step 2: Run the new tests (expect FAIL)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.UnknownEventTests -v
```

Expected: 3 failures with `ImportError: cannot import name 'UnknownEvent' from 'story_automator.core.telemetry_events'`.

- [ ] **Step 3: Implement the `UnknownEvent` class**

In `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`, append the following class definition **after** the `Event` class definition (i.e., after the existing `to_json_line` method's closing line, but BEFORE the `__all__` block):

```python
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
```

(The `to_dict` override lands in Task 4; this task only adds the dataclass shape so the construction + field-introspection tests pass.)

- [ ] **Step 4: Run tests (expect PASS)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all previously-passing m01-m1 tests still pass, plus the 3 new `UnknownEventTests` cases pass. Total grows from the m01-m1 count by exactly 3.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): UnknownEvent dataclass with raw_event_type and raw_fields"
```

---

## Task 3: Verify `UnknownEvent` is NOT auto-registered

**Files:**
- Modify: `tests/test_telemetry_events.py`

(No source change — m01-m1's `__init_subclass__` already returns early when `cls.EVENT_TYPE` is falsy. This task adds the explicit regression test for REQ-04's "must NOT be auto-registered" clause.)

- [ ] **Step 1: Append the registration-exclusion test**

Append to the `UnknownEventTests` class (i.e., add it as another `def test_...` method inside the existing class — keep it grouped with the other UnknownEvent shape tests):

```python
    def test_unknown_event_not_in_registry(self) -> None:
        from story_automator.core.telemetry_events import Event, UnknownEvent

        # Direct lookup by the empty-string EVENT_TYPE must not return
        # UnknownEvent (and must not even contain the empty string as a key).
        self.assertNotIn("", Event._REGISTRY)
        # Defense in depth: scan all registered classes to confirm
        # UnknownEvent is not present under any key (e.g., if a future
        # refactor accidentally registered it under a different string).
        for registered_cls in Event._REGISTRY.values():
            self.assertIsNot(registered_cls, UnknownEvent)
```

- [ ] **Step 2: Run the new test (expect PASS without source change)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.UnknownEventTests.test_unknown_event_not_in_registry -v
```

Expected: PASS. Verifies that `__init_subclass__`'s `if not cls.EVENT_TYPE: return` short-circuit correctly skips `UnknownEvent`. If this FAILS, m01-m1's registration logic regressed — BLOCKED, do not patch around it.

- [ ] **Step 3: Run the full file to confirm no regressions**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass, count grows by 1.

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): UnknownEvent is not auto-registered in _REGISTRY"
```

---

## Task 4: `UnknownEvent.to_dict` override — re-emit original `event_type` and `raw_fields`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing tests for the `to_dict` override**

Append a new test class to `tests/test_telemetry_events.py` (placed after `UnknownEventTests`):

```python
class UnknownEventToDictTests(unittest.TestCase):
    def test_to_dict_event_type_is_raw_event_type(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        instance = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="future_thing_M99",
            raw_fields={"alpha": 1},
        )
        data = instance.to_dict()
        self.assertEqual(data["event_type"], "future_thing_M99")

    def test_to_dict_includes_envelope_fields(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        data = UnknownEvent(
            timestamp="ts-value",
            run_id="rid-value",
            raw_event_type="x",
            raw_fields={},
        ).to_dict()
        self.assertEqual(data["timestamp"], "ts-value")
        self.assertEqual(data["run_id"], "rid-value")

    def test_to_dict_merges_raw_fields_at_top_level(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        data = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="x",
            raw_fields={"alpha": 1, "beta": "two", "gamma": [3]},
        ).to_dict()
        self.assertEqual(data["alpha"], 1)
        self.assertEqual(data["beta"], "two")
        self.assertEqual(data["gamma"], [3])

    def test_to_dict_excludes_internal_field_names(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        data = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="x",
            raw_fields={"alpha": 1},
        ).to_dict()
        # The internal field names raw_event_type/raw_fields MUST NOT appear
        # in the output dict — they are implementation details. The output is
        # the wire representation: event_type + envelope + payload fields.
        self.assertNotIn("raw_event_type", data)
        self.assertNotIn("raw_fields", data)

    def test_to_dict_key_order_is_event_type_then_envelope_then_fields(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        data = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="x",
            raw_fields={"alpha": 1, "beta": 2},
        ).to_dict()
        keys = list(data.keys())
        # Canonical order: event_type, timestamp, run_id, then raw_fields keys
        # in their insertion order. This is the contract that lets REQ-04's
        # "byte-equal to the original input line" hold when the original input
        # was itself canonically ordered.
        self.assertEqual(keys[:3], ["event_type", "timestamp", "run_id"])
        self.assertEqual(keys[3:], ["alpha", "beta"])
```

- [ ] **Step 2: Run the new tests (expect FAIL)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.UnknownEventToDictTests -v
```

Expected: ALL 5 tests fail. The default inherited `Event.to_dict` would put `event_type=""` (from the classvar) instead of `raw_event_type`, and would include `raw_event_type`/`raw_fields` in the output (because they're dataclass fields and `asdict` walks them).

- [ ] **Step 3: Override `to_dict` on `UnknownEvent`**

In `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`, modify the `UnknownEvent` class to add the `to_dict` override. The class body (after Task 2) is:

```python
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
```

Add the following method to the class (after the field declarations):

```python
    def to_dict(self) -> dict[str, Any]:
        """Re-emit the original ``event_type`` and unrecognized fields.

        Returns a dict shaped like the wire form of any other Event:
        ``{"event_type": <raw>, "timestamp": ..., "run_id": ..., **raw_fields}``.
        The internal ``raw_event_type`` and ``raw_fields`` field names do
        NOT appear in the output — they are implementation details that
        capture the unrecognized payload, not part of the JSONL contract.
        Key order is event_type → timestamp → run_id → raw_fields-in-
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
```

- [ ] **Step 4: Run tests (expect PASS)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all previously passing tests still pass, plus the 5 new `UnknownEventToDictTests` cases pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): UnknownEvent.to_dict re-emits raw event_type and fields"
```

---

## Task 5: `parse_event` happy path — typed dispatch via test sentinel

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing test for the happy-path typed dispatch**

Append a new test class to `tests/test_telemetry_events.py`:

```python
class ParseEventHappyPathTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_parse_known_event_type_dispatches_to_subclass(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import (
            Event,
            compact_json,
            parse_event,
        )

        @dataclass
        class _ParsedFoo(Event):
            EVENT_TYPE: ClassVar[str] = "_parsed_foo"
            payload: str

        line = compact_json({
            "event_type": "_parsed_foo",
            "timestamp": "t",
            "run_id": "r",
            "payload": "hi",
        })
        event = parse_event(line)
        self.assertIs(type(event), _ParsedFoo)
        self.assertEqual(event.timestamp, "t")
        self.assertEqual(event.run_id, "r")
        self.assertEqual(event.payload, "hi")
```

Note: this test inherits `_RegistryIsolationMixin` so the `_ParsedFoo` registration is snapshot/restored. `compact_json` is used (instead of `json.dumps`) so the test does not depend on default-separator drift between callers; the produced line is canonical.

- [ ] **Step 2: Run the new test (expect FAIL)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventHappyPathTests -v
```

Expected: `ImportError: cannot import name 'parse_event' from 'story_automator.core.telemetry_events'`.

- [ ] **Step 3: Add the `json` import to the module**

In `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`, modify the stdlib import block. The current block (from m01-m1) is:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .common import compact_json, iso_now
```

Change it to:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from .common import compact_json, iso_now
```

(`import json` goes in the stdlib block, alphabetically before `from dataclasses ...` per ruff's default `isort` ordering: bare `import` statements precede `from` statements within the same group.)

- [ ] **Step 4: Implement the minimal `parse_event` (happy path only)**

Append the following function definition **after** the `UnknownEvent` class definition and **before** the `__all__` block:

```python
def parse_event(line: str) -> Event:
    """Parse a single JSONL line into a typed ``Event`` instance.

    Dispatches by the ``event_type`` field. Known event_types route to the
    matching concrete subclass in ``Event._REGISTRY``; unknown event_types
    route to ``UnknownEvent`` (preserving the original event_type string
    and the unrecognized payload fields). Error semantics are documented
    in the M01 spec (REQ-07) and validated by the test matrix.
    """
    payload = json.loads(line)
    event_type = payload.pop("event_type")
    cls = Event._REGISTRY[event_type]
    return cls(**payload)
```

This is intentionally the **minimum** that makes Task 5's test pass — the happy path with a known event_type. Tasks 6, 7, 8, 9, 10 will incrementally add the unknown-fallback, the missing-event_type guard, and the property-level error tests.

- [ ] **Step 5: Run tests (expect PASS)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all previously-passing tests still pass, plus the 1 new `ParseEventHappyPathTests.test_parse_known_event_type_dispatches_to_subclass` case passes.

- [ ] **Step 6: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): parse_event dispatches known event_type to registered subclass"
```

---

## Task 6: `parse_event` — unknown `event_type` routes to `UnknownEvent`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing test for the unknown-fallback path**

Append to the existing `ParseEventHappyPathTests` class:

```python
    def test_parse_unknown_event_type_routes_to_unknown_event(self) -> None:
        from story_automator.core.telemetry_events import (
            UnknownEvent,
            compact_json,
            parse_event,
        )

        line = compact_json({
            "event_type": "future_thing_M99",
            "timestamp": "t",
            "run_id": "r",
            "anything": 42,
            "other": "value",
        })
        event = parse_event(line)
        self.assertIs(type(event), UnknownEvent)
        self.assertEqual(event.raw_event_type, "future_thing_M99")
        self.assertEqual(event.timestamp, "t")
        self.assertEqual(event.run_id, "r")
        self.assertEqual(event.raw_fields, {"anything": 42, "other": "value"})
```

- [ ] **Step 2: Run the new test (expect FAIL)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventHappyPathTests.test_parse_unknown_event_type_routes_to_unknown_event -v
```

Expected: FAIL with `KeyError: 'future_thing_M99'` (from `Event._REGISTRY[event_type]` lookup).

- [ ] **Step 3: Modify `parse_event` to fall back to `UnknownEvent`**

Replace the body of `parse_event` in `core/telemetry_events.py` with:

```python
def parse_event(line: str) -> Event:
    """Parse a single JSONL line into a typed ``Event`` instance.

    Dispatches by the ``event_type`` field. Known event_types route to the
    matching concrete subclass in ``Event._REGISTRY``; unknown event_types
    route to ``UnknownEvent`` (preserving the original event_type string
    and the unrecognized payload fields). Error semantics are documented
    in the M01 spec (REQ-07) and validated by the test matrix.
    """
    payload = json.loads(line)
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

Key changes from the Task 5 minimal version:
- `Event._REGISTRY.get(event_type)` instead of `Event._REGISTRY[event_type]` (no `KeyError` for unknowns).
- If `cls is None`, construct `UnknownEvent`. `payload.pop("timestamp", "")` and `payload.pop("run_id", "")` defensively handle inputs that omit those fields (REQ-07 doesn't require strict envelope on unknown events — they fall through to empty-string sentinels so old code can read newer streams that may have moved fields around).
- The remaining `payload` (after both pops) becomes `raw_fields`. Insertion order is preserved (Python 3.7+).

- [ ] **Step 4: Run tests (expect PASS)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all previously-passing tests still pass, plus the new `test_parse_unknown_event_type_routes_to_unknown_event` case passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): parse_event routes unknown event_type to UnknownEvent"
```

---

## Task 7: `parse_event` — missing `event_type` raises `ValueError`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing test for missing `event_type`**

Append a new test class to `tests/test_telemetry_events.py`:

```python
class ParseEventErrorPathTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_parse_missing_event_type_raises_value_error(self) -> None:
        from story_automator.core.telemetry_events import compact_json, parse_event

        line = compact_json({"timestamp": "t", "run_id": "r"})
        with self.assertRaises(ValueError) as ctx:
            parse_event(line)
        # The error message must mention the missing field by name so an
        # operator scanning a log can identify the problem at a glance.
        self.assertIn("event_type", str(ctx.exception))
```

- [ ] **Step 2: Run the new test (expect FAIL)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventErrorPathTests.test_parse_missing_event_type_raises_value_error -v
```

Expected: FAIL with `KeyError: 'event_type'` from `payload.pop("event_type")` — the current implementation does not yet check for the field's presence.

- [ ] **Step 3: Add the missing-`event_type` guard to `parse_event`**

Replace the body of `parse_event` in `core/telemetry_events.py` with:

```python
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

Key change: the new `if "event_type" not in payload:` guard raises `ValueError` with the missing field name **and** the first 80 characters of the offending line (with `!r` for unambiguous quoting). The 80-character truncation prevents log spam if the line is huge (a JSON line could in theory be megabytes). REQ-07 calls this a "structural error" — distinct from forward-compat (unknown event_type) which routes to `UnknownEvent`.

- [ ] **Step 4: Run tests (expect PASS)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all previously-passing tests still pass, plus the new `test_parse_missing_event_type_raises_value_error` case passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): parse_event raises ValueError when event_type field missing"
```

---

## Task 8: `parse_event` — invalid JSON propagates `json.JSONDecodeError`

**Files:**
- Modify: `tests/test_telemetry_events.py`

(No source change — `json.loads(line)` naturally raises `json.JSONDecodeError` for malformed input. This task adds the explicit regression test to lock the behavior.)

- [ ] **Step 1: Write the test**

Append to the existing `ParseEventErrorPathTests` class:

```python
    def test_parse_invalid_json_propagates_json_decode_error(self) -> None:
        import json
        from story_automator.core.telemetry_events import parse_event

        with self.assertRaises(json.JSONDecodeError):
            parse_event("this is not json {{{")

    def test_parse_empty_string_propagates_json_decode_error(self) -> None:
        import json
        from story_automator.core.telemetry_events import parse_event

        with self.assertRaises(json.JSONDecodeError):
            parse_event("")
```

(Two tests — one for malformed input, one for the boundary case of empty input. Both must surface `json.JSONDecodeError` cleanly without being swallowed or converted to a different exception type.)

- [ ] **Step 2: Run the new tests (expect PASS without source change)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventErrorPathTests -v
```

Expected: both new tests PASS. `json.loads("this is not json {{{")` and `json.loads("")` both raise `json.JSONDecodeError` natively, and `parse_event` does not catch it.

If either FAILS, BLOCKED — the upstream behavior of `json.loads` changed (unlikely; the Python stdlib documents this contract).

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): parse_event surfaces json.JSONDecodeError for malformed input"
```

---

## Task 9: `parse_event` — typed event missing required field raises `TypeError`

**Files:**
- Modify: `tests/test_telemetry_events.py`

(No source change — `cls(**payload)` with a typed dataclass that has a required field naturally raises `TypeError`. This task adds the regression test using a test-local sentinel subclass.)

- [ ] **Step 1: Write the test**

Append to the existing `ParseEventErrorPathTests` class:

```python
    def test_parse_typed_event_missing_required_field_raises_type_error(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import (
            Event,
            compact_json,
            parse_event,
        )

        @dataclass
        class _RequiresPayload(Event):
            EVENT_TYPE: ClassVar[str] = "_requires_payload"
            payload: str  # required, no default

        line = compact_json({
            "event_type": "_requires_payload",
            "timestamp": "t",
            "run_id": "r",
            # 'payload' deliberately omitted
        })
        with self.assertRaises(TypeError) as ctx:
            parse_event(line)
        # Dataclass __init__ raises with the field name embedded so a
        # consumer can identify the missing field. This is a property of
        # CPython's dataclass implementation — REQ-07 relies on it.
        self.assertIn("payload", str(ctx.exception))
```

- [ ] **Step 2: Run the new test (expect PASS without source change)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventErrorPathTests.test_parse_typed_event_missing_required_field_raises_type_error -v
```

Expected: PASS. The sentinel `_RequiresPayload` has `payload: str` with no default. When `parse_event` calls `_RequiresPayload(timestamp="t", run_id="r")` (without `payload`), Python's auto-generated `__init__` raises `TypeError: __init__() missing 1 required positional argument: 'payload'` (or similar — the exact wording varies by Python version, hence we only assert that `"payload"` is mentioned).

If this test FAILS, the parent class's `__init_subclass__` registration may have been broken by an earlier change, or the dataclass decorator's strictness has regressed — BLOCKED.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): parse_event raises TypeError for typed event missing field"
```

---

## Task 10: `parse_event` — typed event with extra field raises `TypeError`

**Files:**
- Modify: `tests/test_telemetry_events.py`

(No source change — `cls(**payload)` with an unexpected keyword argument naturally raises `TypeError`. This task pins the regression.)

- [ ] **Step 1: Write the test**

Append to the existing `ParseEventErrorPathTests` class:

```python
    def test_parse_typed_event_extra_field_raises_type_error(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import (
            Event,
            compact_json,
            parse_event,
        )

        @dataclass
        class _NoExtras(Event):
            EVENT_TYPE: ClassVar[str] = "_no_extras"
            # No additional fields — only inherits timestamp + run_id.

        line = compact_json({
            "event_type": "_no_extras",
            "timestamp": "t",
            "run_id": "r",
            "uninvited": "guest",
        })
        with self.assertRaises(TypeError) as ctx:
            parse_event(line)
        # Dataclass __init__ rejects unexpected kwargs by name. Strict
        # construction is a property of CPython we lean on for REQ-07.
        self.assertIn("uninvited", str(ctx.exception))
```

- [ ] **Step 2: Run the new test (expect PASS without source change)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventErrorPathTests.test_parse_typed_event_extra_field_raises_type_error -v
```

Expected: PASS. `_NoExtras(timestamp="t", run_id="r", uninvited="guest")` raises `TypeError: __init__() got an unexpected keyword argument 'uninvited'`.

If this test FAILS, the dataclass strictness contract has regressed — BLOCKED.

- [ ] **Step 3: Run the full file**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: every test (m01-m1 baseline + all m01-m2 additions through this task) passes. After this task, the `parse_event` error matrix is fully covered: ValueError on structural error, JSONDecodeError on malformed input, TypeError on typed-event field mismatch (both directions).

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): parse_event raises TypeError for typed event with extra field"
```

---

## Task 11: `UnknownEvent` round-trip byte-equal preservation (REQ-04 closure)

**Files:**
- Modify: `tests/test_telemetry_events.py`

(No source change — `UnknownEvent.to_dict` from Task 4 + `to_json_line` inherited from `Event` together produce a canonical-order JSON line. The full REQ-09 sweep is m01-m4; this task lands the narrow byte-equal test that closes REQ-04's "byte-equal to the original input line" sub-clause.)

- [ ] **Step 1: Write the byte-equal preservation test**

Append a new test class to `tests/test_telemetry_events.py`:

```python
class UnknownEventByteEqualPreservationTests(unittest.TestCase):
    def test_round_trip_preserves_byte_equal_for_canonical_input(self) -> None:
        from story_automator.core.telemetry_events import (
            UnknownEvent,
            compact_json,
            parse_event,
        )

        # The original line is built via compact_json so it is canonically
        # ordered (event_type, timestamp, run_id, then payload fields in
        # insertion order). This is the contract REQ-04's "byte-equal to
        # the original input line" relies on — lines produced by
        # to_json_line are always canonically ordered, so round-trip is
        # byte-equal for any input that came out of the typed-telemetry
        # substrate. Hand-built JSON in arbitrary key order is NOT
        # required to round-trip byte-equal (and m01-m4 does not extend
        # that property either).
        original = compact_json({
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
        self.assertEqual(parsed.raw_event_type, "future_thing_M99")

        reemitted = parsed.to_json_line()
        # Strict byte-level equality: guards against any future regression
        # in compact_json's separator policy, UnknownEvent.to_dict's key
        # insertion order, or dict.update's behavior for raw_fields. The
        # property-level tests in UnknownEventToDictTests (Task 4) catch
        # the obvious cases; this one pins the exact wire format.
        self.assertEqual(reemitted, original)
```

- [ ] **Step 2: Run the new test (expect PASS without source change)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.UnknownEventByteEqualPreservationTests -v
```

Expected: PASS. The `compact_json`-built original line round-trips byte-equal through `parse_event` → `UnknownEvent.to_dict` → `to_json_line` → byte-equal.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): UnknownEvent round-trips byte-equal for canonical input"
```

---

## Task 12: Update `__all__` to export `UnknownEvent` and `parse_event`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write failing export-contract tests**

Append a new test class to `tests/test_telemetry_events.py`:

```python
class ParseEventExportContractTests(unittest.TestCase):
    def test_module_exports_unknown_event_in_all(self) -> None:
        from story_automator.core import telemetry_events

        self.assertIn("UnknownEvent", telemetry_events.__all__)

    def test_module_exports_parse_event_in_all(self) -> None:
        from story_automator.core import telemetry_events

        self.assertIn("parse_event", telemetry_events.__all__)

    def test_module_exports_are_callable_from_top_level(self) -> None:
        # Both must be reachable via `from .telemetry_events import X`
        # (smoke-tests that __all__ matches the actually-defined names).
        from story_automator.core.telemetry_events import (  # noqa: F401
            UnknownEvent,
            parse_event,
        )

        self.assertTrue(callable(parse_event))
        self.assertTrue(isinstance(UnknownEvent, type))
```

- [ ] **Step 2: Run the new tests (expect FAIL)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ParseEventExportContractTests -v
```

Expected: 2 failures on the `__all__` membership tests; the third "callable from top-level" test should PASS because the names are already defined in the module (just not in `__all__` yet).

- [ ] **Step 3: Update `__all__` in the module**

In `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`, find the `__all__` block near the bottom (after m01-m1 it looks like):

```python
__all__ = [
    "Event",
    "compact_json",
    "iso_now",
]
```

Replace it with:

```python
__all__ = [
    "Event",
    "UnknownEvent",
    "compact_json",
    "iso_now",
    "parse_event",
]
```

(Alphabetical-within-group ordering matches the m01-m1 style — classes ordered by name, then helper functions, then the parsing entry point. `compact_json` and `iso_now` are kept grouped with `parse_event` because they're all top-level callables alongside the classes.)

- [ ] **Step 4: Update the module docstring**

The current module docstring (from m01-m1) anticipates that `UnknownEvent` and `parse_event` will land later:

```python
"""Typed telemetry events for bmad-automator (M01 wedge atom).

This module provides the `Event` base @dataclass with a registry-based
discriminator mechanism (auto-registration via __init_subclass__), the
shared envelope fields (timestamp, run_id), and the serialization
helpers (to_dict, to_json_line). The forward-compatibility fallback
`UnknownEvent`, the 13 concrete typed event classes, and the
`parse_event` dispatch land in subsequent slices (m01-m2 ... m01-m4).
"""
```

After m01-m2 lands `UnknownEvent` and `parse_event`, the docstring is stale. Replace the entire module docstring with:

```python
"""Typed telemetry events for bmad-automator (M01 wedge atom).

This module provides the `Event` base @dataclass with a registry-based
discriminator mechanism (auto-registration via __init_subclass__), the
shared envelope fields (timestamp, run_id), the serialization helpers
(to_dict, to_json_line), the `UnknownEvent` forward-compatibility
fallback, and the `parse_event(line) -> Event` dispatch function with
the documented error matrix (ValueError on missing event_type,
json.JSONDecodeError on malformed input, TypeError on typed-event field
mismatch). The 13 concrete typed event classes spanning the BMAD story
lifecycle land in m01-m3, and the full round-trip invariant test suite
plus the coverage / import-allowlist / module-size quality gates land
in m01-m4.
"""
```

This keeps the docstring honest about what the module currently provides versus what is still deferred.

- [ ] **Step 5: Run tests (expect PASS)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass, including the 3 new export-contract cases. The module docstring change is not exercised by a test (docstrings are documentation, not behavior), but the existing `tests.test_telemetry_events.EventImportContractTests.test_module_re_exports_iso_now` (and its compact_json sibling) still pass because the docstring replacement does not touch the `__all__` list or the helper re-exports.

- [ ] **Step 6: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): export UnknownEvent and parse_event; refresh module docstring"
```

---

## Task 13: Final quality gates (lint + format + full suite)

**Files:** None modified — verification only.

Note on deferred gates: the coverage gate (`pytest --cov-fail-under=85`), the import-allowlist grep gate, and the module-size `wc -l` gate are all deferred to m01-m4 per the milestone definition. This task runs only the gates whose contract is established by m01-m1 and continues into m01-m2: ruff lint, ruff format, and the full project unittest suite.

- [ ] **Step 1: Ruff lint**

Run:

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
```

Expected: `All checks passed!` and exit code 0.

If violations are reported, fix them inline. Anticipated potential issues:
- Unused import warnings if any of the new code paths reference a name that turns out to be unused (none expected — `json`, `asdict`, `Any`, `ClassVar` are all used).
- Line length violations if a docstring or error message wraps awkwardly (use `\n`-continuation strings within parentheses, not backslash continuations).

If a fix is needed, commit it as a separate task with: `git commit --trailer "Generated-By: claude-opus-4-7" -m "refactor(telemetry): satisfy ruff lint for m01-m2 additions"`.

- [ ] **Step 2: Ruff format check**

Run:

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
```

Expected: `X files already formatted` with exit code 0 (no files would be reformatted).

If reformat is needed, run the formatter, stage, and commit:

```bash
python -m ruff format \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
git add -A
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(telemetry): ruff format for m01-m2 additions"
```

- [ ] **Step 3: Full project test suite**

Run:

```bash
npm run test:python
```

Expected: all existing test files plus `tests/test_telemetry_events.py` pass with no failures. The exit code from `npm` must be 0.

If any pre-existing test regresses, the most likely cause is registry leakage from a m01-m2 test that defines a typed sentinel subclass but forgot `_RegistryIsolationMixin` — the leaked `_temp_*` key from one TestCase can cause a `RuntimeError: duplicate EVENT_TYPE` when the next TestCase tries to define a class with the same `EVENT_TYPE`. Audit any new test class that defines an inner `@dataclass class _X(Event):` and confirm the enclosing TestCase inherits `_RegistryIsolationMixin`.

- [ ] **Step 4: Final verification — count tests added in this slice**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events 2>&1 | tail -3
```

Expected: the final summary line reads `Ran 44 tests in <time> OK`. That is the **m01-m1 baseline of 24 tests plus the 20 added by m01-m2 = 44 total**.

Per-task / per-class breakdown of the 20 tests added by m01-m2:

| Task | New test class | Tests added in that task |
|---|---|---|
| 2 | `UnknownEventTests` | 3 (class exists, fields, constructs) |
| 3 | `UnknownEventTests` (extends) | 1 (`test_unknown_event_not_in_registry`) |
| 4 | `UnknownEventToDictTests` | 5 |
| 5 | `ParseEventHappyPathTests` | 1 (`test_parse_known_event_type_dispatches_to_subclass`) |
| 6 | `ParseEventHappyPathTests` (extends) | 1 (`test_parse_unknown_event_type_routes_to_unknown_event`) |
| 7 | `ParseEventErrorPathTests` | 1 (`test_parse_missing_event_type_raises_value_error`) |
| 8 | `ParseEventErrorPathTests` (extends) | 2 (invalid_json + empty_string) |
| 9 | `ParseEventErrorPathTests` (extends) | 1 (`test_parse_typed_event_missing_required_field_raises_type_error`) |
| 10 | `ParseEventErrorPathTests` (extends) | 1 (`test_parse_typed_event_extra_field_raises_type_error`) |
| 11 | `UnknownEventByteEqualPreservationTests` | 1 |
| 12 | `ParseEventExportContractTests` | 3 |
| **Total** | **6 new test classes** | **20** |

If the actual `Ran N tests` count differs from 44, audit which test classes / methods are present versus the table above. A common cause is a test method that was forgotten on append; another is a typo in a method name (must start with `test_` for unittest's discovery to find it).

- [ ] **Step 5: Slice complete — no commit (verification only)**

The slice is complete when all three gates above pass. No new commit is needed for verification — the per-task commits already capture the full slice. Future slices (m01-m3, m01-m4) extend the module without re-touching m01-m2's surface.

---

## Self-Review

After writing the plan, the following spot-checks were performed:

**1. Spec coverage (REQ-04 and REQ-07 only — per workflow.json milestone spec_sections):**

| Spec REQ sub-clause | Task that implements it |
|---|---|
| REQ-04: `UnknownEvent` is `@dataclass` subclass | Task 2 |
| REQ-04: NOT auto-registered into `_REGISTRY` | Task 3 |
| REQ-04: carries `raw_event_type: str` and `raw_fields: dict[str, Any]` | Task 2 |
| REQ-04: overrides `to_dict` to re-emit original `event_type` | Task 4 |
| REQ-04: re-emits unrecognized fields byte-equal | Tasks 4 + 11 |
| REQ-07: `parse_event(line: str) -> Event` exists | Task 5 |
| REQ-07: known `event_type` returns matching concrete instance | Tasks 5 + 12 (export) |
| REQ-07: unknown `event_type` returns `UnknownEvent` preserving raw values | Task 6 |
| REQ-07: missing `event_type` raises `ValueError` | Task 7 |
| REQ-07: invalid JSON propagates `json.JSONDecodeError` | Task 8 |
| REQ-07: typed event missing required field raises `TypeError` | Task 9 |
| REQ-07: typed event with extra fields raises `TypeError` | Task 10 |

Every REQ-04 and REQ-07 sub-clause maps to a task. No coverage gap.

**2. Placeholder scan:** searched the plan for `TBD`, `TODO`, `fill in`, `similar to`, `XXX`. Zero matches.

**3. Type consistency:** verified across tasks:
- `parse_event(line: str) -> Event` — consistent in Tasks 5, 6, 7 (all three impl revisions) and in every test method's import block.
- `UnknownEvent` fields: `raw_event_type: str`, `raw_fields: dict[str, Any]` — consistent in Task 2 (introduction), Task 4 (to_dict reads them), Task 6 (parse_event constructs UnknownEvent), Task 11 (round-trip).
- `Event._REGISTRY` — `dict[str, type[Event]]` from m01-m1; not modified by this slice.

**4. Test-count consistency:** the file-structure table and Task 13 Step 4 both report **20 tests across 6 new test classes** for m01-m2, taking the baseline (24 tests from m01-m1) to a final total of **44 tests** in `tests/test_telemetry_events.py`. The per-task / per-class breakdown table in Task 13 Step 4 is authoritative for verification.

**5. Cross-task dependencies:** Task 5 introduces `parse_event` with minimal happy-path logic; Tasks 6 and 7 modify the same function body. The exact replacement code is shown in each task, so the engineer working out-of-order or resuming from a checkpoint sees the full target body each time.

**6. Out-of-scope clarity:** the slice does NOT add the 13 production concrete event classes, the full round-trip sweep (REQ-08, REQ-09), the coverage gate, the allowlist gate, or the module-size gate. This is stated in the header's "Slice scope" paragraph, in the File Structure table's "Out of scope" callout, in Task 13's "Note on deferred gates" line, and in the workflow.json milestone definition for `m01-m2-event-parsing`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-14-m01-m2-event-parsing.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Each task in this plan is self-contained and matches that model well.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Per the port-guide hybrid-mode pattern, m01-m2 is **continuation of the M01 pattern** (m01-m1 established the conventions; m01-m2 is mechanical extension). Either execution mode works; subagent-driven preserves context isolation as the M01 plan grows.
