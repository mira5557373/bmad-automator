from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_CHECKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
    / "story_automator" / "core" / "checks"
)
_SCRIPT = str(_CHECKS_DIR / "presence_check.py")


class PresenceCheckDirectTests(unittest.TestCase):
    """Test presence_check.main() directly (no subprocess)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_present_returns_zero(self) -> None:
        from story_automator.core.checks.presence_check import main

        Path(self.tmpdir, "a.md").write_text("x", encoding="utf-8")
        result = main([self.tmpdir, '["a.md"]'])
        self.assertEqual(result, 0)

    def test_missing_file_returns_one(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([self.tmpdir, '["gone.md"]'])
        self.assertEqual(result, 1)

    def test_mixed_present_and_missing(self) -> None:
        from story_automator.core.checks.presence_check import main

        Path(self.tmpdir, "exists.md").write_text("x", encoding="utf-8")
        result = main([self.tmpdir, '["exists.md", "gone.md"]'])
        self.assertEqual(result, 1)

    def test_nested_path(self) -> None:
        from story_automator.core.checks.presence_check import main

        nested = Path(self.tmpdir, "docs", "ops")
        nested.mkdir(parents=True)
        (nested / "runbook.md").write_text("x", encoding="utf-8")
        result = main([self.tmpdir, '["docs/ops/runbook.md"]'])
        self.assertEqual(result, 0)

    def test_no_args_returns_two(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([])
        self.assertEqual(result, 2)

    def test_invalid_json_returns_two(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([self.tmpdir, "not-json"])
        self.assertEqual(result, 2)

    def test_non_array_json_returns_two(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([self.tmpdir, '{"a": 1}'])
        self.assertEqual(result, 2)

    def test_empty_list_returns_zero(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([self.tmpdir, "[]"])
        self.assertEqual(result, 0)


class PresenceCheckSubprocessTests(unittest.TestCase):
    """Test presence_check.py as a standalone script."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, _SCRIPT, *args],
            capture_output=True, text=True, timeout=10,
        )

    def test_script_exists(self) -> None:
        self.assertTrue(Path(_SCRIPT).is_file(), f"not found: {_SCRIPT}")

    def test_all_present_stdout(self) -> None:
        Path(self.tmpdir, "a.md").write_text("x", encoding="utf-8")
        result = self._run(self.tmpdir, '["a.md"]')
        self.assertEqual(result.returncode, 0)
        self.assertIn("present", result.stdout)

    def test_missing_file_stdout(self) -> None:
        result = self._run(self.tmpdir, '["missing.md"]')
        self.assertEqual(result.returncode, 1)
        self.assertIn("MISSING: missing.md", result.stdout)
