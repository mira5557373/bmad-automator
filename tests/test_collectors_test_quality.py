from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class TestReviewCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.test_quality import TEST_REVIEW

        self.assertEqual(TEST_REVIEW.collector_id, "test-review-test_quality")
        self.assertEqual(TEST_REVIEW.tool, "python3")
        self.assertEqual(TEST_REVIEW.category, "test_quality")
        self.assertTrue(TEST_REVIEW.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.test_quality import TEST_REVIEW

        cmd = TEST_REVIEW.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("test_review_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "70")

    def test_build_cmd_custom_score(self) -> None:
        from story_automator.core.collectors.test_quality import TEST_REVIEW

        profile = {"rules": {"test_quality": {"min_score": 85}}}
        cmd = TEST_REVIEW.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "85")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.test_quality import TEST_REVIEW

        cmd = TEST_REVIEW.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class BurnInCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.test_quality import BURN_IN

        self.assertEqual(BURN_IN.collector_id, "burn-in-test_quality")
        self.assertEqual(BURN_IN.tool, "python3")
        self.assertEqual(BURN_IN.category, "test_quality")
        self.assertTrue(BURN_IN.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.test_quality import BURN_IN

        cmd = BURN_IN.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("burn_in_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "5")
        self.assertEqual(cmd[4], "0")
        test_cmd = json.loads(cmd[5])
        self.assertEqual(test_cmd, ["pytest", "-v", "--tb=line"])

    def test_build_cmd_custom_config(self) -> None:
        from story_automator.core.collectors.test_quality import BURN_IN

        profile = {
            "rules": {
                "test_quality": {
                    "burn_in_runs": 10,
                    "max_flaky": 2,
                    "burn_in_cmd": ["npx", "vitest", "run"],
                },
            },
        }
        cmd = BURN_IN.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "10")
        self.assertEqual(cmd[4], "2")
        test_cmd = json.loads(cmd[5])
        self.assertEqual(test_cmd, ["npx", "vitest", "run"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.test_quality import BURN_IN

        cmd = BURN_IN.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class HardWaitCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.test_quality import HARD_WAIT

        self.assertEqual(HARD_WAIT.collector_id, "hard-wait-test_quality")
        self.assertEqual(HARD_WAIT.tool, "python3")
        self.assertEqual(HARD_WAIT.category, "test_quality")
        self.assertTrue(HARD_WAIT.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.test_quality import HARD_WAIT

        cmd = HARD_WAIT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("hard_wait_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.test_quality import HARD_WAIT

        cmd = HARD_WAIT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class TestQualityCollectorListTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.test_quality import COLLECTORS

        self.assertEqual(len(COLLECTORS), 3)

    def test_all_test_quality_category(self) -> None:
        from story_automator.core.collectors.test_quality import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "test_quality")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.test_quality import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "test-review-test_quality",
            "burn-in-test_quality",
            "hard-wait-test_quality",
        })

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.test_quality import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
