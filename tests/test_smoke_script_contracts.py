from __future__ import annotations

import importlib.util
import io
import json
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
    def test_missing_tmux_fails_before_unittest_loader(self) -> None:
        module = load_script_module("run_smoke_contracts", SCRIPTS / "run-smoke-contracts.py")
        stderr = io.StringIO()

        with (
            patch.object(module.shutil, "which", return_value=None),
            patch.object(module.unittest.defaultTestLoader, "loadTestsFromNames") as load_tests,
            redirect_stderr(stderr),
        ):
            code = module.main()

        self.assertEqual(code, 1)
        self.assertIn("smoke:contracts requires these tools before tests run: tmux", stderr.getvalue())
        load_tests.assert_not_called()


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
        self.assertTrue(persisted.exists())
        self.assertEqual(persisted.read_text(encoding="utf-8"), 'status: "IN_PROGRESS"\n')
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main()
