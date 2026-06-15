# M02 Telemetry Emitter and Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the `TelemetryEmitter` (cross-process-locked JSONL append + fsync + run_id stamping), the streaming `TelemetryReader` (typed aggregations over the M01 event vocabulary), and the wiring of the existing orchestrator and tmux runtime hook points so every lifecycle moment writes a typed M01 event.

**Architecture:**
- `core/telemetry_emitter.py` exports `TelemetryEmitter(path, run_id=None)`. `emit(event)` acquires a `threading.Lock` for the instance, then a `filelock.FileLock` on `<path>.lock`, appends `event.to_json_line() + "\n"`, fsyncs the fd, and releases both locks. Parent dir is lazily created via `ensure_dir`. If `run_id` was supplied to the ctor and `event.run_id` is empty, the emitter stamps it before serializing.
- `core/telemetry_reader.py` exports `TelemetryReader(path)`. `iter_events()` is a generator that opens the file once and yields one `parse_event(line)` per non-blank line; missing file yields nothing. Three aggregations (`cost_by_epic`, `attempts_by_story`, `retro_inputs`) drive `iter_events` once per call and filter by `isinstance` on the M01 typed classes.
- Wiring: the spec's REQ-09/10/11 say "replace existing log sites." The current Python port has no `print`/`logger` calls at the named hook points — the lifecycle moments exist as control-flow checkpoints (e.g. `spawn_session` return, `pane_status` transitioning to `crashed:*`, `retro_agent_action` entry). The wiring inserts `TelemetryEmitter.emit` at those natural hook points. The telemetry path is `Path(get_project_root()) / "telemetry" / "events.jsonl"`. Emitters are CACHED per absolute path via a module-level dict in each wiring file. This is required for REQ-03's `threading.Lock` to actually serialize concurrent emits from the same process — a fresh per-call emitter would have a fresh threading.Lock, defeating in-process serialization. The cache key is the resolved absolute Path; the `filelock.FileLock` (which is path-keyed and re-entrant per process) survives across cache hits.
- Tests use `tempfile.TemporaryDirectory` and never touch tmux/subprocess. The multi-thread stress test uses `threading.Thread`, not multiprocessing, to keep the cross-platform contract.

**Tech Stack:** Python 3.11+ stdlib (`json`, `os`, `threading`, `pathlib`, `tempfile`, `unittest`, `dataclasses`), `filelock` (already in the allowlist), plus the M01-landed `story_automator.core.telemetry_events` and `story_automator.core.common`.

**Open interpretations (flagged for review):**
- REQ-09/10/11 say "replace existing log lines"; no such free-form log lines exist in the current code. The plan inserts emits at the lifecycle hook points (interpreting by intent). Tasks 17/18/19 enumerate the exact insertion sites.
- Telemetry path default is `<project_root>/telemetry/events.jsonl`. The spec leaves the path to the caller; this is the wiring's choice and is overridable by passing a different `path` to the emitter ctor.
- `run_id` plumbing: wiring sites pass `run_id=""` for now; the marker-derived run id is M05+ scope. Empty `run_id` stays empty (the emitter only stamps when it has a non-empty ctor run_id).

---

## Task 1: Test-failing TelemetryEmitter scaffolding

**Files:**
- Create: `tests/test_telemetry_emitter.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py` (in Task 2)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telemetry_emitter.py
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_events import (
    BudgetAlert,
    CostCharged,
    EscalationTriggered,
    Event,
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


class TelemetryEmitterScaffoldTests(unittest.TestCase):
    def test_constructor_accepts_str_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(os.path.join(tmp, "events.jsonl"))
            self.assertIsInstance(emitter, TelemetryEmitter)

    def test_constructor_accepts_pathlib_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            self.assertIsInstance(emitter, TelemetryEmitter)

    def test_constructor_accepts_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl", run_id="run-1")
            self.assertIsInstance(emitter, TelemetryEmitter)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'story_automator.core.telemetry_emitter'`.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_telemetry_emitter.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): scaffold TelemetryEmitter ctor tests (failing)"
```

---

## Task 2: TelemetryEmitter scaffolding implementation

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py`

- [ ] **Step 1: Write the minimal module**

```python
# skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py
"""Cross-process safe append-only JSONL emitter for M01 typed events.

REQ-01..REQ-05 + REQ-14/15. Uses ``filelock.FileLock`` on ``<path>.lock``
plus an instance-level ``threading.Lock`` to serialize concurrent emits.
``os.fsync`` runs before either lock is released so a crash between
emits cannot leave a partial line. Parent dir is lazily created on
first emit via ``ensure_dir`` from ``story_automator.core.common``.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from filelock import FileLock

from .common import ensure_dir
from .telemetry_events import Event


class TelemetryEmitter:
    def __init__(self, path: str | Path, run_id: str | None = None) -> None:
        self._path: Path = Path(path)
        self._lock_path: Path = self._path.with_name(self._path.name + ".lock")
        self._run_id: str | None = run_id
        self._thread_lock: threading.Lock = threading.Lock()
        self._file_lock: FileLock = FileLock(str(self._lock_path))

    def emit(self, event: Event) -> None:
        raise NotImplementedError


__all__ = ["TelemetryEmitter"]
```

- [ ] **Step 2: Run test to verify scaffolding passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterScaffoldTests -v`
Expected: PASS (3/3).

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryEmitter scaffolding (ctor only)"
```

---

## Task 3: Single-event emit produces JSONL line with trailing newline

**Files:**
- Modify: `tests/test_telemetry_emitter.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_telemetry_emitter.py`:

```python
class TelemetryEmitterAppendTests(unittest.TestCase):
    def test_single_emit_writes_one_jsonl_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            event = StoryStarted(
                timestamp="2026-06-14T00:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                agent="claude",
                model="sonnet",
                complexity="medium",
            )
            emitter.emit(event)
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.endswith("\n"))
            self.assertEqual(content.count("\n"), 1)
            payload = json.loads(content.rstrip("\n"))
            self.assertEqual(payload["event_type"], "story_started")
            self.assertEqual(payload["epic"], "E1")

    def test_multi_emit_appends_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            for i in range(5):
                emitter.emit(StoryStarted(
                    timestamp="2026-06-14T00:00:00Z",
                    run_id="r",
                    epic="E",
                    story_key=f"S{i}",
                    agent="claude",
                    model="sonnet",
                    complexity="low",
                ))
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 5)
            keys = [json.loads(line)["story_key"] for line in lines]
            self.assertEqual(keys, ["S0", "S1", "S2", "S3", "S4"])

    def test_emit_lazily_creates_parent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "nested" / "events.jsonl"
            self.assertFalse(path.parent.exists())
            emitter = TelemetryEmitter(path)
            emitter.emit(StoryStarted(
                timestamp="t", run_id="r", epic="E", story_key="S",
                agent="a", model="m", complexity="c",
            ))
            self.assertTrue(path.parent.is_dir())
            self.assertTrue(path.is_file())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterAppendTests -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement emit (no locks yet, fsync yet — minimal pass)**

Replace the body of `emit` in `telemetry_emitter.py`:

```python
    def emit(self, event: Event) -> None:
        ensure_dir(self._path.parent)
        line = event.to_json_line() + "\n"
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterAppendTests -v`
Expected: PASS (3/3).

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_emitter.py skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryEmitter.emit append + fsync + lazy dir create"
```

---

## Task 4: Cross-process and in-process locking

**Files:**
- Modify: `tests/test_telemetry_emitter.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py`

- [ ] **Step 1: Add the failing test**

Append:

```python
class TelemetryEmitterLockingTests(unittest.TestCase):
    def test_concurrent_threads_do_not_interleave_lines(self) -> None:
        # REQ-03 + NFR cross-process concurrency: 50 threads x 20 events
        # must produce 1000 well-formed JSONL lines (no partial writes,
        # no fragment splices).
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)

            def worker(tid: int) -> None:
                for i in range(20):
                    emitter.emit(StoryStarted(
                        timestamp="2026-06-14T00:00:00Z",
                        run_id=f"t{tid}",
                        epic="E",
                        story_key=f"S{tid}-{i}",
                        agent="a",
                        model="m",
                        complexity="c",
                    ))

            threads = [threading.Thread(target=worker, args=(t,)) for t in range(50)]
            for th in threads:
                th.start()
            for th in threads:
                th.join()

            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1000)
            for line in lines:
                payload = json.loads(line)  # raises if any line is corrupt
                self.assertEqual(payload["event_type"], "story_started")

    def test_lock_file_path_is_path_dot_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            emitter.emit(StoryStarted(
                timestamp="t", run_id="r", epic="E", story_key="S",
                agent="a", model="m", complexity="c",
            ))
            # filelock creates the lockfile on first acquire; it stays on
            # disk after release. Confirm the convention from REQ-03.
            self.assertTrue((Path(tmp) / "events.jsonl.lock").exists())
```

- [ ] **Step 2: Run tests to verify they fail (or are flaky without locking)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterLockingTests -v`
Expected: the concurrency test may pass intermittently on CPython due to the GIL and small write sizes; the lock-file-path test will FAIL because no FileLock is acquired so no `.lock` file is created.

- [ ] **Step 3: Add locks to emit**

Replace `emit` in `telemetry_emitter.py`:

```python
    def emit(self, event: Event) -> None:
        ensure_dir(self._path.parent)
        line = event.to_json_line() + "\n"
        with self._thread_lock:
            with self._file_lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterLockingTests -v`
Expected: PASS (2/2). Full suite still green: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_emitter.py skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryEmitter cross-process FileLock + threading.Lock"
```

---

## Task 4b: fsync-before-unlock ordering invariant (REQ-04, REQ-12)

**Files:**
- Modify: `tests/test_telemetry_emitter.py`

REQ-12 explicitly requires "the fsync-before-unlock ordering invariant" as a test. Behavioural tests confirm the data lands on disk but do not codify the ordering. Use `unittest.mock` to record call order against the actual emit code path.

- [ ] **Step 1: Add the failing test**

Append to `tests/test_telemetry_emitter.py`:

```python
from unittest import mock


class TelemetryEmitterFsyncOrderingTests(unittest.TestCase):
    def test_fsync_runs_before_file_lock_release(self) -> None:
        # REQ-04: os.fsync must run before the filelock is released so
        # a crash between emits cannot leave a partially written line.
        # We patch os.fsync and the FileLock context manager exit, then
        # confirm the recorded call sequence: write → flush → fsync →
        # filelock-release.
        events: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)

            real_fsync = os.fsync
            real_file_lock_release = emitter._file_lock.__exit__

            def tracing_fsync(fd: int) -> None:
                events.append("fsync")
                real_fsync(fd)

            def tracing_file_lock_exit(*args: object, **kwargs: object) -> None:
                events.append("filelock_release")
                return real_file_lock_release(*args, **kwargs)

            with mock.patch("story_automator.core.telemetry_emitter.os.fsync",
                            side_effect=tracing_fsync), \
                 mock.patch.object(emitter._file_lock, "__exit__",
                                   side_effect=tracing_file_lock_exit):
                emitter.emit(StoryStarted(
                    timestamp="t", run_id="r", epic="E", story_key="S",
                    agent="a", model="m", complexity="c",
                ))

            self.assertIn("fsync", events)
            self.assertIn("filelock_release", events)
            self.assertLess(
                events.index("fsync"),
                events.index("filelock_release"),
                msg=f"fsync must precede filelock_release, got {events}",
            )
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterFsyncOrderingTests -v`
Expected: PASS (Task 4 implementation already satisfies the ordering — fsync runs inside the `with open(...)` block, which is itself inside the `with self._file_lock:` block, so the lock release happens after fsync).

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_emitter.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): codify fsync-before-unlock ordering invariant (REQ-04, REQ-12)"
```

---

## Task 5: run_id stamping (constructor-provided run_id fills empty event run_id)

**Files:**
- Modify: `tests/test_telemetry_emitter.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py`

- [ ] **Step 1: Add the failing test**

Append:

```python
class TelemetryEmitterRunIdTests(unittest.TestCase):
    def test_ctor_run_id_stamps_empty_event_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path, run_id="ctor-run")
            event = StoryStarted(
                timestamp="t", run_id="", epic="E", story_key="S",
                agent="a", model="m", complexity="c",
            )
            emitter.emit(event)
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["run_id"], "ctor-run")

    def test_caller_run_id_wins_over_ctor_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path, run_id="ctor-run")
            event = StoryStarted(
                timestamp="t", run_id="caller-run", epic="E", story_key="S",
                agent="a", model="m", complexity="c",
            )
            emitter.emit(event)
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["run_id"], "caller-run")

    def test_no_ctor_run_id_passes_event_through_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)  # no run_id arg
            event = StoryStarted(
                timestamp="t", run_id="", epic="E", story_key="S",
                agent="a", model="m", complexity="c",
            )
            emitter.emit(event)
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["run_id"], "")

    def test_emit_does_not_mutate_caller_event_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path, run_id="ctor-run")
            event = StoryStarted(
                timestamp="t", run_id="", epic="E", story_key="S",
                agent="a", model="m", complexity="c",
            )
            emitter.emit(event)
            self.assertEqual(event.run_id, "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterRunIdTests -v`
Expected: FAIL — `test_ctor_run_id_stamps_empty_event_run_id` asserts `"ctor-run"` but emitter writes `""`.

- [ ] **Step 3: Implement run_id stamping without mutating the caller's event**

Update the imports at the top of `telemetry_emitter.py` so `compact_json` is alongside `ensure_dir`:

```python
from .common import compact_json, ensure_dir
```

Then replace `emit` in `telemetry_emitter.py`:

```python
    def emit(self, event: Event) -> None:
        ensure_dir(self._path.parent)
        line = self._serialize(event) + "\n"
        with self._thread_lock:
            with self._file_lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(line)
                    fh.flush()
                    os.fsync(fh.fileno())

    def _serialize(self, event: Event) -> str:
        # REQ-05: caller's non-empty run_id always wins; only stamp the
        # ctor-provided run_id into events whose run_id is empty. Mutate
        # the dict, not the dataclass — the caller keeps their object.
        if self._run_id is None or event.run_id:
            return event.to_json_line()
        data = event.to_dict()
        data["run_id"] = self._run_id
        return compact_json(data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterRunIdTests -v`
Expected: PASS (4/4). Then full suite: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests` — all green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_emitter.py skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryEmitter run_id stamping (ctor fills empty, caller wins)"
```

---

## Task 6: Round-trip every M01 event type through emit + parse_event

**Files:**
- Modify: `tests/test_telemetry_emitter.py`

- [ ] **Step 1: Add the round-trip test**

Append:

```python
class TelemetryEmitterRoundTripTests(unittest.TestCase):
    """REQ-12: every M01 event type round-trips through emit → parse_event."""

    def _emit_and_reparse(self, event: Event) -> Event:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            emitter.emit(event)
            line = path.read_text(encoding="utf-8").rstrip("\n")
            return parse_event(line)

    def test_story_started_round_trip(self) -> None:
        original = StoryStarted(
            timestamp="t", run_id="r", epic="E", story_key="S",
            agent="claude", model="sonnet", complexity="medium",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_story_completed_round_trip(self) -> None:
        original = StoryCompleted(
            timestamp="t", run_id="r", epic="E", story_key="S",
            duration_s=1.5, cost_usd=0.25, tokens_in=100, tokens_out=200, attempts=1,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_story_failed_round_trip(self) -> None:
        original = StoryFailed(
            timestamp="t", run_id="r", epic="E", story_key="S",
            error_class="lint", reason="ruff E501", attempts=5, final_session="sess-1",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_story_deferred_round_trip(self) -> None:
        original = StoryDeferred(
            timestamp="t", run_id="r", epic="E", story_key="S",
            reason="plateau", tasks_completed=3,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_retry_attempt_round_trip(self) -> None:
        original = RetryAttempt(
            timestamp="t", run_id="r", epic="E", story_key="S",
            attempt_num=2, agent="claude", model="opus", prev_error_class="test_fail",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_escalation_triggered_round_trip(self) -> None:
        original = EscalationTriggered(
            timestamp="t", run_id="r", epic="E", story_key="S",
            trigger_id=3, severity="critical", message="review loop",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_review_cycle_round_trip(self) -> None:
        original = ReviewCycle(
            timestamp="t", run_id="r", epic="E", story_key="S",
            cycle_num=2, issues_found=4, blocking=True,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_retro_fired_round_trip(self) -> None:
        original = RetroFired(
            timestamp="t", run_id="r", epic="E",
            stories_completed=4, total_cost_usd=1.50, duration_s=120.0,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_tmux_session_spawned_round_trip(self) -> None:
        original = TmuxSessionSpawned(
            timestamp="t", run_id="r", session_name="sess-1",
            story_key="S", pid=12345, pane_geometry="80x24",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_tmux_session_completed_round_trip(self) -> None:
        original = TmuxSessionCompleted(
            timestamp="t", run_id="r", session_name="sess-1",
            story_key="S", exit_code=0, duration_s=60.0,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_tmux_session_crashed_round_trip(self) -> None:
        original = TmuxSessionCrashed(
            timestamp="t", run_id="r", session_name="sess-1",
            story_key="S", exit_code=137, last_capture_chars=500,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_cost_charged_round_trip(self) -> None:
        original = CostCharged(
            timestamp="t", run_id="r", epic="E", story_key="S",
            phase="dev", cost_usd=0.12, tokens_in=50, tokens_out=100, model="sonnet",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_budget_alert_round_trip(self) -> None:
        original = BudgetAlert(
            timestamp="t", run_id="r",
            threshold_pct=75, total_cost_usd=7.5, max_budget_usd=10.0,
            epic="E", story_key="S",
        )
        self.assertEqual(self._emit_and_reparse(original), original)
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterRoundTripTests -v`
Expected: PASS (13/13). M01 event classes already implement `__eq__` via `@dataclass`, so `assertEqual` checks field-wise.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_emitter.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): emit→parse round-trip for all 13 M01 event types"
```

---

## Task 7: TelemetryReader scaffolding — missing file and empty file

**Files:**
- Create: `tests/test_telemetry_reader.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_telemetry_reader.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.telemetry_reader import TelemetryReader
from story_automator.core.telemetry_events import (
    CostCharged,
    RetroFired,
    RetryAttempt,
    StoryStarted,
)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the scaffolding**

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
from typing import Any

from .telemetry_events import (
    CostCharged,
    Event,
    RetroFired,
    RetryAttempt,
    parse_event,
)


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

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: PASS (2/2).

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_reader.py skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryReader scaffolding + missing/empty file handling"
```

---

## Task 8: Reader blank-line skip and malformed-line propagation

**Files:**
- Modify: `tests/test_telemetry_reader.py`

- [ ] **Step 1: Add the failing tests**

Append:

```python
class TelemetryReaderLineHandlingTests(unittest.TestCase):
    def test_blank_lines_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            line = json.dumps({
                "event_type": "story_started",
                "timestamp": "t", "run_id": "r",
                "epic": "E", "story_key": "S",
                "agent": "a", "model": "m", "complexity": "c",
            })
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
        # REQ NFR: streaming — iter_events must be a generator that
        # produces events one at a time. Verify it's iterable lazily by
        # taking only the first event from a file with many lines.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            line = json.dumps({
                "event_type": "story_started",
                "timestamp": "t", "run_id": "r",
                "epic": "E", "story_key": "S",
                "agent": "a", "model": "m", "complexity": "c",
            })
            path.write_text((line + "\n") * 1000, encoding="utf-8")
            reader = TelemetryReader(path)
            it = reader.iter_events()
            first = next(it)
            self.assertIsInstance(first, StoryStarted)
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader.TelemetryReaderLineHandlingTests -v`
Expected: PASS (3/3) — the Task 7 implementation already handles blank lines, propagates parse errors, and uses a generator.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): reader blank-line skip, malformed propagation, streaming"
```

---

## Task 9: cost_by_epic aggregation

**Files:**
- Modify: `tests/test_telemetry_reader.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`

- [ ] **Step 1: Add the failing tests**

Append:

```python
class TelemetryReaderCostByEpicTests(unittest.TestCase):
    def _write(self, path: Path, events: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev) + "\n")

    def test_cost_by_epic_sums_only_cost_charged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(path, [
                {"event_type": "cost_charged", "timestamp": "t", "run_id": "r",
                 "epic": "E1", "story_key": "S1", "phase": "dev",
                 "cost_usd": 0.10, "tokens_in": 10, "tokens_out": 20, "model": "m"},
                {"event_type": "cost_charged", "timestamp": "t", "run_id": "r",
                 "epic": "E1", "story_key": "S2", "phase": "dev",
                 "cost_usd": 0.25, "tokens_in": 10, "tokens_out": 20, "model": "m"},
                {"event_type": "cost_charged", "timestamp": "t", "run_id": "r",
                 "epic": "E2", "story_key": "S3", "phase": "dev",
                 "cost_usd": 1.00, "tokens_in": 10, "tokens_out": 20, "model": "m"},
                # Non-cost event must not contribute:
                {"event_type": "story_started", "timestamp": "t", "run_id": "r",
                 "epic": "E1", "story_key": "Sx",
                 "agent": "a", "model": "m", "complexity": "c"},
            ])
            reader = TelemetryReader(path)
            result = reader.cost_by_epic()
            self.assertEqual(set(result.keys()), {"E1", "E2"})
            self.assertAlmostEqual(result["E1"], 0.35, places=6)
            self.assertAlmostEqual(result["E2"], 1.00, places=6)

    def test_cost_by_epic_returns_empty_when_no_cost_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(path, [
                {"event_type": "story_started", "timestamp": "t", "run_id": "r",
                 "epic": "E1", "story_key": "S",
                 "agent": "a", "model": "m", "complexity": "c"},
            ])
            self.assertEqual(TelemetryReader(path).cost_by_epic(), {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader.TelemetryReaderCostByEpicTests -v`
Expected: FAIL — `AttributeError: 'TelemetryReader' object has no attribute 'cost_by_epic'`.

- [ ] **Step 3: Implement cost_by_epic**

Add to `TelemetryReader`:

```python
    def cost_by_epic(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for event in self.iter_events():
            if isinstance(event, CostCharged):
                totals[event.epic] = totals.get(event.epic, 0.0) + event.cost_usd
        return totals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader.TelemetryReaderCostByEpicTests -v`
Expected: PASS (2/2).

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_reader.py skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryReader.cost_by_epic aggregation"
```

---

## Task 10: attempts_by_story aggregation

**Files:**
- Modify: `tests/test_telemetry_reader.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`

- [ ] **Step 1: Add the failing tests**

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
            self._write(path, [
                {"event_type": "retry_attempt", "timestamp": "t", "run_id": "r",
                 "epic": "E1", "story_key": "S1", "attempt_num": 2,
                 "agent": "a", "model": "m", "prev_error_class": "x"},
                {"event_type": "retry_attempt", "timestamp": "t", "run_id": "r",
                 "epic": "E1", "story_key": "S1", "attempt_num": 3,
                 "agent": "a", "model": "m", "prev_error_class": "x"},
                {"event_type": "retry_attempt", "timestamp": "t", "run_id": "r",
                 "epic": "E2", "story_key": "S9", "attempt_num": 2,
                 "agent": "a", "model": "m", "prev_error_class": "x"},
                # Other types must not contribute:
                {"event_type": "cost_charged", "timestamp": "t", "run_id": "r",
                 "epic": "E1", "story_key": "S1", "phase": "dev",
                 "cost_usd": 0.01, "tokens_in": 1, "tokens_out": 1, "model": "m"},
            ])
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

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader.TelemetryReaderAttemptsByStoryTests -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Implement attempts_by_story**

Add to `TelemetryReader`:

```python
    def attempts_by_story(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for event in self.iter_events():
            if isinstance(event, RetryAttempt):
                key = (event.epic, event.story_key)
                counts[key] = counts.get(key, 0) + 1
        return counts
```

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader.TelemetryReaderAttemptsByStoryTests -v`
Expected: PASS (2/2).

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_reader.py skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryReader.attempts_by_story aggregation"
```

---

## Task 11: retro_inputs aggregation — most recent RetroFired wins

**Files:**
- Modify: `tests/test_telemetry_reader.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py`

- [ ] **Step 1: Add the failing tests**

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
            self._write(path, [
                {"event_type": "retro_fired", "timestamp": "2026-06-13T00:00:00Z",
                 "run_id": "r", "epic": "E1",
                 "stories_completed": 1, "total_cost_usd": 0.5, "duration_s": 30.0},
                {"event_type": "retro_fired", "timestamp": "2026-06-14T00:00:00Z",
                 "run_id": "r", "epic": "E1",
                 "stories_completed": 4, "total_cost_usd": 2.0, "duration_s": 120.0},
                {"event_type": "retro_fired", "timestamp": "2026-06-14T00:00:00Z",
                 "run_id": "r", "epic": "E2",
                 "stories_completed": 7, "total_cost_usd": 3.0, "duration_s": 60.0},
            ])
            reader = TelemetryReader(path)
            result = reader.retro_inputs("E1")
            self.assertEqual(result, {
                "stories_completed": 4,
                "total_cost_usd": 2.0,
                "duration_s": 120.0,
            })

    def test_retro_inputs_returns_empty_dict_when_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(path, [
                {"event_type": "retro_fired", "timestamp": "t", "run_id": "r",
                 "epic": "E1", "stories_completed": 1,
                 "total_cost_usd": 0.5, "duration_s": 30.0},
            ])
            self.assertEqual(TelemetryReader(path).retro_inputs("E_other"), {})

    def test_retro_inputs_returns_empty_when_no_retro_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.touch()
            self.assertEqual(TelemetryReader(path).retro_inputs("E1"), {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader.TelemetryReaderRetroInputsTests -v`
Expected: FAIL — `AttributeError`.

- [ ] **Step 3: Implement retro_inputs**

Add to `TelemetryReader` (and update the imports if needed):

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

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader -v`
Expected: PASS — all reader tests green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_reader.py skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TelemetryReader.retro_inputs (most-recent-wins per epic)"
```

---

## Task 12: Round-trip emit→read of mixed event types

**Files:**
- Modify: `tests/test_telemetry_reader.py`

- [ ] **Step 1: Add the integration test**

Append:

```python
class TelemetryReaderEmitReadIntegrationTests(unittest.TestCase):
    def test_mixed_events_aggregations_only_count_relevant_types(self) -> None:
        # REQ-13 mixed-event case: only relevant types contribute to
        # each rollup. We emit through the real TelemetryEmitter to
        # confirm the integration with M02's write path.
        from story_automator.core.telemetry_emitter import TelemetryEmitter
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            em = TelemetryEmitter(path)
            em.emit(StoryStarted(timestamp="t", run_id="r", epic="E1",
                                 story_key="S1", agent="a", model="m",
                                 complexity="c"))
            em.emit(CostCharged(timestamp="t", run_id="r", epic="E1",
                                story_key="S1", phase="dev", cost_usd=0.5,
                                tokens_in=1, tokens_out=1, model="m"))
            em.emit(RetryAttempt(timestamp="t", run_id="r", epic="E1",
                                 story_key="S1", attempt_num=2, agent="a",
                                 model="m", prev_error_class="x"))
            em.emit(RetroFired(timestamp="t", run_id="r", epic="E1",
                               stories_completed=2, total_cost_usd=0.5,
                               duration_s=60.0))
            reader = TelemetryReader(path)
            self.assertEqual(reader.cost_by_epic(), {"E1": 0.5})
            self.assertEqual(reader.attempts_by_story(), {("E1", "S1"): 1})
            self.assertEqual(reader.retro_inputs("E1"), {
                "stories_completed": 2, "total_cost_usd": 0.5, "duration_s": 60.0,
            })
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_reader.TelemetryReaderEmitReadIntegrationTests -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_reader.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): emit→read integration over mixed event types"
```

---

## Task 13: Wire tmux_runtime.py — emit TmuxSessionSpawned/Completed/Crashed

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py`
- Modify: `tests/test_telemetry_emitter.py` (add wiring smoke test using monkeypatching of the telemetry path env)

The hook points (the natural lifecycle moments in the existing code):
- `spawn_session` (line ~238): emit `TmuxSessionSpawned` after a successful spawn (exit code 0). The session name is the function argument; pid comes from `_spawn_runner`'s second tuple element when nonzero; pane_geometry is fetched via `tmux display-message -p '#{pane_width}x#{pane_height} -t <session>'` if available, falling back to `""`.
- `heartbeat_check` (line ~251): when the heartbeat returns `"completed"` (line 273 or 287) emit `TmuxSessionCompleted`; when it returns `"dead"`/`"crashed"` (line 273 fallback, line 289) emit `TmuxSessionCrashed`. The story_key for these can be empty (`""`) — the tmux runtime layer doesn't carry the story key.

Telemetry path: `Path(get_project_root()) / "telemetry" / "events.jsonl"`. A small helper `_telemetry_emitter()` in `tmux_runtime.py` returns a fresh `TelemetryEmitter(path)`; emitters are constructed lazily per call, NOT cached as a module global (avoids cross-test state).

- [ ] **Step 1: Add a wiring smoke test that asserts spawn writes an event**

Append to `tests/test_telemetry_emitter.py`:

```python
class TelemetryEmitterTmuxWiringTests(unittest.TestCase):
    def test_emit_tmux_spawned_writes_typed_event(self) -> None:
        # Exercises the spawn-side emit code path directly. The full
        # spawn pipeline depends on tmux and is deferred to the WSL
        # runtime gate (cross-platform policy in CLAUDE.md). This test
        # confirms the emitter integration shape only.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            emitter.emit(TmuxSessionSpawned(
                timestamp="t", run_id="r",
                session_name="sess-1", story_key="S1",
                pid=4242, pane_geometry="80x24",
            ))
            line = path.read_text(encoding="utf-8").rstrip("\n")
            payload = json.loads(line)
            self.assertEqual(payload["event_type"], "tmux_session_spawned")
            self.assertEqual(payload["session_name"], "sess-1")
            self.assertEqual(payload["pid"], 4242)
```

- [ ] **Step 2: Add the helper and emit calls to `tmux_runtime.py`**

Add near the top of `tmux_runtime.py` (after the existing imports). Note: `iso_now` may already be in scope via the existing `from story_automator.core.utils import ...` line; check the existing import block and reuse rather than double-import.

```python
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_events import (
    TmuxSessionCompleted,
    TmuxSessionCrashed,
    TmuxSessionSpawned,
)

_EMITTER_CACHE: dict[Path, TelemetryEmitter] = {}


def _telemetry_path(project_root: str | None) -> Path:
    base = Path(project_root) if project_root else Path(get_project_root())
    return (base / "telemetry" / "events.jsonl").resolve()


def _telemetry_emitter(project_root: str | None) -> TelemetryEmitter:
    path = _telemetry_path(project_root)
    cached = _EMITTER_CACHE.get(path)
    if cached is not None:
        return cached
    emitter = TelemetryEmitter(path)
    _EMITTER_CACHE[path] = emitter
    return emitter
```

In `spawn_session` (around line 238–248), wrap the existing return with an emit:

```python
def spawn_session(
    session: str,
    command: str,
    selected_agent: str,
    project_root: str | None = None,
    mode: str | None = None,
) -> tuple[str, int]:
    resolved_mode = _resolve_spawn_mode(mode)
    if resolved_mode == "legacy":
        output, code = _spawn_legacy(session, command, selected_agent, project_root)
    else:
        output, code = _spawn_runner(session, command, selected_agent, project_root)
    if code == 0:
        _emit_tmux_spawned(session, project_root)
    return output, code


def _emit_tmux_spawned(session: str, project_root: str | None) -> None:
    pid = _safe_int(_session_pid(session))
    geom_out, geom_code = run_cmd(
        "tmux", "display-message", "-p", "-t", session,
        "#{pane_width}x#{pane_height}",
    )
    geometry = geom_out.strip() if geom_code == 0 else ""
    _telemetry_emitter(project_root).emit(TmuxSessionSpawned(
        timestamp=iso_now(),
        run_id="",
        session_name=session,
        story_key="",
        pid=pid,
        pane_geometry=geometry,
    ))


def _session_pid(session: str) -> str:
    out, code = run_cmd(
        "tmux", "display-message", "-p", "-t", session, "#{pane_pid}",
    )
    return out.strip() if code == 0 else ""
```

In `heartbeat_check` (lines 273 and 287–290), emit completion/crash before returning:

Replace the `if _is_terminal_state(state):` block (lines 271–274) with:

```python
    if _is_terminal_state(state):
        pid = str(state.get("childPid") or "")
        result = str(state.get("result") or "")
        status = "completed" if result == "success" else "dead"
        _emit_heartbeat_terminal(session, state, status, project_root)
        return (status, 0.0, pid, prompt)
```

And replace lines 287–290 (the `_wait_for_terminal_state` branch) with:

```python
    _wait_for_terminal_state(state_path)
    status = session_status(session, full=False, codex=selected_agent == "codex", project_root=project_root, mode=resolved_mode)
    public = str(status["session_state"])
    if public == "completed":
        _emit_tmux_completed(session, state, project_root)
        return ("completed", 0.0, str(child_pid), prompt)
    if public in {"crashed", "stuck", "not_found"}:
        _emit_tmux_crashed(session, state, project_root)
        return ("dead", 0.0, str(child_pid), prompt)
    return ("idle", 0.0, str(child_pid), prompt)
```

Then add the three helpers below `heartbeat_check`:

```python
def _emit_heartbeat_terminal(
    session: str, state: dict, status: str, project_root: str | None,
) -> None:
    if status == "completed":
        _emit_tmux_completed(session, state, project_root)
    else:
        _emit_tmux_crashed(session, state, project_root)


def _emit_tmux_completed(
    session: str, state: dict, project_root: str | None,
) -> None:
    exit_code = _safe_int(state.get("exitCode"))
    duration_s = float(state.get("durationSeconds") or 0.0)
    _telemetry_emitter(project_root).emit(TmuxSessionCompleted(
        timestamp=iso_now(),
        run_id="",
        session_name=session,
        story_key="",
        exit_code=exit_code,
        duration_s=duration_s,
    ))


def _emit_tmux_crashed(
    session: str, state: dict, project_root: str | None,
) -> None:
    exit_code = _safe_int(state.get("exitCode"))
    last_capture = _safe_int(state.get("lastCaptureChars"))
    _telemetry_emitter(project_root).emit(TmuxSessionCrashed(
        timestamp=iso_now(),
        run_id="",
        session_name=session,
        story_key="",
        exit_code=exit_code,
        last_capture_chars=last_capture,
    ))
```

- [ ] **Step 3: Run tests to verify wiring smoke test passes and existing tmux tests do not regress**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterTmuxWiringTests -v`
Expected: PASS.
Then run the full suite: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests`
Expected: all M01 + M02 tests green; existing tmux_runtime unit tests untouched. The runtime gate (actual tmux spawn → event-on-disk verification) is deferred to WSL Ubuntu-26.04 per CLAUDE.md.

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_emitter.py skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): wire tmux_runtime spawn/completed/crashed emits"
```

---

## Task 14: Wire orchestrator_epic_agents.py — RetryAttempt/EscalationTriggered/ReviewCycle

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py`
- Modify: `tests/test_telemetry_emitter.py` (extend wiring smoke tests)

Hook points (the natural lifecycle moments):
- `agents_resolve_action` returns the agent for a task. When `--task` is `dev` and the action is invoked after a prior failure (the caller passes an `--attempt` flag if non-1), emit `RetryAttempt`. For M02, since the existing CLI signature does not yet thread `--attempt`, emit `RetryAttempt` only when the resolved action carries a non-zero attempt number from the state file (`agents.attempt_num`); fall back to attempt 1 / no emit otherwise.
- `check_blocking_action` (line 89): when the function returns the path of a blocking finding, emit `EscalationTriggered`. The existing signature returns a JSON line via `print_json`; thread an emit before the print.
- `retro_agent_action` (line 201): no review-cycle emit here. `ReviewCycle` belongs alongside `verify-code-review` in `orchestrator.py` (handled in Task 15) — confirm here that this file emits only `RetryAttempt` and `EscalationTriggered`.

Because the existing CLI does not yet carry `attempt_num` or `cycle_num` on its argument surface, the M02 wiring threads them via the state-file dict (`config["attempt_num"]`, `config["trigger_id"]`, `config["severity"]`, `config["message"]`). Missing keys default to `0` / `""`. The wiring is observational: it emits when the keys are present.

- [ ] **Step 1: Add the wiring smoke test**

Append to `tests/test_telemetry_emitter.py`:

```python
class TelemetryEmitterEpicAgentsWiringTests(unittest.TestCase):
    def test_emit_retry_attempt_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            emitter.emit(RetryAttempt(
                timestamp="t", run_id="r", epic="E1", story_key="S1",
                attempt_num=2, agent="claude", model="opus",
                prev_error_class="test_fail",
            ))
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["event_type"], "retry_attempt")
            self.assertEqual(payload["attempt_num"], 2)

    def test_emit_escalation_triggered_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            emitter.emit(EscalationTriggered(
                timestamp="t", run_id="r", epic="E1", story_key="S1",
                trigger_id=3, severity="critical", message="review loop",
            ))
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["event_type"], "escalation_triggered")
            self.assertEqual(payload["severity"], "critical")
```

- [ ] **Step 2: Add the wiring**

Add to the top of `orchestrator_epic_agents.py` (next to the existing imports). `iso_now` is already imported from `story_automator.core.utils` (line 12) — do NOT add a second import; reuse the existing symbol.

```python
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_events import (
    EscalationTriggered,
    RetroFired,
    RetryAttempt,
)

_EMITTER_CACHE: dict[Path, TelemetryEmitter] = {}


def _telemetry_emitter() -> TelemetryEmitter:
    path = (Path(get_project_root()) / "telemetry" / "events.jsonl").resolve()
    cached = _EMITTER_CACHE.get(path)
    if cached is not None:
        return cached
    emitter = TelemetryEmitter(path)
    _EMITTER_CACHE[path] = emitter
    return emitter
```

In `agents_resolve_action`, extend the `options` dict to accept two new optional flags (`--attempt` and `--prev-error-class`). The existing flag-parsing loop (lines 167–173) already accepts any `--key value` pair, so simply seed the `options` dict with the two new keys to a default. Then, right before the existing `print_json` call at the success branch (around line 195), insert:

```python
        attempt_num = int(options.get("attempt") or 0)
        if attempt_num >= 2:
            _telemetry_emitter().emit(RetryAttempt(
                timestamp=iso_now(),
                run_id="",
                epic=options["story"].split(".", 1)[0],
                story_key=options["story"],
                attempt_num=attempt_num,
                agent=selection.get("primary", ""),
                model=model,
                prev_error_class=options.get("prev-error-class") or "",
            ))
        print_json({"ok": True, "story": options["story"], "task": options["task"], "primary": selection.get("primary", ""), "fallback": fallback, "model": model, "complexity": story.get("complexity", "")})
        return 0
```

Update the `options` dict seed to:

```python
    options = {"state-file": "", "agents-file": "", "story": "", "task": "", "attempt": "", "prev-error-class": ""}
```

Rationale: the existing CLI surface is `--key value`; adding new optional flags is non-breaking. Tests for the new CLI surface live alongside the existing epic_agents unit tests (if any); for M02 the telemetry smoke test covers the emit shape — exercising the CLI flag is M06 retry-engine scope.

In `check_blocking_action`, the existing code has two `blocking: True` return paths: the `epic_file_not_found` early return (line ~102) and the `dependents` non-empty return (line ~115). Emit `EscalationTriggered` at the `dependents` non-empty path only — the early `epic_file_not_found` return is a control-flow error, not a story-level escalation. Insert before the `print_json` call at the `dependents` non-empty branch (line ~115 in the existing source):

```python
        if dependents:
            _telemetry_emitter().emit(EscalationTriggered(
                timestamp=iso_now(),
                run_id="",
                epic=epic,
                story_key=norm.id,
                trigger_id=0,
                severity="warning",
                message=f"blocked by {len(dependents)} dependent stories",
            ))
            print_json({"ok": True, "blocking": True, "story": norm.id, "epic": epic, "dependents": sorted(set(dependents), key=lambda item: _story_sort_key(project_root, item, epic)), "reason": "dependent_stories", "source": "epic_file"})
            return 0
```

Rationale: `epic`, `norm`, and `dependents` are all in scope at that line in the existing function. `trigger_id` is `0` because the M02 spec does not enumerate trigger IDs (the trigger taxonomy is M06+).

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterEpicAgentsWiringTests -v`
Expected: PASS.
Full suite: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests` — all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_emitter.py skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): wire RetryAttempt + EscalationTriggered emits in epic_agents"
```

---

## Task 15: Wire orchestrator.py — StoryStarted/Completed/Failed/Deferred + ReviewCycle + RetroFired

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py`
- Modify: `tests/test_telemetry_emitter.py` (extend wiring smoke tests)

Hook points:
- `_marker create` (line 174): emit `StoryStarted` when the marker is first created — that is the moment the orchestrator decides to begin work on a story.
- `_commit_ready` (line 372): when `status.done` and uncommitted changes exist, the story is commit-ready — emit `StoryCompleted`. Cost/tokens/attempts are pulled from the state file via `parse_simple_frontmatter`; missing keys default to `0`.
- `_escalate` (line 325): when the JSON response carries `"escalate": True`, emit `StoryFailed` for `session-crash`/`story-validation` outcomes (terminal escalations) and `EscalationTriggered` is NOT re-emitted here (that's the `check-blocking` path). `StoryDeferred` is emitted when the escalation reason names plateau detection (`"plateau"` substring in the reason).
- `_verify_code_review` (line 439): emit `ReviewCycle` after `verify_code_review_completion` returns; `cycle_num` from `payload["cycle"]`, `issues_found` from `payload["issuesFound"]`, `blocking` from `not payload["verified"]`.
- `retro_agent_action` is in epic_agents.py — `RetroFired` is emitted there. Update Task 14 to include it as a third event.

For brevity here, this task implements `_marker create` + `_commit_ready` + `_verify_code_review` only. The `_escalate` and `retro_agent_action` emits are a follow-up step in the same commit (Step 3 below).

- [ ] **Step 1: Add the wiring smoke tests**

Append to `tests/test_telemetry_emitter.py`:

```python
class TelemetryEmitterOrchestratorWiringTests(unittest.TestCase):
    def test_emit_story_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            TelemetryEmitter(path).emit(StoryStarted(
                timestamp="t", run_id="r", epic="E1", story_key="S1",
                agent="claude", model="sonnet", complexity="medium",
            ))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").rstrip("\n"))[
                    "event_type"
                ],
                "story_started",
            )

    def test_emit_story_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            TelemetryEmitter(path).emit(StoryCompleted(
                timestamp="t", run_id="r", epic="E1", story_key="S1",
                duration_s=10.0, cost_usd=0.5, tokens_in=100,
                tokens_out=200, attempts=1,
            ))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").rstrip("\n"))[
                    "event_type"
                ],
                "story_completed",
            )

    def test_emit_review_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            TelemetryEmitter(path).emit(ReviewCycle(
                timestamp="t", run_id="r", epic="E1", story_key="S1",
                cycle_num=2, issues_found=4, blocking=True,
            ))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").rstrip("\n"))[
                    "event_type"
                ],
                "review_cycle",
            )

    def test_emit_retro_fired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            TelemetryEmitter(path).emit(RetroFired(
                timestamp="t", run_id="r", epic="E1",
                stories_completed=4, total_cost_usd=2.5, duration_s=120.0,
            ))
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").rstrip("\n"))[
                    "event_type"
                ],
                "retro_fired",
            )
```

- [ ] **Step 2: Add the wiring in orchestrator.py**

Add to the top of `orchestrator.py` (after the existing imports). `iso_now`, `Path`, and `get_project_root` are already in scope via the existing `story_automator.core.utils` import block — do NOT re-import. `StoryDeferred` is NOT used in this milestone (no plateau-detection code path exists in M02; the deferral hook is M06 retry-engine scope) and is intentionally omitted from the import list.

```python
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_events import (
    ReviewCycle,
    StoryCompleted,
    StoryFailed,
    StoryStarted,
)

_EMITTER_CACHE: dict[Path, TelemetryEmitter] = {}


def _telemetry_emitter() -> TelemetryEmitter:
    path = (Path(get_project_root()) / "telemetry" / "events.jsonl").resolve()
    cached = _EMITTER_CACHE.get(path)
    if cached is not None:
        return cached
    emitter = TelemetryEmitter(path)
    _EMITTER_CACHE[path] = emitter
    return emitter
```

In `_marker create` (after `atomic_write(marker_file, ...)`):

```python
        _telemetry_emitter().emit(StoryStarted(
            timestamp=iso_now(),
            run_id="",
            epic=options["epic"],
            story_key=options["story"],
            agent="",  # marker creation does not yet know the agent
            model="",
            complexity="",
        ))
```

In `_commit_ready` (the `if status.done` branch, after the `out, _ = run_cmd("git", ...)` call, before the first `print_json`):

```python
        _telemetry_emitter().emit(StoryCompleted(
            timestamp=iso_now(),
            run_id="",
            epic="",
            story_key=args[0],
            duration_s=0.0,
            cost_usd=0.0,
            tokens_in=0,
            tokens_out=0,
            attempts=1,
        ))
```

In `_verify_code_review` (right before the final `return`):

```python
    _telemetry_emitter().emit(ReviewCycle(
        timestamp=iso_now(),
        run_id="",
        epic="",
        story_key=args[0],
        cycle_num=int(payload.get("cycle") or 0),
        issues_found=int(payload.get("issuesFound") or 0),
        blocking=not bool(payload.get("verified")),
    ))
```

In `_escalate` (in the `if trigger == "session-crash":` branch, when retries >= limit):

```python
            _telemetry_emitter().emit(StoryFailed(
                timestamp=iso_now(),
                run_id="",
                epic="",
                story_key="",
                error_class="session_crash",
                reason=f"Session crashed after {retries} retries",
                attempts=retries,
                final_session="",
            ))
```

In `_escalate` (story-validation: created != 1 → StoryFailed); plateau detection currently doesn't have a dedicated trigger in this file. If the spec mandates `StoryDeferred`, defer that emit to M06 retry/escalation engine (note in commit message).

- [ ] **Step 3: Add `RetroFired` emit in `retro_agent_action`**

In `orchestrator_epic_agents.py` (the function `retro_agent_action` already imported in Task 14), add before the final `print_json`:

```python
    _telemetry_emitter().emit(RetroFired(
        timestamp=iso_now(),
        run_id="",
        epic=str(config.get("epic") or ""),
        stories_completed=int(config.get("storiesCompleted") or 0),
        total_cost_usd=float(config.get("totalCostUsd") or 0.0),
        duration_s=float(config.get("durationSeconds") or 0.0),
    ))
```

Update the import block in epic_agents.py to add `RetroFired`.

- [ ] **Step 4: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_emitter.TelemetryEmitterOrchestratorWiringTests -v`
Expected: PASS.
Full suite: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_emitter.py skills/bmad-story-automator/src/story_automator/commands/orchestrator.py skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): wire orchestrator StoryStarted/Completed/Failed + ReviewCycle + RetroFired"
```

---

## Task 16: Quality gates — ruff, format, coverage, allowlist, size

**Files:**
- (no source changes; gate validation only)

- [ ] **Step 1: Lint gate**

Run:
```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py \
  skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py \
  tests/test_telemetry_emitter.py \
  tests/test_telemetry_reader.py
```
Expected: zero violations. Fix any in-place (no rule disables).

- [ ] **Step 2: Format gate**

Run:
```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py \
  skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py \
  tests/test_telemetry_emitter.py \
  tests/test_telemetry_reader.py
```
Expected: zero files need reformat. If anything fails, run without `--check`, review the diff, and commit.

- [ ] **Step 3: Test gate**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests`
Expected: full suite green (M01 tests included).

- [ ] **Step 4: Coverage gate**

Run:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/telemetry_emitter,skills/bmad-story-automator/src/story_automator/core/telemetry_reader \
  -m unittest tests.test_telemetry_emitter tests.test_telemetry_reader
PYTHONPATH=skills/bmad-story-automator/src python -m coverage report -m --fail-under=85
```
Expected: ≥85% on both modules. If below, identify uncovered lines from the report and add targeted tests.

- [ ] **Step 5: Import-allowlist gate**

Run (use the Grep tool, NOT shell grep — but for documentation purposes the equivalent is):
```bash
grep -E "^(from |import )" \
  skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py \
  skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
```
Expected matches: only `from __future__`, `import os`, `import threading`, `from pathlib`, `from collections.abc`, `from typing`, `from filelock`, `from .common`, `from .telemetry_events`. No third-party imports outside `filelock` and `psutil`.

For the three edited wiring files, confirm no NEW third-party import was introduced (use Grep with `-B 2` against each file's import block and diff against `git log -p` for the file pre-M02).

- [ ] **Step 6: Module-size gate**

Run:
```bash
wc -l \
  skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py \
  skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py
```
Expected: both ≤500 lines.

- [ ] **Step 7: Cross-platform smoke**

Confirm via Bash (Windows git-bash) that the test suite ran clean. The WSL Ubuntu and Linux CI runs are CI's responsibility — note in the commit message that local Windows git-bash passed.

- [ ] **Step 8: Commit the gate evidence**

If any test/lint/format fix was needed, commit it under one tidy message:

```bash
git add -u
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): M02 quality gates green (lint, format, coverage ≥85, allowlist, size)"
```

If everything was already green, no commit is needed — proceed to Task 17.

---

## Task 17: Self-review checklist against M02 spec

**Files:**
- (read-only)

- [ ] **Step 1: Cross-reference each REQ to a task**

Walk the spec section by section and confirm coverage:

| REQ  | Implemented in |
|------|----------------|
| REQ-01 module exists, py 3.11–3.14 importable | Task 2 |
| REQ-02 ctor accepts path, lazy ensure_dir | Task 2 + Task 3 |
| REQ-03 emit append + filelock + threading.Lock | Task 4 |
| REQ-04 fsync before unlock | Task 3 + Task 4 |
| REQ-05 run_id stamping (empty fills, caller wins) | Task 5 |
| REQ-06 TelemetryReader iter_events | Task 7 |
| REQ-07 missing → empty, blank skip, malformed propagates | Task 7 + Task 8 |
| REQ-08 cost_by_epic / attempts_by_story / retro_inputs | Tasks 9–11 |
| REQ-09 orchestrator.py wiring | Task 15 |
| REQ-10 orchestrator_epic_agents.py wiring | Task 14 + Task 15 (RetroFired) |
| REQ-11 tmux_runtime.py wiring | Task 13 |
| REQ-12 emit-side tests (single, multi, blank, fsync, run_id, round-trip) | Tasks 3–6 |
| REQ-13 reader tests (aggregations, empty, missing, malformed, mixed) | Tasks 7–12 |
| REQ-14 stdlib + filelock + psutil only | Task 16 step 5 |
| REQ-15 reuse iso_now/compact_json/ensure_dir from common | Tasks 2, 5 |
| NFR module size ≤500 LOC | Task 16 step 6 |
| NFR PEP 604 + from __future__ annotations | Tasks 2, 7 (built in from the start) |
| NFR ruff check + format clean | Task 16 |
| NFR coverage ≥85% per module | Task 16 |
| NFR cross-platform, no tmux/subprocess in unit tests | Built into every test task (tempfile, threading, no subprocess.run) |
| NFR cross-process concurrency safe | Task 4 stress test |
| NFR reader streaming, no full-file buffer | Task 8 step 1 (`test_iter_events_does_not_buffer_full_file`) |
| Quality gates (lint, format, test, coverage, allowlist, size, cross-plat) | Task 16 |

- [ ] **Step 2: Final commit if any gap-fix is needed**

If any REQ is uncovered, add the missing test/implementation under a small bonus task before merging. Otherwise, the plan is complete.

---
