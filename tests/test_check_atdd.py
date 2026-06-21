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
        [sys.executable, str(_CHECKS_DIR / "atdd_check.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


def _parse_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("ATDD_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


class TestAtddCheckUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)


class TestAtddCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_atdd_output_exits_0(self):
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertFalse(result["available"])
        self.assertTrue(result["passed"])

    def test_red_verified(self):
        tea_dir = os.path.join(self.tmp, ".tea")
        os.makedirs(tea_dir)
        with open(os.path.join(tea_dir, "atdd-result.json"), "w") as f:
            json.dump({
                "red_verified": True,
                "tests_written": 5,
                "tests_failing": 5,
            }, f)
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertTrue(result["available"])
        self.assertTrue(result["red_verified"])
        self.assertTrue(result["passed"])

    def test_red_not_verified(self):
        tea_dir = os.path.join(self.tmp, ".tea")
        os.makedirs(tea_dir)
        with open(os.path.join(tea_dir, "atdd-result.json"), "w") as f:
            json.dump({"red_verified": False, "tests_written": 5}, f)
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertFalse(result["red_verified"])

    def test_malformed_json_exits_1(self):
        tea_dir = os.path.join(self.tmp, ".tea")
        os.makedirs(tea_dir)
        with open(os.path.join(tea_dir, "atdd-result.json"), "w") as f:
            f.write("not json")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
