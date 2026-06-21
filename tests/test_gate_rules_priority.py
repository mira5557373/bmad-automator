"""Tests for TEA priority-threshold semantics in gate_rules.

M26: evaluate_priority_threshold + gate_eligible.
"""
from __future__ import annotations

import unittest

from story_automator.core.gate_rules import (
    COLLECTION_STATUSES,
    PRIORITY_THRESHOLDS,
    evaluate_priority_threshold,
    gate_eligible,
)


class PriorityThresholdConstantsTests(unittest.TestCase):
    def test_priority_thresholds_contains_p0_through_p3(self) -> None:
        self.assertEqual(
            set(PRIORITY_THRESHOLDS.keys()), {"P0", "P1", "P2", "P3"},
        )

    def test_p0_requires_100_with_floor_100(self) -> None:
        self.assertEqual(PRIORITY_THRESHOLDS["P0"], (100, 100))

    def test_p1_requires_95_with_floor_90(self) -> None:
        self.assertEqual(PRIORITY_THRESHOLDS["P1"], (95, 90))

    def test_p2_requires_85_with_floor_80(self) -> None:
        self.assertEqual(PRIORITY_THRESHOLDS["P2"], (85, 80))

    def test_p3_requires_70_with_floor_0(self) -> None:
        self.assertEqual(PRIORITY_THRESHOLDS["P3"], (70, 0))

    def test_collection_statuses_is_frozenset(self) -> None:
        self.assertIsInstance(COLLECTION_STATUSES, frozenset)

    def test_collection_statuses_membership(self) -> None:
        self.assertEqual(
            COLLECTION_STATUSES,
            frozenset({"COLLECTED", "MISSING", "ERROR", "TIMEOUT"}),
        )


class EvaluatePriorityThresholdTests(unittest.TestCase):
    # P0 band: required 100, floor 100
    def test_p0_full_coverage_passes(self) -> None:
        self.assertEqual(evaluate_priority_threshold(100.0, "P0"), "PASS")

    def test_p0_just_under_full_fails(self) -> None:
        self.assertEqual(evaluate_priority_threshold(99.9, "P0"), "FAIL")

    def test_p0_zero_coverage_fails(self) -> None:
        self.assertEqual(evaluate_priority_threshold(0.0, "P0"), "FAIL")

    # P1 band: required 95, floor 90
    def test_p1_at_required_passes(self) -> None:
        self.assertEqual(evaluate_priority_threshold(95.0, "P1"), "PASS")

    def test_p1_above_required_passes(self) -> None:
        self.assertEqual(evaluate_priority_threshold(98.0, "P1"), "PASS")

    def test_p1_between_floor_and_required_is_concerns(self) -> None:
        self.assertEqual(evaluate_priority_threshold(92.0, "P1"), "CONCERNS")

    def test_p1_at_floor_is_concerns(self) -> None:
        self.assertEqual(evaluate_priority_threshold(90.0, "P1"), "CONCERNS")

    def test_p1_below_floor_fails(self) -> None:
        self.assertEqual(evaluate_priority_threshold(89.9, "P1"), "FAIL")

    # P2 band: required 85, floor 80
    def test_p2_at_required_passes(self) -> None:
        self.assertEqual(evaluate_priority_threshold(85.0, "P2"), "PASS")

    def test_p2_above_required_passes(self) -> None:
        self.assertEqual(evaluate_priority_threshold(90.0, "P2"), "PASS")

    def test_p2_between_floor_and_required_is_concerns(self) -> None:
        self.assertEqual(evaluate_priority_threshold(82.0, "P2"), "CONCERNS")

    def test_p2_below_floor_fails(self) -> None:
        self.assertEqual(evaluate_priority_threshold(79.9, "P2"), "FAIL")

    # P3 band: required 70, floor 0 (never FAIL on coverage)
    def test_p3_at_required_passes(self) -> None:
        self.assertEqual(evaluate_priority_threshold(70.0, "P3"), "PASS")

    def test_p3_above_required_passes(self) -> None:
        self.assertEqual(evaluate_priority_threshold(99.0, "P3"), "PASS")

    def test_p3_between_floor_and_required_is_concerns(self) -> None:
        self.assertEqual(evaluate_priority_threshold(50.0, "P3"), "CONCERNS")

    def test_p3_at_zero_floor_is_concerns(self) -> None:
        # Floor 0 means coverage 0 still meets the floor inclusively.
        # Below 70 but at-or-above 0 → CONCERNS.
        self.assertEqual(evaluate_priority_threshold(0.0, "P3"), "CONCERNS")

    def test_unknown_priority_raises(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_priority_threshold(80.0, "P9")


class GateEligibleTests(unittest.TestCase):
    def test_all_required_collected_eligible(self) -> None:
        statuses = {
            "correctness": "COLLECTED",
            "security": "COLLECTED",
            "docs": "COLLECTED",
        }
        required = {"correctness", "security", "docs"}
        ok, reason = gate_eligible(statuses, required)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_missing_required_blocks(self) -> None:
        statuses = {
            "correctness": "COLLECTED",
            "security": "MISSING",
        }
        required = {"correctness", "security"}
        ok, reason = gate_eligible(statuses, required)
        self.assertFalse(ok)
        self.assertIn("security", reason)

    def test_error_status_blocks(self) -> None:
        statuses = {
            "correctness": "COLLECTED",
            "security": "ERROR",
        }
        required = {"correctness", "security"}
        ok, reason = gate_eligible(statuses, required)
        self.assertFalse(ok)
        self.assertIn("security", reason)

    def test_timeout_status_blocks(self) -> None:
        statuses = {
            "correctness": "TIMEOUT",
            "security": "COLLECTED",
        }
        required = {"correctness", "security"}
        ok, reason = gate_eligible(statuses, required)
        self.assertFalse(ok)
        self.assertIn("correctness", reason)

    def test_required_not_present_in_statuses_blocks(self) -> None:
        statuses = {"correctness": "COLLECTED"}
        required = {"correctness", "security"}
        ok, reason = gate_eligible(statuses, required)
        self.assertFalse(ok)
        self.assertIn("security", reason)

    def test_extra_uncollected_categories_ignored_when_not_required(
        self,
    ) -> None:
        statuses = {
            "correctness": "COLLECTED",
            "noise": "ERROR",
        }
        required = {"correctness"}
        ok, reason = gate_eligible(statuses, required)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_empty_required_set_is_eligible(self) -> None:
        ok, reason = gate_eligible({}, set())
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_unknown_status_value_blocks(self) -> None:
        statuses = {"correctness": "MAYBE"}
        required = {"correctness"}
        ok, reason = gate_eligible(statuses, required)
        self.assertFalse(ok)
        self.assertIn("correctness", reason)


if __name__ == "__main__":
    unittest.main()
