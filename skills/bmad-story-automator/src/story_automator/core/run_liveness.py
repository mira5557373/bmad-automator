"""Heartbeat-based liveness for the active-run marker.

The active marker records ``pid "$$"`` — a *transient per-step shell*, not a
long-lived orchestrator process — so ``pid`` cannot be used as a liveness
signal (the shell that wrote it has usually already exited by the time anyone
inspects the marker). Per the documented contract (``marker-file-format.md``:
"Staleness threshold: 30 minutes"), the authoritative crash signal is the
``heartbeat`` timestamp, which the running orchestration loop refreshes well
within the window. A run whose heartbeat has not advanced within
``STALE_AFTER_SECONDS`` is treated as crashed/abandoned.

Two intentionally non-complementary predicates back the two call sites:

- ``run_is_live`` is used by ``marker create`` to refuse double-orchestration —
  it returns True only when a heartbeat is *provably fresh*, so a corrupt or
  timestamp-less marker never permanently blocks a new run.
- ``run_is_stale`` is used by the stop hook to release a crashed orchestrator —
  it returns True only when a heartbeat is *provably old*, so a malformed marker
  never causes a healthy run to be prematurely stopped.

Both fail safe: when the age cannot be determined, each returns False.
"""

from __future__ import annotations

import time
from typing import Any

from .atomic_io import parse_iso_seconds

# 30 minutes, matching the documented marker staleness threshold.
STALE_AFTER_SECONDS = 1800


def heartbeat_age_seconds(payload: Any, now: float | None = None) -> float | None:
    """Seconds since the marker's last heartbeat, or ``None`` if undeterminable.

    Falls back to ``createdAt``/``startedAt`` when ``heartbeat`` is absent.
    Returns ``None`` on a non-dict payload, a missing stamp, or an unparseable
    timestamp (``parse_iso_seconds`` raises ``ValueError`` on a malformed value),
    so callers apply their own safe default rather than trusting a phantom age.
    """
    if not isinstance(payload, dict):
        return None
    stamp = payload.get("heartbeat") or payload.get("createdAt") or payload.get("startedAt")
    if not stamp:
        return None
    now = time.time() if now is None else now
    try:
        return now - parse_iso_seconds(str(stamp))
    except (ValueError, TypeError):
        return None


def run_is_stale(payload: Any, now: float | None = None) -> bool:
    """True only when the run's heartbeat is provably older than the window."""
    age = heartbeat_age_seconds(payload, now)
    return age is not None and age > STALE_AFTER_SECONDS


def run_is_live(payload: Any, now: float | None = None) -> bool:
    """True only when the run's heartbeat is provably within the window."""
    age = heartbeat_age_seconds(payload, now)
    return age is not None and age <= STALE_AFTER_SECONDS


__all__ = ["STALE_AFTER_SECONDS", "heartbeat_age_seconds", "run_is_stale", "run_is_live"]
