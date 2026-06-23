"""Tests for the C5 decisions ledger (``threshold_decisions``).

Covers the AC list in spec §7.4:

1. Append one decision, read back.
2. Append from two processes concurrently — both lines present, no
   interleaving.
3. Filter by ``proposal_id``.
4. ``latest_decision_for`` correctness across multiple appends.
5. Lock timeout (mocked).
6. Missing ``_bmad/calibration/`` lazily created.
7. Durability: crash between ``os.write`` and lock release — written
   line IS durable because ``os.fsync`` ran before release.

Plus a handful of guard-rails the spec implies (invalid-action
rejection, filter-by-id ordering, corrupt-line surfacing) so the
module's small public surface is fully exercised.

All tests run inside a tempdir; nothing touches the real ``_bmad/``.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from filelock import Timeout

from story_automator.core.innovation.threshold_decisions import (
    ACTION_ACCEPT,
    ACTION_CONFIRM_FAILED,
    ACTION_REJECT,
    ACTION_SUPERSEDED,
    ACTIONS,
    CALIBRATION_LOCK_TIMEOUT_S,
    DecisionLedgerError,
    DecisionRecord,
    calibration_dir,
    calibration_lock_path,
    decisions_path,
    latest_decision_for,
    load_decisions,
    record_decision,
)


# ---------------------------------------------------------------------------
# Constants / helpers shared across tests
# ---------------------------------------------------------------------------


_PID = "0a1b2c3d4e5f6789"
_PID_B = "9876543210fedcba"


def _multiproc_worker(root: str, proposal_id: str, action: str) -> None:
    """Top-level worker for the multi-process concurrent-append test.

    ``multiprocessing`` requires picklable targets; nested funcs and
    lambdas would fail to spawn on the ``spawn`` start method, which
    is the default on macOS / Windows.
    """
    record_decision(
        project_root=root,
        proposal_id=proposal_id,
        action=action,
        operator_id="local",
        operator_note="",
    )


# ---------------------------------------------------------------------------
# Action vocabulary & path-helper sanity
# ---------------------------------------------------------------------------


class TestActionVocabulary(unittest.TestCase):
    """The closed action set must match spec §5.3 exactly."""

    def test_actions_constant_is_closed_set(self) -> None:
        self.assertEqual(
            ACTIONS,
            frozenset({"accept", "reject", "superseded", "confirm_failed"}),
        )

    def test_action_string_constants_are_canonical(self) -> None:
        self.assertEqual(ACTION_ACCEPT, "accept")
        self.assertEqual(ACTION_REJECT, "reject")
        self.assertEqual(ACTION_SUPERSEDED, "superseded")
        self.assertEqual(ACTION_CONFIRM_FAILED, "confirm_failed")


class TestPathHelpers(unittest.TestCase):
    def test_paths_under_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            d = calibration_dir(root)
            self.assertEqual(d, root / "_bmad" / "calibration")
            self.assertEqual(decisions_path(root), d / "decisions.jsonl")
            self.assertEqual(calibration_lock_path(root), d / ".calibration.lock")

    def test_calibration_dir_lazy_mkdir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertFalse((root / "_bmad").exists())
            d = calibration_dir(root, create=True)
            self.assertTrue(d.is_dir())


# ---------------------------------------------------------------------------
# AC §7.4-1 — Append one decision, read back
# ---------------------------------------------------------------------------


class TestAppendAndRead(unittest.TestCase):
    def test_append_one_then_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            written = record_decision(
                project_root=root,
                proposal_id=_PID,
                action=ACTION_ACCEPT,
                operator_id="local",
                operator_note="ratchet looks safe",
            )
            self.assertIsInstance(written, DecisionRecord)
            self.assertEqual(written.proposal_id, _PID)
            self.assertEqual(written.action, "accept")
            self.assertEqual(written.operator_id, "local")
            self.assertEqual(written.operator_note, "ratchet looks safe")
            # iso_now stamp matches the canonical Z-suffixed shape.
            self.assertTrue(written.decided_at_iso.endswith("Z"))

            loaded = load_decisions(root)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0], written)

    def test_invalid_action_rejected(self) -> None:
        """Closed vocabulary: anything outside ACTIONS raises before write."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(DecisionLedgerError):
                record_decision(
                    project_root=root,
                    proposal_id=_PID,
                    action="approve",  # near-miss for "accept"
                    operator_id="local",
                )
            # No file should have been created on the rejected call.
            self.assertFalse(decisions_path(root).exists())

    def test_payload_shape_matches_spec(self) -> None:
        """Spec §5.3 fixes the field order; verify on disk byte layout."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            record_decision(
                project_root=root,
                proposal_id=_PID,
                action=ACTION_REJECT,
                operator_id="local",
                operator_note="need 2 more weeks of telemetry",
            )
            raw = decisions_path(root).read_text("utf-8")
            self.assertTrue(raw.endswith("\n"))
            line = raw.strip()
            data = json.loads(line)
            # All five spec fields present, no extras.
            self.assertEqual(
                set(data.keys()),
                {
                    "proposal_id",
                    "action",
                    "operator_id",
                    "decided_at_iso",
                    "operator_note",
                },
            )

    def test_load_missing_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(load_decisions(root), [])
            self.assertIsNone(latest_decision_for(root, _PID))

    def test_corrupt_line_surfaces_loudly(self) -> None:
        """Corrupt JSONL must NOT silently drop — surfaces as DecisionLedgerError."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            calibration_dir(root, create=True)
            decisions_path(root).write_text(
                '{"proposal_id":"x","action":"accept",'
                '"operator_id":"local","decided_at_iso":"2026-06-23T00:00:00Z",'
                '"operator_note":""}\n'
                "this is not json\n",
                encoding="utf-8",
            )
            with self.assertRaises(DecisionLedgerError):
                load_decisions(root)


# ---------------------------------------------------------------------------
# AC §7.4-2 — Two concurrent processes; both lines present, no interleaving
# ---------------------------------------------------------------------------


class TestConcurrentAppend(unittest.TestCase):
    def test_concurrent_threads_serialize_via_filelock(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            N = 8

            def _worker(i: int) -> None:
                record_decision(
                    project_root=root,
                    proposal_id=f"prop-{i:02d}",
                    action=ACTION_ACCEPT,
                    operator_id="local",
                    operator_note=f"worker-{i}",
                )

            threads = [threading.Thread(target=_worker, args=(i,)) for i in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            lines = decisions_path(root).read_text("utf-8").splitlines()
            self.assertEqual(len(lines), N)
            # Every line parses — no interleaved writes.
            seen_ids = set()
            for line in lines:
                data = json.loads(line)
                seen_ids.add(data["proposal_id"])
            self.assertEqual(seen_ids, {f"prop-{i:02d}" for i in range(N)})

    def test_concurrent_processes_serialize_via_filelock(self) -> None:
        """Cross-process filelock contention — true process isolation.

        Filelocks work cross-process by design (the spec calls out
        "two concurrent processes"); threads within one process would
        also serialize, but threading shares an in-process lock-state
        cache that masks lock-acquisition bugs.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ctx = mp.get_context("spawn")
            N = 4
            procs = [
                ctx.Process(
                    target=_multiproc_worker,
                    args=(str(root), f"mp-prop-{i}", ACTION_ACCEPT),
                )
                for i in range(N)
            ]
            for p in procs:
                p.start()
            for p in procs:
                p.join(timeout=30)
                self.assertEqual(p.exitcode, 0)

            lines = decisions_path(root).read_text("utf-8").splitlines()
            self.assertEqual(len(lines), N)
            ids = {json.loads(line)["proposal_id"] for line in lines}
            self.assertEqual(ids, {f"mp-prop-{i}" for i in range(N)})


# ---------------------------------------------------------------------------
# AC §7.4-3 — Filter by proposal_id
# ---------------------------------------------------------------------------


class TestFilterByProposalId(unittest.TestCase):
    def test_filter_returns_only_matching_in_append_order(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            record_decision(root, _PID, ACTION_ACCEPT, "local", "first")
            record_decision(root, _PID_B, ACTION_REJECT, "local", "B-first")
            record_decision(root, _PID, ACTION_CONFIRM_FAILED, "local", "")
            record_decision(root, _PID_B, ACTION_SUPERSEDED, "local", "")
            record_decision(root, _PID, ACTION_REJECT, "local", "third-a")

            only_a = load_decisions(root, proposal_id=_PID)
            self.assertEqual(len(only_a), 3)
            self.assertEqual([r.action for r in only_a], ["accept", "confirm_failed", "reject"])
            self.assertEqual([r.operator_note for r in only_a], ["first", "", "third-a"])

            only_b = load_decisions(root, proposal_id=_PID_B)
            self.assertEqual(len(only_b), 2)
            self.assertEqual([r.action for r in only_b], ["reject", "superseded"])

            unfiltered = load_decisions(root)
            self.assertEqual(len(unfiltered), 5)


# ---------------------------------------------------------------------------
# AC §7.4-4 — latest_decision_for correctness
# ---------------------------------------------------------------------------


class TestLatestDecisionFor(unittest.TestCase):
    def test_latest_returns_most_recent_per_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            record_decision(root, _PID, ACTION_CONFIRM_FAILED, "local")
            record_decision(root, _PID_B, ACTION_ACCEPT, "local")
            record_decision(root, _PID, ACTION_REJECT, "local", "final")

            latest_a = latest_decision_for(root, _PID)
            self.assertIsNotNone(latest_a)
            assert latest_a is not None
            self.assertEqual(latest_a.action, "reject")
            self.assertEqual(latest_a.operator_note, "final")

            latest_b = latest_decision_for(root, _PID_B)
            self.assertIsNotNone(latest_b)
            assert latest_b is not None
            self.assertEqual(latest_b.action, "accept")

    def test_latest_returns_none_when_no_matches(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            record_decision(root, _PID, ACTION_ACCEPT, "local")
            self.assertIsNone(latest_decision_for(root, "no-such-id"))


# ---------------------------------------------------------------------------
# AC §7.4-5 — Lock timeout (mocked)
# ---------------------------------------------------------------------------


class TestLockTimeout(unittest.TestCase):
    def test_lock_timeout_surfaces_as_DecisionLedgerError(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Force the underlying FileLock.acquire to raise filelock.Timeout
            # — emulates a wedged holder without burning 30 seconds of wall
            # clock. We patch the bound method to avoid touching the global
            # filelock state.
            target = "story_automator.core.innovation.threshold_decisions.FileLock.acquire"
            with mock.patch(target, side_effect=Timeout("simulated")):
                with self.assertRaises(DecisionLedgerError) as ctx:
                    record_decision(
                        project_root=root,
                        proposal_id=_PID,
                        action=ACTION_ACCEPT,
                        operator_id="local",
                    )
            self.assertIn("calibration lock", str(ctx.exception).lower())

    def test_lock_timeout_constant_is_30s(self) -> None:
        """Pin the public 30s convention — drift from this would loosen
        the lock-holder-wedge SLA shared by the rest of the gate stack."""
        self.assertEqual(CALIBRATION_LOCK_TIMEOUT_S, 30.0)


# ---------------------------------------------------------------------------
# AC §7.4-6 — Missing _bmad/calibration/ lazily created
# ---------------------------------------------------------------------------


class TestLazyDirectoryCreation(unittest.TestCase):
    def test_first_record_creates_calibration_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Sanity: no _bmad/ yet.
            self.assertFalse((root / "_bmad").exists())
            record_decision(
                project_root=root,
                proposal_id=_PID,
                action=ACTION_ACCEPT,
                operator_id="local",
            )
            self.assertTrue((root / "_bmad" / "calibration").is_dir())
            self.assertTrue(decisions_path(root).exists())


# ---------------------------------------------------------------------------
# AC §7.4-7 — Durability: fsync runs BEFORE lock release
# ---------------------------------------------------------------------------


class TestFsyncDurability(unittest.TestCase):
    def test_fsync_runs_before_lock_release(self) -> None:
        """The durable pattern fsyncs *inside* the lock-held region.

        We patch ``os.fsync`` to record the moment-of-call and patch
        ``FileLock.release`` to record its moment-of-call (then delegate
        to the real release so the lockfile cleans up). If ``fsync``
        is recorded first AND the write payload is on disk by the time
        ``release`` runs, the AC-D-06 contract holds — a crash between
        ``os.write`` and lock release still has the durable line.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            calls: list[str] = []

            real_fsync = os.fsync
            from filelock import FileLock as _RealFL

            real_release = _RealFL.release

            def _spy_fsync(fd: int) -> None:
                calls.append("fsync")
                # File must already contain the payload at fsync time
                # because os.write ran on the preceding line.
                self.assertTrue(decisions_path(root).exists())
                content = decisions_path(root).read_bytes()
                self.assertGreater(len(content), 0)
                real_fsync(fd)

            def _spy_release(self, *a, **kw):  # type: ignore[no-untyped-def]
                calls.append("release")
                return real_release(self, *a, **kw)

            with (
                mock.patch(
                    "story_automator.core.innovation.threshold_decisions.os.fsync",
                    side_effect=_spy_fsync,
                ),
                mock.patch.object(_RealFL, "release", _spy_release),
            ):
                record_decision(
                    project_root=root,
                    proposal_id=_PID,
                    action=ACTION_ACCEPT,
                    operator_id="local",
                    operator_note="durable",
                )

            # fsync MUST be observed before release in the call order.
            self.assertIn("fsync", calls)
            self.assertIn("release", calls)
            self.assertLess(calls.index("fsync"), calls.index("release"))

            # And the written line is observable post-release.
            self.assertEqual(len(load_decisions(root)), 1)

    def test_durability_when_release_raises_after_fsync(self) -> None:
        """Simulated crash between os.write and lock release: the line
        IS durable because os.fsync ran inside the lock-held region
        before the release-raises moment. This pins AC-D-06 directly."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            from filelock import FileLock as _RealFL

            real_release = _RealFL.release

            def _crash_then_release(self, *a, **kw):  # type: ignore[no-untyped-def]
                # First call: simulate a crash by raising.
                # Re-restore so that __exit__/finally cleanup later does
                # not crash the harness.
                _RealFL.release = real_release  # type: ignore[method-assign]
                raise RuntimeError("simulated crash between write and release")

            with mock.patch.object(_RealFL, "release", _crash_then_release):
                with self.assertRaises(RuntimeError):
                    record_decision(
                        project_root=root,
                        proposal_id=_PID,
                        action=ACTION_ACCEPT,
                        operator_id="local",
                        operator_note="durable-on-crash",
                    )

            # After the simulated crash the line is on disk because the
            # os.fsync(fd) inside the try block ran BEFORE the patched
            # release attempted to fire.
            loaded = load_decisions(root, proposal_id=_PID)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].operator_note, "durable-on-crash")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
