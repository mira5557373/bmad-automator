"""N5: Merkle root must be exported in the gate file.

Closes capability gap G5 — auditors must be able to externally verify
NFR claims by recomputing the Merkle root from the evidence bundle.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import (
    compute_evidence_bundle_merkle_root,
    load_evidence_bundle,
    persist_evidence_record,
)
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.gate_schema import make_evidence_record


HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _minimal_profile() -> dict:
    return {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 80, "levels": ["unit"]},
            "P1": {"coverage_pct": 60, "levels": ["unit"]},
            "P2": {"coverage_pct": 40, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": ["correctness"], "system": []},
    }


class GateMerkleExportTests(unittest.TestCase):
    """N5: run_production_gate must export evidence_merkle_root."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.profile = _minimal_profile()
        self.registry = CollectorRegistry()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _persist_evidence(self, gate_id: str, records: list[dict]) -> None:
        for record in records:
            persist_evidence_record(self.project_root, gate_id, record)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_gate_file_contains_evidence_merkle_root(
        self, mock_run: MagicMock,
    ) -> None:
        """Gate file must have a top-level evidence_merkle_root key."""
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        self._persist_evidence("gate-n5-a", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-n5-a",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertIn("evidence_merkle_root", gate)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_evidence_merkle_root_is_sha256_hex_string(
        self, mock_run: MagicMock,
    ) -> None:
        """Value must be a 64-char lowercase hex string for non-empty bundle."""
        evidence = [
            make_evidence_record(
                collector="c1", tool="t1", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ),
            make_evidence_record(
                collector="c2", tool="t2", category="correctness",
                status="ok", metrics={"coverage_pct": 90, "regressions": 0},
            ),
        ]
        self._persist_evidence("gate-n5-b", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-n5-b",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        root = gate["evidence_merkle_root"]
        self.assertIsInstance(root, str)
        self.assertRegex(root, HEX64)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_recomputing_root_from_bundle_matches_gate_file(
        self, mock_run: MagicMock,
    ) -> None:
        """Auditor workflow: recompute root from disk-persisted bundle and verify."""
        evidence = [
            make_evidence_record(
                collector="c1", tool="t1", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ),
            make_evidence_record(
                collector="c2", tool="t2", category="correctness",
                status="ok", metrics={"coverage_pct": 88, "regressions": 0},
            ),
            make_evidence_record(
                collector="c3", tool="t3", category="correctness",
                status="ok", metrics={"coverage_pct": 82, "regressions": 0},
            ),
        ]
        self._persist_evidence("gate-n5-c", evidence)
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-n5-c",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )

        # Auditor's check: reload evidence, recompute, compare.
        bundle = load_evidence_bundle(self.project_root, "gate-n5-c")
        expected = compute_evidence_bundle_merkle_root(bundle)
        self.assertEqual(gate["evidence_merkle_root"], expected)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_empty_bundle_returns_empty_string_sentinel(
        self, mock_run: MagicMock,
    ) -> None:
        """No evidence persisted → evidence_merkle_root must be empty-string sentinel.

        Auditors can distinguish "no evidence to verify" from a real
        64-hex root by checking ``root == ""`` instead of catching errors.
        """
        # No _persist_evidence call → empty bundle.
        mock_run.return_value = []
        gate = run_production_gate(
            self.project_root, "gate-n5-empty",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=self.profile,
            factory_version="1.15.0",
            registry=self.registry,
        )
        self.assertIn("evidence_merkle_root", gate)
        self.assertEqual(gate["evidence_merkle_root"], "")


if __name__ == "__main__":
    unittest.main()
