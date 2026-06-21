from __future__ import annotations

import unittest

from story_automator.core.integration.bmad_review_bridge import (
    BridgeError,
    VERDICT_TO_ACTION,
    bridge_gate_to_review_rows,
    bridge_remediation_tasks_to_rows,
    finding_to_review_row,
    summarize_bridge_result,
)


def _make_gate(
    *,
    gate_id: str = "gate-001",
    overall: str = "FAIL",
    categories: dict | None = None,
) -> dict:
    cats = categories if categories is not None else {
        "correctness": {
            "verdict": "FAIL",
            "rationale": "unit tests failed",
            "findings": ["test_foo failed at tests/test_foo.py:42"],
        }
    }
    return {
        "gate_id": gate_id,
        "overall": overall,
        "categories": cats,
    }


class VerdictToActionMappingTests(unittest.TestCase):
    def test_mapping_is_complete(self) -> None:
        self.assertIn("FAIL", VERDICT_TO_ACTION)
        self.assertIn("CONCERNS", VERDICT_TO_ACTION)
        self.assertIn("PASS", VERDICT_TO_ACTION)
        self.assertIn("NA", VERDICT_TO_ACTION)
        self.assertIn("WAIVED", VERDICT_TO_ACTION)

    def test_fail_maps_to_patch(self) -> None:
        self.assertEqual(VERDICT_TO_ACTION["FAIL"], "patch")

    def test_concerns_maps_to_decision_needed(self) -> None:
        self.assertEqual(VERDICT_TO_ACTION["CONCERNS"], "decision_needed")

    def test_pass_na_waived_are_dropped(self) -> None:
        for benign in ("PASS", "NA", "WAIVED"):
            self.assertIsNone(VERDICT_TO_ACTION[benign])


class BridgeGateToReviewRowsTests(unittest.TestCase):
    def test_fail_category_emits_patch_row_per_finding(self) -> None:
        gate = _make_gate(
            categories={
                "correctness": {
                    "verdict": "FAIL",
                    "rationale": "unit tests failed",
                    "findings": ["a/b.py:10 bad", "a/c.py:20 worse"],
                }
            }
        )
        rows = bridge_gate_to_review_rows(gate)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row.startswith("[Review][patch]"))

    def test_fail_category_without_findings_emits_decision_needed_from_rationale(self) -> None:
        gate = _make_gate(
            categories={
                "security": {
                    "verdict": "FAIL",
                    "rationale": "secrets detected",
                    "findings": [],
                }
            }
        )
        rows = bridge_gate_to_review_rows(gate)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith("[Review][decision_needed]"))
        self.assertIn("security", rows[0])
        self.assertIn("secrets detected", rows[0])

    def test_concerns_category_emits_decision_needed_per_finding(self) -> None:
        gate = _make_gate(
            overall="CONCERNS",
            categories={
                "docs": {
                    "verdict": "CONCERNS",
                    "rationale": "missing changelog entry",
                    "findings": ["docs/changelog/missing.md"],
                }
            },
        )
        rows = bridge_gate_to_review_rows(gate)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith("[Review][decision_needed]"))

    def test_pass_na_waived_categories_produce_no_rows(self) -> None:
        gate = _make_gate(
            overall="PASS",
            categories={
                "correctness": {"verdict": "PASS", "rationale": "all green"},
                "security": {"verdict": "NA", "rationale": "profile-declared N/A"},
                "license": {"verdict": "WAIVED", "rationale": "operator waiver"},
            },
        )
        rows = bridge_gate_to_review_rows(gate)
        self.assertEqual(rows, [])

    def test_mixed_categories_emit_only_active_rows(self) -> None:
        gate = _make_gate(
            overall="FAIL",
            categories={
                "correctness": {
                    "verdict": "FAIL",
                    "rationale": "broken",
                    "findings": ["x.py:1 broken"],
                },
                "static": {"verdict": "PASS", "rationale": "clean"},
                "docs": {
                    "verdict": "CONCERNS",
                    "rationale": "ambiguous",
                    "findings": ["README.md:5 unclear"],
                },
            },
        )
        rows = bridge_gate_to_review_rows(gate)
        self.assertEqual(len(rows), 2)
        actions = sorted(
            row.split(" ")[0].split("][")[1].rstrip("]")
            for row in rows
        )
        self.assertEqual(actions, ["decision_needed", "patch"])

    def test_findings_must_be_list_of_str_or_dict(self) -> None:
        bad = _make_gate(
            categories={
                "correctness": {
                    "verdict": "FAIL",
                    "rationale": "boom",
                    "findings": [42],  # invalid type
                }
            }
        )
        with self.assertRaises(BridgeError):
            bridge_gate_to_review_rows(bad)

    def test_missing_categories_raises(self) -> None:
        with self.assertRaises(BridgeError):
            bridge_gate_to_review_rows({"gate_id": "g"})

    def test_unknown_verdict_string_raises(self) -> None:
        gate = _make_gate(
            categories={
                "correctness": {
                    "verdict": "MAYBE",
                    "rationale": "unsure",
                }
            }
        )
        with self.assertRaises(BridgeError):
            bridge_gate_to_review_rows(gate)

    def test_invalid_category_payload_raises(self) -> None:
        gate = _make_gate(categories={"correctness": "not-a-dict"})
        with self.assertRaises(BridgeError):
            bridge_gate_to_review_rows(gate)

    def test_overall_pass_with_no_active_categories_returns_empty(self) -> None:
        rows = bridge_gate_to_review_rows({
            "gate_id": "g",
            "overall": "PASS",
            "categories": {},
        })
        self.assertEqual(rows, [])

    def test_structured_finding_dict_extracts_file_and_line(self) -> None:
        gate = _make_gate(
            categories={
                "correctness": {
                    "verdict": "FAIL",
                    "rationale": "test failed",
                    "findings": [
                        {
                            "file": "tests/test_foo.py",
                            "line": 17,
                            "message": "AssertionError: expected 1 == 2",
                        }
                    ],
                }
            }
        )
        rows = bridge_gate_to_review_rows(gate)
        self.assertEqual(len(rows), 1)
        self.assertIn("tests/test_foo.py:17", rows[0])
        self.assertIn("AssertionError", rows[0])

    def test_categories_iterated_in_deterministic_order(self) -> None:
        gate = _make_gate(
            categories={
                "zeta": {"verdict": "FAIL", "rationale": "z", "findings": ["z.py:1 z"]},
                "alpha": {"verdict": "FAIL", "rationale": "a", "findings": ["a.py:1 a"]},
                "mid": {"verdict": "FAIL", "rationale": "m", "findings": ["m.py:1 m"]},
            }
        )
        rows = bridge_gate_to_review_rows(gate)
        self.assertEqual(len(rows), 3)
        # alpha comes before mid before zeta
        self.assertIn("a.py", rows[0])
        self.assertIn("m.py", rows[1])
        self.assertIn("z.py", rows[2])


class FindingToReviewRowTests(unittest.TestCase):
    def test_string_finding_with_file_and_line(self) -> None:
        row = finding_to_review_row(
            action="patch",
            category="correctness",
            finding="src/foo.py:42 NullPointerException",
        )
        self.assertTrue(row.startswith("[Review][patch]"))
        self.assertIn("src/foo.py:42", row)
        self.assertIn("NullPointerException", row)

    def test_string_finding_without_file_line(self) -> None:
        row = finding_to_review_row(
            action="patch",
            category="correctness",
            finding="something failed",
        )
        self.assertTrue(row.startswith("[Review][patch]"))
        self.assertIn("something failed", row)

    def test_dict_finding_with_file_only(self) -> None:
        row = finding_to_review_row(
            action="decision_needed",
            category="docs",
            finding={"file": "README.md", "message": "stale"},
        )
        self.assertTrue(row.startswith("[Review][decision_needed]"))
        self.assertIn("README.md", row)
        self.assertIn("stale", row)

    def test_dict_finding_message_only(self) -> None:
        row = finding_to_review_row(
            action="patch",
            category="security",
            finding={"message": "credentials leaked"},
        )
        self.assertTrue(row.startswith("[Review][patch]"))
        self.assertIn("credentials leaked", row)


class BridgeRemediationTasksTests(unittest.TestCase):
    def test_remediation_tasks_become_decision_needed_rows(self) -> None:
        tasks = [
            {
                "title": "[AI-Review] Fix correctness: tests failed",
                "category": "correctness",
                "gate_id": "gate-001",
                "rationale": "tests failed",
            },
            {
                "title": "[AI-Review] Fix docs: missing changelog",
                "category": "docs",
                "gate_id": "gate-001",
                "rationale": "missing changelog",
            },
        ]
        rows = bridge_remediation_tasks_to_rows(tasks)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertTrue(row.startswith("[Review][decision_needed]"))

    def test_empty_tasks_returns_empty_list(self) -> None:
        self.assertEqual(bridge_remediation_tasks_to_rows([]), [])

    def test_malformed_task_raises(self) -> None:
        with self.assertRaises(BridgeError):
            bridge_remediation_tasks_to_rows([{"no_category": True}])


class SummarizeBridgeResultTests(unittest.TestCase):
    def test_summary_counts_actions(self) -> None:
        rows = [
            "[Review][patch] a.py:1 fix",
            "[Review][patch] b.py:2 fix",
            "[Review][decision_needed] c.py:3 think",
        ]
        summary = summarize_bridge_result(rows)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["patch"], 2)
        self.assertEqual(summary["decision_needed"], 1)

    def test_summary_handles_empty(self) -> None:
        summary = summarize_bridge_result([])
        self.assertEqual(summary["total"], 0)


if __name__ == "__main__":
    unittest.main()
