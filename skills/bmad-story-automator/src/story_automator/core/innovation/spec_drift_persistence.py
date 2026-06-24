"""Disk-persistence helpers for :class:`SpecDriftWatcher` (C1 follow-up).

The MVP ``SpecDriftWatcher`` lives entirely in memory; this sibling
module adds the optional disk persistence layer wired in via the
``persistence_key`` kwarg on the watcher. Storing the watcher state on
disk lets a future orchestrator resume mid-session drift detection
across process restarts and emit a complete drift event-log for audit.

Layout under ``<project_root>/_bmad/drift/<persistence_key>/``:

* ``baseline.json`` — compact JSON (deterministic insertion-ordered
  field shape, NOT the project's ``gate_schema.canonical_json``
  ``sort_keys=True`` flavor — drift is advisory telemetry, not part of
  the audit hash chain) serialization of the ``SpecDriftSnapshot``
  baseline. Written atomically via ``core.atomic_io.write_atomic_text``;
  readers tolerate a missing file and return ``None`` so the watcher's
  first ``poll()`` can establish the baseline.
* ``events.jsonl`` — append-only JSON-Lines log of every
  ``SpecDriftEvent`` returned by ``poll()``. Each line is one event so
  a corrupted line bounds the blast radius to that line alone (the
  read helper is intentionally permissive).
* ``.drift.lock`` — ``filelock`` sidecar that serializes
  baseline-write + event-append across processes. 30-second timeout
  matches the convention used elsewhere in the gate stack.

The module is split out of ``spec_drift_watcher.py`` (which sat at 461
LOC after the MVP) to keep the 500-LOC soft limit in play. There is no
HMAC chain — drift is advisory telemetry, not an audit-grade chain;
the existing gate-audit chain remains the source of truth for
auditable events.

Stdlib + ``filelock`` only — honors the project's hard dep guardrail.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout

from story_automator.core.atomic_io import write_atomic_text
from story_automator.core.common import compact_json

if TYPE_CHECKING:
    from story_automator.core.innovation.spec_drift_watcher import (
        SpecDriftEvent,
        SpecDriftSnapshot,
    )

__all__ = [
    "DRIFT_LOCK_TIMEOUT_S",
    "append_drift_event",
    "baseline_path",
    "drift_root_dir",
    "events_path",
    "load_baseline",
    "persist_baseline",
    "validate_persistence_key",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


DRIFT_LOCK_TIMEOUT_S: float = 30.0
"""Per-key filelock timeout in seconds.

30s comfortably absorbs any realistic baseline-write or event-append
contention while still failing fast on a wedged holder. Other stack
modules use the same 30s convention for short-lived metadata locks."""


_PERSISTENCE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*\Z")

_PERSISTENCE_KEY_MAX_LEN: int = 64
"""Upper bound on persistence-key length in characters.

POSIX caps a single path component at 255 bytes (Linux ext4, tmpfs,
etc.); 64 sits comfortably under that ceiling while leaving headroom
for the surrounding ``_bmad/drift/<key>/`` layout and any future
sidecar suffixes. Without this bound an over-long key would silently
pass regex validation and then surface as a raw ``OSError(ENAMETOOLONG)``
out of :func:`drift_root_dir` — bypassing the module's own
SpecDriftError-wrapping convention and breaking the docstring promise
that the resulting directory is "well-formed on every supported FS"."""


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_persistence_key(key: str) -> None:
    """Reject persistence keys that could escape the drift root.

    The key becomes a directory name under ``_bmad/drift/``, so any
    path separator, dot, or whitespace would be either a path traversal
    risk (``../etc``) or a name that breaks the layout invariant
    (``foo/bar`` accidentally nests). We allow only ASCII alphanumeric
    plus ``-`` and ``_`` and require a non-symbol first character so
    the resulting directory is well-formed on every supported FS. The
    length is capped at :data:`_PERSISTENCE_KEY_MAX_LEN` so an
    over-long key fails fast as ``SpecDriftError`` rather than leaking
    a raw ``OSError(ENAMETOOLONG)`` from ``Path.mkdir`` downstream.
    """
    # Local import keeps the module-load graph cheap and avoids a
    # circular import: spec_drift_watcher imports this module.
    from story_automator.core.innovation.spec_drift_watcher import (
        SpecDriftError,
    )
    if not isinstance(key, str) or not _PERSISTENCE_KEY_RE.match(key):
        raise SpecDriftError(
            f"invalid persistence_key {key!r}: must match "
            f"[A-Za-z0-9][A-Za-z0-9_-]*"
        )
    if len(key) > _PERSISTENCE_KEY_MAX_LEN:
        raise SpecDriftError(
            f"invalid persistence_key (length {len(key)} > "
            f"{_PERSISTENCE_KEY_MAX_LEN}): keep keys short so the "
            f"_bmad/drift/<key>/ directory stays within FS limits"
        )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def drift_root_dir(
    project_root: Path | str,
    persistence_key: str,
    *,
    create: bool = False,
) -> Path:
    """Return ``<project_root>/_bmad/drift/<key>/``.

    ``create=True`` lazily makes the directory (parents=True). The
    caller is responsible for validating ``persistence_key`` first via
    :func:`validate_persistence_key`; this helper does not re-validate
    so callers that already validated avoid the double check.
    """
    root = Path(project_root) / "_bmad" / "drift" / persistence_key
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def baseline_path(project_root: Path | str, persistence_key: str) -> Path:
    """Path of the persisted ``baseline.json`` for ``persistence_key``."""
    return drift_root_dir(project_root, persistence_key) / "baseline.json"


def events_path(project_root: Path | str, persistence_key: str) -> Path:
    """Path of the append-only ``events.jsonl`` event log."""
    return drift_root_dir(project_root, persistence_key) / "events.jsonl"


def _lock_path(project_root: Path | str, persistence_key: str) -> Path:
    return drift_root_dir(project_root, persistence_key) / ".drift.lock"


# ---------------------------------------------------------------------------
# Baseline persistence
# ---------------------------------------------------------------------------


def _snapshot_to_dict(snap: "SpecDriftSnapshot") -> dict:
    """Stable serialization shape — keep field order fixed for diff sanity."""
    return {
        "score": snap.score,
        "requirements_total": snap.requirements_total,
        "requirements_satisfied": snap.requirements_satisfied,
        "timestamp_iso": snap.timestamp_iso,
    }


def _dict_to_snapshot(data: dict) -> "SpecDriftSnapshot":
    # Local import avoids the circular at module-load time.
    from story_automator.core.innovation.spec_drift_watcher import (
        SpecDriftSnapshot,
    )
    return SpecDriftSnapshot(
        score=float(data["score"]),
        requirements_total=int(data["requirements_total"]),
        requirements_satisfied=int(data["requirements_satisfied"]),
        timestamp_iso=str(data["timestamp_iso"]),
    )


def persist_baseline(
    project_root: Path | str,
    persistence_key: str,
    snapshot: "SpecDriftSnapshot",
) -> Path:
    """Atomically write ``snapshot`` to ``baseline.json``.

    The directory is created lazily; the write itself is coordinated
    with ``events.jsonl`` appends via the per-key filelock so a
    concurrent reader can never observe a partial baseline.
    """
    validate_persistence_key(persistence_key)
    drift_root_dir(project_root, persistence_key, create=True)
    target = baseline_path(project_root, persistence_key)
    lock = FileLock(str(_lock_path(project_root, persistence_key)))
    try:
        lock.acquire(timeout=DRIFT_LOCK_TIMEOUT_S)
    except Timeout as err:
        from story_automator.core.innovation.spec_drift_watcher import (
            SpecDriftError,
        )
        raise SpecDriftError(
            f"timeout acquiring drift lock for {persistence_key!r}"
        ) from err
    try:
        write_atomic_text(target, compact_json(_snapshot_to_dict(snapshot)))
    finally:
        lock.release()
    return target


def load_baseline(
    project_root: Path | str,
    persistence_key: str,
) -> "SpecDriftSnapshot | None":
    """Load the persisted baseline; return ``None`` on absence.

    The reader intentionally tolerates a missing file (``None``) so
    the watcher's first ``poll()`` can establish a fresh baseline on
    a clean ``_bmad/`` tree. Corrupt JSON raises ``SpecDriftError`` so
    silent data loss surfaces loudly.
    """
    validate_persistence_key(persistence_key)
    path = baseline_path(project_root, persistence_key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        return _dict_to_snapshot(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as err:
        from story_automator.core.innovation.spec_drift_watcher import (
            SpecDriftError,
        )
        raise SpecDriftError(
            f"corrupt baseline at {path}: {err!r}"
        ) from err


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------


def _event_to_dict(event: "SpecDriftEvent") -> dict:
    """Stable JSON shape for one event-log line."""
    return {
        "baseline_score": event.baseline_score,
        "current_score": event.current_score,
        "delta": event.delta,
        "severity": event.severity,
        "requirements_lost": list(event.requirements_lost),
        "timestamp_iso": event.timestamp_iso,
    }


def append_drift_event(
    project_root: Path | str,
    persistence_key: str,
    event: "SpecDriftEvent",
) -> Path:
    """Append one event as a single JSONL line, with fsync.

    Append-then-fsync is a deliberately simple write pattern: each
    line is small (a few hundred bytes) so a torn write is extremely
    unlikely on a POSIX FS, and the filelock keeps writes
    non-interleaved. We do NOT chain lines with an HMAC — drift is
    advisory; the gate audit chain remains the auditable source of
    truth.
    """
    validate_persistence_key(persistence_key)
    drift_root_dir(project_root, persistence_key, create=True)
    target = events_path(project_root, persistence_key)
    payload = compact_json(_event_to_dict(event)) + "\n"
    lock = FileLock(str(_lock_path(project_root, persistence_key)))
    try:
        lock.acquire(timeout=DRIFT_LOCK_TIMEOUT_S)
    except Timeout as err:
        from story_automator.core.innovation.spec_drift_watcher import (
            SpecDriftError,
        )
        raise SpecDriftError(
            f"timeout acquiring drift lock for {persistence_key!r}"
        ) from err
    try:
        fd = os.open(
            str(target),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        lock.release()
    return target
