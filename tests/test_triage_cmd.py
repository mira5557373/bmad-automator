from __future__ import annotations

import io
import json
import sys
import unittest
import unittest.mock as mock

from story_automator.core.common import compact_json
from story_automator.core.failure_triage import Confidence, FailureClass
from story_automator.core.telemetry_events import (
    EscalationTriggered,
    StoryCompleted,
    StoryDeferred,
    StoryFailed,
    TmuxSessionCrashed,
)


def _capture(callable_, *args, **kwargs):
    """Run ``callable_(*args, **kwargs)`` with stdout redirected to a
    string buffer and return ``(exit_code, parsed_json)``."""
    buf = io.StringIO()
    with mock.patch.object(sys, "stdout", buf):
        code = callable_(*args, **kwargs)
    text = buf.getvalue().strip()
    payload = json.loads(text) if text else {}
    return code, payload


def _story_failed(reason: str, error_class: str = "") -> StoryFailed:
    return StoryFailed(
        timestamp="2026-06-15T00:00:00Z",
        run_id="r1",
        epic="E1",
        story_key="S1",
        error_class=error_class,
        reason=reason,
        attempts=3,
        final_session="sess-1",
    )


def _story_deferred(reason: str) -> StoryDeferred:
    return StoryDeferred(
        timestamp="2026-06-15T00:00:00Z",
        run_id="r1",
        epic="E1",
        story_key="S1",
        reason=reason,
        tasks_completed=2,
    )


def _tmux_crash() -> TmuxSessionCrashed:
    return TmuxSessionCrashed(
        timestamp="2026-06-15T00:00:00Z",
        run_id="r1",
        session_name="sess-1",
        story_key="S1",
        exit_code=137,
        last_capture_chars=512,
    )


def _escalation() -> EscalationTriggered:
    return EscalationTriggered(
        timestamp="2026-06-15T00:00:00Z",
        run_id="r1",
        epic="E1",
        story_key="S1",
        trigger_id=4,
        severity="high",
        message="needs human review",
    )


def _story_completed() -> StoryCompleted:
    return StoryCompleted(
        timestamp="2026-06-15T00:00:00Z",
        run_id="r1",
        epic="E1",
        story_key="S1",
        duration_s=1.0,
        cost_usd=0.5,
        tokens_in=10,
        tokens_out=20,
        attempts=1,
    )


class CmdTriageSurfaceTests(unittest.TestCase):
    def test_command_module_is_importable(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage  # noqa: F401

    def test_entry_point_signature(self) -> None:
        """``cmd_triage`` must satisfy ``Command = Callable[[list[str]], int]``
        so the controller can register it in the cli.py dispatch dict.
        (The dispatch wiring itself lands separately in cli.py; this test
        only asserts the entry point is callable with a list and returns an
        int, decoupled from the controller's wiring step.)"""
        from story_automator.commands.triage_cmd import cmd_triage

        line = compact_json(_story_failed("connection timeout").to_dict())
        code, _ = _capture(cmd_triage, ["--json", line])
        self.assertIsInstance(code, int)


class CmdTriageClassifyTests(unittest.TestCase):
    def _run(self, event) -> tuple[int, dict]:
        from story_automator.commands.triage_cmd import cmd_triage

        line = compact_json(event.to_dict())
        return _capture(cmd_triage, ["--json", line])

    def test_story_failed_timeout(self) -> None:
        code, payload = self._run(_story_failed("connection timeout"))
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["failure_class"], "TIMEOUT")
        self.assertEqual(payload["confidence"], "HIGH")
        self.assertEqual(payload["implies"], [])

    def test_story_failed_policy(self) -> None:
        code, payload = self._run(_story_failed("blocked by policy"))
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "POLICY_VIOLATION")
        self.assertEqual(payload["confidence"], "HIGH")
        self.assertEqual(payload["implies"], ["REVIEW_REJECTED"])

    def test_story_failed_test(self) -> None:
        code, payload = self._run(_story_failed("pytest suite failed"))
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "TEST_FAILURE")

    def test_story_deferred_plateau(self) -> None:
        code, payload = self._run(_story_deferred("plateau detected"))
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "REPEATED_RETRY")
        self.assertEqual(payload["implies"], ["PLATEAU"])

    def test_story_deferred_capped(self) -> None:
        code, payload = self._run(_story_deferred("capped"))
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "GATE_DEFER")
        self.assertEqual(payload["implies"], [])

    def test_tmux_crash(self) -> None:
        code, payload = self._run(_tmux_crash())
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "CRASH")
        self.assertEqual(payload["confidence"], "HIGH")
        self.assertEqual(payload["implies"], [])

    def test_escalation_default(self) -> None:
        code, payload = self._run(_escalation())
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "REVIEW_REJECTED")
        self.assertEqual(payload["confidence"], "MEDIUM")

    def test_non_failure_event_is_unknown(self) -> None:
        code, payload = self._run(_story_completed())
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "UNKNOWN")
        self.assertEqual(payload["confidence"], "LOW")
        self.assertEqual(payload["reason"], "non_failure_event")


class CmdTriageStdinTests(unittest.TestCase):
    def test_reads_event_from_stdin(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage

        line = compact_json(_story_failed("connection timeout").to_dict())
        with mock.patch.object(sys, "stdin", io.StringIO(line)):
            code, payload = _capture(cmd_triage, [])
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "TIMEOUT")


class CmdTriageErrorTests(unittest.TestCase):
    def test_missing_event_blank_json_flag(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage

        code, payload = _capture(cmd_triage, ["--json", "   "])
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "missing_event")

    def test_missing_event_empty_stdin(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage

        with mock.patch.object(sys, "stdin", io.StringIO("")):
            code, payload = _capture(cmd_triage, [])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "missing_event")

    def test_invalid_json_returns_structured_error(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage

        code, payload = _capture(cmd_triage, ["--json", "{not json"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_json")
        self.assertIn("detail", payload)

    def test_non_object_top_level_is_invalid_event(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage

        code, payload = _capture(cmd_triage, ["--json", "[1,2]"])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_event")

    def test_missing_event_type_is_invalid_event(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage

        code, payload = _capture(cmd_triage, ["--json", '{"x":1}'])
        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_event")

    def test_unknown_event_type_routes_to_unknown(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage

        line = '{"event_type":"made_up","timestamp":"","run_id":""}'
        code, payload = _capture(cmd_triage, ["--json", line])
        self.assertEqual(code, 0)
        self.assertEqual(payload["failure_class"], "UNKNOWN")
        self.assertEqual(payload["confidence"], "LOW")


class CmdTriageOutputContractTests(unittest.TestCase):
    def test_payload_has_required_keys(self) -> None:
        from story_automator.commands.triage_cmd import cmd_triage

        line = compact_json(_story_failed("connection timeout").to_dict())
        code, payload = _capture(cmd_triage, ["--json", line])
        self.assertEqual(code, 0)
        self.assertEqual(
            set(payload.keys()),
            {"ok", "failure_class", "confidence", "implies", "reason", "event_id"},
        )
        self.assertIsInstance(payload["implies"], list)
        self.assertIn(payload["confidence"], {c.value for c in Confidence})
        self.assertIn(payload["failure_class"], {f.value for f in FailureClass})


if __name__ == "__main__":
    unittest.main()
