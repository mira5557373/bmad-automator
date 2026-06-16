"""Tests for the ``record-cost`` CLI command (critic Gap 3b ingestion).

Emits a ``CostCharged`` event to a temp project root, then reads the JSONL
back via ``TelemetryReader.cost_by_epic`` (and by parsing the raw line) to
assert the row is present with the right cost. Also covers the missing-args
and bad-float error paths. No network / subprocess / tmux.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.record_cost import cmd_record_cost
from story_automator.core.telemetry_events import CostCharged, parse_event
from story_automator.core.telemetry_reader import TelemetryReader


class RecordCostTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._prev_root = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = str(self.root)
        self.events_path = self.root / "telemetry" / "events.jsonl"

    def tearDown(self) -> None:
        if self._prev_root is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._prev_root
        self._tmp.cleanup()

    def _run(self, args: list[str]) -> tuple[int, dict]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cmd_record_cost(args)
        out = buf.getvalue().strip()
        payload = json.loads(out) if out else {}
        return code, payload

    def test_emits_cost_charged_row(self) -> None:
        code, payload = self._run(
            [
                "--epic", "E1",
                "--story-key", "E1.S2",
                "--phase", "dev",
                "--cost-usd", "1.25",
                "--tokens-in", "1000",
                "--tokens-out", "500",
                "--model", "claude-opus",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            payload,
            {
                "ok": True,
                "recorded": "cost_charged",
                "epic": "E1",
                "story_key": "E1.S2",
                "cost_usd": 1.25,
            },
        )

        # The JSONL file exists and the row round-trips into a CostCharged.
        self.assertTrue(self.events_path.is_file())
        lines = [
            ln for ln in self.events_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        self.assertEqual(len(lines), 1)
        event = parse_event(lines[0])
        self.assertIsInstance(event, CostCharged)
        self.assertEqual(event.epic, "E1")
        self.assertEqual(event.story_key, "E1.S2")
        self.assertEqual(event.phase, "dev")
        self.assertEqual(event.cost_usd, 1.25)
        self.assertEqual(event.tokens_in, 1000)
        self.assertEqual(event.tokens_out, 500)
        self.assertEqual(event.model, "claude-opus")

        # And the reader aggregation now sees nonzero spend (the Gap 3b fix).
        totals = TelemetryReader(self.events_path).cost_by_epic()
        self.assertEqual(totals, {"E1": 1.25})

    def test_multiple_rows_accumulate_by_epic(self) -> None:
        c1, _ = self._run(["--epic", "E9", "--story-key", "E9.S1", "--cost-usd", "2"])
        c2, _ = self._run(["--epic", "E9", "--story-key", "E9.S2", "--cost-usd", "0.5"])
        self.assertEqual((c1, c2), (0, 0))
        totals = TelemetryReader(self.events_path).cost_by_epic()
        self.assertAlmostEqual(totals["E9"], 2.5)

    def test_missing_epic_is_missing_args(self) -> None:
        code, payload = self._run(["--story-key", "E1.S1", "--cost-usd", "1.0"])
        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "missing_args"})
        self.assertFalse(self.events_path.exists())

    def test_missing_story_key_is_missing_args(self) -> None:
        code, payload = self._run(["--epic", "E1", "--cost-usd", "1.0"])
        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "missing_args"})
        self.assertFalse(self.events_path.exists())

    def test_bad_float_is_invalid_cost(self) -> None:
        code, payload = self._run(
            ["--epic", "E1", "--story-key", "E1.S1", "--cost-usd", "not-a-number"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error"], "invalid_cost")
        self.assertFalse(self.events_path.exists())

    def test_missing_cost_flag_is_invalid_cost(self) -> None:
        # --cost-usd omitted entirely: empty string fails float() too.
        code, payload = self._run(["--epic", "E1", "--story-key", "E1.S1"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_cost")
        self.assertFalse(self.events_path.exists())

    def test_token_defaults_when_absent(self) -> None:
        code, _ = self._run(["--epic", "E2", "--story-key", "E2.S1", "--cost-usd", "0.0"])
        self.assertEqual(code, 0)
        event = parse_event(
            self.events_path.read_text(encoding="utf-8").splitlines()[0]
        )
        assert isinstance(event, CostCharged)
        self.assertEqual(event.tokens_in, 0)
        self.assertEqual(event.tokens_out, 0)
        self.assertEqual(event.phase, "")
        self.assertEqual(event.model, "")


if __name__ == "__main__":
    unittest.main()
