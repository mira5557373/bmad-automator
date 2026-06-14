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

    def test_unknown_event_not_auto_registered(self):
        """UnknownEvent must NOT be in _REGISTRY after definition."""
        # After import, check UnknownEvent is not in registry
        self.assertNotIn("unknown_event", Event._REGISTRY)
        # Verify no key points to UnknownEvent class
        for value in Event._REGISTRY.values():
            self.assertNotEqual(value.__name__, "UnknownEvent")


class TestEventSerialization(unittest.TestCase):
    """Test to_dict and to_json_line methods."""

    def test_to_dict_injects_event_type(self):
        """to_dict must inject event_type from EVENT_TYPE classvar."""
        event = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="run-123",
            epic="EPIC-1",
            story_key="STORY-1",
            agent="claude",
            model="opus",
            complexity="medium",
        )
        d = event.to_dict()
        self.assertEqual(d["event_type"], "story_started")
        self.assertEqual(d["story_key"], "STORY-1")
        self.assertEqual(d["epic"], "EPIC-1")
        self.assertEqual(d["agent"], "claude")

    def test_to_dict_includes_all_fields(self):
        """to_dict must include timestamp and run_id."""
        event = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="run-123",
            epic="EPIC-1",
            story_key="STORY-1",
            agent="claude",
            model="opus",
            complexity="medium",
        )
        d = event.to_dict()
        self.assertIn("timestamp", d)
        self.assertIn("run_id", d)
        self.assertIn("epic", d)
        self.assertIn("model", d)

    def test_to_json_line_returns_compact_json(self):
        """to_json_line must return compact JSON without spaces."""
        event = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="run-123",
            epic="EPIC-1",
            story_key="STORY-1",
            agent="claude",
            model="opus",
            complexity="medium",
        )
        line = event.to_json_line()
        self.assertIsInstance(line, str)
        # Must not have trailing newline
        self.assertFalse(line.endswith("\n"))
        # Must be valid JSON
        parsed = json.loads(line)
        self.assertEqual(parsed["event_type"], "story_started")

    def test_to_json_line_no_spaces(self):
        """to_json_line output must be compact (no unnecessary spaces)."""
        event = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="run-123",
            epic="EPIC-1",
            story_key="STORY-1",
            agent="claude",
            model="opus",
            complexity="medium",
        )
        line = event.to_json_line()
        # Compact JSON has no spaces after colons or commas
        self.assertNotIn(", ", line)  # No space after comma
        self.assertNotIn(": ", line)  # No space after colon


class TestParseEvent(unittest.TestCase):
    """Test parse_event function with all branches and error cases."""

    def test_parse_event_known_type(self):
        """parse_event must return correct concrete class for known type."""
        line = '{"event_type":"story_started","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","epic":"E1","story_key":"S1","agent":"claude","model":"opus","complexity":"medium"}'
        event = parse_event(line)
        self.assertIsInstance(event, StoryStarted)
        self.assertEqual(event.story_key, "S1")
        self.assertEqual(event.epic, "E1")
        self.assertEqual(event.agent, "claude")

    def test_parse_event_returns_correct_type_for_each_class(self):
        """parse_event must dispatch to correct concrete class."""
        cases = [
            (StoryStarted, '{"event_type":"story_started","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","epic":"E1","story_key":"S1","agent":"claude","model":"opus","complexity":"medium"}'),
            (StoryCompleted, '{"event_type":"story_completed","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","epic":"E1","story_key":"S1","duration_s":120.5,"cost_usd":0.25,"tokens_in":1000,"tokens_out":2000,"attempts":2}'),
            (StoryFailed, '{"event_type":"story_failed","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","epic":"E1","story_key":"S1","error_class":"timeout","reason":"test","attempts":5,"final_session":"session1"}'),
        ]
        for expected_class, line in cases:
            with self.subTest(expected_class=expected_class.__name__):
                event = parse_event(line)
                self.assertIsInstance(event, expected_class)

    def test_parse_event_unknown_type(self):
        """parse_event must return UnknownEvent for unrecognized type."""
        line = '{"event_type":"unknown_event_type","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","custom_field":"value"}'
        event = parse_event(line)
        self.assertIsInstance(event, UnknownEvent)
        self.assertEqual(event.raw_event_type, "unknown_event_type")
        self.assertEqual(event.raw_fields["custom_field"], "value")


class TestRoundTrip(unittest.TestCase):
    """Test round-trip invariant: construct → to_json_line → parse_event."""


if __name__ == "__main__":
    unittest.main()
