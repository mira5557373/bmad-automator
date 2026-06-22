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
    * ``{"_state": "corrupt"}`` — marker file present but unparseable.
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
    if not (isinstance(pid, int) and isinstance(started_at, str)):
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
    print(str(new_exc), file=sys.stderr)
    raise new_exc from exc


__all__ = ["GateLockTimeoutError"]
