from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_CHECKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
    / "story_automator" / "core" / "checks"
)


def _run_check(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECKS_DIR / "burn_in_check.py")] + args,
        capture_output=True, text=True, timeout=30,
    )


def _parse_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("BURN_IN_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


def _make_script(tmp: str, name: str, content: str) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class TestBurnInCheckUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)

    def test_missing_separator_exits_2(self):
        r = _run_check(["/tmp", "3"])
        self.assertEqual(r.returncode, 2)


class TestBurnInCheckAllPass(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.script = _make_script(
            self.tmp, "pass_test.py",
            "import sys; sys.exit(0)\n",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_pass_exits_0(self):
        r = _run_check([self.tmp, "3", "--", sys.executable, self.script])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertEqual(result["total_runs"], 3)
        self.assertEqual(result["passed_runs"], 3)
        self.assertEqual(result["failed_runs"], 0)
        self.assertFalse(result["flaky"])
        self.assertEqual(result["flaky_count"], 0)


class TestBurnInCheckAllFail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.script = _make_script(
            self.tmp, "fail_test.py",
            "import sys; sys.exit(1)\n",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_fail_exits_1_but_not_flaky(self):
        r = _run_check([self.tmp, "3", "--", sys.executable, self.script])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertEqual(result["total_runs"], 3)
        self.assertEqual(result["passed_runs"], 0)
        self.assertEqual(result["failed_runs"], 3)
        self.assertFalse(result["flaky"])


class TestBurnInCheckFlaky(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        counter_file = os.path.join(self.tmp, ".run_counter")
        self.script = _make_script(
            self.tmp, "flaky_test.py",
            textwrap.dedent(f"""\
                import sys, os
                counter = "{counter_file}"
                n = 0
                if os.path.exists(counter):
                    with open(counter) as f:
                        n = int(f.read().strip())
                n += 1
                with open(counter, "w") as f:
                    f.write(str(n))
                sys.exit(0 if n % 2 == 1 else 1)
            """),
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flaky_detected(self):
        r = _run_check([self.tmp, "4", "--", sys.executable, self.script])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertTrue(result["flaky"])
        self.assertGreater(result["passed_runs"], 0)
        self.assertGreater(result["failed_runs"], 0)


class TestBurnInCheckSingleRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.script = _make_script(
            self.tmp, "pass_test.py",
            "import sys; sys.exit(0)\n",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_single_run_no_flaky(self):
        r = _run_check([self.tmp, "1", "--", sys.executable, self.script])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertEqual(result["total_runs"], 1)
        self.assertFalse(result["flaky"])


if __name__ == "__main__":
    unittest.main()
