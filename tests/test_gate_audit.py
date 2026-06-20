from __future__ import annotations

import unittest

from story_automator.core.audit import Event as AuditEventProtocol
from story_automator.core.gate_audit import (
    EvidenceCollectedAudit,
    GateBoundaryViolation,
    GateStartedAudit,
)


class GateStartedAuditTests(unittest.TestCase):
    def test_satisfies_audit_event_protocol(self) -> None:
        event = GateStartedAudit(
            gate_id="gate-001",
            commit_sha="abc123",
            profile_hash="def456",
        )
        self.assertIsInstance(event, AuditEventProtocol)

    def test_event_name(self) -> None:
        event = GateStartedAudit(gate_id="g1", commit_sha="sha1", profile_hash="h1")
        self.assertEqual(event.event_name, "GateStarted")

    def test_to_dict_contains_fields(self) -> None:
        event = GateStartedAudit(
            gate_id="gate-001",
            commit_sha="abc123",
            profile_hash="def456",
            tier="code",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "gate-001")
        self.assertEqual(d["commit_sha"], "abc123")
        self.assertEqual(d["profile_hash"], "def456")
        self.assertEqual(d["tier"], "code")

    def test_default_tier(self) -> None:
        event = GateStartedAudit(gate_id="g1", commit_sha="s1", profile_hash="h1")
        self.assertEqual(event.tier, "code")

    def test_frozen(self) -> None:
        event = GateStartedAudit(gate_id="g1", commit_sha="s1", profile_hash="h1")
        with self.assertRaises(AttributeError):
            event.gate_id = "mutated"  # type: ignore[misc]


class EvidenceCollectedAuditTests(unittest.TestCase):
    def test_satisfies_audit_event_protocol(self) -> None:
        event = EvidenceCollectedAudit(
            gate_id="g1",
            category="security",
            collector="semgrep-collector",
            tool="semgrep",
            status="ok",
            duration_ms=1234,
        )
        self.assertIsInstance(event, AuditEventProtocol)

    def test_event_name(self) -> None:
        event = EvidenceCollectedAudit(
            gate_id="g1", category="c", collector="co", tool="t",
            status="ok", duration_ms=0,
        )
        self.assertEqual(event.event_name, "EvidenceCollected")

    def test_to_dict_contains_fields(self) -> None:
        event = EvidenceCollectedAudit(
            gate_id="g1",
            category="security",
            collector="semgrep-collector",
            tool="semgrep",
            status="violation",
            duration_ms=500,
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["category"], "security")
        self.assertEqual(d["collector"], "semgrep-collector")
        self.assertEqual(d["tool"], "semgrep")
        self.assertEqual(d["status"], "violation")
        self.assertEqual(d["duration_ms"], 500)


class GateBoundaryViolationTests(unittest.TestCase):
    def test_satisfies_audit_event_protocol(self) -> None:
        event = GateBoundaryViolation(
            operation="persist_evidence",
            context="child tried to write evidence",
        )
        self.assertIsInstance(event, AuditEventProtocol)

    def test_event_name(self) -> None:
        event = GateBoundaryViolation(operation="op", context="ctx")
        self.assertEqual(event.event_name, "GateBoundaryViolation")

    def test_to_dict_contains_fields(self) -> None:
        event = GateBoundaryViolation(
            operation="run_collector",
            context="STORY_AUTOMATOR_CHILD=true",
        )
        d = event.to_dict()
        self.assertEqual(d["operation"], "run_collector")
        self.assertEqual(d["context"], "STORY_AUTOMATOR_CHILD=true")


if __name__ == "__main__":
    unittest.main()
