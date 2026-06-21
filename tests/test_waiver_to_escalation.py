from __future__ import annotations

import unittest

from story_automator.core.integration.waiver_to_escalation import (
    PREFERENCE,
    CRITICAL,
    WaiverEscalationError,
    escalation_to_waiver,
    is_waiver_equivalent,
    round_trip_waiver,
    waiver_to_escalation,
)


# Minimal Waiver shape — keyword-only mapping, matches the M02 gate_schema
# Waiver vocabulary (category, reason, granted_by, expires_at, scope).
def _waiver(
    *,
    category: str = "static",
    reason: str = "false-positive in vendored deps",
    granted_by: str = "operator@example",
    expires_at: str = "2026-12-31T23:59:59Z",
    scope: str = "story:S-001",
) -> dict:
    return {
        "category": category,
        "reason": reason,
        "granted_by": granted_by,
        "expires_at": expires_at,
        "scope": scope,
    }


def _escalation(
    *,
    severity: str = PREFERENCE,
    category: str = "static",
    reason: str = "false-positive in vendored deps",
    actor: str = "operator@example",
    expires_at: str = "2026-12-31T23:59:59Z",
    scope: str = "story:S-001",
) -> dict:
    return {
        "api_version": 1,
        "kind": "escalation",
        "severity": severity,
        "category": category,
        "reason": reason,
        "actor": actor,
        "expires_at": expires_at,
        "scope": scope,
    }


class WaiverToEscalationForwardTests(unittest.TestCase):
    def test_waiver_translates_to_preference_escalation(self) -> None:
        esc = waiver_to_escalation(_waiver())
        self.assertEqual(esc["severity"], PREFERENCE)
        self.assertEqual(esc["kind"], "escalation")
        self.assertEqual(esc["api_version"], 1)
        self.assertEqual(esc["category"], "static")
        self.assertEqual(esc["reason"], "false-positive in vendored deps")
        self.assertEqual(esc["actor"], "operator@example")
        self.assertEqual(esc["expires_at"], "2026-12-31T23:59:59Z")
        self.assertEqual(esc["scope"], "story:S-001")

    def test_missing_required_field_raises(self) -> None:
        bad = _waiver()
        del bad["category"]
        with self.assertRaises(WaiverEscalationError):
            waiver_to_escalation(bad)

    def test_empty_string_field_rejected(self) -> None:
        bad = _waiver(reason="")
        with self.assertRaises(WaiverEscalationError):
            waiver_to_escalation(bad)


class EscalationToWaiverReverseTests(unittest.TestCase):
    def test_preference_escalation_becomes_waiver(self) -> None:
        waiver = escalation_to_waiver(_escalation(severity=PREFERENCE))
        self.assertEqual(waiver["category"], "static")
        self.assertEqual(waiver["reason"], "false-positive in vendored deps")
        self.assertEqual(waiver["granted_by"], "operator@example")
        self.assertEqual(waiver["expires_at"], "2026-12-31T23:59:59Z")
        self.assertEqual(waiver["scope"], "story:S-001")
        # The resulting waiver must NOT carry escalation-only keys.
        self.assertNotIn("severity", waiver)
        self.assertNotIn("api_version", waiver)
        self.assertNotIn("kind", waiver)

    def test_critical_escalation_cannot_become_waiver(self) -> None:
        with self.assertRaises(WaiverEscalationError):
            escalation_to_waiver(_escalation(severity=CRITICAL))

    def test_unknown_severity_rejected(self) -> None:
        with self.assertRaises(WaiverEscalationError):
            escalation_to_waiver(_escalation(severity="warning"))

    def test_wrong_kind_rejected(self) -> None:
        bad = _escalation()
        bad["kind"] = "trace"
        with self.assertRaises(WaiverEscalationError):
            escalation_to_waiver(bad)

    def test_unsupported_api_version_rejected(self) -> None:
        bad = _escalation()
        bad["api_version"] = 99
        with self.assertRaises(WaiverEscalationError):
            escalation_to_waiver(bad)


class RoundTripTests(unittest.TestCase):
    def test_waiver_round_trip_is_lossless(self) -> None:
        original = _waiver(
            category="docs",
            reason="ADR-007 covers this gap",
            granted_by="tech-lead@example",
            expires_at="2027-01-15T00:00:00Z",
            scope="epic:E-04",
        )
        restored = round_trip_waiver(original)
        self.assertEqual(restored, original)

    def test_is_waiver_equivalent_true_for_preference(self) -> None:
        self.assertTrue(is_waiver_equivalent(_escalation(severity=PREFERENCE)))

    def test_is_waiver_equivalent_false_for_critical(self) -> None:
        self.assertFalse(is_waiver_equivalent(_escalation(severity=CRITICAL)))

    def test_is_waiver_equivalent_false_for_malformed(self) -> None:
        self.assertFalse(is_waiver_equivalent({"severity": PREFERENCE}))


class InputValidationTests(unittest.TestCase):
    def test_waiver_must_be_mapping(self) -> None:
        with self.assertRaises(WaiverEscalationError):
            waiver_to_escalation("not a dict")  # type: ignore[arg-type]

    def test_escalation_must_be_mapping(self) -> None:
        with self.assertRaises(WaiverEscalationError):
            escalation_to_waiver(["nope"])  # type: ignore[arg-type]

    def test_extra_keys_in_waiver_are_preserved_as_metadata(self) -> None:
        waiver = _waiver()
        waiver["notes"] = "see ticket #42"
        esc = waiver_to_escalation(waiver)
        self.assertEqual(esc["metadata"], {"notes": "see ticket #42"})

    def test_extra_keys_round_trip_through_metadata(self) -> None:
        original = _waiver()
        original["notes"] = "see ticket #42"
        restored = round_trip_waiver(original)
        self.assertEqual(restored["notes"], "see ticket #42")


if __name__ == "__main__":
    unittest.main()
