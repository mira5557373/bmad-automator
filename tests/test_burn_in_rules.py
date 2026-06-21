from __future__ import annotations

import unittest

from story_automator.core import category_rules
from story_automator.core.category_rules import CATEGORY_RULES


def _make_evidence(status="ok", metrics=None, category="test_quality"):
    return {
        "schema_version": 1,
        "collector": "test-collector",
        "tool": "test-tool",
        "category": category,
        "status": status,
        "metrics": metrics or {},
        "findings": [],
        "deterministic": True,
    }


class TestTestQualityRule(unittest.TestCase):
    def _profile(self, **overrides):
        rules = {"min_score": 70, "burn_in_runs": 5, "max_flaky": 0}
        rules.update(overrides)
        return {"rules": {"test_quality": rules}}

    def test_all_pass(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 0}),
            _make_evidence(metrics={"hard_wait_count": 0}),
            _make_evidence(metrics={"test_review_score": 85}),
        ]
        result = category_rules.test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "PASS")

    def test_flaky_detected_fails(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 2}),
            _make_evidence(metrics={"hard_wait_count": 0}),
        ]
        result = category_rules.test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("flaky", result["rationale"])

    def test_hard_wait_fails(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 0}),
            _make_evidence(metrics={"hard_wait_count": 3}),
        ]
        result = category_rules.test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("hard-wait", result["rationale"])

    def test_low_test_review_score_fails(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 0}),
            _make_evidence(metrics={"hard_wait_count": 0}),
            _make_evidence(metrics={"test_review_score": 50}),
        ]
        result = category_rules.test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("test-review", result["rationale"])

    def test_missing_tea_score_passes(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 0}),
            _make_evidence(metrics={"hard_wait_count": 0}),
        ]
        result = category_rules.test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "PASS")

    def test_error_status_fail_closed(self):
        evidence = [_make_evidence(status="error")]
        result = category_rules.test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("fail-closed", result["rationale"])

    def test_timeout_status_fail_closed(self):
        evidence = [_make_evidence(status="timeout")]
        result = category_rules.test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_custom_max_flaky(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 2}),
            _make_evidence(metrics={"hard_wait_count": 0}),
        ]
        result = category_rules.test_quality_rule(evidence, self._profile(max_flaky=5), {})
        self.assertEqual(result["verdict"], "PASS")


class TestTestQualityRegistered(unittest.TestCase):
    def test_registered_in_category_rules(self):
        self.assertIn("test_quality", CATEGORY_RULES)
        self.assertIs(CATEGORY_RULES["test_quality"], category_rules.test_quality_rule)


if __name__ == "__main__":
    unittest.main()
