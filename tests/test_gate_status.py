"""Tests for gate_status — mitigation debt, park/resume, invalidation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.gate_status import (
    clear_mitigation_debt,
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


if __name__ == "__main__":
    unittest.main()
