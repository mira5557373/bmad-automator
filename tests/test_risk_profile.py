from __future__ import annotations

import unittest

from story_automator.core.risk_profile import (
    VALID_RISK_CATEGORIES,
    RiskProfileError,
    make_risk_entry,
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


if __name__ == "__main__":
    unittest.main()
