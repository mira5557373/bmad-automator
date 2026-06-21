from __future__ import annotations

import unittest

from story_automator.core.coverage_status import (
    VALID_COVERAGE_STATUSES,
    CoverageStatusError,
    classify_coverage,
    is_blocking_priority_p0,
    is_passing_priority_p1,
)


class ValidCoverageStatusesTests(unittest.TestCase):
    def test_valid_statuses_is_frozen_and_complete(self) -> None:
        self.assertIsInstance(VALID_COVERAGE_STATUSES, frozenset)
        self.assertEqual(
            VALID_COVERAGE_STATUSES,
            frozenset(
                {
                    "FULL",
                    "PARTIAL",
                    "UNIT-ONLY",
                    "INTEGRATION-ONLY",
                    "NONE",
                }
            ),
        )

    def test_valid_statuses_is_immutable(self) -> None:
        with self.assertRaises(AttributeError):
            VALID_COVERAGE_STATUSES.add("OTHER")  # type: ignore[attr-defined]

    def test_coverage_status_error_is_value_error(self) -> None:
        self.assertTrue(issubclass(CoverageStatusError, ValueError))


class ClassifyCoverageTests(unittest.TestCase):
    def test_no_tests_classifies_as_none(self) -> None:
        self.assertEqual(
            classify_coverage(
                has_unit=False, has_integration=False, has_e2e=False
            ),
            "NONE",
        )

    def test_unit_only(self) -> None:
        self.assertEqual(
            classify_coverage(
                has_unit=True, has_integration=False, has_e2e=False
            ),
            "UNIT-ONLY",
        )

    def test_integration_only(self) -> None:
        self.assertEqual(
            classify_coverage(
                has_unit=False, has_integration=True, has_e2e=False
            ),
            "INTEGRATION-ONLY",
        )

    def test_e2e_only_maps_to_integration_only(self) -> None:
        self.assertEqual(
            classify_coverage(
                has_unit=False, has_integration=False, has_e2e=True
            ),
            "INTEGRATION-ONLY",
        )

    def test_unit_plus_integration_is_partial(self) -> None:
        self.assertEqual(
            classify_coverage(
                has_unit=True, has_integration=True, has_e2e=False
            ),
            "PARTIAL",
        )

    def test_unit_plus_e2e_is_partial(self) -> None:
        self.assertEqual(
            classify_coverage(
                has_unit=True, has_integration=False, has_e2e=True
            ),
            "PARTIAL",
        )

    def test_all_three_layers_is_full(self) -> None:
        self.assertEqual(
            classify_coverage(
                has_unit=True, has_integration=True, has_e2e=True
            ),
            "FULL",
        )

    def test_kwargs_required(self) -> None:
        with self.assertRaises(TypeError):
            classify_coverage(True, False, False)  # type: ignore[misc]

    def test_returns_member_of_valid_statuses(self) -> None:
        for has_unit in (False, True):
            for has_integration in (False, True):
                for has_e2e in (False, True):
                    result = classify_coverage(
                        has_unit=has_unit,
                        has_integration=has_integration,
                        has_e2e=has_e2e,
                    )
                    self.assertIn(result, VALID_COVERAGE_STATUSES)

    def test_non_bool_inputs_rejected(self) -> None:
        with self.assertRaises(CoverageStatusError):
            classify_coverage(
                has_unit=1,  # type: ignore[arg-type]
                has_integration=False,
                has_e2e=False,
            )
        with self.assertRaises(CoverageStatusError):
            classify_coverage(
                has_unit=False,
                has_integration="yes",  # type: ignore[arg-type]
                has_e2e=False,
            )
        with self.assertRaises(CoverageStatusError):
            classify_coverage(
                has_unit=False,
                has_integration=False,
                has_e2e=None,  # type: ignore[arg-type]
            )


class IsBlockingPriorityP0Tests(unittest.TestCase):
    def test_only_full_passes_p0(self) -> None:
        self.assertTrue(is_blocking_priority_p0("FULL"))

    def test_partial_blocks_p0(self) -> None:
        self.assertFalse(is_blocking_priority_p0("PARTIAL"))

    def test_unit_only_blocks_p0(self) -> None:
        self.assertFalse(is_blocking_priority_p0("UNIT-ONLY"))

    def test_integration_only_blocks_p0(self) -> None:
        self.assertFalse(is_blocking_priority_p0("INTEGRATION-ONLY"))

    def test_none_blocks_p0(self) -> None:
        self.assertFalse(is_blocking_priority_p0("NONE"))

    def test_unknown_status_raises(self) -> None:
        with self.assertRaises(CoverageStatusError):
            is_blocking_priority_p0("OTHER")
        with self.assertRaises(CoverageStatusError):
            is_blocking_priority_p0("full")
        with self.assertRaises(CoverageStatusError):
            is_blocking_priority_p0("")

    def test_non_string_raises(self) -> None:
        with self.assertRaises(CoverageStatusError):
            is_blocking_priority_p0(None)  # type: ignore[arg-type]
        with self.assertRaises(CoverageStatusError):
            is_blocking_priority_p0(1)  # type: ignore[arg-type]


class IsPassingPriorityP1Tests(unittest.TestCase):
    def test_full_passes_p1(self) -> None:
        self.assertTrue(is_passing_priority_p1("FULL"))

    def test_partial_passes_p1(self) -> None:
        self.assertTrue(is_passing_priority_p1("PARTIAL"))

    def test_unit_only_blocks_p1(self) -> None:
        self.assertFalse(is_passing_priority_p1("UNIT-ONLY"))

    def test_integration_only_blocks_p1(self) -> None:
        self.assertFalse(is_passing_priority_p1("INTEGRATION-ONLY"))

    def test_none_blocks_p1(self) -> None:
        self.assertFalse(is_passing_priority_p1("NONE"))

    def test_unknown_status_raises(self) -> None:
        with self.assertRaises(CoverageStatusError):
            is_passing_priority_p1("OTHER")
        with self.assertRaises(CoverageStatusError):
            is_passing_priority_p1("partial")
        with self.assertRaises(CoverageStatusError):
            is_passing_priority_p1("")

    def test_non_string_raises(self) -> None:
        with self.assertRaises(CoverageStatusError):
            is_passing_priority_p1(None)  # type: ignore[arg-type]
        with self.assertRaises(CoverageStatusError):
            is_passing_priority_p1(0)  # type: ignore[arg-type]


class CrossFunctionConsistencyTests(unittest.TestCase):
    def test_p0_implies_p1(self) -> None:
        for status in VALID_COVERAGE_STATUSES:
            if is_blocking_priority_p0(status):
                self.assertTrue(
                    is_passing_priority_p1(status),
                    msg=f"P0-passing {status} must also pass P1",
                )

    def test_classify_then_priority_check_round_trip(self) -> None:
        full_status = classify_coverage(
            has_unit=True, has_integration=True, has_e2e=True
        )
        self.assertTrue(is_blocking_priority_p0(full_status))
        self.assertTrue(is_passing_priority_p1(full_status))

        partial_status = classify_coverage(
            has_unit=True, has_integration=True, has_e2e=False
        )
        self.assertFalse(is_blocking_priority_p0(partial_status))
        self.assertTrue(is_passing_priority_p1(partial_status))

        none_status = classify_coverage(
            has_unit=False, has_integration=False, has_e2e=False
        )
        self.assertFalse(is_blocking_priority_p0(none_status))
        self.assertFalse(is_passing_priority_p1(none_status))


if __name__ == "__main__":
    unittest.main()
