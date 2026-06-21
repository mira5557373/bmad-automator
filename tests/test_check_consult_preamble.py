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
        [sys.executable, str(_CHECKS_DIR / "consult_preamble.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


def _parse_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("PREAMBLE_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


class TestConsultPreambleUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)


class TestConsultPreamble(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_fragments_exits_0(self):
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertEqual(result["fragments_found"], 0)
        self.assertIn("CONFIDENCE GATE", r.stdout)

    def test_finds_fragments(self):
        frag_dir = os.path.join(self.tmp, ".tea", "fragments")
        os.makedirs(frag_dir)
        with open(os.path.join(frag_dir, "network-first.md"), "w") as f:
            f.write("# Network First\n")
        with open(os.path.join(frag_dir, "selector-resilience.md"), "w") as f:
            f.write("# Selector Resilience\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertEqual(result["fragments_found"], 2)
        self.assertIn("network-first.md", result["fragment_names"])

    def test_writes_to_file(self):
        output = os.path.join(self.tmp, "preamble.txt")
        r = _run_check([self.tmp, output])
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.isfile(output))
        with open(output) as f:
            content = f.read()
        self.assertIn("CONFIDENCE GATE", content)


if __name__ == "__main__":
    unittest.main()
