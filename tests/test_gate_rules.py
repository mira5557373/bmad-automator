from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from story_automator.core.gate_rules import (
    WaiverError,
    aggregate_verdicts,
    is_waiver_expired,
    validate_waiver_for_gate,
    verdict_for_collector_status,
)
from story_automator.core.gate_schema import (
    compute_waiver_signature,
    make_waiver,
)


class VerdictForStatusTests(unittest.TestCase):
    def test_ok_maps_to_pass(self) -> None:
        self.assertEqual(verdict_for_collector_status("ok"), "PASS")

    def test_violation_maps_to_fail(self) -> None:
        self.assertEqual(verdict_for_collector_status("violation"), "FAIL")

    def test_error_maps_to_fail(self) -> None:
        self.assertEqual(verdict_for_collector_status("error"), "FAIL")

    def test_timeout_maps_to_fail(self) -> None:
        self.assertEqual(verdict_for_collector_status("timeout"), "FAIL")

    def test_unknown_status_maps_to_fail(self) -> None:
        self.assertEqual(verdict_for_collector_status("bogus"), "FAIL")


class AggregateVerdictsTests(unittest.TestCase):
    def test_all_pass(self) -> None:
        cats = {"correctness": "PASS", "security": "PASS"}
        self.assertEqual(aggregate_verdicts(cats), "PASS")

    def test_any_fail(self) -> None:
        cats = {"correctness": "PASS", "security": "FAIL"}
        self.assertEqual(aggregate_verdicts(cats), "FAIL")

    def test_concerns_without_fail(self) -> None:
        cats = {"correctness": "PASS", "security": "CONCERNS"}
        self.assertEqual(aggregate_verdicts(cats), "CONCERNS")

    def test_na_excluded(self) -> None:
        cats = {"correctness": "PASS", "accessibility": "NA"}
        self.assertEqual(aggregate_verdicts(cats), "PASS")

    def test_unmitigated_risk_9(self) -> None:
        cats = {"correctness": "PASS"}
        self.assertEqual(
            aggregate_verdicts(cats, has_unmitigated_risk_9=True), "FAIL"
        )

    def test_fail_takes_precedence_over_concerns(self) -> None:
        cats = {"a": "CONCERNS", "b": "FAIL", "c": "PASS"}
        self.assertEqual(aggregate_verdicts(cats), "FAIL")

    def test_all_na_is_pass(self) -> None:
        cats = {"a": "NA", "b": "NA"}
        self.assertEqual(aggregate_verdicts(cats), "PASS")


class WaiverExpiryTests(unittest.TestCase):
    def test_unexpired_waiver(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(days=7)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        waiver = {"expires_at": future}
        self.assertFalse(is_waiver_expired(waiver))

    def test_expired_waiver(self) -> None:
        past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        waiver = {"expires_at": past}
        self.assertTrue(is_waiver_expired(waiver))

    def test_exact_expiry_is_expired(self) -> None:
        now = datetime.now(timezone.utc)
        waiver = {"expires_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
        self.assertTrue(is_waiver_expired(waiver, now=now))

    def test_invalid_date_raises(self) -> None:
        with self.assertRaises(WaiverError):
            is_waiver_expired({"expires_at": "not-a-date"})


class ValidateWaiverForGateTests(unittest.TestCase):
    def _make_valid_pair(self) -> tuple[dict, dict]:
        waiver = make_waiver(
            waiver_id="w1",
            operator_id="alice",
            issued_at="2026-06-20T00:00:00Z",
            expires_at="2026-07-01T00:00:00Z",
            failing_categories=["security"],
            reason="false positive",
            profile_hash="aabbccdd",
        )
        gate = {
            "categories": {
                "security": {"verdict": "FAIL"},
                "correctness": {"verdict": "PASS"},
            },
            "profile": {"id": "x", "version": 1, "hash": "aabbccdd"},
        }
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        return waiver, gate, now

    def test_valid_waiver_accepted(self) -> None:
        waiver, gate, now = self._make_valid_pair()
        valid, reason = validate_waiver_for_gate(waiver, gate, now=now)
        self.assertTrue(valid, reason)

    def test_expired_waiver_rejected(self) -> None:
        waiver, gate, _ = self._make_valid_pair()
        future = datetime(2027, 1, 1, tzinfo=timezone.utc)
        valid, reason = validate_waiver_for_gate(waiver, gate, now=future)
        self.assertFalse(valid)
        self.assertIn("expired", reason)

    def test_ttl_exceeded_rejected(self) -> None:
        waiver = make_waiver(
            waiver_id="w2",
            operator_id="alice",
            issued_at="2026-06-01T00:00:00Z",
            expires_at="2026-08-01T00:00:00Z",
            failing_categories=["security"],
            reason="too long",
            profile_hash="aabbccdd",
        )
        gate = {
            "categories": {"security": {"verdict": "FAIL"}},
            "profile": {"hash": "aabbccdd"},
        }
        now = datetime(2026, 6, 15, tzinfo=timezone.utc)
        valid, reason = validate_waiver_for_gate(waiver, gate, now=now)
        self.assertFalse(valid)
        self.assertIn("TTL", reason)

    def test_categories_mismatch_rejected(self) -> None:
        waiver, gate, now = self._make_valid_pair()
        waiver["failing_categories"] = ["correctness"]
        waiver["signature"] = compute_waiver_signature(waiver)
        valid, reason = validate_waiver_for_gate(waiver, gate, now=now)
        self.assertFalse(valid)
        self.assertIn("categories", reason)

    def test_signature_mismatch_rejected(self) -> None:
        waiver, gate, now = self._make_valid_pair()
        waiver["signature"] = "0000000000000000"
        valid, reason = validate_waiver_for_gate(waiver, gate, now=now)
        self.assertFalse(valid)
        self.assertIn("signature", reason)

    def test_profile_hash_mismatch_rejected(self) -> None:
        waiver, gate, now = self._make_valid_pair()
        gate["profile"]["hash"] = "different"
        valid, reason = validate_waiver_for_gate(waiver, gate, now=now)
        self.assertFalse(valid)
        self.assertIn("profile_hash", reason)


if __name__ == "__main__":
    unittest.main()
