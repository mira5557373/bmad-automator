import unittest

from story_automator.core.profile_calibrator import CalibrationProposal
from story_automator.core.retrospective_bridge import (
    build_retrospective_summary,
    format_retrospective_markdown,
)


class BuildRetrospectiveSummaryTests(unittest.TestCase):
    def test_empty_inputs(self) -> None:
        summary = build_retrospective_summary(
            {"total_gates": 0, "pass_rate": 0.0, "fail_rate": 0.0,
             "concerns_rate": 0.0, "waived_rate": 0.0,
             "per_category": {}, "flaky_categories": [],
             "timeout_categories": []},
            [],
        )
        self.assertEqual(summary["total_gates"], 0)
        self.assertEqual(summary["calibrations_applied"], 0)

    def test_includes_key_metrics(self) -> None:
        metrics = {
            "total_gates": 10, "pass_rate": 0.7, "fail_rate": 0.2,
            "concerns_rate": 0.1, "waived_rate": 0.0,
            "per_category": {"security": {"fail_count": 2, "pass_count": 8}},
            "flaky_categories": ["correctness"],
            "timeout_categories": ["performance"],
        }
        summary = build_retrospective_summary(metrics, [])
        self.assertEqual(summary["total_gates"], 10)
        self.assertAlmostEqual(summary["pass_rate"], 0.7)
        self.assertIn("correctness", summary["flaky_categories"])
        self.assertIn("performance", summary["timeout_categories"])

    def test_includes_calibration_count(self) -> None:
        metrics = {
            "total_gates": 5, "pass_rate": 0.8, "fail_rate": 0.2,
            "concerns_rate": 0.0, "waived_rate": 0.0,
            "per_category": {}, "flaky_categories": [],
            "timeout_categories": [],
        }
        proposals = [
            CalibrationProposal("s", "timeouts.s", 300, 450, "r", 0.9, "feature"),
        ]
        summary = build_retrospective_summary(metrics, proposals)
        self.assertEqual(summary["calibrations_applied"], 1)


class FormatRetrospectiveMarkdownTests(unittest.TestCase):
    def test_produces_markdown(self) -> None:
        summary = {
            "total_gates": 10, "pass_rate": 0.7,
            "fail_rate": 0.2, "concerns_rate": 0.1,
            "waived_rate": 0.0,
            "flaky_categories": ["correctness"],
            "timeout_categories": [],
            "calibrations_applied": 1,
            "calibrations_deferred": 0,
            "top_failing_categories": [("security", 2)],
        }
        md = format_retrospective_markdown(summary)
        self.assertIn("Gate Quality Summary", md)
        self.assertIn("70.0%", md)
        self.assertIn("correctness", md)

    def test_empty_summary(self) -> None:
        summary = {
            "total_gates": 0, "pass_rate": 0.0,
            "fail_rate": 0.0, "concerns_rate": 0.0,
            "waived_rate": 0.0,
            "flaky_categories": [],
            "timeout_categories": [],
            "calibrations_applied": 0,
            "calibrations_deferred": 0,
            "top_failing_categories": [],
        }
        md = format_retrospective_markdown(summary)
        self.assertIsInstance(md, str)
        self.assertIn("No gate evaluations", md)


if __name__ == "__main__":
    unittest.main()
