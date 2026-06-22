"""Tests for core/action_enum.py — Path B M5 verifier action vocabulary.

The Action Literal type is a purely additive type hint surface; no runtime
behavior of the gate orchestrator changes. These tests pin the vocabulary
and the canonicalize helper that call sites can use to normalise free-form
input before comparing against the Literal.
"""
from __future__ import annotations

import unittest

from story_automator.core.action_enum import (
    VALID_ACTIONS,
    ActionError,
    canonicalize_action,
    is_valid_action,
)


class ValidActionsConstantTests(unittest.TestCase):
    """Pin the vocabulary itself — five actions, frozen, deterministic order."""

    def test_vocabulary_contents(self) -> None:
        self.assertEqual(
            VALID_ACTIONS,
            ("done", "remediate", "park", "defer", "escalate"),
        )

    def test_vocabulary_is_a_tuple(self) -> None:
        # tuples are immutable — protects against accidental .append elsewhere.
        self.assertIsInstance(VALID_ACTIONS, tuple)

    def test_vocabulary_cannot_be_mutated(self) -> None:
        with self.assertRaises((TypeError, AttributeError)):
            VALID_ACTIONS[0] = "mutated"  # type: ignore[index]
        # And tuples have no .append/.extend, so even hasattr is False.
        self.assertFalse(hasattr(VALID_ACTIONS, "append"))


class IsValidActionTests(unittest.TestCase):
    def test_every_vocabulary_member_is_valid(self) -> None:
        for action in VALID_ACTIONS:
            with self.subTest(action=action):
                self.assertTrue(is_valid_action(action))

    def test_unknown_action_is_invalid(self) -> None:
        self.assertFalse(is_valid_action("commit"))
        self.assertFalse(is_valid_action("reopen"))
        self.assertFalse(is_valid_action(""))

    def test_case_sensitive_by_design(self) -> None:
        # is_valid_action is strict — case normalisation is canonicalize's job.
        self.assertFalse(is_valid_action("DONE"))
        self.assertFalse(is_valid_action("Park"))


class CanonicalizeActionTests(unittest.TestCase):
    def test_lowercase_passthrough(self) -> None:
        for action in VALID_ACTIONS:
            with self.subTest(action=action):
                self.assertEqual(canonicalize_action(action), action)

    def test_uppercase_is_normalised(self) -> None:
        self.assertEqual(canonicalize_action("DONE"), "done")
        self.assertEqual(canonicalize_action("REMEDIATE"), "remediate")

    def test_mixed_case_is_normalised(self) -> None:
        self.assertEqual(canonicalize_action("Park"), "park")
        self.assertEqual(canonicalize_action("eScAlAtE"), "escalate")

    def test_whitespace_is_stripped(self) -> None:
        self.assertEqual(canonicalize_action("  done  "), "done")
        self.assertEqual(canonicalize_action("\tdefer\n"), "defer")

    def test_bytes_input_is_decoded(self) -> None:
        self.assertEqual(canonicalize_action(b"done"), "done")
        self.assertEqual(canonicalize_action(b"  PARK\n"), "park")

    def test_unknown_raises_action_error(self) -> None:
        with self.assertRaises(ActionError):
            canonicalize_action("commit")
        with self.assertRaises(ActionError):
            canonicalize_action("reopen")
        with self.assertRaises(ActionError):
            canonicalize_action("")

    def test_action_error_is_value_error_subclass(self) -> None:
        # Lets existing `except ValueError:` call sites still work.
        self.assertTrue(issubclass(ActionError, ValueError))

    def test_error_message_lists_valid_actions(self) -> None:
        try:
            canonicalize_action("bogus")
        except ActionError as exc:
            msg = str(exc)
            for action in VALID_ACTIONS:
                self.assertIn(action, msg)
        else:  # pragma: no cover — assertRaises above guarantees this
            self.fail("ActionError not raised")

    def test_non_string_non_bytes_rejected(self) -> None:
        with self.assertRaises(ActionError):
            canonicalize_action(42)  # type: ignore[arg-type]
        with self.assertRaises(ActionError):
            canonicalize_action(None)  # type: ignore[arg-type]


class ActionLiteralImportTests(unittest.TestCase):
    """The Action alias must be importable as a typing construct."""

    def test_action_alias_is_importable(self) -> None:
        from story_automator.core.action_enum import Action  # noqa: F401

    def test_action_alias_matches_valid_actions(self) -> None:
        # typing.get_args on a Literal returns the literal members.
        from typing import get_args
        from story_automator.core.action_enum import Action
        self.assertEqual(set(get_args(Action)), set(VALID_ACTIONS))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
