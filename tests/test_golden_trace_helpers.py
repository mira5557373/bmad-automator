from __future__ import annotations

import dataclasses
import importlib
import tempfile
import unittest
from pathlib import Path

from tests.golden_trace_helpers import (
    GoldenTraceError,
    TraceDiff,
    TraceEntry,
    TraceMismatch,
    load_golden,
    serialize_trace,
)


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


class TraceMismatchTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(TraceMismatch))
        params = TraceMismatch.__dataclass_params__  # type: ignore[attr-defined]
        self.assertTrue(params.kw_only)
        # Not frozen — caller may want to attach diagnostics later.
        self.assertFalse(params.frozen)

    def test_required_fields(self) -> None:
        names = {f.name for f in dataclasses.fields(TraceMismatch)}
        self.assertEqual(names, {"seq", "field", "actual", "expected"})

    def test_construct_with_payload_diff(self) -> None:
        m = TraceMismatch(seq=3, field="payload", actual={"a": 1}, expected={"a": 2})
        self.assertEqual(m.seq, 3)
        self.assertEqual(m.field, "payload")
        self.assertEqual(m.actual, {"a": 1})
        self.assertEqual(m.expected, {"a": 2})

    def test_actual_and_expected_allow_none(self) -> None:
        # PEP 604 object | None per REQ-10 — used for "length" mismatches
        # where one side has no entry at that seq.
        m = TraceMismatch(seq=5, field="length", actual=None, expected={"x": 1})
        self.assertIsNone(m.actual)
        self.assertEqual(m.expected, {"x": 1})


class TraceDiffTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        self.assertTrue(dataclasses.is_dataclass(TraceDiff))
        params = TraceDiff.__dataclass_params__  # type: ignore[attr-defined]
        self.assertTrue(params.kw_only)

    def test_required_fields(self) -> None:
        names = {f.name for f in dataclasses.fields(TraceDiff)}
        self.assertEqual(names, {"matched", "mismatches", "ok"})

    def test_empty_mismatches_is_ok(self) -> None:
        d = TraceDiff(matched=3, mismatches=[], ok=True)
        self.assertTrue(d.ok)

    def test_summary_includes_seq_and_field_for_each_mismatch(self) -> None:
        m1 = TraceMismatch(seq=2, field="payload", actual={"x": 1}, expected={"x": 2})
        m2 = TraceMismatch(seq=4, field="kind", actual="A", expected="B")
        d = TraceDiff(matched=2, mismatches=[m1, m2], ok=False)
        text = d.summary()
        # Each mismatch is mentioned by seq and field; field-context lets a
        # reader localize the regression without consulting the golden file.
        self.assertIn("seq=2", text)
        self.assertIn("payload", text)
        self.assertIn("seq=4", text)
        self.assertIn("kind", text)

    def test_summary_for_ok_diff_is_succinct(self) -> None:
        d = TraceDiff(matched=5, mismatches=[], ok=True)
        text = d.summary()
        self.assertIn("ok", text.lower())
        self.assertIn("5", text)


class SerializeTraceTests(unittest.TestCase):
    def _entry(self, seq: int) -> "TraceEntry":
        return TraceEntry(
            seq=seq,
            channel="event",
            kind="StoryStarted",
            payload={"z": 2, "a": 1, "m": [3, 2, 1]},
        )

    def test_returns_str_with_trailing_newline(self) -> None:
        out = serialize_trace([self._entry(0)])
        self.assertIsInstance(out, str)
        self.assertTrue(out.endswith("\n"))

    def test_compact_separators(self) -> None:
        out = serialize_trace([self._entry(0)])
        # REQ-07 separators=(",", ":") => no whitespace between tokens.
        self.assertNotIn(", ", out)
        self.assertNotIn(": ", out)

    def test_keys_are_sorted(self) -> None:
        out = serialize_trace([self._entry(0)]).rstrip("\n")
        # Both the entry-level keys and nested payload keys must be sorted.
        # Entry-level: channel < kind < payload < seq.
        self.assertLess(out.index('"channel"'), out.index('"kind"'))
        self.assertLess(out.index('"kind"'), out.index('"payload"'))
        self.assertLess(out.index('"payload"'), out.index('"seq"'))
        # Nested payload: a < m < z.
        self.assertLess(out.index('"a"'), out.index('"m"'))
        self.assertLess(out.index('"m"'), out.index('"z"'))

    def test_empty_list_serializes_to_bracket_newline(self) -> None:
        self.assertEqual(serialize_trace([]), "[]\n")

    def test_determinism_byte_identical_across_calls(self) -> None:
        entries = [self._entry(i) for i in range(5)]
        first = serialize_trace(entries)
        second = serialize_trace(entries)
        self.assertEqual(first, second)
        self.assertEqual(first.encode("utf-8"), second.encode("utf-8"))

    def test_determinism_independent_of_payload_key_insertion_order(self) -> None:
        # Same logical payload constructed in two different insertion orders
        # must serialize byte-identically — this is what enables byte-equal
        # comparison across runs (NFR: Determinism).
        a = TraceEntry(seq=0, channel="event", kind="X", payload={"a": 1, "b": 2})
        b = TraceEntry(seq=0, channel="event", kind="X", payload={"b": 2, "a": 1})
        self.assertEqual(serialize_trace([a]), serialize_trace([b]))


class LoadGoldenHappyPathTests(unittest.TestCase):
    def test_round_trip_serialize_then_load(self) -> None:
        entries = [
            TraceEntry(
                seq=0, channel="event", kind="StoryStarted", payload={"epic": "1"}
            ),
            TraceEntry(
                seq=1,
                channel="state",
                kind="mutation",
                payload={"path": "state.json", "sha256": "abc"},
            ),
            TraceEntry(
                seq=2,
                channel="claude_p",
                kind="invoke",
                payload={"argv": ["claude", "-p"]},
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.json"
            path.write_text(serialize_trace(entries), encoding="utf-8")
            loaded = load_golden(path)
        self.assertEqual(loaded, entries)

    def test_load_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text("[]\n", encoding="utf-8")
            loaded = load_golden(path)
        self.assertEqual(loaded, [])


if __name__ == "__main__":
    unittest.main()
