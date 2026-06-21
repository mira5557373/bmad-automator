"""Tests for the 29-criterion TEA ADR rubric in core/checks/adr_check.py.

These tests pin the M51 contract:

* ``ADR_CRITERIA`` is a tuple of exactly 29 unique, non-empty strings.
* ``evaluate_adr_criteria`` returns one verdict per criterion in declared
  order, mapping a markdown ADR body to a closed verdict vocabulary.
* ``missing_criteria`` only surfaces criteria the rubric considers required
  and missing.
* ``criterion_for`` is a stable lookup by exact criterion string.
* The existing ``Production-Readiness`` heading sub-check still passes.
"""

from __future__ import annotations

import unittest

from story_automator.core.checks.adr_check import (  # type: ignore[import-not-found]
    ADR_CRITERIA,
    AdrCriterionError,
    CRITERION_VERDICTS,
    criterion_for,
    evaluate_adr_criteria,
    has_production_readiness_section,
    missing_criteria,
)


class AdrCriteriaShapeTests(unittest.TestCase):
    def test_tuple_has_exactly_29_entries(self) -> None:
        self.assertIsInstance(ADR_CRITERIA, tuple)
        self.assertEqual(len(ADR_CRITERIA), 29)

    def test_entries_are_unique_non_empty_strings(self) -> None:
        seen: set[str] = set()
        for entry in ADR_CRITERIA:
            self.assertIsInstance(entry, str)
            self.assertTrue(entry.strip(), "criterion must be non-empty")
            self.assertNotIn(entry, seen, "criteria must be unique")
            seen.add(entry)

    def test_verdict_vocabulary_is_closed_three_member_tuple(self) -> None:
        self.assertEqual(
            CRITERION_VERDICTS,
            ("PASS", "FAIL", "NOT_APPLICABLE"),
        )


class CriterionLookupTests(unittest.TestCase):
    def test_criterion_for_returns_known_string(self) -> None:
        first = ADR_CRITERIA[0]
        self.assertEqual(criterion_for(first), first)

    def test_criterion_for_unknown_raises(self) -> None:
        with self.assertRaises(AdrCriterionError):
            criterion_for("not-a-real-criterion")

    def test_criterion_for_rejects_non_string(self) -> None:
        with self.assertRaises(AdrCriterionError):
            criterion_for(123)  # type: ignore[arg-type]


class EvaluateAdrCriteriaTests(unittest.TestCase):
    def test_returns_one_verdict_per_criterion_in_declared_order(self) -> None:
        body = "# ADR-0001\n\n## Context\n\nSome body.\n"
        verdicts = evaluate_adr_criteria(body)
        self.assertEqual(len(verdicts), 29)
        # First element corresponds to the first criterion.
        self.assertEqual(verdicts[0][0], ADR_CRITERIA[0])
        for _, verdict in verdicts:
            self.assertIn(verdict, CRITERION_VERDICTS)

    def test_empty_body_fails_every_required_criterion(self) -> None:
        verdicts = evaluate_adr_criteria("")
        statuses = {c: v for c, v in verdicts}
        # All 29 criteria should be in the result.
        self.assertEqual(set(statuses), set(ADR_CRITERIA))
        # On an empty body, no required criterion can PASS.
        self.assertNotIn("PASS", statuses.values())

    def test_full_body_passes_a_subset_of_criteria(self) -> None:
        body = (
            "# ADR-0001 Switch storage backend\n\n"
            "## Context\n\nWhy we need this.\n\n"
            "## Decision\n\nWe will adopt X.\n\n"
            "## Alternatives Considered\n\n- Option A\n- Option B\n\n"
            "## Consequences\n\nTradeoffs.\n\n"
            "## Production-Readiness\n\nReady.\n\n"
            "## Rollback Plan\n\nRevert to Y.\n\n"
            "## Security Review\n\nNo new attack surface.\n"
        )
        verdicts = dict(evaluate_adr_criteria(body))
        passed = [k for k, v in verdicts.items() if v == "PASS"]
        self.assertGreater(len(passed), 0)


class MissingCriteriaTests(unittest.TestCase):
    def test_empty_body_lists_all_required_criteria(self) -> None:
        missing = missing_criteria("")
        # At least one criterion is required and missing.
        self.assertGreater(len(missing), 0)
        # Every entry must be a valid criterion.
        for entry in missing:
            self.assertIn(entry, ADR_CRITERIA)

    def test_body_with_all_sections_has_no_missing(self) -> None:
        # Synthesize a body that contains every criterion keyword verbatim.
        body_lines = ["# ADR-0042 Full coverage\n"]
        for entry in ADR_CRITERIA:
            body_lines.append(f"## {entry}\n\nSatisfied.\n")
        body = "\n".join(body_lines)
        self.assertEqual(missing_criteria(body), ())

    def test_partial_body_returns_only_missing_criteria(self) -> None:
        # Only emit the first half of criteria as headings.
        half = len(ADR_CRITERIA) // 2
        body = "\n".join(f"## {c}" for c in ADR_CRITERIA[:half])
        missing = missing_criteria(body)
        # The emitted half must not appear in missing.
        for entry in ADR_CRITERIA[:half]:
            self.assertNotIn(entry, missing)


class ProductionReadinessCompatTests(unittest.TestCase):
    def test_production_readiness_helper_still_detects_section(self) -> None:
        self.assertTrue(
            has_production_readiness_section(
                "## Production-Readiness\n\nReady.\n"
            )
        )
        self.assertTrue(
            has_production_readiness_section(
                "## Production Readiness\n\nReady.\n"
            )
        )
        self.assertFalse(has_production_readiness_section("# ADR-0001\n"))


if __name__ == "__main__":
    unittest.main()
