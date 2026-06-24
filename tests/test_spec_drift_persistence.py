"""Tests for SpecDriftWatcher disk persistence (C1 follow-up).

Exercises the additive persistence layer added to the C1 MVP:

* ``persistence_key`` kwarg on ``SpecDriftWatcher`` enables disk-backed
  baseline + event-log behavior under ``_bmad/drift/<key>/``.
* When the kwarg is ``None`` (default), the watcher is byte-identical
  to the MVP — no directory creation, no I/O.
* Baseline is persisted atomically; events are appended JSONL with
  fsync; both are coordinated by a filelock at
  ``_bmad/drift/<key>/.drift.lock``.

Tests stub ``check_compliance`` so they never hit the real spec parser
and never wait on wall-clock time.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.innovation.spec_drift_persistence import (
    append_drift_event,
    baseline_path,
    drift_root_dir,
    events_path,
    load_baseline,
    persist_baseline,
    validate_persistence_key,
)
from story_automator.core.innovation.spec_drift_watcher import (
    SpecDriftError,
    SpecDriftEvent,
    SpecDriftSnapshot,
    SpecDriftWatcher,
)


# ---------------------------------------------------------------------------
# Stubs (mirror MVP test helpers)
# ---------------------------------------------------------------------------


def _verdict(req_id: str, status: str):
    @dataclasses.dataclass(frozen=True)
    class _V:
        req_id: str
        status: str
        evidence: str = ""
        confidence: float = 1.0

    return _V(req_id=req_id, status=status)


def _report(verdicts):
    @dataclasses.dataclass(frozen=True)
    class _R:
        verdicts: list
        spec_path: str = "/tmp/spec.md"
        diff_sha: str = "deadbeef"
        model_invocation_ms: int = 1

    return _R(verdicts=list(verdicts))


_TARGET = "story_automator.core.innovation.spec_drift_watcher.check_compliance"


# ---------------------------------------------------------------------------
# Persistence-key validation
# ---------------------------------------------------------------------------


class TestPersistenceKeyValidation(unittest.TestCase):
    def test_valid_keys_accepted(self) -> None:
        for key in ("abc", "abc_123", "abc-123", "gate-9", "GateA"):
            validate_persistence_key(key)  # no raise

    def test_invalid_keys_rejected(self) -> None:
        for key in ("", "../etc", "with space", "foo/bar", "foo.bar", "."):
            with self.assertRaises(SpecDriftError):
                validate_persistence_key(key)

    def test_trailing_newline_keys_rejected(self) -> None:
        # Regression: pre-fix, ``_PERSISTENCE_KEY_RE`` anchored with
        # ``$`` instead of ``\Z``, and Python's default-mode ``$``
        # matches before a trailing ``\n``. That meant
        # ``validate_persistence_key('foo\n')`` silently passed and
        # ``drift_root_dir(..., create=True)`` then created a directory
        # literally named ``foo\n`` under ``_bmad/drift/``, breaking the
        # docstring promise that the resulting directory is "well-formed
        # on every supported FS" (whitespace is explicitly listed as a
        # rejected character in the docstring). Anchor the regex with
        # ``\Z`` so trailing newline / carriage-return / CRLF all fail
        # validation up front. Sibling ``test_invalid_keys_rejected``
        # already covers internal-whitespace ``"with space"``; this
        # case covers the trailing-anchor mismatch specifically.
        for key in ("foo\n", "\nfoo", "foo\r", "foo\r\n"):
            with self.assertRaises(SpecDriftError):
                validate_persistence_key(key)

    def test_over_long_keys_rejected_as_spec_drift_error(self) -> None:
        # Regression: pre-fix, _PERSISTENCE_KEY_RE had no length cap so
        # a 256+ char key passed validation, then drift_root_dir(...,
        # create=True) raised a raw OSError(ENAMETOOLONG) on POSIX
        # filesystems whose single path component is capped at 255
        # bytes. Callers using `except SpecDriftError` (the module's
        # documented wrapping convention) would have missed it. The
        # length cap surfaces the failure as SpecDriftError where it
        # belongs, before any mkdir is attempted.
        for n in (65, 256, 5000):
            with self.assertRaises(SpecDriftError):
                validate_persistence_key("a" * n)
        # Boundary: 64-char key must still be accepted (cap is
        # inclusive at the documented maximum).
        validate_persistence_key("a" * 64)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


class TestPathHelpers(unittest.TestCase):
    def test_paths_under_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = drift_root_dir(root, "k1")
            self.assertEqual(d, root / "_bmad" / "drift" / "k1")
            self.assertEqual(baseline_path(root, "k1"), d / "baseline.json")
            self.assertEqual(events_path(root, "k1"), d / "events.jsonl")

    def test_drift_root_lazy_mkdir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertFalse((root / "_bmad").exists())
            d = drift_root_dir(root, "k1", create=True)
            self.assertTrue(d.is_dir())


# ---------------------------------------------------------------------------
# Persistence-only helpers (no watcher)
# ---------------------------------------------------------------------------


class TestBaselinePersistence(unittest.TestCase):
    def test_persist_baseline_writes_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = SpecDriftSnapshot(
                score=0.9, requirements_total=10, requirements_satisfied=9,
                timestamp_iso="2026-06-22T00:00:00Z",
            )
            out = persist_baseline(root, "k1", snap)
            self.assertTrue(out.exists())
            data = json.loads(out.read_text("utf-8"))
            self.assertEqual(data["score"], 0.9)
            self.assertEqual(data["requirements_total"], 10)

    def test_load_baseline_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = SpecDriftSnapshot(
                score=0.7, requirements_total=5, requirements_satisfied=3,
                timestamp_iso="2026-06-22T01:00:00Z",
            )
            persist_baseline(root, "k1", snap)
            loaded = load_baseline(root, "k1")
            self.assertEqual(loaded, snap)

    def test_missing_baseline_load_returns_None_no_raise(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertIsNone(load_baseline(root, "missing-key"))

    def test_load_baseline_wraps_structural_corruption_as_spec_drift_error(
        self,
    ) -> None:
        # Regression: load_baseline docstring promises corrupt JSON
        # raises SpecDriftError so silent data loss surfaces loudly.
        # Pre-fix, only OSError/JSONDecodeError were wrapped; structural
        # corruption (missing field, wrong top-level type, non-numeric
        # score) leaked raw KeyError/TypeError/ValueError to the caller.
        # Each shape below must surface as SpecDriftError.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            drift_root_dir(root, "k1", create=True)
            # S1: missing required field -> KeyError pre-fix
            baseline_path(root, "k1").write_text(
                json.dumps({"score": 0.5}), encoding="utf-8",
            )
            with self.assertRaises(SpecDriftError):
                load_baseline(root, "k1")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            drift_root_dir(root, "k1", create=True)
            # S2: JSON list (wrong top-level type) -> TypeError pre-fix
            baseline_path(root, "k1").write_text(
                json.dumps([1, 2, 3]), encoding="utf-8",
            )
            with self.assertRaises(SpecDriftError):
                load_baseline(root, "k1")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            drift_root_dir(root, "k1", create=True)
            # S3: non-numeric score -> ValueError pre-fix
            baseline_path(root, "k1").write_text(
                json.dumps({
                    "score": "abc",
                    "requirements_total": 5,
                    "requirements_satisfied": 3,
                    "timestamp_iso": "x",
                }),
                encoding="utf-8",
            )
            with self.assertRaises(SpecDriftError):
                load_baseline(root, "k1")


class TestEventPersistence(unittest.TestCase):
    def test_append_drift_event_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            evt = SpecDriftEvent(
                baseline_score=1.0, current_score=0.8, delta=0.2,
                severity="WARNING", requirements_lost=("REQ-01",),
                timestamp_iso="2026-06-22T00:00:01Z",
            )
            out = append_drift_event(root, "k1", evt)
            self.assertTrue(out.exists())
            line = out.read_text("utf-8").strip()
            data = json.loads(line)
            self.assertEqual(data["severity"], "WARNING")
            self.assertEqual(data["requirements_lost"], ["REQ-01"])

    def test_events_jsonl_one_event_per_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(3):
                evt = SpecDriftEvent(
                    baseline_score=1.0, current_score=1.0 - i * 0.1,
                    delta=i * 0.1, severity="OK",
                    requirements_lost=(),
                    timestamp_iso=f"2026-06-22T00:00:0{i}Z",
                )
                append_drift_event(root, "k1", evt)
            lines = events_path(root, "k1").read_text("utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            for line in lines:
                json.loads(line)  # each line parses

    def test_concurrent_persist_serialized_via_lock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def _worker(i: int) -> None:
                evt = SpecDriftEvent(
                    baseline_score=1.0, current_score=0.9, delta=0.1,
                    severity="INFO", requirements_lost=(f"REQ-{i:02d}",),
                    timestamp_iso=f"2026-06-22T00:00:{i:02d}Z",
                )
                append_drift_event(root, "k1", evt)

            threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            lines = events_path(root, "k1").read_text("utf-8").splitlines()
            # All 8 events accounted for and every line parses cleanly
            # (no interleaved writes).
            self.assertEqual(len(lines), 8)
            for line in lines:
                json.loads(line)


# ---------------------------------------------------------------------------
# Watcher-level integration
# ---------------------------------------------------------------------------


class TestWatcherPersistenceIntegration(unittest.TestCase):
    def test_persistence_key_none_keeps_existing_in_memory_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w = SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
            )
            report = _report([_verdict("REQ-01", "implemented")])
            with mock.patch(_TARGET, return_value=report):
                w.set_baseline()
                w.poll()
            # No persistence side effects when persistence_key is unset.
            self.assertFalse((root / "_bmad").exists())

    def test_watcher_init_loads_persisted_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = SpecDriftSnapshot(
                score=0.6, requirements_total=10, requirements_satisfied=6,
                timestamp_iso="2026-06-22T00:00:00Z",
            )
            persist_baseline(root, "k1", snap)
            w = SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
                persistence_key="k1",
            )
            self.assertTrue(w.is_baseline_set())

    def test_set_baseline_persists_when_key_set(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w = SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
                persistence_key="k1",
            )
            report = _report([_verdict("REQ-01", "implemented")])
            with mock.patch(_TARGET, return_value=report):
                w.set_baseline()
            self.assertTrue(baseline_path(root, "k1").exists())

    def test_poll_appends_event_when_key_set(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            w = SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
                persistence_key="k1",
            )
            report = _report([_verdict("REQ-01", "implemented")])
            with mock.patch(_TARGET, return_value=report):
                w.set_baseline()
                w.poll()
            self.assertTrue(events_path(root, "k1").exists())
            lines = events_path(root, "k1").read_text("utf-8").splitlines()
            self.assertEqual(len(lines), 1)

    def test_invalid_persistence_key_rejected_at_init(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(SpecDriftError):
                SpecDriftWatcher(
                    project_root=root, spec_path=root / "spec.md",
                    persistence_key="../escape",
                )

    def test_init_supplied_baseline_with_persistence_key_writes_to_disk(self) -> None:
        # Regression: a caller passing BOTH baseline_snapshot AND
        # persistence_key would have the snapshot held in memory only,
        # silently lost on the next process restart.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = SpecDriftSnapshot(
                score=0.8, requirements_total=10, requirements_satisfied=8,
                timestamp_iso="2026-06-22T00:00:00Z",
            )
            SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
                baseline_snapshot=snap, persistence_key="k1",
            )
            # On-disk baseline must have been written so a later watcher
            # can recover it.
            self.assertTrue(baseline_path(root, "k1").exists())
            self.assertEqual(load_baseline(root, "k1"), snap)
            # Simulated process restart: new watcher with only the key
            # must rehydrate the baseline supplied at original init.
            w2 = SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
                persistence_key="k1",
            )
            self.assertTrue(w2.is_baseline_set())

    def test_init_supplied_baseline_does_not_clobber_existing_on_disk_baseline(
        self,
    ) -> None:
        # The init-time persist must NOT clobber a baseline already on
        # disk — a stale caller-supplied snapshot could otherwise erase
        # the legitimately persisted one from a prior session.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = SpecDriftSnapshot(
                score=0.5, requirements_total=10, requirements_satisfied=5,
                timestamp_iso="2026-06-22T00:00:00Z",
            )
            persist_baseline(root, "k1", old)
            stale = SpecDriftSnapshot(
                score=0.9, requirements_total=10, requirements_satisfied=9,
                timestamp_iso="2026-06-23T00:00:00Z",
            )
            SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
                baseline_snapshot=stale, persistence_key="k1",
            )
            # On-disk baseline must remain the previously persisted one.
            self.assertEqual(load_baseline(root, "k1"), old)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
