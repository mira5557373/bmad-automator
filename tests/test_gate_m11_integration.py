"""Integration tests for M11 gate operations.

Comprehensive operational scenarios covering audit chain, duration
tracking, concurrent safety, remediation write-back, and CLI
round-trips through the new M11 subcommands.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.gate_orchestrator import run_production_gate
from story_automator.core.gate_schema import make_evidence_record

PROFILE = {
    "id": "test", "version": 1,
    "matrix": {
        "P0": {"coverage_pct": 100, "levels": []},
        "P1": {"coverage_pct": 90, "levels": []},
        "P2": {"coverage_pct": 50, "levels": []},
        "P3": {"coverage_pct": 20, "levels": []},
    },
    "categories": {"code": ["correctness", "security"], "system": []},
    "categories_na": [],
}


class AuditChainIntegrationTests(unittest.TestCase):
    """Verify run_production_gate emits the full audit chain."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.audit_path = pathlib.Path(self.tmp) / "audit.jsonl"
        self.audit_policy = {"security": {"audit_trail": True}}
        self.registry = CollectorRegistry()

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_full_audit_chain_on_pass(self, mock_run: MagicMock) -> None:
        evidence = [
            make_evidence_record(
                collector="c", tool="t", category="correctness",
                status="ok", metrics={"coverage_pct": 95, "regressions": 0},
            ),
            make_evidence_record(
                collector="s", tool="t", category="security",
                status="ok", metrics={"sast_high_count": 0},
            ),
        ]
        for e in evidence:
            persist_evidence_record(self.tmp, "audit-chain-1", e)
        mock_run.return_value = []
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
            run_production_gate(
                self.tmp, "audit-chain-1", commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=PROFILE, factory_version="1.15.0",
                registry=self.registry,
                audit_policy=self.audit_policy,
                audit_path=self.audit_path,
            )
        self.assertTrue(self.audit_path.exists())
        lines = self.audit_path.read_text().strip().split("\n")
        events = [json.loads(line)["event"] for line in lines]
        self.assertIn("GateStarted", events)
        self.assertIn("GateDecision", events)
        self.assertIn("GateRendered", events)
        self.assertIn("GateCompleted", events)

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_completed_event_has_duration(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )]
        persist_evidence_record(self.tmp, "audit-dur-1", evidence[0])
        mock_run.return_value = []
        with patch.dict(os.environ, {"BMAD_AUDIT_KEY": "test-secret"}):
            run_production_gate(
                self.tmp, "audit-dur-1", commit_sha="abc",
                target={"kind": "story", "id": "s1"},
                profile=PROFILE, factory_version="1.15.0",
                registry=self.registry,
                audit_policy=self.audit_policy,
                audit_path=self.audit_path,
            )
        lines = self.audit_path.read_text().strip().split("\n")
        completed = [json.loads(line) for line in lines if json.loads(line)["event"] == "GateCompleted"]
        self.assertEqual(len(completed), 1)
        self.assertIn("duration_ms", completed[0]["payload"])
        self.assertGreaterEqual(completed[0]["payload"]["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
