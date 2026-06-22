from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from story_automator.core.gate_rules import (
    WaiverError,
    aggregate_verdicts,
    is_waiver_expired,
    validate_waiver_for_gate,
    verdict_for_collector_status,
    verdict_for_cost_tier,
    verdict_for_invariant_severity,
    verdict_for_llm_confidence,
    verdict_na,
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

    def test_all_na_is_fail_closed(self) -> None:
        # §6.3 fail-closed: if every category is NA there is nothing to
        # adjudicate; never silently return PASS.
        cats = {"a": "NA", "b": "NA"}
        self.assertEqual(aggregate_verdicts(cats), "FAIL")

    def test_empty_input_is_fail_closed(self) -> None:
        # §6.3 fail-closed: empty input must never resolve to PASS.
        self.assertEqual(aggregate_verdicts({}), "FAIL")


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


class LlmConfidenceVerdictTests(unittest.TestCase):
    def test_high_confidence_passes(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(8), "PASS")

    def test_low_confidence_concerns(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(3), "CONCERNS")

    def test_boundary_5_passes(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(5), "PASS")

    def test_boundary_4_concerns(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(4), "CONCERNS")

    def test_minimum_1_concerns(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(1), "CONCERNS")

    def test_maximum_10_passes(self) -> None:
        self.assertEqual(verdict_for_llm_confidence(10), "PASS")


class InvariantSeverityVerdictTests(unittest.TestCase):
    def test_no_violation_passes(self) -> None:
        self.assertEqual(
            verdict_for_invariant_severity("FAIL", has_violation=False), "PASS"
        )

    def test_fail_severity_with_violation_is_hard_fail(self) -> None:
        self.assertEqual(
            verdict_for_invariant_severity("FAIL", has_violation=True), "FAIL"
        )

    def test_concerns_severity_with_violation(self) -> None:
        self.assertEqual(
            verdict_for_invariant_severity("CONCERNS", has_violation=True),
            "CONCERNS",
        )

    def test_concerns_severity_no_violation(self) -> None:
        self.assertEqual(
            verdict_for_invariant_severity("CONCERNS", has_violation=False),
            "PASS",
        )


class CostTierVerdictTests(unittest.TestCase):
    def test_dg2_in_forbidden_until_is_concerns(self) -> None:
        self.assertEqual(
            verdict_for_cost_tier(
                {"sku_id": "msme-starter"},
                {"DG-2": ["*.cost-to-serve"]},
            ),
            "CONCERNS",
        )

    def test_no_cost_tier_is_concerns(self) -> None:
        self.assertEqual(verdict_for_cost_tier(None, None), "CONCERNS")

    def test_empty_sku_id_is_concerns(self) -> None:
        self.assertEqual(
            verdict_for_cost_tier({"sku_id": ""}, None), "CONCERNS"
        )

    def test_valid_cost_tier_no_blocker_passes(self) -> None:
        self.assertEqual(
            verdict_for_cost_tier({"sku_id": "msme-pro"}, {}), "PASS"
        )

    def test_dg2_not_in_forbidden_with_valid_tier_passes(self) -> None:
        self.assertEqual(
            verdict_for_cost_tier(
                {"sku_id": "msme-pro"},
                {"DG-3": ["E*.ca-channel-*"]},
            ),
            "PASS",
        )


class VerdictNaTests(unittest.TestCase):
    def test_default_rationale(self) -> None:
        result = verdict_na()
        self.assertEqual(result["verdict"], "NA")
        self.assertEqual(result["rationale"], "profile-declared N/A")

    def test_custom_rationale(self) -> None:
        result = verdict_na("CLI tool — no UI")
        self.assertEqual(result["rationale"], "CLI tool — no UI")


if __name__ == "__main__":
    unittest.main()
