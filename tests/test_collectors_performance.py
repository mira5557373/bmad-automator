# tests/test_collectors_performance.py
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class LighthouseCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.performance import LIGHTHOUSE

        self.assertEqual(LIGHTHOUSE.collector_id, "lighthouse-performance")
        self.assertEqual(LIGHTHOUSE.tool, "lhci")
        self.assertEqual(LIGHTHOUSE.category, "performance")
        self.assertTrue(LIGHTHOUSE.deterministic)
        self.assertIn("*.ts", LIGHTHOUSE.file_patterns)
        self.assertIn("*.css", LIGHTHOUSE.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.performance import LIGHTHOUSE

        cmd = LIGHTHOUSE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "lhci")
        self.assertIn("autorun", cmd)

    def test_build_cmd_custom_config(self) -> None:
        from story_automator.core.collectors.performance import LIGHTHOUSE

        profile = {"rules": {"performance": {"lhci_config": "lighthouserc.custom.json"}}}
        cmd = LIGHTHOUSE.build_cmd("/tmp/checkout", profile)
        self.assertIn("--config=lighthouserc.custom.json", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.performance import LIGHTHOUSE

        self.assertIsNotNone(LIGHTHOUSE.tool_version_cmd)
        self.assertIn("lhci", LIGHTHOUSE.tool_version_cmd)


class BundlesizeCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.performance import BUNDLESIZE

        self.assertEqual(BUNDLESIZE.collector_id, "bundlesize-performance")
        self.assertEqual(BUNDLESIZE.tool, "bundlesize")
        self.assertEqual(BUNDLESIZE.category, "performance")
        self.assertTrue(BUNDLESIZE.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.performance import BUNDLESIZE

        cmd = BUNDLESIZE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "npx")
        self.assertIn("bundlesize", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.performance import BUNDLESIZE

        self.assertIsNotNone(BUNDLESIZE.tool_version_cmd)


class PerfLintCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.performance import PERF_LINT

        self.assertEqual(PERF_LINT.collector_id, "perf-lint-performance")
        self.assertEqual(PERF_LINT.tool, "python3")
        self.assertEqual(PERF_LINT.category, "performance")
        self.assertTrue(PERF_LINT.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.performance import PERF_LINT

        cmd = PERF_LINT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("perf_lint_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_extensions(self) -> None:
        from story_automator.core.collectors.performance import PERF_LINT

        profile = {"rules": {"performance": {"lint_extensions": [".py", ".rs"]}}}
        cmd = PERF_LINT.build_cmd("/tmp/checkout", profile)
        extensions = json.loads(cmd[3])
        self.assertEqual(extensions, [".py", ".rs"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.performance import PERF_LINT

        cmd = PERF_LINT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class PerformanceCollectorListTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.performance import COLLECTORS

        self.assertEqual(len(COLLECTORS), 3)

    def test_all_performance_category(self) -> None:
        from story_automator.core.collectors.performance import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "performance")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.performance import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "lighthouse-performance", "bundlesize-performance",
            "perf-lint-performance",
        })

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.performance import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
