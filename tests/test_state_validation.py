from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_validate_state
from story_automator.core.state_validation import has_runtime_command_config
from tests.test_replacement_unicode import _FixtureMixin, patch_env


class StateValidationDiagnosticsTests(_FixtureMixin, unittest.TestCase):
    def test_validate_state_adds_structured_issues_without_replacing_legacy(self) -> None:
        state_file = self.project_root / "missing-runtime-config.md"
        state_file.write_text(
            "---\nepic: \"1\"\nepicName: \"Epic 1\"\nstoryRange: [\"1.1\"]\nstatus: \"READY\"\nlastUpdated: \"2026-04-13T00:00:00Z\"\naiCommand: \"\"\n---\n",
            encoding="utf-8",
        )

        payload = self._validate_state(state_file)

        self.assertEqual(payload["structure"], "issues")
        self.assertEqual(payload["issueCount"], len(payload["issues"]))
        self.assertIn("Missing or empty aiCommand", payload["issues"])
        self.assertEqual(payload["structuredIssues"][0]["type"], "missing_field")
        self.assertEqual(payload["structuredIssues"][0]["field"], "aiCommand")
        self.assertEqual(payload["structuredIssues"][0]["source"], "validate-state")
        self.assertEqual(payload["structuredIssues"][0]["severity"], "error")

    def test_validate_state_success_includes_empty_structured_fields(self) -> None:
        state_file = self._build_state()

        payload = self._validate_state(state_file)

        self.assertEqual(payload["structure"], "ok")
        self.assertEqual(payload["issues"], [])
        self.assertEqual(payload["structuredIssues"], [])
        self.assertEqual(payload["issueCount"], 0)

    def test_validate_state_accepts_agent_config_header_with_comment(self) -> None:
        state_file = self._build_state_config(aiCommand="")
        text = state_file.read_text(encoding="utf-8")
        text = text.replace(
            'aiCommand: ""\n',
            'aiCommand: ""\nagentConfig: # runtime config\n  defaultPrimary: "codex"\n',
        )
        state_file.write_text(text, encoding="utf-8")

        payload = self._validate_state(state_file)

        self.assertEqual(payload["structure"], "ok")
        self.assertEqual(payload["issues"], [])

    def test_runtime_command_config_rejects_whitespace_only_command(self) -> None:
        self.assertFalse(has_runtime_command_config({"aiCommand": "   "}, ""))
        self.assertFalse(has_runtime_command_config({"aiCommand": ["", "  "]}, ""))
        self.assertTrue(has_runtime_command_config({"aiCommand": ["  claude  "]}, ""))
        self.assertTrue(has_runtime_command_config({"aiCommand": "   "}, 'agentConfig:\n  defaultPrimary: "codex"\n'))
        self.assertFalse(has_runtime_command_config({"aiCommand": "   "}, "agentConfig:\n  defaultPrimary:\n"))
        self.assertFalse(has_runtime_command_config({"aiCommand": "   "}, "agentConfig:\n  complexityOverrides:\n    - medium:\n"))

    def test_validate_state_reports_invalid_status_field(self) -> None:
        state_file = self._build_state_config(status="DONE")

        payload = self._validate_state(state_file)

        self.assertIn("Invalid status", payload["issues"])
        issue = next(item for item in payload["structuredIssues"] if item["field"] == "status")
        self.assertEqual(issue["type"], "invalid_value")
        self.assertEqual(issue["actual"], "DONE")
        self.assertIn("EXECUTION_COMPLETE", issue["expected"])

    def test_state_update_blocks_invalid_status_transition(self) -> None:
        state_file = self._build_state_config(status="READY")
        before = state_file.read_text(encoding="utf-8")

        code, payload = self._state_update(state_file, "status=COMPLETE")

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_status_transition")
        self.assertEqual(payload["currentStatus"], "READY")
        self.assertEqual(payload["attemptedStatus"], "COMPLETE")
        self.assertEqual(payload["allowedTransitions"], ["ABORTED", "IN_PROGRESS", "PAUSED", "READY"])
        self.assertIn("Invalid status transition from READY to COMPLETE", payload["issues"])
        self.assertEqual(payload["structuredIssues"][0]["field"], "status")
        self.assertEqual(state_file.read_text(encoding="utf-8"), before)

    def test_state_update_allows_valid_status_transition(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, "status=IN_PROGRESS")

        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "updated": ["status"]})
        self.assertIn("status: IN_PROGRESS", state_file.read_text(encoding="utf-8"))

    def test_state_update_can_repair_invalid_legacy_status(self) -> None:
        state_file = self._build_state_config(status="DONE")

        code, payload = self._state_update(state_file, "status=READY")

        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "updated": ["status"]})
        self.assertIn("status: READY", state_file.read_text(encoding="utf-8"))

    def test_state_update_rejects_invalid_attempted_status(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, "status=DONE")

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_status_transition")
        self.assertEqual(payload["currentStatus"], "READY")
        self.assertEqual(payload["attemptedStatus"], "DONE")
        self.assertEqual(payload["structuredIssues"][0]["type"], "invalid_value")

    def test_state_update_still_allows_non_status_updates(self) -> None:
        state_file = self._build_state_config(status="COMPLETE")

        code, payload = self._state_update(state_file, "aiCommand=claude --resume")

        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "updated": ["aiCommand"]})
        self.assertIn("aiCommand: claude --resume", state_file.read_text(encoding="utf-8"))

    def _validate_state(self, state_file: Path) -> dict[str, object]:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_validate_state(["--state", str(state_file)])
        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue())

    def _build_state_config(self, **overrides: object) -> Path:
        config = self._default_config()
        config.update(overrides)
        return self._build_state(config)

    def _state_update(self, state_file: Path, update: str) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-update", str(state_file), "--set", update])
        return code, json.loads(stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
