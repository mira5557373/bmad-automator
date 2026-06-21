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
        [sys.executable, str(_CHECKS_DIR / "test_review_check.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


def _parse_review_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("TEST_REVIEW_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


class TestTestReviewCheckUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)


class TestTestReviewCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tea_output_exits_0(self):
        """Graceful degradation: no TEA = still pass."""
        r = _run_check([self.tmp, "70"])
        self.assertEqual(r.returncode, 0)
        result = _parse_review_result(r.stdout)
        self.assertFalse(result["available"])

    def test_score_above_threshold(self):
        tea_dir = os.path.join(self.tmp, ".tea")
        os.makedirs(tea_dir)
        with open(os.path.join(tea_dir, "test-review.json"), "w") as f:
            json.dump({"score": 85, "details": []}, f)
        r = _run_check([self.tmp, "70"])
        self.assertEqual(r.returncode, 0)
        result = _parse_review_result(r.stdout)
        self.assertTrue(result["available"])
        self.assertTrue(result["passed"])

    def test_score_below_threshold(self):
        tea_dir = os.path.join(self.tmp, ".tea")
        os.makedirs(tea_dir)
        with open(os.path.join(tea_dir, "test-review.json"), "w") as f:
            json.dump({"score": 50, "details": []}, f)
        r = _run_check([self.tmp, "70"])
        self.assertEqual(r.returncode, 1)
        result = _parse_review_result(r.stdout)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
