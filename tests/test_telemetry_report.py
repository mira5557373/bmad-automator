from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from story_automator.core.common import compact_json, ensure_dir
from story_automator.core.telemetry_events import CostCharged, RetroFired, RetryAttempt


def _capture(callable_, *args, **kwargs):
    """Run ``callable_(*args, **kwargs)`` with stdout redirected to a
    string buffer and return ``(exit_code, parsed_json)``."""
    buf = io.StringIO()
    with mock.patch.object(sys, "stdout", buf):
        code = callable_(*args, **kwargs)
    text = buf.getvalue().strip()
    payload = json.loads(text) if text else {}
    return code, payload


def _write_ledger(tmp: str, events: list[object]) -> Path:
    ensure_dir(tmp)
    path = Path(tmp) / "events.jsonl"
    body = "\n".join(compact_json(ev.to_dict()) for ev in events)
    if events:
        body += "\n"
    path.write_text(body, encoding="utf-8")
    return path


def _cost(epic: str, cost: float, ts: str = "2026-06-15T00:00:00Z") -> CostCharged:
    return CostCharged(
        timestamp=ts,
        run_id="r1",
        epic=epic,
        story_key="S1",
        phase="impl",
        cost_usd=cost,
        tokens_in=0,
        tokens_out=0,
        model="opus",
    )


def _retry(
    epic: str, story_key: str, attempt_num: int, ts: str = "2026-06-15T00:00:00Z"
) -> RetryAttempt:
    return RetryAttempt(
        timestamp=ts,
        run_id="r1",
        epic=epic,
        story_key=story_key,
        attempt_num=attempt_num,
        agent="dev",
        model="opus",
        prev_error_class="Timeout",
    )


def _retro(
    epic: str,
    stories_completed: int,
    total_cost_usd: float = 9.0,
    duration_s: float = 120.0,
    ts: str = "2026-06-15T00:00:00Z",
) -> RetroFired:
    return RetroFired(
        timestamp=ts,
        run_id="r1",
        epic=epic,
        stories_completed=stories_completed,
        total_cost_usd=total_cost_usd,
        duration_s=duration_s,
    )


class TelemetryReportSurfaceTests(unittest.TestCase):
    def test_command_module_is_importable(self) -> None:
        from story_automator.commands.telemetry_report import (  # noqa: F401
            cmd_telemetry_report,
        )

    def test_entry_point_matches_command_signature(self) -> None:
        """The dispatch wiring in cli.py is added by the controller in a
        separate step (this milestone only ships the command + test
        files). Assert the entry point satisfies the
        ``Command = Callable[[list[str]], int]`` contract so it slots into
        the dispatch dict cleanly once wired: callable, accepts a single
        ``list[str]`` positional, and returns an ``int``."""
        import inspect

        from story_automator.commands.telemetry_report import cmd_telemetry_report

        self.assertTrue(callable(cmd_telemetry_report))
        params = list(inspect.signature(cmd_telemetry_report).parameters.values())
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0].kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        # A bogus report is the cheapest path that exercises the full
        # entry point and confirms it returns an int (the dispatch dict's
        # handlers feed their return straight back as the process exit code).
        code, _ = _capture(cmd_telemetry_report, ["--report", "bogus"])
        self.assertIsInstance(code, int)


class TelemetryReportFlagParseTests(unittest.TestCase):
    def test_invalid_report_returns_structured_error(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        code, payload = _capture(cmd_telemetry_report, ["--report", "bogus"])
        self.assertEqual(code, 1)
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error"), "invalid_report")
        self.assertEqual(payload.get("report"), "bogus")

    def test_missing_epic_for_retro_returns_error(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        code, payload = _capture(cmd_telemetry_report, ["--report", "retro_inputs"])
        self.assertEqual(code, 1)
        self.assertEqual(payload.get("error"), "missing_epic")


class TelemetryReportAggregationTests(unittest.TestCase):
    def test_cost_by_epic_sums_per_epic(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            ledger = _write_ledger(
                tmp, [_cost("E1", 1.5), _cost("E1", 1.5), _cost("E2", 3.0)]
            )
            code, payload = _capture(
                cmd_telemetry_report,
                ["--report", "cost_by_epic", "--events", str(ledger)],
            )
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cost_by_epic"], {"E1": 3.0, "E2": 3.0})

    def test_attempts_by_story_counts_and_is_json_safe(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            ledger = _write_ledger(
                tmp,
                [
                    _retry("E1", "S1", 2),
                    _retry("E1", "S1", 3),
                    _retry("E1", "S1", 4),
                    _retry("E1", "S2", 2),
                ],
            )
            code, payload = _capture(
                cmd_telemetry_report,
                ["--report", "attempts_by_story", "--events", str(ledger)],
            )
        self.assertEqual(code, 0)
        attempts = payload["attempts_by_story"]
        self.assertIsInstance(attempts, list)
        self.assertIn({"epic": "E1", "story_key": "S1", "attempts": 3}, attempts)
        self.assertIn({"epic": "E1", "story_key": "S2", "attempts": 1}, attempts)
        # Round-trips through json -> proves the tuple-key transform happened.
        self.assertEqual(json.loads(json.dumps(attempts)), attempts)

    def test_retro_inputs_returns_latest_for_epic(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            ledger = _write_ledger(
                tmp,
                [
                    _retro("E1", stories_completed=2, ts="2026-06-15T00:00:00Z"),
                    _retro("E1", stories_completed=4, ts="2026-06-15T01:00:00Z"),
                ],
            )
            code, payload = _capture(
                cmd_telemetry_report,
                ["--report", "retro_inputs", "--epic", "E1", "--events", str(ledger)],
            )
        self.assertEqual(code, 0)
        self.assertEqual(payload["epic"], "E1")
        self.assertEqual(payload["retro_inputs"]["stories_completed"], 4)

    def test_retro_inputs_unknown_epic_returns_empty(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            ledger = _write_ledger(tmp, [_retro("E1", stories_completed=2)])
            code, payload = _capture(
                cmd_telemetry_report,
                ["--report", "retro_inputs", "--epic", "NOPE", "--events", str(ledger)],
            )
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["retro_inputs"], {})

    def test_report_all_includes_three_sections(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            ledger = _write_ledger(
                tmp,
                [
                    _cost("E1", 2.0),
                    _retry("E1", "S1", 2),
                    _retro("E1", stories_completed=3),
                ],
            )
            code, payload = _capture(
                cmd_telemetry_report,
                ["--report", "all", "--epic", "E1", "--events", str(ledger)],
            )
        self.assertEqual(code, 0)
        self.assertEqual(payload["report"], "all")
        self.assertIn("cost_by_epic", payload)
        self.assertIn("attempts_by_story", payload)
        self.assertIn("retro_inputs", payload)
        self.assertEqual(payload["retro_inputs"]["E1"]["stories_completed"], 3)

    def test_report_all_without_epic_sets_retro_null(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            ledger = _write_ledger(tmp, [_cost("E1", 2.0)])
            code, payload = _capture(
                cmd_telemetry_report,
                ["--events", str(ledger)],
            )
        self.assertEqual(code, 0)
        self.assertEqual(payload["report"], "all")
        self.assertIsNone(payload["retro_inputs"])
        self.assertIn("retro_note", payload)


class TelemetryReportMissingFileTests(unittest.TestCase):
    def test_missing_events_file_returns_empty_ok(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "no-such.jsonl")
            code, payload = _capture(
                cmd_telemetry_report,
                ["--report", "cost_by_epic", "--events", missing],
            )
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cost_by_epic"], {})


class TelemetryReportDefaultPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prior = os.environ.get("PROJECT_ROOT")

    def tearDown(self) -> None:
        if self._prior is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._prior

    def test_default_events_path_uses_project_root(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            os.environ["PROJECT_ROOT"] = tmp
            telemetry_dir = Path(tmp) / "telemetry"
            ensure_dir(telemetry_dir)
            _write_ledger(str(telemetry_dir), [_cost("E1", 4.0)])
            code, payload = _capture(
                cmd_telemetry_report,
                ["--report", "cost_by_epic"],
            )
        self.assertEqual(code, 0)
        self.assertTrue(
            payload["events"].endswith(os.path.join("telemetry", "events.jsonl"))
        )
        self.assertEqual(payload["cost_by_epic"], {"E1": 4.0})


class TelemetryReportCorruptionTests(unittest.TestCase):
    def test_corrupt_line_surfaces_structured_error(self) -> None:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text("{not json\n", encoding="utf-8")
            code, payload = _capture(
                cmd_telemetry_report,
                ["--report", "cost_by_epic", "--events", str(path)],
            )
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "corrupt_telemetry")
        self.assertIn("detail", payload)


if __name__ == "__main__":
    unittest.main()
