"""Tests for gate_status — mitigation debt, park/resume, invalidation."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from story_automator.core.gate_status import (
    clear_mitigation_debt,
    load_mitigation_debt,
    record_mitigation_debt,
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


if __name__ == "__main__":
    unittest.main()
