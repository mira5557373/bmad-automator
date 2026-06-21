from __future__ import annotations

import tempfile
import unittest

from story_automator.core.gate_orchestrator import run_readiness_gate
from story_automator.core.risk_profile import (
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


if __name__ == "__main__":
    unittest.main()
