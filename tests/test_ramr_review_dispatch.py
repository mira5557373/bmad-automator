from __future__ import annotations

import unittest

from story_automator.core.integration.ramr_review_dispatch import (
    ReviewDispatchEscalation,
    ReviewDispatchError,
    select_reviewer_assignment,
)
from story_automator.core.phase_bridge import (
    PhaseAssignment,
    Phase,
)


def _dev_assignment(cli: str = "claude_opus", model: str = "claude-opus-4-7") -> PhaseAssignment:
    return PhaseAssignment(phase=Phase.DEV_RUNNING, cli_id=cli, model=model)


class SelectReviewerAssignmentHappyPathTests(unittest.TestCase):
    def test_returns_phase_assignment_for_review_verify(self) -> None:
        dev = _dev_assignment(cli="claude_sonnet", model="claude-sonnet-4-5")
        result = select_reviewer_assignment(
            story_key="STORY-1",
            risk="P0",
            dev_assignment=dev,
        )
        self.assertIsInstance(result.assignment, PhaseAssignment)
        self.assertEqual(result.assignment.phase, Phase.DEV_VERIFY)

    def test_default_persona_is_reviewer(self) -> None:
        dev = _dev_assignment(cli="claude_sonnet", model="claude-sonnet-4-5")
        result = select_reviewer_assignment(
            story_key="STORY-1",
            risk="P0",
            dev_assignment=dev,
        )
        # The reviewer routing decision must reference the reviewer persona.
        self.assertEqual(result.routing_decision.persona, "reviewer")

    def test_reviewer_differs_from_dev_when_alternatives_exist(self) -> None:
        # Dev used opus; expect reviewer to be routed to a different model.
        dev = _dev_assignment(cli="claude_opus", model="claude-opus-4-7")
        result = select_reviewer_assignment(
            story_key="STORY-2",
            risk="P0",
            dev_assignment=dev,
        )
        self.assertNotEqual(result.assignment.model, dev.model)


class SelectReviewerAssignmentRejectionTests(unittest.TestCase):
    def test_rejects_when_registry_has_only_dev_model(self) -> None:
        dev = _dev_assignment(cli="solo", model="only-model")
        registry = {
            "solo": {
                "model": "only-model",
                "max_tokens": 1000,
                "temperature": 0.3,
                "tier": "strong",
            }
        }
        with self.assertRaises(ReviewDispatchEscalation) as ctx:
            select_reviewer_assignment(
                story_key="STORY-3",
                risk="P0",
                dev_assignment=dev,
                cli_registry=registry,
            )
        self.assertIn("ramr", str(ctx.exception).lower())

    def test_missing_dev_assignment_raises(self) -> None:
        with self.assertRaises(ReviewDispatchError):
            select_reviewer_assignment(
                story_key="STORY-4",
                risk="P0",
                dev_assignment=None,  # type: ignore[arg-type]
            )

    def test_dev_assignment_wrong_phase_raises(self) -> None:
        wrong_phase = PhaseAssignment(
            phase=Phase.REVIEW_VERIFY, cli_id="claude_opus", model="claude-opus-4-7"
        )
        with self.assertRaises(ReviewDispatchError):
            select_reviewer_assignment(
                story_key="STORY-5",
                risk="P0",
                dev_assignment=wrong_phase,
            )


class SelectReviewerAssignmentValidationTests(unittest.TestCase):
    def test_invalid_risk_raises(self) -> None:
        dev = _dev_assignment()
        with self.assertRaises(ReviewDispatchError):
            select_reviewer_assignment(
                story_key="STORY-6",
                risk="HIGH",  # invalid
                dev_assignment=dev,
            )

    def test_empty_story_key_raises(self) -> None:
        dev = _dev_assignment()
        with self.assertRaises(ReviewDispatchError):
            select_reviewer_assignment(
                story_key="",
                risk="P0",
                dev_assignment=dev,
            )

    def test_independence_is_enforced_pre_flight(self) -> None:
        """Even if the registry returns identical pair, M55 enforce raises."""
        dev = _dev_assignment(cli="claude_opus", model="claude-opus-4-7")
        registry = {
            "claude_opus": {
                "model": "claude-opus-4-7",
                "max_tokens": 8000,
                "temperature": 0.2,
                "tier": "strong",
            },
        }
        with self.assertRaises(ReviewDispatchEscalation):
            select_reviewer_assignment(
                story_key="STORY-7",
                risk="P0",
                dev_assignment=dev,
                cli_registry=registry,
            )

    def test_dispatch_record_includes_story_key_and_rationale(self) -> None:
        dev = _dev_assignment(cli="claude_sonnet", model="claude-sonnet-4-5")
        result = select_reviewer_assignment(
            story_key="STORY-8",
            risk="P1",
            dev_assignment=dev,
        )
        self.assertEqual(result.story_key, "STORY-8")
        self.assertTrue(result.routing_decision.rationale)


class CustomPersonaTests(unittest.TestCase):
    def test_custom_reviewer_persona_accepted(self) -> None:
        dev = _dev_assignment(cli="claude_sonnet", model="claude-sonnet-4-5")
        result = select_reviewer_assignment(
            story_key="STORY-9",
            risk="P1",
            dev_assignment=dev,
            persona="reviewer",
        )
        self.assertEqual(result.routing_decision.persona, "reviewer")


class EscalationCarriesContextTests(unittest.TestCase):
    def test_escalation_message_contains_story_key(self) -> None:
        dev = _dev_assignment(cli="solo", model="only-model")
        registry = {
            "solo": {
                "model": "only-model",
                "max_tokens": 1000,
                "temperature": 0.3,
                "tier": "strong",
            }
        }
        with self.assertRaises(ReviewDispatchEscalation) as ctx:
            select_reviewer_assignment(
                story_key="STORY-10",
                risk="P0",
                dev_assignment=dev,
                cli_registry=registry,
            )
        self.assertIn("STORY-10", str(ctx.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
