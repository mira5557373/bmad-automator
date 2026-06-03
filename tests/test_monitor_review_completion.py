from __future__ import annotations

import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.tmux import _verify_monitor_completion, cmd_monitor_session
from story_automator.core.review_verify import verify_code_review_completion
from tests.success_verifier_case import SuccessVerifierCase, patch_env


class MonitorReviewCompletionTests(SuccessVerifierCase):

    def test_review_wrapper_uses_pinned_state_snapshot(self) -> None:
        self._write_story("1-2-example", status="approved")
        state_file = self._build_state()
        self._write_override(
            {
                "steps": {
                    "review": {
                        "success": {
                            "config": {"doneValues": ["approved"], "sourceOrder": ["story-file"], "syncSprintStatus": False}
                        }
                    }
                }
            }
        )
        payload = verify_code_review_completion(str(self.project_root), "1.2", state_file=state_file)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "workflow_not_complete")

    def test_review_wrapper_ignores_unrelated_missing_assets(self) -> None:
        shutil.rmtree(self.project_root / ".claude" / "skills" / "bmad-create-story")
        self._write_story("1-2-example", status="done")
        payload = verify_code_review_completion(str(self.project_root), "1.2")
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["source"], "story-file")

    def test_monitor_dispatch_uses_review_verifier_from_contract(self) -> None:
        self._write_story("1-2-example", status="done")
        result = _verify_monitor_completion(
            "review",
            project_root=str(self.project_root),
            story_key="1.2",
            output_file="/tmp/session.txt",
        )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "review_completion")
        self.assertTrue(payload["verified"])

    def test_monitor_dispatch_skips_story_keyed_verifier_without_story_key(self) -> None:
        result = _verify_monitor_completion(
            "review",
            project_root=str(self.project_root),
            story_key="",
            output_file="/tmp/session.txt",
        )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "review_completion")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "story_key_required")

    def test_monitor_dispatch_rejects_missing_verifier_in_contract(self) -> None:
        self._write_override({"steps": {"review": {"success": {"verifier": ""}}}})
        result = _verify_monitor_completion(
            "review",
            project_root=str(self.project_root),
            story_key="1.2",
            output_file="/tmp/session.txt",
        )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "verifier_contract_invalid")

    def test_monitor_session_reports_incomplete_when_verifier_missing(self) -> None:
        self._write_override({"steps": {"review": {"success": {"verifier": ""}}}})
        stdout = io.StringIO()
        statuses = [
            {"todos_done": 1, "todos_total": 1, "session_state": "completed"},
            {"active_task": "/tmp/session.txt"},
        ]
        with patch_env(self.project_root), patch("story_automator.commands.tmux.time.sleep"), patch(
            "story_automator.commands.tmux.session_status", side_effect=statuses
        ), redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--workflow", "review", "--story-key", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["final_state"], "incomplete")
        self.assertEqual(payload["exit_reason"], "verifier_contract_invalid")
        self.assertFalse(payload["output_verified"])

    def test_monitor_dispatch_rejects_verifier_side_file_error(self) -> None:
        with patch("story_automator.commands.tmux.run_success_verifier", side_effect=FileNotFoundError("missing.json")):
            result = _verify_monitor_completion(
                "review",
                project_root=str(self.project_root),
                story_key="1.2",
                output_file="/tmp/session.txt",
            )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "review_completion")
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "verifier_contract_invalid")

    def test_monitor_session_reports_incomplete_when_verifier_raises_file_error(self) -> None:
        stdout = io.StringIO()
        statuses = [
            {"todos_done": 1, "todos_total": 1, "session_state": "completed"},
            {"active_task": "/tmp/session.txt"},
        ]
        with patch_env(self.project_root), patch("story_automator.commands.tmux.time.sleep"), patch(
            "story_automator.commands.tmux.session_status", side_effect=statuses
        ), patch("story_automator.commands.tmux.run_success_verifier", side_effect=FileNotFoundError("missing.json")), redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--workflow", "review", "--story-key", "1.2"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["final_state"], "incomplete")
        self.assertEqual(payload["exit_reason"], "verifier_contract_invalid")
        self.assertFalse(payload["output_verified"])

    def test_monitor_session_timeout_keeps_output_unverified_without_verifier_result(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), patch(
            "story_automator.commands.tmux.session_status", return_value={"active_task": "/tmp/session.txt"}
        ), redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--max-polls", "0"])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["final_state"], "timeout")
        self.assertEqual(payload["exit_reason"], "max_polls_exceeded")
        self.assertFalse(payload["output_verified"])

    def test_monitor_session_runtime_agent_uses_resolved_provider_flags(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_session_status(*args: object, **kwargs: object) -> dict[str, object]:
            calls.append({"args": args, **kwargs})
            return {"active_task": "/tmp/session.txt"}

        stdout = io.StringIO()
        with patch_env(self.project_root), patch("story_automator.commands.tmux.runtime_provider", return_value="codex"), patch(
            "story_automator.commands.tmux.session_status", side_effect=fake_session_status
        ), redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--max-polls", "0", "--agent", "runtime"])

        self.assertEqual(code, 0)
        self.assertTrue(calls)
        self.assertTrue(calls[0]["codex"])

    def test_monitor_session_infers_claude_from_legacy_ai_command(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root, extra={"AI_COMMAND": "claude --print"}), patch(
            "story_automator.commands.tmux.session_status",
            return_value={"active_task": "/tmp/session.txt", "todos_done": 0, "todos_total": 0, "wait_estimate": 5, "session_state": "not_found"},
        ) as session_status_mock, redirect_stdout(stdout):
            code = cmd_monitor_session(["fake-session", "--json", "--max-polls", "1"])
        self.assertEqual(code, 0)
        self.assertFalse(session_status_mock.call_args.kwargs["codex"])

    def test_monitor_dispatch_allows_session_exit_without_story_key(self) -> None:
        result = _verify_monitor_completion(
            "dev",
            project_root=str(self.project_root),
            story_key="",
            output_file="/tmp/session.txt",
        )
        self.assertIsNotNone(result)
        payload, verifier = result or ({}, "")
        self.assertEqual(verifier, "session_exit")
        self.assertTrue(payload["verified"])

    def test_review_wrapper_normalizes_directory_state_file(self) -> None:
        payload = verify_code_review_completion(str(self.project_root), "1.2", state_file=self.project_root)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "review_contract_invalid")
        self.assertIn("state file unreadable", str(payload.get("error")))

    def test_review_wrapper_honors_empty_injected_contract(self) -> None:
        self._write_story("1-2-example", status="done")
        self._write_override(
            {
                "steps": {
                    "review": {
                        "success": {
                            "config": {"doneValues": ["approved"], "sourceOrder": ["story-file"], "syncSprintStatus": False}
                        }
                    }
                }
            }
        )
        payload = verify_code_review_completion(str(self.project_root), "1.2", success_contract={})
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["source"], "story-file")

    def test_review_wrapper_normalizes_policy_error(self) -> None:
        payload = verify_code_review_completion(
            str(self.project_root),
            "1.2",
            success_contract={"doneValues": [], "sourceOrder": ["story-file"]},
        )
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "review_contract_invalid")

    def test_verify_code_review_rejects_incomplete_state_file_flag(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["verify-code-review", "1.2", "--state-file"])
        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["reason"], "review_contract_invalid")
        self.assertEqual(payload["error"], "--state-file requires a value")


if __name__ == "__main__":
    unittest.main()
