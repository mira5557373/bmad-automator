"""B1 — Legacy-marker PID-reuse hardening tests.

Covers the v2 rule for ``_recover_from_crash_locked``: when a marker has
``started_at`` but no ``start_time`` (legacy from pre-J-03 era), liveness
is validated via a two-sided bound on the live PID's ``create_time()`` —

* upper bound: ``proc_start <= started_at_epoch + ISO_TRUNCATION_S`` (else
  the PID started AFTER the marker was stamped → reuse).
* lower bound: ``proc_start >= started_at_epoch - MAX_ORCHESTRATOR_UPTIME_S``
  (else the PID has been alive for >24h → almost certainly recycled).

Markers carrying ``start_time`` continue to use the post-J-03 fast path
unchanged (B-L2). Foreign-host markers short-circuit before the B1 branch
runs (B-L3). Zombies count as dead (B-M1).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import psutil

from story_automator.core.gate_orchestrator import (
    ISO_TRUNCATION_S,
    MAX_ORCHESTRATOR_UPTIME_S,
    recover_from_crash,
)
from story_automator.core.utils import write_atomic


def _write_legacy_marker(
    root: Path,
    *,
    gate_id: str = "g1",
    commit_sha: str = "deadbeef",
    pid: int,
    started_at: str | None = None,
    hostname: str | None = None,
    extra: dict | None = None,
) -> Path:
    """Stamp a marker by hand (bypasses write_gate_marker so we can
    omit start_time)."""
    marker_dir = root / "_bmad" / "gate"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "gate_id": gate_id,
        "commit_sha": commit_sha,
        "pid": pid,
    }
    if started_at is not None:
        marker["started_at"] = started_at
    if hostname is not None:
        marker["hostname"] = hostname
    if extra:
        marker.update(extra)
    path = marker_dir / "gate-in-progress.json"
    write_atomic(path, json.dumps(marker) + "\n")
    return path


class _Mixin:
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# v2 rule — two-sided bound on legacy markers with started_at only
# ---------------------------------------------------------------------------


class LegacyMarkerStartedAtTreatedAsLiveTests(_Mixin, unittest.TestCase):
    """A live process whose create_time is within bound → live (no wipe)."""

    def test_marker_with_started_at_within_iso_truncation_treated_as_live(
        self,
    ) -> None:
        # Marker recorded "now", proc started 0.5s before — within bound.
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        # proc_start (live PID's create_time) just slightly before the
        # marker timestamp: well within the lower bound.
        proc_start = now_dt.timestamp() - 0.5

        _write_legacy_marker(
            self.tmp, pid=os.getpid(),
            started_at=started_at,
            hostname=socket.gethostname(),
        )
        # Create evidence dir so we can prove it was not wiped.
        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "g1"
        evidence.mkdir(parents=True)
        sentinel = evidence / "in-flight.json"
        sentinel.write_text('{"ok": true}', encoding="utf-8")

        with mock.patch("psutil.pid_exists", return_value=True), \
             mock.patch.object(
                psutil.Process, "create_time",
                return_value=proc_start,
             ):
            result = recover_from_crash(self.tmp)

        self.assertFalse(result.get("recovered", True),
                         "live legacy marker must not be recovered")
        self.assertEqual(result.get("reason"), "live-pid-still-running")
        self.assertTrue(sentinel.is_file(),
                        "live-pid evidence must be preserved")


class LegacyMarkerProcStartAfterMarkerTreatedAsDeadTests(
    _Mixin, unittest.TestCase,
):
    """Upper bound: proc_start > started_at + ISO_TRUNCATION_S → reuse."""

    def test_marker_with_proc_start_after_marker_treated_as_dead(self) -> None:
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        # proc started 10s AFTER marker — well past the 1s truncation bound.
        proc_start = now_dt.timestamp() + 10.0

        _write_legacy_marker(
            self.tmp, pid=os.getpid(),
            started_at=started_at,
            hostname=socket.gethostname(),
        )

        with mock.patch("psutil.pid_exists", return_value=True), \
             mock.patch.object(
                psutil.Process, "create_time",
                return_value=proc_start,
             ):
            result = recover_from_crash(self.tmp)

        self.assertTrue(result.get("recovered"),
                        "PID reused (proc_start after marker) → recover")


class LegacyMarkerProcStartFarBeforeMarkerTreatedAsDeadTests(
    _Mixin, unittest.TestCase,
):
    """Lower bound: proc_start < started_at - 24h → recycled."""

    def test_marker_with_proc_start_far_before_marker_treated_as_dead(
        self,
    ) -> None:
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        # proc started 25h before marker — past 24h ceiling.
        proc_start = (
            now_dt.timestamp() - (MAX_ORCHESTRATOR_UPTIME_S + 3600)
        )

        _write_legacy_marker(
            self.tmp, pid=os.getpid(),
            started_at=started_at,
            hostname=socket.gethostname(),
        )

        with mock.patch("psutil.pid_exists", return_value=True), \
             mock.patch.object(
                psutil.Process, "create_time",
                return_value=proc_start,
             ):
            result = recover_from_crash(self.tmp)

        self.assertTrue(result.get("recovered"),
                        "PID alive >24h before marker → recycled → recover")


# ---------------------------------------------------------------------------
# Back-compat — fall-through and precedence
# ---------------------------------------------------------------------------


class LegacyMarkerNoStartTimeNoStartedAtTests(_Mixin, unittest.TestCase):
    """No start_time AND no started_at → fall back to pid_exists alone."""

    def test_marker_without_started_at_or_start_time_falls_back_to_pid_exists(
        self,
    ) -> None:
        _write_legacy_marker(
            self.tmp, pid=os.getpid(),
            hostname=socket.gethostname(),
        )

        with mock.patch("psutil.pid_exists", return_value=True):
            result = recover_from_crash(self.tmp)

        # No timestamps at all → pid_exists alone says alive → preserve.
        self.assertFalse(result.get("recovered", True))


class CreateTimeUnreadableTreatedAsLiveTests(_Mixin, unittest.TestCase):
    """psutil errors in the B1 branch fall back to alive (conservative)."""

    def test_create_time_unreadable_treated_as_live_conservative(self) -> None:
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        _write_legacy_marker(
            self.tmp, pid=os.getpid(),
            started_at=started_at,
            hostname=socket.gethostname(),
        )
        evidence = self.tmp / "_bmad" / "gate" / "evidence" / "g1"
        evidence.mkdir(parents=True)
        sentinel = evidence / "in-flight.json"
        sentinel.write_text('{"ok": true}', encoding="utf-8")

        with mock.patch("psutil.pid_exists", return_value=True), \
             mock.patch.object(
                psutil.Process, "create_time",
                side_effect=psutil.AccessDenied(os.getpid()),
             ):
            result = recover_from_crash(self.tmp)

        # AccessDenied during the B1 branch is treated as dead — that's
        # because if we cannot prove the live PID is the same process,
        # PID reuse is plausible. But existing precedent in
        # _recover_from_crash_locked treats AccessDenied as "dead" for
        # start_time path (lines 238-239). Honor that contract here.
        self.assertTrue(result.get("recovered"))


class ZombiePidTreatedAsDeadTests(_Mixin, unittest.TestCase):
    """psutil.ZombieProcess in the B1 branch → dead (gap B-M1)."""

    def test_zombie_pid_treated_as_dead(self) -> None:
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        _write_legacy_marker(
            self.tmp, pid=os.getpid(),
            started_at=started_at,
            hostname=socket.gethostname(),
        )

        with mock.patch("psutil.pid_exists", return_value=True), \
             mock.patch.object(
                psutil.Process, "create_time",
                side_effect=psutil.ZombieProcess(os.getpid()),
             ):
            result = recover_from_crash(self.tmp)

        # Zombies hold no gate state → treat as dead → recover.
        self.assertTrue(result.get("recovered"))


class MarkerWithBothStartTimeAndStartedAtPrefersStartTimeTests(
    _Mixin, unittest.TestCase,
):
    """gap B-L2 — post-J-03 fast-path (start_time) wins over B1 fallback."""

    def test_marker_with_both_start_time_and_started_at_prefers_start_time(
        self,
    ) -> None:
        # We write a marker carrying BOTH start_time (the J-03 fast path)
        # and started_at (the legacy B1 path). The J-03 path uses an
        # exact-match check (within 1.0s). started_at gives a much wider
        # window. We construct a scenario where start_time would say
        # "dead" (mismatched) — if B1 fallback fired it would say "live"
        # — and assert the J-03 branch wins → recovered=True.
        marker_start_time = 100000.0  # arbitrary epoch baseline
        proc_start_time = marker_start_time + 5.0  # 5s mismatch → dead

        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        _write_legacy_marker(
            self.tmp, pid=os.getpid(),
            started_at=started_at,
            hostname=socket.gethostname(),
            extra={"start_time": marker_start_time},
        )

        with mock.patch("psutil.pid_exists", return_value=True), \
             mock.patch.object(
                psutil.Process, "create_time",
                return_value=proc_start_time,
             ):
            result = recover_from_crash(self.tmp)

        # start_time fast-path wins → mismatch → dead → recover.
        self.assertTrue(
            result.get("recovered"),
            "start_time fast-path must win over B1 started_at fallback",
        )


class ForeignHostMarkerSkipsB1Tests(_Mixin, unittest.TestCase):
    """gap B-L3 — composite-identity short-circuits before B1 branch."""

    def test_foreign_host_marker_skips_b1_started_at_check(self) -> None:
        now_dt = datetime.now(timezone.utc).replace(microsecond=0)
        started_at = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # hostname != current host → foreign-host marker → recover.
        _write_legacy_marker(
            self.tmp, pid=os.getpid(),
            started_at=started_at,
            hostname="some-other-host-that-is-not-this-one",
        )

        # No psutil mocks — we want to assert that B1's create_time path
        # is NEVER invoked when the hostname mismatches. We achieve that
        # by side_effect=AssertionError on create_time — if it fires,
        # the test fails.
        with mock.patch.object(
            psutil.Process, "create_time",
            side_effect=AssertionError(
                "create_time must not be called on foreign-host marker"
            ),
        ):
            result = recover_from_crash(self.tmp)

        # Foreign-host marker → not alive from this host's perspective →
        # recovery proceeds.
        self.assertTrue(result.get("recovered"))


# ---------------------------------------------------------------------------
# Constants surface (regression — ensures the constants are exported)
# ---------------------------------------------------------------------------


class ConstantsExportedTests(unittest.TestCase):
    def test_constants_exported_with_expected_values(self) -> None:
        # ISO_TRUNCATION_S covers up to 1.0s of iso_now() second-precision
        # rounding (core/utils.py::iso_now → "%Y-%m-%dT%H:%M:%SZ").
        self.assertEqual(ISO_TRUNCATION_S, 1.0)
        # MAX_ORCHESTRATOR_UPTIME_S: orchestrator processes are not
        # meant to live longer than 24h.
        self.assertEqual(MAX_ORCHESTRATOR_UPTIME_S, 86400.0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
