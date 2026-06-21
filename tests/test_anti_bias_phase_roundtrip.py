"""M55 — anti-bias phase roundtrip tests.

Enforces the RAMR independent-model constraint: ``dev-verify`` MUST use a
different ``(cli_id, model)`` tuple than ``dev-running``. Auto-FAIL on
violation; the gate must reject identical pairs and accept any divergence
in either dimension.
"""

from __future__ import annotations

import unittest

from story_automator.core.phase_bridge import (
    AntiBiasViolation,
    PhaseAssignment,
    Phase,
    check_anti_bias_roundtrip,
    enforce_independent_models,
    verdict_for_assignments,
)


class AntiBiasPhaseRoundtripTests(unittest.TestCase):
    """RAMR independent-model constraint between dev-running and dev-verify."""

    def test_identical_cli_and_model_is_violation(self) -> None:
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="claude", model="opus-4")
        with self.assertRaises(AntiBiasViolation) as ctx:
            enforce_independent_models(running, verify)
        self.assertIn("dev-verify", str(ctx.exception))
        self.assertIn("dev-running", str(ctx.exception))

    def test_different_cli_same_model_is_ok(self) -> None:
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="codex", model="opus-4")
        # Diverging on cli_id alone satisfies RAMR independence.
        enforce_independent_models(running, verify)

    def test_same_cli_different_model_is_ok(self) -> None:
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="claude", model="sonnet-3")
        # Diverging on model alone satisfies RAMR independence.
        enforce_independent_models(running, verify)

    def test_check_returns_violation_dict_on_match(self) -> None:
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="claude", model="opus-4")
        result = check_anti_bias_roundtrip(running, verify)
        self.assertFalse(result["ok"])
        self.assertEqual(result["violation"], "ramr_same_cli_and_model")
        self.assertEqual(result["running"], {"cli_id": "claude", "model": "opus-4"})
        self.assertEqual(result["verify"], {"cli_id": "claude", "model": "opus-4"})

    def test_check_returns_ok_on_independence(self) -> None:
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="codex", model="gpt-5")
        result = check_anti_bias_roundtrip(running, verify)
        self.assertTrue(result["ok"])
        self.assertNotIn("violation", result)

    def test_verdict_is_fail_for_same_pair(self) -> None:
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="claude", model="opus-4")
        verdict = verdict_for_assignments(running, verify)
        # Auto-FAIL — the gate rejects identical pairs.
        self.assertEqual(verdict, "fail")

    def test_verdict_is_pass_on_independence(self) -> None:
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="codex", model="gpt-5")
        verdict = verdict_for_assignments(running, verify)
        self.assertEqual(verdict, "pass")

    def test_phase_must_be_dev_running_then_dev_verify(self) -> None:
        # The roundtrip check is scoped to the dev-running -> dev-verify
        # hand-off. Other phase pairs are out of scope and must raise.
        running = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="codex", model="gpt-5")
        with self.assertRaises(ValueError):
            enforce_independent_models(running, verify)

    def test_case_insensitive_cli_id_comparison(self) -> None:
        # CLI IDs are normalized (case-folded, stripped) so accidental
        # casing differences are not counted as independence.
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="Claude", model="opus-4")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="claude ", model="opus-4")
        with self.assertRaises(AntiBiasViolation):
            enforce_independent_models(running, verify)

    def test_empty_model_rejected(self) -> None:
        # An empty model on either side is ambiguous; the gate refuses to
        # certify independence rather than silently passing.
        running = PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id="claude", model="")
        verify = PhaseAssignment(phase=Phase.DEV_VERIFY, cli_id="codex", model="gpt-5")
        with self.assertRaises(ValueError):
            enforce_independent_models(running, verify)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
