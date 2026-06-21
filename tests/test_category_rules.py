from __future__ import annotations

import unittest

from story_automator.core.category_rules import coverage_verdict


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


if __name__ == "__main__":
    unittest.main()
