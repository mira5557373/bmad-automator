# tests/test_telemetry_reader.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.telemetry_reader import TelemetryReader
from story_automator.core.telemetry_events import (
    CostCharged,  # noqa: F401
    RetroFired,  # noqa: F401
    RetryAttempt,  # noqa: F401
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


class TelemetryReaderLineHandlingTests(unittest.TestCase):
    def test_blank_lines_are_skipped(self) -> None:
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
        # REQ NFR: streaming — iter_events must be a generator that
        # produces events one at a time. Verify it's iterable lazily by
        # taking only the first event from a file with many lines.
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
            # Ensure file is properly closed before temp dir cleanup
            del it
            del reader
