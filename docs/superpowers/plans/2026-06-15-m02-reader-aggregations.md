# M02 Reader and Aggregations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the streaming `TelemetryReader` over the M01 typed-event JSONL produced by the M02 emitter, plus the three typed aggregations (`cost_by_epic`, `attempts_by_story`, `retro_inputs`) that downstream milestones (M03 cost, M06 retry engine, M09 retro summaries) depend on.

**Architecture:**
- New module `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py` exports a single class `TelemetryReader(path)`.
- `iter_events()` opens the file once with `open(..., encoding="utf-8")` inside a `with`-context, iterates line-by-line (so the OS streams from disk — no full-file buffering), strips the trailing `\n`, silently skips lines whose `.strip()` is empty (REQ-07 blank-line skip), and dispatches each remaining line through `parse_event` from `story_automator.core.telemetry_events`. `json.JSONDecodeError` (and any other parse exception) propagates — corruption is loud, not silent (REQ-07).
- Missing file: `iter_events` early-returns an empty generator via an `is_file()` guard at the top before opening anything; the caller sees an empty iterator, not `FileNotFoundError` (REQ-07).
- The three aggregations each call `iter_events()` exactly once and filter by `isinstance` on the M01 typed classes (`CostCharged`, `RetryAttempt`, `RetroFired`). `UnknownEvent` and other event types are skipped silently per rollup (REQ-08).
- `retro_inputs(epic)` walks every matching `RetroFired` and returns the **last** one in file order (the file is append-only, so file-order = chronological for events emitted on the same emitter; spec calls this "most recent"). Returns `{}` when no event matches.
- Tests use `tempfile.TemporaryDirectory` exclusively, never touch tmux/subprocess, and the round-trip integration test goes through the real `TelemetryEmitter` (M02 emitter, already landed in this worktree) to lock down the emit→read contract for all 13 M01 event types.

**Tech Stack:** Python 3.11+ stdlib (`json`, `pathlib`, `tempfile`, `unittest`, `collections.abc.Iterator`, `typing.Any`). No new third-party deps — `filelock`/`psutil` are emitter-side only. The reader imports `parse_event` and the typed event classes from `story_automator.core.telemetry_events` (M01-landed).

**Open interpretations (flagged for review):**
- REQ-08 says "most recent `RetroFired` event matching the supplied epic". The reader interprets "most recent" as **last-in-file**, since the JSONL stream is append-only. We do NOT parse the `timestamp` field and compare lexicographically — that would (a) silently break if a producer writes a non-RFC3339 timestamp and (b) is not in scope for M02. Tests codify this last-in-file-wins interpretation.
- `iter_events()` yields every parsed event including `UnknownEvent`. Aggregations skip non-target types via `isinstance` — including `UnknownEvent`, by design. This means a future event type the reader doesn't recognize yet won't be silently dropped from `iter_events()` (forward-compat preserved) but also won't contribute to today's three rollups.
- Path argument: the spec allows `str | Path`. Constructor normalizes to `pathlib.Path` once and stores it; all subsequent IO uses the `Path`. No env-var defaults, no project-root resolution — the caller decides.

---

## Task 1: TelemetryReader scaffolding + missing/empty file tests

**Files:**
- Create: `tests/test_telemetry_reader.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_telemetry_reader.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.telemetry_reader import TelemetryReader


class TelemetryReaderMissingFileTests(unittest.TestCase):
    def test_iter_events_on_missing_file_yields_nothing(self) -> None:
        # REQ-07: missing file returns empty iterator, not FileNotFoundError.
        with tempfile.TemporaryDirectory() as tmp:
            reader = TelemetryReader(Path(tmp) / "nope.jsonl")
            self.assertEqual(list(reader.iter_events()), [])

    def test_iter_events_on_empty_file_yields_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.touch()
            reader = TelemetryReader(path)
            self.assertEqual(list(reader.iter_events()), [])

    def test_constructor_accepts_str_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reader = TelemetryReader(f"{tmp}/events.jsonl")
            self.assertIsInstance(reader, TelemetryReader)

    def test_constructor_accepts_pathlib_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reader = TelemetryReader(Path(tmp) / "events.jsonl")
            self.assertIsInstance(reader, TelemetryReader)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'story_automator.core.telemetry_reader'`

- [ ] **Step 3: Implement the minimal reader**

```python
# skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
"""Streaming TelemetryReader over M02 JSONL output.

REQ-06..REQ-08. Reads the file line-by-line and dispatches each non-
blank line through ``parse_event`` from
``story_automator.core.telemetry_events``. Aggregations filter by
``isinstance`` on the typed M01 classes so untyped or unknown lines are
ignored by rollups even though ``iter_events`` still yields them.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .telemetry_events import Event, parse_event


class TelemetryReader:
    def __init__(self, path: str | Path) -> None:
        self._path: Path = Path(path)

    def iter_events(self) -> Iterator[Event]:
        if not self._path.is_file():
            return
        with open(self._path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                yield parse_event(line)


__all__ = ["TelemetryReader"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: PASS — all four scaffolding tests green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_reader.py skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryReader scaffolding + missing/empty file handling"
```

---

## Task 2: Blank-line skip + malformed-line propagation + streaming

**Files:**
- Modify: `tests/test_telemetry_reader.py` (add test class)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_telemetry_reader.py`:

```python
from story_automator.core.telemetry_events import StoryStarted


class TelemetryReaderLineHandlingTests(unittest.TestCase):
    def test_blank_lines_are_skipped(self) -> None:
        # REQ-07/REQ-12: blank lines on read are silently skipped.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            line = json.dumps(
                {
                    "event_type": "story_started",
                    "timestamp": "t",
                    "run_id": "r",
                    "epic": "E",
                    "story_key": "S",
                    "agent": "a",
                    "model": "m",
                    "complexity": "c",
                }
            )
            path.write_text(f"\n{line}\n\n  \n{line}\n", encoding="utf-8")
            reader = TelemetryReader(path)
            events = list(reader.iter_events())
            self.assertEqual(len(events), 2)
            self.assertTrue(all(isinstance(e, StoryStarted) for e in events))

    def test_malformed_line_propagates_json_decode_error(self) -> None:
        # REQ-07: corruption is loud, not silent.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("{not json\n", encoding="utf-8")
            reader = TelemetryReader(path)
            with self.assertRaises(json.JSONDecodeError):
                list(reader.iter_events())

    def test_iter_events_does_not_buffer_full_file(self) -> None:
        # NFR: streaming — iter_events must be a generator that produces
        # events one at a time. Verify by taking only the first event
        # from a file with many lines; the generator stays paused.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            line = json.dumps(
                {
                    "event_type": "story_started",
                    "timestamp": "t",
                    "run_id": "r",
                    "epic": "E",
                    "story_key": "S",
                    "agent": "a",
                    "model": "m",
                    "complexity": "c",
                }
            )
            path.write_text((line + "\n") * 1000, encoding="utf-8")
            reader = TelemetryReader(path)
            it = reader.iter_events()
            first = next(it)
            self.assertIsInstance(first, StoryStarted)
            # Drop refs so the temp dir can be cleaned on Windows.
            del it
            del reader
```

- [ ] **Step 2: Run tests to verify**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: PASS — Task 1's implementation already covers blank-line skip (`.strip()` guard) and propagates `json.JSONDecodeError` via `parse_event`. The streaming test passes because `iter_events` is a `yield`-based generator. If any fail, the implementation in Task 1 had a bug; fix in-place before committing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): reader blank-line skip, malformed propagation, streaming"
```

---

## Task 3: cost_by_epic aggregation — failing test

**Files:**
- Modify: `tests/test_telemetry_reader.py` (add test class)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_telemetry_reader.py`:

```python
class TelemetryReaderCostByEpicTests(unittest.TestCase):
    def _write(self, path: Path, events: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def test_cost_by_epic_sums_only_cost_charged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(
                path,
                [
                    {
                        "event_type": "cost_charged", "timestamp": "t", "run_id": "r",
                        "epic": "E1", "story_key": "S1", "phase": "dev",
                        "cost_usd": 0.10, "tokens_in": 10, "tokens_out": 20, "model": "m",
                    },
                    {
                        "event_type": "cost_charged", "timestamp": "t", "run_id": "r",
                        "epic": "E1", "story_key": "S2", "phase": "dev",
                        "cost_usd": 0.25, "tokens_in": 10, "tokens_out": 20, "model": "m",
                    },
                    {
                        "event_type": "cost_charged", "timestamp": "t", "run_id": "r",
                        "epic": "E2", "story_key": "S3", "phase": "dev",
                        "cost_usd": 1.00, "tokens_in": 10, "tokens_out": 20, "model": "m",
                    },
                    # Non-cost event must NOT contribute (REQ-13 mixed case):
                    {
                        "event_type": "story_started", "timestamp": "t", "run_id": "r",
                        "epic": "E1", "story_key": "Sx",
                        "agent": "a", "model": "m", "complexity": "c",
                    },
                ],
            )
            reader = TelemetryReader(path)
            result = reader.cost_by_epic()
            self.assertEqual(set(result.keys()), {"E1", "E2"})
            self.assertAlmostEqual(result["E1"], 0.35, places=6)
            self.assertAlmostEqual(result["E2"], 1.00, places=6)

    def test_cost_by_epic_returns_empty_when_no_cost_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(
                path,
                [
                    {
                        "event_type": "story_started", "timestamp": "t", "run_id": "r",
                        "epic": "E1", "story_key": "S",
                        "agent": "a", "model": "m", "complexity": "c",
                    },
                ],
            )
            self.assertEqual(TelemetryReader(path).cost_by_epic(), {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: FAIL with `AttributeError: 'TelemetryReader' object has no attribute 'cost_by_epic'`.

---

## Task 4: cost_by_epic aggregation — implement

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`

- [ ] **Step 1: Add `CostCharged` to imports and implement method**

Update imports:

```python
from .telemetry_events import CostCharged, Event, parse_event
```

Append method to the `TelemetryReader` class:

```python
    def cost_by_epic(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for event in self.iter_events():
            if isinstance(event, CostCharged):
                totals[event.epic] = totals.get(event.epic, 0.0) + event.cost_usd
        return totals
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: PASS for all `TelemetryReaderCostByEpicTests`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_reader.py skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryReader.cost_by_epic aggregation"
```

---

## Task 5: attempts_by_story aggregation — failing test

**Files:**
- Modify: `tests/test_telemetry_reader.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
class TelemetryReaderAttemptsByStoryTests(unittest.TestCase):
    def _write(self, path: Path, events: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def test_attempts_by_story_counts_retry_attempt_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(
                path,
                [
                    {
                        "event_type": "retry_attempt", "timestamp": "t", "run_id": "r",
                        "epic": "E1", "story_key": "S1", "attempt_num": 2,
                        "agent": "a", "model": "m", "prev_error_class": "x",
                    },
                    {
                        "event_type": "retry_attempt", "timestamp": "t", "run_id": "r",
                        "epic": "E1", "story_key": "S1", "attempt_num": 3,
                        "agent": "a", "model": "m", "prev_error_class": "x",
                    },
                    {
                        "event_type": "retry_attempt", "timestamp": "t", "run_id": "r",
                        "epic": "E2", "story_key": "S9", "attempt_num": 2,
                        "agent": "a", "model": "m", "prev_error_class": "x",
                    },
                    # Other types must NOT contribute (REQ-13 mixed):
                    {
                        "event_type": "cost_charged", "timestamp": "t", "run_id": "r",
                        "epic": "E1", "story_key": "S1", "phase": "dev",
                        "cost_usd": 0.01, "tokens_in": 1, "tokens_out": 1, "model": "m",
                    },
                ],
            )
            reader = TelemetryReader(path)
            result = reader.attempts_by_story()
            self.assertEqual(result, {("E1", "S1"): 2, ("E2", "S9"): 1})

    def test_attempts_by_story_empty_when_no_retry_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.touch()
            self.assertEqual(TelemetryReader(path).attempts_by_story(), {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: FAIL with `AttributeError: 'TelemetryReader' object has no attribute 'attempts_by_story'`.

---

## Task 6: attempts_by_story aggregation — implement

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`

- [ ] **Step 1: Add `RetryAttempt` to imports and implement method**

Update imports:

```python
from .telemetry_events import CostCharged, Event, RetryAttempt, parse_event
```

Append method to `TelemetryReader`:

```python
    def attempts_by_story(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for event in self.iter_events():
            if isinstance(event, RetryAttempt):
                key = (event.epic, event.story_key)
                counts[key] = counts.get(key, 0) + 1
        return counts
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_reader.py skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryReader.attempts_by_story aggregation"
```

---

## Task 7: retro_inputs aggregation — failing test (most-recent-wins per epic)

**Files:**
- Modify: `tests/test_telemetry_reader.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
class TelemetryReaderRetroInputsTests(unittest.TestCase):
    def _write(self, path: Path, events: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def test_retro_inputs_returns_most_recent_match(self) -> None:
        # REQ-08: "most recent RetroFired event matching the supplied epic"
        # Most recent = last in file order (file is append-only).
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(
                path,
                [
                    {
                        "event_type": "retro_fired", "timestamp": "2026-06-13T00:00:00Z",
                        "run_id": "r", "epic": "E1",
                        "stories_completed": 1, "total_cost_usd": 0.5, "duration_s": 30.0,
                    },
                    {
                        "event_type": "retro_fired", "timestamp": "2026-06-14T00:00:00Z",
                        "run_id": "r", "epic": "E1",
                        "stories_completed": 4, "total_cost_usd": 2.0, "duration_s": 120.0,
                    },
                    {
                        "event_type": "retro_fired", "timestamp": "2026-06-14T00:00:00Z",
                        "run_id": "r", "epic": "E2",
                        "stories_completed": 7, "total_cost_usd": 3.0, "duration_s": 60.0,
                    },
                ],
            )
            reader = TelemetryReader(path)
            result = reader.retro_inputs("E1")
            self.assertEqual(
                result,
                {"stories_completed": 4, "total_cost_usd": 2.0, "duration_s": 120.0},
            )

    def test_retro_inputs_returns_empty_dict_when_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(
                path,
                [
                    {
                        "event_type": "retro_fired", "timestamp": "t", "run_id": "r",
                        "epic": "E1",
                        "stories_completed": 1, "total_cost_usd": 0.5, "duration_s": 30.0,
                    },
                ],
            )
            self.assertEqual(TelemetryReader(path).retro_inputs("E_other"), {})

    def test_retro_inputs_returns_empty_when_no_retro_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.touch()
            self.assertEqual(TelemetryReader(path).retro_inputs("E1"), {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: FAIL with `AttributeError: 'TelemetryReader' object has no attribute 'retro_inputs'`.

---

## Task 8: retro_inputs aggregation — implement

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`

- [ ] **Step 1: Add `RetroFired` and `typing.Any` to imports, implement method**

Update imports:

```python
from typing import Any

from .telemetry_events import CostCharged, Event, RetroFired, RetryAttempt, parse_event
```

Append method to `TelemetryReader`:

```python
    def retro_inputs(self, epic: str) -> dict[str, Any]:
        latest: RetroFired | None = None
        for event in self.iter_events():
            if isinstance(event, RetroFired) and event.epic == epic:
                latest = event
        if latest is None:
            return {}
        return {
            "stories_completed": latest.stories_completed,
            "total_cost_usd": latest.total_cost_usd,
            "duration_s": latest.duration_s,
        }
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: PASS — all reader tests green.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_reader.py skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryReader.retro_inputs (most-recent-wins per epic)"
```

---

## Task 9: Mixed-event integration via real TelemetryEmitter

**Files:**
- Modify: `tests/test_telemetry_reader.py`

- [ ] **Step 1: Write the integration test**

Append:

```python
from story_automator.core.telemetry_events import (
    CostCharged,
    RetroFired,
    RetryAttempt,
)


class TelemetryReaderEmitReadIntegrationTests(unittest.TestCase):
    def test_mixed_events_aggregations_only_count_relevant_types(self) -> None:
        # REQ-13 mixed-event case: only relevant types contribute to
        # each rollup. Go through the real TelemetryEmitter to lock the
        # M02 emit→read contract.
        from story_automator.core.telemetry_emitter import TelemetryEmitter

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            em = TelemetryEmitter(path)
            em.emit(StoryStarted(
                timestamp="t", run_id="r", epic="E1", story_key="S1",
                agent="a", model="m", complexity="c",
            ))
            em.emit(CostCharged(
                timestamp="t", run_id="r", epic="E1", story_key="S1",
                phase="dev", cost_usd=0.5, tokens_in=1, tokens_out=1, model="m",
            ))
            em.emit(RetryAttempt(
                timestamp="t", run_id="r", epic="E1", story_key="S1",
                attempt_num=2, agent="a", model="m", prev_error_class="x",
            ))
            em.emit(RetroFired(
                timestamp="t", run_id="r", epic="E1",
                stories_completed=2, total_cost_usd=0.5, duration_s=60.0,
            ))
            reader = TelemetryReader(path)
            self.assertEqual(reader.cost_by_epic(), {"E1": 0.5})
            self.assertEqual(reader.attempts_by_story(), {("E1", "S1"): 1})
            self.assertEqual(
                reader.retro_inputs("E1"),
                {"stories_completed": 2, "total_cost_usd": 0.5, "duration_s": 60.0},
            )
```

- [ ] **Step 2: Run test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader.TelemetryReaderEmitReadIntegrationTests -v`
Expected: PASS — emit→read round-trip across mixed event types correctly isolates each aggregation.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): emit→read integration over mixed event types"
```

---

## Task 10: Round-trip for all 13 M01 event types

**Files:**
- Modify: `tests/test_telemetry_emitter.py`

- [ ] **Step 1: Write the round-trip test**

REQ-12 requires "the round-trip equivalence of every M01 event type through emit then read." Add to `tests/test_telemetry_emitter.py` (alongside the existing emitter tests):

```python
class TelemetryEmitterRoundTripTests(unittest.TestCase):
    def test_all_13_m01_events_round_trip_through_emit_and_parse(self) -> None:
        # REQ-12 round-trip: emit each M01 typed event, read back via
        # parse_event, assert the parsed object equals the original.
        from story_automator.core.telemetry_emitter import TelemetryEmitter
        from story_automator.core.telemetry_events import (
            BudgetAlert,
            CostCharged,
            EscalationTriggered,
            RetroFired,
            RetryAttempt,
            ReviewCycle,
            StoryCompleted,
            StoryDeferred,
            StoryFailed,
            StoryStarted,
            TmuxSessionCompleted,
            TmuxSessionCrashed,
            TmuxSessionSpawned,
            parse_event,
        )

        originals = [
            StoryStarted(timestamp="t", run_id="r", epic="E", story_key="S",
                         agent="a", model="m", complexity="c"),
            StoryCompleted(timestamp="t", run_id="r", epic="E", story_key="S",
                           duration_s=1.0, cost_usd=0.1, tokens_in=1, tokens_out=1,
                           attempts=1),
            StoryFailed(timestamp="t", run_id="r", epic="E", story_key="S",
                        error_class="x", reason="r", attempts=5, final_session="sess"),
            StoryDeferred(timestamp="t", run_id="r", epic="E", story_key="S",
                          reason="r", tasks_completed=3),
            RetryAttempt(timestamp="t", run_id="r", epic="E", story_key="S",
                         attempt_num=2, agent="a", model="m", prev_error_class="x"),
            EscalationTriggered(timestamp="t", run_id="r", epic="E", story_key="S",
                                trigger_id=1, severity="warn", message="msg"),
            ReviewCycle(timestamp="t", run_id="r", epic="E", story_key="S",
                        cycle_num=1, issues_found=0, blocking=False),
            RetroFired(timestamp="t", run_id="r", epic="E",
                       stories_completed=1, total_cost_usd=0.1, duration_s=1.0),
            TmuxSessionSpawned(timestamp="t", run_id="r",
                               session_name="x", story_key="S", pid=1, pane_geometry="80x24"),
            TmuxSessionCompleted(timestamp="t", run_id="r",
                                 session_name="x", story_key="S",
                                 exit_code=0, duration_s=1.0),
            TmuxSessionCrashed(timestamp="t", run_id="r",
                               session_name="x", story_key="S",
                               exit_code=137, last_capture_chars=4096),
            CostCharged(timestamp="t", run_id="r", epic="E", story_key="S",
                        phase="dev", cost_usd=0.1, tokens_in=1, tokens_out=2, model="m"),
            BudgetAlert(timestamp="t", run_id="r", threshold_pct=75,
                        total_cost_usd=7.5, max_budget_usd=10.0,
                        epic="E", story_key="S"),
        ]
        self.assertEqual(len(originals), 13)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            em = TelemetryEmitter(path)
            for ev in originals:
                em.emit(ev)
            with open(path, encoding="utf-8") as fh:
                lines = [ln for ln in fh.read().splitlines() if ln.strip()]
            self.assertEqual(len(lines), 13)
            parsed = [parse_event(ln) for ln in lines]
            for original, after in zip(originals, parsed, strict=True):
                self.assertEqual(type(original), type(after))
                self.assertEqual(original, after)
```

- [ ] **Step 2: Run test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterRoundTripTests -v`
Expected: PASS. If any event type fails equality (e.g. a field name mismatch with the M01 dataclass), surface the diff — do NOT mutate the M01 dataclass in this milestone; the failure means the round-trip test has the wrong field set, fix the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_emitter.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): emit→parse round-trip for all 13 M01 event types"
```

---

## Task 11: Lint and format gates

**Files:**
- All M02 files.

- [ ] **Step 1: Run ruff check on the four M02 paths**

Run:

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py \
  tests/test_telemetry_reader.py \
  tests/test_telemetry_emitter.py
```

Expected: zero violations. If any, fix in-place without adding `# noqa` or new disables in `pyproject.toml`.

- [ ] **Step 2: Run ruff format check**

Run:

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py \
  tests/test_telemetry_reader.py \
  tests/test_telemetry_emitter.py
```

Expected: zero files needing reformat. If any, run `python -m ruff format <path>` and re-commit.

- [ ] **Step 3: Commit any fixes**

If fixes were needed:

```bash
git add -A
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(telemetry): ruff check + format on M02 reader paths"
```

If no fixes were needed: skip the commit — do NOT create an empty commit.

---

## Task 12: Coverage gate (>=85% per spec, target 100% per CLAUDE.md)

**Files:**
- All M02 files.

- [ ] **Step 1: Run coverage on the reader module**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/telemetry_reader \
  -m unittest tests.test_telemetry_reader
PYTHONPATH=skills/bmad-story-automator/src python -m coverage report -m --fail-under=85
```

Expected: coverage report shows `telemetry_reader.py` at >=85% (target 100%); `coverage report` exits 0.

- [ ] **Step 2: If <100%, identify and cover the missing lines**

Open the `Missing` column in the coverage report; for each missing line, write a targeted unit test in `tests/test_telemetry_reader.py` and re-run.

- [ ] **Step 3: Run combined coverage on emitter + reader**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/telemetry_emitter,skills/bmad-story-automator/src/story_automator/core/telemetry_reader \
  -m unittest tests.test_telemetry_emitter tests.test_telemetry_reader
PYTHONPATH=skills/bmad-story-automator/src python -m coverage report -m --fail-under=85
```

Expected: both modules at >=85%, gate passes.

- [ ] **Step 4: Commit if new tests were added**

```bash
git add tests/test_telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): cover remaining branches in TelemetryReader"
```

---

## Task 13: Import allowlist + module size + full suite gates

**Files:**
- Both new modules; the full test suite.

- [ ] **Step 1: Allowlist grep on the reader module**

Run (Git Bash / Linux):

```bash
git grep -nE "^(import|from) " -- skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
```

Or via the agent's `Grep` tool with `pattern="^(import|from) "` and `path=skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`, `output_mode="content"`, `-n=true`.

Expected output (allowlist = stdlib + `filelock` + `psutil` + local):

- `from __future__ import annotations`
- `from collections.abc import Iterator`
- `from pathlib import Path`
- `from typing import Any`
- `from .telemetry_events import CostCharged, Event, RetroFired, RetryAttempt, parse_event`

Zero third-party imports outside `filelock`/`psutil`. (The reader uses neither — pure stdlib is fine.)

- [ ] **Step 2: Module size gate**

Run:

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
```

Expected: well under 500 LOC (target <100; current shape is ~70).

- [ ] **Step 3: Full repo test suite stays green**

Run: `npm run test:python`
Expected: all tests pass — M01 tests still green, both M02 test files green.

- [ ] **Step 4: No commit needed**

These are gate checks; no source change. If a gate failed (rare), open a focused fix commit:

```bash
git add -A
git commit --trailer "Generated-By: claude-opus-4-7" -m "fix(telemetry): tighten <which gate>"
```

---

## Task 14: Final convergence — verify all M02 quality gates green

**Files:**
- None (verification only).

- [ ] **Step 1: Run the full M02 quality-gate sweep**

Run each of these and confirm exit 0:

```bash
# lint
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py \
  skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py \
  tests/test_telemetry_emitter.py \
  tests/test_telemetry_reader.py

# format
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py \
  skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py \
  tests/test_telemetry_emitter.py \
  tests/test_telemetry_reader.py

# full suite
npm run test:python

# coverage
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/telemetry_emitter,skills/bmad-story-automator/src/story_automator/core/telemetry_reader \
  -m unittest tests.test_telemetry_emitter tests.test_telemetry_reader
PYTHONPATH=skills/bmad-story-automator/src python -m coverage report -m --fail-under=85
```

Expected: every command exits 0; coverage report ≥85% (target 100%) on both modules.

- [ ] **Step 2: Tag the milestone in the commit log**

Inspect `git log --oneline | head -20` and confirm the milestone commits land in a clean linear history with Conventional Commits.

- [ ] **Step 3: No commit unless a gate failed and was fixed.**

---

## Self-review notes

- **REQ-06 coverage:** Tasks 1–2 (constructor + `iter_events`).
- **REQ-07 coverage:** Tasks 1 (missing/empty file), 2 (blank-line skip + JSONDecodeError propagation).
- **REQ-08 coverage:** Tasks 3–8 (three aggregations).
- **REQ-12 partial (blank-line + round-trip):** Tasks 2 and 10.
- **REQ-13 coverage:** Tasks 1 (missing/empty), 2 (malformed), 3/5 (each rollup), 9 (mixed-event integration).
- **REQ-14 (import allowlist):** Task 13 step 1.
- **REQ-15 (no helper duplication):** the reader does NOT need `iso_now`/`compact_json`/`ensure_dir` — confirmed by Task 13 step 1's import list. Listed in REQ-15 only "where needed"; reader has no need, so non-import is correct, not a gap.
- **NFRs:** PEP 604 unions throughout (`str | Path`, `dict[str, float]`); `from __future__ import annotations` at the top; streaming verified by Task 2 step 1's 1000-line test; cross-platform via `tempfile.TemporaryDirectory` and no subprocess/tmux; <500 LOC verified by Task 13 step 2.
- **Quality gates:** Task 11 (lint+format), Task 12 (coverage), Task 13 (allowlist+size+suite), Task 14 (sweep).
