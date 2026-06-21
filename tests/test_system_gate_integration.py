"""End-to-end integration tests for system-altitude gate."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.evidence_io import persist_evidence_record
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.gate_status import list_parked
from story_automator.core.system_collector_registry import build_system_registry
from story_automator.core.system_env import SystemEnvInfo, ENV_TIER_MINIMAL, ENV_TIER_FULL
from story_automator.core.system_gate import (
    run_system_gate,
    route_epic_verdict,
)


def _test_profile() -> dict:
    return {
        "version": 1, "id": "test-system",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {
            "code": [],
            "system": ["reliability", "resilience", "cost_to_serve"],
        },
        "rules": {
            "reliability": {"max_rto_seconds": 300, "max_rpo_seconds": 60},
        },
        "cost_tier": {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0},
        "forbidden_until": {"DG-2": ["*.cost-to-serve"]},
    }


class SystemGateIntegrationTests(unittest.TestCase):
    """Integration tests covering the full system gate lifecycle."""

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    def test_system_gate_pass_lifecycle(
        self, mock_collectors: MagicMock, mock_env: MagicMock,
    ) -> None:
        """System gate PASS -> route -> done."""
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            persist_evidence_record(td, "sg-int-1", make_evidence_record(
                collector="test-reliability", tool="test", category="reliability",
                tier="system", status="ok",
                metrics={"rto_seconds": 10, "rpo_seconds": 5},
            ))
            persist_evidence_record(td, "sg-int-1", make_evidence_record(
                collector="test-resilience", tool="test", category="resilience",
                tier="system", status="ok",
                metrics={"scenarios_total": 3, "scenarios_passed": 3},
            ))
            persist_evidence_record(td, "sg-int-1", make_evidence_record(
                collector="test-cost", tool="test", category="cost_to_serve",
                tier="system", status="ok",
                metrics={"pod_cost_per_tenant": 1.0},
            ))
            mock_collectors.return_value = []

            gate_file = run_system_gate(
                td, "sg-int-1", epic_id="E1", commit_sha="abc123",
                epic_metadata={"type": "feature"},
                profile=_test_profile(),
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
            # cost_to_serve has DG-2 in forbidden_until -> CONCERNS
            self.assertEqual(gate_file["overall"], "CONCERNS")

            result = route_epic_verdict(
                td, gate_file, epic_id="E1", story_keys=["E1-001"],
            )
            self.assertEqual(result["action"], "done")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    def test_system_gate_fail_reopens_stories(
        self, mock_collectors: MagicMock, mock_env: MagicMock,
    ) -> None:
        """System gate FAIL -> route -> reopen stories."""
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_FULL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            persist_evidence_record(td, "sg-int-2", make_evidence_record(
                collector="test-reliability", tool="test", category="reliability",
                tier="system", status="ok",
            ))
            persist_evidence_record(td, "sg-int-2", make_evidence_record(
                collector="test-resilience", tool="test", category="resilience",
                tier="system", status="violation",
                findings=["pod-kill scenario failed"],
            ))
            mock_collectors.return_value = []

            profile = _test_profile()
            del profile["forbidden_until"]
            del profile["cost_tier"]
            gate_file = run_system_gate(
                td, "sg-int-2", epic_id="E2", commit_sha="def456",
                epic_metadata={"type": "infra"},
                profile=profile,
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
            self.assertEqual(gate_file["overall"], "FAIL")

            result = route_epic_verdict(
                td, gate_file, epic_id="E2",
                story_keys=["E2-001", "E2-002", "E2-003"],
            )
            self.assertEqual(result["action"], "reopen")
            self.assertEqual(result["stories_to_reopen"], ["E2-001", "E2-002", "E2-003"])

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    def test_cost_to_serve_concerns_with_dg2(self) -> None:
        """cost_to_serve renders CONCERNS while DG-2 in forbidden_until."""
        profile = _test_profile()
        from story_automator.core.category_rules import cost_to_serve_rule

        evidence = [make_evidence_record(
            collector="k6-cost", tool="k6", category="cost_to_serve",
            tier="system", status="ok",
            metrics={"pod_cost_per_tenant": 5.0},
        )]
        result = cost_to_serve_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "CONCERNS")

    @patch.dict(os.environ, {"_STORY_AUTOMATOR_HOST": "1"}, clear=False)
    @patch("story_automator.core.system_gate.system_env")
    @patch("story_automator.core.system_gate.run_gate_collectors")
    def test_exhausted_parks_epic(
        self, mock_collectors: MagicMock, mock_env: MagicMock,
    ) -> None:
        """Exhausted remediation cycles -> park epic."""
        env_info = SystemEnvInfo(env_id="e1", tier=ENV_TIER_MINIMAL, namespace="ns")
        mock_env.return_value.__enter__ = MagicMock(return_value=env_info)
        mock_env.return_value.__exit__ = MagicMock(return_value=False)

        with tempfile.TemporaryDirectory() as td:
            persist_evidence_record(td, "sg-int-3", make_evidence_record(
                collector="test-resilience", tool="test", category="resilience",
                tier="system", status="violation",
            ))
            mock_collectors.return_value = []

            profile = _test_profile()
            profile["categories"]["system"] = ["resilience"]
            del profile["forbidden_until"]
            del profile["cost_tier"]
            gate_file = run_system_gate(
                td, "sg-int-3", epic_id="E3", commit_sha="ghi789",
                epic_metadata={},
                profile=profile,
                factory_version="1.0.0",
                registry=CollectorRegistry(),
            )
            result = route_epic_verdict(
                td, gate_file, epic_id="E3",
                story_keys=["E3-001"],
                remediation_cycle=3, max_cycles=3,
            )
            self.assertEqual(result["action"], "park")
            parked = list_parked(td)
            self.assertEqual(len(parked), 1)

    def test_system_registry_has_expected_categories(self) -> None:
        """Verify all HR6 system categories are covered by registry."""
        registry = build_system_registry()
        cats = registry.all_categories()
        for expected in ("reliability", "resilience", "durable_hitl", "blast_radius", "cost_to_serve"):
            self.assertIn(expected, cats, f"missing system category: {expected}")


if __name__ == "__main__":
    unittest.main()
