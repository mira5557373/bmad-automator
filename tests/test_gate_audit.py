from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from story_automator.core.audit import Event as AuditEventProtocol
from story_automator.core.gate_audit import (
    EvidenceCollectedAudit,
    GateBoundaryViolation,
    GateDecisionAudit,
    GateParkedAudit,
    GateProfileDriftAudit,
    GateRenderedAudit,
    GateStartedAudit,
    emit_gate_audit,
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


class EmitGateAuditTests(unittest.TestCase):
    def _policy_with_audit(self) -> dict:
        return {"security": {"audit_trail": True}}

    def _policy_without_audit(self) -> dict:
        return {"security": {"audit_trail": False}}

    def test_emits_to_audit_log_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = self._policy_with_audit()
            event = GateStartedAudit(gate_id="g1", commit_sha="abc", profile_hash="h1")
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
                emit_gate_audit(policy, audit_path, event)
            self.assertTrue(audit_path.exists())
            line = audit_path.read_text().strip()
            record = json.loads(line)
            self.assertEqual(record["event"], "GateStarted")
            self.assertIn("gate_id", record["payload"])

    def test_noop_when_audit_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = self._policy_without_audit()
            event = GateStartedAudit(gate_id="g1", commit_sha="abc", profile_hash="h1")
            emit_gate_audit(policy, audit_path, event)
            self.assertFalse(audit_path.exists())

    def test_emits_boundary_violation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = self._policy_with_audit()
            event = GateBoundaryViolation(operation="persist", context="child")
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
                emit_gate_audit(policy, audit_path, event)
            line = audit_path.read_text().strip()
            record = json.loads(line)
            self.assertEqual(record["event"], "GateBoundaryViolation")

    def test_emits_evidence_collected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            audit_path = pathlib.Path(td) / "audit.jsonl"
            policy = self._policy_with_audit()
            event = EvidenceCollectedAudit(
                gate_id="g1", category="security", collector="c",
                tool="semgrep", status="ok", duration_ms=100,
            )
            with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
                emit_gate_audit(policy, audit_path, event)
            line = audit_path.read_text().strip()
            record = json.loads(line)
            self.assertEqual(record["event"], "EvidenceCollected")
            self.assertEqual(record["payload"]["status"], "ok")


class GateDecisionAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateDecisionAudit(
            gate_id="g1", overall="PASS", commit_sha="abc",
            profile_hash="aabb", categories_summary="correctness:PASS,security:PASS",
        )
        self.assertEqual(event.event_name, "GateDecision")

    def test_to_dict_has_all_fields(self) -> None:
        event = GateDecisionAudit(
            gate_id="g1", overall="FAIL", commit_sha="abc",
            profile_hash="aabb", categories_summary="security:FAIL",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["overall"], "FAIL")
        self.assertEqual(d["commit_sha"], "abc")
        self.assertIn("categories_summary", d)


class GateRenderedAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateRenderedAudit(
            gate_id="g1", gate_file_path="verdicts/g1.json",
            evidence_bundle_hash="1234567890abcdef",
        )
        self.assertEqual(event.event_name, "GateRendered")

    def test_to_dict_has_all_fields(self) -> None:
        event = GateRenderedAudit(
            gate_id="g1", gate_file_path="verdicts/g1.json",
            evidence_bundle_hash="abcd1234",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["gate_file_path"], "verdicts/g1.json")
        self.assertEqual(d["evidence_bundle_hash"], "abcd1234")


class GateProfileDriftAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateProfileDriftAudit(
            gate_id="g1", old_hash="aabb", new_hash="ccdd",
            old_factory_version="1.14.0", new_factory_version="1.15.0",
            reason="profile.hash mismatch",
        )
        self.assertEqual(event.event_name, "GateProfileDrift")

    def test_to_dict_contains_all_fields(self) -> None:
        event = GateProfileDriftAudit(
            gate_id="g1", old_hash="aabb", new_hash="ccdd",
            old_factory_version="1.14.0", new_factory_version="1.15.0",
            reason="profile.hash mismatch",
        )
        d = event.to_dict()
        self.assertEqual(d["gate_id"], "g1")
        self.assertEqual(d["old_hash"], "aabb")
        self.assertEqual(d["new_hash"], "ccdd")
        self.assertEqual(d["reason"], "profile.hash mismatch")

    def test_frozen(self) -> None:
        event = GateProfileDriftAudit(gate_id="g1")
        with self.assertRaises(AttributeError):
            event.gate_id = "g2"  # type: ignore[misc]


class GateParkedAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        event = GateParkedAudit(
            gate_id="g1", story_key="E1-001", reason="exhausted",
            overall_verdict="FAIL",
        )
        self.assertEqual(event.event_name, "GateParked")

    def test_to_dict(self) -> None:
        event = GateParkedAudit(
            gate_id="g1", story_key="E1-001", reason="risk-9",
            overall_verdict="FAIL",
        )
        d = event.to_dict()
        self.assertEqual(d["story_key"], "E1-001")
        self.assertEqual(d["reason"], "risk-9")
        self.assertEqual(d["overall_verdict"], "FAIL")


class GateCalibrationAuditTests(unittest.TestCase):
    def test_event_name(self) -> None:
        from story_automator.core.gate_audit import GateCalibrationAudit
        event = GateCalibrationAudit(
            profile_id="default",
            proposals_applied=2,
            proposals_deferred=1,
            old_version="1.0",
            new_version="1.1",
        )
        self.assertEqual(event.event_name, "GateCalibration")

    def test_to_dict_contains_all_fields(self) -> None:
        from story_automator.core.gate_audit import GateCalibrationAudit
        event = GateCalibrationAudit(
            profile_id="msme-erp",
            proposals_applied=3,
            proposals_deferred=0,
            old_version="1.2",
            new_version="1.3",
        )
        d = event.to_dict()
        self.assertEqual(d["profile_id"], "msme-erp")
        self.assertEqual(d["proposals_applied"], 3)
        self.assertEqual(d["proposals_deferred"], 0)

    def test_frozen(self) -> None:
        from story_automator.core.gate_audit import GateCalibrationAudit
        event = GateCalibrationAudit(profile_id="x")
        with self.assertRaises(AttributeError):
            event.profile_id = "y"


if __name__ == "__main__":
    unittest.main()
