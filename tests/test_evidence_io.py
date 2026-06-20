from __future__ import annotations

import unittest

from story_automator.core.gate_schema import (
    GateSchemaError,
    make_evidence_record,
)
from story_automator.core.evidence_io import (
    evidence_migrate,
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


if __name__ == "__main__":
    unittest.main()
