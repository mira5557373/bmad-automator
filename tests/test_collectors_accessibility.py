# tests/test_collectors_accessibility.py
from __future__ import annotations

import unittest


class AxeCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        self.assertEqual(AXE.collector_id, "axe-accessibility")
        self.assertEqual(AXE.tool, "playwright")
        self.assertEqual(AXE.category, "accessibility")
        self.assertTrue(AXE.deterministic)
        self.assertIn("*.ts", AXE.file_patterns)
        self.assertIn("*.tsx", AXE.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        cmd = AXE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "npx")
        self.assertIn("playwright", cmd)
        self.assertIn("test", cmd)
        self.assertIn("--grep", cmd)
        self.assertIn("@a11y", cmd)

    def test_build_cmd_custom_grep(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        profile = {"rules": {"accessibility": {"playwright_grep": "@axe"}}}
        cmd = AXE.build_cmd("/tmp/checkout", profile)
        self.assertIn("@axe", cmd)
        self.assertNotIn("@a11y", cmd)

    def test_build_cmd_custom_config(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        profile = {"rules": {"accessibility": {"playwright_config": "e2e.config.ts"}}}
        cmd = AXE.build_cmd("/tmp/checkout", profile)
        self.assertIn("--config=e2e.config.ts", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        self.assertIsNotNone(AXE.tool_version_cmd)
        self.assertIn("playwright", AXE.tool_version_cmd)


class AccessibilityCollectorListTests(unittest.TestCase):
    def test_one_collector(self) -> None:
        from story_automator.core.collectors.accessibility import COLLECTORS

        self.assertEqual(len(COLLECTORS), 1)

    def test_all_accessibility_category(self) -> None:
        from story_automator.core.collectors.accessibility import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "accessibility")

    def test_expected_id(self) -> None:
        from story_automator.core.collectors.accessibility import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"axe-accessibility"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.accessibility import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
