# M05-M1: Atomic Write Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational `write_atomic_text` helper plus per-path in-process lock registry and Windows-replace retry semantics in a new `core/atomic_io.py` module, as the first wedge atom of milestone M05.

**Architecture:** A single new module `skills/bmad-story-automator/src/story_automator/core/atomic_io.py` exposing one public function (`write_atomic_text`) and one public exception (`AtomicWriteRetryExhausted`). The function writes via a sibling temp file (`.tmp-<pid>-<monotonic_ns>` suffix) in the same directory as the target, calls `fsync`, then `os.replace`. On Windows, `os.replace` is retried up to 5 times against `PermissionError` with exponential backoff (50, 100, 200, 400, 800 ms). Per-path serialization uses a module-level registry of `threading.Lock` keyed on resolved-absolute-path, guarded by a registry mutex. This sub-milestone is intentionally narrow — `RunLockIdentity`, `acquire_run_lock`, `HeartbeatThread`, `is_stale`, and the `state.py` wiring (REQ-05–11) are deferred to subsequent M05 sub-milestones.

**Tech Stack:** Python 3.11+ stdlib only (`os`, `time`, `threading`, `pathlib`, `sys`). `filelock` and `psutil` are on the allowlist but are NOT used in this sub-milestone — they belong to later M05 wedges. Tests use `unittest.TestCase` with `unittest.mock.patch`.

---

## Scope for this sub-milestone

**In scope (from the spec):**
- REQ-01: module exists, `from __future__ import annotations`
- REQ-02: `write_atomic_text(path, data, *, encoding="utf-8") -> None` via sibling tmp + fsync + `os.replace`
- REQ-03: per-path `threading.Lock` registry, registry guarded by a module-level lock
- REQ-04: Windows `PermissionError` retry (5 attempts, 50/100/200/400/800 ms backoff); POSIX exactly one `os.replace` call
- REQ-12: type annotations on all public surfaces, import allowlist (stdlib only for this wedge), module ≤500 LOC
- REQ-13 subset: atomic replace happy path, simulated `PermissionError` retry (mock-based), per-path lock serialization
- REQ-14: tests use `unittest.TestCase`, no subprocesses, no tmux, cross-platform
- Non-functional reliability (crash between fsync and replace leaves original intact)
- Non-functional concurrency safety (in-process per-path serialization)
- Non-functional portability (no `O_TMPFILE`/`fcntl`/`msvcrt`)
- Non-functional observability: `AtomicWriteRetryExhausted` exception type defined and raised on retry exhaustion
- Quality gates: ruff check/format, import allowlist audit, module size, coverage ≥85% for the new module

**Out of scope (deferred to later M05 sub-milestones):**
- REQ-05: `RunLockIdentity` dataclass
- REQ-06–07: `acquire_run_lock` and `RunLockHandle`
- REQ-08: `HeartbeatThread`
- REQ-09: `is_stale`
- REQ-10–11: `state.py` integration and marker-file removal
- `RunLockBusy` exception
- All `filelock`/`psutil` integration

---

## File Structure

| File | New / Modified | Responsibility |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/atomic_io.py` | Create | `write_atomic_text`, `AtomicWriteRetryExhausted`, private per-path lock registry, private Windows retry helper |
| `tests/test_atomic_io.py` | Create | Unit tests for happy path, retry, serialization, exception type, payload integrity |

No other files are modified by this sub-milestone. `common.py` is **not** touched — its existing `write_atomic` stays in place (a later sub-milestone may consolidate, but not here, per YAGNI).

---

## Task 1: Module skeleton and exception type

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Test: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_atomic_io.py`:

```python
from __future__ import annotations

import unittest


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'story_automator.core.atomic_io'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`:

```python
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

__all__ = ["AtomicWriteRetryExhausted", "write_atomic_text"]


class AtomicWriteRetryExhausted(PermissionError):
    """Raised when os.replace retries are exhausted on Windows.

    Subclasses PermissionError so REQ-04's "raise the final PermissionError"
    contract is satisfied while still being a TYPED exception per the
    observability NFR (later M02 telemetry wiring can classify it by type
    rather than string-match). PermissionError is itself a subclass of
    OSError, so callers that already handle OSError keep working.
    """


def write_atomic_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    raise NotImplementedError
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): add module skeleton and AtomicWriteRetryExhausted exception"
```

---

## Task 2: Happy-path atomic write

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_atomic_io.py`:

```python
import tempfile
from pathlib import Path


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
        from unittest.mock import patch

        target = self.dir / "out.txt"
        observed_dirs: list[Path] = []
        real_replace = os.replace

        def spy(src: str, dst: str) -> None:
            observed_dirs.append(Path(src).parent.resolve())
            real_replace(src, dst)

        with patch("story_automator.core.atomic_io.os.replace", side_effect=spy):
            write_atomic_text(target, "payload")

        self.assertEqual(observed_dirs, [self.dir.resolve()])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: FAIL on the new `HappyPathTests` cases (`NotImplementedError`).

- [ ] **Step 3: Replace the stub with the working implementation**

Edit `atomic_io.py` — replace the `write_atomic_text` body:

```python
def _write_once(path: Path, data: str, encoding: str) -> None:
    parent = path.parent
    tmp_name = f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    tmp_path = parent / tmp_name
    fd = os.open(
        str(tmp_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data.encode(encoding))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        # The with-block owns fd on success; on rare fdopen-raise we must
        # close it ourselves. The os.close itself raising is treated as a
        # double-close (the fd was already cleaned up) and silently
        # absorbed — we must not mask the original write failure.
        try:  # pragma: no cover - defensive double-close guard
            os.close(fd)
        except OSError:  # pragma: no cover
            pass
        _silent_unlink(tmp_path)
        raise

    try:
        os.replace(str(tmp_path), str(path))
    except BaseException:
        _silent_unlink(tmp_path)
        raise


def _silent_unlink(path: Path) -> None:
    try:
        os.unlink(str(path))
    except FileNotFoundError:
        pass
    except OSError:  # pragma: no cover - best-effort cleanup
        # Do not mask the original error.
        pass


def write_atomic_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    """Write `data` to `path` atomically.

    Writes to a sibling temp file in the same directory, fsyncs, then
    os.replace's into place. On Windows, retries os.replace up to 5 times
    against PermissionError (ERROR_SHARING_VIOLATION) with exponential
    backoff. Per-path serialization is handled by the module-level lock
    registry — added in a later task.
    """
    _write_once(path, data, encoding)
```

> NOTE: the `os.close(fd)` branch only fires if `os.fdopen` raises — `fdopen` takes ownership of `fd` on success, so we must close it ourselves on failure. The `except BaseException` is intentional: we want cleanup even on `KeyboardInterrupt`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: PASS (8 tests total).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): implement happy-path tmp+fsync+os.replace write"
```

---

## Task 3: Windows PermissionError retry with backoff

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py`:

```python
from unittest.mock import patch


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

        with patch("story_automator.core.atomic_io._is_windows", return_value=True), \
             patch("story_automator.core.atomic_io.os.replace", side_effect=flaky), \
             patch("story_automator.core.atomic_io.time.sleep", side_effect=fake_sleep):
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

        with patch("story_automator.core.atomic_io._is_windows", return_value=True), \
             patch("story_automator.core.atomic_io.os.replace", side_effect=always_fails), \
             patch("story_automator.core.atomic_io.time.sleep",
                   side_effect=lambda d: sleep_log.append(d)):
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

        with patch("story_automator.core.atomic_io._is_windows", return_value=False), \
             patch("story_automator.core.atomic_io.os.replace", side_effect=fails):
            with self.assertRaises(PermissionError):
                write_atomic_text(target, "payload")

        self.assertEqual(attempts["n"], 1)

    def test_posix_non_permission_error_is_not_swallowed(self) -> None:
        from story_automator.core.atomic_io import write_atomic_text

        target = self.dir / "out.txt"

        def fails(src: str, dst: str) -> None:
            raise OSError("disk full")

        with patch("story_automator.core.atomic_io._is_windows", return_value=False), \
             patch("story_automator.core.atomic_io.os.replace", side_effect=fails):
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

        with patch("story_automator.core.atomic_io._is_windows", return_value=True), \
             patch("story_automator.core.atomic_io.os.replace", side_effect=fails), \
             patch("story_automator.core.atomic_io.time.sleep",
                   side_effect=lambda d: sleep_log.append(d)):
            with self.assertRaises(OSError):
                write_atomic_text(target, "payload")

        self.assertEqual(attempts["n"], 1)
        self.assertEqual(sleep_log, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.WindowsRetryTests -v`
Expected: FAIL on retry tests — the current implementation does not retry.

- [ ] **Step 3: Add retry logic to `_write_once`**

Edit `atomic_io.py` — replace the `_write_once` and `write_atomic_text` bodies; add a `_replace_with_retry` helper:

```python
# Inter-retry backoffs: sleep _WINDOWS_REPLACE_BACKOFFS_S[i] BEFORE the
# (i+1)-th retry. With 5 entries this gives 1 initial attempt + 5 retries =
# 6 total attempts on Windows; on POSIX exactly 1 attempt.
_WINDOWS_REPLACE_BACKOFFS_S: tuple[float, ...] = (0.050, 0.100, 0.200, 0.400, 0.800)


def _is_windows() -> bool:
    return sys.platform == "win32"


def _replace_with_retry(tmp_path: Path, target: Path) -> None:
    if not _is_windows():
        os.replace(str(tmp_path), str(target))
        return

    # Initial attempt (no preceding sleep).
    try:
        os.replace(str(tmp_path), str(target))
        return
    except PermissionError as last_error:
        pending = last_error
    # Non-PermissionError OSError propagates naturally without retry.

    for backoff in _WINDOWS_REPLACE_BACKOFFS_S:
        time.sleep(backoff)
        try:
            os.replace(str(tmp_path), str(target))
            return
        except PermissionError as err:
            pending = err
        # Non-PermissionError OSError on retry also propagates naturally.

    raise AtomicWriteRetryExhausted(
        f"os.replace failed after {1 + len(_WINDOWS_REPLACE_BACKOFFS_S)} attempts: "
        f"{target}"
    ) from pending
```

Then update `_write_once` to call `_replace_with_retry` instead of `os.replace` directly:

```python
def _write_once(path: Path, data: str, encoding: str) -> None:
    parent = path.parent
    tmp_name = f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    tmp_path = parent / tmp_name
    fd = os.open(
        str(tmp_path),
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data.encode(encoding))
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        _silent_unlink(tmp_path)
        raise

    try:
        _replace_with_retry(tmp_path, path)
    except BaseException:
        _silent_unlink(tmp_path)
        raise
```

> SEMANTICS: 1 initial attempt + up to 5 retries = 6 total attempts on Windows. Each retry is preceded by the corresponding backoff sleep. Walkthrough of the two failure modes:
> - **Success on attempt 3**: initial fails → sleep 50ms → retry-1 fails → sleep 100ms → retry-2 succeeds → return. `sleep_log == [0.050, 0.100]`.
> - **All 6 attempts fail**: initial fails → 5 cycles of (sleep, retry-fail) at 50/100/200/400/800 ms → `raise AtomicWriteRetryExhausted` (subclass of `PermissionError`) `from pending`. `sleep_log == [0.050, 0.100, 0.200, 0.400, 0.800]`.
> A non-`PermissionError` `OSError` propagates unwrapped without retry (REQ-04 is specific to `PermissionError`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: PASS (13 tests total).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): retry os.replace on Windows PermissionError with exponential backoff"
```

---

## Task 4: Per-path lock registry

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py`:

```python
import threading


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
        self.assertTrue(observed.issubset(valid),
                        f"observed non-atomic content: {observed - valid!r}")

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
        from story_automator.core.atomic_io import _lock_for_path, _reset_registry_for_tests

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.PerPathLockSerializationTests -v`
Expected: FAIL — `_lock_for_path` and `_reset_registry_for_tests` do not exist yet.

- [ ] **Step 3: Add the registry and gate `write_atomic_text` through it**

Edit `atomic_io.py` — add at module scope below `_WINDOWS_REPLACE_BACKOFFS_S`:

```python
_registry_lock: threading.Lock = threading.Lock()
_path_locks: dict[str, threading.Lock] = {}


def _lock_for_path(path: Path) -> threading.Lock:
    """Return the threading.Lock guarding writes to the resolved `path`.

    The registry itself is guarded by `_registry_lock` so that concurrent
    first-time lookups for the same path agree on a single Lock instance.
    """
    key = str(Path(path).resolve())
    with _registry_lock:
        lock = _path_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _path_locks[key] = lock
        return lock


def _reset_registry_for_tests() -> None:
    """Clear the registry. Test-only — not part of the public API."""
    with _registry_lock:
        _path_locks.clear()
```

Then update `write_atomic_text` to acquire the per-path lock around the write:

```python
def write_atomic_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    """Write `data` to `path` atomically.

    Writes to a sibling temp file in the same directory, fsyncs, then
    os.replace's into place. On Windows, retries os.replace up to 5 times
    against PermissionError (ERROR_SHARING_VIOLATION) with exponential
    backoff. The write is serialized in-process via a per-path
    threading.Lock; cross-process serialization is the caller's
    responsibility (see acquire_run_lock — added in a later sub-milestone).
    """
    lock = _lock_for_path(path)
    lock.acquire()
    try:
        _write_once(path, data, encoding)
    finally:
        lock.release()
```

> The serialization test uses a 4 KB payload so reading mid-write would, on a non-atomic implementation, plausibly observe a partial buffer. With `os.replace` semantics this should hold even without the per-path lock (the test mainly exercises that the writers don't race each other into a `FileExistsError` on the tmp file — though our `<pid>-<monotonic_ns>` suffix is already collision-resistant). The lock matters for downstream callers that perform read-modify-write through this API in later sub-milestones.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: PASS (17 tests total).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): serialize writes through per-path threading.Lock registry"
```

---

## Task 5: Reliability — crash leaves original intact

**Files:**
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_atomic_io.py`:

```python
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

        with patch("story_automator.core.atomic_io._is_windows", return_value=False), \
             patch("story_automator.core.atomic_io.os.replace", side_effect=boom):
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
        with patch("story_automator.core.atomic_io.os.fsync",
                   side_effect=OSError("fsync failed")):
            with self.assertRaises(OSError):
                write_atomic_text(target, "NEW")

        self.assertFalse(target.exists())
        siblings = list(self.dir.iterdir())
        self.assertEqual(siblings, [])
```

- [ ] **Step 2: Run tests to verify they fail or pass as appropriate**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.CrashSafetyTests -v`
Expected: PASS already — the cleanup logic from Task 2 should cover both cases. If they fail, debug the cleanup branches in `_write_once` before proceeding.

- [ ] **Step 3: Skip if green** — these tests document existing behavior.

- [ ] **Step 4: Commit the documentation tests**

```bash
git add tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(atomic_io): document crash-safety behavior for replace and fsync failures"
```

---

## Task 6: Quality gates — lint, format, import allowlist, module size, coverage

**Files:**
- Inspect (no edits unless gates fail): `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`

- [ ] **Step 1: Ruff check**

Run: `python -m ruff check skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py`
Expected: exit 0. If failures arise, fix the source — do not suppress.

- [ ] **Step 2: Ruff format check**

Run: `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py`
If it fails: run `python -m ruff format skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py` then re-run the check.

- [ ] **Step 3: Import allowlist audit**

Run on Windows PowerShell or bash:

```bash
grep -E "^(import|from) " skills/bmad-story-automator/src/story_automator/core/atomic_io.py
```

Expected output — only stdlib modules. No `filelock`, no `psutil`, no other third-party imports in this sub-milestone (they belong to later wedges). Acceptable imports: `os`, `sys`, `threading`, `time`, `pathlib`.

- [ ] **Step 4: Module size guardrail**

Run on bash: `wc -l skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
Expected: ≤ 500 source lines. (Current expected length: well under 200.)

On PowerShell: `(Get-Content skills/bmad-story-automator/src/story_automator/core/atomic_io.py | Measure-Object -Line).Lines`

- [ ] **Step 5: Coverage gate**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/atomic_io \
  -m unittest tests.test_atomic_io
python -m coverage report -m --fail-under=85
```

Expected: PASS (coverage ≥ 85%). If a particular branch is uncovered, add a focused test rather than lowering the gate.

- [ ] **Step 6: Full suite regression check**

Run: `npm run test:python`
Expected: PASS — every pre-existing test and the new `tests/test_atomic_io.py` discover and pass.

- [ ] **Step 7: Commit any formatting fixes (if Step 2 applied them)**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(atomic_io): ruff format pass"
```

If no fixes were needed, skip this step — do not create an empty commit.

---

## Task 7: Verification on the operator's primary shell (Windows git-bash) and WSL

**Files:** none modified.

- [ ] **Step 1: Windows git-bash run**

Run from a git-bash prompt:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v
```

Expected: all tests PASS. Pay particular attention to:
- `test_failure_during_replace_preserves_original_target` — Windows lock semantics differ from POSIX.
- `test_two_threads_on_same_path_observe_only_complete_writes` — Windows file handles can interact with concurrent readers in surprising ways.

If a real (non-mocked) `PermissionError` surfaces on Windows for an unrelated reason, the retry logic should absorb it transparently — investigate before disabling the test.

- [ ] **Step 2: WSL Ubuntu run (optional but recommended)**

From WSL:

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_atomic_io -v
```

Expected: all PASS. The Windows-path mock tests must still pass on Linux because the `sys.platform` is patched, not introspected indirectly.

- [ ] **Step 3: Final commit-free sign-off**

Update no files. Print a one-line confirmation in the dev log that the test suite is green on at least one of {Windows git-bash, WSL Ubuntu}.

---

## Self-Review Checklist (run after writing tasks 1–7)

- **Spec coverage:**
  - REQ-01: Task 1 (module exists, `from __future__ import annotations` in skeleton).
  - REQ-02: Task 2 (write_atomic_text with sibling tmp + fsync + os.replace).
  - REQ-03: Task 4 (per-path registry, guarded by module-level lock).
  - REQ-04: Task 3 (Windows: 1 initial + up to 5 retries with 50/100/200/400/800 ms pre-retry sleeps; exhaustion raises `AtomicWriteRetryExhausted` which IS-A `PermissionError`; POSIX exactly one `os.replace` call).
  - REQ-12: Task 6 (annotations, imports stdlib-only for this wedge, module size).
  - REQ-13 subset: Task 2 (happy path), Task 3 (PermissionError retry via mock), Task 4 (per-path serialization).
  - REQ-14: All tests are `unittest.TestCase`, no subprocesses, no tmux, cross-platform.
  - Reliability: Task 5 (crash safety).
  - Concurrency: Task 4 (per-path serialization, registry race).
  - Portability: Tasks 1–4 use only `os`, `sys`, `threading`, `time`, `pathlib`. No `O_TMPFILE`, `fcntl`, `msvcrt`.
  - Observability: Task 1 (`AtomicWriteRetryExhausted` exists), Task 3 (raised on exhaustion).
  - Quality gates: Task 6 covers ruff check/format, import audit, module size, coverage.

- **Placeholder scan:** No "TODO", "TBD", "implement later". All code blocks are concrete.

- **Type consistency:**
  - `write_atomic_text(path: Path, data: str, *, encoding: str = "utf-8") -> None` — used identically in every task.
  - `_lock_for_path(path: Path) -> threading.Lock` — used identically in Tasks 4 tests and implementation.
  - `_replace_with_retry(tmp_path: Path, target: Path) -> None` — internal, called only from `_write_once`.
  - `_silent_unlink(path: Path) -> None` — internal, called from cleanup branches.
  - `_WINDOWS_REPLACE_BACKOFFS_S: tuple[float, ...]` — five-element tuple matching the test's expected sleep log.

- **Test names match implementation:** No drift between `_lock_for_path`/`_reset_registry_for_tests` references in tests and the actual symbol names.

---

## Notes for the implementer

1. **Why a hand-rolled `os.open(... O_EXCL ...)` instead of `tempfile.mkstemp`?** `mkstemp` returns a temp path that may be in `tempfile.gettempdir()` if no `dir=` is passed; we need the temp file in the same directory as the target so `os.replace` is atomic on the same filesystem. We could use `tempfile.mkstemp(dir=str(parent))`, but the explicit `O_EXCL` open with a deterministic name (`.<name>.tmp-<pid>-<monotonic_ns>`) makes the temp-file lifecycle easier to reason about and matches the spec's REQ-02 wording precisely.

2. **Why not reuse `common.write_atomic`?** A future sub-milestone may consolidate them. For now, the spec mandates a distinct `write_atomic_text` symbol in `atomic_io.py` with stricter contracts (per-path lock, Windows retry, typed exhaustion exception). Keeping it separate during the wedge keeps blast radius small.

3. **Why patch `sys.platform` instead of using a `_is_windows` toggle?** Both work; patching `sys.platform` (a module attribute lookup) is simpler and avoids exposing test-only knobs in the public API. The `_is_windows()` helper exists internally so the test patches a single reference point.

4. **Why `BaseException` in cleanup branches?** A `KeyboardInterrupt` arriving between `os.open` and `os.fdopen`, or between `fsync` and `os.replace`, would otherwise leak the temp file. Cleanup is silent and re-raises.

5. **Why `_reset_registry_for_tests` is intentionally private with a `_for_tests` suffix:** the public API has no need to flush the registry. The suffix signals to readers that this is a test-only escape hatch, not a stable surface.
