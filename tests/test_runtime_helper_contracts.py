from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.orchestrator_parse import parse_output_action
from story_automator.commands.tmux import _build_cmd, cmd_monitor_session, cmd_tmux_wrapper
from story_automator.core.tmux_runtime import _terminal_runner_status, save_session_state, session_paths
from story_automator.core.tmux_runtime import cleanup_runtime_artifacts, command_exists, session_status, tmux_kill_session
from story_automator.core.utils import COMMAND_TIMEOUT_EXIT, CommandResult


REPO_ROOT = Path(__file__).resolve().parents[1]


class RuntimeHelperContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self._install_bundle()
        self._install_required_skills()
        self.output_file = self.project_root / "session-output.txt"
        self.output_file.write_text("session transcript\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_output_fail_closed_subprocess_matrix(self) -> None:
        cases = [
            (
                "timeout",
                CommandResult("", COMMAND_TIMEOUT_EXIT, subprocess.TimeoutExpired(["claude"], 1)),
                "sub-agent call timed out",
                "sub_agent",
            ),
            (
                "nonzero",
                CommandResult("boom", 42, RuntimeError("boom")),
                "sub-agent call failed",
                "sub_agent",
            ),
            (
                "no_json",
                CommandResult("plain text only", 0),
                "sub-agent returned invalid json",
                "payload",
            ),
            (
                "schema_invalid",
                CommandResult('{"status":"SUCCESS"}', 0),
                "sub-agent returned invalid json",
                "story_created",
            ),
        ]
        for label, result, reason, field in cases:
            with self.subTest(label=label):
                stdout = io.StringIO()
                with self._env(), patch("story_automator.commands.orchestrator_parse.run_cmd", return_value=result), redirect_stdout(stdout):
                    code = parse_output_action([str(self.output_file), "create"])
                self.assertEqual(code, 1)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["status"], "error")
                self.assertEqual(payload["reason"], reason)
                self.assertEqual(payload["structuredIssues"][0]["field"], field)

    def test_parse_output_rejects_missing_and_empty_outputs_before_subprocess(self) -> None:
        missing = self.project_root / "missing.txt"
        empty = self.project_root / "empty.txt"
        empty.write_text("", encoding="utf-8")
        for path in (missing, empty):
            with self.subTest(path=path.name):
                stdout = io.StringIO()
                with self._env(), patch("story_automator.commands.orchestrator_parse.run_cmd") as mock_run, redirect_stdout(stdout):
                    code = parse_output_action([str(path), "create"])
                self.assertEqual(code, 1)
                mock_run.assert_not_called()
                payload = json.loads(stdout.getvalue())
                self.assertEqual(payload["reason"], "output file not found or empty")
                self.assertEqual(payload["structuredIssues"][0]["field"], "output_file")

    def test_build_cmd_covers_agent_safety_and_override_branches(self) -> None:
        stdout = io.StringIO()
        with self._env(extra={"AI_AGENT": "codex", "AI_COMMAND": ""}), redirect_stdout(stdout):
            code = _build_cmd(["review", "1.1", "--model", "gpt-5.5"])
        rendered = stdout.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("codex exec -s workspace-write", rendered)
        self.assertIn("approval_policy=\"never\"", rendered)
        self.assertIn("--disable plugins --disable sqlite --disable shell_snapshot", rendered)
        self.assertIn("--model gpt-5.5", rendered)

        stdout = io.StringIO()
        with self._env(extra={"AI_AGENT": "", "AI_COMMAND": "custom-ai --json"}), redirect_stdout(stdout):
            code = _build_cmd(["review", "1.1"])
        self.assertEqual(code, 0)
        self.assertTrue(stdout.getvalue().startswith("unset CLAUDECODE && custom-ai --json "))

        stdout = io.StringIO()
        with self._env(extra={"AI_AGENT": "", "AI_COMMAND": ""}), redirect_stdout(stdout):
            code = _build_cmd(["review", "1.1", "--agent", "claude", "--model", "claude sonnet"])
        self.assertEqual(code, 0)
        self.assertIn("claude --dangerously-skip-permissions --model 'claude sonnet'", stdout.getvalue())

    def test_build_cmd_negative_contracts_fail_without_prompt_text_leakage(self) -> None:
        for args, expected in (
            (["ship", "1.1"], "unknown step: ship"),
            (["review", "1.1", "--state-file"], "--state-file requires a value"),
            (["review", "1.1", "--state-file", str(self.project_root / "missing.md")], "state file unreadable"),
        ):
            with self.subTest(args=args):
                stderr = io.StringIO()
                with self._env(), redirect_stderr(stderr):
                    code = _build_cmd(args)
                self.assertEqual(code, 1)
                self.assertIn(expected, stderr.getvalue())

        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.policy.json").write_text(json.dumps({"runtime": {"parser": {"provider": "bad"}}}), encoding="utf-8")
        stderr = io.StringIO()
        with self._env(), redirect_stderr(stderr):
            code = _build_cmd(["review", "1.1"])
        self.assertEqual(code, 1)
        self.assertIn("runtime.parser.provider", stderr.getvalue())

    def test_monitor_session_json_terminal_state_matrix(self) -> None:
        cases = [
            (
                "completed",
                [
                    {"todos_done": 2, "todos_total": 2, "session_state": "completed", "wait_estimate": 0, "active_task": ""},
                    {"active_task": "/tmp/session.txt", "todos_done": 2, "todos_total": 2, "session_state": "completed", "wait_estimate": 0},
                ],
                {"final_state": "completed", "exit_reason": "normal_completion", "output_verified": True},
            ),
            (
                "crashed",
                [
                    {"todos_done": 1, "todos_total": 2, "session_state": "crashed", "wait_estimate": 0, "active_task": ""},
                    {"active_task": "/tmp/crash.txt", "todos_done": 1, "todos_total": 2, "session_state": "crashed", "wait_estimate": 7},
                ],
                {"final_state": "crashed", "exit_reason": "exit_code_7", "output_verified": False},
            ),
            (
                "stuck",
                [
                    {"todos_done": 0, "todos_total": 0, "session_state": "stuck", "wait_estimate": 0, "active_task": ""},
                    {"active_task": "/tmp/stuck.txt", "todos_done": 0, "todos_total": 0, "session_state": "stuck", "wait_estimate": 0},
                ],
                {"final_state": "stuck", "exit_reason": "never_active", "output_verified": False},
            ),
            (
                "not_found",
                [{"todos_done": 0, "todos_total": 0, "session_state": "not_found", "wait_estimate": 0, "active_task": ""}],
                {"final_state": "not_found", "exit_reason": "session_gone", "output_verified": False},
            ),
        ]
        for label, statuses, expected in cases:
            with self.subTest(label=label):
                stdout = io.StringIO()
                with self._env(), patch("story_automator.commands.tmux.time.sleep"), patch(
                    "story_automator.commands.tmux.session_status", side_effect=statuses
                ), redirect_stdout(stdout):
                    code = cmd_monitor_session(["sa-test", "--json", "--max-polls", "1", "--initial-wait", "0", "--workflow", "dev"])
                self.assertEqual(code, 0)
                payload = json.loads(stdout.getvalue())
                for key, value in expected.items():
                    self.assertEqual(payload[key], value)

    def test_runner_terminal_status_maps_edge_results(self) -> None:
        cases = [
            ("spawn-error", "spawn_error", "runner_exec_failed", 127, "crashed"),
            ("interrupted", "interrupted", "signal_terminated", 130, "crashed"),
            ("launch-never", "unknown", "launch_never_succeeded", "", "stuck"),
        ]
        for suffix, result, reason, exit_code, expected_state in cases:
            with self.subTest(suffix=suffix):
                session = f"sa-contract-{suffix}"
                paths = session_paths(session, str(self.project_root))
                paths.output.write_text("runner output\n", encoding="utf-8")
                save_session_state(
                    paths.state,
                    {
                        "schemaVersion": 1,
                        "session": session,
                        "projectRoot": str(self.project_root),
                        "lifecycle": "finished",
                        "result": result,
                        "failureReason": reason,
                        "exitCode": exit_code,
                    },
                )
                status = _terminal_runner_status(session, {"result": result, "failureReason": reason, "exitCode": exit_code}, full=True, project_root=str(self.project_root))
                self.assertEqual(status["session_state"], expected_state)
                self.assertTrue(str(status["active_task"]).endswith(f"output-{session}.txt"))

    def _install_bundle(self) -> None:
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(REPO_ROOT / "skills" / "bmad-story-automator", target_root / "bmad-story-automator")
        shutil.copytree(REPO_ROOT / "skills" / "bmad-story-automator-review", target_root / "bmad-story-automator-review")

    def _install_required_skills(self) -> None:
        extras = {
            "bmad-create-story": {"discover-inputs.md": "# discover\n", "checklist.md": "# checklist\n", "template.md": "# template\n"},
            "bmad-dev-story": {"checklist.md": "# checklist\n"},
            "bmad-retrospective": {},
            "bmad-qa-generate-e2e-tests": {"checklist.md": "# checklist\n"},
        }
        for name, files in extras.items():
            skill_dir = self.project_root / ".claude" / "skills" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
            for rel, content in files.items():
                (skill_dir / rel).write_text(content, encoding="utf-8")

    def _env(self, extra: dict[str, str] | None = None):
        env = {"PROJECT_ROOT": str(self.project_root), "AI_AGENT": "", "AI_COMMAND": ""}
        env.update(extra or {})
        return patch.dict("os.environ", env, clear=False)


@unittest.skipUnless(command_exists("tmux"), "tmux not available")
class TmuxWrapperRunnerContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.sessions: list[str] = []

    def tearDown(self) -> None:
        try:
            for session in self.sessions:
                try:
                    tmux_kill_session(session, str(self.project_root))
                except Exception:
                    pass
                cleanup_runtime_artifacts(session, str(self.project_root))
        finally:
            self.tmp.cleanup()

    def test_tmux_wrapper_spawn_runner_success_and_crash(self) -> None:
        cases = [
            ("success", "printf wrapper-ok", "completed", 0),
            ("crash", "printf wrapper-boom && exit 7", "crashed", 7),
        ]
        for label, command, expected_state, expected_wait in cases:
            with self.subTest(label=label):
                stdout = io.StringIO()
                with patch.dict("os.environ", {"PROJECT_ROOT": str(self.project_root), "SA_TMUX_RUNTIME": "runner"}, clear=False), redirect_stdout(stdout):
                    code = cmd_tmux_wrapper(["spawn", "dev", "1", f"1.{len(self.sessions) + 1}", "--command", command, "--agent", "codex"])
                self.assertEqual(code, 0)
                session = stdout.getvalue().strip()
                self.sessions.append(session)
                status = self._wait_for_terminal(session)
                self.assertEqual(status["session_state"], expected_state)
                self.assertEqual(status["wait_estimate"], expected_wait)

    def _wait_for_terminal(self, session: str) -> dict[str, str | int]:
        import time

        deadline = time.time() + 30
        last: dict[str, str | int] = {}
        while time.time() < deadline:
            last = session_status(session, full=False, codex=True, project_root=str(self.project_root), mode="runner")
            if str(last["session_state"]) in {"completed", "crashed", "stuck"}:
                return last
            time.sleep(0.1)
        self.fail(f"session did not reach terminal state: {last}")


if __name__ == "__main__":
    unittest.main()
