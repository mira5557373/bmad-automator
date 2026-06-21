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

from io import StringIO
from pathlib import Path

from story_automator.commands.gate_cmd import gate_dispatch
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record, persist_gate_file
from story_automator.core.gate_orchestrator import recover_from_crash, route_gate_verdict, run_production_gate
from story_automator.core.gate_ops import (
    apply_remediation,
    enrich_route_with_runbook,
    gate_doctor,
    gate_summary,
    list_verdicts,
)
from story_automator.core.gate_schema import make_evidence_record, make_gate_file
from story_automator.core.gate_status import park_story

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


class RemediationWriteBackIntegrationTests(unittest.TestCase):
    """FAIL -> route -> apply_remediation -> story file updated."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.story_path = Path(self.tmp) / "E1-001.md"
        self.story_path.write_text(
            "---\nStatus: in-progress\n---\n\n## Tasks\n- [ ] Original task\n",
            encoding="utf-8",
        )

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_fail_remediate_writes_to_story(self, mock_run: MagicMock) -> None:
        evidence = [make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="error", findings=["test failure"],
        )]
        persist_evidence_record(self.tmp, "rem-1", evidence[0])
        mock_run.return_value = []
        gate = run_production_gate(
            self.tmp, "rem-1", commit_sha="abc",
            target={"kind": "story", "id": "E1-001"},
            profile=PROFILE, factory_version="1.15.0",
            registry=CollectorRegistry(),
        )
        self.assertEqual(gate["overall"], "FAIL")
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
        )
        self.assertEqual(route["action"], "remediate")
        result = apply_remediation(self.story_path, route)
        self.assertTrue(result["applied"])
        self.assertGreaterEqual(result["tasks_written"], 1)
        content = self.story_path.read_text(encoding="utf-8")
        self.assertIn("[AI-Review]", content)
        self.assertIn("Original task", content)


class ParkRerunCLIIntegrationTests(unittest.TestCase):
    """Park -> rerun CLI -> clean state."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_park_then_rerun(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        gate = make_gate_file(
            gate_id="g-rerun",
            target={"kind": "story", "id": "rerun-target"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "r"}},
            overall="FAIL",
        )
        persist_gate_file(self.tmp, gate)
        park_story(self.tmp, "g-rerun", "rerun-target", "exhausted", "FAIL")
        with patch("sys.stdout", new_callable=StringIO) as out:
            code = gate_dispatch(["rerun", "rerun-target"])
        output = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(output["invalidated_count"], 1)
        self.assertEqual(output["resumed_count"], 1)
        verdicts_dir = Path(self.tmp) / "_bmad" / "gate" / "verdicts"
        active = [p for p in verdicts_dir.glob("*.json") if not p.name.endswith(".invalidated.json")]
        self.assertEqual(len(active), 0)


class DoctorAfterCrashIntegrationTests(unittest.TestCase):
    """Crash -> recover -> doctor reports healthy."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_doctor_healthy_after_crash_recovery(self) -> None:
        from story_automator.core.evidence_io import write_gate_marker
        write_gate_marker(self.tmp, "crash-doc", "abc")
        evidence_dir = Path(self.tmp) / "_bmad" / "gate" / "evidence" / "crash-doc"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "partial.json").write_text("{}")
        self.assertFalse(gate_doctor(self.tmp)["healthy"])
        recover_from_crash(self.tmp)
        self.assertTrue(gate_doctor(self.tmp)["healthy"])


class SummaryAccuracyIntegrationTests(unittest.TestCase):
    """Summary metrics match actual verdicts."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_summary_matches_verdicts(self) -> None:
        for gid, verdict in [("g1", "PASS"), ("g2", "PASS"), ("g3", "FAIL"), ("g4", "CONCERNS")]:
            gate = make_gate_file(
                gate_id=gid,
                target={"kind": "story", "id": f"s-{gid}"},
                commit_sha="abc",
                profile={"id": "test", "version": 1, "hash": "aabb"},
                factory_version="1.15.0",
                categories={"c": {"verdict": verdict, "required": {}, "actual": {}, "rationale": "ok"}},
                overall=verdict,
            )
            persist_gate_file(self.tmp, gate)
        summary = gate_summary(self.tmp)
        self.assertEqual(summary["total_verdicts"], 4)
        self.assertEqual(summary["by_verdict"]["PASS"], 2)
        self.assertEqual(summary["by_verdict"]["FAIL"], 1)
        self.assertEqual(summary["by_verdict"]["CONCERNS"], 1)
        verdicts = list_verdicts(self.tmp)
        self.assertEqual(len(verdicts), summary["total_verdicts"])


class RunbookEnrichmentIntegrationTests(unittest.TestCase):
    """Route results enriched with runbook references."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def test_fail_route_enriched_with_runbook(self) -> None:
        gate = make_gate_file(
            gate_id="g-enrich",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "r"}},
            overall="FAIL",
        )
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=0, max_cycles=3,
        )
        enriched = enrich_route_with_runbook(route)
        self.assertIn("section-4", enriched["runbook_ref"])
        self.assertEqual(enriched["action"], route["action"])

    def test_park_route_enriched_with_runbook(self) -> None:
        gate = make_gate_file(
            gate_id="g-park-rb",
            target={"kind": "story", "id": "s1"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "FAIL", "required": {}, "actual": {}, "rationale": "r"}},
            overall="FAIL",
        )
        route = route_gate_verdict(
            self.tmp, gate, story_key="E1-001",
            remediation_cycle=3, max_cycles=3,
        )
        enriched = enrich_route_with_runbook(route)
        self.assertIn("section-3", enriched["runbook_ref"])


class CLINewCommandsRoundTripTests(unittest.TestCase):
    """Round-trip tests for M11 CLI commands."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    @patch("story_automator.commands.gate_cmd._project_root")
    def test_doctor_list_summary_round_trip(self, mock_root) -> None:
        mock_root.return_value = self.tmp
        gate = make_gate_file(
            gate_id="g-rt",
            target={"kind": "story", "id": "s-rt"},
            commit_sha="abc",
            profile={"id": "test", "version": 1, "hash": "aabb"},
            factory_version="1.15.0",
            categories={"c": {"verdict": "PASS", "required": {}, "actual": {}, "rationale": "ok"}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate)

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["doctor"])
        doc = json.loads(out.getvalue())
        self.assertTrue(doc["healthy"])

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["list"])
        lst = json.loads(out.getvalue())
        self.assertEqual(lst["count"], 1)

        with patch("sys.stdout", new_callable=StringIO) as out:
            gate_dispatch(["summary"])
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["total_verdicts"], 1)


if __name__ == "__main__":
    unittest.main()
