from __future__ import annotations

import dataclasses
import importlib
import unittest

from tests.golden_trace_helpers import GoldenTraceError, TraceEntry


class ModuleImportTests(unittest.TestCase):
    def test_module_imports_cleanly(self) -> None:
        module = importlib.import_module("tests.golden_trace_helpers")
        self.assertTrue(hasattr(module, "__all__"))

    def test_module_exports_expected_symbols(self) -> None:
        module = importlib.import_module("tests.golden_trace_helpers")
        expected = {
            "Channel",
            "GoldenTraceError",
            "MismatchField",
            "TraceDiff",
            "TraceEntry",
            "TraceMismatch",
            "compare_traces",
            "load_golden",
            "serialize_trace",
        }
        self.assertEqual(set(module.__all__), expected)


class GoldenTraceErrorTests(unittest.TestCase):
    def test_is_value_error_subclass(self) -> None:
        self.assertTrue(issubclass(GoldenTraceError, ValueError))

    def test_carries_message(self) -> None:
        err = GoldenTraceError("unknown channel 'foo'")
        self.assertIn("unknown channel", str(err))


class TraceEntryTests(unittest.TestCase):
    def test_is_frozen_kw_only_dataclass(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(TraceEntry))
        params = TraceEntry.__dataclass_params__  # type: ignore[attr-defined]
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_required_fields_present(self) -> None:
        names = {f.name for f in dataclasses.fields(TraceEntry)}
        self.assertEqual(names, {"seq", "channel", "kind", "payload"})

    def test_construct_and_equality(self) -> None:
        a = TraceEntry(
            seq=0, channel="event", kind="StoryStarted", payload={"epic": "1"}
        )
        b = TraceEntry(
            seq=0, channel="event", kind="StoryStarted", payload={"epic": "1"}
        )
        self.assertEqual(a, b)

    def test_frozen_blocks_mutation(self) -> None:
        entry = TraceEntry(
            seq=0, channel="state", kind="mutation", payload={"path": "x"}
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.seq = 1  # type: ignore[misc]

    def test_positional_construction_rejected(self) -> None:
        # kw_only=True must forbid positional args.
        with self.assertRaises(TypeError):
            TraceEntry(0, "event", "StoryStarted", {})  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
