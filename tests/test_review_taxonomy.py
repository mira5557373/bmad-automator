from __future__ import annotations

import unittest

from story_automator.core.review_taxonomy import (
    VALID_REVIEW_ACTIONS,
    ReviewActionError,
    canonicalize_action,
    format_review_row,
    parse_review_row,
)


class ValidReviewActionsTests(unittest.TestCase):
    def test_valid_actions_is_frozen_and_complete(self) -> None:
        self.assertIsInstance(VALID_REVIEW_ACTIONS, frozenset)
        self.assertEqual(
            VALID_REVIEW_ACTIONS,
            frozenset({"decision_needed", "patch", "defer", "dismiss"}),
        )

    def test_valid_actions_is_immutable(self) -> None:
        with self.assertRaises(AttributeError):
            VALID_REVIEW_ACTIONS.add("new_action")  # type: ignore[attr-defined]


class CanonicalizeActionTests(unittest.TestCase):
    def test_lowercase_passthrough(self) -> None:
        for action in VALID_REVIEW_ACTIONS:
            self.assertEqual(canonicalize_action(action), action)

    def test_uppercase_is_canonicalized(self) -> None:
        self.assertEqual(canonicalize_action("PATCH"), "patch")
        self.assertEqual(canonicalize_action("Decision_Needed"), "decision_needed")
        self.assertEqual(canonicalize_action("Defer"), "defer")
        self.assertEqual(canonicalize_action("DISMISS"), "dismiss")

    def test_whitespace_is_stripped(self) -> None:
        self.assertEqual(canonicalize_action("  patch  "), "patch")
        self.assertEqual(canonicalize_action("\tdefer\n"), "defer")

    def test_unknown_action_raises(self) -> None:
        with self.assertRaises(ReviewActionError):
            canonicalize_action("approve")
        with self.assertRaises(ReviewActionError):
            canonicalize_action("")

    def test_non_string_raises(self) -> None:
        with self.assertRaises(ReviewActionError):
            canonicalize_action(None)  # type: ignore[arg-type]
        with self.assertRaises(ReviewActionError):
            canonicalize_action(42)  # type: ignore[arg-type]

    def test_review_action_error_is_value_error(self) -> None:
        self.assertTrue(issubclass(ReviewActionError, ValueError))


class FormatReviewRowTests(unittest.TestCase):
    def test_format_full_row(self) -> None:
        row = format_review_row(
            action="patch",
            finding="Missing null check",
            file_ref="src/foo.py",
            line=42,
        )
        self.assertEqual(row, "[Review][patch] src/foo.py:42 Missing null check")

    def test_format_no_line(self) -> None:
        row = format_review_row(
            action="defer",
            finding="Refactor later",
            file_ref="src/bar.py",
        )
        self.assertEqual(row, "[Review][defer] src/bar.py Refactor later")

    def test_format_no_file_ref(self) -> None:
        row = format_review_row(
            action="decision_needed",
            finding="Choose library",
        )
        self.assertEqual(row, "[Review][decision_needed] Choose library")

    def test_format_canonicalizes_action(self) -> None:
        row = format_review_row(
            action="PATCH",
            finding="fix",
            file_ref="a.py",
            line=1,
        )
        self.assertEqual(row, "[Review][patch] a.py:1 fix")

    def test_format_invalid_action_raises(self) -> None:
        with self.assertRaises(ReviewActionError):
            format_review_row(action="approve", finding="x")

    def test_format_empty_finding_raises(self) -> None:
        with self.assertRaises(ValueError):
            format_review_row(action="patch", finding="")
        with self.assertRaises(ValueError):
            format_review_row(action="patch", finding="   ")


class ParseReviewRowTests(unittest.TestCase):
    def test_parse_full_row(self) -> None:
        parsed = parse_review_row("[Review][patch] src/foo.py:42 Missing null check")
        self.assertEqual(
            parsed,
            {
                "action": "patch",
                "file_ref": "src/foo.py",
                "line": 42,
                "finding": "Missing null check",
            },
        )

    def test_parse_no_line(self) -> None:
        parsed = parse_review_row("[Review][defer] src/bar.py Refactor later")
        self.assertEqual(
            parsed,
            {
                "action": "defer",
                "file_ref": "src/bar.py",
                "line": None,
                "finding": "Refactor later",
            },
        )

    def test_parse_no_file(self) -> None:
        parsed = parse_review_row("[Review][decision_needed] Choose library")
        self.assertEqual(
            parsed,
            {
                "action": "decision_needed",
                "file_ref": "",
                "line": None,
                "finding": "Choose library",
            },
        )

    def test_parse_invalid_returns_none(self) -> None:
        self.assertIsNone(parse_review_row("not a review row"))
        self.assertIsNone(parse_review_row(""))
        self.assertIsNone(parse_review_row("[Review] missing action"))
        self.assertIsNone(parse_review_row("[Review][unknown_action] foo"))

    def test_parse_non_string_returns_none(self) -> None:
        self.assertIsNone(parse_review_row(None))  # type: ignore[arg-type]
        self.assertIsNone(parse_review_row(123))  # type: ignore[arg-type]

    def test_roundtrip_full(self) -> None:
        original = format_review_row(
            action="dismiss",
            finding="Not a bug",
            file_ref="src/x.py",
            line=7,
        )
        parsed = parse_review_row(original)
        self.assertIsNotNone(parsed)
        roundtrip = format_review_row(**parsed)  # type: ignore[arg-type]
        self.assertEqual(original, roundtrip)

    def test_roundtrip_no_line(self) -> None:
        original = format_review_row(
            action="defer",
            finding="Later",
            file_ref="src/y.py",
        )
        parsed = parse_review_row(original)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["action"], "defer")
        self.assertEqual(parsed["file_ref"], "src/y.py")
        self.assertIsNone(parsed["line"])
        self.assertEqual(parsed["finding"], "Later")

    def test_roundtrip_no_file(self) -> None:
        original = format_review_row(
            action="decision_needed",
            finding="Pick one",
        )
        parsed = parse_review_row(original)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["action"], "decision_needed")
        self.assertEqual(parsed["file_ref"], "")
        self.assertIsNone(parsed["line"])
        self.assertEqual(parsed["finding"], "Pick one")


if __name__ == "__main__":
    unittest.main()
