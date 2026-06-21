"""Tests for M59 phase-shaped budgets.

The phase-shaped budget module layers per-phase, per-persona spend
ceilings on top of the base budget_ceilings primitives. Concretely:

- A *running budget* is enforced inside the dev/run phase. P0 overspend
  here demotes the overrun task to a "retry-cheap" policy (smaller model
  / fewer tokens) rather than escalating.
- A *verification budget* is enforced inside the review/verify phase.
  Overspend here pauses the story so a human can re-scope, because
  spending more on verification past the ceiling is a smell, not a
  recoverable transient.
- Each phase has per-persona sub-ceilings (e.g. dev-running has a
  separate ceiling for the developer persona vs. the QA-running persona)
  so a single greedy persona cannot starve the others.

These tests pin the shape so M59 can be safely refactored later.
"""

from __future__ import annotations

import unittest

from story_automator.core.budget_ceilings import (
    BudgetCeiling,
    BudgetLedger,
    OverspendAction,
    classify_overspend,
)
from story_automator.core.innovation.phase_budget import (
    PHASE_DEV_RUNNING,
    PHASE_REVIEW_VERIFY,
    PhaseBudgetConfig,
    PhaseBudgetError,
    PhaseBudgetState,
    PhaseSpendOutcome,
    default_phase_budget_config,
    enforce_phase_spend,
    persona_remaining,
    summarize_phase_state,
)


class BudgetCeilingsTests(unittest.TestCase):
    def test_ceiling_validates_positive_limit(self) -> None:
        with self.assertRaises(ValueError):
            BudgetCeiling(limit=0, priority="P0")
        with self.assertRaises(ValueError):
            BudgetCeiling(limit=-5, priority="P0")

    def test_ledger_tracks_spend_per_key(self) -> None:
        ledger = BudgetLedger()
        ledger.record("dev", 30)
        ledger.record("dev", 10)
        ledger.record("qa", 5)
        self.assertEqual(ledger.total("dev"), 40)
        self.assertEqual(ledger.total("qa"), 5)
        self.assertEqual(ledger.total("missing"), 0)

    def test_classify_overspend_p0_running_is_retry_cheap(self) -> None:
        action = classify_overspend(priority="P0", phase=PHASE_DEV_RUNNING)
        self.assertEqual(action, OverspendAction.RETRY_CHEAP)

    def test_classify_overspend_review_verify_is_pause(self) -> None:
        action = classify_overspend(priority="P0", phase=PHASE_REVIEW_VERIFY)
        self.assertEqual(action, OverspendAction.PAUSE)
        # Non-P0 in review still pauses — verification overspend always pauses.
        action2 = classify_overspend(priority="P2", phase=PHASE_REVIEW_VERIFY)
        self.assertEqual(action2, OverspendAction.PAUSE)


class PhaseBudgetConfigTests(unittest.TestCase):
    def test_default_config_has_required_phases(self) -> None:
        config = default_phase_budget_config()
        self.assertIn(PHASE_DEV_RUNNING, config.phases)
        self.assertIn(PHASE_REVIEW_VERIFY, config.phases)

    def test_default_config_per_persona_ceilings_present(self) -> None:
        config = default_phase_budget_config()
        dev_phase = config.phases[PHASE_DEV_RUNNING]
        # Dev-running phase must distinguish developer vs qa persona ceilings.
        self.assertIn("developer", dev_phase.persona_ceilings)
        self.assertIn("qa", dev_phase.persona_ceilings)
        self.assertGreater(dev_phase.persona_ceilings["developer"].limit, 0)

    def test_invalid_phase_raises(self) -> None:
        config = default_phase_budget_config()
        with self.assertRaises(PhaseBudgetError):
            enforce_phase_spend(
                config=config,
                state=PhaseBudgetState(),
                phase="not-a-real-phase",
                persona="developer",
                priority="P0",
                spend=10,
            )


class EnforcePhaseSpendTests(unittest.TestCase):
    def _config(self) -> PhaseBudgetConfig:
        return default_phase_budget_config()

    def test_within_ceiling_returns_allow(self) -> None:
        config = self._config()
        state = PhaseBudgetState()
        outcome = enforce_phase_spend(
            config=config,
            state=state,
            phase=PHASE_DEV_RUNNING,
            persona="developer",
            priority="P1",
            spend=5,
        )
        self.assertIsInstance(outcome, PhaseSpendOutcome)
        self.assertEqual(outcome.action, OverspendAction.ALLOW)
        self.assertGreater(outcome.persona_remaining, 0)

    def test_dev_running_p0_overspend_returns_retry_cheap(self) -> None:
        config = self._config()
        state = PhaseBudgetState()
        persona_limit = config.phases[PHASE_DEV_RUNNING].persona_ceilings["developer"].limit
        # Spend everything plus one to overflow the per-persona ceiling.
        outcome = enforce_phase_spend(
            config=config,
            state=state,
            phase=PHASE_DEV_RUNNING,
            persona="developer",
            priority="P0",
            spend=persona_limit + 1,
        )
        self.assertEqual(outcome.action, OverspendAction.RETRY_CHEAP)
        self.assertTrue(outcome.overspent)
        self.assertEqual(outcome.persona_remaining, 0)

    def test_review_verify_overspend_returns_pause(self) -> None:
        config = self._config()
        state = PhaseBudgetState()
        phase_cfg = config.phases[PHASE_REVIEW_VERIFY]
        persona_limit = phase_cfg.persona_ceilings["qa"].limit
        outcome = enforce_phase_spend(
            config=config,
            state=state,
            phase=PHASE_REVIEW_VERIFY,
            persona="qa",
            priority="P0",
            spend=persona_limit + 5,
        )
        self.assertEqual(outcome.action, OverspendAction.PAUSE)
        self.assertTrue(outcome.overspent)

    def test_per_persona_ceiling_isolated(self) -> None:
        # One greedy persona must not consume another persona's quota.
        config = self._config()
        state = PhaseBudgetState()
        dev_limit = config.phases[PHASE_DEV_RUNNING].persona_ceilings["developer"].limit
        enforce_phase_spend(
            config=config,
            state=state,
            phase=PHASE_DEV_RUNNING,
            persona="developer",
            priority="P1",
            spend=dev_limit,  # exhaust developer
        )
        qa_outcome = enforce_phase_spend(
            config=config,
            state=state,
            phase=PHASE_DEV_RUNNING,
            persona="qa",
            priority="P1",
            spend=1,
        )
        self.assertEqual(qa_outcome.action, OverspendAction.ALLOW)
        self.assertEqual(
            persona_remaining(config, state, PHASE_DEV_RUNNING, "developer"),
            0,
        )

    def test_unknown_persona_raises(self) -> None:
        config = self._config()
        state = PhaseBudgetState()
        with self.assertRaises(PhaseBudgetError):
            enforce_phase_spend(
                config=config,
                state=state,
                phase=PHASE_DEV_RUNNING,
                persona="ghost-persona",
                priority="P0",
                spend=1,
            )

    def test_summarize_phase_state_reports_per_persona(self) -> None:
        config = self._config()
        state = PhaseBudgetState()
        enforce_phase_spend(
            config=config,
            state=state,
            phase=PHASE_DEV_RUNNING,
            persona="developer",
            priority="P1",
            spend=3,
        )
        enforce_phase_spend(
            config=config,
            state=state,
            phase=PHASE_DEV_RUNNING,
            persona="qa",
            priority="P1",
            spend=2,
        )
        summary = summarize_phase_state(config, state, PHASE_DEV_RUNNING)
        self.assertEqual(summary["phase"], PHASE_DEV_RUNNING)
        self.assertEqual(summary["personas"]["developer"]["spent"], 3)
        self.assertEqual(summary["personas"]["qa"]["spent"], 2)
        self.assertGreater(summary["personas"]["developer"]["remaining"], 0)

    def test_negative_spend_rejected(self) -> None:
        config = self._config()
        state = PhaseBudgetState()
        with self.assertRaises(PhaseBudgetError):
            enforce_phase_spend(
                config=config,
                state=state,
                phase=PHASE_DEV_RUNNING,
                persona="developer",
                priority="P0",
                spend=-1,
            )


if __name__ == "__main__":
    unittest.main()
