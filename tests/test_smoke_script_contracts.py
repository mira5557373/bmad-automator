from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_script_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load script module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VersionAlignmentScriptTests(unittest.TestCase):
    def test_python_version_missing_raises_targeted_error(self) -> None:
        module = load_script_module("check_version_alignment", SCRIPTS / "check-version-alignment.py")

        with self.assertRaisesRegex(ValueError, "missing Python __version__ assignment"):
            module.python_version("# no version here\n", "pkg/__init__.py")

    def test_marketplace_plugin_version_uses_stable_plugin_name(self) -> None:
        module = load_script_module("check_version_alignment", SCRIPTS / "check-version-alignment.py")

        version = module.marketplace_plugin_version(
            {
                "plugins": [
                    {"name": "other-plugin", "version": "9.9.9"},
                    {"name": "bmad-automator", "version": "1.15.0"},
                ]
            },
            {"name": "bmad-automator"},
        )

        self.assertEqual(version, "1.15.0")

    def test_marketplace_plugin_version_requires_match(self) -> None:
        module = load_script_module("check_version_alignment", SCRIPTS / "check-version-alignment.py")

        with self.assertRaisesRegex(ValueError, "missing plugin: bmad-automator"):
            module.marketplace_plugin_version({"plugins": []}, {"name": "bmad-automator"})


class SmokeContractsScriptTests(unittest.TestCase):
    def test_allowed_environment_skips_do_not_fail_default_contract_gate(self) -> None:
        module = load_script_module("run_smoke_contracts", SCRIPTS / "run-smoke-contracts.py")
        stderr = io.StringIO()

        class Result:
            skipped = [("tmux test", "tmux not available")]

            def wasSuccessful(self) -> bool:
                return True

        class Runner:
            def __init__(self, *, verbosity: int) -> None:
                self.verbosity = verbosity

            def run(self, suite):
                return Result()

        with (
            patch.object(module.unittest.defaultTestLoader, "loadTestsFromNames", return_value=object()) as load_tests,
            patch.object(module.unittest, "TextTestRunner", Runner),
            redirect_stderr(stderr),
        ):
            code = module.main()

        self.assertEqual(code, 0)
        self.assertIn("smoke:contracts skipped 1 allowed environment-dependent tests", stderr.getvalue())
        load_tests.assert_called_once_with(module.TEST_MODULES)

    def test_unexpected_skips_fail_default_contract_gate(self) -> None:
        module = load_script_module("run_smoke_contracts", SCRIPTS / "run-smoke-contracts.py")
        stderr = io.StringIO()

        class Result:
            skipped = [("feature test", "temporarily disabled")]

            def wasSuccessful(self) -> bool:
                return True

        class Runner:
            def __init__(self, *, verbosity: int) -> None:
                self.verbosity = verbosity

            def run(self, suite):
                return Result()

        with (
            patch.object(module.unittest.defaultTestLoader, "loadTestsFromNames", return_value=object()),
            patch.object(module.unittest, "TextTestRunner", Runner),
            redirect_stderr(stderr),
        ):
            code = module.main()

        self.assertEqual(code, 1)
        self.assertIn("smoke:contracts got 1 unexpected skipped tests", stderr.getvalue())


class DeterministicSmokeEnvTests(unittest.TestCase):
    def test_subprocess_runners_clear_marker_override_env(self) -> None:
        automator = load_script_module("run_smoke_automator", SCRIPTS / "run-smoke-automator.py")
        dev_loop = load_script_module("run_smoke_dev_loop", SCRIPTS / "run-smoke-dev-loop.py")

        with patch.dict(
            os.environ,
            {
                "BMAD_STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-a",
                "STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-b",
            },
            clear=False,
        ):
            runner = automator.SmokeRunner(
                root=REPO_ROOT,
                workspace=REPO_ROOT / ".smoke",
                project=REPO_ROOT / ".smoke" / "gunz",
                story_id="1.1",
            )
            dev = dev_loop.DevLoopSmokeRunner(
                root=REPO_ROOT,
                workspace=REPO_ROOT / ".smoke",
                project=REPO_ROOT / ".smoke" / "gunz",
                story_ids=["1.1"],
            )

        for env in (runner.env, dev.env):
            self.assertNotIn("BMAD_STORY_AUTOMATOR_ACTIVE_MARKER", env)
            self.assertNotIn("STORY_AUTOMATOR_ACTIVE_MARKER", env)

    def test_in_process_runners_clear_marker_override_env_during_calls(self) -> None:
        modes = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")
        finish = load_script_module("run_smoke_finish_loop", SCRIPTS / "run-smoke-finish-loop.py")

        def assert_clean_env(args):
            self.assertNotIn("BMAD_STORY_AUTOMATOR_ACTIVE_MARKER", os.environ)
            self.assertNotIn("STORY_AUTOMATOR_ACTIVE_MARKER", os.environ)
            return 0

        with patch.dict(
            os.environ,
            {
                "BMAD_STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-a",
                "STORY_AUTOMATOR_ACTIVE_MARKER": "/tmp/outside-b",
            },
            clear=False,
        ):
            mode_runner = modes.ModeSmokeRunner()
            finish_runner = finish.FinishLoopSmokeRunner()
            try:
                self.assertEqual(mode_runner._call(assert_clean_env, [])[0], 0)
                self.assertEqual(finish_runner._call(assert_clean_env, [])[0], 0)
            finally:
                mode_runner.close()
                finish_runner.close()

            self.assertEqual(os.environ["BMAD_STORY_AUTOMATOR_ACTIVE_MARKER"], "/tmp/outside-a")
            self.assertEqual(os.environ["STORY_AUTOMATOR_ACTIVE_MARKER"], "/tmp/outside-b")


class SmokePrepCliTests(unittest.TestCase):
    def test_value_error_returns_clean_failure(self) -> None:
        from smoke_prep import cli

        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with (
                patch.object(cli, "repo_root", return_value=REPO_ROOT),
                patch.object(cli, "ensure_tool"),
                patch.object(cli, "resolve_workspace", return_value=Path(tmp)),
                patch.object(cli, "prepare_gunz"),
                patch.object(cli, "smoke_env", return_value={}),
                patch.object(cli, "smoke_inputs", side_effect=ValueError("bad smoke input")),
                redirect_stderr(stderr),
            ):
                code = cli.main([])

        self.assertEqual(code, 1)
        self.assertIn("smoke prep failed: bad smoke input", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


class SmokeModesScriptTests(unittest.TestCase):
    def test_json_objects_parses_concatenated_marker_output(self) -> None:
        module = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")
        runner = module.ModeSmokeRunner()
        try:
            payloads = runner._json_objects(0, '{"exists":true}\n{"storiesRemaining":2}\n')
        finally:
            runner.close()

        self.assertEqual(payloads[0]["exists"], True)
        self.assertEqual(payloads[1]["storiesRemaining"], 2)

    def test_report_payload_persists_latest_incomplete_state(self) -> None:
        module = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")
        runner = module.ModeSmokeRunner()
        state_file = runner.output / "orchestration-smoke.md"
        try:
            state_file.parent.mkdir(parents=True)
            state_file.write_text('status: "IN_PROGRESS"\n', encoding="utf-8")

            report, payload = runner.write_report(
                {
                    "project": str(runner.project),
                    "resume": {"latestIncomplete": str(state_file)},
                }
            )
            persisted = Path(payload["resume"]["latestIncomplete"])
        finally:
            runner.close()

        self.assertEqual(payload["project"]["kind"], "ephemeral")
        self.assertNotIn("path", payload["project"])
        self.assertTrue(persisted.exists())
        self.assertEqual(persisted.read_text(encoding="utf-8"), 'status: "IN_PROGRESS"\n')
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), payload)

    def test_report_payload_fails_closed_when_latest_incomplete_cannot_be_persisted(self) -> None:
        module = load_script_module("run_smoke_modes", SCRIPTS / "run-smoke-modes.py")
        runner = module.ModeSmokeRunner()
        try:
            missing = runner.output / "missing-state.md"
            with self.assertRaisesRegex(module.SmokeModesError, "failed to persist latest incomplete state"):
                runner._report_payload(
                    {
                        "project": str(runner.project),
                        "resume": {"latestIncomplete": str(missing)},
                    }
                )
        finally:
            runner.close()


class SmokeStorySlugTests(unittest.TestCase):
    def test_automator_story_slug_ignores_unfound_sprint_status_story_echo(self) -> None:
        module = load_script_module("run_smoke_automator", SCRIPTS / "run-smoke-automator.py")
        runner = module.SmokeRunner(
            root=REPO_ROOT,
            workspace=REPO_ROOT / ".smoke",
            project=REPO_ROOT / ".smoke" / "gunz",
            story_id="1.1",
        )

        with patch.object(
            runner,
            "_helper_json",
            side_effect=[
                {"found": False, "story": "1.1", "status": "not_found"},
                {"title": "First Story"},
            ],
        ):
            slug = runner._story_slug()

        self.assertEqual(slug, "1-1-first-story")

    def test_dev_loop_story_slug_ignores_unfound_sprint_status_story_echo(self) -> None:
        module = load_script_module("run_smoke_dev_loop", SCRIPTS / "run-smoke-dev-loop.py")
        runner = module.DevLoopSmokeRunner(
            root=REPO_ROOT,
            workspace=REPO_ROOT / ".smoke",
            project=REPO_ROOT / ".smoke" / "gunz",
            story_ids=["1.1"],
        )

        with patch.object(
            runner,
            "_helper_json",
            side_effect=[
                {"found": False, "story": "1.1", "status": "not_found"},
                {"title": "First Story"},
            ],
        ):
            slug = runner._story_slug("1.1")

        self.assertEqual(slug, "1-1-first-story")


class FinishLoopSmokeScriptTests(unittest.TestCase):
    def test_ephemeral_descriptors_do_not_expose_cleaned_paths(self) -> None:
        module = load_script_module("run_smoke_finish_loop", SCRIPTS / "run-smoke-finish-loop.py")
        runner = module.FinishLoopSmokeRunner()
        try:
            project_descriptor = runner._ephemeral_project_descriptor()
            repo_descriptor = runner._repo_descriptor(runner.project)
        finally:
            runner.close()

        self.assertEqual(project_descriptor["kind"], "ephemeral")
        self.assertFalse(project_descriptor["retained"])
        self.assertNotIn("path", project_descriptor)
        self.assertEqual(repo_descriptor["kind"], "ephemeral")
        self.assertFalse(repo_descriptor["retained"])
        self.assertNotIn("path", repo_descriptor)

    def test_write_report_returns_persisted_payload_without_temp_paths(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git not available")
        module = load_script_module("run_smoke_finish_loop", SCRIPTS / "run-smoke-finish-loop.py")
        runner = module.FinishLoopSmokeRunner()
        try:
            runner.project.mkdir(parents=True)
            runner._init_git()
            state = runner.project / "orchestration-smoke.md"
            state.write_text('status: "COMPLETE"\n', encoding="utf-8")
            payload = runner._write_report(state, [{"story": "1.1", "commit": "abc123"}], runner.project)
            report = Path(payload["report"])
            temp_root = runner.tmp.name
        finally:
            runner.close()

        persisted = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(persisted, payload)
        self.assertTrue(Path(payload["diagnostics"]["stateFile"]).exists())
        self.assertTrue(Path(payload["diagnostics"]["gitLog"]).exists())
        self.assert_no_temp_path(payload, temp_root)

    def assert_no_temp_path(self, value: object, temp_root: str) -> None:
        if isinstance(value, dict):
            for child in value.values():
                self.assert_no_temp_path(child, temp_root)
        elif isinstance(value, list):
            for child in value:
                self.assert_no_temp_path(child, temp_root)
        elif isinstance(value, str):
            self.assertNotIn(temp_root, value)


if __name__ == "__main__":
    unittest.main()
