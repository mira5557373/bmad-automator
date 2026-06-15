# tests/test_telemetry_emitter.py
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

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
