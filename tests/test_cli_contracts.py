from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

from story_automator.cli import main
from story_automator.commands.agent_config_cmd import cmd_agent_config
from story_automator.commands.tmux import cmd_tmux_wrapper
from story_automator.core.tmux_runtime import generate_session_name, project_hash, project_slug, tmux_list_sessions


REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = REPO_ROOT / "skills" / "bmad-story-automator" / "scripts" / "story-automator"


class CliParserContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_parse_story_range_invalid_total_returns_json_error(self) -> None:
        code, payload = self._main_json(["parse-story-range", "--input", "all", "--total", "abc"])

        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "missing_input_or_total"})

    def test_parse_story_reports_missing_rules_file(self) -> None:
        epic = self._epic_file()

        code, payload = self._main_json(["parse-story", "--epic", str(epic), "--story", "1.1", "--rules", str(self.root / "missing.json")])

        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "rules_file_not_found"})

    def test_parse_story_reports_invalid_rules_json(self) -> None:
        epic = self._epic_file()
        rules = self.root / "rules.json"
        rules.write_text("{bad json", encoding="utf-8")

        code, payload = self._main_json(["parse-story", "--epic", str(epic), "--story", "1.1", "--rules", str(rules)])

        self.assertEqual(code, 1)
        self.assertEqual(payload, {"ok": False, "error": "invalid_rules_json"})

    def test_parse_story_success_scores_story(self) -> None:
        epic = self._epic_file()
        rules = self.root / "rules.json"
        rules.write_text(
            json.dumps({"rules": [{"pattern": "database", "score": 3, "label": "Touches DB"}], "thresholds": {"low_max": 1, "medium_max": 3}}),
            encoding="utf-8",
        )

        code, payload = self._main_json(["parse-story", "--epic", str(epic), "--story", "1.1", "--rules", str(rules)])

        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["storyId"], "1.1")
        self.assertEqual(payload["complexity"]["score"], 3)
        self.assertEqual(payload["complexity"]["level"], "Medium")

    def test_parse_story_read_failure_returns_json_error(self) -> None:
        epic = self._epic_file()
        rules = self.root / "rules.json"
        rules.write_text("{}", encoding="utf-8")

        with mock.patch("story_automator.cli.parse_story", side_effect=OSError("permission denied")):
            code, payload = self._main_json(["parse-story", "--epic", str(epic), "--story", "1.1", "--rules", str(rules)])

        self.assertEqual(code, 1)
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["error"], "file_read_failed")
        self.assertIn("permission denied", payload["reason"])

    def test_module_subprocess_preserves_json_error_contract(self) -> None:
        result = self._subprocess([sys.executable, "-m", "story_automator", "parse-story-range", "--input", "all", "--total", "abc"])

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), {"ok": False, "error": "missing_input_or_total"})
        self.assertEqual(result.stderr, "")

    def test_installed_wrapper_subprocess_preserves_validate_state_contract(self) -> None:
        state_file = self.root / "state.md"
        state_file.write_text('---\nstatus: "DONE"\nlastUpdated: "bad"\naiCommand: ""\n---\n', encoding="utf-8")

        result = self._subprocess([str(WRAPPER), "validate-state", "--state", str(state_file)])

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["structure"], "issues")
        self.assertGreater(payload["issueCount"], 0)
        self.assertTrue(payload["structuredIssues"])

    def _epic_file(self) -> Path:
        epic = self.root / "epic.md"
        epic.write_text(
            "# Product Epic\n\n## Epic 1: Platform\n\n### Story 1.1: Add database sync\nDescription line.\n\nAcceptance Criteria\n- Works reliably\n",
            encoding="utf-8",
        )
        return epic

    def _main_json(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(args)
        return code, json.loads(stdout.getvalue())

    def _subprocess(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT / "skills" / "bmad-story-automator" / "src") + os.pathsep + env.get("PYTHONPATH", "")
        env["PROJECT_ROOT"] = str(self.root)
        return subprocess.run(args, cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False)


class AgentConfigCommandContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.presets = Path(self.tmp.name) / "presets.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_save_load_update_delete_preset(self) -> None:
        code, payload = self._agent(["save", "--file", str(self.presets), "--name", "Default", "--config-json", '{"defaultPrimary":"codex"}'])
        self.assertEqual(code, 0)
        self.assertEqual(payload["action"], "created")

        code, payload = self._agent(["save", "--file", str(self.presets), "--name", "default", "--config-json", '{"defaultPrimary":"claude"}'])
        self.assertEqual(code, 0)
        self.assertEqual(payload["action"], "updated")

        code, payload = self._agent(["load", "--file", str(self.presets), "--name", "DEFAULT"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["name"], "Default")
        self.assertEqual(payload["config"]["defaultPrimary"], "claude")

        code, payload = self._agent(["delete", "--file", str(self.presets), "--name", "default"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["action"], "deleted")

    def test_invalid_config_json_returns_stable_error(self) -> None:
        code, payload = self._agent(["save", "--file", str(self.presets), "--name", "bad", "--config-json", "{bad"])

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_config_json")

    def test_malformed_presets_file_returns_stable_error(self) -> None:
        self.presets.write_text("{bad", encoding="utf-8")

        code, payload = self._agent(["list", "--file", str(self.presets)])

        self.assertEqual(code, 1)
        self.assertEqual(payload["error"], "invalid_presets_json")

    def _agent(self, args: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = cmd_agent_config(args)
        return code, json.loads(stdout.getvalue())


class TmuxCommandContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_name_cycle_uses_cycle_value_not_flag_token(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"PROJECT_ROOT": str(self.root)}), redirect_stdout(stdout):
            code = cmd_tmux_wrapper(["name", "review", "5", "5.3", "--cycle", "2"])

        self.assertEqual(code, 0)
        session = stdout.getvalue().strip()
        self.assertIn(f"sa-{project_slug(str(self.root))}-{project_hash(str(self.root))}-", session)
        self.assertTrue(session.endswith("-review-r2"), session)
        self.assertNotIn("-r--cycle", session)

    def test_name_cycle_preserves_legacy_positional_value(self) -> None:
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {"PROJECT_ROOT": str(self.root)}), redirect_stdout(stdout):
            code = cmd_tmux_wrapper(["name", "review", "5", "5.3", "2"])

        self.assertEqual(code, 0)
        self.assertTrue(stdout.getvalue().strip().endswith("-review-r2"))

    def test_name_cycle_requires_value(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = cmd_tmux_wrapper(["name", "review", "5", "5.3", "--cycle"])

        self.assertEqual(code, 1)
        self.assertIn("--cycle requires a value", stderr.getvalue())

    def test_project_only_session_filter_uses_slug_and_hash(self) -> None:
        own = f"sa-{project_slug(str(self.root))}-{project_hash(str(self.root))}-260521-101010-e5-s5-3-review"
        other_root = self.root.parent / "other" / self.root.name
        other = f"sa-{project_slug(str(other_root))}-{project_hash(str(other_root))}-260521-101011-e5-s5-3-review"
        legacy_collision = f"sa-{project_slug(str(self.root))}-260521-101012-e5-s5-3-review"
        output = "\n".join([own, other, legacy_collision, "unrelated"])

        with (
            mock.patch.dict(os.environ, {"PROJECT_ROOT": str(self.root)}),
            mock.patch("story_automator.core.tmux_runtime.command_exists", return_value=True),
            mock.patch("story_automator.core.tmux_runtime.run_cmd", return_value=(output, 0)),
        ):
            sessions, code = tmux_list_sessions(project_only=True)

        self.assertEqual(code, 0)
        self.assertEqual(sessions, [own])

    def test_kill_all_defaults_to_all_automator_sessions(self) -> None:
        with (
            mock.patch("story_automator.commands.tmux.tmux_list_sessions", return_value=(["sa-one"], 0)) as list_sessions,
            mock.patch("story_automator.commands.tmux.tmux_kill_session") as kill_session,
            redirect_stdout(io.StringIO()),
        ):
            code = cmd_tmux_wrapper(["kill-all"])

        self.assertEqual(code, 0)
        list_sessions.assert_called_once_with(False)
        kill_session.assert_called_once_with("sa-one")

    def test_kill_all_project_only_opt_in(self) -> None:
        with (
            mock.patch("story_automator.commands.tmux.tmux_list_sessions", return_value=(["sa-one"], 0)) as list_sessions,
            mock.patch("story_automator.commands.tmux.tmux_kill_session"),
            redirect_stdout(io.StringIO()),
        ):
            code = cmd_tmux_wrapper(["kill-all", "--project-only"])

        self.assertEqual(code, 0)
        list_sessions.assert_called_once_with(True)

    def test_kill_all_all_projects_opt_in(self) -> None:
        with (
            mock.patch("story_automator.commands.tmux.tmux_list_sessions", return_value=(["sa-one"], 0)) as list_sessions,
            mock.patch("story_automator.commands.tmux.tmux_kill_session"),
            redirect_stdout(io.StringIO()),
        ):
            code = cmd_tmux_wrapper(["kill-all", "--all-projects"])

        self.assertEqual(code, 0)
        list_sessions.assert_called_once_with(False)

    def test_generate_session_name_includes_project_hash(self) -> None:
        with mock.patch.dict(os.environ, {"PROJECT_ROOT": str(self.root)}):
            session = generate_session_name("dev", "2", "2.4")

        self.assertIn(f"sa-{project_slug(str(self.root))}-{project_hash(str(self.root))}-", session)
        self.assertTrue(session.endswith("-e2-s2-4-dev"), session)


if __name__ == "__main__":
    unittest.main()
