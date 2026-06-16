from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import os
import tempfile
import threading as _threading
import time
import unittest
import warnings
from collections.abc import Callable
from pathlib import Path

from story_automator.commands import state as _state_module
from story_automator.core.atomic_io import (
    HeartbeatThread,
    RunLockIdentity,
    acquire_run_lock,
)
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

_GOLDEN_DIR = Path(__file__).parent / "golden"
_REGEN_ENV = "BMA_GOLDEN_REGEN"


def _validate_or_regen(
    fixture_name: str,
    builder: Callable[[Path], list[TraceEntry]],
) -> None:
    """Validate a shipped fixture against a fresh recording.

    Normal mode: ``load_golden(<fixture>)`` and ``compare_traces(fresh, golden)``;
    fail with a diagnostic summary if not ok.

    Regen mode (``BMA_GOLDEN_REGEN=1``): build the recording in a tempdir,
    serialize it, and write to ``<fixture>``. The caller's tempdir is used as
    ``repo_root`` inside the builder so absolute paths normalize to repo-
    relative POSIX in the recorded entries.
    """
    fixture_path = _GOLDEN_DIR / fixture_name
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        entries = builder(root)
        serialized = serialize_trace(entries)
    if os.environ.get(_REGEN_ENV) == "1":
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(serialized, encoding="utf-8")
        return
    if not fixture_path.exists():
        raise AssertionError(
            f"fixture {fixture_path} does not exist; run with "
            f"{_REGEN_ENV}=1 to generate it"
        )
    golden = load_golden(fixture_path)
    diff = compare_traces(entries, golden)
    if not diff.ok:
        raise AssertionError(
            f"{fixture_name} diverged from fresh recording:\n{diff.summary()}"
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


class StateLockExclusionTests(unittest.TestCase):
    def test_run_lock_write_not_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(root / ".run.lock", '{"pid":1}')
        self.assertEqual(rec.entries, [])

    def test_state_build_lock_write_not_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "output").mkdir()
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(
                    root / "output" / ".state-build.lock", "ignored"
                )
        self.assertEqual(rec.entries, [])

    def test_non_lock_path_still_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            body = '{"k": 1}'
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(root / "config.json", body)
        self.assertEqual(len(rec.entries), 1)

    def test_user_named_dot_lock_file_still_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(root / "mystory.lock", "user data")
        self.assertEqual(len(rec.entries), 1)
        self.assertEqual(rec.entries[0].payload["path"], "mystory.lock")


class ClaudePHookTests(unittest.TestCase):
    def test_notify_claude_p_records_invoke_entry(self) -> None:
        import tests.golden_trace_helpers as gh

        with tempfile.TemporaryDirectory() as tmp:
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                gh.notify_claude_p(["claude", "-p", "Run story s1"])
        self.assertEqual(len(rec.entries), 1)
        entry = rec.entries[0]
        self.assertEqual(entry.channel, "claude_p")
        self.assertEqual(entry.kind, "invoke")
        self.assertEqual(entry.payload["argv"], ["claude", "-p", "Run story s1"])

    def test_notify_claude_p_outside_recorder_is_noop(self) -> None:
        import tests.golden_trace_helpers as gh

        with tempfile.TemporaryDirectory() as tmp:
            with GoldenTraceRecorder(repo_root=Path(tmp)):
                pass
        self.assertIsNone(gh.notify_claude_p(["claude", "-p", "x"]))

    def test_claude_p_hook_removed_on_exit(self) -> None:
        import tests.golden_trace_helpers as gh

        with tempfile.TemporaryDirectory() as tmp:
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                gh.notify_claude_p(["claude", "-p", "a"])
            gh.notify_claude_p(["claude", "-p", "b"])  # not recorded
        self.assertEqual(len(rec.entries), 1)


class ClaudePArgvNormalizationTests(unittest.TestCase):
    def test_absolute_repo_path_normalized_to_relative_posix(self) -> None:
        import tests.golden_trace_helpers as gh

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "stories").mkdir()
            story = root / "stories" / "s1.md"
            story.write_text("body", encoding="utf-8")
            with GoldenTraceRecorder(repo_root=root) as rec:
                gh.notify_claude_p(["claude", "-p", str(story)])
        self.assertEqual(
            rec.entries[0].payload["argv"], ["claude", "-p", "stories/s1.md"]
        )

    def test_four_letter_placeholder_token_preserved(self) -> None:
        import tests.golden_trace_helpers as gh

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with GoldenTraceRecorder(repo_root=root) as rec:
                gh.notify_claude_p(["claude", "-p", "Run EPIC STRY now"])
        self.assertEqual(
            rec.entries[0].payload["argv"],
            ["claude", "-p", "Run EPIC STRY now"],
        )

    def test_non_path_token_passes_through_unchanged(self) -> None:
        import tests.golden_trace_helpers as gh

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with GoldenTraceRecorder(repo_root=root) as rec:
                gh.notify_claude_p(["claude", "-p", "--model=opus", "key=value"])
        self.assertEqual(
            rec.entries[0].payload["argv"],
            ["claude", "-p", "--model=opus", "key=value"],
        )


class RecorderRestorationOnExceptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._baseline_emit = TelemetryEmitter.emit
        self._baseline_state_write = _state_module.write_atomic_text

    def tearDown(self) -> None:
        TelemetryEmitter.emit = self._baseline_emit  # type: ignore[method-assign]
        _state_module.write_atomic_text = self._baseline_state_write  # type: ignore[assignment]

    def test_emit_restored_when_block_raises(self) -> None:
        import tests.golden_trace_helpers as gh

        orig_emit = TelemetryEmitter.emit
        orig_state_write = _state_module.write_atomic_text
        orig_hook = gh._CLAUDE_P_HOOK  # type: ignore[attr-defined]

        class _MyError(RuntimeError):
            pass

        with self.assertRaises(_MyError):
            with GoldenTraceRecorder(repo_root=Path(".")):
                raise _MyError("synthetic")

        self.assertIs(TelemetryEmitter.emit, orig_emit)
        self.assertIs(_state_module.write_atomic_text, orig_state_write)
        self.assertIs(gh._CLAUDE_P_HOOK, orig_hook)  # type: ignore[attr-defined]

    def test_two_sequential_with_blocks_yield_independent_traces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r",
                epic="e",
                story_key="s",
                agent="a",
                model="m",
                complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as r1:
                emitter.emit(event)
            with GoldenTraceRecorder(repo_root=Path(tmp)) as r2:
                emitter.emit(event)
                emitter.emit(event)
        self.assertEqual(len(r1.entries), 1)
        self.assertEqual(len(r2.entries), 2)
        self.assertEqual(r1.entries[0].seq, 0)
        self.assertEqual(r2.entries[0].seq, 0)

    def test_nested_recorders_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            rec = GoldenTraceRecorder(repo_root=Path(tmp))
            with rec:
                with self.assertRaises(RuntimeError):
                    with rec:
                        pass

    def test_second_distinct_recorder_rejected_while_first_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with GoldenTraceRecorder(repo_root=Path(tmp)):
                with self.assertRaises(RuntimeError):
                    with GoldenTraceRecorder(repo_root=Path(tmp)):
                        pass


class ImportSafetyTests(unittest.TestCase):
    def test_import_does_not_install_hooks(self) -> None:
        # Fresh subprocess so we observe pristine module state — using
        # importlib.reload in-process is unsafe (the reload could race
        # with a concurrently-active recorder in another test thread).
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, 'skills/bmad-story-automator/src');\n"
                "from story_automator.core.telemetry_emitter import TelemetryEmitter\n"
                "from story_automator.commands import state\n"
                "orig_emit = TelemetryEmitter.emit\n"
                "orig_write = state.write_atomic_text\n"
                "import tests.golden_trace_helpers as gh\n"
                "assert TelemetryEmitter.emit is orig_emit, 'emit was patched at import'\n"
                "assert state.write_atomic_text is orig_write, 'write_atomic_text patched at import'\n"
                "assert gh._CLAUDE_P_HOOK is None, 'claude_p hook installed at import'\n"
                "print('ok')",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("ok", result.stdout)

    def test_module_level_claude_p_hook_is_none(self) -> None:
        import tests.golden_trace_helpers as gh

        self.assertIsNone(gh._CLAUDE_P_HOOK)  # type: ignore[attr-defined]


class DeterminismE2ETests(unittest.TestCase):
    """NFR primary criterion: a given recorded session must serialize
    byte-identically across runs."""

    def _record_five_events(self, tmp: Path) -> bytes:
        emitter = TelemetryEmitter(tmp / "events.jsonl")
        events = [
            StoryStarted(
                timestamp="2026-06-15T01:02:03Z",
                run_id="r",
                epic="e",
                story_key=f"s{i}",
                agent="a",
                model="m",
                complexity="c",
            )
            for i in range(5)
        ]
        with GoldenTraceRecorder(repo_root=tmp) as rec:
            for ev in events:
                emitter.emit(ev)
        return serialize_trace(rec.entries).encode("utf-8")

    def test_two_recordings_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp1:
            first = self._record_five_events(Path(tmp1).resolve())
        with tempfile.TemporaryDirectory() as tmp2:
            second = self._record_five_events(Path(tmp2).resolve())
        self.assertEqual(first, second)

    def test_real_iso_timestamp_collapsed_to_ts(self) -> None:
        from story_automator.core.common import iso_now

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            with GoldenTraceRecorder(repo_root=root) as rec:
                emitter.emit(
                    StoryStarted(
                        timestamp=iso_now(),
                        run_id="r",
                        epic="e",
                        story_key="s",
                        agent="a",
                        model="m",
                        complexity="c",
                    )
                )
        self.assertEqual(rec.entries[0].payload["timestamp"], "<ts>")


class HookSafetyTests(unittest.TestCase):
    """NFR Safety: a recording-side failure must not propagate into the
    caller — the recorded operation itself has already completed."""

    def test_emit_hook_swallows_recording_failure(self) -> None:
        import tests.golden_trace_helpers as gh

        def _raise(_payload: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("synthetic redaction failure")

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r",
                epic="e",
                story_key="s",
                agent="a",
                model="m",
                complexity="c",
            )
            orig_redact = gh._redact_event_payload
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    gh._redact_event_payload = _raise  # type: ignore[assignment]
                    try:
                        emitter.emit(event)
                    finally:
                        gh._redact_event_payload = orig_redact  # type: ignore[assignment]
                emitter.emit(event)
        # First emit lost its trace entry; second emit (after un-patch)
        # records normally — passive-observer contract: a recording-side
        # failure does NOT propagate to the caller of emit.
        self.assertEqual(len(rec.entries), 1)
        self.assertEqual(rec.entries[0].kind, "StoryStarted")
        self.assertTrue(
            any("emit-hook recording failed" in str(w.message) for w in caught)
        )

    def test_claude_p_hook_swallows_recording_failure(self) -> None:
        import tests.golden_trace_helpers as gh

        def _raise(_argv: list[str], *, repo_root: Path) -> list[str]:
            raise RuntimeError("synthetic normalize failure")

        with tempfile.TemporaryDirectory() as tmp:
            orig_norm = gh._normalize_argv
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    gh._normalize_argv = _raise  # type: ignore[assignment]
                    try:
                        gh.notify_claude_p(["claude", "-p", "boom"])
                    finally:
                        gh._normalize_argv = orig_norm  # type: ignore[assignment]
                gh.notify_claude_p(["claude", "-p", "ok"])
        self.assertEqual(len(rec.entries), 1)
        self.assertEqual(rec.entries[0].payload["argv"], ["claude", "-p", "ok"])
        self.assertTrue(
            any("claude_p-hook recording failed" in str(w.message) for w in caught)
        )


class RecorderPerformanceTests(unittest.TestCase):
    """NFR Performance: hook overhead must add no more than ~50us per
    intercepted op on commodity hardware; the M02 five-event fixture
    must record + serialize end-to-end in under 100ms.

    The 50us bound is per-op steady-state; we use a generous 500us
    upper bound here to absorb CI noise (Windows scheduler quanta,
    GC pauses, antivirus). A breach above 500us-per-op signals an
    O(N) or O(log N) regression in the hook path, which is what
    this test is actually guarding against.
    """

    def test_five_event_record_and_serialize_under_100ms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            events = [
                StoryStarted(
                    timestamp="2026-06-15T01:02:03Z",
                    run_id="r",
                    epic="e",
                    story_key=f"s{i}",
                    agent="a",
                    model="m",
                    complexity="c",
                )
                for i in range(5)
            ]
            t0 = time.perf_counter()
            with GoldenTraceRecorder(repo_root=root) as rec:
                for ev in events:
                    emitter.emit(ev)
            serialized = serialize_trace(rec.entries)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
        self.assertEqual(len(rec.entries), 5)
        self.assertTrue(serialized.endswith("\n"))
        self.assertLess(
            elapsed_ms,
            100.0,
            f"5-event record+serialize took {elapsed_ms:.1f}ms; NFR budget is 100ms",
        )

    def test_emit_hook_overhead_per_op_within_budget(self) -> None:
        # Measure per-op overhead by comparing 50 emits inside the recorder
        # to 50 emits outside it. Spec budget is ~50us; we assert <500us
        # to absorb CI variance. A regression that pushes overhead to
        # milliseconds will still trip this gate.
        N = 50
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter_a = TelemetryEmitter(root / "a.jsonl")
            emitter_b = TelemetryEmitter(root / "b.jsonl")
            event = StoryStarted(
                timestamp="2026-06-15T01:02:03Z",
                run_id="r",
                epic="e",
                story_key="s",
                agent="a",
                model="m",
                complexity="c",
            )
            t0 = time.perf_counter()
            for _ in range(N):
                emitter_a.emit(event)
            baseline_ns = time.perf_counter() - t0

            t1 = time.perf_counter()
            with GoldenTraceRecorder(repo_root=root):
                for _ in range(N):
                    emitter_b.emit(event)
            recorded_ns = time.perf_counter() - t1
        overhead_us = max(0.0, (recorded_ns - baseline_ns) * 1_000_000 / N)
        self.assertLess(
            overhead_us,
            500.0,
            f"per-op overhead {overhead_us:.0f}us exceeds 500us guard "
            f"(spec target is ~50us)",
        )


class FixtureHelperContractTests(unittest.TestCase):
    def test_golden_dir_constant_points_to_tests_golden(self) -> None:
        from tests.test_golden_trace_helpers import _GOLDEN_DIR

        self.assertEqual(_GOLDEN_DIR, Path(__file__).parent / "golden")

    def test_regen_env_var_constant(self) -> None:
        from tests.test_golden_trace_helpers import _REGEN_ENV

        self.assertEqual(_REGEN_ENV, "BMA_GOLDEN_REGEN")

    def test_validate_or_regen_callable_present(self) -> None:
        from tests.test_golden_trace_helpers import _validate_or_regen

        self.assertTrue(callable(_validate_or_regen))


class GoldenDirectoryStructureTests(unittest.TestCase):
    def test_golden_directory_exists_under_tests(self) -> None:
        golden_dir = Path(__file__).parent / "golden"
        self.assertTrue(
            golden_dir.is_dir(),
            "tests/golden/ must exist; M10c ships fixtures here",
        )

    def test_golden_directory_is_committed(self) -> None:
        golden_dir = Path(__file__).parent / "golden"
        contents = list(golden_dir.iterdir())
        self.assertTrue(
            contents,
            "tests/golden/ must contain at least .gitkeep or a fixture",
        )


class RecorderSelfComparisonTests(unittest.TestCase):
    """REQ-12(a): a recording compared against itself yields ok=True.

    Uses the live recorder to capture all three channels, then runs
    compare_traces(entries, entries) — the loopback acts as the simplest
    smoke test of the full record + diff pipeline.
    """

    def test_self_comparison_returns_ok_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            event = StoryStarted(
                timestamp="2026-06-15T00:00:00Z",
                run_id="r",
                epic="e",
                story_key="s",
                agent="a",
                model="m",
                complexity="c",
            )
            import tests.golden_trace_helpers as gh

            with GoldenTraceRecorder(repo_root=root) as rec:
                emitter.emit(event)
                _state_module.write_atomic_text(root / "doc.txt", "hello")
                gh.notify_claude_p(["claude", "-p", "Run story"])
            entries = rec.entries
        diff = compare_traces(entries, entries)
        self.assertTrue(diff.ok)
        self.assertEqual(diff.matched, len(entries))
        self.assertEqual(diff.mismatches, [])

    def test_self_comparison_after_serialize_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            with GoldenTraceRecorder(repo_root=root) as rec:
                emitter.emit(
                    StoryStarted(
                        timestamp="2026-06-15T00:00:00Z",
                        run_id="r",
                        epic="e",
                        story_key="s",
                        agent="a",
                        model="m",
                        complexity="c",
                    )
                )
            entries = rec.entries
            fixture = Path(tmp) / "round_trip.json"
            fixture.write_text(serialize_trace(entries), encoding="utf-8")
            reloaded = load_golden(fixture)
        diff = compare_traces(entries, reloaded)
        self.assertTrue(diff.ok)


def _build_m01_recording(root: Path) -> list[TraceEntry]:
    """M01 fixture: one StoryStarted event captured by the recorder.

    All event fields are literal strings — no real timestamps, no PIDs,
    no float fields — so the serialized trace is byte-identical across
    runs once the recorder's timestamp redaction collapses the literal
    ``timestamp`` field to ``"<ts>"``.
    """
    emitter = TelemetryEmitter(root / "events.jsonl")
    event = StoryStarted(
        timestamp="2026-06-15T00:00:00Z",
        run_id="m01-fixture-run",
        epic="e1",
        story_key="s1",
        agent="dev",
        model="opus",
        complexity="M",
    )
    with GoldenTraceRecorder(repo_root=root) as rec:
        emitter.emit(event)
    return rec.entries


class M01FixtureTests(unittest.TestCase):
    """REQ-11 + REQ-12(e): m01_event_basics.json round-trip."""

    def test_m01_fixture_matches_fresh_recording(self) -> None:
        _validate_or_regen("m01_event_basics.json", _build_m01_recording)

    def test_m01_fixture_records_exactly_one_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = _build_m01_recording(Path(tmp).resolve())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].channel, "event")
        self.assertEqual(entries[0].kind, "StoryStarted")
        self.assertEqual(entries[0].payload["timestamp"], "<ts>")


def _build_m02_recording(root: Path) -> list[TraceEntry]:
    """M02 fixture: five StoryStarted events emitted in order, captured.

    The emitter routes each event through write_atomic_text on its
    backing JSONL log, but that file lives in ``root`` (the tempdir) and
    is OUTSIDE the recorder's interest — the recorder only intercepts
    ``state.write_atomic_text``, not ``atomic_io.write_atomic_text``
    directly. So only the five event entries appear in the trace,
    matching the spec's "five emitted events read back" description.
    """
    emitter = TelemetryEmitter(root / "events.jsonl")
    events = [
        StoryStarted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="m02-fixture-run",
            epic="e1",
            story_key=f"s{i}",
            agent="dev",
            model="opus",
            complexity="M",
        )
        for i in range(5)
    ]
    with GoldenTraceRecorder(repo_root=root) as rec:
        for ev in events:
            emitter.emit(ev)
    return rec.entries


class M02FixtureTests(unittest.TestCase):
    """REQ-11 + REQ-12(e): m02_emitter_smoke.json round-trip."""

    def test_m02_fixture_matches_fresh_recording(self) -> None:
        _validate_or_regen("m02_emitter_smoke.json", _build_m02_recording)

    def test_m02_fixture_records_five_events_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = _build_m02_recording(Path(tmp).resolve())
        self.assertEqual(len(entries), 5)
        self.assertEqual([e.seq for e in entries], [0, 1, 2, 3, 4])
        self.assertEqual([e.channel for e in entries], ["event"] * 5)
        self.assertEqual([e.kind for e in entries], ["StoryStarted"] * 5)
        self.assertEqual(
            [e.payload["story_key"] for e in entries],
            ["s0", "s1", "s2", "s3", "s4"],
        )


def _build_m05_recording(root: Path) -> list[TraceEntry]:
    """M05 fixture: three concurrent state writes under composite-identity
    lock + heartbeat thread, sequenced via threading.Event for a fixed
    completion order.

    The lock-file writes (``<root>/.run.lock``) are filtered by the
    recorder's ``_is_heartbeat_lock_path`` helper, and heartbeat writes go
    through ``atomic_io.write_atomic_text`` directly (not state.py), so
    neither pollutes the trace. The only recorded entries are the three
    ``state.mutation`` events from the worker threads, in seq 0/1/2 order.
    """
    lock_path = root / ".run.lock"
    gates = [_threading.Event() for _ in range(4)]
    gates[0].set()
    write_results: list[Exception | None] = [None, None, None]

    def worker(i: int) -> None:
        try:
            gates[i].wait()
            _state_module.write_atomic_text(root / f"out{i}.json", f'{{"i":{i}}}')
        except Exception as exc:
            write_results[i] = exc
        finally:
            gates[i + 1].set()

    with GoldenTraceRecorder(repo_root=root) as rec:
        with acquire_run_lock(lock_path, run_id="m05-fixture-run"):
            heartbeat = HeartbeatThread(
                lock_path=lock_path,
                identity=RunLockIdentity(
                    pid=0,
                    start_time=0.0,
                    hostname="fixture",
                    heartbeat_iso="2026-06-15T00:00:00Z",
                    run_id="m05-fixture-run",
                ),
                interval=3600.0,
            )
            heartbeat.start()
            try:
                threads = [
                    _threading.Thread(target=worker, args=(i,)) for i in range(3)
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                heartbeat.stop()
                heartbeat.join(timeout=5.0)
    for i, err in enumerate(write_results):
        if err is not None:
            raise AssertionError(f"worker {i} raised: {err!r}") from err
    return rec.entries


class M05FixtureTests(unittest.TestCase):
    """REQ-11 + REQ-12(e): m05_atomic_write_smoke.json round-trip."""

    def test_m05_fixture_matches_fresh_recording(self) -> None:
        _validate_or_regen("m05_atomic_write_smoke.json", _build_m05_recording)

    def test_m05_fixture_records_three_state_mutations_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = _build_m05_recording(Path(tmp).resolve())
        self.assertEqual(len(entries), 3)
        self.assertEqual([e.seq for e in entries], [0, 1, 2])
        self.assertEqual([e.channel for e in entries], ["state"] * 3)
        self.assertEqual([e.kind for e in entries], ["mutation"] * 3)
        self.assertEqual(
            [e.payload["path"] for e in entries],
            ["out0.json", "out1.json", "out2.json"],
        )


class M05DeterminismTests(unittest.TestCase):
    """Quality gate: M05 fixture passes ten consecutive runs with byte-
    identical serialized output, confirming determinism under composite-
    identity lock + heartbeat thread + concurrent worker threads.
    """

    def test_ten_consecutive_recordings_byte_identical(self) -> None:
        outputs: list[bytes] = []
        for _ in range(10):
            with tempfile.TemporaryDirectory() as tmp:
                entries = _build_m05_recording(Path(tmp).resolve())
                outputs.append(serialize_trace(entries).encode("utf-8"))
        first = outputs[0]
        for idx, out in enumerate(outputs[1:], start=1):
            self.assertEqual(
                out,
                first,
                f"run #{idx} diverged from run #0 byte-wise; "
                f"M05 concurrent-thread fixture is non-deterministic",
            )


class RecorderRegressionLocalizationTests(unittest.TestCase):
    """REQ-12(b) at recorder altitude: a real recorded run with one
    injected payload divergence is detected by compare_traces with the
    correct seq and field. Strengthens the M10a unit-level coverage by
    exercising the full pipeline (record -> serialize -> mutate -> load
    -> compare).
    """

    def test_payload_regression_localized_to_correct_seq(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            actual = _build_m02_recording(root)
            golden = [
                TraceEntry(
                    seq=e.seq,
                    channel=e.channel,
                    kind=e.kind,
                    payload=dict(e.payload),
                )
                for e in actual
            ]
            golden[2] = TraceEntry(
                seq=golden[2].seq,
                channel=golden[2].channel,
                kind=golden[2].kind,
                payload={**dict(golden[2].payload), "story_key": "s2-regressed"},
            )
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(len(diff.mismatches), 1)
        mismatch = diff.mismatches[0]
        self.assertEqual(mismatch.seq, 2)
        self.assertEqual(mismatch.field, "payload")
        summary = diff.summary()
        self.assertIn("seq=2", summary)
        self.assertIn("payload", summary)

    def test_length_regression_localized_via_recorder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            actual = _build_m02_recording(root)
            golden = list(actual[:-1])
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(len(diff.mismatches), 1)
        self.assertEqual(diff.mismatches[0].seq, 4)
        self.assertEqual(diff.mismatches[0].field, "length")


class PlaceholderLeakQualityGateTests(unittest.TestCase):
    """Quality gate: no unresolved four-letter placeholder tokens leak
    into tests/golden_trace_helpers.py.

    The recorder source must never contain bare 4-letter uppercase
    sentinels like ``EPIC`` or ``STRY`` — those belong only in template
    payloads, which the recorder preserves verbatim per REQ-13.
    """

    _ALLOWED_TOKENS = frozenset(
        {
            "JSON",
            "HTTP",
            "NONE",
            "TRUE",
            "ASCI",
            "REQ",
            "POSIX",
            "PEP",
        }
    )

    def test_no_unallowed_four_letter_placeholder_in_helper_source(self) -> None:
        import re

        helper_path = Path(__file__).parent / "golden_trace_helpers.py"
        source = helper_path.read_text(encoding="utf-8")
        pattern = re.compile(r"\b[A-Z]{4}\b")
        offenders: list[tuple[int, str, str]] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for match in pattern.finditer(line):
                token = match.group(0)
                if token in self._ALLOWED_TOKENS:
                    continue
                offenders.append((lineno, token, line.rstrip()))
        self.assertEqual(
            offenders,
            [],
            f"unresolved 4-letter placeholder tokens in helper source: {offenders}",
        )

    def test_four_letter_placeholder_in_event_payload_survives_serialization(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            with GoldenTraceRecorder(repo_root=root) as rec:
                emitter.emit(
                    StoryStarted(
                        timestamp="2026-06-15T00:00:00Z",
                        run_id="r",
                        epic="EPIC",
                        story_key="STRY",
                        agent="a",
                        model="m",
                        complexity="c",
                    )
                )
            entries = rec.entries
            fixture = Path(tmp) / "placeholder.json"
            fixture.write_text(serialize_trace(entries), encoding="utf-8")
            reloaded = load_golden(fixture)
        self.assertEqual(reloaded[0].payload["epic"], "EPIC")
        self.assertEqual(reloaded[0].payload["story_key"], "STRY")


class HelperImportProducesNoObservablesTests(unittest.TestCase):
    """Quality gate: importing tests.golden_trace_helpers emits no
    telemetry events, performs no state mutations, and triggers no
    claude_p invocations during the import itself.

    Uses direct counter wrappers on the two surfaces that could leak
    (state.write_atomic_text and TelemetryEmitter.emit) BEFORE the
    helper imports. claude_p has no module-level call site (the hook
    slot is just rebound to None), so it cannot fire at import time.
    """

    def test_cold_import_produces_no_state_writes_or_emits(self) -> None:
        import subprocess
        import sys

        script = (
            "import sys; sys.path.insert(0, 'skills/bmad-story-automator/src')\n"
            "import json\n"
            "from story_automator.commands import state as _state\n"
            "from story_automator.core.telemetry_emitter import TelemetryEmitter\n"
            "writes = []\n"
            "emits = []\n"
            "_orig_write = _state.write_atomic_text\n"
            "_orig_emit = TelemetryEmitter.emit\n"
            "def _counted_write(path, data, *, encoding='utf-8'):\n"
            "    writes.append((str(path), data))\n"
            "    return _orig_write(path, data, encoding=encoding)\n"
            "def _counted_emit(self, event):\n"
            "    emits.append(type(event).__name__)\n"
            "    return _orig_emit(self, event)\n"
            "_state.write_atomic_text = _counted_write\n"
            "TelemetryEmitter.emit = _counted_emit\n"
            "import tests.golden_trace_helpers as gh\n"
            "out = {\n"
            "    'writes': writes,\n"
            "    'emits': emits,\n"
            "    'claude_p_hook_is_none': gh._CLAUDE_P_HOOK is None,\n"
            "    'active_recorder_is_none': gh._ACTIVE_RECORDER is None,\n"
            "}\n"
            "sys.stdout.write(json.dumps(out))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"subprocess exited {result.returncode}:\n"
            f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        import json as _json

        payload = _json.loads(result.stdout)
        self.assertEqual(
            payload["writes"],
            [],
            msg=f"helper import triggered state writes: {payload['writes']}",
        )
        self.assertEqual(
            payload["emits"],
            [],
            msg=f"helper import triggered telemetry emits: {payload['emits']}",
        )
        self.assertTrue(
            payload["claude_p_hook_is_none"],
            msg="helper import installed a non-None claude_p hook",
        )
        self.assertTrue(
            payload["active_recorder_is_none"],
            msg="helper import installed an active recorder",
        )


if __name__ == "__main__":
    unittest.main()
