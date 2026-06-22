"""Bug R2 / J-03 — PID-recycle false positive in gate-marker liveness check.

L1's liveness check used ONLY ``psutil.pid_exists(pid)``. On long-running
hosts PIDs are aggressively recycled by the kernel — an unrelated process
inheriting the recorded PID would falsely mark the gate as "live" and
wedge the L1 lock permanently (recover_from_crash refuses, no one else
ever owns the lock). A foreign-host marker (NFS-shared project root)
would do the same: the recorded PID either does not exist locally
(legitimately recoverable) or coincidentally collides with a local
unrelated process (false-positive wedge).

Fix:
- ``write_gate_marker`` records additive ``start_time`` (from
  ``psutil.Process().create_time()``) and ``hostname`` (``socket.gethostname()``).
- ``_recover_from_crash_locked`` only treats a PID as alive when:
    * ``psutil.pid_exists(pid)`` AND
    * the recorded ``hostname`` matches the local hostname AND
    * the recorded ``start_time`` matches ``psutil.Process(pid).create_time()``
      within a 1.0s tolerance.
- Foreign-host markers and recycled-PID markers are treated as DEAD —
  recovery proceeds.
- Legacy markers (no ``start_time`` / no ``hostname``) keep their L1
  behavior (pid_exists alone) — backward compatible.
"""
from __future__ import annotations

import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path

import psutil

from story_automator.core.evidence_io import (
    read_gate_marker,
    write_gate_marker,
)
from story_automator.core.gate_orchestrator import recover_from_crash
from story_automator.core.utils import iso_now


class _Mixin:
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# write_gate_marker records the composite-identity fields.
# ---------------------------------------------------------------------------


class WriteMarkerStampsCompositeIdentity(_Mixin, unittest.TestCase):
    """write_gate_marker must record start_time + hostname additively."""

    def test_marker_includes_start_time_and_hostname(self) -> None:
        write_gate_marker(self.tmp, "g-x", "deadbeef")
        marker = read_gate_marker(self.tmp)
        self.assertIsNotNone(marker)
        assert marker is not None  # for type checker
        # Existing fields — must NOT regress.
        self.assertEqual(marker["gate_id"], "g-x")
        self.assertEqual(marker["commit_sha"], "deadbeef")
        self.assertIn("started_at", marker)
        self.assertIn("pid", marker)
        # New fields — composite-identity for PID-recycle safety.
        self.assertIn("start_time", marker)
        self.assertIsInstance(marker["start_time"], (int, float))
        self.assertIn("hostname", marker)
        self.assertEqual(marker["hostname"], socket.gethostname())
        # The recorded start_time matches this process's create_time
        # (1s tolerance bridges time.time/create_time resolution).
        my_start = psutil.Process().create_time()
        self.assertAlmostEqual(marker["start_time"], my_start, delta=1.0)


# ---------------------------------------------------------------------------
# Recycled-PID marker is treated as DEAD.
# ---------------------------------------------------------------------------


class RecycledPidMarkerRecovered(_Mixin, unittest.TestCase):
    """A marker whose PID exists but with a different start_time is recoverable.

    Reproduces J-03 directly: pid_exists is True (someone else owns it now),
    but the recorded start_time does not match the current process's
    create_time → original owner is gone, PID was recycled, marker is dead.
    """

    def test_recycled_pid_marker_is_recoverable(self) -> None:
        marker_path = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker_path.parent.mkdir(parents=True)
        # Use *our* PID so psutil.pid_exists(pid) returns True (the recycle
        # scenario). But record a start_time from the deep past — no real
        # process on this box was started in 1980. That guarantees the
        # composite check ("same process?") returns False → DEAD → recover.
        payload = {
            "gate_id": "recycled-gate",
            "commit_sha": "deadbeef",
            "started_at": iso_now(),
            "pid": psutil.Process().pid,
            # Jan 1, 1980 — guaranteed older than any live process.
            "start_time": 315532800.0,
            "hostname": socket.gethostname(),
        }
        marker_path.write_text(json.dumps(payload), encoding="utf-8")

        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "recycled-gate"
        evidence.mkdir(parents=True)
        (evidence / "orphan.json").write_text("{}", encoding="utf-8")

        result = recover_from_crash(self.tmp)
        # Without the fix: pid_exists is True → "live-pid-still-running" → wedged.
        # With the fix: start_time mismatch → DEAD → recover.
        self.assertTrue(
            result["recovered"],
            f"recycled-PID marker should be recoverable, got {result!r}",
        )
        self.assertEqual(result["gate_id"], "recycled-gate")
        self.assertFalse(marker_path.exists())
        self.assertFalse(evidence.exists())


# ---------------------------------------------------------------------------
# Foreign-host marker is treated as DEAD.
# ---------------------------------------------------------------------------


class ForeignHostMarkerRecovered(_Mixin, unittest.TestCase):
    """A marker from a different hostname is dead from this host's perspective.

    Even if pid_exists(pid) on this box happens to be True, that's a totally
    unrelated process — the original owner lives on another machine. Without
    the hostname check, an NFS-shared project root would permanently wedge.
    """

    def test_foreign_host_marker_is_recoverable(self) -> None:
        marker_path = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker_path.parent.mkdir(parents=True)
        # Use our PID so pid_exists is True. The hostname is what flags it
        # as foreign; the recorded start_time is irrelevant for this case.
        payload = {
            "gate_id": "foreign-gate",
            "commit_sha": "deadbeef",
            "started_at": iso_now(),
            "pid": psutil.Process().pid,
            "start_time": psutil.Process().create_time(),
            # Pretend the marker was written from a different box.
            "hostname": "some-other-host-not-this-one",
        }
        marker_path.write_text(json.dumps(payload), encoding="utf-8")

        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "foreign-gate"
        evidence.mkdir(parents=True)
        (evidence / "orphan.json").write_text("{}", encoding="utf-8")

        result = recover_from_crash(self.tmp)
        self.assertTrue(
            result["recovered"],
            f"foreign-host marker should be recoverable, got {result!r}",
        )
        self.assertEqual(result["gate_id"], "foreign-gate")
        self.assertFalse(marker_path.exists())
        self.assertFalse(evidence.exists())


# ---------------------------------------------------------------------------
# Genuinely-live marker (same host, matching start_time) is still NOT recovered.
# ---------------------------------------------------------------------------


class LiveLocalMarkerNotRecovered(_Mixin, unittest.TestCase):
    """The L1 protection is preserved: a genuinely-live local gate is untouched."""

    def test_live_local_marker_still_protected(self) -> None:
        # write_gate_marker stamps our PID + our create_time + our hostname.
        # recover_from_crash must STILL refuse to recover.
        write_gate_marker(self.tmp, "live-gate", "deadbeef")
        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "live-gate"
        evidence.mkdir(parents=True)
        (evidence / "in-flight.json").write_text('{"ok": true}', encoding="utf-8")

        result = recover_from_crash(self.tmp)
        self.assertFalse(result.get("recovered", True))
        self.assertEqual(result.get("reason"), "live-pid-still-running")
        # L1 invariant: live evidence preserved.
        self.assertTrue((evidence / "in-flight.json").is_file())


# ---------------------------------------------------------------------------
# Legacy marker (no start_time / no hostname) is forward-compatible.
# ---------------------------------------------------------------------------


class LegacyMarkerNoStartTimeStillUsesPidCheck(_Mixin, unittest.TestCase):
    """Markers from prior versions that have ``pid`` but no ``start_time`` /
    ``hostname`` keep the L1 behavior — pid_exists alone is authoritative.
    Otherwise an in-place upgrade across a running gate would break L1.
    """

    def test_legacy_marker_dead_pid_recovers(self) -> None:
        marker_path = self.tmp / "_bmad" / "gate" / "gate-in-progress.json"
        marker_path.parent.mkdir(parents=True)
        payload = {
            "gate_id": "legacy-gate",
            "commit_sha": "deadbeef",
            "started_at": iso_now(),
            # Older marker: pid only, no start_time, no hostname.
            "pid": 999999,
        }
        marker_path.write_text(json.dumps(payload), encoding="utf-8")
        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "legacy-gate"
        evidence.mkdir(parents=True)
        (evidence / "orphan.json").write_text("{}", encoding="utf-8")
        result = recover_from_crash(self.tmp)
        # Dead pid → recover (per L1).
        self.assertTrue(result["recovered"])
        self.assertEqual(result["gate_id"], "legacy-gate")
        self.assertFalse(evidence.exists())


if __name__ == "__main__":
    unittest.main()
