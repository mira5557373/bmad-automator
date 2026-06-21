"""Tests for core/phase_bridge.py — M25 phase bridge port from bmad-auto."""

from __future__ import annotations

import unittest
from enum import StrEnum

from story_automator.core import phase_bridge
from story_automator.core.phase_bridge import (
    PAUSE_STAGES,
    PHASE_TO_STEP,
    STEP_TO_PHASES,
    TERMINAL_PHASES,
    Phase,
    is_terminal_phase,
    pause_stage_for_phase,
    phases_for_step,
    step_for_phase,
)


class PhaseEnumTests(unittest.TestCase):
    def test_phase_is_strenum_subclass(self) -> None:
        self.assertTrue(issubclass(Phase, StrEnum))

    def test_phase_has_exactly_eleven_values(self) -> None:
        self.assertEqual(len(list(Phase)), 11)

    def test_phase_values_kebab_case_strings(self) -> None:
        expected = {
            "pending",
            "dev-running",
            "dev-verify",
            "review-running",
            "review-verify",
            "committing",
            "triage-running",
            "triage-verify",
            "done",
            "deferred",
            "escalated",
        }
        actual = {member.value for member in Phase}
        self.assertEqual(expected, actual)

    def test_each_phase_value_individually(self) -> None:
        self.assertEqual(Phase.PENDING.value, "pending")
        self.assertEqual(Phase.DEV_RUNNING.value, "dev-running")
        self.assertEqual(Phase.DEV_VERIFY.value, "dev-verify")
        self.assertEqual(Phase.REVIEW_RUNNING.value, "review-running")
        self.assertEqual(Phase.REVIEW_VERIFY.value, "review-verify")
        self.assertEqual(Phase.COMMITTING.value, "committing")
        self.assertEqual(Phase.TRIAGE_RUNNING.value, "triage-running")
        self.assertEqual(Phase.TRIAGE_VERIFY.value, "triage-verify")
        self.assertEqual(Phase.DONE.value, "done")
        self.assertEqual(Phase.DEFERRED.value, "deferred")
        self.assertEqual(Phase.ESCALATED.value, "escalated")

    def test_phase_string_equality(self) -> None:
        # StrEnum behaves as str
        self.assertEqual(Phase.PENDING, "pending")
        self.assertEqual(Phase.DONE, "done")


class TerminalPhasesTests(unittest.TestCase):
    def test_terminal_phases_is_frozenset(self) -> None:
        self.assertIsInstance(TERMINAL_PHASES, frozenset)

    def test_terminal_phases_contents(self) -> None:
        self.assertEqual(
            TERMINAL_PHASES,
            frozenset({Phase.DONE, Phase.DEFERRED, Phase.ESCALATED}),
        )

    def test_is_terminal_phase_true_for_terminals(self) -> None:
        for phase in (Phase.DONE, Phase.DEFERRED, Phase.ESCALATED):
            self.assertTrue(is_terminal_phase(phase), msg=f"{phase} should be terminal")

    def test_is_terminal_phase_false_for_running(self) -> None:
        for phase in (
            Phase.PENDING,
            Phase.DEV_RUNNING,
            Phase.DEV_VERIFY,
            Phase.REVIEW_RUNNING,
            Phase.REVIEW_VERIFY,
            Phase.COMMITTING,
            Phase.TRIAGE_RUNNING,
            Phase.TRIAGE_VERIFY,
        ):
            self.assertFalse(is_terminal_phase(phase), msg=f"{phase} should not be terminal")

    def test_is_terminal_phase_accepts_string_value(self) -> None:
        self.assertTrue(is_terminal_phase("done"))
        self.assertFalse(is_terminal_phase("pending"))


class PauseStagesTests(unittest.TestCase):
    def test_pause_stages_is_frozenset(self) -> None:
        self.assertIsInstance(PAUSE_STAGES, frozenset)

    def test_pause_stages_contents(self) -> None:
        self.assertEqual(
            PAUSE_STAGES,
            frozenset({"spec-approval", "epic-boundary", "escalation", "story-gate"}),
        )

    def test_pause_stage_for_phase_escalated(self) -> None:
        self.assertEqual(pause_stage_for_phase(Phase.ESCALATED), "escalation")

    def test_pause_stage_for_phase_non_paused_returns_none(self) -> None:
        # Running phases have no associated pause stage
        self.assertIsNone(pause_stage_for_phase(Phase.PENDING))
        self.assertIsNone(pause_stage_for_phase(Phase.DEV_RUNNING))
        self.assertIsNone(pause_stage_for_phase(Phase.DONE))


class StepPhaseMappingTests(unittest.TestCase):
    def test_step_to_phases_keys_are_five_steps(self) -> None:
        expected_steps = {"create", "dev", "auto", "review", "retro"}
        self.assertEqual(set(STEP_TO_PHASES.keys()), expected_steps)

    def test_step_to_phases_values_are_frozensets(self) -> None:
        for step, phases in STEP_TO_PHASES.items():
            self.assertIsInstance(phases, frozenset, msg=f"step={step}")
            for phase in phases:
                self.assertIsInstance(phase, Phase, msg=f"step={step}")

    def test_phase_to_step_covers_all_phases(self) -> None:
        for phase in Phase:
            self.assertIn(phase, PHASE_TO_STEP, msg=f"missing {phase}")

    def test_phase_to_step_values_are_valid_steps(self) -> None:
        valid_steps = set(STEP_TO_PHASES.keys())
        for phase, step in PHASE_TO_STEP.items():
            self.assertIn(step, valid_steps, msg=f"{phase} -> {step}")

    def test_round_trip_step_to_phase_to_step(self) -> None:
        # Every phase reachable from a step maps back to that step
        for step, phases in STEP_TO_PHASES.items():
            for phase in phases:
                self.assertEqual(
                    PHASE_TO_STEP[phase],
                    step,
                    msg=f"round-trip mismatch: {step} -> {phase} -> {PHASE_TO_STEP[phase]}",
                )

    def test_step_for_phase_helper(self) -> None:
        self.assertEqual(step_for_phase(Phase.DEV_RUNNING), "dev")
        self.assertEqual(step_for_phase(Phase.REVIEW_VERIFY), "review")

    def test_phases_for_step_helper(self) -> None:
        dev_phases = phases_for_step("dev")
        self.assertIn(Phase.DEV_RUNNING, dev_phases)
        self.assertIn(Phase.DEV_VERIFY, dev_phases)
        self.assertIsInstance(dev_phases, frozenset)


class UnknownInputTests(unittest.TestCase):
    def test_step_for_phase_rejects_unknown(self) -> None:
        with self.assertRaises(KeyError):
            step_for_phase("not-a-phase")  # type: ignore[arg-type]

    def test_phases_for_step_rejects_unknown(self) -> None:
        with self.assertRaises(KeyError):
            phases_for_step("not-a-step")

    def test_is_terminal_phase_unknown_returns_false(self) -> None:
        self.assertFalse(is_terminal_phase("nonsense"))

    def test_pause_stage_for_phase_unknown_returns_none(self) -> None:
        self.assertIsNone(pause_stage_for_phase("nonsense"))


class ModuleExportsTests(unittest.TestCase):
    def test_public_symbols_exist(self) -> None:
        for name in (
            "Phase",
            "TERMINAL_PHASES",
            "PAUSE_STAGES",
            "STEP_TO_PHASES",
            "PHASE_TO_STEP",
            "is_terminal_phase",
            "pause_stage_for_phase",
            "step_for_phase",
            "phases_for_step",
        ):
            self.assertTrue(hasattr(phase_bridge, name), msg=f"missing export: {name}")


if __name__ == "__main__":
    unittest.main()
