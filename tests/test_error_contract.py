# tests/test_error_contract.py
"""Wave A: the CLI must always honor its machine-readable error contract.

Every command the orchestrator step scripts shell out to parses stdout as JSON.
A handler that raises an uncaught exception leaks a Python traceback to stderr
and emits no JSON, silently breaking the calling workflow. These tests lock in
the structured-error behavior for the trivially-malformed-input paths that
previously crashed, plus the top-level backstop in cli.main.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator import cli
from story_automator.commands import orchestrator
from story_automator.core.epic_parser import parse_story
from story_automator.core.runtime_layout import active_marker_path
from story_automator.core.telemetry_emitter import TelemetryEmitter


def _run_main(argv: list[str]) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli.main(argv)
    return code, json.loads(buffer.getvalue())


def _run_cmd(fn, args: list[str]) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = fn(args)
    return code, json.loads(buffer.getvalue())


class ParseRangeContractTests(unittest.TestCase):
    def test_non_numeric_total_yields_structured_error_not_traceback(self) -> None:
        code, payload = _run_main(["parse-story-range", "--input", "1-3", "--total", "abc"])
        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "missing_input_or_total"})


class ParseStoryRulesContractTests(unittest.TestCase):
    def _write_epic(self, root: Path) -> Path:
        epic = root / "epic.md"
        epic.write_text(
            "# Epic One\n## Epic 1: First\n### Story 1.1: Title\nAcceptance Criteria\n- Works\n",
            encoding="utf-8",
        )
        return epic

    def test_non_dict_rules_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            epic = self._write_epic(root)
            rules = root / "rules.json"
            rules.write_text("[]", encoding="utf-8")  # valid JSON, not an object
            with self.assertRaises(ValueError) as ctx:
                parse_story(epic, "1.1", rules)
            self.assertEqual(str(ctx.exception), "invalid_rules_file")

    def test_non_dict_rules_surfaces_structured_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            epic = self._write_epic(root)
            rules = root / "rules.json"
            rules.write_text("[]", encoding="utf-8")
            code, payload = _run_main(
                ["parse-story", "--epic", str(epic), "--story", "1.1", "--rules", str(rules)]
            )
            self.assertEqual(code, 1)
            self.assertEqual(payload, {"ok": False, "error": "invalid_rules_file"})


class MarkerCorruptionContractTests(unittest.TestCase):
    def _heartbeat(self, tmp: Path, marker_body: str) -> tuple[int, dict]:
        marker = active_marker_path(str(tmp))
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(marker_body, encoding="utf-8")
        with mock.patch.object(orchestrator, "get_project_root", return_value=str(tmp)):
            return _run_cmd(orchestrator._marker, ["heartbeat"])

    def test_heartbeat_on_corrupt_json_marker_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            code, payload = self._heartbeat(Path(d), "{ not json")
            self.assertEqual(code, 1)
            self.assertEqual(payload, {"exists": True, "error": "marker_corrupt"})

    def test_heartbeat_on_non_dict_marker_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            code, payload = self._heartbeat(Path(d), "[]")
            self.assertEqual(code, 1)
            self.assertEqual(payload, {"exists": True, "error": "marker_corrupt"})


class MarkerCreateNumericContractTests(unittest.TestCase):
    def test_non_numeric_remaining_and_pid_default_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            emitter = TelemetryEmitter(tmp / "events.jsonl")
            with (
                mock.patch.object(orchestrator, "get_project_root", return_value=str(tmp)),
                mock.patch.object(
                    orchestrator, "emitter_for_project_root", side_effect=lambda _r: emitter
                ),
            ):
                code = orchestrator._marker(
                    [
                        "create",
                        "--epic", "1",
                        "--story", "1.1",
                        "--remaining", "N",  # unexpanded shell var
                        "--pid", "xyz",
                        "--state-file", str(tmp / "state.md"),
                    ]
                )
            self.assertEqual(code, 0)
            marker = json.loads(active_marker_path(str(tmp)).read_text(encoding="utf-8"))
            self.assertEqual(marker["storiesRemaining"], 0)
            self.assertEqual(marker["pid"], 0)


class StateUpdateOperandContractTests(unittest.TestCase):
    def test_set_without_equals_yields_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / "orchestration-1.md"
            state.write_text("---\nstatus: active\n---\n", encoding="utf-8")
            code, payload = _run_cmd(orchestrator._state_update, [str(state), "--set", "foo"])
            self.assertEqual(code, 1)
            self.assertEqual(
                payload, {"ok": False, "error": "invalid_set_operand", "operand": "foo"}
            )


class TopLevelBoundaryTests(unittest.TestCase):
    def test_unexpected_handler_exception_becomes_internal_error(self) -> None:
        def _boom(_args: list[str]) -> int:
            raise RuntimeError("kaboom")

        with mock.patch.object(cli, "_command_registry", return_value={"boom": _boom}):
            code, payload = _run_main(["boom"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error"], "internal_error")
        self.assertEqual(payload["command"], "boom")
        self.assertIn("kaboom", payload["detail"])


if __name__ == "__main__":
    unittest.main()
