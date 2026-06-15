from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import atomic_io  # noqa: F401

    def test_exposes_atomic_write_retry_exhausted(self) -> None:
        from story_automator.core.atomic_io import AtomicWriteRetryExhausted

        # Subclass PermissionError so REQ-04 ("raise the final PermissionError
        # if all retries fail") is satisfied while still being a typed
        # exception per the observability NFR. PermissionError is itself
        # a subclass of OSError.
        self.assertTrue(issubclass(AtomicWriteRetryExhausted, PermissionError))
        self.assertTrue(issubclass(AtomicWriteRetryExhausted, OSError))

    def test_exposes_write_atomic_text(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        self.assertTrue(callable(write_atomic_text))


class HappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_writes_full_contents_to_target(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        write_atomic_text(target, "hello world")

        self.assertEqual(target.read_text(encoding="utf-8"), "hello world")

    def test_overwrites_existing_file(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        target.write_text("old", encoding="utf-8")
        write_atomic_text(target, "new")

        self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_writes_unicode_content(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "uni.txt"
        write_atomic_text(target, "héllo — 世界")

        self.assertEqual(target.read_text(encoding="utf-8"), "héllo — 世界")

    def test_no_leftover_tmp_files_in_directory(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        write_atomic_text(target, "payload")

        entries = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(entries, ["out.txt"])

    def test_tmp_file_lives_in_same_directory_as_target(self) -> None:
        # Same-directory siblings are required for os.replace atomicity
        # across filesystems. We assert the implementation hasn't drifted
        # to tempfile.gettempdir() by inspecting an interrupted write.
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        observed_dirs: list[Path] = []
        real_replace = os.replace

        def spy(src: str, dst: str) -> None:
            observed_dirs.append(Path(src).parent.resolve())
            real_replace(src, dst)

        with patch("story_automator.core.atomic_io.os.replace", side_effect=spy):
            write_atomic_text(target, "payload")

        self.assertEqual(observed_dirs, [self.dir.resolve()])


class WindowsRetryTests(unittest.TestCase):
    """Simulated retry logic — must pass on POSIX too via mocking."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_retries_replace_on_permission_error_until_success(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        real_replace = os.replace
        call_log: list[float] = []
        attempts = {"n": 0}

        def flaky(src: str, dst: str) -> None:
            attempts["n"] += 1
            call_log.append(time.monotonic())
            if attempts["n"] < 3:
                raise PermissionError("simulated sharing violation")
            real_replace(src, dst)

        sleep_log: list[float] = []

        def fake_sleep(d: float) -> None:
            sleep_log.append(d)

        with (
            patch("story_automator.core.atomic_io._is_windows", return_value=True),
            patch("story_automator.core.atomic_io.os.replace", side_effect=flaky),
            patch("story_automator.core.atomic_io.time.sleep", side_effect=fake_sleep),
        ):
            write_atomic_text(target, "payload")

        self.assertEqual(attempts["n"], 3)
        # Two backoff sleeps happened before the third (successful) attempt.
        self.assertEqual(sleep_log, [0.050, 0.100])
        self.assertEqual(target.read_text(encoding="utf-8"), "payload")

    def test_raises_atomic_write_retry_exhausted_after_five_failures(self) -> None:
        from story_automator.core.atomic_io import (
            AtomicWriteRetryExhausted,
            write_atomic_text,
        )

        target = self.dir / "out.txt"
        sleep_log: list[float] = []

        def always_fails(src: str, dst: str) -> None:
            raise PermissionError("simulated sharing violation")

        with (
            patch("story_automator.core.atomic_io._is_windows", return_value=True),
            patch(
                "story_automator.core.atomic_io.os.replace", side_effect=always_fails
            ),
            patch(
                "story_automator.core.atomic_io.time.sleep",
                side_effect=lambda d: sleep_log.append(d),
            ),
        ):
            with self.assertRaises(AtomicWriteRetryExhausted) as ctx:
                write_atomic_text(target, "payload")

        # Interpretation: 1 initial attempt + 5 retries = 6 total attempts.
        # Each retry is preceded by the corresponding backoff sleep, so 5
        # retries means exactly 5 sleeps (50/100/200/400/800 ms). The spec
        # REQ-04 wording "retry up to 5 times with exponential backoff
        # 50/100/200/400/800 ms" pairs each backoff value with one retry.
        self.assertEqual(sleep_log, [0.050, 0.100, 0.200, 0.400, 0.800])
        self.assertIsInstance(ctx.exception.__cause__, PermissionError)
        # Temp file must have been cleaned up.
        leftovers = list(self.dir.iterdir())
        self.assertEqual(leftovers, [])

    def test_posix_calls_replace_exactly_once_on_failure(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        attempts = {"n": 0}

        def fails(src: str, dst: str) -> None:
            attempts["n"] += 1
            raise PermissionError("posix should not retry")

        with (
            patch("story_automator.core.atomic_io._is_windows", return_value=False),
            patch("story_automator.core.atomic_io.os.replace", side_effect=fails),
        ):
            with self.assertRaises(PermissionError):
                write_atomic_text(target, "payload")

        self.assertEqual(attempts["n"], 1)

    def test_posix_non_permission_error_is_not_swallowed(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"

        def fails(src: str, dst: str) -> None:
            raise OSError("disk full")

        with (
            patch("story_automator.core.atomic_io._is_windows", return_value=False),
            patch("story_automator.core.atomic_io.os.replace", side_effect=fails),
        ):
            with self.assertRaises(OSError):
                write_atomic_text(target, "payload")

    def test_windows_non_permission_oserror_does_not_retry(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        sleep_log: list[float] = []
        attempts = {"n": 0}

        def fails(src: str, dst: str) -> None:
            attempts["n"] += 1
            raise OSError("not a sharing violation")

        with (
            patch("story_automator.core.atomic_io._is_windows", return_value=True),
            patch("story_automator.core.atomic_io.os.replace", side_effect=fails),
            patch(
                "story_automator.core.atomic_io.time.sleep",
                side_effect=lambda d: sleep_log.append(d),
            ),
        ):
            with self.assertRaises(OSError):
                write_atomic_text(target, "payload")

        self.assertEqual(attempts["n"], 1)
        self.assertEqual(sleep_log, [])


class PerPathLockSerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_two_threads_on_same_path_observe_only_complete_writes(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "shared.txt"
        # Two payloads of equal length; only one of these two exact strings
        # may appear in the file at any sampling point.
        a = "A" * 4096
        b = "B" * 4096
        valid = {a, b}

        # Pre-create so readers don't race on FileNotFoundError.
        write_atomic_text(target, a)

        stop = threading.Event()
        errors: list[BaseException] = []

        def writer(payload: str) -> None:
            try:
                for _ in range(50):
                    if stop.is_set():
                        return
                    write_atomic_text(target, payload)
            except BaseException as err:
                errors.append(err)

        ta = threading.Thread(target=writer, args=(a,))
        tb = threading.Thread(target=writer, args=(b,))
        ta.start()
        tb.start()

        observed: set[str] = set()
        for _ in range(200):
            try:
                observed.add(target.read_text(encoding="utf-8"))
            except FileNotFoundError:
                # If this fires we've violated atomicity — readers must see
                # either the prior contents or the new contents, never absence.
                stop.set()
                ta.join()
                tb.join()
                self.fail("reader observed FileNotFoundError mid-write")
            except PermissionError:
                # Windows-only: during os.replace, the target is briefly
                # inaccessible to concurrent readers (ERROR_SHARING_VIOLATION).
                # The writer-side per-path lock cannot prevent this OS-level
                # transient — it serializes writers, not OS replace windows.
                # Atomicity is still preserved (no absence, no partial
                # content); we just retry on the next iteration. On POSIX
                # rename(2) is genuinely atomic to readers, so a
                # PermissionError there indicates a real bug — re-raise.
                if sys.platform != "win32":
                    raise

        ta.join()
        tb.join()

        self.assertEqual(errors, [])
        # Guard against vacuous pass: if every read hit PermissionError we'd
        # silently report green. At least one successful read is required to
        # exercise the atomicity assertion below.
        self.assertGreater(
            len(observed), 0, "no reads succeeded — test would be vacuous"
        )
        self.assertTrue(
            observed.issubset(valid),
            f"observed non-atomic content: {observed - valid!r}",
        )

    def test_lock_registry_keyed_by_resolved_path(self) -> None:
        from story_automator.core.atomic_io import _lock_for_path

        a = self.dir / "out.txt"
        # Symlink-free alternative spelling of the same resolved path:
        b = self.dir / "." / "out.txt"

        self.assertIs(_lock_for_path(a), _lock_for_path(b))

    def test_lock_registry_distinguishes_different_paths(self) -> None:
        from story_automator.core.atomic_io import _lock_for_path

        a = self.dir / "a.txt"
        b = self.dir / "b.txt"

        self.assertIsNot(_lock_for_path(a), _lock_for_path(b))

    def test_lock_registry_concurrent_first_access_returns_same_lock(self) -> None:
        # If the registry isn't guarded, two threads racing on the first
        # access to the same path could each install their own Lock,
        # silently breaking serialization. This test exercises that race.
        from story_automator.core.atomic_io import (
            _lock_for_path,
            _reset_registry_for_tests,
        )

        _reset_registry_for_tests()
        target = self.dir / "race.txt"
        results: list = []
        barrier = threading.Barrier(8)

        def grab() -> None:
            barrier.wait()
            results.append(_lock_for_path(target))

        threads = [threading.Thread(target=grab) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(results), 8)
        self.assertTrue(all(r is results[0] for r in results))


class CrashSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_failure_during_replace_preserves_original_target(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        target.write_text("ORIGINAL", encoding="utf-8")

        def boom(src: str, dst: str) -> None:
            raise OSError("simulated crash between fsync and replace")

        with (
            patch("story_automator.core.atomic_io._is_windows", return_value=False),
            patch("story_automator.core.atomic_io.os.replace", side_effect=boom),
        ):
            with self.assertRaises(OSError):
                write_atomic_text(target, "NEW")

        self.assertEqual(target.read_text(encoding="utf-8"), "ORIGINAL")
        # No orphan tmp file left behind.
        siblings = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(siblings, ["out.txt"])

    def test_failure_during_write_preserves_missing_target(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"
        # Inject failure into fsync (after the fd is open and writable).
        with patch(
            "story_automator.core.atomic_io.os.fsync",
            side_effect=OSError("fsync failed"),
        ):
            with self.assertRaises(OSError):
                write_atomic_text(target, "NEW")

        self.assertFalse(target.exists())
        siblings = list(self.dir.iterdir())
        self.assertEqual(siblings, [])


class RunLockBusyExceptionTests(unittest.TestCase):
    def test_run_lock_busy_is_exported(self) -> None:
        from story_automator.core.atomic_io import RunLockBusy

        self.assertTrue(issubclass(RunLockBusy, Exception))

    def test_run_lock_busy_is_distinct_from_permission_error(self) -> None:
        # REQ-04 vs REQ-06: a Windows replace timeout is AtomicWriteRetryExhausted
        # (a PermissionError); a run-lock acquisition timeout is RunLockBusy.
        # They must NOT collapse onto each other so M02 telemetry wiring can
        # classify them by type without string-matching (observability NFR).
        from story_automator.core.atomic_io import (
            AtomicWriteRetryExhausted,
            RunLockBusy,
        )

        self.assertFalse(issubclass(RunLockBusy, PermissionError))
        self.assertFalse(issubclass(AtomicWriteRetryExhausted, RunLockBusy))
        self.assertFalse(issubclass(RunLockBusy, AtomicWriteRetryExhausted))

    def test_run_lock_busy_accepts_message(self) -> None:
        from story_automator.core.atomic_io import RunLockBusy

        err = RunLockBusy("lock /tmp/x.lock held by pid 42")
        self.assertIn("pid 42", str(err))


class RunLockIdentityTests(unittest.TestCase):
    def _sample(self):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import RunLockIdentity

        return RunLockIdentity(
            pid=4242,
            start_time=1717000000.5,
            hostname="builder-01",
            heartbeat_iso="2026-06-14T12:34:56Z",
            run_id="run-abc-123",
        )

    def test_dataclass_requires_keyword_only_construction(self) -> None:
        # REQ-05 specifies @dataclass(kw_only=True). Positional construction
        # must raise TypeError so a future field reordering cannot silently
        # rebind callers passing positional args.
        from story_automator.core.atomic_io import RunLockIdentity

        with self.assertRaises(TypeError):
            RunLockIdentity(  # type: ignore[misc]
                4242,
                1717000000.5,
                "builder-01",
                "2026-06-14T12:34:56Z",
                "run-abc-123",
            )

    def test_to_json_is_compact(self) -> None:
        identity = self._sample()
        payload = identity.to_json()
        # compact_json uses (",", ":") separators — no whitespace between
        # tokens. Our sample values contain no spaces, so the WHOLE payload
        # must be whitespace-free.
        self.assertNotIn(" ", payload)
        self.assertNotIn("\n", payload)
        self.assertNotIn("\t", payload)

    def test_to_json_round_trips_via_json_loads(self) -> None:
        identity = self._sample()
        parsed = json.loads(identity.to_json())
        self.assertEqual(
            parsed,
            {
                "pid": 4242,
                "start_time": 1717000000.5,
                "hostname": "builder-01",
                "heartbeat_iso": "2026-06-14T12:34:56Z",
                "run_id": "run-abc-123",
            },
        )

    def test_to_json_key_order_is_stable(self) -> None:
        # Two constructions in different field orders must yield byte-equal
        # JSON. This protects future readers parsing the file mid-write from
        # observing reordered keys across heartbeat refreshes.
        from story_automator.core.atomic_io import RunLockIdentity

        a = RunLockIdentity(
            pid=1,
            start_time=2.0,
            hostname="h",
            heartbeat_iso="2026-06-14T00:00:00Z",
            run_id="r",
        )
        b = RunLockIdentity(
            run_id="r",
            heartbeat_iso="2026-06-14T00:00:00Z",
            hostname="h",
            start_time=2.0,
            pid=1,
        )
        self.assertEqual(a.to_json(), b.to_json())

    def test_to_json_uses_compact_json_helper(self) -> None:
        # REQ-05 explicitly requires the compact_json helper from common.py;
        # patching it must be observable so we know the wiring is right.
        identity = self._sample()
        with patch(
            "story_automator.core.atomic_io.compact_json",
            return_value='{"sentinel":true}',
        ) as spy:
            self.assertEqual(identity.to_json(), '{"sentinel":true}')
            spy.assert_called_once()


class AcquireRunLockHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_acquire_writes_payload_and_returns_handle(self) -> None:
        from story_automator.core.atomic_io import (
            RunLockHandle,
            RunLockIdentity,
            acquire_run_lock,
        )

        lock_path = self.dir / "run.lock-payload"
        handle = acquire_run_lock(lock_path, run_id="run-xyz")
        try:
            self.assertIsInstance(handle, RunLockHandle)
            self.assertTrue(lock_path.exists())
            parsed = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["run_id"], "run-xyz")
            self.assertEqual(parsed["pid"], os.getpid())
            self.assertIsInstance(parsed["start_time"], float)
            self.assertIsInstance(parsed["hostname"], str)
            self.assertRegex(
                parsed["heartbeat_iso"],
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            )
            self.assertIsInstance(handle.identity, RunLockIdentity)
            self.assertEqual(handle.identity.run_id, "run-xyz")
        finally:
            handle.release()

    def test_handle_is_a_context_manager_that_cleans_up(self) -> None:
        from story_automator.core.atomic_io import acquire_run_lock

        lock_path = self.dir / "run.lock-payload"
        with acquire_run_lock(lock_path, run_id="run-ctx") as handle:
            self.assertTrue(lock_path.exists())
            inside = handle.identity.run_id
        self.assertEqual(inside, "run-ctx")
        self.assertFalse(lock_path.exists())

    def test_lock_sidecar_path_is_payload_path_plus_dot_lock(self) -> None:
        from story_automator.core.atomic_io import acquire_run_lock

        lock_path = self.dir / "subdir" / "run.payload"
        lock_path.parent.mkdir(parents=True)

        captured_args: list[str] = []

        class FakeFileLock:
            def __init__(self, p: str, *args: object, **kwargs: object) -> None:
                captured_args.append(p)
                self._p = p

            def acquire(self, timeout: float = -1) -> None:
                return None

            def release(self, force: bool = False) -> None:
                return None

        with patch("story_automator.core.atomic_io.FileLock", FakeFileLock):
            handle = acquire_run_lock(lock_path, run_id="run-path")
            handle.release()

        self.assertEqual(captured_args, [str(lock_path) + ".lock"])

    def test_release_is_idempotent(self) -> None:
        from story_automator.core.atomic_io import acquire_run_lock

        lock_path = self.dir / "run.lock-payload"
        handle = acquire_run_lock(lock_path, run_id="run-idem")
        handle.release()
        handle.release()


class AcquireRunLockTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_filelock_timeout_is_translated_to_run_lock_busy(self) -> None:
        from filelock import Timeout

        from story_automator.core.atomic_io import (
            RunLockBusy,
            acquire_run_lock,
        )

        lock_path = self.dir / "run.payload"

        class BusyFileLock:
            def __init__(self, p: str, *a: object, **kw: object) -> None:
                pass

            def acquire(self, timeout: float = -1) -> None:
                raise Timeout("simulated busy lock")

            def release(self, force: bool = False) -> None:
                return None

        with patch("story_automator.core.atomic_io.FileLock", BusyFileLock):
            with self.assertRaises(RunLockBusy) as ctx:
                acquire_run_lock(lock_path, run_id="run-busy", timeout=0.0)

        self.assertIsInstance(ctx.exception.__cause__, Timeout)
        self.assertFalse(lock_path.exists())

    def test_acquire_zero_timeout_does_not_block(self) -> None:
        from story_automator.core.atomic_io import (
            RunLockBusy,
            acquire_run_lock,
        )

        lock_path = self.dir / "run.payload"
        outer = acquire_run_lock(lock_path, run_id="run-outer", timeout=0.0)
        try:
            t0 = time.monotonic()
            with self.assertRaises(RunLockBusy):
                acquire_run_lock(lock_path, run_id="run-inner", timeout=0.0)
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 2.0)
        finally:
            outer.release()


class IdentityPopulationTests(unittest.TestCase):
    """REQ-07: heartbeat_iso via iso_now(), start_time via time.time(),
    hostname via socket.gethostname(), pid via os.getpid()."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_identity_fields_populated_from_canonical_helpers(self) -> None:
        from story_automator.core.atomic_io import acquire_run_lock

        lock_path = self.dir / "run.payload"

        with (
            patch("story_automator.core.atomic_io.os.getpid", return_value=9999),
            patch("story_automator.core.atomic_io.time.time", return_value=12345.5),
            patch(
                "story_automator.core.atomic_io.socket.gethostname",
                return_value="fake-host",
            ),
            patch(
                "story_automator.core.atomic_io.iso_now",
                return_value="2026-06-15T01:02:03Z",
            ),
        ):
            handle = acquire_run_lock(lock_path, run_id="run-pop")

        try:
            self.assertEqual(handle.identity.pid, 9999)
            self.assertEqual(handle.identity.start_time, 12345.5)
            self.assertEqual(handle.identity.hostname, "fake-host")
            self.assertEqual(handle.identity.heartbeat_iso, "2026-06-15T01:02:03Z")
            self.assertEqual(handle.identity.run_id, "run-pop")
            self.assertEqual(
                json.loads(lock_path.read_text(encoding="utf-8")),
                {
                    "pid": 9999,
                    "start_time": 12345.5,
                    "hostname": "fake-host",
                    "heartbeat_iso": "2026-06-15T01:02:03Z",
                    "run_id": "run-pop",
                },
            )
        finally:
            handle.release()


class AcquireRunLockFailureCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_payload_write_failure_releases_filelock(self) -> None:
        from story_automator.core.atomic_io import acquire_run_lock

        lock_path = self.dir / "run.payload"
        release_calls: list[bool] = []
        original_acquire: list[bool] = []

        class TrackingFileLock:
            def __init__(self, p: str, *a: object, **kw: object) -> None:
                self.p = p
                self.acquired = False

            def acquire(self, timeout: float = -1) -> None:
                self.acquired = True
                original_acquire.append(True)

            def release(self, force: bool = False) -> None:
                release_calls.append(self.acquired)

        with (
            patch("story_automator.core.atomic_io.FileLock", TrackingFileLock),
            patch(
                "story_automator.core.atomic_io.write_atomic_text",
                side_effect=OSError("simulated disk full"),
            ),
        ):
            with self.assertRaises(OSError):
                acquire_run_lock(lock_path, run_id="run-fail")

        self.assertEqual(original_acquire, [True])
        self.assertEqual(release_calls, [True])


class ParseIsoSecondsTests(unittest.TestCase):
    def test_epoch_zero(self) -> None:
        from story_automator.core.atomic_io import parse_iso_seconds

        # 1970-01-01T00:00:00Z is the Unix epoch — easiest exact-value pin.
        self.assertEqual(parse_iso_seconds("1970-01-01T00:00:00Z"), 0.0)

    def test_one_second_past_epoch(self) -> None:
        from story_automator.core.atomic_io import parse_iso_seconds

        # Pins second resolution and ordering — if a future refactor
        # accidentally parses milliseconds, this immediately surfaces.
        self.assertEqual(parse_iso_seconds("1970-01-01T00:00:01Z"), 1.0)

    def test_inverse_of_datetime_utc(self) -> None:
        # Cross-check against the stdlib so the exact epoch value used in
        # later is_stale tests cannot drift. Using datetime() directly keeps
        # the assertion independent of any mental arithmetic.
        from datetime import datetime, timezone

        from story_automator.core.atomic_io import parse_iso_seconds

        expected = datetime(2026, 6, 15, 12, 34, 56, tzinfo=timezone.utc).timestamp()
        self.assertEqual(parse_iso_seconds("2026-06-15T12:34:56Z"), expected)

    def test_rejects_non_utc_format(self) -> None:
        # The format must match iso_now() exactly. A trailing offset like
        # "+00:00" or a missing "Z" indicates the value did not come from
        # our own iso_now() helper and must not be silently coerced.
        from story_automator.core.atomic_io import parse_iso_seconds

        with self.assertRaises(ValueError):
            parse_iso_seconds("2026-06-15T12:34:56+00:00")
        with self.assertRaises(ValueError):
            parse_iso_seconds("2026-06-15T12:34:56")

    def test_round_trip_with_iso_now(self) -> None:
        # iso_now() is the canonical producer; parse_iso_seconds must accept
        # any value it emits without raising. Drift in either direction would
        # silently break is_stale arithmetic.
        from story_automator.core.atomic_io import parse_iso_seconds
        from story_automator.core.common import iso_now

        sample = iso_now()
        result = parse_iso_seconds(sample)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0.0)


class ImportAllowlistTests(unittest.TestCase):
    """REQ-12: only stdlib plus filelock and psutil. The audit is a grep in
    the spec's quality gates; this test is the CI-side counterpart so the
    constraint cannot be silently broken between releases."""

    def test_only_allowlisted_third_party_imports(self) -> None:
        import re
        from pathlib import Path as _Path

        module_path = (
            _Path(__file__).resolve().parent.parent
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "atomic_io.py"
        )
        source = module_path.read_text(encoding="utf-8")

        # Stdlib roots we expect to see in this module today. Anything outside
        # this set that is NOT filelock or psutil is a guardrail violation.
        stdlib_roots = {
            "__future__",
            "dataclasses",
            "datetime",
            "os",
            "socket",
            "sys",
            "threading",
            "time",
            "pathlib",
        }
        allowed_third_party = {"filelock", "psutil"}
        local_roots = {"story_automator"}

        import_line = re.compile(r"^(?:from|import)\s+([\w\.]+)", re.MULTILINE)
        for match in import_line.finditer(source):
            root = match.group(1).split(".", 1)[0]
            self.assertIn(
                root,
                stdlib_roots | allowed_third_party | local_roots,
                f"unexpected import root: {root!r} — REQ-12 allowlist violated",
            )

    def test_psutil_is_importable(self) -> None:
        # The module imports psutil at top level (REQ-09 uses pid_exists),
        # so a missing psutil at install time would surface as ImportError
        # at import. Pin the dependency presence here for clarity.
        import psutil  # noqa: F401


class IsStaleTrueBranchTests(unittest.TestCase):
    """REQ-09 / REQ-13: dead PID + heartbeat older than 600s ⇒ True."""

    def _identity(self, *, pid: int, heartbeat_iso: str):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import RunLockIdentity

        return RunLockIdentity(
            pid=pid,
            start_time=0.0,
            hostname="h",
            heartbeat_iso=heartbeat_iso,
            run_id="r",
        )

    def test_dead_pid_and_aged_heartbeat_is_stale(self) -> None:
        from story_automator.core.atomic_io import is_stale

        # Use the Unix epoch as the heartbeat so all arithmetic below is
        # exact and inspectable. parse_iso_seconds("1970-01-01T00:00:00Z")
        # is 0.0 (pinned by ParseIsoSecondsTests.test_epoch_zero), so
        # `age == now`.
        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        # now is 3600s past the heartbeat — well beyond the 600s window.
        now = 3600.0
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=False,
        ):
            self.assertTrue(is_stale(identity, now=now))


class IsStaleFalseBranchTests(unittest.TestCase):
    """REQ-09 / REQ-13: each of the three False cells of the truth table."""

    def _identity(self, *, pid: int, heartbeat_iso: str):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import RunLockIdentity

        return RunLockIdentity(
            pid=pid,
            start_time=0.0,
            hostname="h",
            heartbeat_iso=heartbeat_iso,
            run_id="r",
        )

    def test_live_pid_with_aged_heartbeat_is_not_stale(self) -> None:
        # A long-running process whose heartbeat is far behind must NOT be
        # reclaimed if the PID is still alive — the runtime might be wedged
        # but it has not actually died.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=os.getpid(),
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 3600.0  # heartbeat parses to 0.0; age == now.
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=True,
        ):
            self.assertFalse(is_stale(identity, now=now))

    def test_dead_pid_with_fresh_heartbeat_is_not_stale(self) -> None:
        # A crashed process whose lock is less than 600s old must NOT be
        # reclaimed — its successor may still be racing to acquire the lock.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 60.0  # only 60s past the heartbeat
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=False,
        ):
            self.assertFalse(is_stale(identity, now=now))

    def test_exactly_at_600s_threshold_is_not_stale(self) -> None:
        # Strict ">" per REQ-09: age == 600.0 is still fresh. Off-by-one at
        # the boundary would silently shrink the window.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 600.0
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=False,
        ):
            self.assertFalse(is_stale(identity, now=now))

    def test_just_past_threshold_with_dead_pid_is_stale(self) -> None:
        # Symmetric to the boundary test: 600.001s past must flip to True
        # when the PID is dead.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 600.001
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=False,
        ):
            self.assertTrue(is_stale(identity, now=now))

    def test_default_now_uses_time_time(self) -> None:
        # REQ-09: now=None ⇒ time.time() at call site. Confirm by patching
        # time.time inside the module to a controlled fixed value.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        with (
            patch(
                "story_automator.core.atomic_io.time.time",
                return_value=3600.0,
            ),
            patch(
                "story_automator.core.atomic_io.psutil.pid_exists",
                return_value=False,
            ),
        ):
            self.assertTrue(is_stale(identity))

    def test_pid_exists_short_circuits_on_fresh_heartbeat(self) -> None:
        # If the heartbeat is fresh, psutil.pid_exists must not be called —
        # avoid a needless syscall on the common path. This is a perf
        # contract, not a correctness contract, but it also locks the cheap-
        # first ordering documented in the docstring.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 60.0
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists"
        ) as pid_exists_spy:
            self.assertFalse(is_stale(identity, now=now))
            pid_exists_spy.assert_not_called()
