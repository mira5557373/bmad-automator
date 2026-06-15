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
                        "event_type": "cost_charged",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E1",
                        "story_key": "S1",
                        "phase": "dev",
                        "cost_usd": 0.10,
                        "tokens_in": 10,
                        "tokens_out": 20,
                        "model": "m",
                    },
                    {
                        "event_type": "cost_charged",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E1",
                        "story_key": "S2",
                        "phase": "dev",
                        "cost_usd": 0.25,
                        "tokens_in": 10,
                        "tokens_out": 20,
                        "model": "m",
                    },
                    {
                        "event_type": "cost_charged",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E2",
                        "story_key": "S3",
                        "phase": "dev",
                        "cost_usd": 1.00,
                        "tokens_in": 10,
                        "tokens_out": 20,
                        "model": "m",
                    },
                    # Non-cost event must not contribute:
                    {
                        "event_type": "story_started",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E1",
                        "story_key": "Sx",
                        "agent": "a",
                        "model": "m",
                        "complexity": "c",
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
                        "event_type": "story_started",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E1",
                        "story_key": "S",
                        "agent": "a",
                        "model": "m",
                        "complexity": "c",
                    },
                ],
            )
            self.assertEqual(TelemetryReader(path).cost_by_epic(), {})


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
                        "event_type": "retry_attempt",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E1",
                        "story_key": "S1",
                        "attempt_num": 2,
                        "agent": "a",
                        "model": "m",
                        "prev_error_class": "x",
                    },
                    {
                        "event_type": "retry_attempt",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E1",
                        "story_key": "S1",
                        "attempt_num": 3,
                        "agent": "a",
                        "model": "m",
                        "prev_error_class": "x",
                    },
                    {
                        "event_type": "retry_attempt",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E2",
                        "story_key": "S9",
                        "attempt_num": 2,
                        "agent": "a",
                        "model": "m",
                        "prev_error_class": "x",
                    },
                    # Other types must not contribute:
                    {
                        "event_type": "cost_charged",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E1",
                        "story_key": "S1",
                        "phase": "dev",
                        "cost_usd": 0.01,
                        "tokens_in": 1,
                        "tokens_out": 1,
                        "model": "m",
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
                        "event_type": "retro_fired",
                        "timestamp": "2026-06-13T00:00:00Z",
                        "run_id": "r",
                        "epic": "E1",
                        "stories_completed": 1,
                        "total_cost_usd": 0.5,
                        "duration_s": 30.0,
                    },
                    {
                        "event_type": "retro_fired",
                        "timestamp": "2026-06-14T00:00:00Z",
                        "run_id": "r",
                        "epic": "E1",
                        "stories_completed": 4,
                        "total_cost_usd": 2.0,
                        "duration_s": 120.0,
                    },
                    {
                        "event_type": "retro_fired",
                        "timestamp": "2026-06-14T00:00:00Z",
                        "run_id": "r",
                        "epic": "E2",
                        "stories_completed": 7,
                        "total_cost_usd": 3.0,
                        "duration_s": 60.0,
                    },
                ],
            )
            reader = TelemetryReader(path)
            result = reader.retro_inputs("E1")
            self.assertEqual(
                result,
                {
                    "stories_completed": 4,
                    "total_cost_usd": 2.0,
                    "duration_s": 120.0,
                },
            )

    def test_retro_inputs_returns_empty_dict_when_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            self._write(
                path,
                [
                    {
                        "event_type": "retro_fired",
                        "timestamp": "t",
                        "run_id": "r",
                        "epic": "E1",
                        "stories_completed": 1,
                        "total_cost_usd": 0.5,
                        "duration_s": 30.0,
                    },
                ],
            )
            self.assertEqual(TelemetryReader(path).retro_inputs("E_other"), {})

    def test_retro_inputs_returns_empty_when_no_retro_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.touch()
            self.assertEqual(TelemetryReader(path).retro_inputs("E1"), {})
