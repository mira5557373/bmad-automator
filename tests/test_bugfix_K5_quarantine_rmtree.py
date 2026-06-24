"""Round-3 fix K-5 — quarantine-then-rmtree-outside-lock + crash-resilient janitor.

Before K-5, ``gate_orchestrator._recover_from_crash_locked`` invoked
``shutil.rmtree`` directly on the orphan evidence dir INSIDE the gate
lock. For a multi-gigabyte evidence bundle on slow storage, the rmtree
could take seconds — during which every concurrent ``run_production_gate``
on the same project_root blocked on the gate lock. That defeated the
whole point of the L1 lock (serialize marker lifecycle, not bulk I/O).

K-5 splits the work:

1. Under the gate lock — atomically rename each orphan evidence dir to
   ``_bmad/gate/cleanup/<gate_id>-<uuid4>/``. ``os.rename`` is O(1)
   (a directory inode rename on the same filesystem; the cleanup root
   lives inside ``_bmad/gate/`` precisely so EXDEV cannot occur).
2. Release the gate lock.
3. Outside the lock — ``shutil.rmtree`` each quarantined dir. Slow,
   but no longer blocks other gate runs.
4. Crash resilience — if the process dies between rename and rmtree,
   ``run_cleanup_janitor`` scans ``_bmad/gate/cleanup/`` on startup
   and rmtrees any orphans. It runs BEFORE the gate lock is acquired
   (the quarantined dirs are by construction unreferenced once renamed
   into ``cleanup/``), so it can run unsynchronized without racing the
   gate lifecycle. Janitor errors are non-fatal: a per-subdir try/except
   keeps one corrupted dir from blocking the rest.

The L1+L2 + L1-followup contracts must be preserved:
- ``recover_from_crash`` STILL acquires the gate lock for the marker
  read + recovery decision.
- ``_recover_from_crash_locked`` STILL the inner-no-lock helper used by
  ``run_production_gate`` and ``run_system_gate``.
- MarkerCorruptionInvariant + the L1 / L2 audit-floor tests stay green
  (re-asserted at the bottom of this module).
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core.evidence_io import (
    get_gate_cleanup_root,
    get_gate_lock,
    run_cleanup_janitor,
)
from story_automator.core.gate_orchestrator import recover_from_crash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Mixin:
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _seed_dead_marker(
        self,
        gate_id: str = "orphan-gate",
        evidence_payload: str = '{"v": 1}',
    ) -> Path:
        """Lay down a marker referencing a dead pid + an orphan evidence dir."""
        marker_path = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        # Legacy marker (no pid) ⇒ treated as dead by recovery.
        marker_path.write_text(
            json.dumps({
                "gate_id": gate_id,
                "commit_sha": "abc123",
                "started_at": "2026-06-22T12:00:00Z",
            }) + "\n",
            encoding="utf-8",
        )
        evidence_dir = self.tmp / "_bmad" / "gate" / "evidence" / gate_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "leftover.json").write_text(
            evidence_payload, encoding="utf-8",
        )
        return evidence_dir


# ---------------------------------------------------------------------------
# K-5: quarantine inside lock, rmtree outside lock
# ---------------------------------------------------------------------------


class QuarantineInsideLockRmtreeOutsideLock(_Mixin, unittest.TestCase):
    """Orphan evidence is renamed under the lock, rmtree'd outside it."""

    def test_orphan_evidence_quarantined_inside_lock_rmtreed_outside(self) -> None:
        evidence_dir = self._seed_dead_marker()

        observed_order: list[str] = []

        real_rename = os.rename
        real_rmtree = shutil.rmtree

        def tracking_rename(src, dst, *args, **kwargs):
            observed_order.append("rename")
            return real_rename(src, dst, *args, **kwargs)

        def tracking_rmtree(path, *args, **kwargs):
            observed_order.append("rmtree")
            return real_rmtree(path, *args, **kwargs)

        with mock.patch(
            "story_automator.core.gate_orchestrator.os.rename",
            side_effect=tracking_rename,
        ), mock.patch(
            "story_automator.core.gate_orchestrator.shutil.rmtree",
            side_effect=tracking_rmtree,
        ):
            result = recover_from_crash(self.tmp)

        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], "orphan-gate")
        # The rename of the orphan evidence dir happens before any rmtree.
        # (There may be many rmtrees if other code also calls it, but the
        # first cleanup activity must be the rename.)
        self.assertIn("rename", observed_order)
        self.assertIn("rmtree", observed_order)
        rename_idx = observed_order.index("rename")
        rmtree_idx = observed_order.index("rmtree")
        self.assertLess(
            rename_idx, rmtree_idx,
            f"rename must precede rmtree, got: {observed_order}",
        )
        # Evidence dir is gone from its original location AND from quarantine.
        self.assertFalse(evidence_dir.exists())
        cleanup_root = get_gate_cleanup_root(self.tmp)
        # Cleanup root may exist (we created it) but it should be empty after
        # the rmtree pass.
        if cleanup_root.is_dir():
            self.assertEqual(
                list(cleanup_root.iterdir()), [],
                "post-recovery cleanup root must be empty",
            )


class ConcurrentGateNotBlockedBySlowRmtree(_Mixin, unittest.TestCase):
    """Slow rmtree outside the lock must not block other gates from acquiring it."""

    def test_concurrent_gate_not_blocked_by_slow_rmtree(self) -> None:
        self._seed_dead_marker(gate_id="g-a")

        # Make rmtree slow (0.3s) so we can witness the second thread
        # acquire the lock immediately after the rename phase finishes.
        rmtree_started = threading.Event()
        rmtree_release = threading.Event()
        thread_b_acquired = threading.Event()

        real_rmtree = shutil.rmtree

        def slow_rmtree(path, *args, **kwargs):
            rmtree_started.set()
            # Allow the second thread to attempt the lock during rmtree.
            rmtree_release.wait(timeout=5.0)
            return real_rmtree(path, *args, **kwargs)

        result_a: dict = {}
        result_b: dict = {}

        def worker_a() -> None:
            with mock.patch(
                "story_automator.core.gate_orchestrator.shutil.rmtree",
                side_effect=slow_rmtree,
            ):
                result_a["r"] = recover_from_crash(self.tmp)

        def worker_b() -> None:
            # Wait until rmtree is in flight (A has released the lock).
            rmtree_started.wait(timeout=5.0)
            # B should be able to acquire the gate lock with a short timeout
            # because A released it before starting the slow rmtree.
            t0 = time.monotonic()
            with get_gate_lock(self.tmp, timeout=0.5):
                thread_b_acquired.set()
                result_b["acq_dt"] = time.monotonic() - t0
                result_b["ok"] = True

        t_a = threading.Thread(target=worker_a)
        t_b = threading.Thread(target=worker_b)
        t_a.start()
        t_b.start()
        # Give B time to grab the lock, then let A's rmtree finish.
        thread_b_acquired.wait(timeout=3.0)
        rmtree_release.set()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

        self.assertTrue(result_a.get("r", {}).get("recovered"))
        self.assertTrue(result_b.get("ok"), "thread B must acquire the lock during rmtree")
        # Acquisition was effectively instant (well under the slow-rmtree's 0.3s).
        self.assertLess(result_b["acq_dt"], 0.4)


class QuarantineSubdirNamingCollisionProof(_Mixin, unittest.TestCase):
    """Two recoveries against the same gate_id must not collide in cleanup/."""

    def test_quarantine_subdir_naming_collision_proof(self) -> None:
        # Round 1: seed + recover. Evidence is renamed to a uuid-suffixed
        # cleanup dir, then rmtree'd. We patch rmtree to a no-op so the
        # quarantine subdir stays around — simulating a crash between
        # rename and rmtree.
        self._seed_dead_marker(gate_id="dup-gate")
        with mock.patch(
            "story_automator.core.gate_orchestrator.shutil.rmtree",
            side_effect=lambda *a, **kw: None,
        ):
            recover_from_crash(self.tmp)

        cleanup_root = get_gate_cleanup_root(self.tmp)
        first_round = {p.name for p in cleanup_root.iterdir()}
        self.assertEqual(len(first_round), 1, f"round1 children: {first_round}")

        # Round 2: same gate_id, same evidence path. Without uuid suffix this
        # rename would collide and either raise or silently overwrite.
        self._seed_dead_marker(gate_id="dup-gate", evidence_payload='{"v": 2}')
        with mock.patch(
            "story_automator.core.gate_orchestrator.shutil.rmtree",
            side_effect=lambda *a, **kw: None,
        ):
            recover_from_crash(self.tmp)

        second_round = {p.name for p in cleanup_root.iterdir()}
        self.assertEqual(
            len(second_round), 2,
            f"expected round2 to add a new subdir; got {second_round} "
            f"(round1: {first_round})",
        )
        # The round-1 entry must still be present; round-2 added a fresh
        # uuid-suffixed sibling rather than colliding with it.
        self.assertTrue(first_round.issubset(second_round))
        new_entries = second_round - first_round
        self.assertEqual(len(new_entries), 1)
        self.assertTrue(next(iter(new_entries)).startswith("dup-gate-"))


# ---------------------------------------------------------------------------
# K-5: janitor — crash resilience between rename and rmtree
# ---------------------------------------------------------------------------


class JanitorPicksUpOrphansOnStartup(_Mixin, unittest.TestCase):
    """``run_cleanup_janitor`` rmtrees orphaned quarantine subdirs."""

    def test_janitor_picks_up_orphans_on_startup(self) -> None:
        cleanup_root = get_gate_cleanup_root(self.tmp)
        # Pre-populate two orphaned cleanup subdirs.
        orphan_a = cleanup_root / "g-a-deadbeef"
        orphan_b = cleanup_root / "g-b-deadbeef"
        orphan_a.mkdir(parents=True)
        orphan_b.mkdir(parents=True)
        (orphan_a / "stuff.json").write_text("{}")
        (orphan_b / "more.json").write_text("{}")

        run_cleanup_janitor(self.tmp)

        self.assertFalse(orphan_a.exists())
        self.assertFalse(orphan_b.exists())


class JanitorIdempotent(_Mixin, unittest.TestCase):
    """Running the janitor twice is a no-op the second time."""

    def test_janitor_idempotent(self) -> None:
        cleanup_root = get_gate_cleanup_root(self.tmp)
        orphan = cleanup_root / "g-x-deadbeef"
        orphan.mkdir(parents=True)
        (orphan / "stuff.json").write_text("{}")

        run_cleanup_janitor(self.tmp)
        # No raise on the second invocation; cleanup root stays empty.
        run_cleanup_janitor(self.tmp)

        self.assertFalse(orphan.exists())


class JanitorPerSubdirIsolation(_Mixin, unittest.TestCase):
    """One bad subdir does not block cleanup of others."""

    def test_janitor_per_subdir_isolation(self) -> None:
        cleanup_root = get_gate_cleanup_root(self.tmp)
        bad = cleanup_root / "g-bad-1"
        good = cleanup_root / "g-good-1"
        bad.mkdir(parents=True)
        good.mkdir(parents=True)
        (bad / "x").write_text("{}")
        (good / "y").write_text("{}")

        real_rmtree = shutil.rmtree

        def selective_rmtree(path, *args, **kwargs):
            if str(path).endswith("g-bad-1"):
                raise OSError("simulated rmtree failure on bad subdir")
            return real_rmtree(path, *args, **kwargs)

        with mock.patch(
            "story_automator.core.evidence_io.shutil.rmtree",
            side_effect=selective_rmtree,
        ):
            # Must not raise — per-subdir try/except.
            run_cleanup_janitor(self.tmp)

        # ``good`` was cleaned even though ``bad`` raised.
        self.assertFalse(good.exists())
        self.assertTrue(bad.exists())


class RmtreeFailureOutsideLockDoesNotPropagate(_Mixin, unittest.TestCase):
    """rmtree raising outside the lock must not derail ``recover_from_crash``."""

    def test_rmtree_failure_outside_lock_does_not_propagate(self) -> None:
        self._seed_dead_marker(gate_id="boom-gate")

        with mock.patch(
            "story_automator.core.gate_orchestrator.shutil.rmtree",
            side_effect=OSError("simulated"),
        ):
            # Must NOT raise — outside-lock rmtree failures only surface
            # via ``cleanup_failed`` / ``cleanup_error`` in the descriptor.
            result = recover_from_crash(self.tmp)

        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], "boom-gate")
        self.assertTrue(result.get("cleanup_failed", False))
        self.assertIn("cleanup_error", result)


class ClearGateMarkerOSErrorDrainsPendingCleanup(_Mixin, unittest.TestCase):
    """Round-3 fix #20 — ``clear_gate_marker`` OSError must not leak pending_cleanup.

    Before the fix, ``_recover_from_crash_locked`` called
    ``clear_gate_marker(project_root)`` UNCONDITIONALLY after a successful
    rename of the orphan evidence dir into ``_bmad/gate/cleanup/``. Because
    ``clear_gate_marker`` catches only ``FileNotFoundError``, any other
    ``OSError`` (read-only fs, permission denied, IsADirectoryError on the
    marker unlink) propagated out BEFORE the ``(result, pending_cleanup)``
    tuple was returned. All three call sites
    (``recover_from_crash``, ``run_production_gate``, and
    ``system_gate.run_system_gate``) bind the return via tuple unpacking, so
    the local ``pending_cleanup`` reference was never assigned to the
    caller, and the outside-lock ``_rmtree_quarantined_dirs`` pass was
    skipped. The renamed evidence subdir leaked into
    ``_bmad/gate/cleanup/<gate_id>-<uuid4>/`` until the next startup
    janitor swept it.

    Fix: catch the marker-clear OSError in ``_recover_from_crash_locked``,
    surface via the existing ``cleanup_failed`` / ``cleanup_error``
    descriptor fields (mirroring the rename's OSError handling), and
    always return the tuple so the outside-lock rmtree drains the queue.
    """

    def test_clear_gate_marker_oserror_does_not_leak_pending_cleanup(self) -> None:
        self._seed_dead_marker(gate_id="marker-fail-gate")

        with mock.patch(
            "story_automator.core.gate_orchestrator.clear_gate_marker",
            side_effect=OSError("simulated readonly fs on marker unlink"),
        ):
            # Pre-fix: this raised OSError out of recover_from_crash.
            # Post-fix: returns descriptor with cleanup_failed=True.
            result = recover_from_crash(self.tmp)

        # Recovery still succeeds on the orphan-rename side; the marker
        # failure is surfaced via cleanup_failed / cleanup_error.
        self.assertTrue(
            result.get("recovered"),
            "rename succeeded so recovered=True must hold",
        )
        self.assertEqual(result.get("gate_id"), "marker-fail-gate")
        self.assertTrue(
            result.get("cleanup_failed", False),
            "marker-clear OSError must be surfaced as cleanup_failed",
        )
        self.assertIn(
            "clear_gate_marker failed",
            result.get("cleanup_error", ""),
            "cleanup_error must name the marker-clear as the failure source",
        )

        # The K-5 contract: pending_cleanup must have been drained even
        # though clear_gate_marker raised inside the lock. Pre-fix the
        # renamed subdir leaked here until the next startup janitor.
        cleanup_root = get_gate_cleanup_root(self.tmp)
        if cleanup_root.is_dir():
            leftovers = list(cleanup_root.iterdir())
            self.assertEqual(
                leftovers, [],
                f"clear_gate_marker OSError must not leak _pending_cleanup; "
                f"leftover: {[p.name for p in leftovers]}",
            )


class JanitorRunsBeforeLockOnStartup(_Mixin, unittest.TestCase):
    """The janitor must execute before the gate lock is acquired."""

    def test_janitor_runs_before_lock_on_run_production_gate_startup(self) -> None:
        # Pre-populate an orphan cleanup subdir simulating a prior crash.
        cleanup_root = get_gate_cleanup_root(self.tmp)
        orphan = cleanup_root / "g-prior-deadbeef"
        orphan.mkdir(parents=True)
        (orphan / "stuff.json").write_text("{}")

        # Hold the gate lock from another thread to demonstrate the
        # janitor runs UNlocked. If the janitor were inside the lock, it
        # would block while we hold the lock.
        from story_automator.core.evidence_io import get_gate_lock as _get_lock

        outer = _get_lock(self.tmp, timeout=5.0)
        outer.acquire()
        try:
            # Janitor itself acquires no lock; it should clear the orphan
            # even though the gate lock is held by us.
            run_cleanup_janitor(self.tmp)
        finally:
            outer.release()

        self.assertFalse(orphan.exists())


# ---------------------------------------------------------------------------
# K-5: preserve L1 + L2 audit-floor invariants under the refactor
# ---------------------------------------------------------------------------


class L1L2AuditFloorInvariantsPreserved(_Mixin, unittest.TestCase):
    """Re-run the L1+L2 audit-floor contract after the refactor."""

    def test_live_pid_marker_still_not_recovered(self) -> None:
        # Live PID marker — recovery refuses, evidence preserved.
        from story_automator.core.evidence_io import write_gate_marker

        write_gate_marker(self.tmp, "live-gate", "deadbeef")
        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "live-gate"
        evidence.mkdir(parents=True, exist_ok=True)
        important = evidence / "in-flight.json"
        important.write_text('{"ok": true}', encoding="utf-8")

        result = recover_from_crash(self.tmp)

        self.assertTrue(important.is_file(),
                        "live-pid evidence must remain untouched")
        self.assertFalse(result.get("recovered", True))
        self.assertEqual(result.get("reason"), "live-pid-still-running")

    def test_corrupt_marker_still_loud_and_targeted(self) -> None:
        # Corrupt marker carrying gate_id ⇒ targeted quarantine
        # ⇒ {recovered=False, quarantined=True, quarantine_dir,
        #     corruption_reason} contract preserved.
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(
            '{"gate_id": "lost-gate", "commit_sha": "x", not json',
            encoding="utf-8",
        )
        evidence_dir = self.tmp / "_bmad" / "gate" / "evidence" / "lost-gate"
        evidence_dir.mkdir(parents=True)
        important = evidence_dir / "important.json"
        important.write_text('{"do_not_delete": true}', encoding="utf-8")

        result = recover_from_crash(self.tmp)

        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"])
        self.assertIn("quarantine_dir", result)
        self.assertIn("corruption_reason", result)
        # Evidence was MOVED — must not still exist at original path.
        self.assertFalse(important.exists())


class CleanupRootDoesNotPolluteEvidence(_Mixin, unittest.TestCase):
    """``cleanup/`` lives at the gate root, NOT inside ``evidence/``."""

    def test_cleanup_root_is_gate_local_not_evidence_local(self) -> None:
        cleanup_root = get_gate_cleanup_root(self.tmp)
        gate_root = self.tmp / "_bmad" / "gate"
        evidence_root = gate_root / "evidence"
        # cleanup root must be a direct child of gate/, never under evidence/.
        self.assertEqual(cleanup_root.parent, gate_root)
        self.assertNotEqual(cleanup_root, evidence_root)
        self.assertFalse(
            str(cleanup_root).startswith(str(evidence_root)),
            "cleanup root must not live under evidence/",
        )


# ---------------------------------------------------------------------------
# K-5: pending-cleanup drain on early-return paths of run_production_gate /
# run_system_gate. Pre-fix, the reuse-shortcut ``return existing`` and the
# lie-detector ``return {"action": "baseline_drift", ...}`` exited the inner
# try block via the lock-release finally without ever running the
# outside-lock ``_rmtree_quarantined_dirs(_pending_cleanup)`` pass. The
# renamed orphan leaked into ``_bmad/gate/cleanup/`` until the next startup
# janitor swept it. Fix: function-level finally so EVERY exit path drains
# the queue.
# ---------------------------------------------------------------------------


class PendingCleanupDrainedOnEarlyReturnPaths(_Mixin, unittest.TestCase):
    """run_production_gate / run_system_gate drain _pending_cleanup on every exit."""

    def _minimal_profile(self) -> dict:
        return {
            "version": 1,
            "id": "test",
            "matrix": {
                "P0": {"coverage_pct": 80, "levels": ["unit"]},
                "P1": {"coverage_pct": 60, "levels": ["unit"]},
                "P2": {"coverage_pct": 40, "levels": ["unit"]},
                "P3": {"coverage_pct": 20, "levels": ["unit"]},
            },
            "categories": {"code": ["correctness"], "system": []},
        }

    def _persist_reusable_gate(self, gate_id: str, commit_sha: str,
                               profile: dict, factory_version: str) -> None:
        from story_automator.core.evidence_io import persist_gate_file
        from story_automator.core.gate_schema import make_gate_file
        from story_automator.core.product_profile import compute_profile_hash

        gate_file = make_gate_file(
            gate_id=gate_id,
            target={"kind": "story", "id": "s1"},
            commit_sha=commit_sha,
            profile={
                "id": profile.get("id", "test"),
                "version": profile.get("version", 1),
                "hash": compute_profile_hash(profile),
            },
            factory_version=factory_version,
            categories={"correctness": {"verdict": "PASS", "evidence": []}},
            overall="PASS",
        )
        persist_gate_file(self.tmp, gate_file)

    def test_reuse_shortcut_drains_pending_cleanup(self) -> None:
        """Reuse-path ``return existing`` must still rmtree the renamed orphan.

        Before the fix, _recover_from_crash_locked renamed the orphan evidence
        dir into ``_bmad/gate/cleanup/<gate_id>-<uuid>/`` and populated
        ``_pending_cleanup``, but the ``return existing`` early-return at the
        reuse shortcut exited via the lock-release finally without reaching
        the outside-lock rmtree pass. The orphan leaked until the next
        startup janitor swept it.
        """
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.gate_orchestrator import run_production_gate

        # Seed a dead-PID legacy marker pointing at a DIFFERENT gate_id so
        # recovery quarantines the orphan evidence dir for that gate.
        self._seed_dead_marker(gate_id="orphan-gate")

        # Persist a reusable gate file for the gate_id we are about to
        # ``run_production_gate(...)``. check_gate_reuse will return it,
        # triggering the ``return existing`` early-return.
        profile = self._minimal_profile()
        self._persist_reusable_gate(
            "reuse-gate", "abc123", profile, "1.0.0",
        )

        result = run_production_gate(
            self.tmp, "reuse-gate",
            commit_sha="abc123",
            target={"kind": "story", "id": "s1"},
            profile=profile,
            factory_version="1.0.0",
            registry=CollectorRegistry(),
        )

        # Reuse-path returned the cached gate.
        self.assertEqual(result.get("overall"), "PASS")
        self.assertEqual(result.get("gate_id"), "reuse-gate")

        # K-5 contract: the cleanup root must be empty after the call.
        # Pre-fix this asserted leftover ``orphan-gate-<uuid>`` entries.
        cleanup_root = get_gate_cleanup_root(self.tmp)
        if cleanup_root.is_dir():
            leftovers = list(cleanup_root.iterdir())
            self.assertEqual(
                leftovers, [],
                f"reuse-path early-return must drain _pending_cleanup; "
                f"leftover: {[p.name for p in leftovers]}",
            )

    def test_lie_detector_baseline_drift_return_drains_pending_cleanup(self) -> None:
        """Lie-detector ``baseline_drift`` return must still rmtree the renamed orphan.

        Same shape as the reuse-path test but exercising the
        ``enable_lie_detector=True`` early-return. The drift-detection helper
        is monkey-patched to return ``ok=False`` so the
        ``{"action": "baseline_drift", ...}`` branch fires.
        """
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core import gate_orchestrator as _go

        # Seed a dead-PID legacy marker pointing at a DIFFERENT gate_id.
        self._seed_dead_marker(gate_id="orphan-gate-2")

        profile = self._minimal_profile()

        # Stub detect_baseline_drift to return a not-ok outcome, forcing
        # the lie-detector early-return path.
        class _Outcome:
            ok = False

            def to_dict(self) -> dict:
                return {"reason": "expected-sha-mismatch"}

        with mock.patch.object(
            _go, "detect_baseline_drift", return_value=_Outcome(),
        ):
            result = _go.run_production_gate(
                self.tmp, "drift-gate",
                commit_sha="abc123",
                target={"kind": "story", "id": "s1"},
                profile=profile,
                factory_version="1.0.0",
                registry=CollectorRegistry(),
                enable_lie_detector=True,
                baseline_sha="baseline-deadbeef",
            )

        # Lie-detector path returned the baseline_drift descriptor.
        self.assertEqual(result.get("action"), "baseline_drift")
        self.assertEqual(result.get("gate_id"), "drift-gate")

        # K-5 contract: cleanup root must be empty after the call.
        cleanup_root = get_gate_cleanup_root(self.tmp)
        if cleanup_root.is_dir():
            leftovers = list(cleanup_root.iterdir())
            self.assertEqual(
                leftovers, [],
                f"lie-detector early-return must drain _pending_cleanup; "
                f"leftover: {[p.name for p in leftovers]}",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
