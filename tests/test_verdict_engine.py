from __future__ import annotations

import unittest

from story_automator.core.gate_schema import (
    make_evidence_record,
    make_llm_evidence_record,
)
from story_automator.core.verdict_engine import (
    compute_all_verdicts,
    compute_category_verdict,
    group_evidence_by_category,
    has_llm_low_confidence,
)


class GroupEvidenceByCategoryTests(unittest.TestCase):
    def test_groups_by_category(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="correctness", status="ok"),
            make_evidence_record(collector="b", tool="t", category="security", status="ok"),
            make_evidence_record(collector="c", tool="t", category="correctness", status="violation"),
        ]
        grouped = group_evidence_by_category(records)
        self.assertEqual(len(grouped["correctness"]), 2)
        self.assertEqual(len(grouped["security"]), 1)

    def test_empty_input(self) -> None:
        self.assertEqual(group_evidence_by_category([]), {})

    def test_single_category(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="static", status="ok"),
        ]
        grouped = group_evidence_by_category(records)
        self.assertIn("static", grouped)
        self.assertEqual(len(grouped["static"]), 1)


class HasLlmLowConfidenceTests(unittest.TestCase):
    def test_no_llm_evidence(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_high_confidence_passes(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=8, rationale="good",
            ),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_low_confidence_detected(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=3, rationale="uncertain",
            ),
        ]
        self.assertTrue(has_llm_low_confidence(records))

    def test_boundary_5_passes(self) -> None:
        records = [
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=5, rationale="ok",
            ),
        ]
        self.assertFalse(has_llm_low_confidence(records))

    def test_mixed_deterministic_and_llm(self) -> None:
        records = [
            make_evidence_record(collector="a", tool="t", category="x", status="ok"),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="x",
                status="ok", confidence=4, rationale="weak",
            ),
        ]
        self.assertTrue(has_llm_low_confidence(records))


class ComputeCategoryVerdictTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
    }
    REQ = {"coverage_pct": 90, "levels": [], "priority": "P1"}

    def test_pass_verdict(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_verdict(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="violation",
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_llm_low_confidence_downgrades_pass_to_concerns(self) -> None:
        evidence = [
            make_evidence_record(collector="runner", tool="pytest", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="correctness",
                status="ok", confidence=3, rationale="uncertain about edge cases",
            ),
        ]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "CONCERNS")
        self.assertIn("confidence", result["rationale"].lower())

    def test_llm_low_confidence_does_not_upgrade_fail(self) -> None:
        evidence = [
            make_evidence_record(collector="runner", tool="pytest", category="correctness",
                                 status="violation"),
            make_llm_evidence_record(
                collector="llm", tool="claude", category="correctness",
                status="ok", confidence=3, rationale="uncertain",
            ),
        ]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertEqual(result["verdict"], "FAIL")

    def test_result_includes_evidence_refs(self) -> None:
        evidence = [make_evidence_record(
            collector="runner", tool="pytest", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        result = compute_category_verdict("correctness", evidence, self.PROFILE, self.REQ)
        self.assertIn("evidence_refs", result)
        self.assertIsInstance(result["evidence_refs"], list)


class ComputeAllVerdictsTests(unittest.TestCase):
    PROFILE = {
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": []},
            "P1": {"coverage_pct": 90, "levels": []},
            "P2": {"coverage_pct": 50, "levels": []},
            "P3": {"coverage_pct": 20, "levels": []},
        },
        "categories": {
            "code": ["correctness", "security", "static"],
            "system": [],
        },
        "categories_na": ["accessibility", "performance"],
    }

    def test_na_categories_get_na_verdict(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertEqual(verdicts["accessibility"]["verdict"], "NA")
        self.assertEqual(verdicts["performance"]["verdict"], "NA")
        self.assertIn("profile-declared", verdicts["accessibility"]["rationale"])

    def test_na_verdict_has_consistent_shape(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        na_verdict = verdicts["accessibility"]
        self.assertIn("required", na_verdict)
        self.assertIn("actual", na_verdict)
        self.assertIn("evidence_refs", na_verdict)
        self.assertEqual(na_verdict["required"], {})
        self.assertEqual(na_verdict["actual"], {})
        self.assertEqual(na_verdict["evidence_refs"], [])

    def test_evidence_categories_get_computed_verdict(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="c", tool="t", category="security",
                                 status="ok", metrics={"sast_high_count": 0}),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertEqual(verdicts["correctness"]["verdict"], "PASS")
        self.assertEqual(verdicts["security"]["verdict"], "PASS")

    def test_empty_evidence_for_active_category_fails_closed(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
        ]
        profile = dict(self.PROFILE)
        profile["categories"] = {"code": ["correctness", "security"], "system": []}
        profile["categories_na"] = []
        verdicts = compute_all_verdicts(evidence, profile, "P1")
        self.assertEqual(verdicts["security"]["verdict"], "FAIL")

    def test_returns_all_active_plus_na_categories(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="correctness",
                                 status="ok", metrics={"coverage_pct": 95, "regressions": 0}),
            make_evidence_record(collector="c", tool="t", category="security",
                                 status="ok"),
            make_evidence_record(collector="c", tool="t", category="static",
                                 status="ok"),
        ]
        verdicts = compute_all_verdicts(evidence, self.PROFILE, "P1")
        self.assertIn("correctness", verdicts)
        self.assertIn("security", verdicts)
        self.assertIn("static", verdicts)
        self.assertIn("accessibility", verdicts)
        self.assertIn("performance", verdicts)

    def test_extra_evidence_category_not_in_profile_still_evaluated(self) -> None:
        evidence = [
            make_evidence_record(collector="c", tool="t", category="docs",
                                 status="ok"),
        ]
        profile = dict(self.PROFILE)
        profile["categories"] = {"code": [], "system": []}
        verdicts = compute_all_verdicts(evidence, profile, "P1")
        self.assertIn("docs", verdicts)


if __name__ == "__main__":
    unittest.main()
