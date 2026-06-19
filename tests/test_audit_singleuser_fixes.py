"""Regression tests for the single-user audit-fix pass (docs/audit/2026-06-19).

One test (or small cluster) per fixed finding, named with its F-id so the
mapping back to the audit backlog stays obvious.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.core.common import compact_json


def _write(text: str, suffix: str = ".md") -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


class F001CalibrationCorrelation(unittest.TestCase):
    """build_calibration populates from real M01 events via StoryStarted join."""

    def _line(self, event) -> str:
        return compact_json(event.to_dict())

    def test_real_events_populate_table_by_model_and_complexity(self) -> None:
        from story_automator.core.calibration import build_calibration
        from story_automator.core.telemetry_events import (
            StoryCompleted,
            StoryFailed,
            StoryStarted,
        )

        lines = [
            self._line(StoryStarted(
                timestamp="2026-06-19T10:00:00Z", run_id="r1", epic="E1",
                story_key="1.1", agent="claude", model="opus", complexity="low",
            )),
            self._line(StoryCompleted(
                timestamp="2026-06-19T10:05:00Z", run_id="r1", epic="E1",
                story_key="1.1", duration_s=10.0, cost_usd=0.1, tokens_in=1,
                tokens_out=1, attempts=1,
            )),
            self._line(StoryStarted(
                timestamp="2026-06-19T11:00:00Z", run_id="r2", epic="E1",
                story_key="1.2", agent="claude", model="opus", complexity="low",
            )),
            self._line(StoryFailed(
                timestamp="2026-06-19T11:05:00Z", run_id="r2", epic="E1",
                story_key="1.2", error_class="X", reason="boom", attempts=3,
                final_session="s",
            )),
        ]
        ledger = _write("\n".join(lines) + "\n", suffix=".jsonl")
        table = build_calibration(ledger)

        self.assertIn(("opus", "low"), table.entries)
        entry = table.entries[("opus", "low")]
        self.assertEqual(entry.sample_count, 2)
        self.assertEqual(entry.success_rate, 0.5)  # 1 completed / 1 failed

    def test_completion_without_matching_started_is_skipped(self) -> None:
        from story_automator.core.calibration import build_calibration
        from story_automator.core.telemetry_events import StoryCompleted

        line = self._line(StoryCompleted(
            timestamp="2026-06-19T10:05:00Z", run_id="orphan", epic="E1",
            story_key="9.9", duration_s=10.0, cost_usd=0.1, tokens_in=1,
            tokens_out=1, attempts=1,
        ))
        ledger = _write(line + "\n", suffix=".jsonl")
        table = build_calibration(ledger)
        self.assertEqual(table.entries, {})
        self.assertEqual(table.total_events_scanned, 1)


class F015IsStaleOffsetHeartbeat(unittest.TestCase):
    def test_offset_heartbeat_does_not_crash(self) -> None:
        from story_automator.core.atomic_io import RunLockIdentity, is_stale

        identity = RunLockIdentity(
            pid=999999, start_time=0.0, hostname="foreign-host",
            heartbeat_iso="2026-01-01T00:00:00+00:00", run_id="r",
        )
        # Previously raised ValueError; now treated as fresh (not reclaimable).
        self.assertIs(is_stale(identity), False)


class F016EscalationPolicy(unittest.TestCase):
    def test_policy_message_upgrades_to_policy_violation(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify
        from story_automator.core.telemetry_events import EscalationTriggered

        event = EscalationTriggered(
            timestamp="t", run_id="r", epic="E1", story_key="1.1",
            trigger_id=1, severity="high", message="policy:cost_violation",
        )
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)


class F017AgentConfigNonDictOverrides(unittest.TestCase):
    def test_non_dict_complexity_overrides_does_not_crash(self) -> None:
        from story_automator.core.agent_config import parse_agent_config_json

        for blob in ('{"complexityOverrides":[1,2,3]}', '{"complexityOverrides":"x"}', '"top-level-string"', "[1,2]"):
            config = parse_agent_config_json(blob)
            self.assertEqual(config.complexity_overrides, {})

    def test_non_dict_presets_file_returns_default(self) -> None:
        from story_automator.core.agent_config import load_presets_file

        path = _write("[1, 2, 3]", suffix=".json")
        data = load_presets_file(path)
        self.assertEqual(data, {"version": "1.0.0", "presets": []})


class F034UpdateFrontmatterBounded(unittest.TestCase):
    def test_body_line_matching_key_is_not_rewritten(self) -> None:
        from story_automator.core.frontmatter import update_simple_frontmatter

        path = _write("---\nstatus: open\n---\n\nstatus: a body sentence\n")
        updated = update_simple_frontmatter(path, {"status": "closed"})
        text = path.read_text(encoding="utf-8")
        self.assertEqual(updated, ["status"])
        self.assertIn("status: closed", text)
        self.assertIn("status: a body sentence", text)  # body untouched

    def test_bare_leading_block_still_updates(self) -> None:
        from story_automator.core.frontmatter import update_simple_frontmatter

        path = _write("status: open\nepic: 1\n\nstatus: body\n")
        update_simple_frontmatter(path, {"status": "done"})
        text = path.read_text(encoding="utf-8")
        self.assertIn("status: done", text)
        self.assertIn("status: body", text)


class F037ExtractLastAction(unittest.TestCase):
    def test_returns_last_action_not_first(self) -> None:
        from story_automator.core.frontmatter import extract_last_action

        path = _write("## Action Log\n\n- step 1\n- step 2\n- step 3\n")
        self.assertEqual(extract_last_action(path), "step 3")

    def test_stops_at_next_section(self) -> None:
        from story_automator.core.frontmatter import extract_last_action

        path = _write("## Action Log\n\n- a\n- b\n\n## Other\n\n- z\n")
        self.assertEqual(extract_last_action(path), "b")


class F054ExtractJsonBlock(unittest.TestCase):
    def test_trailing_prose_and_nested(self) -> None:
        from story_automator.core import agent_config, frontmatter

        for mod in (frontmatter, agent_config):
            self.assertEqual(mod.extract_json_block('{"valid":true} and prose'), '{"valid":true}')
            self.assertEqual(mod.extract_json_block('{"a":{"b":1}}'), '{"a":{"b":1}}')
            self.assertEqual(
                mod.extract_json_block('```json\n{"a": {"b": 1}}\n```'),
                '{"a": {"b": 1}}',
            )
            self.assertEqual(mod.extract_json_block("no json"), "")


class F053FilterInputBox(unittest.TestCase):
    def test_markdown_table_rows_survive_orphan_box_start(self) -> None:
        from story_automator.core import common, utils

        sample = "╭─ box\n| col1 | col2 |\n| a | b |\n"
        for mod in (common, utils):
            kept = mod.filter_input_box(sample)
            self.assertIn("| col1 | col2 |", kept)
            self.assertIn("| a | b |", kept)

    def test_real_box_drawing_lines_still_filtered(self) -> None:
        from story_automator.core import common, utils

        sample = "╭─ box\n│ inside the box\n╰─ end\nkept line\n"
        for mod in (common, utils):
            kept = mod.filter_input_box(sample)
            self.assertNotIn("inside the box", kept)
            self.assertIn("kept line", kept)


class F036CompletionMarker(unittest.TestCase):
    def test_log_line_with_trailing_prose_is_not_a_marker(self) -> None:
        from story_automator.core.tmux_runtime import _claude_completion_marker_present

        self.assertFalse(_claude_completion_marker_present("Tested for 3m 12s. Now starting next task."))
        self.assertFalse(_claude_completion_marker_present("Started for 3m 12s. continuing"))

    def test_real_spinner_lines_still_detected(self) -> None:
        from story_automator.core.tmux_runtime import _claude_completion_marker_present

        self.assertTrue(_claude_completion_marker_present("Finished for 2m"))
        self.assertTrue(_claude_completion_marker_present("Story\n\n✻ Cogitated for 3m 45s\n\n❯ "))


class F039StateNonDictConfig(unittest.TestCase):
    def test_non_dict_config_json_returns_structured_error(self) -> None:
        from story_automator.commands.state import cmd_build_state_doc

        with tempfile.TemporaryDirectory() as d:
            template = Path(d) / "template.md"
            template.write_text("---\nepic: {{epic}}\n---\n", encoding="utf-8")
            out = Path(d) / "out"
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = cmd_build_state_doc([
                    "--template", str(template),
                    "--output-folder", str(out),
                    "--config-json", '"a bare string"',
                ])
            payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 1)
        self.assertIs(payload["ok"], False)
        self.assertEqual(payload["error"], "missing_config")


class F052TelemetryTail(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, dict]:
        from story_automator.commands.telemetry_report import cmd_telemetry_report

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cmd_telemetry_report(args)
        return code, json.loads(buffer.getvalue())

    def test_tail_returns_recent_events_and_tolerates_corruption(self) -> None:
        ledger = _write(
            '{"event_type":"story_started","timestamp":"t","run_id":"r","epic":"E",'
            '"story_key":"1.1","agent":"claude","model":"opus","complexity":"low"}\n'
            "NOT-JSON\n",
            suffix=".jsonl",
        )
        code, payload = self._run(["--events", str(ledger), "--tail", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["report"], "tail")
        self.assertEqual(len(payload["recent"]), 2)
        self.assertTrue(payload["recent"][1]["_corrupt"])

    def test_invalid_tail_is_structured_error(self) -> None:
        ledger = _write("", suffix=".jsonl")
        code, payload = self._run(["--events", str(ledger), "--tail", "abc"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_tail")

    def test_normal_report_still_fails_loud_on_corruption(self) -> None:
        ledger = _write("NOT-JSON\n", suffix=".jsonl")
        code, payload = self._run(["--events", str(ledger), "--report", "cost_by_epic"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "corrupt_telemetry")


if __name__ == "__main__":
    unittest.main()
