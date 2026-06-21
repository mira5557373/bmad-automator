"""Tests for VerifyOutcome (Phase 1 typed verifier verdict)."""
from __future__ import annotations

import unittest

from story_automator.core.verify_outcome import VerifyOutcome


class VerifyOutcomeShapeTests(unittest.TestCase):
    def test_passed_factory(self) -> None:
        outcome = VerifyOutcome.passed()
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.reason, "")
        self.assertEqual(outcome.severity, "")
        self.assertFalse(outcome.fixable)
        self.assertFalse(outcome.retryable)

    def test_retry_factory_default(self) -> None:
        outcome = VerifyOutcome.retry("transient")
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "transient")
        self.assertEqual(outcome.severity, "")
        self.assertFalse(outcome.fixable)
        self.assertTrue(outcome.retryable)

    def test_retry_factory_fixable(self) -> None:
        outcome = VerifyOutcome.retry("test_failure", fixable=True)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.fixable)
        self.assertTrue(outcome.retryable)

    def test_escalate_factory_default_critical(self) -> None:
        outcome = VerifyOutcome.escalate("data_loss")
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.severity, "CRITICAL")
        self.assertFalse(outcome.retryable)

    def test_escalate_factory_preference(self) -> None:
        outcome = VerifyOutcome.escalate("style_drift", severity="PREFERENCE")
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.severity, "PREFERENCE")
        self.assertFalse(outcome.retryable)

    def test_frozen_dataclass(self) -> None:
        outcome = VerifyOutcome.passed()
        with self.assertRaises(Exception):
            outcome.ok = False  # type: ignore[misc]


class VerifyOutcomeWireFormatTests(unittest.TestCase):
    def test_to_dict_alpha_keys(self) -> None:
        outcome = VerifyOutcome.retry("baseline_drift", fixable=True)
        d = outcome.to_dict()
        # All four fields present; sorted alphabetically.
        self.assertEqual(list(d.keys()), ["fixable", "ok", "reason", "severity"])
        self.assertEqual(d, {
            "fixable": True, "ok": False,
            "reason": "baseline_drift", "severity": "",
        })

    def test_round_trip(self) -> None:
        original = VerifyOutcome.escalate("git_unavailable", "CRITICAL")
        restored = VerifyOutcome.from_dict(original.to_dict())
        self.assertEqual(restored, original)

    def test_from_dict_tolerant_of_missing_fields(self) -> None:
        # Older gate files may not have all fields.
        outcome = VerifyOutcome.from_dict({"ok": True})
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.reason, "")
        self.assertEqual(outcome.severity, "")
        self.assertFalse(outcome.fixable)

    def test_from_dict_coerces_types(self) -> None:
        outcome = VerifyOutcome.from_dict(
            {"ok": 0, "reason": 123, "severity": "X", "fixable": 1}
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "123")
        self.assertEqual(outcome.severity, "X")
        self.assertTrue(outcome.fixable)


class RetryableSemanticsTests(unittest.TestCase):
    def test_passed_is_not_retryable(self) -> None:
        self.assertFalse(VerifyOutcome.passed().retryable)

    def test_retry_without_severity_is_retryable(self) -> None:
        self.assertTrue(VerifyOutcome.retry("x").retryable)

    def test_failure_with_severity_is_not_retryable(self) -> None:
        self.assertFalse(VerifyOutcome.escalate("x", "CRITICAL").retryable)
        self.assertFalse(VerifyOutcome.escalate("x", "PREFERENCE").retryable)


if __name__ == "__main__":
    unittest.main()
