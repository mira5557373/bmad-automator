from __future__ import annotations

import unittest


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


if __name__ == "__main__":
    unittest.main()
