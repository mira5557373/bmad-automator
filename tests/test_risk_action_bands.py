"""Tests for the TEA risk-action ladder (M37).

Maps an integer risk score (1-9) to a discrete action band that drives the
remediation policy:

    1-3 -> DOCUMENT  (low; record context only)
    4-5 -> MONITOR   (watch in subsequent reviews)
    6-8 -> MITIGATE  (require a concrete plan before merge)
    9   -> BLOCK     (hard-blocks release until reduced)

Out-of-range scores fail closed via ``RiskProfileError``. Only ``BLOCK``
returns ``True`` from ``action_blocks_release`` — the other three bands are
advisory and never gate the release on their own.
"""

from __future__ import annotations

import unittest

from story_automator.core.risk_profile import (
    ACTION_BANDS,
    RiskProfileError,
    action_blocks_release,
    risk_score_to_action,
)


class ActionBandsConstantTests(unittest.TestCase):
    def test_action_bands_is_a_tuple(self) -> None:
        self.assertIsInstance(ACTION_BANDS, tuple)

    def test_action_bands_exact_membership_and_order(self) -> None:
        self.assertEqual(
            ACTION_BANDS, ("DOCUMENT", "MONITOR", "MITIGATE", "BLOCK")
        )

    def test_action_bands_strings_are_uppercase_ascii(self) -> None:
        for band in ACTION_BANDS:
            self.assertIsInstance(band, str)
            self.assertTrue(band.isascii())
            self.assertEqual(band, band.upper())


class RiskScoreToActionTests(unittest.TestCase):
    def test_document_band_covers_one_through_three(self) -> None:
        for score in (1, 2, 3):
            with self.subTest(score=score):
                self.assertEqual(risk_score_to_action(score), "DOCUMENT")

    def test_monitor_band_covers_four_and_five(self) -> None:
        for score in (4, 5):
            with self.subTest(score=score):
                self.assertEqual(risk_score_to_action(score), "MONITOR")

    def test_mitigate_band_covers_six_through_eight(self) -> None:
        for score in (6, 7, 8):
            with self.subTest(score=score):
                self.assertEqual(risk_score_to_action(score), "MITIGATE")

    def test_block_band_covers_nine_only(self) -> None:
        self.assertEqual(risk_score_to_action(9), "BLOCK")

    def test_full_range_returns_only_known_action_bands(self) -> None:
        for score in range(1, 10):
            with self.subTest(score=score):
                self.assertIn(risk_score_to_action(score), ACTION_BANDS)

    def test_out_of_range_below_one_raises(self) -> None:
        for score in (0, -1, -100):
            with self.subTest(score=score):
                with self.assertRaises(RiskProfileError):
                    risk_score_to_action(score)

    def test_out_of_range_above_nine_raises(self) -> None:
        for score in (10, 11, 100):
            with self.subTest(score=score):
                with self.assertRaises(RiskProfileError):
                    risk_score_to_action(score)

    def test_non_integer_score_raises(self) -> None:
        for score in (None, "5", 5.5, [5], object()):
            with self.subTest(score=score):
                with self.assertRaises(RiskProfileError):
                    risk_score_to_action(score)  # type: ignore[arg-type]

    def test_bool_is_rejected_as_non_integer(self) -> None:
        # bools are an int subclass in Python; reject explicitly so True/False
        # never silently maps to a band.
        for score in (True, False):
            with self.subTest(score=score):
                with self.assertRaises(RiskProfileError):
                    risk_score_to_action(score)  # type: ignore[arg-type]


class ActionBlocksReleaseTests(unittest.TestCase):
    def test_only_block_band_blocks_release(self) -> None:
        self.assertTrue(action_blocks_release("BLOCK"))

    def test_non_block_bands_do_not_block_release(self) -> None:
        for band in ("DOCUMENT", "MONITOR", "MITIGATE"):
            with self.subTest(band=band):
                self.assertFalse(action_blocks_release(band))

    def test_unknown_band_raises(self) -> None:
        for band in ("block", "Block", "", "ESCALATE", "warn", "OK"):
            with self.subTest(band=band):
                with self.assertRaises(RiskProfileError):
                    action_blocks_release(band)

    def test_non_string_input_raises(self) -> None:
        for band in (None, 9, 0, True, ["BLOCK"], {"BLOCK"}):
            with self.subTest(band=band):
                with self.assertRaises(RiskProfileError):
                    action_blocks_release(band)  # type: ignore[arg-type]

    def test_every_action_band_is_classified(self) -> None:
        # Every band returned by the ladder must be answerable by
        # action_blocks_release without raising — sanity-check the closed set.
        blocking = [b for b in ACTION_BANDS if action_blocks_release(b)]
        self.assertEqual(blocking, ["BLOCK"])


class RiskProfileErrorTests(unittest.TestCase):
    def test_risk_profile_error_is_an_exception(self) -> None:
        self.assertTrue(issubclass(RiskProfileError, Exception))


if __name__ == "__main__":
    unittest.main()
