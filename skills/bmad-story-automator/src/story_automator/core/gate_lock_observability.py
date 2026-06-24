"""Lock-holder observability for the gate-lifecycle file lock (Milestone B2).

When :func:`evidence_io.get_gate_lock` times out the operator today sees an
opaque :class:`filelock.Timeout` and has to ``lsof``/``ps`` from another
shell to find the holder. This module ships three things to close that
gap without expanding the frozen public surface of ``evidence_io.py``:

* :class:`GateLockTimeoutError` — a :class:`filelock.Timeout` subclass that
  carries ``holder`` + ``timeout_s`` attributes and renders a useful
  ``__str__``. ``except filelock.Timeout:`` callers still match by
  inheritance.
* :func:`_describe_lock_holder` — leading-underscore private helper that
  reads the in-flight gate marker to identify the live holder. Never
  raises; observability code must not amplify a primary failure.
* :func:`_handle_gate_lock_timeout` — leading-underscore private helper
  used at all three ``get_gate_lock`` call sites
  (``gate_orchestrator.py`` x2, ``system_gate.py`` x1) to convert a raw
  :class:`filelock.Timeout` into a :class:`GateLockTimeoutError` and emit
  a one-line ``stderr`` log. Centralized to prevent augmentation drift.

Trust-boundary note (single-user threat model): the marker carries
``pid`` + ``hostname`` + ``started_at`` — operator-visible identity
already on disk via ``write_gate_marker``. No new sensitive surface.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, NoReturn

from filelock import Timeout

from .evidence_io import GateMarkerCorruptedError, read_gate_marker


def _rebuild_gate_lock_timeout(
    lock_file: str,
    holder: dict[str, Any] | None,
    timeout: float,
) -> "GateLockTimeoutError":
    """Module-level constructor used by ``GateLockTimeoutError.__reduce__``.

    The pickle protocol needs a callable that accepts positional args. The
    subclass ``__init__`` marks ``holder`` and ``timeout`` as keyword-only,
    so we route through this helper to translate the positional tuple from
    ``__reduce__`` back into the keyword-only signature.
    """
    return GateLockTimeoutError(lock_file, holder=holder, timeout=timeout)


class GateLockTimeoutError(Timeout):
    """``filelock.Timeout`` subclass carrying holder identity for operability.

    Stable public attributes:

    * ``lock_file`` (inherited): absolute path of the lock file (NOT a
      free-form prose message — fixes the broken ``raise Timeout(msg)``
      pattern flagged by gap B-H1).
    * ``holder``: ``dict | None`` — output of
      :func:`_describe_lock_holder`. ``None`` only on internal lookup
      error; otherwise a marker subset or a ``{"_state": ...}`` sentinel.
    * ``timeout_s``: ``float`` — the timeout value the caller passed to
      :func:`evidence_io.get_gate_lock`.
    """

    def __init__(
        self,
        lock_file: str,
        *,
        holder: dict[str, Any] | None,
        timeout: float,
    ) -> None:
        super().__init__(lock_file)
        self.holder = holder
        self.timeout_s = timeout

    def __reduce__(
        self,
    ) -> tuple[Any, tuple[str, dict[str, Any] | None, float]]:
        # The inherited ``filelock.Timeout.__reduce__`` returns
        # ``(self.__class__, (self._lock_file,))`` — i.e. it only passes the
        # positional ``lock_file``. Because ``__init__`` adds ``holder`` and
        # ``timeout`` as required keyword-only arguments, the inherited
        # reduction is incompatible with this subclass: ``pickle.loads``,
        # ``copy.copy``, and ``copy.deepcopy`` would all raise
        # ``TypeError: missing 2 required keyword-only arguments``.
        # Route through ``_rebuild_gate_lock_timeout`` so the positional
        # tuple from ``__reduce__`` is translated back into the kw-only
        # ``__init__`` signature.
        return (
            _rebuild_gate_lock_timeout,
            (self._lock_file, self.holder, self.timeout_s),
        )

    def __str__(self) -> str:
        base = (
            f"gate lock at {self.lock_file} not acquired within "
            f"{self.timeout_s}s"
        )
        holder = self.holder
        if holder is None:
            return f"{base}; holder unknown"
        state = holder.get("_state")
        if state == "missing":
            return (
                f"{base}; holder unknown (marker missing — holder may have "
                f"just released the lock)"
            )
        if state == "corrupt":
            return f"{base}; holder unknown (marker present but unparseable)"
        if state == "legacy":
            return (
                f"{base}; held by a pre-L1 process (PID unavailable — legacy "
                f"marker)"
            )
        # Well-formed marker subset.
        pid = holder.get("pid")
        started_at = holder.get("started_at")
        host = holder.get("hostname", "")
        return (
            f"{base}; held by PID={pid}, started_at={started_at}, host={host}"
        )


def _describe_lock_holder(
    project_root: str | Path,
) -> dict[str, Any] | None:
    """Read holder identity from the gate marker for observability.

    Returns one of:

    * ``{"pid": int, "started_at": str, "hostname": str}`` — marker
      present and well-formed.
    * ``{"_state": "missing"}`` — marker file absent (holder may have
      just released the lock).
    * ``{"_state": "legacy"}`` — marker present and well-formed but
      written by a pre-L1+J-03 process (no ``pid`` field). The legacy
      shape is part of the supported back-compat contract (see
      ``write_gate_marker`` docstring + ``recover_from_crash`` B1
      fallback) — distinguishing it from "corrupt" prevents an
      operator-misleading diagnostic.
    * ``{"_state": "corrupt"}`` — marker file present but unparseable
      (e.g. ``pid`` field present but wrong type, or marker raises
      :class:`GateMarkerCorruptedError`).
    * ``None`` — internal/unrecognized error (caller treats as "unknown").

    Never raises. Observability code must not amplify a primary failure.
    """
    try:
        marker = read_gate_marker(project_root)
    except GateMarkerCorruptedError:
        return {"_state": "corrupt"}
    except Exception:  # noqa: BLE001 — observability never amplifies failure
        return None
    if marker is None:
        return {"_state": "missing"}
    pid = marker.get("pid")
    started_at = marker.get("started_at")
    hostname = marker.get("hostname")
    # Legacy markers (pre-L1+J-03) carry gate_id/commit_sha/started_at
    # but no pid — read_gate_marker tolerates that shape (evidence_io.py
    # only validates the three required string fields). Treat the missing
    # pid as ``"_state": "legacy"`` so the operator sees an accurate
    # diagnostic rather than the misleading "marker present but
    # unparseable" rendering.
    if pid is None:
        return {"_state": "legacy"}
    # ``isinstance(pid, int)`` returns True for bool — guard against the
    # int/bool gotcha so a marker carrying ``"pid": true`` is reported as
    # corrupt rather than rendered as ``PID=True``.
    if not (
        isinstance(pid, int)
        and not isinstance(pid, bool)
        and isinstance(started_at, str)
    ):
        return {"_state": "corrupt"}
    return {
        "pid": pid,
        "started_at": started_at,
        "hostname": hostname if isinstance(hostname, str) else "",
    }


def _handle_gate_lock_timeout(
    project_root: str | Path,
    lock_path: str | Path,
    timeout: float,
    exc: Timeout,
) -> NoReturn:
    """Convert a raw ``filelock.Timeout`` into a ``GateLockTimeoutError``.

    Reads the lock-holder identity from the gate marker (best-effort,
    never raises), emits a one-line ``stderr`` log for the operator,
    and raises :class:`GateLockTimeoutError` chaining from the original
    ``exc``. Used at every ``get_gate_lock`` call site to keep the
    augmentation consistent (gap B-M7 — prevents drift).
    """
    holder = _describe_lock_holder(project_root)
    new_exc = GateLockTimeoutError(
        str(lock_path), holder=holder, timeout=timeout,
    )
    # Observability never amplifies the primary failure: a broken/closed
    # stderr (EPIPE on a redirected child, /dev/full, pytest-captured
    # stream that became invalid) must not mask the raise of
    # ``GateLockTimeoutError``. ``except filelock.Timeout:`` callers at
    # all three ``get_gate_lock`` sites continue to match by inheritance
    # only when the augmented exception actually propagates. Mirrors the
    # ``_describe_lock_holder`` swallow-on-error discipline.
    try:
        print(str(new_exc), file=sys.stderr)
    except OSError:
        pass
    raise new_exc from exc


__all__ = ["GateLockTimeoutError"]
