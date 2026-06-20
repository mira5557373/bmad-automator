from __future__ import annotations

import tempfile
import unittest

from story_automator.core.gate_schema import (
    EVIDENCE_SCHEMA_VERSION,
    GATE_ARTIFACT_SUBDIRS,
    GATE_SCHEMA_VERSION,
    MAX_WAIVER_TTL_DAYS,
    VALID_EVIDENCE_STATUSES,
    VALID_GATE_VERDICTS,
    VALID_INVARIANT_CHECK_TYPES,
    VALID_INVARIANT_SEVERITIES,
    GateSchemaError,
    canonical_json,
    compute_waiver_signature,
    gate_artifact_dir,
    make_evidence_record,
    make_gate_file,
    make_timeout_evidence,
    make_waiver,
    validate_evidence_record,
    validate_gate_file,
    validate_invariant_entry,
    validate_waiver,
)


class ConstantsTests(unittest.TestCase):
    def test_schema_versions_are_positive(self) -> None:
        self.assertGreater(EVIDENCE_SCHEMA_VERSION, 0)
        self.assertGreater(GATE_SCHEMA_VERSION, 0)

    def test_max_waiver_ttl_is_30_days(self) -> None:
        self.assertEqual(MAX_WAIVER_TTL_DAYS, 30)

    def test_valid_evidence_statuses(self) -> None:
        self.assertEqual(
            VALID_EVIDENCE_STATUSES,
            frozenset({"ok", "violation", "error", "timeout"}),
        )

    def test_valid_gate_verdicts(self) -> None:
        self.assertIn("PASS", VALID_GATE_VERDICTS)
        self.assertIn("WAIVED", VALID_GATE_VERDICTS)

    def test_invariant_check_types(self) -> None:
        for ct in ("semgrep", "conftest", "presence", "human"):
            self.assertIn(ct, VALID_INVARIANT_CHECK_TYPES)

    def test_invariant_severities(self) -> None:
        self.assertEqual(VALID_INVARIANT_SEVERITIES, frozenset({"FAIL", "CONCERNS"}))

    def test_gate_artifact_subdirs(self) -> None:
        self.assertEqual(set(GATE_ARTIFACT_SUBDIRS), {"risk", "evidence", "verdicts"})


class CanonicalJsonTests(unittest.TestCase):
    def test_deterministic_output(self) -> None:
        obj = {"b": 2, "a": 1}
        self.assertEqual(canonical_json(obj), '{"a":1,"b":2}')

    def test_no_whitespace(self) -> None:
        self.assertNotIn(" ", canonical_json({"key": "value"}))


class WaiverSignatureTests(unittest.TestCase):
    def test_signature_is_deterministic(self) -> None:
        fields = {"waiver_id": "abc", "operator_id": "op1", "reason": "test"}
        sig1 = compute_waiver_signature(fields)
        sig2 = compute_waiver_signature(fields)
        self.assertEqual(sig1, sig2)

    def test_signature_is_16_char_hex(self) -> None:
        sig = compute_waiver_signature({"waiver_id": "x"})
        self.assertEqual(len(sig), 16)
        int(sig, 16)

    def test_signature_field_excluded(self) -> None:
        base = {"waiver_id": "x", "reason": "test"}
        with_sig = {**base, "signature": "will_be_ignored"}
        self.assertEqual(
            compute_waiver_signature(base),
            compute_waiver_signature(with_sig),
        )


class GateArtifactDirTests(unittest.TestCase):
    def test_creates_valid_subdirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for subdir in GATE_ARTIFACT_SUBDIRS:
                path = gate_artifact_dir(tmp, subdir)
                self.assertTrue(path.is_dir())
                self.assertIn(subdir, str(path))

    def test_invalid_subdir_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(GateSchemaError, "invalid gate artifact subdir"):
                gate_artifact_dir(tmp, "bogus")


class MakeEvidenceRecordTests(unittest.TestCase):
    def test_creates_valid_record(self) -> None:
        record = make_evidence_record(
            collector="test-collector",
            tool="pytest",
            category="correctness",
            status="ok",
        )
        self.assertEqual(record["schema_version"], EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(record["collector"], "test-collector")
        self.assertEqual(record["status"], "ok")
        self.assertIsInstance(record["findings"], list)

    def test_invalid_status_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "evidence.status"):
            make_evidence_record(
                collector="x", tool="x", category="x", status="bogus",
            )


class MakeTimeoutEvidenceTests(unittest.TestCase):
    def test_creates_timeout_record(self) -> None:
        record = make_timeout_evidence("coll", "semgrep", "security", 300)
        self.assertEqual(record["status"], "timeout")
        self.assertEqual(record["findings"], ["TIMEOUT: semgrep exceeded 300s"])
        self.assertEqual(record["exit_code"], -1)

    def test_schema_version_set(self) -> None:
        record = make_timeout_evidence("c", "t", "security", 60)
        self.assertEqual(record["schema_version"], EVIDENCE_SCHEMA_VERSION)


class MakeGateFileTests(unittest.TestCase):
    def test_creates_valid_gate_file(self) -> None:
        gate = make_gate_file(
            gate_id="01234567-abcd-7000-8000-000000000001",
            target={"kind": "story", "id": "E1.S1"},
            commit_sha="abc123",
            profile={"id": "default", "version": 1, "hash": "aabbccdd"},
            factory_version="0.1.0",
            categories={"correctness": {"verdict": "PASS"}},
            overall="PASS",
        )
        self.assertEqual(gate["schema_version"], GATE_SCHEMA_VERSION)
        self.assertEqual(gate["overall"], "PASS")
        self.assertEqual(gate["waivers"], [])

    def test_invalid_overall_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "gate.overall"):
            make_gate_file(
                gate_id="x", target={"kind": "story"}, commit_sha="abc",
                profile={"id": "x"}, factory_version="0.1",
                categories={}, overall="INVALID",
            )


class MakeWaiverTests(unittest.TestCase):
    def test_creates_signed_waiver(self) -> None:
        waiver = make_waiver(
            waiver_id="01234567-abcd-7000-8000-000000000002",
            operator_id="alice",
            issued_at="2026-06-20T00:00:00Z",
            expires_at="2026-07-01T00:00:00Z",
            failing_categories=["security"],
            reason="false positive",
            profile_hash="aabbccdd",
        )
        self.assertIn("signature", waiver)
        self.assertEqual(len(waiver["signature"]), 16)
        expected = compute_waiver_signature(waiver)
        self.assertEqual(waiver["signature"], expected)


class ValidateEvidenceRecordTests(unittest.TestCase):
    def _valid_record(self) -> dict:
        return {
            "schema_version": 1,
            "collector": "test",
            "tool": "pytest",
            "category": "correctness",
            "status": "ok",
            "findings": [],
            "metrics": {},
            "deterministic": True,
        }

    def test_valid_record_passes(self) -> None:
        validate_evidence_record(self._valid_record())

    def test_missing_collector_raises(self) -> None:
        record = self._valid_record()
        record["collector"] = ""
        with self.assertRaisesRegex(GateSchemaError, "evidence.collector"):
            validate_evidence_record(record)

    def test_invalid_status_raises(self) -> None:
        record = self._valid_record()
        record["status"] = "bogus"
        with self.assertRaisesRegex(GateSchemaError, "evidence.status"):
            validate_evidence_record(record)

    def test_findings_must_be_list(self) -> None:
        record = self._valid_record()
        record["findings"] = "not a list"
        with self.assertRaisesRegex(GateSchemaError, "evidence.findings"):
            validate_evidence_record(record)


class ValidateGateFileTests(unittest.TestCase):
    def _valid_gate(self) -> dict:
        return {
            "gate_id": "abc",
            "schema_version": 1,
            "target": {"kind": "story"},
            "commit_sha": "abc123",
            "profile": {"id": "x"},
            "factory_version": "0.1",
            "categories": {},
            "overall": "PASS",
            "waivers": [],
        }

    def test_valid_gate_passes(self) -> None:
        validate_gate_file(self._valid_gate())

    def test_missing_gate_id_raises(self) -> None:
        gate = self._valid_gate()
        gate["gate_id"] = ""
        with self.assertRaisesRegex(GateSchemaError, "gate.gate_id"):
            validate_gate_file(gate)


class ValidateWaiverTests(unittest.TestCase):
    def _valid_waiver(self) -> dict:
        return {
            "waiver_id": "abc",
            "operator_id": "alice",
            "issued_at": "2026-06-20T00:00:00Z",
            "expires_at": "2026-07-01T00:00:00Z",
            "failing_categories": ["security"],
            "reason": "false positive",
            "signature": "deadbeef12345678",
            "profile_hash": "aabbccdd",
        }

    def test_valid_waiver_passes(self) -> None:
        validate_waiver(self._valid_waiver())

    def test_empty_categories_raises(self) -> None:
        waiver = self._valid_waiver()
        waiver["failing_categories"] = []
        with self.assertRaisesRegex(GateSchemaError, "waiver.failing_categories"):
            validate_waiver(waiver)

    def test_missing_signature_raises(self) -> None:
        waiver = self._valid_waiver()
        waiver["signature"] = ""
        with self.assertRaisesRegex(GateSchemaError, "waiver.signature"):
            validate_waiver(waiver)


class ValidateInvariantEntryTests(unittest.TestCase):
    def test_valid_checkable_entry(self) -> None:
        validate_invariant_entry({
            "id": "DG-12",
            "checkable": "yes",
            "check_type": "semgrep",
            "rule_file": "semgrep/dg12.yml",
            "severity": "FAIL",
        })

    def test_valid_non_checkable_entry(self) -> None:
        validate_invariant_entry({
            "id": "DG-99",
            "checkable": "no",
            "severity": "CONCERNS",
        })

    def test_invalid_check_type_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "invariant.check_type"):
            validate_invariant_entry({
                "id": "DG-12",
                "checkable": "yes",
                "check_type": "invalid",
                "rule_file": "x.yml",
                "severity": "FAIL",
            })

    def test_invalid_severity_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "invariant.severity"):
            validate_invariant_entry({
                "id": "DG-12",
                "checkable": "yes",
                "check_type": "semgrep",
                "rule_file": "x.yml",
                "severity": "WARN",
            })

    def test_missing_id_raises(self) -> None:
        with self.assertRaisesRegex(GateSchemaError, "invariant.id"):
            validate_invariant_entry({
                "id": "",
                "checkable": "yes",
                "check_type": "semgrep",
                "rule_file": "x.yml",
                "severity": "FAIL",
            })


if __name__ == "__main__":
    unittest.main()
