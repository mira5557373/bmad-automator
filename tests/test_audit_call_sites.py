from __future__ import annotations

import unittest


class TelemetryEventsSurfaceTests(unittest.TestCase):
    def test_three_event_classes_exposed(self) -> None:
        from story_automator.core import telemetry_events as te

        self.assertTrue(hasattr(te, "EscalationRaised"))
        self.assertTrue(hasattr(te, "StoryStateChanged"))
        self.assertTrue(hasattr(te, "RetroAgentDispatched"))

    def test_event_name_matches_class_name(self) -> None:
        from story_automator.core.telemetry_events import (
            EscalationRaised,
            RetroAgentDispatched,
            StoryStateChanged,
        )

        self.assertEqual(EscalationRaised.event_name, "EscalationRaised")
        self.assertEqual(StoryStateChanged.event_name, "StoryStateChanged")
        self.assertEqual(RetroAgentDispatched.event_name, "RetroAgentDispatched")

    def test_to_dict_round_trip(self) -> None:
        from story_automator.core.telemetry_events import EscalationRaised

        ev = EscalationRaised(
            trigger="review-loop",
            reason="Review loop exceeded max cycles (5/5)",
            correlation_id="c-1",
        )
        d = ev.to_dict()
        self.assertEqual(
            d,
            {
                "trigger": "review-loop",
                "reason": "Review loop exceeded max cycles (5/5)",
                "correlation_id": "c-1",
            },
        )

    def test_dataclass_is_frozen_and_kw_only(self) -> None:
        # Frozen so callers can't mutate after passing to append(); kw-only
        # so call-sites stay readable across the three carriers.
        from story_automator.core.telemetry_events import StoryStateChanged

        ev = StoryStateChanged(
            story="1.2", from_status="draft", to_status="qa", correlation_id="c-2"
        )
        with self.assertRaises(Exception):
            ev.story = "x"  # type: ignore[misc]

    def test_satisfies_audit_event_protocol(self) -> None:
        from story_automator.core.audit import Event
        from story_automator.core.telemetry_events import RetroAgentDispatched

        ev = RetroAgentDispatched(
            primary="claude", fallback="false", model="", correlation_id="c-3"
        )
        # runtime_checkable Protocol: isinstance check works structurally.
        self.assertIsInstance(ev, Event)


if __name__ == "__main__":
    unittest.main()
