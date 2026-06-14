from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from story_automator.core.telemetry_events import Event


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import telemetry_events  # noqa: F401


class EventBaseTests(unittest.TestCase):
    def test_event_class_exposes_event_type_classvar(self) -> None:
        from story_automator.core.telemetry_events import Event

        self.assertTrue(hasattr(Event, "EVENT_TYPE"))
        self.assertEqual(Event.EVENT_TYPE, "")

    def test_event_class_exposes_registry_classvar(self) -> None:
        from story_automator.core.telemetry_events import Event

        self.assertTrue(hasattr(Event, "_REGISTRY"))
        self.assertIsInstance(Event._REGISTRY, dict)

    def test_event_dataclass_fields_are_timestamp_and_run_id(self) -> None:
        from dataclasses import fields
        from story_automator.core.telemetry_events import Event

        field_names = {f.name for f in fields(Event)}
        self.assertEqual(field_names, {"timestamp", "run_id"})

    def test_event_field_types_are_str(self) -> None:
        from dataclasses import fields
        from story_automator.core.telemetry_events import Event

        types_by_name = {f.name: f.type for f in fields(Event)}
        # With `from __future__ import annotations` types are strings.
        self.assertEqual(types_by_name["timestamp"], "str")
        self.assertEqual(types_by_name["run_id"], "str")


class _RegistryIsolationMixin:
    """Snapshots Event._REGISTRY on setUp and restores it on tearDown.

    Tests that DEFINE inner-class subclasses of Event mutate the module-
    level registry. Without isolation, a leaked `_temp_*` key from one
    test can break another. The snapshot/restore pattern is robust to
    mid-`assertRaises` aborts.
    """

    def setUp(self) -> None:
        from story_automator.core.telemetry_events import Event

        self._registry_snapshot = dict(Event._REGISTRY)

    def tearDown(self) -> None:
        from story_automator.core.telemetry_events import Event

        Event._REGISTRY.clear()
        Event._REGISTRY.update(self._registry_snapshot)


class EventRegistrationTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_subclass_with_event_type_is_registered(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempRegistered(Event):
            EVENT_TYPE: ClassVar[str] = "_temp_registered"

        self.assertIn("_temp_registered", Event._REGISTRY)
        self.assertIs(Event._REGISTRY["_temp_registered"], _TempRegistered)

    def test_subclass_without_event_type_is_not_registered(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempUnregistered(Event):
            pass

        # Confirm the class is usable AND not in the registry under "".
        instance = _TempUnregistered(timestamp="t", run_id="r")
        self.assertEqual(instance.timestamp, "t")
        self.assertNotIn("", Event._REGISTRY)


class EventDuplicateDetectionTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_duplicate_event_type_raises_runtime_error(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _DupFirst(Event):
            EVENT_TYPE: ClassVar[str] = "_dup_key"

        with self.assertRaises(RuntimeError):

            @dataclass
            class _DupSecond(Event):  # noqa: F841 — declaration triggers __init_subclass__
                EVENT_TYPE: ClassVar[str] = "_dup_key"

    def test_duplicate_error_message_contains_both_qualnames(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _DupQualA(Event):
            EVENT_TYPE: ClassVar[str] = "_dup_qual"

        with self.assertRaises(RuntimeError) as ctx:

            @dataclass
            class _DupQualB(Event):  # noqa: F841
                EVENT_TYPE: ClassVar[str] = "_dup_qual"

        message = str(ctx.exception)
        self.assertIn("_dup_qual", message)
        self.assertIn(_DupQualA.__qualname__, message)
        # The second class's qualname is harder to obtain post-raise
        # (the class binding never completes). The implementation must
        # embed `cls.__qualname__` BEFORE raising, so assert the
        # expected suffix shape:
        self.assertIn("_DupQualB", message)


class EventIdempotencyTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_same_class_reregistration_does_not_raise(self) -> None:
        """Identity check `existing is not cls` lets the same class
        re-trigger __init_subclass__ (e.g., under module reload) without
        raising a spurious RuntimeError.

        This is the canonical test for the idempotency NFR. We do NOT
        use importlib.reload here — reload mutates the module's class
        identity, which can pollute cross-TestCase state and confuse
        the snapshot/restore mixin. Calling __init_subclass__ directly
        on the same class exercises the exact code path that matters."""
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _Reentrant(Event):
            EVENT_TYPE: ClassVar[str] = "_reentrant_check"

        registered_first = Event._REGISTRY["_reentrant_check"]
        self.assertIs(registered_first, _Reentrant)

        # Python wraps __init_subclass__ as an implicit classmethod;
        # __func__ gives the underlying function so we can invoke it
        # with an explicit `cls` argument matching the same identity
        # that's already in the registry.
        init_subclass = Event.__init_subclass__.__func__  # type: ignore[attr-defined]
        try:
            init_subclass(_Reentrant)
        except RuntimeError as exc:
            self.fail(f"identity check failed: re-registration raised {exc!r}")

        # Registry entry unchanged — not cleared, not duplicated.
        self.assertIs(Event._REGISTRY["_reentrant_check"], registered_first)

    def test_different_class_same_event_type_still_raises(self) -> None:
        """Companion negative test: confirm the identity check is
        SPECIFIC to identity — two different class objects sharing the
        same EVENT_TYPE must still raise (this is REQ-03 from a
        different angle and protects against an over-eager identity
        check that accidentally accepts any class)."""
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _IdFirst(Event):
            EVENT_TYPE: ClassVar[str] = "_idemp_negative"

        with self.assertRaises(RuntimeError):

            @dataclass
            class _IdSecond(Event):  # noqa: F841
                EVENT_TYPE: ClassVar[str] = "_idemp_negative"


class EventToDictTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_to_dict_injects_event_type_from_classvar(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempToDict(Event):
            EVENT_TYPE: ClassVar[str] = "_to_dict_test"

        data = _TempToDict(timestamp="t", run_id="r").to_dict()
        self.assertEqual(data["event_type"], "_to_dict_test")

    def test_to_dict_event_type_is_first_key(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempOrder(Event):
            EVENT_TYPE: ClassVar[str] = "_order_test"

        keys = list(_TempOrder(timestamp="t", run_id="r").to_dict().keys())
        self.assertEqual(keys[0], "event_type")

    def test_to_dict_includes_envelope_fields(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempEnv(Event):
            EVENT_TYPE: ClassVar[str] = "_env_test"

        data = _TempEnv(timestamp="ts-value", run_id="rid-value").to_dict()
        self.assertEqual(data["timestamp"], "ts-value")
        self.assertEqual(data["run_id"], "rid-value")

    def test_to_dict_returns_plain_dict(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempType(Event):
            EVENT_TYPE: ClassVar[str] = "_type_test"

        data = _TempType(timestamp="t", run_id="r").to_dict()
        # to_dict must return a builtin dict for json.dumps compatibility.
        self.assertIs(type(data), dict)


class EventToJsonLineTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_to_json_line_is_single_line(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempLine(Event):
            EVENT_TYPE: ClassVar[str] = "_line_test"

        line = _TempLine(timestamp="t", run_id="r").to_json_line()
        self.assertNotIn("\n", line)

    def test_to_json_line_has_no_trailing_newline(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempNoNl(Event):
            EVENT_TYPE: ClassVar[str] = "_no_nl_test"

        line = _TempNoNl(timestamp="t", run_id="r").to_json_line()
        self.assertFalse(line.endswith("\n"))

    def test_to_json_line_uses_compact_separators(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempCompact(Event):
            EVENT_TYPE: ClassVar[str] = "_compact_test"

        line = _TempCompact(timestamp="t", run_id="r").to_json_line()
        # compact_json uses (",", ":") — no whitespace after either.
        self.assertNotIn(": ", line)
        self.assertNotIn(", ", line)

    def test_to_json_line_matches_to_dict_via_compact_json(self) -> None:
        import json
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempMatch(Event):
            EVENT_TYPE: ClassVar[str] = "_match_test"

        instance = _TempMatch(timestamp="t", run_id="r")
        line = instance.to_json_line()
        # The line must parse back to the same dict to_dict returns.
        self.assertEqual(json.loads(line), instance.to_dict())

    def test_to_json_line_byte_output_is_deterministic(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import Event

        @dataclass
        class _TempBytes(Event):
            EVENT_TYPE: ClassVar[str] = "_byte_stable"

        line = _TempBytes(timestamp="ts1", run_id="rid1").to_json_line()
        # Strict byte-level assertion: guards the future REQ-08 round-trip
        # invariant against silent regressions in compact_json's separator
        # policy, asdict's field ordering, or to_dict's key insertion order.
        # The existing property tests (no spaces, event_type-first) catch
        # the obvious cases; this one pins the exact wire format.
        self.assertEqual(
            line,
            '{"event_type":"_byte_stable","timestamp":"ts1","run_id":"rid1"}',
        )


class EventImportContractTests(unittest.TestCase):
    def test_module_re_exports_iso_now(self) -> None:
        from story_automator.core import telemetry_events
        from story_automator.core.common import iso_now as canonical

        self.assertIs(telemetry_events.iso_now, canonical)

    def test_module_re_exports_compact_json(self) -> None:
        from story_automator.core import telemetry_events
        from story_automator.core.common import compact_json as canonical

        self.assertIs(telemetry_events.compact_json, canonical)

    def test_module_all_lists_event_and_helpers(self) -> None:
        from story_automator.core import telemetry_events

        self.assertIn("Event", telemetry_events.__all__)
        self.assertIn("iso_now", telemetry_events.__all__)
        self.assertIn("compact_json", telemetry_events.__all__)

    def test_module_does_not_redefine_iso_now(self) -> None:
        # Guard against a future regression where someone re-implements
        # the helper inside this module. The function object must be
        # IDENTITY-equal to the one in core.common.
        from story_automator.core import telemetry_events
        from story_automator.core import common

        self.assertIs(telemetry_events.iso_now, common.iso_now)
        self.assertIs(telemetry_events.compact_json, common.compact_json)


class UnknownEventTests(unittest.TestCase):
    def test_unknown_event_class_exists(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        self.assertTrue(hasattr(UnknownEvent, "EVENT_TYPE"))
        self.assertEqual(UnknownEvent.EVENT_TYPE, "")

    def test_unknown_event_dataclass_fields(self) -> None:
        from dataclasses import fields
        from story_automator.core.telemetry_events import UnknownEvent

        field_names = {f.name for f in fields(UnknownEvent)}
        # Inherits timestamp + run_id from Event; adds raw_event_type + raw_fields.
        self.assertEqual(
            field_names,
            {"timestamp", "run_id", "raw_event_type", "raw_fields"},
        )

    def test_unknown_event_constructs_with_required_fields(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        instance = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="future_thing_M99",
            raw_fields={"alpha": 1, "beta": "two"},
        )
        self.assertEqual(instance.timestamp, "t")
        self.assertEqual(instance.run_id, "r")
        self.assertEqual(instance.raw_event_type, "future_thing_M99")
        self.assertEqual(instance.raw_fields, {"alpha": 1, "beta": "two"})

    def test_unknown_event_not_in_registry(self) -> None:
        from story_automator.core.telemetry_events import Event, UnknownEvent

        # Direct lookup by the empty-string EVENT_TYPE must not return
        # UnknownEvent (and must not even contain the empty string as a key).
        self.assertNotIn("", Event._REGISTRY)
        # Defense in depth: scan all registered classes to confirm
        # UnknownEvent is not present under any key (e.g., if a future
        # refactor accidentally registered it under a different string).
        for registered_cls in Event._REGISTRY.values():
            self.assertIsNot(registered_cls, UnknownEvent)


class UnknownEventToDictTests(unittest.TestCase):
    def test_to_dict_event_type_is_raw_event_type(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        instance = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="future_thing_M99",
            raw_fields={"alpha": 1},
        )
        data = instance.to_dict()
        self.assertEqual(data["event_type"], "future_thing_M99")

    def test_to_dict_includes_envelope_fields(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        data = UnknownEvent(
            timestamp="ts-value",
            run_id="rid-value",
            raw_event_type="x",
            raw_fields={},
        ).to_dict()
        self.assertEqual(data["timestamp"], "ts-value")
        self.assertEqual(data["run_id"], "rid-value")

    def test_to_dict_merges_raw_fields_at_top_level(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        data = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="x",
            raw_fields={"alpha": 1, "beta": "two", "gamma": [3]},
        ).to_dict()
        self.assertEqual(data["alpha"], 1)
        self.assertEqual(data["beta"], "two")
        self.assertEqual(data["gamma"], [3])

    def test_to_dict_excludes_internal_field_names(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        data = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="x",
            raw_fields={"alpha": 1},
        ).to_dict()
        # The internal field names raw_event_type/raw_fields MUST NOT appear
        # in the output dict — they are implementation details. The output is
        # the wire representation: event_type + envelope + payload fields.
        self.assertNotIn("raw_event_type", data)
        self.assertNotIn("raw_fields", data)

    def test_to_dict_key_order_is_event_type_then_envelope_then_fields(self) -> None:
        from story_automator.core.telemetry_events import UnknownEvent

        data = UnknownEvent(
            timestamp="t",
            run_id="r",
            raw_event_type="x",
            raw_fields={"alpha": 1, "beta": 2},
        ).to_dict()
        keys = list(data.keys())
        # Canonical order: event_type, timestamp, run_id, then raw_fields keys
        # in their insertion order. This is the contract that lets REQ-04's
        # "byte-equal to the original input line" hold when the original input
        # was itself canonically ordered.
        self.assertEqual(keys[:3], ["event_type", "timestamp", "run_id"])
        self.assertEqual(keys[3:], ["alpha", "beta"])


class ParseEventHappyPathTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_parse_known_event_type_dispatches_to_subclass(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import (
            Event,
            compact_json,
            parse_event,
        )

        @dataclass
        class _ParsedFoo(Event):
            EVENT_TYPE: ClassVar[str] = "_parsed_foo"
            payload: str

        line = compact_json(
            {
                "event_type": "_parsed_foo",
                "timestamp": "t",
                "run_id": "r",
                "payload": "hi",
            }
        )
        event = parse_event(line)
        self.assertIs(type(event), _ParsedFoo)
        self.assertEqual(event.timestamp, "t")
        self.assertEqual(event.run_id, "r")
        self.assertEqual(event.payload, "hi")

    def test_parse_unknown_event_type_routes_to_unknown_event(self) -> None:
        from story_automator.core.telemetry_events import (
            UnknownEvent,
            compact_json,
            parse_event,
        )

        line = compact_json(
            {
                "event_type": "future_thing_M99",
                "timestamp": "t",
                "run_id": "r",
                "anything": 42,
                "other": "value",
            }
        )
        event = parse_event(line)
        self.assertIs(type(event), UnknownEvent)
        self.assertEqual(event.raw_event_type, "future_thing_M99")
        self.assertEqual(event.timestamp, "t")
        self.assertEqual(event.run_id, "r")
        self.assertEqual(event.raw_fields, {"anything": 42, "other": "value"})


class ParseEventErrorPathTests(_RegistryIsolationMixin, unittest.TestCase):
    def test_parse_missing_event_type_raises_value_error(self) -> None:
        from story_automator.core.telemetry_events import compact_json, parse_event

        line = compact_json({"timestamp": "t", "run_id": "r"})
        with self.assertRaises(ValueError) as ctx:
            parse_event(line)
        # The error message must mention the missing field by name so an
        # operator scanning a log can identify the problem at a glance.
        self.assertIn("event_type", str(ctx.exception))

    def test_parse_invalid_json_propagates_json_decode_error(self) -> None:
        import json
        from story_automator.core.telemetry_events import parse_event

        with self.assertRaises(json.JSONDecodeError):
            parse_event("this is not json {{{")

    def test_parse_empty_string_propagates_json_decode_error(self) -> None:
        import json
        from story_automator.core.telemetry_events import parse_event

        with self.assertRaises(json.JSONDecodeError):
            parse_event("")

    def test_parse_typed_event_missing_required_field_raises_type_error(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import (
            Event,
            compact_json,
            parse_event,
        )

        @dataclass
        class _RequiresPayload(Event):
            EVENT_TYPE: ClassVar[str] = "_requires_payload"
            payload: str  # required, no default

        line = compact_json(
            {
                "event_type": "_requires_payload",
                "timestamp": "t",
                "run_id": "r",
                # 'payload' deliberately omitted
            }
        )
        with self.assertRaises(TypeError) as ctx:
            parse_event(line)
        # Dataclass __init__ raises with the field name embedded so a
        # consumer can identify the missing field. This is a property of
        # CPython's dataclass implementation — REQ-07 relies on it.
        self.assertIn("payload", str(ctx.exception))

    def test_parse_typed_event_extra_field_raises_type_error(self) -> None:
        from dataclasses import dataclass
        from story_automator.core.telemetry_events import (
            Event,
            compact_json,
            parse_event,
        )

        @dataclass
        class _NoExtras(Event):
            EVENT_TYPE: ClassVar[str] = "_no_extras"
            # No additional fields — only inherits timestamp + run_id.

        line = compact_json(
            {
                "event_type": "_no_extras",
                "timestamp": "t",
                "run_id": "r",
                "uninvited": "guest",
            }
        )
        with self.assertRaises(TypeError) as ctx:
            parse_event(line)
        # Dataclass __init__ rejects unexpected kwargs by name. Strict
        # construction is a property of CPython we lean on for REQ-07.
        self.assertIn("uninvited", str(ctx.exception))

    def test_parse_top_level_array_raises_value_error(self) -> None:
        from story_automator.core.telemetry_events import parse_event

        # JSONL events are JSON objects. A top-level array can't be
        # dispatched by event_type. Without the explicit isinstance
        # guard this would surface as the less specific "missing
        # event_type" ValueError (because "event_type" not in [1,2,3]
        # is True). With the guard the message clearly identifies the
        # type problem at the top of the function.
        with self.assertRaises(ValueError) as ctx:
            parse_event("[1, 2, 3]")
        self.assertIn("JSON object", str(ctx.exception))

    def test_parse_top_level_string_raises_value_error(self) -> None:
        from story_automator.core.telemetry_events import parse_event

        # Catches the most dangerous of the non-object cases: a top-level
        # JSON string that happens to contain the substring "event_type"
        # used to slip past the membership check and fail with
        # AttributeError on the subsequent payload.pop. The dict-type
        # guard makes the error a clean ValueError instead.
        with self.assertRaises(ValueError) as ctx:
            parse_event('"event_type_in_a_string"')
        self.assertIn("JSON object", str(ctx.exception))

    def test_parse_top_level_number_raises_value_error(self) -> None:
        from story_automator.core.telemetry_events import parse_event

        with self.assertRaises(ValueError) as ctx:
            parse_event("42")
        self.assertIn("JSON object", str(ctx.exception))

    def test_parse_top_level_null_raises_value_error(self) -> None:
        from story_automator.core.telemetry_events import parse_event

        with self.assertRaises(ValueError) as ctx:
            parse_event("null")
        self.assertIn("JSON object", str(ctx.exception))


class UnknownEventByteEqualPreservationTests(unittest.TestCase):
    def test_round_trip_preserves_byte_equal_for_canonical_input(self) -> None:
        from story_automator.core.telemetry_events import (
            UnknownEvent,
            compact_json,
            parse_event,
        )

        # The original line is built via compact_json so it is canonically
        # ordered (event_type, timestamp, run_id, then payload fields in
        # insertion order). This is the contract REQ-04's "byte-equal to
        # the original input line" relies on — lines produced by
        # to_json_line are always canonically ordered, so round-trip is
        # byte-equal for any input that came out of the typed-telemetry
        # substrate. Hand-built JSON in arbitrary key order is NOT
        # required to round-trip byte-equal (and m01-m4 does not extend
        # that property either).
        original = compact_json(
            {
                "event_type": "future_thing_M99",
                "timestamp": "2026-06-14T05:12:34Z",
                "run_id": "20260614-051234",
                "alpha": 1,
                "beta": "two",
                "gamma": [1, 2, 3],
                "delta": {"nested": True},
            }
        )
        parsed = parse_event(original)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertEqual(parsed.raw_event_type, "future_thing_M99")

        reemitted = parsed.to_json_line()
        # Strict byte-level equality: guards against any future regression
        # in compact_json's separator policy, UnknownEvent.to_dict's key
        # insertion order, or dict.update's behavior for raw_fields. The
        # property-level tests in UnknownEventToDictTests (Task 4) catch
        # the obvious cases; this one pins the exact wire format.
        self.assertEqual(reemitted, original)


class ParseEventExportContractTests(unittest.TestCase):
    def test_module_exports_unknown_event_in_all(self) -> None:
        from story_automator.core import telemetry_events

        self.assertIn("UnknownEvent", telemetry_events.__all__)

    def test_module_exports_parse_event_in_all(self) -> None:
        from story_automator.core import telemetry_events

        self.assertIn("parse_event", telemetry_events.__all__)

    def test_module_exports_are_callable_from_top_level(self) -> None:
        # Both must be reachable via `from .telemetry_events import X`
        # (smoke-tests that __all__ matches the actually-defined names).
        from story_automator.core.telemetry_events import (  # noqa: F401
            UnknownEvent,
            parse_event,
        )

        self.assertTrue(callable(parse_event))
        self.assertTrue(isinstance(UnknownEvent, type))


class ConcreteEventRoundTripTests(unittest.TestCase):
    """REQ-08: round-trip invariant for every concrete event class.

    For each of the 13 concrete event classes the round trip
    ``instance -> to_json_line -> parse_event`` must return an instance
    of the same class that compares equal via dataclass ``__eq__`` and
    whose own ``to_json_line`` output is byte-equal to the original
    line. This catches any drift in field declaration order, in the
    ``to_dict`` key insertion order, or in ``compact_json``'s separator
    policy.
    """

    def _round_trip(self, event: Event) -> None:
        from story_automator.core.telemetry_events import parse_event

        line = event.to_json_line()
        parsed = parse_event(line)
        self.assertIs(type(parsed), type(event))
        self.assertEqual(parsed, event)
        self.assertEqual(parsed.to_json_line(), line)

    def test_story_started_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryStarted

        self._round_trip(
            StoryStarted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                agent="claude",
                model="sonnet",
                complexity="medium",
            )
        )

    def test_story_completed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryCompleted

        self._round_trip(
            StoryCompleted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                duration_s=42.5,
                cost_usd=1.23,
                tokens_in=1000,
                tokens_out=500,
                attempts=2,
            )
        )

    def test_story_failed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryFailed

        self._round_trip(
            StoryFailed(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                error_class="CRASH",
                reason="exit code 1",
                attempts=5,
                final_session="sa-foo-abc123",
            )
        )

    def test_story_deferred_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryDeferred

        self._round_trip(
            StoryDeferred(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                reason="plateau",
                tasks_completed=4,
            )
        )

    def test_retry_attempt_round_trip(self) -> None:
        from story_automator.core.telemetry_events import RetryAttempt

        self._round_trip(
            RetryAttempt(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                attempt_num=3,
                agent="claude",
                model="opus",
                prev_error_class="TIMEOUT",
            )
        )

    def test_escalation_triggered_round_trip(self) -> None:
        from story_automator.core.telemetry_events import EscalationTriggered

        self._round_trip(
            EscalationTriggered(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                trigger_id=4,
                severity="CRITICAL",
                message="story file missing",
            )
        )

    def test_review_cycle_round_trip(self) -> None:
        from story_automator.core.telemetry_events import ReviewCycle

        self._round_trip(
            ReviewCycle(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                cycle_num=2,
                issues_found=3,
                blocking=True,
            )
        )

    def test_retro_fired_round_trip(self) -> None:
        from story_automator.core.telemetry_events import RetroFired

        self._round_trip(
            RetroFired(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                stories_completed=5,
                total_cost_usd=12.34,
                duration_s=300.0,
            )
        )

    def test_tmux_session_spawned_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionSpawned

        self._round_trip(
            TmuxSessionSpawned(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                session_name="sa-foo-abc123",
                story_key="3.1",
                pid=12345,
                pane_geometry="200x50",
            )
        )

    def test_tmux_session_completed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionCompleted

        self._round_trip(
            TmuxSessionCompleted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                session_name="sa-foo-abc123",
                story_key="3.1",
                exit_code=0,
                duration_s=45.0,
            )
        )

    def test_tmux_session_crashed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionCrashed

        self._round_trip(
            TmuxSessionCrashed(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                session_name="sa-foo-abc123",
                story_key="3.1",
                exit_code=137,
                last_capture_chars=4096,
            )
        )

    def test_cost_charged_round_trip(self) -> None:
        from story_automator.core.telemetry_events import CostCharged

        self._round_trip(
            CostCharged(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                phase="dev",
                cost_usd=0.45,
                tokens_in=2000,
                tokens_out=800,
                model="sonnet",
            )
        )

    def test_budget_alert_round_trip(self) -> None:
        from story_automator.core.telemetry_events import BudgetAlert

        self._round_trip(
            BudgetAlert(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                threshold_pct=75,
                total_cost_usd=15.0,
                max_budget_usd=20.0,
                epic="3",
                story_key="3.1",
            )
        )


class RegistryCompletenessTests(unittest.TestCase):
    """REQ-06: after module import Event._REGISTRY contains exactly 13
    entries keyed by the concrete classes' EVENT_TYPE strings; UnknownEvent
    must NOT be present.

    Uses a module-level filter that excludes leading-underscore keys so a
    leaked ``_temp_*`` sentinel from a test that aborted before
    ``_RegistryIsolationMixin.tearDown`` cleared it cannot mask a missing
    production event_type.
    """

    EXPECTED_EVENT_TYPES = frozenset(
        {
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
    )

    def test_registry_contains_exactly_thirteen_production_entries(self) -> None:
        from story_automator.core.telemetry_events import Event

        production = {k for k in Event._REGISTRY if not k.startswith("_")}
        self.assertEqual(len(production), 13)
        self.assertEqual(production, self.EXPECTED_EVENT_TYPES)

    def test_unknown_event_is_not_a_registered_value(self) -> None:
        from story_automator.core.telemetry_events import Event, UnknownEvent

        for cls in Event._REGISTRY.values():
            self.assertIsNot(cls, UnknownEvent)

    def test_each_registered_class_event_type_matches_its_key(self) -> None:
        from story_automator.core.telemetry_events import Event

        # Guards against a future regression where the registry key drifts
        # from the class's own EVENT_TYPE classvar (e.g., a subclass that
        # overrides EVENT_TYPE after registration in an init hook).
        for key, cls in Event._REGISTRY.items():
            self.assertEqual(cls.EVENT_TYPE, key)


class ConcreteEventExportContractTests(unittest.TestCase):
    """REQ-05 implication: the 13 concrete classes must be importable
    via the documented module path. ``__all__`` pins the surface so
    ``from story_automator.core.telemetry_events import *`` works as
    documented in the design doc, and so future renames are caught
    by this gate rather than at downstream call sites.
    """

    # Only the 13 concrete classes. The base ``Event`` / fallback ``UnknownEvent`` /
    # function ``parse_event`` / helpers ``iso_now`` + ``compact_json`` are pinned by
    # m01-m1's ``EventImportContractTests`` and m01-m2's ``ParseEventExportContractTests``.
    # This tuple is the m01-m3 delta — adding the base/fallback/parser here would
    # double-cover them and tightly couple this test class to upstream slice contracts.
    EXPECTED_NAMES = (
        "BudgetAlert",
        "CostCharged",
        "EscalationTriggered",
        "RetroFired",
        "RetryAttempt",
        "ReviewCycle",
        "StoryCompleted",
        "StoryDeferred",
        "StoryFailed",
        "StoryStarted",
        "TmuxSessionCompleted",
        "TmuxSessionCrashed",
        "TmuxSessionSpawned",
    )

    def test_all_thirteen_concrete_classes_are_in_dunder_all(self) -> None:
        from story_automator.core import telemetry_events

        for name in self.EXPECTED_NAMES:
            self.assertIn(
                name,
                telemetry_events.__all__,
                f"{name} missing from __all__",
            )

    def test_all_thirteen_concrete_classes_are_importable_top_level(self) -> None:
        # Smoke test: every name in EXPECTED_NAMES resolves to a class
        # attribute on the module (and is not None / not a function).
        from story_automator.core import telemetry_events

        for name in self.EXPECTED_NAMES:
            obj = getattr(telemetry_events, name, None)
            self.assertIsNotNone(obj, f"{name} is not defined")
            self.assertTrue(isinstance(obj, type), f"{name} is not a class")


class ConcreteEventRoundTripExtendedTests(unittest.TestCase):
    """REQ-08 broader sweep: round-trip holds under unicode, JSON-special
    characters, and numeric / boolean edge cases.

    m01-m3 verified the per-class happy path with ASCII fixtures. This
    class broadens the verification to confirm that `compact_json`'s
    `ensure_ascii=False` policy preserves unicode in string fields
    byte-equal, that JSON-special characters in strings are escaped and
    parsed back identically, and that integer / float / boolean
    boundary values survive the serialization round-trip without drift.
    """

    def _round_trip(self, event: Event) -> None:
        from story_automator.core.telemetry_events import parse_event

        line = event.to_json_line()
        parsed = parse_event(line)
        self.assertIs(type(parsed), type(event))
        self.assertEqual(parsed, event)
        self.assertEqual(parsed.to_json_line(), line)

    def test_round_trip_preserves_unicode_in_string_fields(self) -> None:
        """REQ-08 + NFR: `compact_json(ensure_ascii=False)` must emit
        non-ASCII codepoints natively (not as `\\uXXXX` escapes), and
        parse_event must round-trip them byte-equal. Covers the operator's
        real-world case of unicode in story titles or epic names.
        """
        from story_automator.core.telemetry_events import StoryStarted

        self._round_trip(
            StoryStarted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="エピック-3",
                story_key="3.1-héllo-世界",
                agent="クロード",
                model="sonnet",
                complexity="medium",
            )
        )

    def test_round_trip_preserves_json_special_characters_in_strings(self) -> None:
        """REQ-08 + NFR: JSON-special characters (`"`, `\\`, control
        characters) must be escaped on emission and parsed back byte-
        identically. The strict-byte-equal round-trip is the contract
        that lets the JSONL stream be transported through any utf-8 pipe
        without corruption.
        """
        from story_automator.core.telemetry_events import StoryFailed

        self._round_trip(
            StoryFailed(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                error_class="CRASH",
                # Embedded double-quote, backslash, tab, and newline must all
                # round-trip exactly. json.dumps escapes them; json.loads un-
                # escapes them; the assertion is that the second emission of
                # to_json_line yields the same escape sequences.
                reason='exit code 1: "fatal" \\ stderr=foo\tbar\nline2',
                attempts=5,
                final_session="sa-foo-abc123",
            )
        )

    def test_round_trip_preserves_numeric_edge_cases(self) -> None:
        """REQ-08 + NFR: integer / float boundary values (zero, negative,
        large, fractional) must survive the round-trip. ``json.dumps``
        emits ``0`` for int zero and ``0.0`` for float zero — distinct
        wire forms — so the round-trip preserves both type identity and
        byte representation.
        """
        from story_automator.core.telemetry_events import StoryCompleted

        self._round_trip(
            StoryCompleted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                duration_s=0.0,
                cost_usd=999_999.123456,
                tokens_in=0,
                tokens_out=2_147_483_648,
                attempts=1,
            )
        )

    def test_round_trip_preserves_boolean_both_values(self) -> None:
        """REQ-08 + NFR: ``ReviewCycle.blocking`` is the only bool field
        in the M01 type set. Both ``True`` and ``False`` must round-trip,
        and the wire form must use lowercase JSON booleans (``true`` /
        ``false``), not the Python repr (``True`` / ``False``). This is
        guaranteed by ``json.dumps``; the test pins the behavior.
        """
        from story_automator.core.telemetry_events import ReviewCycle

        for blocking_value in (True, False):
            with self.subTest(blocking=blocking_value):
                self._round_trip(
                    ReviewCycle(
                        timestamp="2026-06-14T05:12:34Z",
                        run_id="20260614-051234",
                        epic="3",
                        story_key="3.1",
                        cycle_num=2,
                        issues_found=3,
                        blocking=blocking_value,
                    )
                )


if __name__ == "__main__":
    unittest.main()
