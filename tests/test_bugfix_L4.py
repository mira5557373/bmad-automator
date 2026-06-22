"""Regression test for L4: aggregate_verdicts must fail-closed (§6.3).

Bug: `aggregate_verdicts({})` and `aggregate_verdicts({"a": "NA"})` returned
"PASS" — silently approving a gate where no category was actually evaluated.
Per spec §6.3 fail-closed invariant, an empty active-category set must produce
"FAIL" with rationale "no categories evaluated"; the same rule must mirror in
`compute_all_verdicts`/`adjudicate`.
"""
from __future__ import annotations

import unittest

from story_automator.core.gate_rules import aggregate_verdicts
from story_automator.core.verdict_engine import adjudicate


class AggregateVerdictsFailClosedTests(unittest.TestCase):
    def test_empty_input_returns_fail(self) -> None:
        """Empty category map must fail-closed (no categories evaluated)."""
        self.assertEqual(aggregate_verdicts({}), "FAIL")

    def test_all_na_returns_fail(self) -> None:
        """All-NA category map must fail-closed (no active categories)."""
        self.assertEqual(aggregate_verdicts({"a": "NA", "b": "NA"}), "FAIL")

    def test_mixed_with_one_active_pass_still_passes(self) -> None:
        """Sanity: one PASS plus NAs still aggregates to PASS."""
        self.assertEqual(
            aggregate_verdicts({"a": "PASS", "b": "NA"}),
            "PASS",
        )


class AdjudicateFailClosedTests(unittest.TestCase):
    PROFILE_ALL_NA = {
        "id": "test",
        "version": 1,
        "categories": {"code": [], "system": []},
        "categories_na": ["correctness", "security"],
        "rules": {},
        "invariants": [],
        "matrix": {"P0": [], "P1": [], "P2": [], "P3": []},
    }

    def test_all_na_profile_overall_fails(self) -> None:
        """A profile where every category is NA cannot produce a PASS gate."""
        result = adjudicate([], self.PROFILE_ALL_NA, priority="P1")
        self.assertEqual(result["overall"], "FAIL")


if __name__ == "__main__":
    unittest.main()
