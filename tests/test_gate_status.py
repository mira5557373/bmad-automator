"""Tests for gate_status — mitigation debt, park/resume, invalidation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.evidence_io import persist_gate_file
from story_automator.core.gate_schema import make_gate_file
from story_automator.core.gate_status import (
    clear_mitigation_debt,
    invalidate_gate,
    invalidate_gates_for_target,
    list_parked,
    load_mitigation_debt,
    park_story,
    record_mitigation_debt,
    resume_story,
)


class RecordMitigationDebtTests(unittest.TestCase):
    def test_creates_mitigation_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = record_mitigation_debt(
                tmp, "gate-001", "E1.S1", ["security", "docs"],
            )
            self.assertTrue(path.is_file())
            self.assertIn("mitigation", str(path))
            self.assertEqual(path.name, "gate-001.json")

    def test_file_contains_expected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = record_mitigation_debt(
                tmp, "gate-002", "E1.S2", ["correctness"],
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["gate_id"], "gate-002")
            self.assertEqual(data["story_key"], "E1.S2")
            self.assertEqual(data["categories"], ["correctness"])
            self.assertIn("recorded_at", data)

    def test_overwrites_existing_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record_mitigation_debt(tmp, "gate-003", "E1.S3", ["docs"])
            path = record_mitigation_debt(
                tmp, "gate-003", "E1.S3", ["docs", "security"],
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["categories"], ["docs", "security"])


class LoadMitigationDebtTests(unittest.TestCase):
    def test_empty_when_no_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_mitigation_debt(tmp)
            self.assertEqual(result, [])

    def test_loads_all_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record_mitigation_debt(tmp, "gate-010", "E1.S1", ["security"])
            record_mitigation_debt(tmp, "gate-011", "E1.S2", ["docs"])
            result = load_mitigation_debt(tmp)
            self.assertEqual(len(result), 2)
            gate_ids = {r["gate_id"] for r in result}
            self.assertEqual(gate_ids, {"gate-010", "gate-011"})


class ClearMitigationDebtTests(unittest.TestCase):
    def test_removes_existing_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record_mitigation_debt(tmp, "gate-020", "E1.S1", ["security"])
            removed = clear_mitigation_debt(tmp, "gate-020")
            self.assertTrue(removed)
            self.assertEqual(load_mitigation_debt(tmp), [])

    def test_returns_false_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            removed = clear_mitigation_debt(tmp, "gate-nonexistent")
            self.assertFalse(removed)


class ParkStoryTests(unittest.TestCase):
    def test_creates_parked_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = park_story(
                tmp, "gate-100", "E2.S1", "exhaustion", "FAIL",
            )
            self.assertTrue(path.is_file())
            self.assertIn("parked", str(path))
            self.assertEqual(path.name, "gate-100.json")

    def test_parked_file_contents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = park_story(
                tmp, "gate-101", "E2.S2", "risk-9", "CONCERNS",
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["gate_id"], "gate-101")
            self.assertEqual(data["story_key"], "E2.S2")
            self.assertEqual(data["reason"], "risk-9")
            self.assertEqual(data["overall_verdict"], "CONCERNS")
            self.assertIn("parked_at", data)

    @patch("story_automator.core.gate_status.emit_gate_audit")
    def test_emits_audit_event_when_policy_provided(self, mock_emit: object) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            policy = {"security": {"audit_trail": True}}
            park_story(
                tmp, "gate-102", "E2.S3", "exhaustion", "FAIL",
                audit_policy=policy,
                audit_path=audit_path,
            )
            mock_emit.assert_called_once()  # type: ignore[attr-defined]
            args = mock_emit.call_args  # type: ignore[attr-defined]
            event = args[0][2]
            self.assertEqual(event.gate_id, "gate-102")
            self.assertEqual(event.reason, "exhaustion")


class ListParkedTests(unittest.TestCase):
    def test_empty_when_no_parked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = list_parked(tmp)
            self.assertEqual(result, [])

    def test_lists_all_parked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            park_story(tmp, "gate-110", "E3.S1", "exhaustion", "FAIL")
            park_story(tmp, "gate-111", "E3.S2", "risk-9", "CONCERNS")
            result = list_parked(tmp)
            self.assertEqual(len(result), 2)

    def test_filters_by_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            park_story(tmp, "gate-120", "E3.S1", "exhaustion", "FAIL")
            park_story(tmp, "gate-121", "E3.S2", "risk-9", "CONCERNS")
            result = list_parked(tmp, state_filter="exhaustion")
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["reason"], "exhaustion")


class ResumeStoryTests(unittest.TestCase):
    def test_removes_and_returns_parked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            park_story(tmp, "gate-130", "E4.S1", "exhaustion", "FAIL")
            result = resume_story(tmp, "gate-130")
            self.assertIsNotNone(result)
            self.assertEqual(result["gate_id"], "gate-130")
            # Should be removed from parked
            self.assertEqual(list_parked(tmp), [])

    def test_returns_none_when_not_parked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = resume_story(tmp, "gate-nonexistent")
            self.assertIsNone(result)


def _make_test_gate(gate_id: str, target_id: str = "E1.S1", overall: str = "PASS") -> dict:
    """Helper to build a minimal valid gate file for testing."""
    return make_gate_file(
        gate_id=gate_id,
        target={"kind": "story", "id": target_id},
        commit_sha="abc123def456",
        profile={"id": "default", "version": 1, "hash": "aabbccdd"},
        factory_version="0.1.0",
        categories={"correctness": {"verdict": "PASS"}},
        overall=overall,
    )


class InvalidateGateTests(unittest.TestCase):
    def test_renames_existing_gate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = _make_test_gate("gate-200")
            persist_gate_file(tmp, gate)
            ok, msg = invalidate_gate(tmp, "gate-200")
            self.assertTrue(ok)
            # Original should be gone
            original = Path(tmp) / "_bmad" / "gate" / "verdicts" / "gate-200.json"
            self.assertFalse(original.exists())
            # Invalidated copy should exist
            renamed = Path(tmp) / "_bmad" / "gate" / "verdicts" / "gate-200.invalidated.json"
            self.assertTrue(renamed.is_file())

    def test_returns_false_when_gate_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg = invalidate_gate(tmp, "gate-nonexistent")
            self.assertFalse(ok)
            self.assertIn("not found", msg)

    def test_invalidated_file_is_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = _make_test_gate("gate-201")
            persist_gate_file(tmp, gate)
            invalidate_gate(tmp, "gate-201")
            renamed = Path(tmp) / "_bmad" / "gate" / "verdicts" / "gate-201.invalidated.json"
            data = json.loads(renamed.read_text(encoding="utf-8"))
            self.assertEqual(data["gate_id"], "gate-201")


class InvalidateGatesForTargetTests(unittest.TestCase):
    def test_invalidates_matching_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate1 = _make_test_gate("gate-300", target_id="E1.S1")
            gate2 = _make_test_gate("gate-301", target_id="E1.S1")
            gate3 = _make_test_gate("gate-302", target_id="E2.S1")
            persist_gate_file(tmp, gate1)
            persist_gate_file(tmp, gate2)
            persist_gate_file(tmp, gate3)
            invalidated = invalidate_gates_for_target(tmp, "E1.S1")
            self.assertEqual(len(invalidated), 2)
            self.assertIn("gate-300", invalidated)
            self.assertIn("gate-301", invalidated)
            # gate-302 should still be intact
            remaining = Path(tmp) / "_bmad" / "gate" / "verdicts" / "gate-302.json"
            self.assertTrue(remaining.is_file())

    def test_returns_empty_when_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = _make_test_gate("gate-310", target_id="E5.S1")
            persist_gate_file(tmp, gate)
            invalidated = invalidate_gates_for_target(tmp, "E99.S99")
            self.assertEqual(invalidated, [])

    def test_returns_empty_when_no_verdicts_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalidated = invalidate_gates_for_target(tmp, "E1.S1")
            self.assertEqual(invalidated, [])


if __name__ == "__main__":
    unittest.main()
