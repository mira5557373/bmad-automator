"""Reproducer + regression tests for L1 + L2 (gate-marker race + over-quarantine).

L1: two concurrent run_production_gate calls against the same project_root
   could race on _bmad/gate/gate-in-progress.json — process B mistakenly
   "recovers" A's still-running gate, wiping A's evidence dir mid-flight.

L2 variant: when read_gate_marker raises GateMarkerCorruptedError,
   recover_from_crash quarantined EVERY child of evidence/, breaking Merkle
   reverification of all historical gates. Only the in-flight gate should
   be quarantined.

Fix:
- filelock.FileLock around marker lifecycle (write_marker → collectors →
  clear_marker) so concurrent calls serialize.
- Marker carries pid + started_at additively. recover_from_crash checks
  psutil.pid_exists(pid) and refuses to recover a live gate.
- Targeted quarantine: try to extract gate_id from the corrupted marker;
  if found, only quarantine evidence/<gate_id>/. If unreadable, quarantine
  only the marker file. Leave the rest of evidence/ alone.

Preserves the MarkerCorruptionInvariant (tests/test_audit_regression.py):
{recovered=False, quarantined=True, quarantine_dir, corruption_reason}
contract is unchanged — only the SCOPE of what moves into quarantine
narrows.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from filelock import FileLock, Timeout

from story_automator.core.evidence_io import (
    get_gate_lock,
    write_gate_marker,
)
from story_automator.core.gate_orchestrator import (
    recover_from_crash,
)


class _Mixin:
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# L1 — liveness checks + lock semantics
# ---------------------------------------------------------------------------


class LivePidMarkerNotRecovered(_Mixin, unittest.TestCase):
    """When the marker names a live pid, recover_from_crash must refuse."""

    def test_live_pid_marker_not_recovered(self) -> None:
        # write_gate_marker now stamps os.getpid() additively
        write_gate_marker(self.tmp, "live-gate", "deadbeef")
        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "live-gate"
        evidence.mkdir(parents=True)
        important = evidence / "in-flight.json"
        important.write_text('{"ok": true}', encoding="utf-8")

        result = recover_from_crash(self.tmp)

        # Must NOT wipe a live gate's evidence dir.
        self.assertTrue(important.is_file(),
                        "live-pid evidence must be preserved")
        self.assertFalse(result.get("recovered", True),
                         "live-pid marker is not recoverable")
        self.assertEqual(result.get("reason"), "live-pid-still-running")
        self.assertEqual(result.get("pid"), os.getpid())
        # Marker must still be present — we did not clear it.
        marker = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        self.assertTrue(marker.is_file())


class DeadPidMarkerRecovered(_Mixin, unittest.TestCase):
    """When the marker names a dead pid, recover_from_crash proceeds normally."""

    def test_dead_pid_marker_recovered(self) -> None:
        # Pick a pid that is almost certainly dead. We pick 999999 — psutil
        # confirms pid_exists is False for it on every supported platform.
        import json

        from story_automator.core.utils import iso_now

        marker_path = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker_path.parent.mkdir(parents=True)
        payload = {
            "gate_id": "dead-gate",
            "commit_sha": "deadbeef",
            "started_at": iso_now(),
            "pid": 999999,
        }
        marker_path.write_text(json.dumps(payload), encoding="utf-8")

        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "dead-gate"
        evidence.mkdir(parents=True)
        (evidence / "orphan.json").write_text("{}")

        result = recover_from_crash(self.tmp)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], "dead-gate")
        self.assertFalse(result["had_verdict"])
        # Marker cleared.
        self.assertFalse(marker_path.exists())
        # Orphan evidence cleaned.
        self.assertFalse(evidence.exists())


class NoPidLegacyMarkerRecovered(_Mixin, unittest.TestCase):
    """Markers written by older versions (no pid field) still recover."""

    def test_no_pid_marker_legacy_recovered(self) -> None:
        import json

        from story_automator.core.utils import iso_now

        marker_path = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker_path.parent.mkdir(parents=True)
        # Legacy shape — no pid.
        payload = {
            "gate_id": "legacy-gate",
            "commit_sha": "legacy-sha",
            "started_at": iso_now(),
        }
        marker_path.write_text(json.dumps(payload), encoding="utf-8")

        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "legacy-gate"
        evidence.mkdir(parents=True)
        (evidence / "orphan.json").write_text("{}")

        result = recover_from_crash(self.tmp)
        # Legacy treated as dead → recover.
        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], "legacy-gate")
        self.assertFalse(evidence.exists())


class ConcurrentGatesDoNotRace(_Mixin, unittest.TestCase):
    """Two concurrent run_production_gate calls must NOT clobber each other.

    Reproduces L1: without the fix, thread B sees A's marker, sees no
    verdict, shutil.rmtrees A's evidence dir, then clears A's marker. A's
    persist_evidence_record then crashes (or writes into a wiped dir).
    """

    def test_concurrent_gates_serialize_via_lock(self) -> None:
        # We don't need a full run_production_gate stack here — that pulls
        # in too many real collectors. Instead, exercise the lock helper
        # directly: two threads hold the gate lock; the second must block
        # until the first releases.
        order: list[str] = []
        gate_dir = self.tmp / "_bmad" / "gate"
        gate_dir.mkdir(parents=True)

        def worker_a() -> None:
            with get_gate_lock(self.tmp, timeout=5.0):
                order.append("a-enter")
                time.sleep(0.3)
                order.append("a-exit")

        def worker_b() -> None:
            time.sleep(0.05)
            with get_gate_lock(self.tmp, timeout=5.0):
                order.append("b-enter")
                order.append("b-exit")

        t_a = threading.Thread(target=worker_a)
        t_b = threading.Thread(target=worker_b)
        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

        # B must have entered AFTER A exited — the lock serialized them.
        self.assertEqual(order, ["a-enter", "a-exit", "b-enter", "b-exit"])


class LockTimeoutClearError(_Mixin, unittest.TestCase):
    """When the lock is held by another holder, callers see a clear timeout."""

    def test_lock_timeout_raises_clear_error(self) -> None:
        gate_dir = self.tmp / "_bmad" / "gate"
        gate_dir.mkdir(parents=True)
        lock_path = gate_dir / ".gate.lock"
        # Hold the lock from a separate FileLock instance.
        outer = FileLock(str(lock_path))
        outer.acquire(timeout=5.0)
        try:
            with self.assertRaises(Timeout):
                with get_gate_lock(self.tmp, timeout=0.2):
                    self.fail("should not have acquired the lock")
        finally:
            outer.release()


# ---------------------------------------------------------------------------
# L2 — targeted quarantine on marker corruption
# ---------------------------------------------------------------------------


class CorruptMarkerTargetsOnlyNamedGate(_Mixin, unittest.TestCase):
    """A corrupted marker that still names a gate_id must NOT take down all of
    evidence/. Only evidence/<gate_id>/ is quarantined; siblings stay live."""

    def test_corrupt_marker_targets_only_named_gate(self) -> None:
        gate_root = self.tmp / "_bmad" / "gate"
        gate_root.mkdir(parents=True)
        # Pre-seed three historical gate evidence dirs.
        for gid in ("g1", "g2", "g3"):
            d = gate_root / "evidence" / gid
            d.mkdir(parents=True)
            (d / f"{gid}.json").write_text(f'{{"gate": "{gid}"}}', encoding="utf-8")

        # Write a corrupted-but-grep-able marker pointing at g2.
        marker = gate_root / "gate-in-progress.json"
        marker.write_text(
            '{"gate_id": "g2", "commit_sha": "deadbeef", not valid JSON,,, }',
            encoding="utf-8",
        )

        result = recover_from_crash(self.tmp)
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"])
        self.assertIn("quarantine_dir", result)
        quar = Path(result["quarantine_dir"])

        # ONLY g2 should have been moved.
        self.assertTrue(
            (quar / "evidence" / "g2" / "g2.json").is_file(),
            "g2 (the named gate) must be quarantined",
        )
        self.assertFalse(
            (gate_root / "evidence" / "g2").exists(),
            "g2's live dir must be moved out",
        )
        # g1 and g3 must STILL be in evidence/ (Merkle reverification works).
        self.assertTrue((gate_root / "evidence" / "g1" / "g1.json").is_file(),
                        "g1 must NOT be touched")
        self.assertTrue((gate_root / "evidence" / "g3" / "g3.json").is_file(),
                        "g3 must NOT be touched")


class CorruptMarkerUnreadableQuarantinesOnlyMarker(_Mixin, unittest.TestCase):
    """A marker with no extractable gate_id quarantines only itself."""

    def test_corrupt_marker_unreadable_quarantines_only_marker(self) -> None:
        gate_root = self.tmp / "_bmad" / "gate"
        gate_root.mkdir(parents=True)
        for gid in ("g1", "g2"):
            d = gate_root / "evidence" / gid
            d.mkdir(parents=True)
            (d / f"{gid}.json").write_text(f'{{"gate": "{gid}"}}', encoding="utf-8")

        marker = gate_root / "gate-in-progress.json"
        # Pure garbage — no JSON fragment, no gate_id key anywhere.
        marker.write_text("######### corrupted blob #########", encoding="utf-8")

        result = recover_from_crash(self.tmp)
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"])
        quar = Path(result["quarantine_dir"])

        # Marker moved.
        self.assertTrue((quar / "gate-in-progress.json").is_file())
        self.assertFalse(marker.exists())
        # Evidence dir UNTOUCHED.
        self.assertTrue((gate_root / "evidence" / "g1" / "g1.json").is_file())
        self.assertTrue((gate_root / "evidence" / "g2" / "g2.json").is_file())


# ---------------------------------------------------------------------------
# L2 — empty/missing gate_id in valid-JSON marker (Round 1 fix #29)
# ---------------------------------------------------------------------------


class ValidJsonMarkerMissingGateIdPreservesHistoricalEvidence(
    _Mixin, unittest.TestCase
):
    """A valid-JSON marker missing ``gate_id`` MUST NOT wipe historical evidence.

    Previously the recover_from_crash path read ``marker.get("gate_id", "")``
    without validating non-empty / path-safe, then computed
    ``evidence_dir = evidence / gate_id``. Pathlib semantics: ``Path('.../evidence') / ''``
    is a no-op, so evidence_dir collapsed to the evidence ROOT containing every
    historical gate. ``os.rename`` then moved the entire historical tree into
    cleanup/ where it was rmtree'd — silently destroying every gate's bundle
    while returning ``recovered=True, gate_id=''``. Such a marker is
    structurally corrupted (the marker contract requires gate_id); recovery
    must route it through the corrupted-marker quarantine path per §9.2.
    """

    def test_empty_gate_id_marker_does_not_destroy_historical_evidence(
        self,
    ) -> None:
        gate_root = self.tmp / "_bmad" / "gate"
        gate_root.mkdir(parents=True)
        # Pre-seed two historical / completed gate evidence dirs.
        for gid in ("completed-A", "completed-B"):
            d = gate_root / "evidence" / gid
            d.mkdir(parents=True)
            (d / "audit.json").write_text(f'{{"gate": "{gid}"}}', encoding="utf-8")

        # Marker is VALID JSON (a dict) but missing the gate_id field.
        # read_gate_marker accepts this; the bug surfaces in
        # _recover_from_crash_locked when it dereferences gate_id="".
        marker = gate_root / "gate-in-progress.json"
        marker.write_text("{}", encoding="utf-8")

        result = recover_from_crash(self.tmp)

        # Audit-floor MarkerCorruptionInvariant contract must hold:
        # recovered=False, quarantined=True, quarantine_dir, corruption_reason.
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"], "missing gate_id must surface loud")
        self.assertIn("quarantine_dir", result)
        self.assertIn("corruption_reason", result)

        # The bug was: returns recovered=True/gate_id='' AND destroys evidence.
        # Both halves must be fixed.
        self.assertNotEqual(
            result.get("gate_id", "MISSING"),
            "",
            "must not silently return gate_id=''",
        )

        # Historical evidence dirs MUST survive (this is the core regression).
        for gid in ("completed-A", "completed-B"):
            self.assertTrue(
                (gate_root / "evidence" / gid / "audit.json").is_file(),
                f"{gid} historical evidence must be preserved",
            )

        # Marker moved into quarantine (per the corrupted-marker contract).
        quar = Path(result["quarantine_dir"])
        self.assertTrue((quar / "gate-in-progress.json").is_file())
        self.assertFalse(marker.exists())

    def test_foreign_marker_with_extra_fields_but_no_gate_id_is_quarantined(
        self,
    ) -> None:
        """Even a marker with unrelated valid-JSON content but no gate_id
        must not destroy evidence — the structural contract is gate_id."""
        gate_root = self.tmp / "_bmad" / "gate"
        gate_root.mkdir(parents=True)
        d = gate_root / "evidence" / "historical"
        d.mkdir(parents=True)
        (d / "x.json").write_text('{"ok": 1}', encoding="utf-8")

        marker = gate_root / "gate-in-progress.json"
        # Valid JSON object, but the gate_id key is absent.
        marker.write_text('{"foo": "bar", "baz": 42}', encoding="utf-8")

        result = recover_from_crash(self.tmp)
        self.assertFalse(result["recovered"])
        self.assertTrue(result["quarantined"])
        # Historical evidence preserved.
        self.assertTrue(
            (gate_root / "evidence" / "historical" / "x.json").is_file(),
            "historical evidence must survive a missing-gate_id marker",
        )


if __name__ == "__main__":
    unittest.main()
