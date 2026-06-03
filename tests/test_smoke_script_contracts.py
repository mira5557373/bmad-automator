from __future__ import annotations

import importlib.util
import io
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


if __name__ == "__main__":
    unittest.main()
