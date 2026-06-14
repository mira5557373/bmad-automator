from __future__ import annotations

import json
import unittest
from typing import Any, ClassVar

from story_automator.core.telemetry_events import (
    Event,
    UnknownEvent,
    StoryStarted,
    StoryCompleted,
    StoryFailed,
    StoryDeferred,
    RetryAttempt,
    EscalationTriggered,
    ReviewCycle,
    RetroFired,
    TmuxSessionSpawned,
    TmuxSessionCompleted,
    TmuxSessionCrashed,
    CostCharged,
    BudgetAlert,
    parse_event,
)


class TestEventRegistry(unittest.TestCase):
    """Test Event base class, registration, and registry structure."""

    def test_event_has_event_type_classvar(self):
        """Event base must define EVENT_TYPE classvar."""
        self.assertTrue(hasattr(Event, "EVENT_TYPE"))
        self.assertIsNotNone(Event.EVENT_TYPE)

    def test_event_has_registry_classvar(self):
        """Event base must define _REGISTRY classvar as dict."""
        self.assertTrue(hasattr(Event, "_REGISTRY"))
        self.assertIsInstance(Event._REGISTRY, dict)

    def test_event_has_timestamp_and_run_id_fields(self):
        """Event base must have timestamp and run_id instance fields."""
        import inspect
        sig = inspect.signature(Event)
        params = list(sig.parameters.keys())
        self.assertIn("timestamp", params)
        self.assertIn("run_id", params)

    def test_concrete_subclass_auto_registers(self):
        """Concrete subclass with EVENT_TYPE must auto-register."""
        class TestEvent(Event):
            EVENT_TYPE: ClassVar[str] = "test_event"

        self.assertIn("test_event", Event._REGISTRY)
        self.assertIs(Event._REGISTRY["test_event"], TestEvent)

    def test_duplicate_event_type_raises_runtime_error(self):
        """Duplicate EVENT_TYPE must raise RuntimeError with qualnames."""
        class FirstEvent(Event):
            EVENT_TYPE: ClassVar[str] = "duplicate_type"

        with self.assertRaises(RuntimeError) as cm:
            class SecondEvent(Event):
                EVENT_TYPE: ClassVar[str] = "duplicate_type"

        error_msg = str(cm.exception)
        self.assertIn("duplicate_type", error_msg)
        self.assertIn("FirstEvent", error_msg)
        self.assertIn("SecondEvent", error_msg)


class TestEventSerialization(unittest.TestCase):
    """Test to_dict and to_json_line methods."""


class TestParseEvent(unittest.TestCase):
    """Test parse_event function with all branches and error cases."""


class TestRoundTrip(unittest.TestCase):
    """Test round-trip invariant: construct → to_json_line → parse_event."""


if __name__ == "__main__":
    unittest.main()
