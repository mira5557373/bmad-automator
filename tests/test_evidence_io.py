from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from story_automator.core.gate_schema import (
    GateSchemaError,
    make_evidence_record,
    make_gate_file,
    make_llm_evidence_record,
)
from story_automator.core.evidence_io import (
    GateMarkerCorruptedError,
    can_reuse_gate_file,
    clear_gate_marker,
    compute_evidence_bundle_hash,
    evidence_filename,
    evidence_migrate,
    load_evidence_bundle,
    persist_evidence_record,
    persist_gate_file,
    load_gate_file,
    read_gate_marker,
    write_gate_marker,
)
from story_automator.core.trust_boundary import TrustBoundaryError


class EvidenceMigrateTests(unittest.TestCase):
    def _v1_record(self) -> dict:
        return make_evidence_record(
            collector="test-collector",
            tool="pytest",
            category="correctness",
            status="ok",
        )

    def test_v1_to_v1_passthrough(self) -> None:
        original = self._v1_record()
        migrated = evidence_migrate(original)
        self.assertEqual(migrated, original)

    def test_returns_deep_copy(self) -> None:
        original = self._v1_record()
        migrated = evidence_migrate(original)
        migrated["collector"] = "mutated"
        self.assertEqual(original["collector"], "test-collector")

    def test_explicit_target_v1(self) -> None:
        record = self._v1_record()
        migrated = evidence_migrate(record, target_version=1)
        self.assertEqual(migrated["schema_version"], 1)

    def test_downgrade_raises(self) -> None:
        record = self._v1_record()
        record["schema_version"] = 2
        with self.assertRaisesRegex(GateSchemaError, "cannot downgrade"):
            evidence_migrate(record, target_version=1)

    def test_unknown_target_raises(self) -> None:
        record = self._v1_record()
        with self.assertRaisesRegex(GateSchemaError, "unknown target"):
            evidence_migrate(record, target_version=999)

    def test_invalid_schema_version_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "schema_version"):
            evidence_migrate({"schema_version": "bad"})

    def test_zero_schema_version_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "schema_version"):
            evidence_migrate({"schema_version": 0})

    def test_llm_evidence_preserves_confidence_and_rationale(self) -> None:
        from story_automator.core.gate_schema import make_llm_evidence_record
        original = make_llm_evidence_record(
            collector="llm-reviewer", tool="claude",
            category="test_quality", status="ok",
            confidence=7, rationale="Good coverage",
        )
        migrated = evidence_migrate(original)
        self.assertEqual(migrated["confidence"], 7)
        self.assertEqual(migrated["rationale"], "Good coverage")
        self.assertFalse(migrated["deterministic"])


class ComputeEvidenceBundleHashTests(unittest.TestCase):
    def _record(self, category: str, collector: str, tool: str) -> dict:
        return make_evidence_record(
            collector=collector, tool=tool, category=category, status="ok",
        )

    def test_deterministic_same_input(self) -> None:
        records = [
            self._record("correctness", "test-runner", "pytest"),
            self._record("security", "scanner", "semgrep"),
        ]
        hash1 = compute_evidence_bundle_hash(records)
        hash2 = compute_evidence_bundle_hash(records)
        self.assertEqual(hash1, hash2)

    def test_order_independent(self) -> None:
        r1 = self._record("correctness", "test-runner", "pytest")
        r2 = self._record("security", "scanner", "semgrep")
        hash_ab = compute_evidence_bundle_hash([r1, r2])
        hash_ba = compute_evidence_bundle_hash([r2, r1])
        self.assertEqual(hash_ab, hash_ba)

    def test_returns_16_char_hex(self) -> None:
        records = [self._record("correctness", "runner", "pytest")]
        result = compute_evidence_bundle_hash(records)
        self.assertEqual(len(result), 16)
        int(result, 16)

    def test_empty_list_returns_deterministic_hash(self) -> None:
        h1 = compute_evidence_bundle_hash([])
        h2 = compute_evidence_bundle_hash([])
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_different_records_different_hash(self) -> None:
        r1 = [self._record("correctness", "runner", "pytest")]
        r2 = [self._record("security", "scanner", "semgrep")]
        self.assertNotEqual(
            compute_evidence_bundle_hash(r1),
            compute_evidence_bundle_hash(r2),
        )


class EvidenceFilenameTests(unittest.TestCase):
    def test_simple_names(self) -> None:
        record = make_evidence_record(
            collector="test-runner", tool="pytest",
            category="correctness", status="ok",
        )
        self.assertEqual(
            evidence_filename(record),
            "correctness--test-runner--pytest.json",
        )

    def test_sanitizes_slashes(self) -> None:
        record = make_evidence_record(
            collector="my/collector", tool="some/tool",
            category="security", status="ok",
        )
        name = evidence_filename(record)
        self.assertNotIn("/", name)
        self.assertTrue(name.endswith(".json"))

    def test_sanitizes_dot_dot(self) -> None:
        record = make_evidence_record(
            collector="test", tool="pytest",
            category="correctness", status="ok",
        )
        record["collector"] = "foo..bar"
        name = evidence_filename(record)
        self.assertNotIn("..", name)


class PersistEvidenceRecordTests(unittest.TestCase):
    def test_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            path = persist_evidence_record(tmp, "gate-001", record)
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["collector"], "runner")

    def test_file_lives_under_gate_id_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            path = persist_evidence_record(tmp, "gate-002", record)
            self.assertIn("gate-002", str(path))

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            path = persist_evidence_record(tmp, "gate-003", record)
            self.assertTrue(path.parent.is_dir())

    def test_rejects_path_traversal_gate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            with self.assertRaisesRegex(GateSchemaError, "invalid path"):
                persist_evidence_record(tmp, "../../etc", record)

    def test_rejects_empty_gate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            with self.assertRaisesRegex(GateSchemaError, "gate_id"):
                persist_evidence_record(tmp, "", record)


class LoadEvidenceBundleTests(unittest.TestCase):
    def test_loads_persisted_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r1 = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            r2 = make_evidence_record(
                collector="scanner", tool="semgrep",
                category="security", status="ok",
            )
            persist_evidence_record(tmp, "gate-010", r1)
            persist_evidence_record(tmp, "gate-010", r2)
            bundle = load_evidence_bundle(tmp, "gate-010")
            self.assertEqual(len(bundle), 2)
            categories = {r["category"] for r in bundle}
            self.assertEqual(categories, {"correctness", "security"})

    def test_empty_dir_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = load_evidence_bundle(tmp, "nonexistent-gate")
            self.assertEqual(bundle, [])

    def test_sorted_by_category_collector_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r_sec = make_evidence_record(
                collector="scanner", tool="semgrep",
                category="security", status="ok",
            )
            r_cor = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            persist_evidence_record(tmp, "gate-011", r_sec)
            persist_evidence_record(tmp, "gate-011", r_cor)
            bundle = load_evidence_bundle(tmp, "gate-011")
            self.assertEqual(bundle[0]["category"], "correctness")
            self.assertEqual(bundle[1]["category"], "security")

    def test_rejects_future_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = make_evidence_record(
                collector="runner", tool="pytest",
                category="correctness", status="ok",
            )
            record["schema_version"] = 999
            evidence_dir = (
                Path(tmp) / "_bmad" / "gate" / "evidence" / "gate-012"
            )
            evidence_dir.mkdir(parents=True)
            target = evidence_dir / "correctness--runner--pytest.json"
            target.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(GateSchemaError, "schema_version"):
                load_evidence_bundle(tmp, "gate-012")

    def test_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence_dir = (
                Path(tmp) / "_bmad" / "gate" / "evidence" / "gate-013"
            )
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "bad.json").write_text(
                "not valid json", encoding="utf-8",
            )
            with self.assertRaisesRegex(GateSchemaError, "invalid JSON"):
                load_evidence_bundle(tmp, "gate-013")


class PersistGateFileTests(unittest.TestCase):
    def _valid_gate(self) -> dict:
        return make_gate_file(
            gate_id="gate-100",
            target={"kind": "story", "id": "E1.S1"},
            commit_sha="abc123def456",
            profile={"id": "default", "version": 1, "hash": "aabbccdd"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )

    def test_writes_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._valid_gate()
            path = persist_gate_file(tmp, gate)
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["gate_id"], "gate-100")

    def test_file_in_verdicts_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = self._valid_gate()
            path = persist_gate_file(tmp, gate)
            self.assertIn("verdicts", str(path))
            self.assertEqual(path.name, "gate-100.json")


class LoadGateFileTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = make_gate_file(
                gate_id="gate-200",
                target={"kind": "story", "id": "E1.S2"},
                commit_sha="deadbeef",
                profile={"id": "default", "version": 1, "hash": "11223344"},
                factory_version="0.2.0",
                categories={"security": {"verdict": "FAIL"}},
                overall="FAIL",
            )
            persist_gate_file(tmp, gate)
            loaded = load_gate_file(tmp, "gate-200")
            self.assertEqual(loaded["gate_id"], "gate-200")
            self.assertEqual(loaded["overall"], "FAIL")

    def test_missing_gate_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(GateSchemaError, "not found"):
                load_gate_file(tmp, "nonexistent")

    def test_rejects_future_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            verdicts_dir = Path(tmp) / "_bmad" / "gate" / "verdicts"
            verdicts_dir.mkdir(parents=True)
            bad_gate = {
                "gate_id": "gate-300",
                "schema_version": 999,
                "target": {"kind": "story"},
                "commit_sha": "abc",
                "profile": {"id": "x"},
                "factory_version": "0.1",
                "categories": {},
                "overall": "PASS",
                "waivers": [],
            }
            (verdicts_dir / "gate-300.json").write_text(
                json.dumps(bad_gate), encoding="utf-8",
            )
            with self.assertRaisesRegex(GateSchemaError, "schema_version"):
                load_gate_file(tmp, "gate-300")


class CanReuseGateFileTests(unittest.TestCase):
    def _gate(self) -> dict:
        return {
            "gate_id": "gate-400",
            "commit_sha": "abc123",
            "profile": {"id": "default", "version": 1, "hash": "aabbccdd"},
            "factory_version": "0.1.0",
        }

    def test_all_match_returns_true(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_commit_sha_mismatch(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="different",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("commit_sha", reason)

    def test_profile_hash_mismatch(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="different",
            factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("profile", reason)

    def test_factory_version_mismatch(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.2.0",
        )
        self.assertFalse(ok)
        self.assertIn("factory_version", reason)

    def test_multiple_mismatches_reports_first(self) -> None:
        gate = self._gate()
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="wrong",
            profile_hash="wrong",
            factory_version="wrong",
        )
        self.assertFalse(ok)
        self.assertTrue(len(reason) > 0)

    def test_missing_profile_hash_reports_mismatch(self) -> None:
        gate = self._gate()
        gate["profile"] = {"id": "x"}
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("profile", reason)

    # §6.4(e): waiver.expires_at must be re-checked on EVERY reuse.
    # Expired waiver → forces re-evaluation, even when all three of
    # commit_sha / profile.hash / factory_version match.

    def test_expired_waiver_blocks_reuse(self) -> None:
        gate = self._gate()
        gate["waivers"] = [{
            "waiver_id": "01J90000000000000000000W",
            "operator_id": "mira",
            "issued_at": "2026-06-01T00:00:00Z",
            "expires_at": "2026-06-02T00:00:00Z",  # past
            "failing_categories": ["security"],
            "reason": "deadline",
            "signature": "sig",
            "profile_hash": "aabbccdd",
        }]
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("waiver expired", reason)
        self.assertIn("01J90000000000000000000W", reason)

    def test_unexpired_waiver_allows_reuse(self) -> None:
        gate = self._gate()
        gate["waivers"] = [{
            "waiver_id": "01J90000000000000000000F",
            "operator_id": "mira",
            "issued_at": "2099-01-01T00:00:00Z",
            "expires_at": "2099-12-31T23:59:59Z",
            "failing_categories": ["security"],
            "reason": "infra dependency",
            "signature": "sig",
            "profile_hash": "aabbccdd",
        }]
        ok, _reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertTrue(ok)

    def test_no_waivers_allows_reuse(self) -> None:
        gate = self._gate()
        gate["waivers"] = []
        ok, _reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertTrue(ok)

    def test_malformed_waiver_blocks_reuse_fail_closed(self) -> None:
        gate = self._gate()
        # Missing expires_at → is_waiver_expired raises WaiverError →
        # reuse must fail-closed.
        gate["waivers"] = [{"waiver_id": "01J9MALFORMED", "reason": "bad"}]
        ok, reason = can_reuse_gate_file(
            gate,
            commit_sha="abc123",
            profile_hash="aabbccdd",
            factory_version="0.1.0",
        )
        self.assertFalse(ok)
        self.assertIn("waiver validation error", reason)


class GateMarkerLifecycleTests(unittest.TestCase):
    def test_write_creates_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_gate_marker(tmp, "gate-500", "sha123")
            self.assertTrue(path.is_file())

    def test_read_returns_marker_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_gate_marker(tmp, "gate-501", "sha456")
            marker = read_gate_marker(tmp)
            self.assertIsNotNone(marker)
            self.assertEqual(marker["gate_id"], "gate-501")
            self.assertEqual(marker["commit_sha"], "sha456")
            self.assertIn("started_at", marker)

    def test_read_returns_none_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = read_gate_marker(tmp)
            self.assertIsNone(marker)

    def test_clear_removes_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_gate_marker(tmp, "gate-502", "sha789")
            clear_gate_marker(tmp)
            self.assertIsNone(read_gate_marker(tmp))

    def test_clear_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clear_gate_marker(tmp)
            self.assertIsNone(read_gate_marker(tmp))

    def test_marker_file_location(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_gate_marker(tmp, "gate-503", "shaabc")
            self.assertEqual(path.name, "gate-in-progress.json")
            self.assertIn("gate", str(path.parent))

    def test_marker_overwrites_previous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            write_gate_marker(tmp, "gate-old", "sha-old")
            write_gate_marker(tmp, "gate-new", "sha-new")
            marker = read_gate_marker(tmp)
            self.assertEqual(marker["gate_id"], "gate-new")

    # §9.2 "corruption is loud, not silent":
    # read_gate_marker must raise GateMarkerCorruptedError when the marker
    # file exists but is unreadable / malformed JSON / not an object.

    def test_corrupted_json_marker_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_bmad" / "gate" / "gate-in-progress.json"
            path.parent.mkdir(parents=True)
            path.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(GateMarkerCorruptedError) as cm:
                read_gate_marker(tmp)
            self.assertIn("not valid JSON", str(cm.exception))

    def test_non_object_marker_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_bmad" / "gate" / "gate-in-progress.json"
            path.parent.mkdir(parents=True)
            path.write_text("[1,2,3]", encoding="utf-8")  # array, not object
            with self.assertRaises(GateMarkerCorruptedError) as cm:
                read_gate_marker(tmp)
            self.assertIn("must be a JSON object", str(cm.exception))

    def test_absent_marker_still_returns_none(self) -> None:
        # Regression: corruption-detection didn't change the absent path.
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_gate_marker(tmp))


class RoundTripDeterminismTests(unittest.TestCase):
    def test_evidence_round_trip_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = make_evidence_record(
                collector="runner", tool="pytest", tool_version="8.2.0",
                category="correctness", status="ok",
                metrics={"line_coverage": 95.5},
                findings=[], exit_code=0, duration_ms=1234,
            )
            persist_evidence_record(tmp, "rt-gate", original)
            bundle = load_evidence_bundle(tmp, "rt-gate")
            self.assertEqual(len(bundle), 1)
            self.assertEqual(bundle[0], original)

    def test_gate_file_round_trip_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = make_gate_file(
                gate_id="rt-gate-2",
                target={"kind": "story", "id": "E1.S1"},
                commit_sha="abc123",
                profile={"id": "default", "version": 1, "hash": "aabb"},
                factory_version="0.1.0",
                categories={
                    "correctness": {"verdict": "PASS", "required": {}, "actual": {}},
                    "security": {"verdict": "CONCERNS", "required": {}, "actual": {}},
                },
                overall="CONCERNS",
                evidence_bundle_hash="1234567890abcdef",
            )
            persist_gate_file(tmp, original)
            loaded = load_gate_file(tmp, "rt-gate-2")
            self.assertEqual(loaded, original)

    def test_bundle_hash_stable_across_persist_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                make_evidence_record(
                    collector="runner", tool="pytest",
                    category="correctness", status="ok",
                ),
                make_evidence_record(
                    collector="scanner", tool="semgrep",
                    category="security", status="violation",
                    findings=["CVE-2026-0001"],
                ),
            ]
            hash_before = compute_evidence_bundle_hash(records)
            for r in records:
                persist_evidence_record(tmp, "hash-gate", r)
            loaded = load_evidence_bundle(tmp, "hash-gate")
            hash_after = compute_evidence_bundle_hash(loaded)
            self.assertEqual(hash_before, hash_after)

    def test_llm_evidence_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = make_llm_evidence_record(
                collector="llm-reviewer", tool="claude",
                category="test_quality", status="ok",
                confidence=7, rationale="Good coverage patterns",
            )
            persist_evidence_record(tmp, "llm-gate", original)
            bundle = load_evidence_bundle(tmp, "llm-gate")
            self.assertEqual(len(bundle), 1)
            self.assertEqual(bundle[0]["confidence"], 7)
            self.assertEqual(bundle[0]["rationale"], "Good coverage patterns")
            self.assertFalse(bundle[0]["deterministic"])


class EvidenceToGatePipelineTests(unittest.TestCase):
    def test_full_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            records = [
                make_evidence_record(
                    collector="runner", tool="pytest",
                    category="correctness", status="ok",
                ),
                make_evidence_record(
                    collector="scanner", tool="semgrep",
                    category="security", status="ok",
                ),
                make_llm_evidence_record(
                    collector="llm-reviewer", tool="claude",
                    category="test_quality", status="ok",
                    confidence=8, rationale="Solid test design",
                ),
            ]
            for r in records:
                persist_evidence_record(tmp, "pipe-gate", r)
            bundle = load_evidence_bundle(tmp, "pipe-gate")
            bundle_hash = compute_evidence_bundle_hash(bundle)
            gate = make_gate_file(
                gate_id="pipe-gate",
                target={"kind": "story", "id": "E2.S3"},
                commit_sha="deadbeef",
                profile={"id": "msme-erp", "version": 1, "hash": "eeff0011"},
                factory_version="0.3.0",
                categories={
                    "correctness": {"verdict": "PASS"},
                    "security": {"verdict": "PASS"},
                    "test_quality": {"verdict": "PASS"},
                },
                overall="PASS",
                evidence_bundle_hash=bundle_hash,
            )
            persist_gate_file(tmp, gate)
            loaded_gate = load_gate_file(tmp, "pipe-gate")
            self.assertEqual(loaded_gate["evidence_bundle_hash"], bundle_hash)
            ok, _ = can_reuse_gate_file(
                loaded_gate,
                commit_sha="deadbeef",
                profile_hash="eeff0011",
                factory_version="0.3.0",
            )
            self.assertTrue(ok)


class EvidenceIOTrustBoundaryTests(unittest.TestCase):
    def _v1_record(self) -> dict:
        return make_evidence_record(
            collector="test-collector",
            tool="pytest",
            category="correctness",
            status="ok",
        )

    def test_persist_evidence_raises_in_child(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                with self.assertRaises(TrustBoundaryError):
                    persist_evidence_record(td, "gate-001", self._v1_record())

    def test_persist_gate_file_raises_in_child(self) -> None:
        gate = make_gate_file(
            gate_id="gate-001",
            target={"kind": "story", "id": "1.1"},
            commit_sha="abc123",
            profile={"id": "default", "version": 1, "hash": "h1"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                with self.assertRaises(TrustBoundaryError):
                    persist_gate_file(td, gate)

    def test_write_gate_marker_raises_in_child(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                with self.assertRaises(TrustBoundaryError):
                    write_gate_marker(td, "gate-001", "abc123")

    def test_clear_gate_marker_raises_in_child(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ)
            env.pop("STORY_AUTOMATOR_CHILD", None)
            with patch.dict(os.environ, env, clear=True):
                write_gate_marker(td, "gate-001", "abc123")
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                with self.assertRaises(TrustBoundaryError):
                    clear_gate_marker(td)

    def test_persist_evidence_works_on_host(self) -> None:
        env = dict(os.environ)
        env.pop("STORY_AUTOMATOR_CHILD", None)
        with patch.dict(os.environ, env, clear=True):
            with tempfile.TemporaryDirectory() as td:
                path = persist_evidence_record(td, "gate-001", self._v1_record())
                self.assertTrue(path.exists())

    def test_read_functions_work_in_child(self) -> None:
        """Read-only functions must NOT be guarded — child may read evidence."""
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ)
            env.pop("STORY_AUTOMATOR_CHILD", None)
            with patch.dict(os.environ, env, clear=True):
                persist_evidence_record(td, "gate-001", self._v1_record())
            with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
                records = load_evidence_bundle(td, "gate-001")
                self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
