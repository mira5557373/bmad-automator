"""Regression tests for bug L3: _aggregate_metrics dropped later records.

Before the fix, ``_aggregate_metrics`` returned the first record that
contained the requested key, silently dropping metrics from every later
collector. For multi-collector categories (security/correctness/test
quality/license) this meant a clean first record could mask a violating
second record, producing a false PASS.

The fix replaces the "first match wins" behavior with a per-metric
reducer table — counts (e.g. ``sast_high_count``) aggregate via ``sum``
across records, while values where lower is worse (e.g. ``coverage_pct``,
``mutation_score``) aggregate via ``min``. Booleans aggregate via worst-
case (``any`` for "bad if true" flags such as ``slo_breached``).
"""
from __future__ import annotations

import unittest

from story_automator.core.category_rules import (
    _aggregate_metrics,
    correctness_rule,
    license_rule,
    security_rule,
    test_quality_rule,
)
from story_automator.core.gate_schema import make_evidence_record


class AggregateMetricsMultiRecordTests(unittest.TestCase):
    """Direct tests of _aggregate_metrics across multiple records."""

    def test_count_metric_sums_across_records(self) -> None:
        records = [
            make_evidence_record(
                collector="semgrep", tool="semgrep", category="security",
                status="ok", metrics={"sast_high_count": 0},
            ),
            make_evidence_record(
                collector="bandit", tool="bandit", category="security",
                status="violation", metrics={"sast_high_count": 3},
                findings=["SQLi"],
            ),
        ]
        # Before fix: returned 0 (first record). After fix: sums to 3.
        self.assertEqual(_aggregate_metrics(records, "sast_high_count", 0), 3)

    def test_coverage_metric_takes_minimum(self) -> None:
        records = [
            make_evidence_record(
                collector="pytest-unit", tool="pytest", category="correctness",
                status="ok", metrics={"coverage_pct": 95},
            ),
            make_evidence_record(
                collector="pytest-integration", tool="pytest", category="correctness",
                status="ok", metrics={"coverage_pct": 60},
            ),
        ]
        # Before fix: 95 (first). After fix: 60 (worst, fail-closed).
        self.assertEqual(_aggregate_metrics(records, "coverage_pct", 0), 60)

    def test_missing_in_first_present_in_second_still_found(self) -> None:
        records = [
            make_evidence_record(
                collector="a", tool="t", category="security",
                status="ok", metrics={},
            ),
            make_evidence_record(
                collector="b", tool="t", category="security",
                status="violation", metrics={"secrets_count": 2},
                findings=["api key"],
            ),
        ]
        self.assertEqual(_aggregate_metrics(records, "secrets_count", 0), 2)

    def test_default_returned_when_no_record_has_key(self) -> None:
        records = [
            make_evidence_record(
                collector="a", tool="t", category="security",
                status="ok", metrics={},
            ),
            make_evidence_record(
                collector="b", tool="t", category="security",
                status="ok", metrics={},
            ),
        ]
        self.assertEqual(_aggregate_metrics(records, "sast_high_count", 0), 0)

    def test_bool_metric_any_true_aggregates_true(self) -> None:
        records = [
            make_evidence_record(
                collector="a", tool="t", category="blast_radius",
                status="ok", metrics={"slo_breached": False},
            ),
            make_evidence_record(
                collector="b", tool="t", category="blast_radius",
                status="violation", metrics={"slo_breached": True},
                findings=["SLO breach"],
            ),
        ]
        # Worst of: True OR False = True (any). Before fix: False.
        self.assertTrue(_aggregate_metrics(records, "slo_breached", False))


class SecurityRuleMultiCollectorTests(unittest.TestCase):
    """Multi-collector security: a clean record must NOT mask a violating one."""

    PROFILE = {
        "rules": {
            "security": {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 0},
        },
    }
    REQ = {"priority": "P1"}

    def test_clean_first_then_violating_second_fails(self) -> None:
        # semgrep finds nothing (ok, 0 high), bandit finds 5 high in a different
        # part of the tree. Before fix: silently PASSED. After fix: FAIL.
        evidence = [
            make_evidence_record(
                collector="semgrep", tool="semgrep", category="security",
                status="ok", metrics={"sast_high_count": 0},
            ),
            make_evidence_record(
                collector="bandit", tool="bandit", category="security",
                status="violation", metrics={"sast_high_count": 5},
                findings=["SQLi", "XXE", "deser", "cmd-inj", "path-trav"],
            ),
        ]
        result = security_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["actual"]["sast_high_count"], 5)


class CorrectnessRuleMultiCollectorTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
    }
    REQUIRED_P1 = {"coverage_pct": 90, "levels": [], "priority": "P1"}

    def test_worst_coverage_used_across_tiers(self) -> None:
        # Unit suite has 95% coverage, but integration suite only 70%.
        # The worst (70%) must be used for the verdict, not the first (95%).
        evidence = [
            make_evidence_record(
                collector="unit", tool="pytest", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ),
            make_evidence_record(
                collector="integration", tool="pytest", category="correctness",
                status="ok", metrics={"coverage_pct": 70, "regressions": 0},
            ),
        ]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["actual"]["coverage_pct"], 70)

    def test_regressions_summed_across_records(self) -> None:
        # Two suites each report 1 regression. Total must be 2 (>0 => FAIL).
        evidence = [
            make_evidence_record(
                collector="unit", tool="pytest", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 1},
            ),
            make_evidence_record(
                collector="integration", tool="pytest", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 1},
            ),
        ]
        result = correctness_rule(evidence, self.PROFILE, self.REQUIRED_P1)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["actual"]["regressions"], 2)


class LicenseRuleMultiCollectorTests(unittest.TestCase):
    PROFILE = {
        "rules": {
            "license": {"forbidden": ["BSL"], "boundary": {}},
        },
    }
    REQ = {"priority": "P1"}

    def test_boundary_violations_summed(self) -> None:
        evidence = [
            make_evidence_record(
                collector="syft-frontend", tool="syft", category="license",
                status="ok", metrics={"forbidden_count": 0, "boundary_violations": 0},
            ),
            make_evidence_record(
                collector="syft-backend", tool="syft", category="license",
                status="violation",
                metrics={"forbidden_count": 0, "boundary_violations": 2},
                findings=["AGPL leak"],
            ),
        ]
        result = license_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["actual"]["boundary_violations"], 2)


class TestQualityRuleMultiCollectorTests(unittest.TestCase):
    PROFILE = {
        "rules": {
            "test_quality": {"max_flaky": 0, "min_score": 70},
        },
    }
    REQ = {"priority": "P1"}

    def test_flaky_counts_sum_across_burn_in_runs(self) -> None:
        # First burn-in is clean. Second burn-in finds 3 flaky tests.
        evidence = [
            make_evidence_record(
                collector="burnin-1", tool="pytest", category="test_quality",
                status="ok", metrics={"flaky_count": 0, "hard_wait_count": 0},
            ),
            make_evidence_record(
                collector="burnin-2", tool="pytest", category="test_quality",
                status="violation", metrics={"flaky_count": 3, "hard_wait_count": 0},
                findings=["flaky: test_a", "flaky: test_b", "flaky: test_c"],
            ),
        ]
        result = test_quality_rule(evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["actual"]["flaky_count"], 3)


if __name__ == "__main__":
    unittest.main()
