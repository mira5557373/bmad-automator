from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_validate_state
from story_automator.core.diagnostics import DiagnosticIssue
from story_automator.core.state_validation import has_runtime_command_config, state_validation_payload, status_transition_error_payload, validate_state_fields, validate_status_transition
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
        self.assertFalse(has_runtime_command_config({"aiCommand": "   "}, '  agentConfig:\n    defaultPrimary: "codex"\n'))
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

    def test_validate_state_reports_wrong_typed_required_fields_from_frontmatter(self) -> None:
        state_file = self._build_state_config(epicName=["Epic 1"], storyRange="1.1")

        payload = self._validate_state(state_file)

        fields = {issue["field"]: issue for issue in payload["structuredIssues"]}
        self.assertEqual(fields["epicName"]["expected"], "non-empty string")
        self.assertEqual(fields["storyRange"]["expected"], "array of non-empty story IDs")

    def test_validate_state_fields_rejects_non_string_epic(self) -> None:
        issues = validate_state_fields(
            str(self.project_root / "state.md"),
            {
                "epic": 1,
                "epicName": "Epic 1",
                "storyRange": ["1.1"],
                "status": "READY",
                "lastUpdated": "2026-04-13T00:00:00Z",
                "aiCommand": "claude",
            },
            "",
        )

        epic_issue = next(issue for issue in issues if issue.field == "epic")
        self.assertEqual(epic_issue.type, "invalid_value")

    def test_validate_state_legacy_issues_redact_sensitive_context(self) -> None:
        payload = state_validation_payload(
            [
                DiagnosticIssue(
                    type="invalid_value",
                    field="policySnapshotFile",
                    actual="/tmp/token=abc123/snapshot.json",
                    message="policy snapshot missing: /tmp/token=abc123/snapshot.json",
                    source="validate-state",
                )
            ]
        )

        serialized = json.dumps(payload, separators=(",", ":"))
        self.assertNotIn("token=abc123", serialized)
        self.assertNotIn("/tmp/token=abc123", serialized)
        self.assertIn("<path:snapshot.json>", payload["issues"][0])

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

    def test_status_transition_payload_uses_precomputed_issue(self) -> None:
        issue = validate_status_transition("READY", "COMPLETE")
        self.assertIsNotNone(issue)

        payload = status_transition_error_payload("READY", "COMPLETE", issue)

        self.assertEqual(payload["error"], "invalid_status_transition")
        self.assertEqual(payload["structuredIssues"][0]["message"], "Invalid status transition from READY to COMPLETE")

    def test_status_transition_payload_rejects_valid_transition(self) -> None:
        with self.assertRaises(ValueError):
            status_transition_error_payload("READY", "IN_PROGRESS")

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

    def test_state_update_blocks_completion_from_invalid_current_status(self) -> None:
        state_file = self._build_state_config(status="BOGUS")
        before = state_file.read_text(encoding="utf-8")

        code, payload = self._state_update(state_file, "status=COMPLETE")

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_status_transition")
        self.assertEqual(payload["currentStatus"], "BOGUS")
        self.assertEqual(payload["attemptedStatus"], "COMPLETE")
        self.assertEqual(payload["allowedTransitions"], ["ABORTED", "READY"])
        self.assertEqual(state_file.read_text(encoding="utf-8"), before)

    def test_state_update_rejects_invalid_attempted_status(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, "status=DONE")

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_status_transition")
        self.assertEqual(payload["currentStatus"], "READY")
        self.assertEqual(payload["attemptedStatus"], "DONE")
        self.assertEqual(payload["structuredIssues"][0]["type"], "invalid_value")

    def test_state_update_redacts_secret_like_attempted_status_in_legacy_fields(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, "status=token=abc123")

        self.assertEqual(code, 1)
        serialized = json.dumps(payload, separators=(",", ":"))
        self.assertNotIn("token=abc123", serialized)
        self.assertEqual(payload["attemptedStatus"], "token=<redacted>")
        self.assertEqual(payload["issues"], ["Invalid status token=<redacted>"])

    def test_state_update_redacts_absolute_path_attempted_status_in_legacy_fields(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, "status=/tmp/private/state.md")

        self.assertEqual(code, 1)
        serialized = json.dumps(payload, separators=(",", ":"))
        self.assertNotIn("/tmp/private", serialized)
        self.assertEqual(payload["attemptedStatus"], "<path:state.md>")
        self.assertEqual(payload["issues"], ["Invalid status <path:state.md>"])

    def test_state_update_rejects_malformed_set_argument_with_structured_issue(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, "status")

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_set_argument")
        self.assertEqual(payload["structuredIssues"][0]["field"], "--set")
        self.assertEqual(payload["structuredIssues"][0]["expected"], "KEY=VALUE")

    def test_state_update_rejects_trailing_set_argument_with_structured_issue(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update_args(state_file, ["--set"])

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_set_argument")
        self.assertEqual(payload["structuredIssues"][0]["field"], "--set")

    def test_state_update_rejects_empty_set_key_with_structured_issue(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, "=READY")

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_set_argument")
        self.assertEqual(payload["structuredIssues"][0]["actual"], "=READY")

    def test_state_update_still_allows_non_status_updates(self) -> None:
        state_file = self._build_state_config(status="COMPLETE")

        code, payload = self._state_update(state_file, "aiCommand=claude --resume")

        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "updated": ["aiCommand"]})
        self.assertIn("aiCommand: claude --resume", state_file.read_text(encoding="utf-8"))

    def test_state_update_rejects_mixed_missing_key_without_partial_write(self) -> None:
        state_file = self._build_state_config(status="COMPLETE")
        before = state_file.read_text(encoding="utf-8")

        code, payload = self._state_update_args(state_file, ["--set", "aiCommand=codex exec", "--set", "bogus=value"])

        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "keys_not_found", "updated": []})
        self.assertEqual(state_file.read_text(encoding="utf-8"), before)

    def test_state_update_write_failure_leaves_file_unchanged(self) -> None:
        state_file = self._build_state_config(status="READY")
        before = state_file.read_text(encoding="utf-8")

        with self.assertRaises(OSError), unittest.mock.patch(
            "story_automator.commands.orchestrator_state.write_atomic",
            side_effect=OSError("disk full"),
        ):
            self._state_update(state_file, "status=IN_PROGRESS")

        self.assertEqual(state_file.read_text(encoding="utf-8"), before)

    def test_state_update_quotes_yaml_like_frontmatter_values(self) -> None:
        state_file = self._build_state_config(status="COMPLETE")

        for raw, rendered in (
            ("currentStep=false", 'currentStep: "false"'),
            ("currentStep=null", 'currentStep: "null"'),
            ("currentStep=01", 'currentStep: "01"'),
            ("currentStep=value: detail", 'currentStep: "value: detail"'),
            ("currentStep=value # detail", 'currentStep: "value # detail"'),
        ):
            with self.subTest(raw=raw):
                code, payload = self._state_update(state_file, raw)

                self.assertEqual(code, 0)
                self.assertEqual(payload, {"ok": True, "updated": ["currentStep"]})
                self.assertIn(rendered, state_file.read_text(encoding="utf-8"))

    def test_state_update_only_rewrites_frontmatter(self) -> None:
        state_file = self._build_state_config(status="COMPLETE")
        text = state_file.read_text(encoding="utf-8").replace("currentStep: null\n", "currentStep: step-old\n", 1)
        state_file.write_text(text + "\nstatus: body-marker\ncurrentStep: body-step\n", encoding="utf-8")

        code, payload = self._state_update_args(state_file, ["--set", "status=COMPLETE", "--set", "currentStep=step-next"])

        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "updated": ["status", "currentStep"]})
        text = state_file.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        body = text.split("---", 2)[2]
        self.assertIn("status: COMPLETE", frontmatter)
        self.assertIn("currentStep: step-next", frontmatter)
        self.assertIn("status: body-marker", body)
        self.assertIn("currentStep: body-step", body)

    def test_state_update_rejects_file_without_frontmatter_without_rewriting_body(self) -> None:
        state_file = self.project_root / "body-only.md"
        state_file.write_text("body\nstatus: body-marker\n", encoding="utf-8")

        code, payload = self._state_update(state_file, "status=READY")

        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "keys_not_found", "updated": []})
        self.assertEqual(state_file.read_text(encoding="utf-8"), "body\nstatus: body-marker\n")

    def test_state_update_rejects_unterminated_frontmatter_without_rewriting_body(self) -> None:
        state_file = self.project_root / "unterminated.md"
        state_file.write_text("---\nstatus: body-marker\n", encoding="utf-8")

        code, payload = self._state_update(state_file, "status=READY")

        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "keys_not_found", "updated": []})
        self.assertEqual(state_file.read_text(encoding="utf-8"), "---\nstatus: body-marker\n")

    def test_state_update_strips_set_key_whitespace(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, " status=COMPLETE")

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_status_transition")

    def test_state_update_strips_set_value_whitespace(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, " status = IN_PROGRESS")

        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "updated": ["status"]})
        self.assertIn("status: IN_PROGRESS", state_file.read_text(encoding="utf-8"))

    def test_state_update_preserves_non_status_value_whitespace(self) -> None:
        state_file = self._build_state_config(status="READY")

        code, payload = self._state_update(state_file, " currentStep =  step-next  ")

        self.assertEqual(code, 0)
        self.assertEqual(payload, {"ok": True, "updated": ["currentStep"]})
        self.assertIn('currentStep: "step-next"', state_file.read_text(encoding="utf-8"))

    def test_state_update_uses_frontmatter_status_for_transition(self) -> None:
        state_file = self._build_state_config(status="COMPLETE")
        state_file.write_text(state_file.read_text(encoding="utf-8") + "\nstatus: READY\n", encoding="utf-8")

        code, payload = self._state_update(state_file, "status=IN_PROGRESS")

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_status_transition")
        self.assertEqual(payload["currentStatus"], "COMPLETE")

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
        return self._state_update_args(state_file, ["--set", update])

    def _state_update_args(self, state_file: Path, args: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["state-update", str(state_file), *args])
        return code, json.loads(stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
