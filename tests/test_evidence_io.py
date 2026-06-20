from __future__ import annotations

import json
import tempfile
import unittest

from story_automator.core.gate_schema import (
    GateSchemaError,
    make_evidence_record,
)
from story_automator.core.evidence_io import (
    compute_evidence_bundle_hash,
    evidence_filename,
    evidence_migrate,
    persist_evidence_record,
)


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


if __name__ == "__main__":
    unittest.main()
