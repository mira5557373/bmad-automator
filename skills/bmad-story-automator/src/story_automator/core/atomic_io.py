from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

__all__ = [
    "AtomicWriteRetryExhausted",
    "RunLockBusy",
    "write_atomic_text",
]


# Inter-retry backoffs: sleep _WINDOWS_REPLACE_BACKOFFS_S[i] BEFORE the
# (i+1)-th retry. With 5 entries this gives 1 initial attempt + 5 retries =
# 6 total attempts on Windows; on POSIX exactly 1 attempt.
_WINDOWS_REPLACE_BACKOFFS_S: tuple[float, ...] = (0.050, 0.100, 0.200, 0.400, 0.800)


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


def _is_windows() -> bool:
    return sys.platform == "win32"


class AtomicWriteRetryExhausted(PermissionError):
    """Raised when os.replace retries are exhausted on Windows.

    Subclasses PermissionError so REQ-04's "raise the final PermissionError"
    contract is satisfied while still being a TYPED exception per the
    observability NFR (later M02 telemetry wiring can classify it by type
    rather than string-match). PermissionError is itself a subclass of
    OSError, so callers that already handle OSError keep working.
    """


class RunLockBusy(Exception):
    """Raised when acquiring a run lock times out.

    Intentionally NOT a subclass of PermissionError or
    AtomicWriteRetryExhausted: a busy run lock means another holder is
    actively making progress (or recently crashed and has not yet been
    reclaimed by the stale-detection path added in M05-M3). Future M02
    telemetry consumers classify it by type, so it must remain distinct
    from the atomic-write retry-exhaustion failure mode.
    """


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
        _replace_with_retry(tmp_path, path)
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
    backoff. The write is serialized in-process via a per-path
    threading.Lock; cross-process serialization is the caller's
    responsibility (see acquire_run_lock — added in a later sub-milestone).
    """
    with _lock_for_path(path):
        _write_once(path, data, encoding)
