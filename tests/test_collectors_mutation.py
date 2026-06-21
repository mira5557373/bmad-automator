from __future__ import annotations

import sys
import unittest
from pathlib import Path


class MutmutCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.mutation import MUTMUT

        self.assertEqual(MUTMUT.collector_id, "mutmut-mutation")
        self.assertEqual(MUTMUT.tool, "python3")
        self.assertEqual(MUTMUT.category, "mutation")
        self.assertTrue(MUTMUT.deterministic)
        self.assertIn("*.py", MUTMUT.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.mutation import MUTMUT

        cmd = MUTMUT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("mutation_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "mutmut")
        self.assertEqual(cmd[4], "80")

    def test_build_cmd_custom_threshold(self) -> None:
        from story_automator.core.collectors.mutation import MUTMUT

        profile = {"rules": {"mutation": {"threshold": 90}}}
        cmd = MUTMUT.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[4], "90")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.mutation import MUTMUT

        cmd = MUTMUT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class StrykerCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.mutation import STRYKER

        self.assertEqual(STRYKER.collector_id, "stryker-mutation")
        self.assertEqual(STRYKER.tool, "python3")
        self.assertEqual(STRYKER.category, "mutation")
        self.assertTrue(STRYKER.deterministic)
        self.assertIn("*.ts", STRYKER.file_patterns)
        self.assertIn("*.tsx", STRYKER.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.mutation import STRYKER

        cmd = STRYKER.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("mutation_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "stryker")
        self.assertEqual(cmd[4], "80")

    def test_build_cmd_custom_threshold(self) -> None:
        from story_automator.core.collectors.mutation import STRYKER

        profile = {"rules": {"mutation": {"threshold": 95}}}
        cmd = STRYKER.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[4], "95")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.mutation import STRYKER

        cmd = STRYKER.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class MutationCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.mutation import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_mutation_category(self) -> None:
        from story_automator.core.collectors.mutation import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "mutation")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.mutation import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"mutmut-mutation", "stryker-mutation"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.mutation import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
