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

    @classmethod
    def setUpClass(cls):
        """Save registry state before tests that pollute it."""
        cls._initial_registry = dict(Event._REGISTRY)

    @classmethod
    def tearDownClass(cls):
        """Restore registry to initial state after all tests."""
        Event._REGISTRY.clear()
        Event._REGISTRY.update(cls._initial_registry)

    def test_registry_has_13_entries(self):
        """After import, Event._REGISTRY must contain exactly 13 entries."""
        self.assertEqual(len(self._initial_registry), 13)

    def test_registry_contains_all_event_types(self):
        """Registry must contain all 13 concrete event types by their EVENT_TYPE strings."""
        expected_types = {
            "story_started",
            "story_completed",
            "story_failed",
            "story_deferred",
            "retry_attempt",
            "escalation_triggered",
            "review_cycle",
            "retro_fired",
            "tmux_session_spawned",
            "tmux_session_completed",
            "tmux_session_crashed",
            "cost_charged",
            "budget_alert",
        }
        self.assertEqual(set(self._initial_registry.keys()), expected_types)

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
            (
                StoryStarted,
                '{"event_type":"story_started","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","epic":"E1","story_key":"S1","agent":"claude","model":"opus","complexity":"medium"}',
            ),
            (
                StoryCompleted,
                '{"event_type":"story_completed","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","epic":"E1","story_key":"S1","duration_s":120.5,"cost_usd":0.25,"tokens_in":1000,"tokens_out":2000,"attempts":2}',
            ),
            (
                StoryFailed,
                '{"event_type":"story_failed","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","epic":"E1","story_key":"S1","error_class":"timeout","reason":"test","attempts":5,"final_session":"session1"}',
            ),
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

    def test_parse_event_missing_event_type_raises_value_error(self):
        """parse_event must raise ValueError if event_type is missing."""
        line = '{"timestamp":"2026-06-14T12:00:00Z","run_id":"run-123"}'
        with self.assertRaises(ValueError):
            parse_event(line)

    def test_parse_event_invalid_json_propagates_decode_error(self):
        """parse_event must propagate json.JSONDecodeError for invalid JSON."""
        line = "not valid json {"
        with self.assertRaises(json.JSONDecodeError):
            parse_event(line)

    def test_parse_event_missing_required_field_raises_type_error(self):
        """parse_event must raise TypeError if required field is missing."""
        line = '{"event_type":"story_started","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123"}'
        # story_key is required but missing
        with self.assertRaises(TypeError):
            parse_event(line)

    def test_parse_event_unexpected_extra_fields_raise_type_error(self):
        """parse_event must raise TypeError if known event has unexpected fields."""
        line = '{"event_type":"story_started","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","story_key":"S1","epic":"E1","unknown_field":"value"}'
        with self.assertRaises(TypeError):
            parse_event(line)

    def test_parse_event_all_13_types(self):
        """parse_event must correctly dispatch all 13 concrete event types."""
        test_data = {
            StoryStarted: {
                "epic": "EPIC-1",
                "story_key": "S1",
                "agent": "claude",
                "model": "opus",
                "complexity": "medium",
            },
            StoryCompleted: {
                "epic": "EPIC-1",
                "story_key": "S1",
                "duration_s": 120.5,
                "cost_usd": 0.25,
                "tokens_in": 1000,
                "tokens_out": 2000,
                "attempts": 2,
            },
            StoryFailed: {
                "epic": "EPIC-1",
                "story_key": "S1",
                "error_class": "timeout",
                "reason": "test",
                "attempts": 5,
                "final_session": "session1",
            },
            StoryDeferred: {
                "epic": "EPIC-1",
                "story_key": "S1",
                "reason": "plateau",
                "tasks_completed": 3,
            },
            RetryAttempt: {
                "epic": "EPIC-1",
                "story_key": "S1",
                "attempt_num": 2,
                "agent": "claude",
                "model": "sonnet",
                "prev_error_class": "rate_limit",
            },
            EscalationTriggered: {
                "epic": "EPIC-1",
                "story_key": "S1",
                "trigger_id": 1,
                "severity": "CRITICAL",
                "message": "test",
            },
            ReviewCycle: {
                "epic": "EPIC-1",
                "story_key": "S1",
                "cycle_num": 1,
                "issues_found": 2,
                "blocking": True,
            },
            RetroFired: {
                "epic": "EPIC-1",
                "stories_completed": 5,
                "total_cost_usd": 2.5,
                "duration_s": 600.0,
            },
            TmuxSessionSpawned: {
                "session_name": "session1",
                "story_key": "S1",
                "pid": 1234,
                "pane_geometry": "200x50",
            },
            TmuxSessionCompleted: {
                "session_name": "session1",
                "story_key": "S1",
                "exit_code": 0,
                "duration_s": 120.0,
            },
            TmuxSessionCrashed: {
                "session_name": "session1",
                "story_key": "S1",
                "exit_code": 1,
                "last_capture_chars": 500,
            },
            CostCharged: {
                "epic": "EPIC-1",
                "story_key": "S1",
                "phase": "dev",
                "cost_usd": 0.1,
                "tokens_in": 500,
                "tokens_out": 1000,
                "model": "opus",
            },
            BudgetAlert: {
                "threshold_pct": 75,
                "total_cost_usd": 7.5,
                "max_budget_usd": 10.0,
                "epic": "EPIC-1",
                "story_key": "S1",
            },
        }

        for event_class, fields in test_data.items():
            with self.subTest(event_type=event_class.EVENT_TYPE):
                fields_with_base = {
                    "timestamp": "2026-06-14T12:00:00Z",
                    "run_id": "run-123",
                    **fields,
                }
                event = event_class(**fields_with_base)
                line = event.to_json_line()
                parsed = parse_event(line)
                self.assertIsInstance(parsed, event_class)


class TestRoundTrip(unittest.TestCase):
    """Test round-trip invariant: construct → to_json_line → parse_event."""

    def test_story_started_round_trip(self):
        """StoryStarted round-trip must produce byte-equal JSON."""
        original = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="run-123",
            epic="EPIC-1",
            story_key="STORY-1",
            agent="claude",
            model="opus",
            complexity="medium",
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        self.assertEqual(parsed, original)
        line2 = parsed.to_json_line()
        self.assertEqual(line1, line2)

    def test_all_concrete_events_round_trip(self):
        """All 13 concrete events must support round-trip."""
        test_cases = [
            StoryStarted(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                agent="claude",
                model="opus",
                complexity="medium",
            ),
            StoryCompleted(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                duration_s=120.5,
                cost_usd=0.25,
                tokens_in=1000,
                tokens_out=2000,
                attempts=2,
            ),
            StoryFailed(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                error_class="timeout",
                reason="test",
                attempts=5,
                final_session="session1",
            ),
            StoryDeferred(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                reason="plateau",
                tasks_completed=3,
            ),
            RetryAttempt(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                attempt_num=2,
                agent="claude",
                model="sonnet",
                prev_error_class="rate_limit",
            ),
            EscalationTriggered(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                trigger_id=1,
                severity="CRITICAL",
                message="test",
            ),
            ReviewCycle(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                cycle_num=1,
                issues_found=2,
                blocking=True,
            ),
            RetroFired(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                stories_completed=5,
                total_cost_usd=2.5,
                duration_s=600.0,
            ),
            TmuxSessionSpawned(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                session_name="session1",
                story_key="S1",
                pid=1234,
                pane_geometry="200x50",
            ),
            TmuxSessionCompleted(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                session_name="session1",
                story_key="S1",
                exit_code=0,
                duration_s=120.0,
            ),
            TmuxSessionCrashed(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                session_name="session1",
                story_key="S1",
                exit_code=1,
                last_capture_chars=500,
            ),
            CostCharged(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                epic="E1",
                story_key="S1",
                phase="dev",
                cost_usd=0.1,
                tokens_in=500,
                tokens_out=1000,
                model="opus",
            ),
            BudgetAlert(
                timestamp="2026-06-14T12:00:00Z",
                run_id="r1",
                threshold_pct=75,
                total_cost_usd=7.5,
                max_budget_usd=10.0,
                epic="E1",
                story_key="S1",
            ),
        ]
        for event in test_cases:
            with self.subTest(event_type=event.EVENT_TYPE):
                line1 = event.to_json_line()
                parsed = parse_event(line1)
                self.assertEqual(parsed, event)
                line2 = parsed.to_json_line()
                self.assertEqual(line1, line2)

    def test_unknown_event_round_trip(self):
        """UnknownEvent round-trip must preserve event_type and raw_fields."""
        original = UnknownEvent(
            timestamp="2026-06-14T12:00:00Z",
            run_id="run-123",
            raw_event_type="future_event_type",
            raw_fields={"custom_field": "value", "count": 42},
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertEqual(parsed.raw_event_type, "future_event_type")
        self.assertEqual(parsed.raw_fields, {"custom_field": "value", "count": 42})
        line2 = parsed.to_json_line()
        # For UnknownEvent, at minimum the re-parsed content must match
        parsed2 = parse_event(line2)
        self.assertEqual(parsed2.raw_event_type, parsed.raw_event_type)
        self.assertEqual(parsed2.raw_fields, parsed.raw_fields)


if __name__ == "__main__":
    unittest.main()
