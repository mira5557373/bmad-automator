from __future__ import annotations

import json
import os
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


def _run_check(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECKS_DIR / "dod_check.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


def _parse_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("DOD_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


class TestDodCheckUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)


class TestDodCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_story_exits_0(self):
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertFalse(result["available"])

    def test_complete_story_passes(self):
        with open(os.path.join(self.tmp, "story.md"), "w") as f:
            f.write(
                "# Story Title\n\n"
                "## Status\ndone\n\n"
                "## File List\n- src/foo.py\n- src/bar.py\n\n"
                "## Change Log\n- Added foo\n"
            )
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertTrue(result["available"])
        self.assertTrue(result["passed"])

    def test_missing_file_list_fails(self):
        with open(os.path.join(self.tmp, "story.md"), "w") as f:
            f.write(
                "# Story Title\n\n"
                "## Status\ndone\n\n"
                "## Change Log\n- Added foo\n"
            )
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertFalse(result["passed"])
        self.assertIn("File List", str(result["violations"]))

    def test_missing_change_log_fails(self):
        with open(os.path.join(self.tmp, "story.md"), "w") as f:
            f.write(
                "# Story Title\n\n"
                "## Status\ndone\n\n"
                "## File List\n- src/foo.py\n- src/bar.py\n"
            )
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
