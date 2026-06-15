# M10a — Golden-Trace Data Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the pure data layer for the M10 golden-trace harness — typed dataclasses (`TraceEntry`, `TraceMismatch`, `TraceDiff`), the typed `GoldenTraceError`, and three pure helpers (`serialize_trace`, `load_golden`, `compare_traces`) — with no interception, no recorder, no fixtures, no monkey-patching.

**Architecture:** Single file `tests/golden_trace_helpers.py` (deliberately outside `src/` because this is testing infrastructure, not shipped code). The file is import-safe: defining dataclasses and pure functions runs no I/O and installs no hooks. Mismatch detection is a positional walk over two `list[TraceEntry]`; the first divergence per index is recorded as a `TraceMismatch`. Canonical JSON via `json.dumps(..., sort_keys=True, separators=(",", ":"))` plus a trailing `"\n"` gives byte-identical serialization across OSes and Python patch versions. Tests live in `tests/test_golden_trace_helpers.py` and exercise only the M10a surface — recorder coverage lands in M10b.

**Tech Stack:** Python 3.11+ stdlib only (`dataclasses`, `json`, `pathlib`, `typing`). No third-party deps. `ruff` + `mypy --strict` clean. `unittest.TestCase` per project convention. `tests/` is a namespace package (no `__init__.py`); `python -m unittest discover -s tests` handles this and `from tests.golden_trace_helpers import ...` works under both PEP 420 namespace discovery and the project's existing `PYTHONPATH=skills/bmad-story-automator/src` invocation pattern. **Do not** add `tests/__init__.py`.

**Imports convention:** Every code block in this plan that shows additions to either `tests/golden_trace_helpers.py` or `tests/test_golden_trace_helpers.py` shows the new symbols inline at the top of the snippet for readability, but the actual implementation **must consolidate all imports at the top of the file** (per `ruff E402`). When a task says "append" a test class, the test class body goes at the bottom of the file, and any imports it needs are merged into the top-of-file import block — do not let imports drift down between class definitions. Use grouped sections: stdlib first, then `tests.golden_trace_helpers` last.

---

## Scope boundary (anti-scope-creep)

**In scope for M10a (this plan):**
- REQ-02: `TraceEntry` (`@dataclass(kw_only=True, frozen=True)`).
- REQ-07: `serialize_trace(entries) -> str`.
- REQ-08: `load_golden(path) -> list[TraceEntry]` + `GoldenTraceError`.
- REQ-09: `compare_traces(actual, golden) -> TraceDiff`.
- REQ-10: `TraceMismatch` with `Literal` field-name and PEP 604 `object | None` slots.
- REQ-15: `from __future__ import annotations`, stdlib-only, `ruff` + `mypy --strict` clean.
- NFR: determinism (byte-identical serialization), isolation (no module-level state), diagnostics (human-readable mismatch summary).

**Out of scope for M10a (deferred):**
- M10b: `GoldenTraceRecorder` context manager, interception of `TelemetryEmitter.emit` / `commands.state.py` writes / `claude_p` invocations, threading lock, redaction of timestamps/PIDs/lock-token UUIDs, REQ-14 import-safety beyond what we already test.
- M10c: golden fixtures `tests/golden/m01_event_basics.json`, `tests/golden/m02_emitter_smoke.json`, `tests/golden/m05_atomic_write_smoke.json`, and the record-then-compare tests in REQ-12 sub-cases (a) and (e).

If a later task in this plan looks like it's drifting into recorder territory — stop, that's M10b.

---

## File structure

**Create:**
- `tests/golden_trace_helpers.py` — all four dataclasses, `GoldenTraceError`, and the three pure helpers.
- `tests/test_golden_trace_helpers.py` — `unittest.TestCase` coverage for every public symbol added in M10a.

**Do not modify:**
- Any file under `skills/bmad-story-automator/src/` (M10 is pure testing infrastructure).
- `pyproject.toml` (no new deps).
- Anything else.

---

## Public surface (locked here so later tasks use the same identifiers)

```python
# tests/golden_trace_helpers.py
__all__ = [
    "Channel",
    "GoldenTraceError",
    "MismatchField",
    "TraceDiff",
    "TraceEntry",
    "TraceMismatch",
    "compare_traces",
    "load_golden",
    "serialize_trace",
]

Channel = Literal["event", "state", "claude_p"]
MismatchField = Literal["channel", "kind", "payload", "length"]
_VALID_CHANNELS: frozenset[str] = frozenset({"event", "state", "claude_p"})
_REQUIRED_KEYS: tuple[str, ...] = ("seq", "channel", "kind", "payload")
```

The `Channel` and `MismatchField` aliases are exported so M10b/M10c can import them directly instead of re-stating the literal sets.

---

## Task 1: Bootstrap empty module + import-no-side-effects test

**Files:**
- Create: `tests/golden_trace_helpers.py`
- Create: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_golden_trace_helpers.py
from __future__ import annotations

import importlib
import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports_cleanly(self) -> None:
        module = importlib.import_module("tests.golden_trace_helpers")
        self.assertTrue(hasattr(module, "__all__"))

    def test_module_exports_expected_symbols(self) -> None:
        module = importlib.import_module("tests.golden_trace_helpers")
        expected = {
            "Channel",
            "GoldenTraceError",
            "MismatchField",
            "TraceDiff",
            "TraceEntry",
            "TraceMismatch",
            "compare_traces",
            "load_golden",
            "serialize_trace",
        }
        self.assertEqual(set(module.__all__), expected)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.golden_trace_helpers'` (or empty `__all__`).

- [ ] **Step 3: Create the minimal module skeleton**

```python
# tests/golden_trace_helpers.py
"""Golden-trace data types and pure helpers (M10a wedge).

The recorder, interception hooks, fixtures, and redaction layer land in
later M10 sub-milestones. Importing this module must produce no telemetry
events, no state mutations, and no claude_p invocations.
"""

from __future__ import annotations

from typing import Literal

Channel = Literal["event", "state", "claude_p"]
MismatchField = Literal["channel", "kind", "payload", "length"]

__all__ = [
    "Channel",
    "GoldenTraceError",
    "MismatchField",
    "TraceDiff",
    "TraceEntry",
    "TraceMismatch",
    "compare_traces",
    "load_golden",
    "serialize_trace",
]


class GoldenTraceError(ValueError):
    """Raised when a stored golden fixture is malformed or carries unknown channels."""


# Stubs — concrete implementations land in later tasks.
class TraceEntry:  # pragma: no cover - replaced in Task 3
    pass


class TraceMismatch:  # pragma: no cover - replaced in Task 4
    pass


class TraceDiff:  # pragma: no cover - replaced in Task 5
    pass


def serialize_trace(entries: list[TraceEntry]) -> str:  # pragma: no cover - replaced
    raise NotImplementedError


def load_golden(path: object) -> list[TraceEntry]:  # pragma: no cover - replaced
    raise NotImplementedError


def compare_traces(  # pragma: no cover - replaced
    actual: list[TraceEntry], golden: list[TraceEntry]
) -> TraceDiff:
    raise NotImplementedError
```

The stubs are intentionally throwaway scaffolding so the import test passes; every subsequent task replaces one of them.

- [ ] **Step 4: Run the test, verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers -v`
Expected: PASS for both `test_module_imports_cleanly` and `test_module_exports_expected_symbols`.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10a): bootstrap golden-trace helpers module"
```

---

## Task 2: GoldenTraceError type discrimination

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
from tests.golden_trace_helpers import GoldenTraceError


class GoldenTraceErrorTests(unittest.TestCase):
    def test_is_value_error_subclass(self) -> None:
        self.assertTrue(issubclass(GoldenTraceError, ValueError))

    def test_carries_message(self) -> None:
        err = GoldenTraceError("unknown channel 'foo'")
        self.assertIn("unknown channel", str(err))
```

- [ ] **Step 2: Run test, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.GoldenTraceErrorTests -v`
Expected: PASS — `GoldenTraceError(ValueError)` already exists from Task 1.

This task locks in the subclass contract so a later refactor that switches the base class will fail loudly.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10a): lock GoldenTraceError as ValueError subclass"
```

---

## Task 3: `TraceEntry` frozen dataclass (REQ-02)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
import dataclasses

from tests.golden_trace_helpers import TraceEntry


class TraceEntryTests(unittest.TestCase):
    def test_is_frozen_kw_only_dataclass(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(TraceEntry))
        params = TraceEntry.__dataclass_params__  # type: ignore[attr-defined]
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_required_fields_present(self) -> None:
        names = {f.name for f in dataclasses.fields(TraceEntry)}
        self.assertEqual(names, {"seq", "channel", "kind", "payload"})

    def test_construct_and_equality(self) -> None:
        a = TraceEntry(seq=0, channel="event", kind="StoryStarted", payload={"epic": "1"})
        b = TraceEntry(seq=0, channel="event", kind="StoryStarted", payload={"epic": "1"})
        self.assertEqual(a, b)

    def test_frozen_blocks_mutation(self) -> None:
        entry = TraceEntry(seq=0, channel="state", kind="mutation", payload={"path": "x"})
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.seq = 1  # type: ignore[misc]

    def test_positional_construction_rejected(self) -> None:
        # kw_only=True must forbid positional args.
        with self.assertRaises(TypeError):
            TraceEntry(0, "event", "StoryStarted", {})  # type: ignore[misc]
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.TraceEntryTests -v`
Expected: FAIL — current `TraceEntry` is an empty `class`, not a dataclass.

- [ ] **Step 3: Replace the stub with the real dataclass**

In `tests/golden_trace_helpers.py`, replace the `class TraceEntry: pass` stub with:

```python
from dataclasses import dataclass


@dataclass(kw_only=True, frozen=True)
class TraceEntry:
    """One arrival-ordered observation recorded by the golden-trace recorder.

    `payload` is a JSON-object dict whose key ordering is canonicalized at
    serialize time (REQ-07 uses sort_keys=True), so callers do not need to
    pre-sort payloads to get byte-identical traces.
    """

    seq: int
    channel: Channel
    kind: str
    payload: dict[str, object]
```

Move the `from dataclasses import dataclass` import to the top of the file alongside the existing imports. Delete the old stub class.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.TraceEntryTests -v`
Expected: PASS for all 5 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10a): add frozen kw_only TraceEntry dataclass"
```

---

## Task 4: `TraceMismatch` dataclass (REQ-10)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
from tests.golden_trace_helpers import TraceMismatch


class TraceMismatchTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(TraceMismatch))
        params = TraceMismatch.__dataclass_params__  # type: ignore[attr-defined]
        self.assertTrue(params.kw_only)
        # Not frozen — caller may want to attach diagnostics later.
        self.assertFalse(params.frozen)

    def test_required_fields(self) -> None:
        names = {f.name for f in dataclasses.fields(TraceMismatch)}
        self.assertEqual(names, {"seq", "field", "actual", "expected"})

    def test_construct_with_payload_diff(self) -> None:
        m = TraceMismatch(seq=3, field="payload", actual={"a": 1}, expected={"a": 2})
        self.assertEqual(m.seq, 3)
        self.assertEqual(m.field, "payload")
        self.assertEqual(m.actual, {"a": 1})
        self.assertEqual(m.expected, {"a": 2})

    def test_actual_and_expected_allow_none(self) -> None:
        # PEP 604 object | None per REQ-10 — used for "length" mismatches
        # where one side has no entry at that seq.
        m = TraceMismatch(seq=5, field="length", actual=None, expected={"x": 1})
        self.assertIsNone(m.actual)
        self.assertEqual(m.expected, {"x": 1})
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.TraceMismatchTests -v`
Expected: FAIL — `TraceMismatch` is still the empty stub.

- [ ] **Step 3: Replace the stub**

In `tests/golden_trace_helpers.py`, replace `class TraceMismatch: pass` with:

```python
@dataclass(kw_only=True)
class TraceMismatch:
    """One arrival-position divergence between an actual and a golden trace.

    `field` identifies which slot diverged (per REQ-10). `actual` and
    `expected` use PEP 604 `object | None` because a "length" mismatch may
    have no entry on one side at that arrival index.
    """

    seq: int
    field: MismatchField
    actual: object | None
    expected: object | None
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.TraceMismatchTests -v`
Expected: PASS for all 4 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10a): add TraceMismatch kw_only dataclass"
```

---

## Task 5: `TraceDiff` dataclass (REQ-09) + `summary()` method (NFR diagnostics)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
from tests.golden_trace_helpers import TraceDiff


class TraceDiffTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(TraceDiff))
        params = TraceDiff.__dataclass_params__  # type: ignore[attr-defined]
        self.assertTrue(params.kw_only)

    def test_required_fields(self) -> None:
        names = {f.name for f in dataclasses.fields(TraceDiff)}
        self.assertEqual(names, {"matched", "mismatches", "ok"})

    def test_empty_mismatches_is_ok(self) -> None:
        d = TraceDiff(matched=3, mismatches=[], ok=True)
        self.assertTrue(d.ok)

    def test_summary_includes_seq_and_field_for_each_mismatch(self) -> None:
        m1 = TraceMismatch(seq=2, field="payload", actual={"x": 1}, expected={"x": 2})
        m2 = TraceMismatch(seq=4, field="kind", actual="A", expected="B")
        d = TraceDiff(matched=2, mismatches=[m1, m2], ok=False)
        text = d.summary()
        # Each mismatch is mentioned by seq and field; field-context lets a
        # reader localize the regression without consulting the golden file.
        self.assertIn("seq=2", text)
        self.assertIn("payload", text)
        self.assertIn("seq=4", text)
        self.assertIn("kind", text)

    def test_summary_for_ok_diff_is_succinct(self) -> None:
        d = TraceDiff(matched=5, mismatches=[], ok=True)
        text = d.summary()
        self.assertIn("ok", text.lower())
        self.assertIn("5", text)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.TraceDiffTests -v`
Expected: FAIL — `TraceDiff` is still the empty stub.

- [ ] **Step 3: Replace the stub**

In `tests/golden_trace_helpers.py`, replace `class TraceDiff: pass` with:

```python
@dataclass(kw_only=True)
class TraceDiff:
    """Result of comparing two traces. ``ok=True`` iff lengths match and no
    arrival position diverged."""

    matched: int
    mismatches: list[TraceMismatch]
    ok: bool

    def summary(self) -> str:
        """Human-readable summary including the arrival position and the
        diverging field of each mismatch (NFR: Diagnostics).
        """
        if self.ok:
            return f"trace ok ({self.matched} entries matched)"
        lines = [
            f"trace mismatch: {self.matched} matched, {len(self.mismatches)} mismatch(es)",
        ]
        for m in self.mismatches:
            lines.append(
                f"  seq={m.seq} field={m.field} "
                f"actual={m.actual!r} expected={m.expected!r}"
            )
        return "\n".join(lines)
```

The `dataclass` import already lives at the top of the file from Task 3 — do not re-import it here.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.TraceDiffTests -v`
Expected: PASS for all 5 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10a): add TraceDiff with summary() diagnostic"
```

---

## Task 6: `serialize_trace` canonical-JSON output (REQ-07)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
from tests.golden_trace_helpers import serialize_trace


class SerializeTraceTests(unittest.TestCase):
    def _entry(self, seq: int) -> "TraceEntry":
        return TraceEntry(
            seq=seq,
            channel="event",
            kind="StoryStarted",
            payload={"z": 2, "a": 1, "m": [3, 2, 1]},
        )

    def test_returns_str_with_trailing_newline(self) -> None:
        out = serialize_trace([self._entry(0)])
        self.assertIsInstance(out, str)
        self.assertTrue(out.endswith("\n"))

    def test_compact_separators(self) -> None:
        out = serialize_trace([self._entry(0)])
        # REQ-07 separators=(",", ":") => no whitespace between tokens.
        self.assertNotIn(", ", out)
        self.assertNotIn(": ", out)

    def test_keys_are_sorted(self) -> None:
        out = serialize_trace([self._entry(0)]).rstrip("\n")
        # Both the entry-level keys and nested payload keys must be sorted.
        # Entry-level: channel < kind < payload < seq.
        self.assertLess(out.index('"channel"'), out.index('"kind"'))
        self.assertLess(out.index('"kind"'), out.index('"payload"'))
        self.assertLess(out.index('"payload"'), out.index('"seq"'))
        # Nested payload: a < m < z.
        self.assertLess(out.index('"a"'), out.index('"m"'))
        self.assertLess(out.index('"m"'), out.index('"z"'))

    def test_empty_list_serializes_to_bracket_newline(self) -> None:
        self.assertEqual(serialize_trace([]), "[]\n")

    def test_determinism_byte_identical_across_calls(self) -> None:
        entries = [self._entry(i) for i in range(5)]
        first = serialize_trace(entries)
        second = serialize_trace(entries)
        self.assertEqual(first, second)
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))

    def test_determinism_independent_of_payload_key_insertion_order(self) -> None:
        # Same logical payload constructed in two different insertion orders
        # must serialize byte-identically — this is what enables byte-equal
        # comparison across runs (NFR: Determinism).
        a = TraceEntry(seq=0, channel="event", kind="X", payload={"a": 1, "b": 2})
        b = TraceEntry(seq=0, channel="event", kind="X", payload={"b": 2, "a": 1})
        self.assertEqual(serialize_trace([a]), serialize_trace([b]))
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.SerializeTraceTests -v`
Expected: FAIL — current `serialize_trace` raises `NotImplementedError`.

- [ ] **Step 3: Implement `serialize_trace`**

Replace the stub in `tests/golden_trace_helpers.py` with:

```python
import json
from dataclasses import asdict


def serialize_trace(entries: list[TraceEntry]) -> str:
    """Serialize entries to canonical JSON with a trailing newline (REQ-07).

    Uses ``sort_keys=True`` so payload-dict insertion order is irrelevant
    and ``separators=(",", ":")`` to produce the compact form. The trailing
    newline matches the project's JSONL/JSON conventions and keeps git
    diffs clean.
    """
    payload = [asdict(entry) for entry in entries]
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
```

Add `import json` and `from dataclasses import asdict, dataclass` (merge with the existing `dataclass` import) at the top of the file.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.SerializeTraceTests -v`
Expected: PASS for all 6 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10a): add canonical serialize_trace"
```

---

## Task 7: `load_golden` happy path (REQ-08, half)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
import tempfile
from pathlib import Path

from tests.golden_trace_helpers import load_golden, serialize_trace


class LoadGoldenHappyPathTests(unittest.TestCase):
    def test_round_trip_serialize_then_load(self) -> None:
        entries = [
            TraceEntry(seq=0, channel="event", kind="StoryStarted", payload={"epic": "1"}),
            TraceEntry(seq=1, channel="state", kind="mutation", payload={"path": "state.json", "sha256": "abc"}),
            TraceEntry(seq=2, channel="claude_p", kind="invoke", payload={"argv": ["claude", "-p"]}),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.json"
            path.write_text(serialize_trace(entries), encoding="utf-8")
            loaded = load_golden(path)
        self.assertEqual(loaded, entries)

    def test_load_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text("[]\n", encoding="utf-8")
            loaded = load_golden(path)
        self.assertEqual(loaded, [])
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.LoadGoldenHappyPathTests -v`
Expected: FAIL — current `load_golden` raises `NotImplementedError`.

- [ ] **Step 3: Implement `load_golden`**

Add to the top-of-file imports (consolidated alongside existing ones):

```python
from pathlib import Path
from typing import cast
```

Then replace the `load_golden` stub in `tests/golden_trace_helpers.py` with:

```python
_VALID_CHANNELS: frozenset[str] = frozenset({"event", "state", "claude_p"})
_REQUIRED_KEYS: tuple[str, ...] = ("seq", "channel", "kind", "payload")


def load_golden(path: Path) -> list[TraceEntry]:
    """Parse a stored golden fixture into a list of TraceEntry (REQ-08).

    Raises GoldenTraceError on malformed JSON, non-list top-level value,
    non-dict entry, missing required keys, or unknown channel.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoldenTraceError(f"{path}: malformed JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise GoldenTraceError(
            f"{path}: top-level value must be a JSON array, got {type(raw).__name__}"
        )
    entries: list[TraceEntry] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise GoldenTraceError(
                f"{path}: entry #{idx} must be a JSON object, got {type(item).__name__}"
            )
        missing = [k for k in _REQUIRED_KEYS if k not in item]
        if missing:
            raise GoldenTraceError(
                f"{path}: entry #{idx} missing required keys: {missing}"
            )
        channel = item["channel"]
        if channel not in _VALID_CHANNELS:
            raise GoldenTraceError(
                f"{path}: entry #{idx} unknown channel {channel!r}; "
                f"expected one of {sorted(_VALID_CHANNELS)}"
            )
        payload = item["payload"]
        if not isinstance(payload, dict):
            raise GoldenTraceError(
                f"{path}: entry #{idx} payload must be an object, "
                f"got {type(payload).__name__}"
            )
        entries.append(
            TraceEntry(
                seq=int(item["seq"]),
                channel=cast(Channel, channel),
                kind=str(item["kind"]),
                payload=cast("dict[str, object]", dict(payload)),
            )
        )
    return entries
```

Note: the `int(...)` / `str(...)` runtime conversions narrow values coming out of `json.loads` (whose return type is `Any`). The two `cast(...)` calls are pure type-system narrowing — they do nothing at runtime but tell mypy `--strict` that `channel` is now a `Channel` `Literal` (validated by the `_VALID_CHANNELS` guard above) and that the dict has `str` keys and `object` values (a JSON object always has string keys). Without those casts, mypy `--strict` rejects the assignments because `dict(Any)` resolves to `dict[Any, Any]`.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.LoadGoldenHappyPathTests -v`
Expected: PASS for both cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10a): add load_golden round-trip parser"
```

---

## Task 8: `load_golden` rejects unknown channels and missing keys (REQ-08, full)

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class LoadGoldenRejectionTests(unittest.TestCase):
    def _write(self, body: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.write(body)
        tmp.close()
        path = Path(tmp.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_unknown_channel_raises(self) -> None:
        path = self._write(
            '[{"seq":0,"channel":"file","kind":"x","payload":{}}]'
        )
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("unknown channel", str(ctx.exception))
        self.assertIn("'file'", str(ctx.exception))

    def test_missing_seq_raises(self) -> None:
        path = self._write('[{"channel":"event","kind":"x","payload":{}}]')
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("seq", str(ctx.exception))

    def test_missing_payload_raises(self) -> None:
        path = self._write('[{"seq":0,"channel":"event","kind":"x"}]')
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("payload", str(ctx.exception))

    def test_top_level_not_a_list_raises(self) -> None:
        path = self._write('{"seq":0}')
        with self.assertRaises(GoldenTraceError):
            load_golden(path)

    def test_entry_not_a_dict_raises(self) -> None:
        path = self._write('["not-an-object"]')
        with self.assertRaises(GoldenTraceError):
            load_golden(path)

    def test_payload_not_a_dict_raises(self) -> None:
        path = self._write(
            '[{"seq":0,"channel":"event","kind":"x","payload":[]}]'
        )
        with self.assertRaises(GoldenTraceError):
            load_golden(path)

    def test_malformed_json_raises_golden_trace_error(self) -> None:
        path = self._write("not json at all")
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("malformed JSON", str(ctx.exception))
        # JSONDecodeError must be chained as __cause__ for diagnostics.
        self.assertIsInstance(ctx.exception.__cause__, json.JSONDecodeError)
```

Add `import json` at the top of the test file if not already present.

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.LoadGoldenRejectionTests -v`
Expected: PASS — the rejection paths were already implemented in Task 7. This task locks them in.

If any case fails, fix `load_golden` in `tests/golden_trace_helpers.py` until all pass — that's a sign Task 7's implementation was incomplete.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10a): cover load_golden rejection paths"
```

---

## Task 9: `compare_traces` happy path — equal lists yield `ok=True` (REQ-09)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
from tests.golden_trace_helpers import compare_traces


class CompareTracesEqualTests(unittest.TestCase):
    def test_identical_lists_yield_ok_true(self) -> None:
        entries = [
            TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1}),
            TraceEntry(seq=1, channel="state", kind="mutation", payload={"path": "p"}),
        ]
        # Deliberate copy to ensure object identity isn't being relied on.
        actual = [TraceEntry(seq=e.seq, channel=e.channel, kind=e.kind, payload=dict(e.payload)) for e in entries]
        diff = compare_traces(actual, entries)
        self.assertTrue(diff.ok)
        self.assertEqual(diff.matched, 2)
        self.assertEqual(diff.mismatches, [])

    def test_empty_lists_yield_ok_true(self) -> None:
        diff = compare_traces([], [])
        self.assertTrue(diff.ok)
        self.assertEqual(diff.matched, 0)
        self.assertEqual(diff.mismatches, [])

    def test_payload_key_order_irrelevant_for_equality(self) -> None:
        # Two payloads with the same keys/values but different insertion order
        # must compare equal (dict equality is order-insensitive, and we want
        # the byte-equal serialization to imply byte-equal comparison too).
        a = [TraceEntry(seq=0, channel="event", kind="X", payload={"a": 1, "b": 2})]
        g = [TraceEntry(seq=0, channel="event", kind="X", payload={"b": 2, "a": 1})]
        diff = compare_traces(a, g)
        self.assertTrue(diff.ok)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.CompareTracesEqualTests -v`
Expected: FAIL — `compare_traces` raises `NotImplementedError`.

- [ ] **Step 3: Implement minimal happy-path `compare_traces`**

Replace the `compare_traces` stub in `tests/golden_trace_helpers.py` with:

```python
def compare_traces(
    actual: list[TraceEntry], golden: list[TraceEntry]
) -> TraceDiff:
    """Positional comparison of two traces (REQ-09).

    Walks both lists in arrival order, recording a TraceMismatch at the
    first diverging field per index. Length divergence appends "length"
    mismatches for the tail of whichever list is longer.
    """
    mismatches: list[TraceMismatch] = []
    matched = 0
    common = min(len(actual), len(golden))
    for i in range(common):
        a = actual[i]
        g = golden[i]
        field = _first_diverging_field(a, g)
        if field is None:
            matched += 1
            continue
        mismatches.append(
            TraceMismatch(
                seq=i,
                field=field,
                actual=_field_value(a, field),
                expected=_field_value(g, field),
            )
        )
    # Tail-length mismatches (one side is longer).
    for i in range(common, len(actual)):
        mismatches.append(
            TraceMismatch(seq=i, field="length", actual=actual[i], expected=None)
        )
    for i in range(common, len(golden)):
        mismatches.append(
            TraceMismatch(seq=i, field="length", actual=None, expected=golden[i])
        )
    ok = not mismatches and len(actual) == len(golden)
    return TraceDiff(matched=matched, mismatches=mismatches, ok=ok)


def _first_diverging_field(
    a: TraceEntry, g: TraceEntry
) -> MismatchField | None:
    """Return the first field name where two entries differ, in the order
    channel -> kind -> payload. ``seq`` is the arrival index, not a value
    to compare. Returns None if entries are equal.
    """
    if a.channel != g.channel:
        return "channel"
    if a.kind != g.kind:
        return "kind"
    if a.payload != g.payload:
        return "payload"
    return None


def _field_value(entry: TraceEntry, field: MismatchField) -> object | None:
    """Look up the value of a diverging field for diagnostics."""
    if field == "channel":
        return entry.channel
    if field == "kind":
        return entry.kind
    if field == "payload":
        return entry.payload
    # "length" is handled by the caller (one side has no entry).
    return None
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.CompareTracesEqualTests -v`
Expected: PASS for all 3 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10a): add compare_traces happy path"
```

---

## Task 10: `compare_traces` field-level mismatch detection (REQ-09 / REQ-10)

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class CompareTracesFieldMismatchTests(unittest.TestCase):
    def _golden(self) -> list[TraceEntry]:
        return [
            TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1}),
            TraceEntry(seq=1, channel="event", kind="B", payload={"y": 2}),
            TraceEntry(seq=2, channel="state", kind="mutation", payload={"path": "p"}),
        ]

    def test_payload_regression_localized_to_specific_seq(self) -> None:
        golden = self._golden()
        actual = [
            golden[0],
            TraceEntry(seq=1, channel="event", kind="B", payload={"y": 99}),  # changed
            golden[2],
        ]
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.matched, 2)
        self.assertEqual(len(diff.mismatches), 1)
        m = diff.mismatches[0]
        self.assertEqual(m.seq, 1)
        self.assertEqual(m.field, "payload")
        self.assertEqual(m.actual, {"y": 99})
        self.assertEqual(m.expected, {"y": 2})

    def test_channel_mismatch_takes_priority_over_kind_and_payload(self) -> None:
        golden = [TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1})]
        actual = [TraceEntry(seq=0, channel="state", kind="Z", payload={"y": 9})]
        diff = compare_traces(actual, golden)
        self.assertEqual(len(diff.mismatches), 1)
        self.assertEqual(diff.mismatches[0].field, "channel")

    def test_kind_mismatch_when_channels_match(self) -> None:
        golden = [TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1})]
        actual = [TraceEntry(seq=0, channel="event", kind="B", payload={"x": 1})]
        diff = compare_traces(actual, golden)
        self.assertEqual(len(diff.mismatches), 1)
        self.assertEqual(diff.mismatches[0].field, "kind")
        self.assertEqual(diff.mismatches[0].actual, "B")
        self.assertEqual(diff.mismatches[0].expected, "A")

    def test_multiple_mismatches_one_per_seq(self) -> None:
        golden = self._golden()
        actual = [
            TraceEntry(seq=0, channel="event", kind="A", payload={"x": 99}),  # payload differs
            TraceEntry(seq=1, channel="state", kind="B", payload={"y": 2}),    # channel differs
            golden[2],
        ]
        diff = compare_traces(actual, golden)
        self.assertEqual(diff.matched, 1)
        self.assertEqual(len(diff.mismatches), 2)
        self.assertEqual([m.seq for m in diff.mismatches], [0, 1])
        self.assertEqual([m.field for m in diff.mismatches], ["payload", "channel"])
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.CompareTracesFieldMismatchTests -v`
Expected: PASS — implementation in Task 9 already handles these. This task locks the field-priority contract (channel > kind > payload).

If any test fails, the priority logic in `_first_diverging_field` is wrong — fix it before continuing. Do not relax the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10a): lock compare_traces field-priority contract"
```

---

## Task 11: `compare_traces` length mismatch (REQ-10 `"length"` field)

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class CompareTracesLengthMismatchTests(unittest.TestCase):
    def test_actual_longer_than_golden(self) -> None:
        golden = [TraceEntry(seq=0, channel="event", kind="A", payload={})]
        extra = TraceEntry(seq=1, channel="event", kind="B", payload={})
        actual = [golden[0], extra]
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.matched, 1)
        self.assertEqual(len(diff.mismatches), 1)
        m = diff.mismatches[0]
        self.assertEqual(m.seq, 1)
        self.assertEqual(m.field, "length")
        self.assertEqual(m.actual, extra)
        self.assertIsNone(m.expected)

    def test_golden_longer_than_actual(self) -> None:
        actual = [TraceEntry(seq=0, channel="event", kind="A", payload={})]
        missing = TraceEntry(seq=1, channel="event", kind="B", payload={})
        golden = [actual[0], missing]
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.matched, 1)
        self.assertEqual(len(diff.mismatches), 1)
        m = diff.mismatches[0]
        self.assertEqual(m.seq, 1)
        self.assertEqual(m.field, "length")
        self.assertIsNone(m.actual)
        self.assertEqual(m.expected, missing)

    def test_length_mismatch_with_prior_field_mismatch(self) -> None:
        actual = [
            TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1}),
        ]
        golden = [
            TraceEntry(seq=0, channel="event", kind="A", payload={"x": 2}),  # payload differs
            TraceEntry(seq=1, channel="event", kind="B", payload={}),         # missing in actual
        ]
        diff = compare_traces(actual, golden)
        self.assertEqual(diff.matched, 0)
        self.assertEqual(len(diff.mismatches), 2)
        # First mismatch is the payload diff at seq=0; second is the length
        # mismatch at seq=1 — ordering matters for diagnostics.
        self.assertEqual(diff.mismatches[0].field, "payload")
        self.assertEqual(diff.mismatches[0].seq, 0)
        self.assertEqual(diff.mismatches[1].field, "length")
        self.assertEqual(diff.mismatches[1].seq, 1)
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.CompareTracesLengthMismatchTests -v`
Expected: PASS — Task 9's implementation already handles tail-length mismatches.

If any case fails, fix the tail-handling loops in `compare_traces` until they pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10a): cover compare_traces length mismatches"
```

---

## Task 12: Diagnostics — `TraceDiff.summary()` localizes regressions (NFR)

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class TraceDiffSummaryIntegrationTests(unittest.TestCase):
    """End-to-end diagnostic check: produce a real diff, render its summary,
    confirm a reader can localize the regression without the golden file.
    """

    def test_summary_localizes_payload_regression(self) -> None:
        golden = [
            TraceEntry(seq=0, channel="event", kind="StoryStarted", payload={"epic": "1"}),
            TraceEntry(seq=1, channel="event", kind="StoryCompleted", payload={"cost_usd": 0.42}),
        ]
        actual = [
            golden[0],
            TraceEntry(seq=1, channel="event", kind="StoryCompleted", payload={"cost_usd": 0.99}),
        ]
        diff = compare_traces(actual, golden)
        text = diff.summary()
        # Channel + kind + the diverging payload values must all be present
        # so the reader can identify the regression without re-opening the
        # golden fixture (NFR: Diagnostics).
        self.assertIn("seq=1", text)
        self.assertIn("payload", text)
        self.assertIn("0.42", text)
        self.assertIn("0.99", text)

    def test_summary_localizes_length_mismatch(self) -> None:
        golden: list[TraceEntry] = []
        actual = [TraceEntry(seq=0, channel="event", kind="StoryStarted", payload={})]
        diff = compare_traces(actual, golden)
        text = diff.summary()
        self.assertIn("seq=0", text)
        self.assertIn("length", text)
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.TraceDiffSummaryIntegrationTests -v`
Expected: PASS — `TraceDiff.summary()` already includes seq, field, actual/expected per Task 5.

If the test fails, the `summary()` format in Task 5 omits a required diagnostic — extend the template to include it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10a): lock diagnostic summary contract"
```

---

## Task 13: Full suite green + ruff clean (REQ-15)

**Files:**
- (no source changes expected; fix only if a tool complains)

- [ ] **Step 1: Run the full M10a test set**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers -v
```

Expected: every `TestCase` from Tasks 1-12 passes. Count the cases — there should be roughly 30 in total. If anything fails, fix the underlying code, do not weaken the test.

- [ ] **Step 2: Run the existing project test suite (no regressions)**

Run:

```bash
npm run test:python
```

Expected: PASS. M10a touches only the new files; no shipped module should regress.

- [ ] **Step 3: Run ruff**

Run:

```bash
python -m ruff check tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
python -m ruff format --check tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
```

Expected: zero findings. If `ruff format --check` reports formatting drift, run `python -m ruff format tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py` and re-run the check.

- [ ] **Step 4: Commit if any formatting changes were made**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(m10a): ruff format"
```

If no formatting drift, skip this step — empty commits are not allowed by project convention.

---

## Task 14: `mypy --strict` clean (REQ-15)

**Files:**
- Modify: `tests/golden_trace_helpers.py` (only if mypy complains)

- [ ] **Step 1: Run mypy --strict against the helper module**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m mypy --strict tests/golden_trace_helpers.py
```

Expected: zero errors. The known narrowing-casts in `load_golden` (Task 7) — `cast(Channel, channel)` and `cast("dict[str, object]", dict(payload))` — should already satisfy mypy. Remaining likely findings and their fixes:

| mypy finding | fix |
|---|---|
| `Returning Any from function declared to return ...` on `json.loads(...)` result | The `isinstance(raw, list)` / `isinstance(item, dict)` narrowing should already cover this; if mypy still complains, add `cast("list[object]", raw)` after the `isinstance(raw, list)` check. |
| `Incompatible default for argument` | Don't introduce defaults — every dataclass field is required by spec. |
| `Need type annotation for "_VALID_CHANNELS"` | Already annotated as `frozenset[str]`; if mypy still flags, ensure the annotation appears on the same line as the assignment, not on a preceding `:` line. |
| Anything in `_first_diverging_field` / `_field_value` | Return type is `MismatchField \| None` / `object \| None`; ensure both helpers are annotated and that the `if/elif` chain is exhaustive (final `return None` line). |

If `mypy` is not installed in this environment, install it as a dev tool but do NOT add it to `pyproject.toml` dependencies — it's an operator-installed quality-gate tool, mirroring how `coverage` is treated.

```bash
python -m pip install --quiet mypy
```

- [ ] **Step 2: Apply fixes inline**

Edit `tests/golden_trace_helpers.py` only as needed to clear mypy findings. Do not silence with `# type: ignore` unless the underlying issue is a known stdlib stub limitation; in that case add an inline comment explaining why.

- [ ] **Step 3: Re-run mypy, confirm clean**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m mypy --strict tests/golden_trace_helpers.py`
Expected: `Success: no issues found in 1 source file`.

- [ ] **Step 4: Commit (only if fixes were applied)**

```bash
git add tests/golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "fix(m10a): satisfy mypy --strict"
```

If no fixes were needed, skip the commit.

---

## Task 15: Cross-platform smoke + final verification

**Files:**
- (no changes expected)

- [ ] **Step 1: Verify import has no side effects**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -c "import tests.golden_trace_helpers; print('ok')"
```

Expected: `ok` with no telemetry events, state mutations, or claude_p invocations. Since M10a does not install hooks (recorder lands in M10b), this should trivially hold — but verifying explicitly catches regressions like an accidental top-level `print` or module-level state setup.

- [ ] **Step 2: Re-run the full unittest sweep one final time**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v 2>&1 | tail -50
```

Expected: `OK` and no failures. Confirm that the count of M10a tests matches the sum from Tasks 1-12.

- [ ] **Step 3: No final commit required**

M10a is complete. Nothing further to commit; the milestone hands off to M10b (recorder + interception hooks) and M10c (golden fixtures + record-then-compare tests). No new branches needed.

---

## Self-review checklist (run before declaring done)

- [ ] **Spec coverage**
  - REQ-02 (`TraceEntry`): Task 3
  - REQ-07 (`serialize_trace`): Task 6
  - REQ-08 (`load_golden` + `GoldenTraceError`): Tasks 2, 7, 8
  - REQ-09 (`compare_traces` / `TraceDiff`): Tasks 5, 9, 10, 11
  - REQ-10 (`TraceMismatch` with `Literal` field + PEP 604 `object | None`): Task 4
  - REQ-15 (`__future__`, stdlib, ruff, mypy --strict): Tasks 1, 13, 14
  - NFR Determinism: Task 6 byte-equal tests
  - NFR Isolation: Task 1 import-no-side-effects test; the module has no module-level state
  - NFR Diagnostics: Tasks 5, 12 `TraceDiff.summary()` localization tests
- [ ] **Placeholders:** None. Every code block is concrete.
- [ ] **Type consistency:** `Channel`, `MismatchField`, `TraceEntry`, `TraceMismatch`, `TraceDiff`, `GoldenTraceError`, `compare_traces`, `load_golden`, `serialize_trace` names match across all tasks.
- [ ] **Scope guard:** No task touches `TelemetryEmitter`, `commands/state.py`, `claude_p` invocation, threading locks, redaction logic, or golden fixture files. Those are explicitly M10b/M10c.
