from __future__ import annotations

import unittest

from story_automator.core.collectors.test_quality import (
    BURN_IN,
    HARD_WAIT,
    TEST_REVIEW,
    COLLECTORS,
)


class TestBurnInCollector(unittest.TestCase):
    def test_category_is_test_quality(self):
        self.assertEqual(BURN_IN.category, "test_quality")

    def test_collector_id(self):
        self.assertEqual(BURN_IN.collector_id, "burn-in-test-quality")

    def test_tool(self):
        self.assertEqual(BURN_IN.tool, "python3")

    def test_build_cmd_includes_burn_in_runs(self):
        profile = {"rules": {"test_quality": {"burn_in_runs": 3}}, "timeouts": {"test_quality": 900}}
        cmd = BURN_IN.build_cmd("/checkout", profile)
        self.assertIn("burn_in_check.py", cmd[1])
        self.assertIn("3", cmd)
        self.assertIn("--timeout", cmd)
        self.assertIn("--", cmd)

    def test_build_cmd_default_runs(self):
        profile = {"rules": {}}
        cmd = BURN_IN.build_cmd("/checkout", profile)
        self.assertIn("5", cmd)
        self.assertIn("--timeout", cmd)


class TestHardWaitCollector(unittest.TestCase):
    def test_category_is_test_quality(self):
        self.assertEqual(HARD_WAIT.category, "test_quality")

    def test_collector_id(self):
        self.assertEqual(HARD_WAIT.collector_id, "hard-wait-test-quality")

    def test_build_cmd(self):
        cmd = HARD_WAIT.build_cmd("/checkout", {})
        self.assertIn("hard_wait_check.py", cmd[1])
        self.assertEqual(cmd[2], "/checkout")


class TestTestReviewCollector(unittest.TestCase):
    def test_category_is_test_quality(self):
        self.assertEqual(TEST_REVIEW.category, "test_quality")

    def test_collector_id(self):
        self.assertEqual(TEST_REVIEW.collector_id, "test-review-test-quality")

    def test_deterministic_is_false(self):
        self.assertFalse(TEST_REVIEW.deterministic)

    def test_build_cmd(self):
        profile = {"rules": {"test_quality": {"min_score": 70}}}
        cmd = TEST_REVIEW.build_cmd("/checkout", profile)
        self.assertIn("test_review_check.py", cmd[1])


class TestCollectorsList(unittest.TestCase):
    def test_all_three_present(self):
        self.assertEqual(len(COLLECTORS), 3)
        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("burn-in-test-quality", ids)
        self.assertIn("hard-wait-test-quality", ids)
        self.assertIn("test-review-test-quality", ids)

    def test_all_category_test_quality(self):
        for c in COLLECTORS:
            self.assertEqual(c.category, "test_quality")


if __name__ == "__main__":
    unittest.main()
