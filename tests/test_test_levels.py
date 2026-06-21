from __future__ import annotations

import unittest

from story_automator.core.test_levels import (
    CANONICAL_LEVELS,
    LEVEL_ALIASES,
    TestLevelError,
    bucket_levels,
    canonicalize_level,
    is_canonical,
)


class CanonicalShapeTests(unittest.TestCase):
    def test_canonical_levels_is_exact_tuple(self) -> None:
        self.assertEqual(CANONICAL_LEVELS, ("e2e", "api", "component", "unit"))

    def test_canonical_levels_is_tuple_not_list(self) -> None:
        self.assertIsInstance(CANONICAL_LEVELS, tuple)

    def test_aliases_map_to_canonical_members(self) -> None:
        for alias, target in LEVEL_ALIASES.items():
            self.assertIn(
                target,
                CANONICAL_LEVELS,
                msg=f"alias {alias!r} maps to non-canonical {target!r}",
            )

    def test_aliases_contains_expected_entries(self) -> None:
        expected = {
            "integration": "api",
            "ui": "component",
            "unit-test": "unit",
            "end-to-end": "e2e",
            "func": "api",
            "functional": "api",
        }
        for alias, target in expected.items():
            self.assertEqual(LEVEL_ALIASES[alias], target)


class IsCanonicalTests(unittest.TestCase):
    def test_returns_true_for_every_canonical_level(self) -> None:
        for level in CANONICAL_LEVELS:
            self.assertTrue(is_canonical(level))

    def test_returns_false_for_aliases(self) -> None:
        self.assertFalse(is_canonical("integration"))
        self.assertFalse(is_canonical("ui"))

    def test_returns_false_for_uppercase_canonical(self) -> None:
        # is_canonical is strict — canonicalize first to normalize case.
        self.assertFalse(is_canonical("E2E"))

    def test_returns_false_for_unknown(self) -> None:
        self.assertFalse(is_canonical("smoke"))
        self.assertFalse(is_canonical(""))

    def test_returns_false_for_non_string(self) -> None:
        self.assertFalse(is_canonical(None))
        self.assertFalse(is_canonical(7))


class CanonicalizeLevelTests(unittest.TestCase):
    def test_canonical_input_returns_self(self) -> None:
        for level in CANONICAL_LEVELS:
            self.assertEqual(canonicalize_level(level), level)

    def test_alias_resolves_to_canonical(self) -> None:
        self.assertEqual(canonicalize_level("integration"), "api")
        self.assertEqual(canonicalize_level("ui"), "component")
        self.assertEqual(canonicalize_level("end-to-end"), "e2e")
        self.assertEqual(canonicalize_level("unit-test"), "unit")
        self.assertEqual(canonicalize_level("functional"), "api")
        self.assertEqual(canonicalize_level("func"), "api")

    def test_case_insensitive(self) -> None:
        self.assertEqual(canonicalize_level("E2E"), "e2e")
        self.assertEqual(canonicalize_level("UNIT"), "unit")
        self.assertEqual(canonicalize_level("Integration"), "api")

    def test_strips_whitespace(self) -> None:
        self.assertEqual(canonicalize_level("  unit  "), "unit")
        self.assertEqual(canonicalize_level("\tapi\n"), "api")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(TestLevelError):
            canonicalize_level("smoke")
        with self.assertRaises(TestLevelError):
            canonicalize_level("")

    def test_non_string_raises(self) -> None:
        with self.assertRaises(TestLevelError):
            canonicalize_level(None)
        with self.assertRaises(TestLevelError):
            canonicalize_level(42)
        with self.assertRaises(TestLevelError):
            canonicalize_level(["unit"])

    def test_test_level_error_is_value_error_subclass(self) -> None:
        self.assertTrue(issubclass(TestLevelError, ValueError))


class BucketLevelsTests(unittest.TestCase):
    def test_empty_input_returns_all_empty_buckets(self) -> None:
        result = bucket_levels([])
        self.assertEqual(set(result.keys()), set(CANONICAL_LEVELS))
        for level in CANONICAL_LEVELS:
            self.assertEqual(result[level], [])

    def test_canonical_inputs_grouped_in_order(self) -> None:
        result = bucket_levels(["unit", "e2e", "unit", "api"])
        self.assertEqual(result["unit"], ["unit", "unit"])
        self.assertEqual(result["e2e"], ["e2e"])
        self.assertEqual(result["api"], ["api"])
        self.assertEqual(result["component"], [])

    def test_aliases_are_bucketed_under_canonical_key(self) -> None:
        result = bucket_levels(["integration", "ui", "functional"])
        # Originals preserved inside the bucket; key is canonical.
        self.assertEqual(result["api"], ["integration", "functional"])
        self.assertEqual(result["component"], ["ui"])
        self.assertEqual(result["e2e"], [])
        self.assertEqual(result["unit"], [])

    def test_mixed_case_inputs_bucketed(self) -> None:
        result = bucket_levels(["E2E", "Unit", "INTEGRATION"])
        self.assertEqual(result["e2e"], ["E2E"])
        self.assertEqual(result["unit"], ["Unit"])
        self.assertEqual(result["api"], ["INTEGRATION"])

    def test_unknown_input_raises(self) -> None:
        with self.assertRaises(TestLevelError):
            bucket_levels(["unit", "smoke"])

    def test_non_string_input_raises(self) -> None:
        with self.assertRaises(TestLevelError):
            bucket_levels(["unit", None])

    def test_result_has_all_four_canonical_keys_even_if_some_empty(
        self,
    ) -> None:
        result = bucket_levels(["unit"])
        self.assertEqual(set(result.keys()), set(CANONICAL_LEVELS))


if __name__ == "__main__":
    unittest.main()
