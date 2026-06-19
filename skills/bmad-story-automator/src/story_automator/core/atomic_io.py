from __future__ import annotations

import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout
import psutil

from story_automator.core.common import compact_json, fsync_dir, iso_now

__all__ = [
    "AtomicWriteRetryExhausted",
    "HeartbeatThread",
    "RunLockBusy",
    "RunLockHandle",
    "RunLockIdentity",
    "acquire_run_lock",
    "is_stale",
    "parse_iso_seconds",
    "write_atomic_text",
]


# Inter-retry backoffs: sleep _WINDOWS_REPLACE_BACKOFFS_S[i] BEFORE the
# (i+1)-th retry. With 5 entries this gives 1 initial attempt + 5 retries =
# 6 total attempts on Windows; on POSIX exactly 1 attempt.
_WINDOWS_REPLACE_BACKOFFS_S: tuple[float, ...] = (0.050, 0.100, 0.200, 0.400, 0.800)


def parse_iso_seconds(value: str) -> float:
    """Parse an ``iso_now()``-formatted UTC timestamp into epoch seconds.

    The expected format is exactly ``"%Y-%m-%dT%H:%M:%SZ"`` — the same string
    ``iso_now`` in ``core/common.py`` emits. ``is_stale`` (REQ-09) uses this
    to subtract from ``time.time()`` and compare against the 600-second
    stale window. Strings in any other shape (offset suffix, missing ``Z``,
    fractional seconds) raise ``ValueError`` rather than being silently
    coerced — a malformed heartbeat must surface as a parse failure, not as
    a phantom "fresh" reading.
    """
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return parsed.timestamp()


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


@dataclass(kw_only=True)
class RunLockIdentity:
    """Identity payload written into a run lock file.

    Field order is fixed by REQ-05; ``to_json`` always emits keys in this
    same order so two constructions with permuted kwargs produce byte-equal
    output. That stability matters because a future ``HeartbeatThread``
    (M05-M3) will rewrite this payload roughly every 60 seconds and stale
    detectors may diff the bytes.
    """

    pid: int
    start_time: float
    hostname: str
    heartbeat_iso: str
    run_id: str

    def to_json(self) -> str:
        return compact_json(
            {
                "pid": self.pid,
                "start_time": self.start_time,
                "hostname": self.hostname,
                "heartbeat_iso": self.heartbeat_iso,
                "run_id": self.run_id,
            }
        )


class RunLockHandle:
    """Context-manager handle returned by ``acquire_run_lock``.

    Holds the live ``filelock.FileLock``, the resolved payload ``Path``,
    and the ``RunLockIdentity`` written to disk. ``release`` (also invoked
    from ``__exit__``) is idempotent: it deletes the payload file
    best-effort and releases the FileLock exactly once.
    """

    def __init__(
        self,
        *,
        file_lock: FileLock,
        payload_path: Path,
        identity: RunLockIdentity,
    ) -> None:
        self._file_lock = file_lock
        self._payload_path = payload_path
        self._released = False
        self.identity = identity

    def __enter__(self) -> RunLockHandle:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        _silent_unlink(self._payload_path)
        try:
            self._file_lock.release()
        except Exception:  # pragma: no cover - filelock defensive guard
            pass


def acquire_run_lock(
    lock_path: Path,
    *,
    run_id: str,
    timeout: float = 0.0,
) -> RunLockHandle:
    """Acquire a cross-process run lock at ``lock_path``.

    REQ-06: wraps ``filelock.FileLock(str(lock_path) + ".lock")``,
    acquires with the given ``timeout`` (seconds; 0.0 means no waiting),
    then writes a ``RunLockIdentity`` JSON payload to ``lock_path``
    via ``write_atomic_text``. Returns a ``RunLockHandle`` whose
    ``__exit__`` / ``release`` deletes the payload and releases the lock.

    Raises ``RunLockBusy`` if the underlying filelock raises ``Timeout``.

    The caller is responsible for ensuring ``lock_path.parent`` exists;
    this function does not auto-create directories so that a typo'd path
    fails fast rather than scattering empty lock files.
    """

    sidecar = str(lock_path) + ".lock"
    file_lock = FileLock(sidecar)
    try:
        file_lock.acquire(timeout=timeout)
    except Timeout as err:
        raise RunLockBusy(
            f"run lock at {lock_path} is busy (timeout={timeout}s)"
        ) from err

    try:
        identity = RunLockIdentity(
            pid=os.getpid(),
            start_time=time.time(),
            hostname=socket.gethostname(),
            heartbeat_iso=iso_now(),
            run_id=run_id,
        )
        write_atomic_text(Path(lock_path), identity.to_json())
    except BaseException:
        try:  # pragma: no cover - defensive guard against double-release
            file_lock.release()
        except Exception:
            pass
        raise

    return RunLockHandle(
        file_lock=file_lock,
        payload_path=Path(lock_path),
        identity=identity,
    )


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
    fsync_dir(path.parent)


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


_STALE_HEARTBEAT_WINDOW_S: float = 600.0


def is_stale(
    identity: RunLockIdentity,
    *,
    now: float | None = None,
) -> bool:
    """Return ``True`` only when ``identity`` is reclaimable.

    REQ-09: stale iff the heartbeat is older than 600 seconds AND the
    recorded PID is no longer alive. Either condition alone keeps the lock
    live — a slow but still-running process must not be reclaimed, and a
    crashed process whose lock is less than 600 seconds old is presumed to
    be a fresh acquisition that hasn't ticked yet.

    The check is intentionally ordered cheap-first (timestamp arithmetic
    before the syscall in ``psutil.pid_exists``).

    Composite-identity liveness (beyond the bare REQ-09 pid check): the
    recorded ``hostname`` and ``start_time`` are also consulted so a
    foreign-host lock on a shared filesystem and a recycled-PID false
    negative are both reclaimable once the heartbeat has aged out:

    - foreign host: the local PID table is meaningless, so an aged
      heartbeat alone marks the lock stale (``pid_exists`` is not called);
    - same host: the PID must both exist AND have a process-creation time
      matching the recorded ``start_time`` — otherwise the PID was recycled
      by an unrelated process and the original owner is gone.
    """
    try:
        heartbeat_seconds = parse_iso_seconds(identity.heartbeat_iso)
    except ValueError:
        # An unparseable heartbeat (e.g. a "+00:00" offset instead of the
        # "Z" form iso_now() emits, or a partially-written lock) must not
        # crash lock liveness. Treat it as fresh — a live owner is still
        # refreshing it on the canonical format; a truly dead owner ages out
        # once a well-formed heartbeat stops arriving.
        return False
    age = (now if now is not None else time.time()) - heartbeat_seconds
    if age <= _STALE_HEARTBEAT_WINDOW_S:
        return False
    if identity.hostname != socket.gethostname():
        # Foreign-host lock: the local pid table is irrelevant. The aged
        # heartbeat is the only liveness signal we can trust.
        return True
    if not psutil.pid_exists(identity.pid):
        return True
    try:
        proc = psutil.Process(identity.pid)
        # 1.0s tolerance bridges the resolution gap between the recorded
        # start_time (time.time() float) and psutil's create_time().
        same_owner = abs(proc.create_time() - identity.start_time) < 1.0
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        same_owner = False
    return not same_owner


class HeartbeatThread(threading.Thread):
    """Daemon thread that refreshes a run lock's heartbeat field.

    REQ-08: subclasses ``threading.Thread`` with ``daemon=True``; the
    class-level ``interval`` constant is 60.0 seconds. ``stop()`` sets a
    ``threading.Event`` that the ``run()`` loop polls between writes, so
    shutdown is observed within at most one tick rather than waiting up
    to a full interval.

    The constructor accepts an optional ``interval`` argument so unit
    tests can run with sub-second tick rates without mutating the class
    constant. The on-disk payload is refreshed via ``write_atomic_text``,
    inheriting the same per-path serialization the rest of the module
    uses — concurrent writes through ``write_atomic_text`` on the same
    path never interleave.
    """

    interval: float = 60.0

    def __init__(
        self,
        *,
        lock_path: Path,
        identity: RunLockIdentity,
        interval: float | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self._lock_path = Path(lock_path)
        self._identity = identity
        if interval is not None:
            if interval <= 0:
                raise ValueError(
                    f"HeartbeatThread interval must be > 0; got {interval!r}"
                )
            self.interval = interval
        self._stop_event = threading.Event()
        self.write_errors: int = 0

    def stop(self) -> None:
        """Signal the loop to exit at its next wake-up."""
        self._stop_event.set()

    def run(self) -> None:
        """Refresh the on-disk heartbeat until ``stop()`` is signalled.

        REQ-08: rewrites the payload via ``write_atomic_text`` with a
        refreshed ``heartbeat_iso`` each tick. The loop uses
        ``Event.wait(self.interval)`` so ``stop()`` is observed within
        one wake-up rather than waiting up to a full interval. Transient
        write failures (e.g. an ENOSPC blip) are counted on
        ``self.write_errors`` and swallowed so a single bad refresh does
        not terminate the daemon; surfacing those counts is M02's job.
        """
        while not self._stop_event.is_set():
            try:
                self._identity.heartbeat_iso = iso_now()
                write_atomic_text(self._lock_path, self._identity.to_json())
            except Exception:
                self.write_errors += 1
            # wait() returns True if the event was set, False on timeout.
            if self._stop_event.wait(self.interval):
                return
