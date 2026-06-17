from __future__ import annotations

import unittest


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


if __name__ == "__main__":
    unittest.main()
