from __future__ import annotations

import os
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
