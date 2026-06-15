from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import os
import tempfile
import threading as _threading
import unittest
from pathlib import Path

from story_automator.commands import state as _state_module
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_events import StoryStarted, TmuxSessionSpawned

from tests.golden_trace_helpers import (
    GoldenTraceError,
    GoldenTraceRecorder,
    TraceDiff,
    TraceEntry,
    TraceMismatch,
    _to_repo_relative_posix,
    compare_traces,
    load_golden,
    notify_claude_p,
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
            "GoldenTraceRecorder",
            "MismatchField",
            "TraceDiff",
            "TraceEntry",
            "TraceMismatch",
            "compare_traces",
            "load_golden",
            "notify_claude_p",
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


class LoadGoldenRejectionTests(unittest.TestCase):
    def _write(self, body: str) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        tmp.write(body)
        tmp.close()
        path = Path(tmp.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_unknown_channel_raises(self) -> None:
        path = self._write('[{"seq":0,"channel":"file","kind":"x","payload":{}}]')
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("unknown channel", str(ctx.exception))
        self.assertIn("'file'", str(ctx.exception))

    def test_missing_seq_raises(self) -> None:
        path = self._write('[{"channel":"event","kind":"x","payload":{}}]')
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("seq", str(ctx.exception))

    def test_missing_payload_raises(self) -> None:
        path = self._write('[{"seq":0,"channel":"event","kind":"x"}]')
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("payload", str(ctx.exception))

    def test_top_level_not_a_list_raises(self) -> None:
        path = self._write('{"seq":0}')
        with self.assertRaises(GoldenTraceError):
            load_golden(path)

    def test_entry_not_a_dict_raises(self) -> None:
        path = self._write('["not-an-object"]')
        with self.assertRaises(GoldenTraceError):
            load_golden(path)

    def test_payload_not_a_dict_raises(self) -> None:
        path = self._write('[{"seq":0,"channel":"event","kind":"x","payload":[]}]')
        with self.assertRaises(GoldenTraceError):
            load_golden(path)

    def test_malformed_json_raises_golden_trace_error(self) -> None:
        path = self._write("not json at all")
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("malformed JSON", str(ctx.exception))
        # JSONDecodeError must be chained as __cause__ for diagnostics.
        self.assertIsInstance(ctx.exception.__cause__, json.JSONDecodeError)

    def test_non_integer_seq_raises_golden_trace_error(self) -> None:
        # REQ-08 contract: all malformed input must surface as GoldenTraceError,
        # not as TypeError leaking from int(None) or ValueError from int("abc").
        path = self._write('[{"seq":null,"channel":"event","kind":"x","payload":{}}]')
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("seq", str(ctx.exception))

    def test_string_seq_raises_golden_trace_error(self) -> None:
        path = self._write('[{"seq":"zero","channel":"event","kind":"x","payload":{}}]')
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("seq", str(ctx.exception))

    def test_non_string_kind_raises_golden_trace_error(self) -> None:
        # Silently coercing kind=123 to "123" would mask malformed fixtures.
        path = self._write('[{"seq":0,"channel":"event","kind":123,"payload":{}}]')
        with self.assertRaises(GoldenTraceError) as ctx:
            load_golden(path)
        self.assertIn("kind", str(ctx.exception))


class CompareTracesEqualTests(unittest.TestCase):
    def test_identical_lists_yield_ok_true(self) -> None:
        entries = [
            TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1}),
            TraceEntry(seq=1, channel="state", kind="mutation", payload={"path": "p"}),
        ]
        # Deliberate copy to ensure object identity isn't being relied on.
        actual = [
            TraceEntry(
                seq=e.seq, channel=e.channel, kind=e.kind, payload=dict(e.payload)
            )
            for e in entries
        ]
        diff = compare_traces(actual, entries)
        self.assertTrue(diff.ok)
        self.assertEqual(diff.matched, 2)
        self.assertEqual(diff.mismatches, [])

    def test_empty_lists_yield_ok_true(self) -> None:
        diff = compare_traces([], [])
        self.assertTrue(diff.ok)
        self.assertEqual(diff.matched, 0)
        self.assertEqual(diff.mismatches, [])

    def test_payload_key_order_irrelevant_for_equality(self) -> None:
        # Two payloads with the same keys/values but different insertion order
        # must compare equal (dict equality is order-insensitive, and we want
        # the byte-equal serialization to imply byte-equal comparison too).
        a = [TraceEntry(seq=0, channel="event", kind="X", payload={"a": 1, "b": 2})]
        g = [TraceEntry(seq=0, channel="event", kind="X", payload={"b": 2, "a": 1})]
        diff = compare_traces(a, g)
        self.assertTrue(diff.ok)


class CompareTracesFieldMismatchTests(unittest.TestCase):
    def _golden(self) -> list[TraceEntry]:
        return [
            TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1}),
            TraceEntry(seq=1, channel="event", kind="B", payload={"y": 2}),
            TraceEntry(seq=2, channel="state", kind="mutation", payload={"path": "p"}),
        ]

    def test_payload_regression_localized_to_specific_seq(self) -> None:
        golden = self._golden()
        actual = [
            golden[0],
            TraceEntry(seq=1, channel="event", kind="B", payload={"y": 99}),  # changed
            golden[2],
        ]
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.matched, 2)
        self.assertEqual(len(diff.mismatches), 1)
        m = diff.mismatches[0]
        self.assertEqual(m.seq, 1)
        self.assertEqual(m.field, "payload")
        self.assertEqual(m.actual, {"y": 99})
        self.assertEqual(m.expected, {"y": 2})

    def test_channel_mismatch_takes_priority_over_kind_and_payload(self) -> None:
        golden = [TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1})]
        actual = [TraceEntry(seq=0, channel="state", kind="Z", payload={"y": 9})]
        diff = compare_traces(actual, golden)
        self.assertEqual(len(diff.mismatches), 1)
        self.assertEqual(diff.mismatches[0].field, "channel")

    def test_kind_mismatch_when_channels_match(self) -> None:
        golden = [TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1})]
        actual = [TraceEntry(seq=0, channel="event", kind="B", payload={"x": 1})]
        diff = compare_traces(actual, golden)
        self.assertEqual(len(diff.mismatches), 1)
        self.assertEqual(diff.mismatches[0].field, "kind")
        self.assertEqual(diff.mismatches[0].actual, "B")
        self.assertEqual(diff.mismatches[0].expected, "A")

    def test_multiple_mismatches_one_per_seq(self) -> None:
        golden = self._golden()
        actual = [
            TraceEntry(
                seq=0, channel="event", kind="A", payload={"x": 99}
            ),  # payload differs
            TraceEntry(
                seq=1, channel="state", kind="B", payload={"y": 2}
            ),  # channel differs
            golden[2],
        ]
        diff = compare_traces(actual, golden)
        self.assertEqual(diff.matched, 1)
        self.assertEqual(len(diff.mismatches), 2)
        self.assertEqual([m.seq for m in diff.mismatches], [0, 1])
        self.assertEqual([m.field for m in diff.mismatches], ["payload", "channel"])


class CompareTracesLengthMismatchTests(unittest.TestCase):
    def test_actual_longer_than_golden(self) -> None:
        golden = [TraceEntry(seq=0, channel="event", kind="A", payload={})]
        extra = TraceEntry(seq=1, channel="event", kind="B", payload={})
        actual = [golden[0], extra]
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.matched, 1)
        self.assertEqual(len(diff.mismatches), 1)
        m = diff.mismatches[0]
        self.assertEqual(m.seq, 1)
        self.assertEqual(m.field, "length")
        self.assertEqual(m.actual, extra)
        self.assertIsNone(m.expected)

    def test_golden_longer_than_actual(self) -> None:
        actual = [TraceEntry(seq=0, channel="event", kind="A", payload={})]
        missing = TraceEntry(seq=1, channel="event", kind="B", payload={})
        golden = [actual[0], missing]
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(diff.matched, 1)
        self.assertEqual(len(diff.mismatches), 1)
        m = diff.mismatches[0]
        self.assertEqual(m.seq, 1)
        self.assertEqual(m.field, "length")
        self.assertIsNone(m.actual)
        self.assertEqual(m.expected, missing)

    def test_length_mismatch_with_prior_field_mismatch(self) -> None:
        actual = [
            TraceEntry(seq=0, channel="event", kind="A", payload={"x": 1}),
        ]
        golden = [
            TraceEntry(
                seq=0, channel="event", kind="A", payload={"x": 2}
            ),  # payload differs
            TraceEntry(
                seq=1, channel="event", kind="B", payload={}
            ),  # missing in actual
        ]
        diff = compare_traces(actual, golden)
        self.assertEqual(diff.matched, 0)
        self.assertEqual(len(diff.mismatches), 2)
        # First mismatch is the payload diff at seq=0; second is the length
        # mismatch at seq=1 — ordering matters for diagnostics.
        self.assertEqual(diff.mismatches[0].field, "payload")
        self.assertEqual(diff.mismatches[0].seq, 0)
        self.assertEqual(diff.mismatches[1].field, "length")
        self.assertEqual(diff.mismatches[1].seq, 1)


class TraceDiffSummaryIntegrationTests(unittest.TestCase):
    """End-to-end diagnostic check: produce a real diff, render its summary,
    confirm a reader can localize the regression without the golden file.
    """

    def test_summary_localizes_payload_regression(self) -> None:
        golden = [
            TraceEntry(
                seq=0, channel="event", kind="StoryStarted", payload={"epic": "1"}
            ),
            TraceEntry(
                seq=1,
                channel="event",
                kind="StoryCompleted",
                payload={"cost_usd": 0.42},
            ),
        ]
        actual = [
            golden[0],
            TraceEntry(
                seq=1,
                channel="event",
                kind="StoryCompleted",
                payload={"cost_usd": 0.99},
            ),
        ]
        diff = compare_traces(actual, golden)
        text = diff.summary()
        # Channel + kind + the diverging payload values must all be present
        # so the reader can identify the regression without re-opening the
        # golden fixture (NFR: Diagnostics).
        self.assertIn("seq=1", text)
        self.assertIn("payload", text)
        self.assertIn("0.42", text)
        self.assertIn("0.99", text)

    def test_summary_localizes_length_mismatch(self) -> None:
        golden: list[TraceEntry] = []
        actual = [TraceEntry(seq=0, channel="event", kind="StoryStarted", payload={})]
        diff = compare_traces(actual, golden)
        text = diff.summary()
        self.assertIn("seq=0", text)
        self.assertIn("length", text)


class RecorderSurfaceTests(unittest.TestCase):
    def test_recorder_exported(self) -> None:
        module = importlib.import_module("tests.golden_trace_helpers")
        self.assertIn("GoldenTraceRecorder", module.__all__)
        self.assertIn("notify_claude_p", module.__all__)

    def test_notify_claude_p_is_noop_when_no_recorder_active(self) -> None:
        self.assertIsNone(notify_claude_p(["claude", "-p", "x"]))

    def test_recorder_constructs_with_no_args(self) -> None:
        rec = GoldenTraceRecorder()
        self.assertEqual(rec.entries, [])


class RecorderArrivalOrderingTests(unittest.TestCase):
    def test_record_assigns_monotonic_seq_starting_at_zero(self) -> None:
        rec = GoldenTraceRecorder()
        rec._record("event", "StoryStarted", {"epic": "1"})  # type: ignore[attr-defined]
        rec._record("state", "mutation", {"path": "p", "sha256": "x"})  # type: ignore[attr-defined]
        rec._record("claude_p", "invoke", {"argv": ["claude"]})  # type: ignore[attr-defined]
        self.assertEqual([e.seq for e in rec.entries], [0, 1, 2])
        self.assertEqual(
            [e.channel for e in rec.entries], ["event", "state", "claude_p"]
        )
        self.assertEqual(
            [e.kind for e in rec.entries], ["StoryStarted", "mutation", "invoke"]
        )

    def test_record_is_thread_safe_under_concurrent_callers(self) -> None:
        rec = GoldenTraceRecorder()

        def worker(label: str) -> None:
            for i in range(100):
                rec._record("event", label, {"i": i})  # type: ignore[attr-defined]

        t1 = _threading.Thread(target=worker, args=("A",))
        t2 = _threading.Thread(target=worker, args=("B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        seqs = sorted(e.seq for e in rec.entries)
        self.assertEqual(seqs, list(range(200)))
        self.assertEqual(len(rec.entries), 200)


class PathNormalizationTests(unittest.TestCase):
    def test_absolute_path_under_repo_becomes_repo_relative_posix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            inner = root / "telemetry" / "events.jsonl"
            inner.parent.mkdir(parents=True)
            inner.write_text("", encoding="utf-8")
            out = _to_repo_relative_posix(inner, repo_root=root)
        self.assertEqual(out, "telemetry/events.jsonl")

    def test_unrelated_absolute_path_returned_as_posix_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            outside = Path(tempfile.gettempdir()).resolve() / "unrelated.txt"
            out = _to_repo_relative_posix(outside, repo_root=root)
        self.assertEqual(out, outside.as_posix())

    def test_relative_path_preserved_as_posix(self) -> None:
        out = _to_repo_relative_posix(Path("tests") / "foo.json", repo_root=Path.cwd())
        self.assertEqual(out, "tests/foo.json")

    def test_backslashes_normalized_to_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "a").mkdir()
            (root / "a" / "b.txt").write_text("", encoding="utf-8")
            out = _to_repo_relative_posix(root / "a" / "b.txt", repo_root=root)
        self.assertNotIn(os.sep if os.sep == "\\" else "\x00", out)
        self.assertEqual(out, "a/b.txt")


class RecorderRepoRootResolutionTests(unittest.TestCase):
    def test_explicit_repo_root_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            rec = GoldenTraceRecorder(repo_root=root)
            self.assertEqual(rec._repo_root, root)  # type: ignore[attr-defined]

    def test_default_repo_root_finds_project_root(self) -> None:
        rec = GoldenTraceRecorder()
        resolved = rec._repo_root  # type: ignore[attr-defined]
        self.assertIsNotNone(resolved)
        assert resolved is not None
        self.assertTrue(
            (resolved / "pyproject.toml").exists() or (resolved / ".git").exists(),
            f"resolved repo_root {resolved} contains no project marker",
        )


class EmitHookTests(unittest.TestCase):
    def test_emit_records_event_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r1",
                epic="e1",
                story_key="s1",
                agent="dev",
                model="opus",
                complexity="L",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        self.assertEqual(len(rec.entries), 1)
        entry = rec.entries[0]
        self.assertEqual(entry.channel, "event")
        self.assertEqual(entry.kind, "StoryStarted")
        self.assertEqual(entry.payload.get("epic"), "e1")
        self.assertEqual(entry.payload.get("story_key"), "s1")
        self.assertEqual(entry.payload.get("event_type"), "story_started")

    def test_emit_passes_through_normal_return(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r1",
                epic="e",
                story_key="s",
                agent="a",
                model="m",
                complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)):
                emitter.emit(event)
            self.assertTrue(log.exists())
            self.assertGreater(log.stat().st_size, 0)

    def test_emit_hook_removed_on_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r1",
                epic="e",
                story_key="s",
                agent="a",
                model="m",
                complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
            emitter.emit(event)
        self.assertEqual(len(rec.entries), 1)


class EventTimestampRedactionTests(unittest.TestCase):
    def test_timestamp_replaced_with_ts_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = StoryStarted(
                timestamp="2026-06-15T12:34:56Z",
                run_id="r",
                epic="e",
                story_key="s",
                agent="a",
                model="m",
                complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        self.assertEqual(rec.entries[0].payload["timestamp"], "<ts>")

    def test_emit_pass_through_keeps_original_timestamp_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-06-15T12:34:56Z",
                run_id="r",
                epic="e",
                story_key="s",
                agent="a",
                model="m",
                complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)):
                emitter.emit(event)
            disk = log.read_text(encoding="utf-8")
        self.assertIn("2026-06-15T12:34:56Z", disk)
        self.assertNotIn("<ts>", disk)


class EventRedactionTests(unittest.TestCase):
    def test_pid_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = TmuxSessionSpawned(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r",
                session_name="bmad-1",
                story_key="s1",
                pid=12345,
                pane_geometry="80x24",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        self.assertEqual(rec.entries[0].payload["pid"], "<redacted>")

    def test_session_name_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = TmuxSessionSpawned(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r",
                session_name="bmad-12345",
                story_key="s1",
                pid=12345,
                pane_geometry="80x24",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        self.assertEqual(rec.entries[0].payload["session_name"], "<redacted>")

    def test_four_letter_placeholder_in_payload_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r",
                epic="e",
                story_key="XXXX",
                agent="a",
                model="m",
                complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        self.assertEqual(rec.entries[0].payload["story_key"], "XXXX")


class StateWriteHookTests(unittest.TestCase):
    def test_state_write_records_path_and_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "state.json"
            body = '{"k": 1}'
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(target, body)
        self.assertEqual(len(rec.entries), 1)
        entry = rec.entries[0]
        self.assertEqual(entry.channel, "state")
        self.assertEqual(entry.kind, "mutation")
        self.assertEqual(entry.payload["path"], "state.json")
        expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.assertEqual(entry.payload["sha256"], expected)

    def test_state_write_passes_through(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "doc.md"
            body = "# heading\n"
            with GoldenTraceRecorder(repo_root=root):
                _state_module.write_atomic_text(target, body)
            self.assertEqual(target.read_text(encoding="utf-8"), body)

    def test_state_hook_removed_on_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "a.txt"
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(target, "x")
            _state_module.write_atomic_text(target, "y")
        self.assertEqual(len(rec.entries), 1)


if __name__ == "__main__":
    unittest.main()
