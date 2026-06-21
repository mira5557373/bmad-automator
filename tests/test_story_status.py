from __future__ import annotations

import unittest

from story_automator.core import story_status
from story_automator.core.story_status import (
    LEGACY_ALIASES,
    LEGAL_TRANSITIONS,
    VALID_STATUSES,
    StoryStatusError,
    canonicalize,
    is_actionable,
    is_terminal,
    is_valid,
    transition,
)


class StoryStatusConstantsTests(unittest.TestCase):
    def test_valid_statuses_set(self) -> None:
        self.assertEqual(
            VALID_STATUSES,
            frozenset({"backlog", "ready-for-dev", "in-progress", "review", "done"}),
        )

    def test_legal_transitions_shape(self) -> None:
        self.assertEqual(LEGAL_TRANSITIONS["backlog"], frozenset({"ready-for-dev"}))
        self.assertEqual(
            LEGAL_TRANSITIONS["ready-for-dev"], frozenset({"in-progress", "backlog"})
        )
        self.assertEqual(
            LEGAL_TRANSITIONS["in-progress"], frozenset({"review", "ready-for-dev"})
        )
        self.assertEqual(
            LEGAL_TRANSITIONS["review"], frozenset({"in-progress", "done"})
        )
        self.assertEqual(LEGAL_TRANSITIONS["done"], frozenset())

    def test_legacy_aliases_map(self) -> None:
        self.assertEqual(LEGACY_ALIASES["drafted"], "ready-for-dev")
        self.assertEqual(LEGACY_ALIASES["contexted"], "in-progress")

    def test_module_exports_error(self) -> None:
        self.assertTrue(issubclass(StoryStatusError, Exception))
        self.assertTrue(hasattr(story_status, "StoryStatusError"))


class CanonicalizeTests(unittest.TestCase):
    def test_canonicalize_valid_passthrough(self) -> None:
        self.assertEqual(canonicalize("backlog"), "backlog")
        self.assertEqual(canonicalize("ready-for-dev"), "ready-for-dev")
        self.assertEqual(canonicalize("in-progress"), "in-progress")
        self.assertEqual(canonicalize("review"), "review")
        self.assertEqual(canonicalize("done"), "done")

    def test_canonicalize_legacy_alias(self) -> None:
        self.assertEqual(canonicalize("drafted"), "ready-for-dev")
        self.assertEqual(canonicalize("contexted"), "in-progress")

    def test_canonicalize_strip_and_lower(self) -> None:
        self.assertEqual(canonicalize("  Drafted  "), "ready-for-dev")
        self.assertEqual(canonicalize("REVIEW"), "review")

    def test_canonicalize_unknown_raises(self) -> None:
        with self.assertRaises(StoryStatusError):
            canonicalize("nope")

    def test_canonicalize_non_string_raises(self) -> None:
        with self.assertRaises(StoryStatusError):
            canonicalize(None)  # type: ignore[arg-type]

    def test_canonicalize_empty_raises(self) -> None:
        with self.assertRaises(StoryStatusError):
            canonicalize("")


class IsValidTests(unittest.TestCase):
    def test_is_valid_true_for_each_status(self) -> None:
        for status in VALID_STATUSES:
            self.assertTrue(is_valid(status))

    def test_is_valid_false_for_alias_raw(self) -> None:
        # aliases are NOT directly valid (must be canonicalized first)
        self.assertFalse(is_valid("drafted"))
        self.assertFalse(is_valid("contexted"))

    def test_is_valid_false_for_unknown(self) -> None:
        self.assertFalse(is_valid("nope"))
        self.assertFalse(is_valid(""))


class TransitionTests(unittest.TestCase):
    def test_each_legal_transition(self) -> None:
        legal_pairs = [
            ("backlog", "ready-for-dev"),
            ("ready-for-dev", "in-progress"),
            ("ready-for-dev", "backlog"),
            ("in-progress", "review"),
            ("in-progress", "ready-for-dev"),
            ("review", "in-progress"),
            ("review", "done"),
        ]
        for src, dst in legal_pairs:
            self.assertEqual(transition(src, dst), dst, msg=f"{src}->{dst}")

    def test_illegal_transition_raises(self) -> None:
        illegal_pairs = [
            ("backlog", "in-progress"),
            ("backlog", "review"),
            ("backlog", "done"),
            ("ready-for-dev", "review"),
            ("ready-for-dev", "done"),
            ("in-progress", "backlog"),
            ("in-progress", "done"),
            ("review", "backlog"),
            ("review", "ready-for-dev"),
            ("done", "backlog"),
            ("done", "ready-for-dev"),
            ("done", "in-progress"),
            ("done", "review"),
            ("done", "done"),
            ("backlog", "backlog"),
        ]
        for src, dst in illegal_pairs:
            with self.assertRaises(StoryStatusError, msg=f"{src}->{dst}"):
                transition(src, dst)

    def test_transition_canonicalizes_alias_inputs(self) -> None:
        # drafted -> ready-for-dev; transition to in-progress should be legal
        self.assertEqual(transition("drafted", "contexted"), "in-progress")
        self.assertEqual(transition("contexted", "review"), "review")

    def test_transition_unknown_status_raises(self) -> None:
        with self.assertRaises(StoryStatusError):
            transition("backlog", "garbage")
        with self.assertRaises(StoryStatusError):
            transition("garbage", "backlog")


class IsTerminalTests(unittest.TestCase):
    def test_done_is_terminal(self) -> None:
        self.assertTrue(is_terminal("done"))

    def test_non_done_not_terminal(self) -> None:
        for status in ("backlog", "ready-for-dev", "in-progress", "review"):
            self.assertFalse(is_terminal(status))

    def test_is_terminal_canonicalizes(self) -> None:
        self.assertFalse(is_terminal("drafted"))
        self.assertFalse(is_terminal("contexted"))

    def test_is_terminal_unknown_raises(self) -> None:
        with self.assertRaises(StoryStatusError):
            is_terminal("nope")


class IsActionableTests(unittest.TestCase):
    def test_actionable_set(self) -> None:
        self.assertTrue(is_actionable("backlog"))
        self.assertTrue(is_actionable("ready-for-dev"))

    def test_non_actionable_set(self) -> None:
        self.assertFalse(is_actionable("in-progress"))
        self.assertFalse(is_actionable("review"))
        self.assertFalse(is_actionable("done"))

    def test_actionable_canonicalizes(self) -> None:
        self.assertTrue(is_actionable("drafted"))
        self.assertFalse(is_actionable("contexted"))

    def test_actionable_unknown_raises(self) -> None:
        with self.assertRaises(StoryStatusError):
            is_actionable("nope")


if __name__ == "__main__":
    unittest.main()
