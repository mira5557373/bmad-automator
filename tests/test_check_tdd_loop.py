from __future__ import annotations

import json
import os
import shutil
import stat
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
        [sys.executable, str(_CHECKS_DIR / "tdd_loop.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


def _parse_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("TDD_LOOP_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


def _make_script(tmp: str, name: str, content: str) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class TestTddLoopUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)

    def test_invalid_phase_exits_2(self):
        r = _run_check(["/tmp", "invalid_phase"])
        self.assertEqual(r.returncode, 2)


class TestTddLoopRed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_red_phase_tests_fail_is_valid(self):
        script = _make_script(self.tmp, "fail.py", "import sys; sys.exit(1)\n")
        r = _run_check([self.tmp, "red", "--", sys.executable, script])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertTrue(result["tdd_valid"])

    def test_red_phase_tests_pass_is_invalid(self):
        script = _make_script(self.tmp, "pass.py", "import sys; sys.exit(0)\n")
        r = _run_check([self.tmp, "red", "--", sys.executable, script])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertFalse(result["tdd_valid"])


class TestTddLoopGreen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_green_phase_tests_pass_is_valid(self):
        script = _make_script(self.tmp, "pass.py", "import sys; sys.exit(0)\n")
        r = _run_check([self.tmp, "green", "--", sys.executable, script])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertTrue(result["tdd_valid"])

    def test_green_phase_tests_fail_is_invalid(self):
        script = _make_script(self.tmp, "fail.py", "import sys; sys.exit(1)\n")
        r = _run_check([self.tmp, "green", "--", sys.executable, script])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertFalse(result["tdd_valid"])


if __name__ == "__main__":
    unittest.main()
