"""B2 — Lock-holder observability tests.

Verifies that ``get_gate_lock`` timeouts surfaced by the three call sites
(``gate_orchestrator.recover_from_crash``,
``gate_orchestrator.run_production_gate``, ``system_gate.run_system_gate``)
raise a :class:`GateLockTimeoutError` carrying the holder PID +
``started_at`` instead of an opaque :class:`filelock.Timeout`.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from filelock import FileLock, Timeout

from story_automator.core.evidence_io import (
    gate_lock_path,
    write_gate_marker,
)
from story_automator.core.gate_lock_observability import (
    GateLockTimeoutError,
    _describe_lock_holder,
    _handle_gate_lock_timeout,
)
from story_automator.core.gate_orchestrator import recover_from_crash


class _Mixin:
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# B-H1 — exception is filelock.Timeout subclass, lock_file is the path
# ---------------------------------------------------------------------------


class LockTimeoutIncludesHolderTests(_Mixin, unittest.TestCase):
    """When the lock is held, a sibling caller sees holder identity."""

    def test_lock_timeout_includes_holder_pid_and_started_at(self) -> None:
        # Stamp a marker that names the (synthetic) holder. We use the
        # current PID so the marker is well-formed; the test does not
        # exercise liveness — only the observability path.
        write_gate_marker(self.tmp, "gate-1", "deadbeef")
        lock_path = gate_lock_path(self.tmp)

        # Hold the lock from a sibling thread and try to acquire from
        # the main thread with a tight timeout. FileLock is process-level
        # on POSIX; constructing a second instance from a sibling thread
        # models a sibling-process holder (filelock re-entrance applies
        # only to the same instance).
        ready = threading.Event()
        release = threading.Event()

        def _holder() -> None:
            with FileLock(str(lock_path), timeout=10.0):
                ready.set()
                release.wait(timeout=10.0)

        thread = threading.Thread(target=_holder, daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(timeout=5.0), "holder did not acquire")
            with self.assertRaises(Timeout) as cm:
                # recover_from_crash takes the gate lock with the
                # default 60.0s timeout; we patch that to a tight value
                # via the helper directly to keep the test fast.
                _handle_gate_lock_timeout(
                    self.tmp, lock_path, 0.1,
                    Timeout(str(lock_path)),
                )
        finally:
            release.set()
            thread.join(timeout=5.0)

        exc = cm.exception
        self.assertIsInstance(exc, GateLockTimeoutError)
        self.assertIsInstance(exc, Timeout)  # subclass inheritance
        # exc.lock_file MUST remain the lock path (gap B-H1 — never
        # the augmented prose).
        self.assertEqual(exc.lock_file, str(lock_path))
        self.assertEqual(exc.timeout_s, 0.1)
        self.assertIsNotNone(exc.holder)
        self.assertEqual(exc.holder["pid"], os.getpid())
        self.assertIn("started_at", exc.holder)
        rendered = str(exc)
        self.assertIn(f"PID={os.getpid()}", rendered)
        self.assertIn("started_at=", rendered)
        self.assertIn("host=", rendered)

    def test_lock_timeout_with_missing_marker_reports_holder_unknown(
        self,
    ) -> None:
        # No marker on disk — holder may have just released the lock.
        # Build the project root with the gate dir but no marker.
        (self.tmp / "_bmad" / "gate").mkdir(parents=True)
        lock_path = gate_lock_path(self.tmp)

        with self.assertRaises(GateLockTimeoutError) as cm:
            _handle_gate_lock_timeout(
                self.tmp, lock_path, 0.1, Timeout(str(lock_path)),
            )
        rendered = str(cm.exception)
        self.assertIn(
            "marker missing — holder may have just released the lock",
            rendered,
        )

    def test_describe_lock_holder_swallows_marker_corruption(self) -> None:
        # Write a corrupted marker (gap B-M6: corrupt vs missing distinction).
        gate_dir = self.tmp / "_bmad" / "gate"
        gate_dir.mkdir(parents=True)
        marker_path = gate_dir / "gate-in-progress.json"
        marker_path.write_bytes(b"not json{")

        holder = _describe_lock_holder(self.tmp)
        self.assertEqual(holder, {"_state": "corrupt"})

        # And via the full timeout path the message must say so.
        with self.assertRaises(GateLockTimeoutError) as cm:
            _handle_gate_lock_timeout(
                self.tmp, gate_lock_path(self.tmp), 0.1,
                Timeout(str(gate_lock_path(self.tmp))),
            )
        self.assertIn("marker present but unparseable", str(cm.exception))


# ---------------------------------------------------------------------------
# B-H2 — third call site at system_gate.run_system_gate
# ---------------------------------------------------------------------------


class RunSystemGateLockTimeoutTests(_Mixin, unittest.TestCase):
    """system_gate.run_system_gate's get_gate_lock call site must augment."""

    def test_run_system_gate_lock_timeout_includes_holder(self) -> None:
        from story_automator.core import system_gate as sg_mod

        # Stamp a marker that names a holder.
        write_gate_marker(self.tmp, "sys-gate-1", "feedbeef")
        lock_path = gate_lock_path(self.tmp)

        # Hold the lock from a sibling thread; then call run_system_gate
        # with a contrived short lock timeout. We monkey-patch the
        # 3600.0 timeout used in system_gate to a tight value via
        # mock.patch on get_gate_lock — pass the same call through but
        # with timeout=0.1.
        original_get_gate_lock = sg_mod.get_gate_lock

        def _short_lock(root, *args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["timeout"] = 0.1
            return original_get_gate_lock(root, **kwargs)

        ready = threading.Event()
        release = threading.Event()

        def _holder() -> None:
            with FileLock(str(lock_path), timeout=10.0):
                ready.set()
                release.wait(timeout=10.0)

        thread = threading.Thread(target=_holder, daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(timeout=5.0))
            with mock.patch.object(sg_mod, "get_gate_lock", _short_lock):
                with self.assertRaises(Timeout) as cm:
                    sg_mod.run_system_gate(
                        self.tmp, "sys-gate-1",
                        epic_id="epic-1",
                        commit_sha="feedbeef",
                        epic_metadata={},
                        profile={"id": "x", "version": 1},
                        factory_version="t",
                        registry=mock.MagicMock(),
                    )
        finally:
            release.set()
            thread.join(timeout=5.0)

        exc = cm.exception
        self.assertIsInstance(exc, GateLockTimeoutError)
        self.assertEqual(exc.holder["pid"], os.getpid())
        self.assertEqual(exc.timeout_s, 0.1)


# ---------------------------------------------------------------------------
# Recover-from-crash lock timeout path
# ---------------------------------------------------------------------------


class RecoverFromCrashLockTimeoutTests(_Mixin, unittest.TestCase):
    """The gate_orchestrator.recover_from_crash call site must also augment."""

    def test_recover_from_crash_lock_timeout_includes_holder(self) -> None:
        from story_automator.core import gate_orchestrator as go_mod

        write_gate_marker(self.tmp, "rec-1", "cafebabe")
        lock_path = gate_lock_path(self.tmp)

        original_get_gate_lock = go_mod.get_gate_lock

        def _short_lock(root, *args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs["timeout"] = 0.1
            return original_get_gate_lock(root, **kwargs)

        ready = threading.Event()
        release = threading.Event()

        def _holder() -> None:
            with FileLock(str(lock_path), timeout=10.0):
                ready.set()
                release.wait(timeout=10.0)

        thread = threading.Thread(target=_holder, daemon=True)
        thread.start()
        try:
            self.assertTrue(ready.wait(timeout=5.0))
            with mock.patch.object(go_mod, "get_gate_lock", _short_lock):
                with self.assertRaises(Timeout) as cm:
                    recover_from_crash(self.tmp)
        finally:
            release.set()
            thread.join(timeout=5.0)

        exc = cm.exception
        self.assertIsInstance(exc, GateLockTimeoutError)
        self.assertEqual(exc.holder["pid"], os.getpid())


# ---------------------------------------------------------------------------
# Round-trip regression — pickle / copy / deepcopy must preserve holder + timeout
# ---------------------------------------------------------------------------


class GateLockTimeoutErrorRoundTripTests(unittest.TestCase):
    """``GateLockTimeoutError`` must survive pickle / copy / deepcopy.

    The inherited ``filelock.Timeout.__reduce__`` returns
    ``(self.__class__, (self._lock_file,))`` — i.e. only the positional
    ``lock_file``. Because the subclass ``__init__`` adds ``holder`` and
    ``timeout`` as REQUIRED keyword-only arguments, the inherited reduction
    is incompatible: ``pickle.loads`` / ``copy.copy`` / ``copy.deepcopy``
    would all raise ``TypeError: missing 2 required keyword-only
    arguments: 'holder' and 'timeout'``. This regression test pins the
    ``__reduce__`` override that makes the subclass picklable/copyable
    while preserving holder + timeout context.
    """

    def _assert_round_trip_preserves_state(
        self,
        original: GateLockTimeoutError,
        revived: GateLockTimeoutError,
    ) -> None:
        self.assertIsInstance(revived, GateLockTimeoutError)
        self.assertIsInstance(revived, Timeout)  # subclass inheritance
        self.assertEqual(revived.lock_file, original.lock_file)
        self.assertEqual(revived.holder, original.holder)
        self.assertEqual(revived.timeout_s, original.timeout_s)
        # ``__str__`` is computed from the three public attributes, so a
        # successful round-trip must produce the same rendered message.
        self.assertEqual(str(revived), str(original))

    def test_pickle_round_trip_with_well_formed_holder(self) -> None:
        import pickle

        exc = GateLockTimeoutError(
            "/tmp/foo.lock",
            holder={
                "pid": 1234,
                "started_at": "2026-06-24T00:00:00Z",
                "hostname": "host1",
            },
            timeout=30.0,
        )
        revived = pickle.loads(pickle.dumps(exc))
        self._assert_round_trip_preserves_state(exc, revived)

    def test_copy_copy_round_trip_with_well_formed_holder(self) -> None:
        import copy

        exc = GateLockTimeoutError(
            "/tmp/bar.lock",
            holder={
                "pid": 9999,
                "started_at": "2026-06-24T01:02:03Z",
                "hostname": "h2",
            },
            timeout=60.0,
        )
        revived = copy.copy(exc)
        self._assert_round_trip_preserves_state(exc, revived)

    def test_copy_deepcopy_round_trip_with_well_formed_holder(self) -> None:
        import copy

        exc = GateLockTimeoutError(
            "/tmp/baz.lock",
            holder={
                "pid": 7777,
                "started_at": "2026-06-24T02:03:04Z",
                "hostname": "h3",
            },
            timeout=120.0,
        )
        revived = copy.deepcopy(exc)
        self._assert_round_trip_preserves_state(exc, revived)
        # deepcopy must produce an independent ``holder`` dict.
        self.assertIsNot(revived.holder, exc.holder)

    def test_pickle_round_trip_with_none_holder(self) -> None:
        import pickle

        exc = GateLockTimeoutError(
            "/tmp/none.lock", holder=None, timeout=0.5,
        )
        revived = pickle.loads(pickle.dumps(exc))
        self._assert_round_trip_preserves_state(exc, revived)
        self.assertIsNone(revived.holder)

    def test_pickle_round_trip_with_state_sentinel_holder(self) -> None:
        import pickle

        for state in ("missing", "corrupt"):
            with self.subTest(state=state):
                exc = GateLockTimeoutError(
                    "/tmp/sentinel.lock",
                    holder={"_state": state},
                    timeout=1.5,
                )
                revived = pickle.loads(pickle.dumps(exc))
                self._assert_round_trip_preserves_state(exc, revived)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
