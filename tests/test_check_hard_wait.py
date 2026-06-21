from __future__ import annotations

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
        [sys.executable, str(_CHECKS_DIR / "hard_wait_check.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


class TestHardWaitUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)


class TestHardWaitPython(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_time_sleep(self):
        test_file = os.path.join(self.tmp, "test_example.py")
        with open(test_file, "w") as f:
            f.write("import time\ntime.sleep(5)\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        self.assertIn("HARD_WAIT:", r.stdout)
        self.assertIn("time.sleep", r.stdout)

    def test_detects_asyncio_sleep(self):
        test_file = os.path.join(self.tmp, "test_async.py")
        with open(test_file, "w") as f:
            f.write("import asyncio\nawait asyncio.sleep(2)\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        self.assertIn("asyncio.sleep", r.stdout)

    def test_clean_file_passes(self):
        test_file = os.path.join(self.tmp, "test_clean.py")
        with open(test_file, "w") as f:
            f.write("def test_ok():\n    assert True\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)

    def test_noqa_marker_suppresses(self):
        test_file = os.path.join(self.tmp, "test_noqa.py")
        with open(test_file, "w") as f:
            f.write("time.sleep(5)  # noqa: burn-in\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)

    def test_non_test_file_ignored(self):
        src_file = os.path.join(self.tmp, "main.py")
        with open(src_file, "w") as f:
            f.write("import time\ntime.sleep(5)\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)


class TestHardWaitJavaScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_wait_for_timeout(self):
        test_file = os.path.join(self.tmp, "test_e2e.spec.ts")
        with open(test_file, "w") as f:
            f.write("await page.waitForTimeout(5000);\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        self.assertIn("waitForTimeout", r.stdout)

    def test_detects_set_timeout(self):
        test_file = os.path.join(self.tmp, "test_timer.test.ts")
        with open(test_file, "w") as f:
            f.write("setTimeout(() => {}, 3000);\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)

    def test_detects_cy_wait(self):
        test_file = os.path.join(self.tmp, "test_cypress.spec.js")
        with open(test_file, "w") as f:
            f.write("cy.wait(5000);\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
