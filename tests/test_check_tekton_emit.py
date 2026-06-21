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
        [sys.executable, str(_CHECKS_DIR / "tekton_emit.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


class TestTektonEmitUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)


class TestTektonEmit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_emits_pipeline_to_stdout(self):
        collectors_file = os.path.join(self.tmp, "collectors.json")
        with open(collectors_file, "w") as f:
            json.dump([
                {"collector_id": "test-collector", "category": "test", "cmd": ["echo", "ok"]},
            ], f)
        r = _run_check([collectors_file])
        self.assertEqual(r.returncode, 0)
        self.assertIn("tekton.dev", r.stdout)
        self.assertIn("PipelineRun", r.stdout)

    def test_emits_pipeline_to_file(self):
        collectors_file = os.path.join(self.tmp, "collectors.json")
        output_file = os.path.join(self.tmp, "pipeline.json")
        with open(collectors_file, "w") as f:
            json.dump([
                {"collector_id": "test-a", "category": "test", "cmd": ["echo", "a"]},
                {"collector_id": "test-b", "category": "test", "cmd": ["echo", "b"]},
            ], f)
        r = _run_check([collectors_file, output_file])
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.isfile(output_file))
        with open(output_file) as f:
            content = f.read()
        self.assertIn("PipelineRun", content)


class TestTektonEmitFunction(unittest.TestCase):
    def test_emit_pipeline(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from tekton_emit import emit_pipeline
        finally:
            sys.path.pop(0)
        result = emit_pipeline([
            {"collector_id": "foo", "category": "bar", "cmd": ["echo"]},
        ])
        self.assertIn("tekton.dev", result)
        parsed = json.loads(result.split("\n", 2)[2])
        self.assertEqual(parsed["kind"], "PipelineRun")
        self.assertEqual(len(parsed["spec"]["pipelineSpec"]["tasks"]), 1)


if __name__ == "__main__":
    unittest.main()
