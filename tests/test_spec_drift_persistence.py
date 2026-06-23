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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
