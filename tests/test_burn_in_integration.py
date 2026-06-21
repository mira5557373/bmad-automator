from __future__ import annotations

import unittest

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.collectors import register_core_collectors
from story_automator.core.category_rules import apply_category_rule
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.verdict_engine import compute_all_verdicts


def _msme_profile():
    return {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
        "categories": {
            "code": ["test_quality", "mutation"],
            "system": [],
        },
        "categories_na": [],
        "rules": {
            "test_quality": {"min_score": 70, "burn_in_runs": 5, "max_flaky": 0},
            "mutation": {"min_score": 60},
        },
    }


class TestTestQualityPipeline(unittest.TestCase):
    def test_registry_includes_test_quality(self):
        reg = CollectorRegistry()
        register_core_collectors(reg)
        configs = reg.get_for_category("test_quality")
        self.assertGreater(len(configs), 0)
        ids = {c.collector_id for c in configs}
        self.assertIn("burn-in-test-quality", ids)
        self.assertIn("hard-wait-test-quality", ids)
        self.assertIn("test-review-test-quality", ids)

    def test_registry_includes_mutation(self):
        reg = CollectorRegistry()
        register_core_collectors(reg)
        configs = reg.get_for_category("mutation")
        self.assertGreater(len(configs), 0)
        ids = {c.collector_id for c in configs}
        self.assertIn("mutmut-mutation", ids)

    def test_applicable_filters_for_profile(self):
        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = _msme_profile()
        applicable = reg.applicable(profile)
        categories = {c.category for c in applicable}
        self.assertIn("test_quality", categories)
        self.assertIn("mutation", categories)

    def test_verdict_engine_with_test_quality_evidence(self):
        profile = _msme_profile()
        evidence = [
            make_evidence_record(
                collector="burn-in-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"flaky_count": 0},
            ),
            make_evidence_record(
                collector="hard-wait-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"hard_wait_count": 0},
            ),
        ]
        result = apply_category_rule("test_quality", evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_verdict_engine_with_flaky_evidence(self):
        profile = _msme_profile()
        evidence = [
            make_evidence_record(
                collector="burn-in-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"flaky_count": 2},
            ),
        ]
        result = apply_category_rule("test_quality", evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_verdict_engine_with_mutation_evidence(self):
        profile = _msme_profile()
        evidence = [
            make_evidence_record(
                collector="mutmut-mutation", tool="python3",
                category="mutation", status="ok",
                metrics={"mutation_score": 75.0, "mutants_total": 20,
                         "mutants_killed": 15, "mutants_survived": 5},
            ),
        ]
        result = apply_category_rule("mutation", evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_compute_all_verdicts_includes_categories(self):
        profile = _msme_profile()
        evidence_bundle = [
            make_evidence_record(
                collector="burn-in-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"flaky_count": 0},
            ),
            make_evidence_record(
                collector="mutmut-mutation", tool="python3",
                category="mutation", status="ok",
                metrics={"mutation_score": 75.0, "mutants_total": 20,
                         "mutants_killed": 15, "mutants_survived": 5},
            ),
        ]
        verdicts = compute_all_verdicts(evidence_bundle, profile, "P1")
        self.assertIn("test_quality", verdicts)
        self.assertIn("mutation", verdicts)
        self.assertEqual(verdicts["test_quality"]["verdict"], "PASS")
        self.assertEqual(verdicts["mutation"]["verdict"], "PASS")

    def test_overall_fail_on_flaky(self):
        profile = _msme_profile()
        evidence_bundle = [
            make_evidence_record(
                collector="burn-in-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"flaky_count": 3},
            ),
            make_evidence_record(
                collector="mutmut-mutation", tool="python3",
                category="mutation", status="ok",
                metrics={"mutation_score": 75.0, "mutants_total": 20,
                         "mutants_killed": 15, "mutants_survived": 5},
            ),
        ]
        verdicts = compute_all_verdicts(evidence_bundle, profile, "P1")
        self.assertEqual(verdicts["test_quality"]["verdict"], "FAIL")
        self.assertEqual(verdicts["mutation"]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
