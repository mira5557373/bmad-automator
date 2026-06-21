from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.gate_orchestrator import (
    run_epic_readiness_gate,
    run_production_gate,
    run_readiness_gate,
)
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.risk_profile import (
    has_unmitigated_risk_9,
    load_risk_profile,
    make_risk_entry,
    persist_risk_profile,
)


class RunReadinessGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
                "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
                "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
                "P3": {"coverage_pct": 20, "levels": ["smoke"]},
            },
            "categories": {"code": ["correctness"], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }

    def test_ready_with_inline_risk_entries(self) -> None:
        entries = [make_risk_entry("TECH", 2, 2)]
        result = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "READY")
        self.assertEqual(result["priority"], "P2")
        self.assertIn("risk_profile_ref", result)

    def test_ready_with_persisted_risk(self) -> None:
        entries = [make_risk_entry("SEC", 2, 3)]
        persist_risk_profile(self.tmp, "E1-001", entries)
        result = run_readiness_gate(
            self.tmp, "E1-001", profile=self.profile,
        )
        self.assertEqual(result["verdict"], "READY")
        self.assertEqual(result["priority"], "P1")

    def test_needs_risk_when_nothing_available(self) -> None:
        result = run_readiness_gate(
            self.tmp, "E1-001", profile=self.profile,
        )
        self.assertEqual(result["verdict"], "NEEDS_RISK")

    def test_blocked_by_adr(self) -> None:
        profile = dict(self.profile)
        profile["forbidden_until"] = {"ADR-1": ["E1-*"]}
        entries = [make_risk_entry("TECH", 1, 1)]
        result = run_readiness_gate(
            self.tmp, "E1-001",
            profile=profile, risk_entries=entries,
        )
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_persists_risk_entries(self) -> None:
        entries = [make_risk_entry("DATA", 2, 2)]
        run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=entries,
        )
        loaded = load_risk_profile(self.tmp, "E1-001")
        self.assertEqual(len(loaded["entries"]), 1)

    def test_persists_readiness_result(self) -> None:
        from story_automator.core.readiness_gate import load_readiness_result
        entries = [make_risk_entry("PERF", 1, 2)]
        run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=entries,
        )
        loaded = load_readiness_result(self.tmp, "E1-001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["verdict"], "READY")

    def test_priority_flows_to_requirements(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        result = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=entries,
        )
        self.assertEqual(result["priority"], "P0")
        self.assertEqual(result["requirements"]["coverage_pct"], 100)

    def test_inline_entries_override_persisted(self) -> None:
        old_entries = [make_risk_entry("TECH", 1, 1)]
        persist_risk_profile(self.tmp, "E1-001", old_entries)
        new_entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        result = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=new_entries,
        )
        self.assertEqual(result["priority"], "P0")


class RunEpicReadinessGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": []},
                "P1": {"coverage_pct": 90, "levels": []},
                "P2": {"coverage_pct": 50, "levels": []},
                "P3": {"coverage_pct": 20, "levels": []},
            },
            "categories": {"code": [], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }

    def test_epic_ready_with_risk_map(self) -> None:
        risk_map = {
            "E1-001": [make_risk_entry("TECH", 2, 2)],
            "E1-002": [make_risk_entry("OPS", 1, 1)],
        }
        result = run_epic_readiness_gate(
            self.tmp, "E1", ["E1-001", "E1-002"],
            profile=self.profile, risk_map=risk_map,
        )
        self.assertEqual(result["verdict"], "READY")
        self.assertEqual(result["epic_id"], "E1")

    def test_epic_persists_risk_entries(self) -> None:
        risk_map = {"E1-001": [make_risk_entry("TECH", 1, 1)]}
        run_epic_readiness_gate(
            self.tmp, "E1", ["E1-001"],
            profile=self.profile, risk_map=risk_map,
        )
        loaded = load_risk_profile(self.tmp, "E1-001")
        self.assertEqual(len(loaded["entries"]), 1)

    def test_epic_persists_readiness_result(self) -> None:
        from story_automator.core.readiness_gate import load_readiness_result
        risk_map = {"E1-001": [make_risk_entry("TECH", 1, 1)]}
        run_epic_readiness_gate(
            self.tmp, "E1", ["E1-001"],
            profile=self.profile, risk_map=risk_map,
        )
        loaded = load_readiness_result(self.tmp, "E1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["verdict"], "READY")

    def test_epic_needs_risk_when_no_entries(self) -> None:
        result = run_epic_readiness_gate(
            self.tmp, "E1", ["E1-001"],
            profile=self.profile,
        )
        self.assertEqual(result["verdict"], "NEEDS_RISK")

    def test_epic_blocked(self) -> None:
        profile = dict(self.profile)
        profile["forbidden_until"] = {"ADR-1": ["E1-*"]}
        risk_map = {"E1-001": [make_risk_entry("TECH", 1, 1)]}
        result = run_epic_readiness_gate(
            self.tmp, "E1", ["E1-001"],
            profile=profile, risk_map=risk_map,
        )
        self.assertEqual(result["verdict"], "BLOCKED")


class ReadinessToProductionGateBridgeTests(unittest.TestCase):
    """Verify readiness priority flows into production gate."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.profile = {
            "id": "test", "version": 1,
            "matrix": {
                "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
                "P1": {"coverage_pct": 90, "levels": ["unit", "integration", "api"]},
                "P2": {"coverage_pct": 50, "levels": ["unit", "api_happy_path"]},
                "P3": {"coverage_pct": 20, "levels": ["smoke"]},
            },
            "categories": {"code": ["correctness"], "system": []},
            "categories_na": [],
            "forbidden_until": {},
        }
        self.registry = CollectorRegistry()

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_p0_readiness_drives_100pct_coverage(self, mock_run: MagicMock) -> None:
        risk_entries = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        readiness = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=risk_entries,
        )
        self.assertEqual(readiness["priority"], "P0")

        evidence = make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 95, "regressions": 0},
        )
        persist_evidence_record(self.tmp, "gate-1", evidence)
        mock_run.return_value = []

        gate = run_production_gate(
            self.tmp, "gate-1",
            commit_sha="abc", target={"kind": "story", "id": "E1-001"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry, priority=readiness["priority"],
        )
        self.assertEqual(gate["overall"], "FAIL")
        correctness = gate["categories"]["correctness"]
        self.assertEqual(correctness["verdict"], "FAIL")
        self.assertIn("coverage", correctness.get("rationale", ""))

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_p3_readiness_allows_20pct_coverage(self, mock_run: MagicMock) -> None:
        risk_entries = [make_risk_entry("OPS", 1, 1)]
        readiness = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=risk_entries,
        )
        self.assertEqual(readiness["priority"], "P3")

        evidence = make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 25, "regressions": 0},
        )
        persist_evidence_record(self.tmp, "gate-2", evidence)
        mock_run.return_value = []

        gate = run_production_gate(
            self.tmp, "gate-2",
            commit_sha="abc", target={"kind": "story", "id": "E1-001"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry, priority=readiness["priority"],
        )
        self.assertEqual(gate["overall"], "PASS")

    def test_unmitigated_risk_9_detection(self) -> None:
        entries = [make_risk_entry("SEC", 3, 3)]
        self.assertTrue(has_unmitigated_risk_9(entries))

        entries_mitigated = [make_risk_entry("SEC", 3, 3, rationale="mitigated")]
        self.assertFalse(has_unmitigated_risk_9(entries_mitigated))

    @patch("story_automator.core.gate_orchestrator._run_collectors")
    def test_unmitigated_risk_9_causes_production_gate_fail(self, mock_run: MagicMock) -> None:
        risk_entries = [make_risk_entry("SEC", 3, 3)]
        readiness = run_readiness_gate(
            self.tmp, "E1-001",
            profile=self.profile, risk_entries=risk_entries,
        )
        self.assertTrue(readiness["risk_summary"]["unmitigated_risk_9"])

        evidence = make_evidence_record(
            collector="c", tool="t", category="correctness",
            status="ok", metrics={"coverage_pct": 100, "regressions": 0},
        )
        persist_evidence_record(self.tmp, "gate-3", evidence)
        mock_run.return_value = []

        gate = run_production_gate(
            self.tmp, "gate-3",
            commit_sha="abc", target={"kind": "story", "id": "E1-001"},
            profile=self.profile, factory_version="1.15.0",
            registry=self.registry, priority="P0",
            has_unmitigated_risk_9=True,
        )
        self.assertEqual(gate["overall"], "FAIL")


if __name__ == "__main__":
    unittest.main()
