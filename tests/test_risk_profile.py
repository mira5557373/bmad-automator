from __future__ import annotations

import unittest

from story_automator.core.risk_profile import (
    DEFAULT_RISK_THRESHOLDS,
    VALID_RISK_CATEGORIES,
    RiskProfileError,
    aggregate_risk_priority,
    has_unmitigated_risk_9,
    make_risk_entry,
    risk_score_to_priority,
    validate_risk_entry,
    validate_risk_profile,
)


class RiskCategoriesTests(unittest.TestCase):
    def test_all_six_categories_present(self) -> None:
        self.assertEqual(
            VALID_RISK_CATEGORIES,
            frozenset({"TECH", "SEC", "PERF", "DATA", "BUS", "OPS"}),
        )


class ValidateRiskEntryTests(unittest.TestCase):
    def test_valid_entry(self) -> None:
        entry = {
            "category": "SEC", "probability": 3, "impact": 3,
            "score": 9, "rationale": "critical auth flow",
        }
        validate_risk_entry(entry)

    def test_invalid_category(self) -> None:
        entry = {
            "category": "UNKNOWN", "probability": 1, "impact": 1,
            "score": 1,
        }
        with self.assertRaises(RiskProfileError):
            validate_risk_entry(entry)

    def test_probability_out_of_range(self) -> None:
        for bad in (0, 4, -1):
            with self.assertRaises(RiskProfileError):
                validate_risk_entry({
                    "category": "TECH", "probability": bad,
                    "impact": 1, "score": bad,
                })

    def test_impact_out_of_range(self) -> None:
        for bad in (0, 4, -1):
            with self.assertRaises(RiskProfileError):
                validate_risk_entry({
                    "category": "TECH", "probability": 1,
                    "impact": bad, "score": bad,
                })

    def test_score_must_equal_probability_times_impact(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": 2,
                "impact": 3, "score": 5,
            })

    def test_missing_category_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({"probability": 1, "impact": 1, "score": 1})

    def test_boolean_probability_rejected(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": True,
                "impact": 1, "score": 1,
            })

    def test_rationale_must_be_string_if_present(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_entry({
                "category": "TECH", "probability": 1,
                "impact": 1, "score": 1, "rationale": 42,
            })


class ValidateRiskProfileTests(unittest.TestCase):
    def test_valid_profile(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            {"category": "TECH", "probability": 2, "impact": 2, "score": 4},
        ]
        validate_risk_profile(entries)

    def test_empty_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_profile([])

    def test_duplicate_category_raises(self) -> None:
        entries = [
            {"category": "SEC", "probability": 3, "impact": 3, "score": 9},
            {"category": "SEC", "probability": 1, "impact": 1, "score": 1},
        ]
        with self.assertRaises(RiskProfileError):
            validate_risk_profile(entries)

    def test_non_list_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            validate_risk_profile("not a list")


class MakeRiskEntryTests(unittest.TestCase):
    def test_computes_score(self) -> None:
        entry = make_risk_entry("PERF", 2, 3, rationale="latency risk")
        self.assertEqual(entry["score"], 6)
        self.assertEqual(entry["category"], "PERF")
        self.assertEqual(entry["rationale"], "latency risk")

    def test_invalid_category_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            make_risk_entry("INVALID", 1, 1)

    def test_score_range_1_to_9(self) -> None:
        entry_min = make_risk_entry("TECH", 1, 1)
        entry_max = make_risk_entry("TECH", 3, 3)
        self.assertEqual(entry_min["score"], 1)
        self.assertEqual(entry_max["score"], 9)


class RiskScoreToPriorityTests(unittest.TestCase):
    def test_score_9_is_p0(self) -> None:
        self.assertEqual(risk_score_to_priority(9), "P0")

    def test_scores_6_7_8_are_p1(self) -> None:
        for score in (6, 7, 8):
            self.assertEqual(risk_score_to_priority(score), "P1", f"score={score}")

    def test_scores_3_4_5_are_p2(self) -> None:
        for score in (3, 4, 5):
            self.assertEqual(risk_score_to_priority(score), "P2", f"score={score}")

    def test_scores_1_2_are_p3(self) -> None:
        for score in (1, 2):
            self.assertEqual(risk_score_to_priority(score), "P3", f"score={score}")

    def test_custom_thresholds(self) -> None:
        custom = {7: "P0", 4: "P1", 2: "P2", 1: "P3"}
        self.assertEqual(risk_score_to_priority(9, thresholds=custom), "P0")
        self.assertEqual(risk_score_to_priority(5, thresholds=custom), "P1")
        self.assertEqual(risk_score_to_priority(3, thresholds=custom), "P2")
        self.assertEqual(risk_score_to_priority(1, thresholds=custom), "P3")

    def test_out_of_range_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            risk_score_to_priority(0)
        with self.assertRaises(RiskProfileError):
            risk_score_to_priority(10)

    def test_default_thresholds_has_four_entries(self) -> None:
        self.assertEqual(len(DEFAULT_RISK_THRESHOLDS), 4)


class AggregateRiskPriorityTests(unittest.TestCase):
    def test_worst_priority_wins(self) -> None:
        entries = [
            make_risk_entry("TECH", 1, 1),   # score=1 → P3
            make_risk_entry("SEC", 3, 3),    # score=9 → P0
            make_risk_entry("PERF", 2, 2),   # score=4 → P2
        ]
        self.assertEqual(aggregate_risk_priority(entries), "P0")

    def test_single_entry(self) -> None:
        entries = [make_risk_entry("DATA", 2, 1)]  # score=2 → P3
        self.assertEqual(aggregate_risk_priority(entries), "P3")

    def test_all_low_risk(self) -> None:
        entries = [
            make_risk_entry("TECH", 1, 1),  # P3
            make_risk_entry("OPS", 1, 2),   # P3
        ]
        self.assertEqual(aggregate_risk_priority(entries), "P3")

    def test_empty_raises(self) -> None:
        with self.assertRaises(RiskProfileError):
            aggregate_risk_priority([])


class HasUnmitigatedRisk9Tests(unittest.TestCase):
    def test_no_score_9(self) -> None:
        entries = [make_risk_entry("TECH", 2, 3)]  # score=6
        self.assertFalse(has_unmitigated_risk_9(entries))

    def test_score_9_without_rationale(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]  # score=9, no rationale
        self.assertTrue(has_unmitigated_risk_9(entries))

    def test_score_9_with_rationale(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated by WAF")]
        self.assertFalse(has_unmitigated_risk_9(entries))

    def test_mixed_some_mitigated(self) -> None:
        entries = [
            make_risk_entry("SEC", 3, 3, rationale="mitigated"),
            make_risk_entry("DATA", 3, 3),  # score=9, no rationale
        ]
        self.assertTrue(has_unmitigated_risk_9(entries))


if __name__ == "__main__":
    unittest.main()
