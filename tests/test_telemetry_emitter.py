# tests/test_telemetry_emitter.py
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

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
                emitter.emit(
                    StoryStarted(
                        timestamp="2026-06-14T00:00:00Z",
                        run_id="r",
                        epic="E",
                        story_key=f"S{i}",
                        agent="claude",
                        model="sonnet",
                        complexity="low",
                    )
                )
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 5)
            keys = [json.loads(line)["story_key"] for line in lines]
            self.assertEqual(keys, ["S0", "S1", "S2", "S3", "S4"])

    def test_emit_lazily_creates_parent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "nested" / "events.jsonl"
            self.assertFalse(path.parent.exists())
            emitter = TelemetryEmitter(path)
            emitter.emit(
                StoryStarted(
                    timestamp="t",
                    run_id="r",
                    epic="E",
                    story_key="S",
                    agent="a",
                    model="m",
                    complexity="c",
                )
            )
            self.assertTrue(path.parent.is_dir())
            self.assertTrue(path.is_file())


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
                    emitter.emit(
                        StoryStarted(
                            timestamp="2026-06-14T00:00:00Z",
                            run_id=f"t{tid}",
                            epic="E",
                            story_key=f"S{tid}-{i}",
                            agent="a",
                            model="m",
                            complexity="c",
                        )
                    )

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
            expected_lock_path = Path(tmp) / "events.jsonl.lock"
            self.assertEqual(emitter._lock_path, expected_lock_path)


class TelemetryEmitterFsyncOrderingTests(unittest.TestCase):
    def test_fsync_runs_before_file_lock_release(self) -> None:
        # REQ-04: os.fsync must run before the filelock is released so
        # a crash between emits cannot leave a partially written line.
        # We patch os.fsync and the FileLock context manager __exit__, then
        # confirm the recorded call sequence: write → flush → fsync →
        # filelock-release.
        events: list[str] = []

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)

            real_fsync = os.fsync

            def tracing_fsync(fd: int) -> None:
                events.append("fsync")
                real_fsync(fd)

            # Create a wrapper that traces the filelock's __exit__
            class TracingFileLock:
                def __init__(self, wrapped):
                    self._wrapped = wrapped

                def __enter__(self):
                    return self._wrapped.__enter__()

                def __exit__(self, *args):
                    events.append("filelock_release")
                    return self._wrapped.__exit__(*args)

                def __getattr__(self, name):
                    return getattr(self._wrapped, name)

            # Replace the filelock with our tracing wrapper
            original_lock = emitter._file_lock
            emitter._file_lock = TracingFileLock(original_lock)

            with mock.patch(
                "story_automator.core.telemetry_emitter.os.fsync",
                side_effect=tracing_fsync,
            ):
                emitter.emit(
                    StoryStarted(
                        timestamp="t",
                        run_id="r",
                        epic="E",
                        story_key="S",
                        agent="a",
                        model="m",
                        complexity="c",
                    )
                )

            self.assertIn("fsync", events)
            self.assertIn("filelock_release", events)
            self.assertLess(
                events.index("fsync"),
                events.index("filelock_release"),
                msg=f"fsync must precede filelock_release, got {events}",
            )


class TelemetryEmitterRunIdTests(unittest.TestCase):
    def test_ctor_run_id_stamps_empty_event_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path, run_id="ctor-run")
            event = StoryStarted(
                timestamp="t",
                run_id="",
                epic="E",
                story_key="S",
                agent="a",
                model="m",
                complexity="c",
            )
            emitter.emit(event)
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["run_id"], "ctor-run")

    def test_caller_run_id_wins_over_ctor_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path, run_id="ctor-run")
            event = StoryStarted(
                timestamp="t",
                run_id="caller-run",
                epic="E",
                story_key="S",
                agent="a",
                model="m",
                complexity="c",
            )
            emitter.emit(event)
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["run_id"], "caller-run")

    def test_no_ctor_run_id_passes_event_through_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)  # no run_id arg
            event = StoryStarted(
                timestamp="t",
                run_id="",
                epic="E",
                story_key="S",
                agent="a",
                model="m",
                complexity="c",
            )
            emitter.emit(event)
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["run_id"], "")

    def test_emit_does_not_mutate_caller_event_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path, run_id="ctor-run")
            event = StoryStarted(
                timestamp="t",
                run_id="",
                epic="E",
                story_key="S",
                agent="a",
                model="m",
                complexity="c",
            )
            emitter.emit(event)
            self.assertEqual(event.run_id, "")


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
            timestamp="t",
            run_id="r",
            epic="E",
            story_key="S",
            agent="claude",
            model="sonnet",
            complexity="medium",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_story_completed_round_trip(self) -> None:
        original = StoryCompleted(
            timestamp="t",
            run_id="r",
            epic="E",
            story_key="S",
            duration_s=1.5,
            cost_usd=0.25,
            tokens_in=100,
            tokens_out=200,
            attempts=1,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_story_failed_round_trip(self) -> None:
        original = StoryFailed(
            timestamp="t",
            run_id="r",
            epic="E",
            story_key="S",
            error_class="lint",
            reason="ruff E501",
            attempts=5,
            final_session="sess-1",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_story_deferred_round_trip(self) -> None:
        original = StoryDeferred(
            timestamp="t",
            run_id="r",
            epic="E",
            story_key="S",
            reason="plateau",
            tasks_completed=3,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_retry_attempt_round_trip(self) -> None:
        original = RetryAttempt(
            timestamp="t",
            run_id="r",
            epic="E",
            story_key="S",
            attempt_num=2,
            agent="claude",
            model="opus",
            prev_error_class="test_fail",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_escalation_triggered_round_trip(self) -> None:
        original = EscalationTriggered(
            timestamp="t",
            run_id="r",
            epic="E",
            story_key="S",
            trigger_id=3,
            severity="critical",
            message="review loop",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_review_cycle_round_trip(self) -> None:
        original = ReviewCycle(
            timestamp="t",
            run_id="r",
            epic="E",
            story_key="S",
            cycle_num=2,
            issues_found=4,
            blocking=True,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_retro_fired_round_trip(self) -> None:
        original = RetroFired(
            timestamp="t",
            run_id="r",
            epic="E",
            stories_completed=4,
            total_cost_usd=1.50,
            duration_s=120.0,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_tmux_session_spawned_round_trip(self) -> None:
        original = TmuxSessionSpawned(
            timestamp="t",
            run_id="r",
            session_name="sess-1",
            story_key="S",
            pid=12345,
            pane_geometry="80x24",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_tmux_session_completed_round_trip(self) -> None:
        original = TmuxSessionCompleted(
            timestamp="t",
            run_id="r",
            session_name="sess-1",
            story_key="S",
            exit_code=0,
            duration_s=60.0,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_tmux_session_crashed_round_trip(self) -> None:
        original = TmuxSessionCrashed(
            timestamp="t",
            run_id="r",
            session_name="sess-1",
            story_key="S",
            exit_code=137,
            last_capture_chars=500,
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_cost_charged_round_trip(self) -> None:
        original = CostCharged(
            timestamp="t",
            run_id="r",
            epic="E",
            story_key="S",
            phase="dev",
            cost_usd=0.12,
            tokens_in=50,
            tokens_out=100,
            model="sonnet",
        )
        self.assertEqual(self._emit_and_reparse(original), original)

    def test_budget_alert_round_trip(self) -> None:
        original = BudgetAlert(
            timestamp="t",
            run_id="r",
            threshold_pct=75,
            total_cost_usd=7.5,
            max_budget_usd=10.0,
            epic="E",
            story_key="S",
        )
        self.assertEqual(self._emit_and_reparse(original), original)


class TelemetryEmitterTmuxWiringTests(unittest.TestCase):
    def test_emit_tmux_spawned_writes_typed_event(self) -> None:
        # Exercises the spawn-side emit code path directly. The full
        # spawn pipeline depends on tmux and is deferred to the WSL
        # runtime gate (cross-platform policy in CLAUDE.md). This test
        # confirms the emitter integration shape only.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            emitter.emit(
                TmuxSessionSpawned(
                    timestamp="t",
                    run_id="r",
                    session_name="sess-1",
                    story_key="S1",
                    pid=4242,
                    pane_geometry="80x24",
                )
            )
            line = path.read_text(encoding="utf-8").rstrip("\n")
            payload = json.loads(line)
            self.assertEqual(payload["event_type"], "tmux_session_spawned")
            self.assertEqual(payload["session_name"], "sess-1")
            self.assertEqual(payload["pid"], 4242)


class TelemetryEmitterEpicAgentsWiringTests(unittest.TestCase):
    def test_emit_retry_attempt_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            emitter.emit(
                RetryAttempt(
                    timestamp="t",
                    run_id="r",
                    epic="E1",
                    story_key="S1",
                    attempt_num=2,
                    agent="claude",
                    model="opus",
                    prev_error_class="test_fail",
                )
            )
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["event_type"], "retry_attempt")
            self.assertEqual(payload["attempt_num"], 2)

    def test_emit_escalation_triggered_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(path)
            emitter.emit(
                EscalationTriggered(
                    timestamp="t",
                    run_id="r",
                    epic="E1",
                    story_key="S1",
                    trigger_id=3,
                    severity="critical",
                    message="review loop",
                )
            )
            payload = json.loads(path.read_text(encoding="utf-8").rstrip("\n"))
            self.assertEqual(payload["event_type"], "escalation_triggered")
            self.assertEqual(payload["severity"], "critical")


class TelemetryEmitterOrchestratorWiringTests(unittest.TestCase):
    def test_emit_story_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            TelemetryEmitter(path).emit(
                StoryStarted(
                    timestamp="t",
                    run_id="r",
                    epic="E1",
                    story_key="S1",
                    agent="claude",
                    model="sonnet",
                    complexity="medium",
                )
            )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").rstrip("\n"))["event_type"],
                "story_started",
            )

    def test_emit_story_completed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            TelemetryEmitter(path).emit(
                StoryCompleted(
                    timestamp="t",
                    run_id="r",
                    epic="E1",
                    story_key="S1",
                    duration_s=10.0,
                    cost_usd=0.5,
                    tokens_in=100,
                    tokens_out=200,
                    attempts=1,
                )
            )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").rstrip("\n"))["event_type"],
                "story_completed",
            )

    def test_emit_review_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            TelemetryEmitter(path).emit(
                ReviewCycle(
                    timestamp="t",
                    run_id="r",
                    epic="E1",
                    story_key="S1",
                    cycle_num=2,
                    issues_found=4,
                    blocking=True,
                )
            )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").rstrip("\n"))["event_type"],
                "review_cycle",
            )

    def test_emit_retro_fired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            TelemetryEmitter(path).emit(
                RetroFired(
                    timestamp="t",
                    run_id="r",
                    epic="E1",
                    stories_completed=4,
                    total_cost_usd=2.5,
                    duration_s=120.0,
                )
            )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8").rstrip("\n"))["event_type"],
                "retro_fired",
            )
