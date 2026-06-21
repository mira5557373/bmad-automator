from __future__ import annotations

import unittest

from story_automator.core.story_keys import (
    EPIC_KEY_RE,
    RETRO_KEY_RE,
    classify_key,
    epic_number,
)


class EpicKeyRegexTests(unittest.TestCase):
    def test_epic_key_re_matches_simple_epic(self) -> None:
        match = EPIC_KEY_RE.fullmatch("epic-1")
        assert match is not None
        self.assertEqual(match.group(1), "1")

    def test_epic_key_re_matches_multi_digit(self) -> None:
        match = EPIC_KEY_RE.fullmatch("epic-42")
        assert match is not None
        self.assertEqual(match.group(1), "42")

    def test_epic_key_re_rejects_retrospective_key(self) -> None:
        self.assertIsNone(EPIC_KEY_RE.fullmatch("epic-1-retrospective"))

    def test_epic_key_re_rejects_non_numeric_epic(self) -> None:
        self.assertIsNone(EPIC_KEY_RE.fullmatch("epic-foo"))

    def test_epic_key_re_rejects_story_key(self) -> None:
        self.assertIsNone(EPIC_KEY_RE.fullmatch("1-2"))


class RetroKeyRegexTests(unittest.TestCase):
    def test_retro_key_re_matches(self) -> None:
        match = RETRO_KEY_RE.fullmatch("epic-3-retrospective")
        assert match is not None
        self.assertEqual(match.group(1), "3")

    def test_retro_key_re_matches_multi_digit(self) -> None:
        match = RETRO_KEY_RE.fullmatch("epic-1234-retrospective")
        assert match is not None
        self.assertEqual(match.group(1), "1234")

    def test_retro_key_re_rejects_plain_epic(self) -> None:
        self.assertIsNone(RETRO_KEY_RE.fullmatch("epic-3"))

    def test_retro_key_re_rejects_wrong_suffix(self) -> None:
        self.assertIsNone(RETRO_KEY_RE.fullmatch("epic-3-retro"))


class ClassifyKeyTests(unittest.TestCase):
    def test_classify_epic(self) -> None:
        self.assertEqual(classify_key("epic-1"), "epic")

    def test_classify_retrospective(self) -> None:
        self.assertEqual(classify_key("epic-1-retrospective"), "retrospective")

    def test_classify_story_dotted(self) -> None:
        self.assertEqual(classify_key("1.2"), "story")

    def test_classify_story_dashed(self) -> None:
        self.assertEqual(classify_key("1-2"), "story")

    def test_classify_story_full_key(self) -> None:
        self.assertEqual(classify_key("1-2-some-slug"), "story")

    def test_classify_unknown_empty(self) -> None:
        self.assertEqual(classify_key(""), "unknown")

    def test_classify_unknown_garbage(self) -> None:
        self.assertEqual(classify_key("not-a-key!"), "unknown")

    def test_classify_unknown_bare_epic_word(self) -> None:
        self.assertEqual(classify_key("epic"), "unknown")

    def test_classify_retrospective_takes_precedence_over_epic(self) -> None:
        # The retrospective pattern is a superstring of epic-N; ensure precedence
        self.assertEqual(classify_key("epic-7-retrospective"), "retrospective")


class EpicNumberTests(unittest.TestCase):
    def test_epic_number_from_epic_key(self) -> None:
        self.assertEqual(epic_number("epic-5"), 5)

    def test_epic_number_from_retrospective_key(self) -> None:
        self.assertEqual(epic_number("epic-5-retrospective"), 5)

    def test_epic_number_multi_digit(self) -> None:
        self.assertEqual(epic_number("epic-123"), 123)

    def test_epic_number_returns_none_for_story(self) -> None:
        self.assertIsNone(epic_number("1.2"))

    def test_epic_number_returns_none_for_unknown(self) -> None:
        self.assertIsNone(epic_number("garbage"))

    def test_epic_number_returns_none_for_bare_epic(self) -> None:
        self.assertIsNone(epic_number("epic"))


if __name__ == "__main__":
    unittest.main()
