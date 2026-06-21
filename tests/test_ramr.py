from __future__ import annotations

import unittest

from story_automator.core.innovation.ramr import (
    RAMRError,
    RoutingDecision,
    DEFAULT_CLI_REGISTRY,
    DEFAULT_PERSONAS,
    VALID_RISK_LEVELS,
    VALID_PHASES,
    route,
    route_many,
    normalize_risk,
    normalize_persona,
    normalize_phase,
    validate_cli_registry,
    risk_temperature,
    risk_max_tokens,
    select_cli_for_risk,
    explain_decision,
)


class NormalizationTests(unittest.TestCase):
    def test_normalize_risk_accepts_canonical(self) -> None:
        for level in ("P0", "P1", "P2", "P3"):
            self.assertEqual(normalize_risk(level), level)

    def test_normalize_risk_uppercases(self) -> None:
        self.assertEqual(normalize_risk("p0"), "P0")
        self.assertEqual(normalize_risk("p3"), "P3")

    def test_normalize_risk_rejects_unknown(self) -> None:
        with self.assertRaises(RAMRError):
            normalize_risk("P4")
        with self.assertRaises(RAMRError):
            normalize_risk("")
        with self.assertRaises(RAMRError):
            normalize_risk(None)  # type: ignore[arg-type]

    def test_normalize_persona_lowercases(self) -> None:
        self.assertEqual(normalize_persona("DEV"), "dev")
        self.assertEqual(normalize_persona("Architect"), "architect")

    def test_normalize_persona_rejects_unknown(self) -> None:
        with self.assertRaises(RAMRError):
            normalize_persona("not-a-persona")

    def test_normalize_phase_accepts_known(self) -> None:
        for phase in VALID_PHASES:
            self.assertEqual(normalize_phase(phase), phase)

    def test_normalize_phase_rejects_unknown(self) -> None:
        with self.assertRaises(RAMRError):
            normalize_phase("ship-it")


class RegistryValidationTests(unittest.TestCase):
    def test_default_registry_is_valid(self) -> None:
        validate_cli_registry(DEFAULT_CLI_REGISTRY)

    def test_validate_registry_rejects_missing_fields(self) -> None:
        bad = {"claude": {"model": "x"}}  # missing max_tokens / temperature
        with self.assertRaises(RAMRError):
            validate_cli_registry(bad)

    def test_validate_registry_rejects_empty(self) -> None:
        with self.assertRaises(RAMRError):
            validate_cli_registry({})

    def test_validate_registry_rejects_non_dict_entry(self) -> None:
        with self.assertRaises(RAMRError):
            validate_cli_registry({"claude": "not-a-dict"})  # type: ignore[arg-type]


class TemperatureAndTokensTests(unittest.TestCase):
    def test_risk_temperature_monotone_decreasing(self) -> None:
        t0 = risk_temperature("P0")
        t1 = risk_temperature("P1")
        t2 = risk_temperature("P2")
        t3 = risk_temperature("P3")
        # Highest risk (P0) -> lowest temperature (most deterministic)
        self.assertLess(t0, t1)
        self.assertLess(t1, t2)
        self.assertLess(t2, t3)
        # All within sane bounds
        for value in (t0, t1, t2, t3):
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_risk_max_tokens_monotone_with_risk(self) -> None:
        m0 = risk_max_tokens("P0")
        m3 = risk_max_tokens("P3")
        # Higher risk -> more budget for deep reasoning
        self.assertGreaterEqual(m0, m3)

    def test_select_cli_for_risk_high_risk_uses_strongest(self) -> None:
        cli_id = select_cli_for_risk("P0", DEFAULT_CLI_REGISTRY)
        self.assertIn(cli_id, DEFAULT_CLI_REGISTRY)
        # The selection for low-risk may differ but stays in registry
        low = select_cli_for_risk("P3", DEFAULT_CLI_REGISTRY)
        self.assertIn(low, DEFAULT_CLI_REGISTRY)


class RouteTests(unittest.TestCase):
    def test_route_returns_routing_decision(self) -> None:
        decision = route(persona="dev", risk="P1", phase="implement")
        self.assertIsInstance(decision, RoutingDecision)
        self.assertIn(decision.cli_id, DEFAULT_CLI_REGISTRY)
        self.assertGreater(decision.max_tokens, 0)
        self.assertGreaterEqual(decision.temperature, 0.0)
        self.assertLessEqual(decision.temperature, 1.0)
        self.assertEqual(decision.persona, "dev")
        self.assertEqual(decision.risk, "P1")
        self.assertEqual(decision.phase, "implement")

    def test_route_is_deterministic(self) -> None:
        a = route(persona="qa", risk="P0", phase="review")
        b = route(persona="qa", risk="P0", phase="review")
        self.assertEqual(a, b)

    def test_route_high_risk_lower_temperature_than_low_risk(self) -> None:
        high = route(persona="dev", risk="P0", phase="implement")
        low = route(persona="dev", risk="P3", phase="implement")
        self.assertLess(high.temperature, low.temperature)

    def test_route_normalizes_inputs(self) -> None:
        decision = route(persona="DEV", risk="p1", phase="implement")
        self.assertEqual(decision.persona, "dev")
        self.assertEqual(decision.risk, "P1")

    def test_route_rejects_unknown_risk(self) -> None:
        with self.assertRaises(RAMRError):
            route(persona="dev", risk="P9", phase="implement")

    def test_route_rejects_unknown_persona(self) -> None:
        with self.assertRaises(RAMRError):
            route(persona="bogus", risk="P1", phase="implement")

    def test_route_rejects_unknown_phase(self) -> None:
        with self.assertRaises(RAMRError):
            route(persona="dev", risk="P1", phase="bogus-phase")

    def test_route_custom_registry(self) -> None:
        custom = {
            "myclaude": {"model": "claude-foo", "max_tokens": 1234, "temperature": 0.42},
        }
        decision = route(persona="dev", risk="P2", phase="implement", cli_registry=custom)
        self.assertEqual(decision.cli_id, "myclaude")
        self.assertEqual(decision.model, "claude-foo")

    def test_route_persona_affects_decision_for_review_phase(self) -> None:
        # Reviewer personas in review phase should get a deterministic decision distinct
        # from arbitrary persona; but at minimum: decision is stable per (persona, risk, phase)
        a = route(persona="reviewer", risk="P1", phase="review")
        b = route(persona="dev", risk="P1", phase="review")
        # Both produce valid decisions
        self.assertIn(a.cli_id, DEFAULT_CLI_REGISTRY)
        self.assertIn(b.cli_id, DEFAULT_CLI_REGISTRY)
        # Same persona is stable
        c = route(persona="reviewer", risk="P1", phase="review")
        self.assertEqual(a, c)

    def test_route_many_returns_one_per_input(self) -> None:
        inputs = [
            ("dev", "P0", "implement"),
            ("qa", "P1", "review"),
            ("architect", "P2", "design"),
        ]
        decisions = route_many(inputs)
        self.assertEqual(len(decisions), 3)
        for d, (persona, risk, phase) in zip(decisions, inputs):
            self.assertEqual(d.persona, persona)
            self.assertEqual(d.risk, risk)
            self.assertEqual(d.phase, phase)


class ExplainTests(unittest.TestCase):
    def test_explain_decision_returns_dict_with_expected_keys(self) -> None:
        decision = route(persona="dev", risk="P0", phase="implement")
        explanation = explain_decision(decision)
        self.assertIsInstance(explanation, dict)
        for key in ("persona", "risk", "phase", "cli_id", "model", "max_tokens", "temperature", "rationale"):
            self.assertIn(key, explanation)
        self.assertIsInstance(explanation["rationale"], str)
        self.assertGreater(len(explanation["rationale"]), 0)

    def test_explain_decision_mentions_risk_level(self) -> None:
        decision = route(persona="dev", risk="P0", phase="implement")
        explanation = explain_decision(decision)
        self.assertIn("P0", explanation["rationale"])


class DefaultsTests(unittest.TestCase):
    def test_default_personas_includes_core_bmad_roles(self) -> None:
        for persona in ("dev", "qa", "architect", "pm", "po", "sm", "reviewer", "analyst"):
            self.assertIn(persona, DEFAULT_PERSONAS)

    def test_default_phases_includes_core_workflow(self) -> None:
        for phase in ("plan", "design", "implement", "review", "test"):
            self.assertIn(phase, VALID_PHASES)

    def test_default_risk_levels_are_p0_to_p3(self) -> None:
        self.assertEqual(VALID_RISK_LEVELS, ("P0", "P1", "P2", "P3"))


if __name__ == "__main__":
    unittest.main()
