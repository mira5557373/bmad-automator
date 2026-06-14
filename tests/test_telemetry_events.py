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


if __name__ == "__main__":
    unittest.main()
