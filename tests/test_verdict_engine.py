from __future__ import annotations

import unittest

from story_automator.core.gate_schema import (
    make_evidence_record,
    make_llm_evidence_record,
)
from story_automator.core.verdict_engine import (
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


if __name__ == "__main__":
    unittest.main()
