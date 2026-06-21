from __future__ import annotations

import json
import shutil
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
        [sys.executable, str(_CHECKS_DIR / "mutation_check.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


def _parse_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("MUTATION_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


class TestMutationCheckUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)

    def test_invalid_tool_exits_2(self):
        r = _run_check(["/tmp", "unknown_tool", "60"])
        self.assertEqual(r.returncode, 2)


class TestMutationScoreParsing(unittest.TestCase):
    def test_parse_mutmut_results(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from mutation_check import _parse_mutmut_score
        finally:
            sys.path.pop(0)
        output = textwrap.dedent("""\
            Killed: 8
            Survived: 2
            Timeout: 0
            Suspicious: 0
            Skipped: 0
        """)
        score, killed, survived, total = _parse_mutmut_score(output)
        self.assertAlmostEqual(score, 80.0)
        self.assertEqual(killed, 8)
        self.assertEqual(survived, 2)
        self.assertEqual(total, 10)

    def test_parse_stryker_json(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from mutation_check import _parse_stryker_score
        finally:
            sys.path.pop(0)
        report = {
            "schemaVersion": "1",
            "thresholds": {"high": 80, "low": 60},
            "files": {
                "src/foo.ts": {
                    "mutants": [
                        {"status": "Killed"},
                        {"status": "Killed"},
                        {"status": "Survived"},
                    ]
                }
            },
        }
        score, killed, survived, total = _parse_stryker_score(report)
        self.assertAlmostEqual(score, 66.67, places=1)
        self.assertEqual(killed, 2)
        self.assertEqual(survived, 1)
        self.assertEqual(total, 3)

    def test_empty_mutmut_output(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from mutation_check import _parse_mutmut_score
        finally:
            sys.path.pop(0)
        score, killed, survived, total = _parse_mutmut_score("")
        self.assertEqual(score, 0.0)
        self.assertEqual(total, 0)


class TestMutationThreshold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tool_not_found_exits_1(self):
        r = _run_check([self.tmp, "mutmut", "60"])
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
