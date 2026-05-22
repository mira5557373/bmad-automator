from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.state import cmd_validate_state
from story_automator.commands.tmux import cmd_monitor_session
from story_automator.core.diagnostics import DIAGNOSTIC_EVENTS_FILE_ENV
from story_automator.core.monitoring import emit_monitor_result
from story_automator.core.agent_plan import validate_agents_plan_payload
from story_automator.core.parse_contracts import validate_payload
from story_automator.core.tmux_runtime import session_paths


class DiagnosticsE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_malformed_llm_output_reports_nested_field_path(self) -> None:
        issues = validate_payload(
            {"status": "SUCCESS", "issues_found": {"critical": "0"}, "all_fixed": True, "summary": "ok", "next_action": "proceed"},
            {
                "requiredKeys": ["status", "issues_found", "all_fixed", "summary", "next_action"],
                "schema": {
                    "status": "SUCCESS|FAILURE|AMBIGUOUS",
                    "issues_found": {"critical": "integer"},
                    "all_fixed": "true|false",
                    "summary": "brief description",
                    "next_action": "proceed|retry|escalate",
                },
            },
        )

        self.assertEqual(issues[0].field, "issues_found.critical")
        self.assertEqual(issues[0].type, "invalid_type")

    def test_invalid_state_frontmatter_returns_legacy_and_structured_issues(self) -> None:
        state_file = self.project_root / "state.md"
        state_file.write_text('---\nepic: ""\nstatus: "DONE"\nlastUpdated: "bad"\naiCommand: ""\n---\n', encoding="utf-8")

        payload = self._validate_state(state_file)

        self.assertEqual(payload["structure"], "issues")
        self.assertGreater(payload["issueCount"], 0)
        self.assertTrue(any(isinstance(issue, str) for issue in payload["issues"]))
        self.assertTrue(any(issue["field"] == "status" for issue in payload["structuredIssues"]))

    def test_illegal_state_transition_is_blocked_before_write(self) -> None:
        state_file = self.project_root / "state.md"
        state_file.write_text('---\nstatus: READY\n---\n', encoding="utf-8")

        code, payload = self._helper(["state-update", str(state_file), "--set", "status=COMPLETE"])

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_status_transition")
        self.assertEqual(payload["currentStatus"], "READY")
        self.assertIn("IN_PROGRESS", payload["allowedTransitions"])
        self.assertIn("status: READY", state_file.read_text(encoding="utf-8"))

    def test_state_transition_event_uses_redacted_opt_in_channel(self) -> None:
        state_file = self.project_root / "state.md"
        state_file.write_text('---\nstatus: READY\n---\n', encoding="utf-8")
        events_file = self.project_root / "events.jsonl"

        code, payload = self._helper(["state-update", str(state_file), "--set", "status=token=abc123"], events_file=events_file)

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_status_transition")
        event = json.loads(events_file.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(event["name"], "state.transition")
        self.assertEqual(event["context"]["stateFile"], "<path:state.md>")
        self.assertEqual(event["context"]["attemptedStatus"], "token=<redacted>")
        self.assertNotIn(str(self.project_root), events_file.read_text(encoding="utf-8"))
        self.assertNotIn("abc123", events_file.read_text(encoding="utf-8"))

    def test_story_and_step_updates_emit_state_event(self) -> None:
        state_file = self.project_root / "state.md"
        state_file.write_text('---\ncurrentStory: ""\ncurrentStep: ""\nlastUpdated: old\n---\n', encoding="utf-8")
        events_file = self.project_root / "events.jsonl"

        code, payload = self._helper(
            [
                "state-update",
                str(state_file),
                "--set",
                "currentStory=1.2",
                "--set",
                "currentStep=dev",
            ],
            events_file=events_file,
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["updated"], ["currentStory", "currentStep"])
        event = json.loads(events_file.read_text(encoding="utf-8"))
        self.assertEqual(event["name"], "state.fields_updated")
        self.assertEqual(event["context"]["updatedFields"], ["currentStory", "currentStep"])
        self.assertEqual(event["context"]["values"], {"currentStory": "1.2", "currentStep": "dev"})

    def test_monitor_result_emits_session_lifecycle_event(self) -> None:
        events_file = self.project_root / "events.jsonl"
        stdout = io.StringIO()
        with patch.dict("os.environ", {DIAGNOSTIC_EVENTS_FILE_ENV: str(events_file)}), redirect_stdout(stdout):
            code = emit_monitor_result(True, "completed", 1, 1, str(self.project_root / "out.txt"), "normal_completion")

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["final_state"], "completed")
        event = json.loads(events_file.read_text(encoding="utf-8"))
        self.assertEqual(event["name"], "session.lifecycle.result")
        self.assertEqual(event["context"]["outputFile"], "<path:out.txt>")

    def test_malformed_agent_plan_reports_task_field_paths(self) -> None:
        issues = validate_agents_plan_payload({"stories": [{"storyId": "1.1", "tasks": {"create": {"primary": ""}}}]})

        fields = [issue.field for issue in issues]
        self.assertIn("stories[0].tasks.create.primary", fields)
        self.assertIn("stories[0].tasks.dev", fields)

    def test_monitor_json_keeps_malformed_session_state_when_legacy_status_deletes_file(self) -> None:
        session = "sa-test-session"
        paths = session_paths(session, self.project_root)
        paths.state.parent.mkdir(parents=True, exist_ok=True)
        paths.state.write_text("{bad json", encoding="utf-8")

        stdout = io.StringIO()
        with (
            patch.dict("os.environ", {"PROJECT_ROOT": str(self.project_root), "SA_TMUX_RUNTIME": "auto", "AI_AGENT": "claude"}),
            patch("story_automator.core.tmux_runtime.command_exists", return_value=True),
            patch("story_automator.core.tmux_runtime.run_cmd", return_value=("", 1)),
            redirect_stdout(stdout),
        ):
            code = cmd_monitor_session([session, "--json", "--max-polls", "1"])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["structuredIssues"][0]["type"], "session_state.invalid_json")

    def _validate_state(self, state_file: Path) -> dict[str, object]:
        stdout = io.StringIO()
        with patch.dict("os.environ", {"PROJECT_ROOT": str(self.project_root)}), redirect_stdout(stdout):
            code = cmd_validate_state(["--state", str(state_file)])
        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue())

    def _helper(self, args: list[str], *, events_file: Path | None = None) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        env = {"PROJECT_ROOT": str(self.project_root)}
        if events_file is not None:
            env[DIAGNOSTIC_EVENTS_FILE_ENV] = str(events_file)
        with patch.dict("os.environ", env), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(args)
        return code, json.loads(stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
