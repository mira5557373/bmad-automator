# tests/test_collectors_traceability.py
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class TraceCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        self.assertEqual(TRACE.collector_id, "trace-traceability")
        self.assertEqual(TRACE.tool, "python3")
        self.assertEqual(TRACE.category, "traceability")
        self.assertTrue(TRACE.deterministic)
        self.assertIn("*.md", TRACE.file_patterns)
        self.assertIn("*.json", TRACE.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        cmd = TRACE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("traceability_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        thresholds = json.loads(cmd[3])
        self.assertEqual(thresholds["P0"], 100)
        self.assertEqual(thresholds["P1"], 90)

    def test_build_cmd_custom_thresholds(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        profile = {
            "matrix": {
                "P0": {"coverage_pct": 100},
                "P1": {"coverage_pct": 80},
            },
        }
        cmd = TRACE.build_cmd("/tmp/checkout", profile)
        thresholds = json.loads(cmd[3])
        self.assertEqual(thresholds["P0"], 100)
        self.assertEqual(thresholds["P1"], 80)

    def test_build_cmd_custom_tea_path(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        profile = {
            "rules": {"traceability": {"tea_trace_path": "custom/trace.json"}},
        }
        cmd = TRACE.build_cmd("/tmp/checkout", profile)
        self.assertIn("custom/trace.json", cmd)

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        cmd = TRACE.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class TraceabilityCollectorListTests(unittest.TestCase):
    def test_one_collector(self) -> None:
        from story_automator.core.collectors.traceability import COLLECTORS

        self.assertEqual(len(COLLECTORS), 1)

    def test_all_traceability_category(self) -> None:
        from story_automator.core.collectors.traceability import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "traceability")

    def test_expected_id(self) -> None:
        from story_automator.core.collectors.traceability import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"trace-traceability"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.traceability import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
