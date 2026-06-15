from __future__ import annotations

import os
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

        ta.join()
        tb.join()

        self.assertEqual(errors, [])
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
