from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from dataclasses import dataclass as _dc
from pathlib import Path

from story_automator.commands.calibration_cmd import cmd_calibration
from story_automator.core import telemetry_events as _events_mod
from story_automator.core.common import compact_json
from story_automator.core.telemetry_events import StoryCompleted, StoryFailed


def _run(args: list[str]) -> tuple[int, dict]:
    """Invoke cmd_calibration, capturing the single compact-JSON stdout line."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cmd_calibration(args)
    return code, json.loads(buffer.getvalue())


def _completed_line(timestamp: str, model_id: str, task_kind: str) -> str:
    event = StoryCompleted(
        timestamp=timestamp,
        run_id="r",
        epic="EP-1",
        story_key="S-1",
        duration_s=100.0,
        cost_usd=0.5,
        tokens_in=1000,
        tokens_out=200,
        attempts=1,
    )
    payload = event.to_dict()
    payload["model_id"] = model_id
    payload["task_kind"] = task_kind
    return compact_json(payload)


def _failed_line(timestamp: str, model_id: str, task_kind: str) -> str:
    event = StoryFailed(
        timestamp=timestamp,
        run_id="r",
        epic="EP-1",
        story_key="S-1",
        error_class="TimeoutError",
        reason="exceeded",
        attempts=5,
        final_session="sess-1",
    )
    payload = event.to_dict()
    payload["model_id"] = model_id
    payload["task_kind"] = task_kind
    return compact_json(payload)


def _e2e_snapshot_lines() -> list[str]:
    return [
        _completed_line("2026-06-14T10:00:00Z", "claude-opus-4", "code"),
        _completed_line("2026-06-14T10:01:00Z", "claude-opus-4", "code"),
        _failed_line("2026-06-14T10:02:00Z", "claude-opus-4", "code"),
        _completed_line("2026-06-14T10:03:00Z", "gpt-5-codex", "review"),
    ]


def _e2e_snapshot_expected(ledger: Path) -> str:
    return (
        f"source: {ledger}\n"
        "model_id\ttask_kind\tsuccess_rate\tsample_count\tlast_seen_iso\n"
        "claude-opus-4\tcode\t0.6667\t3\t2026-06-14T10:02:00Z\n"
        "gpt-5-codex\treview\t1.0000\t1\t2026-06-14T10:03:00Z\n"
    )


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


class _ExtendedEventShim:
    """Temporarily widen StoryCompleted/StoryFailed so fixtures can carry
    `model_id`/`task_kind` without an M01 change (mirrors the M08 test
    scaffold in skills/.../tests/_calibration_fixtures.py). Restored in
    tearDownClass.
    """

    _saved: dict[str, type] = {}

    @classmethod
    def install(cls) -> None:
        cls._saved = {
            "StoryCompleted": _events_mod.StoryCompleted,
            "StoryFailed": _events_mod.StoryFailed,
        }
        _events_mod.Event._REGISTRY.pop("story_completed", None)
        _events_mod.Event._REGISTRY.pop("story_failed", None)
        new_completed = cls._widen(_events_mod.StoryCompleted, "story_completed")
        new_failed = cls._widen(_events_mod.StoryFailed, "story_failed")
        _events_mod.StoryCompleted = new_completed
        _events_mod.StoryFailed = new_failed
        import story_automator.core.calibration as cal_mod

        cal_mod.StoryCompleted = new_completed
        cal_mod.StoryFailed = new_failed

    @classmethod
    def uninstall(cls) -> None:
        _events_mod.Event._REGISTRY.pop("story_completed", None)
        _events_mod.Event._REGISTRY.pop("story_failed", None)
        _events_mod.StoryCompleted = cls._saved["StoryCompleted"]
        _events_mod.StoryFailed = cls._saved["StoryFailed"]
        _events_mod.Event._REGISTRY["story_completed"] = cls._saved["StoryCompleted"]
        _events_mod.Event._REGISTRY["story_failed"] = cls._saved["StoryFailed"]
        import story_automator.core.calibration as cal_mod

        cal_mod.StoryCompleted = cls._saved["StoryCompleted"]
        cal_mod.StoryFailed = cls._saved["StoryFailed"]

    @staticmethod
    def _widen(base: type, event_type: str) -> type:
        @_dc(kw_only=True)
        class _Widened(base):  # type: ignore[misc, valid-type]
            model_id: str = ""
            task_kind: str = ""

        _Widened.__name__ = base.__name__
        _Widened.__qualname__ = base.__qualname__
        _Widened.EVENT_TYPE = event_type
        _events_mod.Event._REGISTRY[event_type] = _Widened
        return _Widened


class _ShimmedCmdCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ExtendedEventShim.install()

    @classmethod
    def tearDownClass(cls) -> None:
        _ExtendedEventShim.uninstall()


class CalibrationCmdMissingLedgerTests(unittest.TestCase):
    def test_missing_ledger_is_ok_with_empty_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nope.jsonl"
            code, parsed = _run(["--events", str(missing)])

        self.assertEqual(code, 0)
        self.assertIs(parsed["ok"], True)
        self.assertEqual(parsed["entries"], [])
        self.assertEqual(parsed["total_events_scanned"], 0)
        self.assertEqual(parsed["source_path"], str(missing))


class CalibrationCmdEmptyLedgerTests(unittest.TestCase):
    def test_empty_ledger_is_ok_with_empty_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "events.jsonl"
            ledger.write_text("", encoding="utf-8")
            code, parsed = _run(["--events", str(ledger)])

        self.assertEqual(code, 0)
        self.assertIs(parsed["ok"], True)
        self.assertEqual(parsed["entries"], [])
        self.assertEqual(parsed["total_events_scanned"], 0)


class CalibrationCmdAggregationTests(_ShimmedCmdCase):
    def test_entries_sorted_and_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "events.jsonl"
            _write_jsonl(ledger, _e2e_snapshot_lines())
            code, parsed = _run(["--events", str(ledger)])

        self.assertEqual(code, 0)
        self.assertIs(parsed["ok"], True)
        self.assertEqual(parsed["total_events_scanned"], 4)
        self.assertEqual(
            parsed["entries"],
            [
                {
                    "model_id": "claude-opus-4",
                    "task_kind": "code",
                    "success_rate": 0.6667,
                    "sample_count": 3,
                    "last_seen_iso": "2026-06-14T10:02:00Z",
                },
                {
                    "model_id": "gpt-5-codex",
                    "task_kind": "review",
                    "success_rate": 1.0,
                    "sample_count": 1,
                    "last_seen_iso": "2026-06-14T10:03:00Z",
                },
            ],
        )


class CalibrationCmdReportFlagTests(_ShimmedCmdCase):
    def test_report_flag_includes_report_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "events.jsonl"
            _write_jsonl(ledger, _e2e_snapshot_lines())
            code, parsed = _run(["--events", str(ledger), "--report"])

        self.assertEqual(code, 0)
        self.assertIn("report", parsed)
        self.assertEqual(parsed["report"], _e2e_snapshot_expected(ledger))

    def test_report_absent_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "events.jsonl"
            _write_jsonl(ledger, _e2e_snapshot_lines())
            code, parsed = _run(["--events", str(ledger)])

        self.assertEqual(code, 0)
        self.assertNotIn("report", parsed)


class CalibrationCmdLookupFlagTests(_ShimmedCmdCase):
    def test_lookup_hit_returns_stored_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "events.jsonl"
            _write_jsonl(ledger, _e2e_snapshot_lines())
            code, parsed = _run(
                ["--events", str(ledger), "--model", "claude-opus-4", "--task", "code"]
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            parsed["lookup"],
            {
                "model_id": "claude-opus-4",
                "task_kind": "code",
                "success_rate": 0.6667,
            },
        )

    def test_lookup_miss_returns_default_half(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "events.jsonl"
            _write_jsonl(ledger, _e2e_snapshot_lines())
            code, parsed = _run(
                ["--events", str(ledger), "--model", "x", "--task", "y"]
            )

        self.assertEqual(code, 0)
        self.assertEqual(parsed["lookup"]["success_rate"], 0.5)

    def test_lookup_absent_without_model_and_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "events.jsonl"
            _write_jsonl(ledger, _e2e_snapshot_lines())
            code, parsed = _run(["--events", str(ledger)])

        self.assertEqual(code, 0)
        self.assertNotIn("lookup", parsed)


class CalibrationCmdDefaultPathTests(_ShimmedCmdCase):
    def setUp(self) -> None:
        self._saved_root = os.environ.get("PROJECT_ROOT")

    def tearDown(self) -> None:
        if self._saved_root is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self._saved_root

    def test_default_path_resolves_under_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["PROJECT_ROOT"] = tmpdir
            ledger = Path(tmpdir) / "telemetry" / "events.jsonl"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            _write_jsonl(ledger, _e2e_snapshot_lines())
            code, parsed = _run([])

        self.assertEqual(code, 0)
        self.assertIs(parsed["ok"], True)
        self.assertTrue(
            parsed["source_path"].endswith(os.path.join("telemetry", "events.jsonl"))
        )
        self.assertEqual(len(parsed["entries"]), 2)


class CalibrationCmdDispatchTests(unittest.TestCase):
    """Wiring-readiness checks. The controller registers `calibration` in
    cli.py separately; this command module must not edit cli.py. These tests
    therefore prove the entry point is a wireable `Callable[[list[str]], int]`
    that returns 0 and emits valid JSON, without asserting the dispatch table
    (which is wired by the controller in a separate change).
    """

    def test_cmd_calibration_is_callable(self) -> None:
        self.assertTrue(callable(cmd_calibration))

    def test_entry_point_returns_int_and_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nope.jsonl"
            code, parsed = _run(["--events", str(missing)])

        self.assertIsInstance(code, int)
        self.assertEqual(code, 0)
        self.assertIs(parsed["ok"], True)

    def test_dispatch_wired_when_registered(self) -> None:
        # If/when the controller wires `calibration` into cli.py, exercise the
        # full dispatch path. Skip cleanly while it is not yet registered so
        # this module's own test suite stays green pre-wiring.
        from story_automator.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nope.jsonl"
            err = io.StringIO()
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["calibration", "--events", str(missing)])
            if "Unknown command" in err.getvalue():
                self.skipTest("calibration not yet wired into cli.py dispatch")
            self.assertEqual(code, 0)
            parsed = json.loads(out.getvalue())
            self.assertIs(parsed["ok"], True)


if __name__ == "__main__":
    unittest.main()
