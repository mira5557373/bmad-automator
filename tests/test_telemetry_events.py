from __future__ import annotations

import unittest
from typing import ClassVar


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


if __name__ == "__main__":
    unittest.main()
