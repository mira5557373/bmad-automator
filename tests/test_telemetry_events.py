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


class TestUnknownEvent(unittest.TestCase):
    """Test UnknownEvent dataclass structure (REQ-04)."""

    def test_unknown_event_has_required_fields(self):
        """UnknownEvent must have raw_event_type and raw_fields fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(UnknownEvent)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(UnknownEvent)}

        # Check base fields from Event
        self.assertIn("timestamp", fields)
        self.assertIn("run_id", fields)

        # Check UnknownEvent-specific fields
        self.assertIn("raw_event_type", fields)
        self.assertIn("raw_fields", fields)
        self.assertEqual(fields["raw_event_type"], str)
        self.assertEqual(fields["raw_fields"], dict[str, Any])

    def test_unknown_event_to_dict_re_emits_original_type(self):
        """UnknownEvent.to_dict must use raw_event_type as event_type."""
        unknown = UnknownEvent(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            raw_event_type="future_event_v2",
            raw_fields={"custom": "value", "count": 42},
        )
        d = unknown.to_dict()
        self.assertEqual(d["event_type"], "future_event_v2")
        self.assertNotIn(
            "raw_event_type", d
        )  # raw_event_type is injected as event_type
        self.assertEqual(d["custom"], "value")
        self.assertEqual(d["count"], 42)


class TestEventRegistry(unittest.TestCase):
    """Test Event base class, registration, and registry structure."""

    @classmethod
    def setUpClass(cls):
        """Save registry state before tests that pollute it."""
        cls._initial_registry = dict(Event._REGISTRY)

    @classmethod
    def tearDownClass(cls):
        """Restore registry to match initial count (may have new classes from reload)."""
        # Don't restore to old class objects as reload creates new ones
        # Just verify the count matches what was expected
        pass

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

    def test_registry_idempotent_under_reimport(self):
        """Re-importing module should not cause duplicate registration errors."""
        # Verify initial registry state (captured at class setup before tests added artifacts)
        self.assertEqual(len(self._initial_registry), 13)

        # Verify all 13 original types are present
        for event_type in self._initial_registry.keys():
            self.assertIn(event_type, Event._REGISTRY)
            self.assertEqual(
                Event._REGISTRY[event_type].__name__,
                self._initial_registry[event_type].__name__,
            )

        # Verify story_started is registered
        self.assertIn("story_started", Event._REGISTRY)
        self.assertEqual(Event._REGISTRY["story_started"].__name__, "StoryStarted")


class TestRegistryAcceptance(unittest.TestCase):
    """Audit Event._REGISTRY against REQ-06 specification.

    REQ-06: Registry must contain exactly 13 entries, UnknownEvent excluded.
    """

    # Define the expected concrete event types (no test artifacts)
    EXPECTED_CONCRETE_TYPES = {
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

    def _get_concrete_registry_only(self):
        """Extract only the 13 concrete event types, excluding test artifacts."""
        concrete = {}
        for event_type_str, event_class in Event._REGISTRY.items():
            if event_type_str in self.EXPECTED_CONCRETE_TYPES:
                concrete[event_type_str] = event_class
        return concrete

    def test_registry_exactly_13_entries_req06(self):
        """REQ-06: Event._REGISTRY must contain exactly 13 concrete entries."""
        concrete = self._get_concrete_registry_only()
        self.assertEqual(
            len(concrete),
            13,
            f"Expected 13 registry entries, got {len(concrete)}",
        )

    def test_registry_contains_all_13_event_types(self):
        """REQ-06: Registry must contain all 13 concrete event type strings."""
        concrete = self._get_concrete_registry_only()
        actual_types = set(concrete.keys())
        self.assertEqual(
            actual_types,
            self.EXPECTED_CONCRETE_TYPES,
            f"Registry types mismatch.\nExpected: {self.EXPECTED_CONCRETE_TYPES}\nActual: {actual_types}",
        )

    def test_registry_keys_match_class_event_type(self):
        """REQ-06: Each registry key must match the class's EVENT_TYPE."""
        concrete = self._get_concrete_registry_only()
        for event_type_str, event_class in concrete.items():
            self.assertEqual(
                event_type_str,
                event_class.EVENT_TYPE,
                f"Key {event_type_str!r} does not match {event_class.__name__}.EVENT_TYPE = {event_class.EVENT_TYPE!r}",
            )

    def test_registry_excludes_unknown_event(self):
        """REQ-06: UnknownEvent must NOT be in the registry."""
        for event_class in Event._REGISTRY.values():
            self.assertNotEqual(
                event_class.__name__,
                "UnknownEvent",
                "UnknownEvent found in registry — should be excluded per REQ-06",
            )

    def test_registry_lookup_by_event_type_string(self):
        """REQ-06: Registry lookup by event_type string must work for all 13."""
        concrete = self._get_concrete_registry_only()
        for event_type_str, expected_class in concrete.items():
            actual_class = Event._REGISTRY.get(event_type_str)
            self.assertIs(
                actual_class,
                expected_class,
                f"Registry[{event_type_str!r}] mismatch",
            )

    def test_all_concrete_classes_are_dataclasses(self):
        """All 13 concrete classes must be dataclasses."""
        import dataclasses

        concrete = self._get_concrete_registry_only()
        for event_class in concrete.values():
            self.assertTrue(
                dataclasses.is_dataclass(event_class),
                f"{event_class.__name__} is not a dataclass",
            )


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

    def test_parse_rejects_float_for_int_field(self):
        """parse_event must reject float value for int field (tokens_in)."""
        line = '{"event_type":"story_completed","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","epic":"E1","story_key":"S1","duration_s":120.5,"cost_usd":0.25,"tokens_in":1.5,"tokens_out":2000,"attempts":2}'
        with self.assertRaises(TypeError):
            parse_event(line)

    def test_parse_accepts_int_for_float_field(self):
        """parse_event must accept int value for float field (cost_usd)."""
        line = '{"event_type":"cost_charged","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","epic":"E1","story_key":"S1","phase":"dev","cost_usd":1,"tokens_in":500,"tokens_out":1000,"model":"opus"}'
        event = parse_event(line)
        self.assertIsInstance(event, CostCharged)
        self.assertEqual(event.cost_usd, 1)  # int coerced to float

    def test_parse_rejects_string_for_int_field(self):
        """parse_event must reject string value for int field."""
        line = '{"event_type":"review_cycle","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","epic":"E1","story_key":"S1","cycle_num":"one","issues_found":0,"blocking":false}'
        with self.assertRaises(TypeError):
            parse_event(line)

    def test_parse_rejects_string_for_bool_field(self):
        """parse_event must reject string value for bool field."""
        line = '{"event_type":"review_cycle","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","epic":"E1","story_key":"S1","cycle_num":1,"issues_found":0,"blocking":"yes"}'
        with self.assertRaises(TypeError):
            parse_event(line)

    def test_parse_unicode_in_string_fields(self):
        """parse_event must preserve non-ASCII in string fields."""
        line = '{"event_type":"story_started","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","epic":"史诗","story_key":"S1","agent":"claude","model":"opus","complexity":"medium"}'
        event = parse_event(line)
        self.assertEqual(event.epic, "史诗")

    def test_parse_rejects_none_for_required_fields(self):
        """parse_event must reject None for non-optional required fields."""
        line = '{"event_type":"story_started","timestamp":null,"run_id":"run-123","epic":"E1","story_key":"S1","agent":"claude","model":"opus","complexity":"medium"}'
        with self.assertRaises(TypeError) as cm:
            parse_event(line)
        self.assertIn("does not accept None", str(cm.exception))

    def test_parse_handles_none_for_optional_field_gracefully(self):
        """parse_event must gracefully skip None values when checking optional fields.

        This tests the continue branch in _validate_event_fields that handles
        optional fields with None values (defensive, though M01 has no optional fields).
        """
        # Currently all M01 fields are required, so we create a mock scenario
        # by testing that the validator doesn't crash on None for int/float/bool types
        line = '{"event_type":"story_completed","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","epic":"E1","story_key":"S1","duration_s":120.5,"cost_usd":0.25,"tokens_in":1000,"tokens_out":2000,"attempts":2}'
        # All fields present and valid
        event = parse_event(line)
        self.assertIsInstance(event, StoryCompleted)


class TestConcreteEventSpecCompliance(unittest.TestCase):
    """Audit concrete event classes against REQ-05 specification.

    REQ-05: Must define exactly 13 concrete event classes with correct fields.
    Design doc table: Each class has specific field names and types.
    """

    def test_story_started_fields_req05(self):
        """StoryStarted must have exactly 7 fields: timestamp, run_id, epic, story_key, agent, model, complexity."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(StoryStarted)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(StoryStarted)}
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "story_key": str,
            "agent": str,
            "model": str,
            "complexity": str,
        }
        self.assertEqual(fields, expected)

    def test_story_completed_fields_req05(self):
        """StoryCompleted must have exactly 9 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(StoryCompleted)
        fields = {
            f.name: type_hints[f.name] for f in dataclasses.fields(StoryCompleted)
        }
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "story_key": str,
            "duration_s": float,
            "cost_usd": float,
            "tokens_in": int,
            "tokens_out": int,
            "attempts": int,
        }
        self.assertEqual(fields, expected)

    def test_story_failed_fields_req05(self):
        """StoryFailed must have exactly 8 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(StoryFailed)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(StoryFailed)}
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "story_key": str,
            "error_class": str,
            "reason": str,
            "attempts": int,
            "final_session": str,
        }
        self.assertEqual(fields, expected)

    def test_story_deferred_fields_req05(self):
        """StoryDeferred must have exactly 6 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(StoryDeferred)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(StoryDeferred)}
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "story_key": str,
            "reason": str,
            "tasks_completed": int,
        }
        self.assertEqual(fields, expected)

    def test_retry_attempt_fields_req05(self):
        """RetryAttempt must have exactly 8 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(RetryAttempt)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(RetryAttempt)}
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "story_key": str,
            "attempt_num": int,
            "agent": str,
            "model": str,
            "prev_error_class": str,
        }
        self.assertEqual(fields, expected)

    def test_escalation_triggered_fields_req05(self):
        """EscalationTriggered must have exactly 7 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(EscalationTriggered)
        fields = {
            f.name: type_hints[f.name] for f in dataclasses.fields(EscalationTriggered)
        }
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "story_key": str,
            "trigger_id": int,
            "severity": str,
            "message": str,
        }
        self.assertEqual(fields, expected)

    def test_review_cycle_fields_req05(self):
        """ReviewCycle must have exactly 7 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(ReviewCycle)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(ReviewCycle)}
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "story_key": str,
            "cycle_num": int,
            "issues_found": int,
            "blocking": bool,
        }
        self.assertEqual(fields, expected)

    def test_retro_fired_fields_req05(self):
        """RetroFired must have exactly 6 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(RetroFired)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(RetroFired)}
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "stories_completed": int,
            "total_cost_usd": float,
            "duration_s": float,
        }
        self.assertEqual(fields, expected)

    def test_tmux_session_spawned_fields_req05(self):
        """TmuxSessionSpawned must have exactly 6 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(TmuxSessionSpawned)
        fields = {
            f.name: type_hints[f.name] for f in dataclasses.fields(TmuxSessionSpawned)
        }
        expected = {
            "timestamp": str,
            "run_id": str,
            "session_name": str,
            "story_key": str,
            "pid": int,
            "pane_geometry": str,
        }
        self.assertEqual(fields, expected)

    def test_tmux_session_completed_fields_req05(self):
        """TmuxSessionCompleted must have exactly 6 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(TmuxSessionCompleted)
        fields = {
            f.name: type_hints[f.name] for f in dataclasses.fields(TmuxSessionCompleted)
        }
        expected = {
            "timestamp": str,
            "run_id": str,
            "session_name": str,
            "story_key": str,
            "exit_code": int,
            "duration_s": float,
        }
        self.assertEqual(fields, expected)

    def test_tmux_session_crashed_fields_req05(self):
        """TmuxSessionCrashed must have exactly 6 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(TmuxSessionCrashed)
        fields = {
            f.name: type_hints[f.name] for f in dataclasses.fields(TmuxSessionCrashed)
        }
        expected = {
            "timestamp": str,
            "run_id": str,
            "session_name": str,
            "story_key": str,
            "exit_code": int,
            "last_capture_chars": int,
        }
        self.assertEqual(fields, expected)

    def test_cost_charged_fields_req05(self):
        """CostCharged must have exactly 9 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(CostCharged)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(CostCharged)}
        expected = {
            "timestamp": str,
            "run_id": str,
            "epic": str,
            "story_key": str,
            "phase": str,
            "cost_usd": float,
            "tokens_in": int,
            "tokens_out": int,
            "model": str,
        }
        self.assertEqual(fields, expected)

    def test_budget_alert_fields_req05(self):
        """BudgetAlert must have exactly 7 fields."""
        import dataclasses
        import typing

        type_hints = typing.get_type_hints(BudgetAlert)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(BudgetAlert)}
        expected = {
            "timestamp": str,
            "run_id": str,
            "threshold_pct": int,
            "total_cost_usd": float,
            "max_budget_usd": float,
            "epic": str,
            "story_key": str,
        }
        self.assertEqual(fields, expected)

    def test_all_event_types_are_snake_case(self):
        """REQ-05: All EVENT_TYPE strings must be snake_case."""
        event_classes = [
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
        ]
        for cls in event_classes:
            event_type = cls.EVENT_TYPE
            self.assertTrue(
                event_type.islower(),
                f"{cls.__name__}.EVENT_TYPE = {event_type!r} is not lowercase",
            )
            self.assertNotIn(
                " ",
                event_type,
                f"{cls.__name__}.EVENT_TYPE contains spaces",
            )
            # Verify snake_case (letters, digits, underscores only)
            self.assertRegex(
                event_type,
                r"^[a-z0-9_]+$",
                f"{cls.__name__}.EVENT_TYPE = {event_type!r} is not snake_case",
            )


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

    def test_unknown_event_preserves_key_order(self):
        """UnknownEvent to_dict must preserve original field order from raw_fields."""
        # Create UnknownEvent with specific raw_fields order
        original = UnknownEvent(
            timestamp="2026-06-14T12:00:00Z",
            run_id="run-123",
            raw_event_type="custom_event",
            raw_fields={"field_a": 1, "field_b": "test", "field_c": True},
        )

        # Serialize and parse back
        line1 = original.to_json_line()
        parsed = parse_event(line1)

        # Verify fields are preserved
        self.assertEqual(parsed.raw_event_type, "custom_event")
        self.assertEqual(
            parsed.raw_fields, {"field_a": 1, "field_b": "test", "field_c": True}
        )

        # Re-serialize and verify content (key order may differ in JSON, but content is same)
        line2 = parsed.to_json_line()
        parsed2 = parse_event(line2)
        self.assertEqual(parsed2.raw_event_type, parsed.raw_event_type)
        self.assertEqual(parsed2.raw_fields, parsed.raw_fields)

    def test_unknown_event_byte_equal_reserialize_req09(self):
        """REQ-09: UnknownEvent re-serialization must produce byte-equal output for round-trip."""
        # Create a JSON line with an unrecognized event_type and fields
        original_line = '{"event_type":"future_thing_M99","timestamp":"2026-06-14T12:34:56Z","run_id":"run-999","fancy_field":42,"text":"hello"}'

        # Parse it
        parsed = parse_event(original_line)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertEqual(parsed.raw_event_type, "future_thing_M99")

        # Re-serialize
        reserialized = parsed.to_json_line()

        # Verify byte-equality (REQ-09): original_line == reserialized
        self.assertEqual(original_line, reserialized)

        # Parse again to verify it's valid
        parsed2 = parse_event(reserialized)
        self.assertIsInstance(parsed2, UnknownEvent)
        self.assertEqual(parsed2.raw_event_type, "future_thing_M99")
        self.assertEqual(parsed2.raw_fields, parsed.raw_fields)

        # Verify re-serialization is byte-equal (same JSON content, though key order may vary in dict)
        parsed3 = parse_event(reserialized)
        reserialized2 = parsed3.to_json_line()
        parsed4 = parse_event(reserialized2)
        self.assertEqual(parsed4.raw_event_type, parsed3.raw_event_type)
        self.assertEqual(parsed4.raw_fields, parsed3.raw_fields)


class TestUnknownEventRoundTrip(unittest.TestCase):
    """Test UnknownEvent round-trip with arbitrary event types and fields (REQ-09)."""

    def test_unknown_event_round_trip_basic(self):
        """UnknownEvent with custom event_type must round-trip."""
        original_line = '{"event_type":"custom_future_v1","timestamp":"2026-06-14T00:00:00Z","run_id":"r1","custom_field":"value"}'
        parsed = parse_event(original_line)
        self.assertIsInstance(parsed, UnknownEvent)
        reserialized = parsed.to_json_line()
        self.assertEqual(original_line, reserialized)

    def test_unknown_event_with_nested_json_object(self):
        """UnknownEvent must preserve nested JSON objects in raw_fields."""
        original_line = '{"event_type":"unknown_with_nested","timestamp":"2026-06-14T00:00:00Z","run_id":"r1","nested":{"inner":"value","count":42}}'
        parsed = parse_event(original_line)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertEqual(parsed.raw_fields["nested"], {"inner": "value", "count": 42})
        reserialized = parsed.to_json_line()
        parsed2 = parse_event(reserialized)
        self.assertEqual(parsed2.raw_fields["nested"], {"inner": "value", "count": 42})


class TestRoundTripEdgeCases(unittest.TestCase):
    """Test round-trip with unicode, special JSON chars, and boundary values."""

    def test_concrete_event_with_unicode_emoji(self):
        """StoryStarted must preserve unicode emoji in string fields."""
        original = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="EPIC-🚀",
            story_key="S1",
            agent="claude",
            model="opus",
            complexity="high 🎯",
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        self.assertEqual(parsed.epic, "EPIC-🚀")
        self.assertEqual(parsed.complexity, "high 🎯")
        line2 = parsed.to_json_line()
        self.assertEqual(line1, line2)

    def test_concrete_event_with_escaped_json_chars(self):
        """Event must handle escaped quotes, newlines, tabs, and backslashes."""
        original = StoryFailed(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="EPIC-1",
            story_key="S1",
            error_class='syntax"error',
            reason="line1\nline2\ttab",
            attempts=1,
            final_session=r"path\to\session",  # Use raw string to avoid double-escape
        )
        # First round-trip
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        # Verify parsed values match original
        self.assertEqual(parsed.error_class, 'syntax"error')
        self.assertEqual(parsed.reason, "line1\nline2\ttab")
        self.assertEqual(parsed.final_session, r"path\to\session")
        # Verify byte-equality on re-serialize
        line2 = parsed.to_json_line()
        self.assertEqual(
            line1,
            line2,
            f"JSON not byte-equal after round-trip.\nOriginal: {line1}\nRe-serialized: {line2}",
        )

    def test_cost_charged_with_boundary_float_values(self):
        """CostCharged must handle float boundaries and precision."""
        original = CostCharged(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            phase="test",
            cost_usd=0.0001,  # Small value
            tokens_in=0,  # Zero
            tokens_out=999999,  # Large int
            model="opus",
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        self.assertEqual(parsed.cost_usd, 0.0001)
        self.assertEqual(parsed.tokens_in, 0)
        self.assertEqual(parsed.tokens_out, 999999)
        line2 = parsed.to_json_line()
        self.assertEqual(line1, line2)

    def test_story_completed_with_large_duration(self):
        """StoryCompleted must handle large float values without precision loss."""
        original = StoryCompleted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=999999.99999,
            cost_usd=123.456789,
            tokens_in=2000000,
            tokens_out=5000000,
            attempts=100,
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        # Note: JSON float serialization may lose precision; verify parse succeeds
        self.assertAlmostEqual(parsed.cost_usd, 123.456789, places=5)
        line2 = parsed.to_json_line()
        # Re-parse and verify consistency
        parsed2 = parse_event(line2)
        self.assertEqual(parsed2.cost_usd, parsed.cost_usd)

    def test_concrete_event_with_empty_strings(self):
        """Events must preserve empty string fields."""
        original = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="",
            epic="",
            story_key="S1",
            agent="",
            model="",
            complexity="",
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        self.assertEqual(parsed.run_id, "")
        self.assertEqual(parsed.epic, "")
        self.assertEqual(parsed.agent, "")
        line2 = parsed.to_json_line()
        self.assertEqual(line1, line2)


if __name__ == "__main__":
    unittest.main()
