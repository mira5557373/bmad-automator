from __future__ import annotations

import unittest

from story_automator.core.category_rules import (
    correctness_rule,
    coverage_verdict,
    risk_to_requirements,
    worst_evidence_status,
)
from story_automator.core.gate_schema import make_evidence_record


class CoverageVerdictTests(unittest.TestCase):
    def test_p0_100_passes(self) -> None:
        self.assertEqual(coverage_verdict(100.0, 100, "P0"), "PASS")

    def test_p0_below_100_fails(self) -> None:
        self.assertEqual(coverage_verdict(99.9, 100, "P0"), "FAIL")

    def test_p1_at_target_passes(self) -> None:
        self.assertEqual(coverage_verdict(90.0, 90, "P1"), "PASS")

    def test_p1_above_target_passes(self) -> None:
        self.assertEqual(coverage_verdict(95.0, 90, "P1"), "PASS")

    def test_p1_between_80_and_target_concerns(self) -> None:
        self.assertEqual(coverage_verdict(85.0, 90, "P1"), "CONCERNS")

    def test_p1_at_80_concerns(self) -> None:
        self.assertEqual(coverage_verdict(80.0, 90, "P1"), "CONCERNS")

    def test_p1_below_80_fails(self) -> None:
        self.assertEqual(coverage_verdict(79.9, 90, "P1"), "FAIL")

    def test_p2_at_target_passes(self) -> None:
        self.assertEqual(coverage_verdict(50.0, 50, "P2"), "PASS")

    def test_p2_below_target_fails(self) -> None:
        self.assertEqual(coverage_verdict(49.0, 50, "P2"), "FAIL")

    def test_p3_at_target_passes(self) -> None:
        self.assertEqual(coverage_verdict(20.0, 20, "P3"), "PASS")

    def test_p3_below_target_fails(self) -> None:
        self.assertEqual(coverage_verdict(10.0, 20, "P3"), "FAIL")

    def test_zero_target_always_passes(self) -> None:
        self.assertEqual(coverage_verdict(0.0, 0, "P3"), "PASS")


class RiskToRequirementsTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
            "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
            "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
    }

    def test_p0_returns_full_requirements(self) -> None:
        req = risk_to_requirements("P0", self.PROFILE)
        self.assertEqual(req["coverage_pct"], 100)
        self.assertIn("e2e", req["levels"])
        self.assertEqual(req["priority"], "P0")

    def test_p1_returns_p1_requirements(self) -> None:
        req = risk_to_requirements("P1", self.PROFILE)
        self.assertEqual(req["coverage_pct"], 90)
        self.assertIn("api", req["levels"])

    def test_p3_returns_minimal_requirements(self) -> None:
        req = risk_to_requirements("P3", self.PROFILE)
        self.assertEqual(req["coverage_pct"], 20)
        self.assertEqual(req["levels"], ["smoke"])

    def test_unknown_priority_defaults_to_p1(self) -> None:
        req = risk_to_requirements("P99", self.PROFILE)
        self.assertEqual(req["coverage_pct"], 90)
        self.assertEqual(req["priority"], "P1")

    def test_empty_priority_defaults_to_p1(self) -> None:
        req = risk_to_requirements("", self.PROFILE)
        self.assertEqual(req["priority"], "P1")


class WorstEvidenceStatusTests(unittest.TestCase):
    def test_all_ok(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
            make_evidence_record(collector="b", tool="t", category="x", status="ok"),
        ]
        self.assertEqual(worst_evidence_status(records), "ok")

    def test_violation_worse_than_ok(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
            make_evidence_record(collector="b", tool="t", category="x", status="violation"),
        ]
        self.assertEqual(worst_evidence_status(records), "violation")

    def test_timeout_worse_than_violation(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="violation"),
            make_evidence_record(collector="b", tool="t", category="x", status="timeout",
                                 findings=["TIMEOUT: t exceeded 10s"]),
        ]
        self.assertEqual(worst_evidence_status(records), "timeout")

    def test_error_worst(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="timeout",
                                 findings=["TIMEOUT"]),
            make_evidence_record(collector="b", tool="t", category="x", status="error",
                                 findings=["crash"]),
        ]
        self.assertEqual(worst_evidence_status(records), "error")

    def test_empty_list_fail_closed(self) -> None:
        self.assertEqual(worst_evidence_status([]), "error")


class CorrectnessRuleTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
            "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
    }
    REQUIRED_P1 = {"coverage_pct": 90, "levels": ["unit", "integration", "api"], "priority": "P1"}

    def test_all_green_above_threshold_passes(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "PASS")

    def test_coverage_below_target_above_80_concerns_for_p1(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 85, "regressions": 0},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "CONCERNS")

    def test_coverage_below_80_fails_for_p1(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 70, "regressions": 0},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_regressions_cause_fail(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 2},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_error_status_fail_closed(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="error", findings=["crash"],
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_timeout_status_fail_closed(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="timeout", findings=["TIMEOUT: pytest exceeded 1800s"],
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_no_coverage_metric_uses_zero(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")

    def test_result_has_required_and_actual(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertIn("required", result)
        self.assertIn("actual", result)
        self.assertIn("rationale", result)
        self.assertEqual(result["actual"]["coverage_pct"], 95)


if __name__ == "__main__":
    unittest.main()
