# tests/test_telemetry_reader.py
from __future__ import annotations

import json  # noqa: F401
import tempfile
import unittest
from pathlib import Path

from story_automator.core.telemetry_reader import TelemetryReader
from story_automator.core.telemetry_events import (
    CostCharged,  # noqa: F401
    RetroFired,  # noqa: F401
    RetryAttempt,  # noqa: F401
    StoryStarted,  # noqa: F401
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
