import json
import tempfile
import unittest
from unittest.mock import patch

from story_automator.core.gate_history import (
    count_gate_history,
    load_gate_history,
    make_history_record,
    prune_gate_history,
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

    def test_rejects_path_traversal_gate_id(self) -> None:
        gf = _make_gate_file(gate_id="../escape")
        with self.assertRaises(ValueError):
            record_gate_result(self.tmp, gf, story_key="E1-001")

    def test_rejects_slash_in_gate_id(self) -> None:
        gf = _make_gate_file(gate_id="foo/bar")
        with self.assertRaises(ValueError):
            record_gate_result(self.tmp, gf, story_key="E1-001")


class LoadGateHistoryTests(unittest.TestCase):
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

    def test_empty_history(self) -> None:
        records = load_gate_history(self.tmp)
        self.assertEqual(records, [])

    def test_loads_persisted_records(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        record_gate_result(self.tmp, _make_gate_file(gate_id="g-002"), story_key="E1-002")
        records = load_gate_history(self.tmp)
        self.assertEqual(len(records), 2)

    def test_sorted_chronologically(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(gate_id="g-a"), story_key="E1-001")
        record_gate_result(self.tmp, _make_gate_file(gate_id="g-b"), story_key="E1-002")
        records = load_gate_history(self.tmp)
        self.assertEqual(records[0]["gate_id"], "g-a")
        self.assertEqual(records[1]["gate_id"], "g-b")

    def test_filter_by_profile_id(self) -> None:
        record_gate_result(
            self.tmp, _make_gate_file(profile_id="default"), story_key="E1-001",
        )
        record_gate_result(
            self.tmp,
            _make_gate_file(gate_id="g-002", profile_id="msme-erp"),
            story_key="E1-002",
        )
        records = load_gate_history(self.tmp, profile_id="msme-erp")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["profile_id"], "msme-erp")

    def test_filter_by_story_key(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        record_gate_result(
            self.tmp, _make_gate_file(gate_id="g-002"), story_key="E2-003",
        )
        records = load_gate_history(self.tmp, story_key="E1-001")
        self.assertEqual(len(records), 1)

    def test_filter_by_overall(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(overall="PASS"), story_key="E1-001")
        record_gate_result(
            self.tmp, _make_gate_file(gate_id="g-002", overall="FAIL"),
            story_key="E1-002",
        )
        records = load_gate_history(self.tmp, overall="FAIL")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["overall"], "FAIL")

    def test_filter_by_since(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        records = load_gate_history(self.tmp, since="2099-01-01T00:00:00Z")
        self.assertEqual(len(records), 0)
        records_all = load_gate_history(self.tmp, since="2000-01-01T00:00:00Z")
        self.assertEqual(len(records_all), 1)


class CountGateHistoryTests(unittest.TestCase):
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

    def test_empty(self) -> None:
        self.assertEqual(count_gate_history(self.tmp), 0)

    def test_counts_files(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        record_gate_result(
            self.tmp, _make_gate_file(gate_id="g-002"), story_key="E1-002",
        )
        self.assertEqual(count_gate_history(self.tmp), 2)


class PruneGateHistoryTests(unittest.TestCase):
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

    def test_prune_empty(self) -> None:
        pruned = prune_gate_history(self.tmp, max_age_days=1)
        self.assertEqual(pruned, 0)

    def test_prune_old_records(self) -> None:
        record_gate_result(self.tmp, _make_gate_file(), story_key="E1-001")
        pruned = prune_gate_history(self.tmp, max_age_days=365)
        self.assertEqual(pruned, 0)
        self.assertEqual(count_gate_history(self.tmp), 1)

    def test_prune_by_max_records(self) -> None:
        for i in range(5):
            record_gate_result(
                self.tmp, _make_gate_file(gate_id=f"g-{i:03d}"),
                story_key=f"E1-{i:03d}",
            )
        pruned = prune_gate_history(self.tmp, max_records=3)
        self.assertEqual(pruned, 2)
        self.assertEqual(count_gate_history(self.tmp), 3)

    def test_prune_keeps_newest(self) -> None:
        for i in range(5):
            record_gate_result(
                self.tmp, _make_gate_file(gate_id=f"g-{i:03d}"),
                story_key=f"E1-{i:03d}",
            )
        prune_gate_history(self.tmp, max_records=2)
        remaining = load_gate_history(self.tmp)
        gate_ids = [r["gate_id"] for r in remaining]
        self.assertIn("g-003", gate_ids)
        self.assertIn("g-004", gate_ids)


if __name__ == "__main__":
    unittest.main()
