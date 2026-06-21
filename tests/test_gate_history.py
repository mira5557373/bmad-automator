import json
import tempfile
import unittest
from unittest.mock import patch

from story_automator.core.gate_history import (
    make_history_record,
    record_gate_result,
)


def _make_gate_file(
    gate_id="g-001",
    overall="PASS",
    commit_sha="abc123",
    categories=None,
    profile_hash="aabb",
    profile_id="default",
    factory_version="1.15.0",
    evidence_bundle_hash="eebb",
):
    return {
        "gate_id": gate_id,
        "schema_version": 1,
        "target": {"kind": "story", "id": "E1-001"},
        "tier": "code",
        "commit_sha": commit_sha,
        "scanner_data_snapshot": "",
        "profile": {"id": profile_id, "version": 1, "hash": profile_hash},
        "factory_version": factory_version,
        "risk_profile_ref": "",
        "categories": categories or {
            "correctness": {"verdict": "PASS", "rationale": "all green"},
            "security": {"verdict": "PASS", "rationale": "clean"},
        },
        "overall": overall,
        "waivers": [],
        "evidence_bundle_hash": evidence_bundle_hash,
    }


class MakeHistoryRecordTests(unittest.TestCase):
    def test_extracts_core_fields(self) -> None:
        gf = _make_gate_file()
        rec = make_history_record(gf, story_key="E1-001")
        self.assertEqual(rec["gate_id"], "g-001")
        self.assertEqual(rec["story_key"], "E1-001")
        self.assertEqual(rec["overall"], "PASS")
        self.assertEqual(rec["commit_sha"], "abc123")
        self.assertEqual(rec["profile_id"], "default")
        self.assertEqual(rec["profile_hash"], "aabb")
        self.assertEqual(rec["factory_version"], "1.15.0")
        self.assertEqual(rec["evidence_bundle_hash"], "eebb")
        self.assertIn("recorded_at", rec)

    def test_extracts_category_verdicts(self) -> None:
        gf = _make_gate_file(categories={
            "security": {"verdict": "FAIL", "rationale": "vuln found"},
        })
        rec = make_history_record(gf, story_key="E1-001")
        self.assertEqual(rec["categories"]["security"]["verdict"], "FAIL")

    def test_remediation_cycle_default(self) -> None:
        rec = make_history_record(_make_gate_file(), story_key="E1-001")
        self.assertEqual(rec["remediation_cycle"], 0)

    def test_remediation_cycle_explicit(self) -> None:
        rec = make_history_record(
            _make_gate_file(), story_key="E1-001", remediation_cycle=2,
        )
        self.assertEqual(rec["remediation_cycle"], 2)


class RecordGateResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch(
            "story_automator.core.gate_history.assert_host_context",
        )
        self.patcher.start()

    def tearDown(self) -> None:
        self.patcher.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persists_to_history_dir(self) -> None:
        gf = _make_gate_file()
        path = record_gate_result(self.tmp, gf, story_key="E1-001")
        self.assertTrue(path.is_file())
        self.assertIn("history", str(path))

    def test_persisted_record_is_valid_json(self) -> None:
        gf = _make_gate_file()
        path = record_gate_result(self.tmp, gf, story_key="E1-001")
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["gate_id"], "g-001")

    def test_filename_contains_gate_id(self) -> None:
        gf = _make_gate_file(gate_id="my-gate-42")
        path = record_gate_result(self.tmp, gf, story_key="E1-001")
        self.assertIn("my-gate-42", path.name)


if __name__ == "__main__":
    unittest.main()
