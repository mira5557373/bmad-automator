"""Tests for system-altitude category rule functions."""
from __future__ import annotations

import unittest

from story_automator.core.category_rules import (
    apply_category_rule,
    reliability_rule,
    resilience_rule,
    blast_radius_rule,
    durable_hitl_rule,
)


def _sys_profile(**rule_overrides: object) -> dict:
    """Minimal profile with system rules."""
    return {
        "version": 1,
        "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["unit"]},
        },
        "categories": {"code": [], "system": [
            "reliability", "resilience", "blast_radius", "durable_hitl",
        ]},
        "rules": {
            "reliability": {"max_rto_seconds": 300, "max_rpo_seconds": 60, **rule_overrides},
        },
    }


def _evidence(category: str, status: str = "ok", **metrics: object) -> dict:
    return {
        "schema_version": 1,
        "collector": f"test-{category}",
        "tool": "test-tool",
        "tool_version": "",
        "category": category,
        "tier": "system",
        "status": status,
        "metrics": dict(metrics),
        "findings": [],
        "raw_output_ref": "",
        "exit_code": 0,
        "duration_ms": 100,
        "deterministic": True,
    }


class ReliabilityRuleTests(unittest.TestCase):
    def test_pass_within_limits(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", rto_seconds=120, rpo_seconds=30)]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_rto_exceeded(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", rto_seconds=600, rpo_seconds=30)]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("rto", result["rationale"].lower())

    def test_fail_rpo_exceeded(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", rto_seconds=120, rpo_seconds=120)]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_fail_closed_on_error(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", status="error")]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_fail_closed_on_timeout(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", status="timeout")]
        result = reliability_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_dispatch_via_apply(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("reliability", rto_seconds=120, rpo_seconds=30)]
        result = apply_category_rule("reliability", evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")


class ResilienceRuleTests(unittest.TestCase):
    def test_pass_all_scenarios(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("resilience", scenarios_total=3, scenarios_passed=3)]
        result = resilience_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_scenario_failed(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("resilience", scenarios_total=3, scenarios_passed=2)]
        result = resilience_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("scenario", result["rationale"].lower())

    def test_fail_zero_scenarios(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("resilience", scenarios_total=0, scenarios_passed=0)]
        result = resilience_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("no resilience scenarios", result["rationale"])

    def test_fail_closed_on_error(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("resilience", status="timeout")]
        result = resilience_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")


class BlastRadiusRuleTests(unittest.TestCase):
    def test_pass_no_breach(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("blast_radius", slo_breached=False)]
        result = blast_radius_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_slo_breached(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("blast_radius", slo_breached=True)]
        result = blast_radius_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("slo", result["rationale"].lower())


class DurableHitlRuleTests(unittest.TestCase):
    def test_pass_signal_survived(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("durable_hitl", signal_survived=True)]
        result = durable_hitl_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_fail_signal_lost(self) -> None:
        profile = _sys_profile()
        evidence = [_evidence("durable_hitl", signal_survived=False)]
        result = durable_hitl_rule(evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("signal", result["rationale"].lower())


if __name__ == "__main__":
    unittest.main()
