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


if __name__ == "__main__":
    unittest.main()
