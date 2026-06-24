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

    def test_init_supplied_baseline_does_not_clobber_in_toctou_window(
        self,
    ) -> None:
        # Regression: pre-fix, ``__init__`` did ``not exists() ->
        # persist_baseline(...)`` with NO lock continuity between the
        # two calls. A peer process landing a legitimate baseline in
        # the TOCTOU window (after our exists() returned False but
        # before persist_baseline acquired its lock) would have its
        # baseline silently overwritten by our stale caller-supplied
        # snapshot — directly contradicting the lines 165-166 docstring
        # promise that "a previously-persisted baseline is never
        # clobbered by a stale caller-supplied snapshot". The fix adds
        # ``if_absent=True`` to persist_baseline, which re-checks
        # existence INSIDE the lock and skips the write when a baseline
        # already exists. This test simulates the race by patching
        # ``Path.exists`` at the spec_drift_watcher view of
        # baseline_path so the outer check returns False AND drops a
        # peer-persisted baseline inside the patched call (representing
        # B's write landing in the window).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            peer = SpecDriftSnapshot(
                score=0.95, requirements_total=20, requirements_satisfied=19,
                timestamp_iso="2026-06-23T00:00:00Z",
            )
            stale = SpecDriftSnapshot(
                score=0.5, requirements_total=10, requirements_satisfied=5,
                timestamp_iso="2026-06-22T00:00:00Z",
            )

            # The exists() call happens on the Path returned by
            # ``baseline_path(...)``. Patch Path.exists globally for the
            # duration of __init__ so it returns False (mirroring an
            # empty drift dir at check time) while we simultaneously
            # persist the peer baseline to disk inside the same call
            # (representing B's write landing in the TOCTOU window).
            call_state = {"persisted_peer": False}
            original_exists = Path.exists

            def _spoofed_exists(self_path: Path) -> bool:
                target = baseline_path(root, "k1")
                if self_path == target and not call_state["persisted_peer"]:
                    # Simulate peer process B persisting its baseline
                    # in the TOCTOU window — after our outer exists()
                    # returned False but before our persist_baseline
                    # acquires the lock.
                    persist_baseline(root, "k1", peer)
                    call_state["persisted_peer"] = True
                    # Return False so the outer guard in __init__
                    # proceeds to call persist_baseline (as it would
                    # have observed False before B's write landed).
                    return False
                return original_exists(self_path)

            with mock.patch.object(Path, "exists", _spoofed_exists):
                SpecDriftWatcher(
                    project_root=root, spec_path=root / "spec.md",
                    baseline_snapshot=stale, persistence_key="k1",
                )
            # The peer's baseline must remain on disk — the stale
            # caller-supplied snapshot must NOT have clobbered it.
            self.assertEqual(load_baseline(root, "k1"), peer)

    def test_poll_auto_init_does_not_clobber_concurrent_on_disk_baseline(
        self,
    ) -> None:
        # Regression: pre-fix, the auto-init branch in ``poll()`` (no
        # baseline observed in memory) unconditionally called
        # ``persist_baseline(...)``, while ``__init__`` carefully
        # guarded its own write with an ``exists()`` check. A second
        # process that persisted a baseline between this watcher's
        # ``__init__`` (which observed an empty drift dir) and its
        # first ``poll()`` would have its baseline silently overwritten
        # by the in-memory auto-init snapshot — directly contradicting
        # the docstring promise that "a previously-persisted baseline
        # is never clobbered by a stale caller-supplied snapshot."
        # The fix mirrors the __init__ exists-guard at the auto-init
        # call site so a concurrent writer's baseline is preserved.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Step 1: construct watcher A with persistence_key but no
            # on-disk baseline yet — __init__'s load_baseline returns
            # None, so A._baseline stays None.
            w = SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
                persistence_key="k1",
            )
            self.assertFalse(w.is_baseline_set())
            # Step 2: simulate a peer process B persisting a baseline
            # between A's __init__ and A's first poll().
            peer = SpecDriftSnapshot(
                score=0.95, requirements_total=20, requirements_satisfied=19,
                timestamp_iso="2026-06-23T00:00:00Z",
            )
            persist_baseline(root, "k1", peer)
            self.assertEqual(load_baseline(root, "k1"), peer)
            # Step 3: A.poll() fires; check_compliance returns a
            # regressed report so the auto-init in-memory snapshot
            # is strictly worse than B's persisted baseline.
            report = _report([
                _verdict("REQ-01", "missing"),
                _verdict("REQ-02", "missing"),
            ])
            with mock.patch(_TARGET, return_value=report):
                w.poll()
            # The peer's baseline must remain on disk.
            self.assertEqual(load_baseline(root, "k1"), peer)

    def test_poll_auto_init_does_not_clobber_in_toctou_window(
        self,
    ) -> None:
        # Regression: pre-fix, ``poll()`` auto-init did
        # ``not exists() -> persist_baseline(...)`` with NO lock
        # continuity between the two calls. The companion
        # ``test_poll_auto_init_does_not_clobber_concurrent_on_disk_baseline``
        # above covers only the strictly-sequential case (peer persists
        # BEFORE ``poll()`` is called), so A's outer ``exists()`` check
        # already observes True and the auto-init persist is skipped at
        # the outer guard. That test never opens the actual TOCTOU
        # window: a peer that lands its persist BETWEEN A's outer
        # ``exists()`` returning False and A's ``persist_baseline`` lock
        # acquire would still get clobbered pre-fix. The fix adds
        # ``if_absent=True`` to ``persist_baseline``, which re-checks
        # existence INSIDE the lock and skips the write when a baseline
        # already exists. This test simulates the interleave by patching
        # ``Path.exists`` to return False AND drop a peer-persisted
        # baseline inside the patched call (representing B's write
        # landing in the window), mirroring the ``__init__`` interleave
        # regression test at line 401 but exercising the ``poll()``
        # auto-init call site at spec_drift_watcher.py:318.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Step 1: construct watcher A with persistence_key but no
            # on-disk baseline — __init__'s load_baseline returns None,
            # so A._baseline stays None and poll() will hit auto-init.
            w = SpecDriftWatcher(
                project_root=root, spec_path=root / "spec.md",
                persistence_key="k1",
            )
            self.assertFalse(w.is_baseline_set())

            peer = SpecDriftSnapshot(
                score=0.95, requirements_total=20, requirements_satisfied=19,
                timestamp_iso="2026-06-23T00:00:00Z",
            )
            # Step 2: A.poll() fires. check_compliance returns a
            # regressed report so the auto-init in-memory snapshot is
            # strictly worse than B's persisted baseline (score 0.0 vs
            # peer's 0.95). The TOCTOU interleave is injected via the
            # patched Path.exists below: on the first call against the
            # baseline path, peer B persists its baseline AND exists()
            # returns False (mirroring A's exists() observing the empty
            # drift dir before B's write landed).
            report = _report([
                _verdict("REQ-01", "missing"),
                _verdict("REQ-02", "missing"),
            ])
            call_state = {"persisted_peer": False}
            original_exists = Path.exists

            def _spoofed_exists(self_path: Path) -> bool:
                target = baseline_path(root, "k1")
                if self_path == target and not call_state["persisted_peer"]:
                    # Simulate peer process B persisting its baseline
                    # in the TOCTOU window — after our outer exists()
                    # returned False but before our persist_baseline
                    # acquires the lock.
                    persist_baseline(root, "k1", peer)
                    call_state["persisted_peer"] = True
                    # Return False so the outer guard in poll()
                    # proceeds to call persist_baseline (as it would
                    # have observed False before B's write landed).
                    return False
                return original_exists(self_path)

            with mock.patch(_TARGET, return_value=report), \
                    mock.patch.object(Path, "exists", _spoofed_exists):
                w.poll()
            # The peer's baseline must remain on disk — A's stale
            # auto-init snapshot must NOT have clobbered it.
            self.assertEqual(load_baseline(root, "k1"), peer)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
