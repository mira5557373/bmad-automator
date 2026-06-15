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
from story_automator.core.telemetry_events import StoryStarted


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
