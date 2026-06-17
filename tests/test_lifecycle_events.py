from __future__ import annotations

import json
import unittest

from story_automator.core.lifecycle_events import (
    LifecyclePhaseCompleted,
    LifecyclePhaseFailed,
    LifecyclePhaseStarted,
)
from story_automator.core.telemetry_events import parse_event


class LifecycleEventsModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_events  # noqa: F401

    def test_event_types_are_registered(self) -> None:
        from story_automator.core import lifecycle_events  # noqa: F401
        from story_automator.core.telemetry_events import Event

        for name in (
            "lifecycle_phase_started",
            "lifecycle_phase_completed",
            "lifecycle_phase_failed",
        ):
            self.assertIn(
                name,
                Event._REGISTRY,
                f"{name!r} did not auto-register; check __init_subclass__ "
                f"and that lifecycle_events.py was imported.",
            )

    def test_event_classes_are_distinct(self) -> None:
        from story_automator.core.lifecycle_events import (
            LifecyclePhaseCompleted,
            LifecyclePhaseFailed,
            LifecyclePhaseStarted,
        )

        self.assertNotEqual(LifecyclePhaseStarted, LifecyclePhaseCompleted)
        self.assertNotEqual(LifecyclePhaseStarted, LifecyclePhaseFailed)
        self.assertNotEqual(LifecyclePhaseCompleted, LifecyclePhaseFailed)


class LifecycleEventsRoundTripTests(unittest.TestCase):
    def test_started_round_trip(self) -> None:
        original = LifecyclePhaseStarted(
            timestamp="2026-06-17T12:00:00Z",
            run_id="run-deadbeef",
            node_id="B1-brief",
            phase=1,
            track="bmm",
            skill="bmad-product-brief",
            agent_role="analyst",
        )
        line = original.to_json_line()
        parsed = parse_event(line)
        self.assertIsInstance(parsed, LifecyclePhaseStarted)
        self.assertEqual(parsed.node_id, "B1-brief")
        self.assertEqual(parsed.phase, 1)
        self.assertEqual(parsed.run_id, "run-deadbeef")

    def test_completed_round_trip(self) -> None:
        original = LifecyclePhaseCompleted(
            timestamp="2026-06-17T12:00:05Z",
            run_id="run-deadbeef",
            node_id="B1-brief",
            phase=1,
            track="bmm",
            duration_s=5.0,
            gate_decision="auto_complete",
        )
        line = original.to_json_line()
        parsed = parse_event(line)
        self.assertIsInstance(parsed, LifecyclePhaseCompleted)
        self.assertEqual(parsed.gate_decision, "auto_complete")
        self.assertEqual(parsed.duration_s, 5.0)

    def test_failed_round_trip(self) -> None:
        original = LifecyclePhaseFailed(
            timestamp="2026-06-17T12:00:05Z",
            run_id="run-deadbeef",
            node_id="B1-brief",
            phase=1,
            track="bmm",
            reason="agent_timeout",
            error_class="TimeoutError",
            attempt=1,
        )
        line = original.to_json_line()
        parsed = parse_event(line)
        self.assertIsInstance(parsed, LifecyclePhaseFailed)
        self.assertEqual(parsed.reason, "agent_timeout")
        self.assertEqual(parsed.error_class, "TimeoutError")

    def test_event_type_in_serialized_payload(self) -> None:
        line = LifecyclePhaseStarted(
            timestamp="t",
            run_id="r",
            node_id="n",
            phase=1,
            track="bmm",
            skill="s",
            agent_role="a",
        ).to_json_line()
        payload = json.loads(line)
        self.assertEqual(payload["event_type"], "lifecycle_phase_started")
        self.assertNotIn("EVENT_TYPE", payload)


class LifecycleEventsReimportTests(unittest.TestCase):
    def test_same_class_reregistration_does_not_raise(self) -> None:
        """__init_subclass__ uses an identity check, so calling it again on
        the SAME class object must be a no-op. We do not use importlib.reload
        here because reload creates new class objects and would conflict with
        an unrelated identity (see test_telemetry_events.py)."""
        from story_automator.core.telemetry_events import Event

        init_subclass = Event.__init_subclass__.__func__  # type: ignore[attr-defined]
        try:
            init_subclass(LifecyclePhaseStarted)
            init_subclass(LifecyclePhaseCompleted)
            init_subclass(LifecyclePhaseFailed)
        except RuntimeError as exc:
            self.fail(f"identity check failed: re-registration raised {exc!r}")


if __name__ == "__main__":
    unittest.main()
