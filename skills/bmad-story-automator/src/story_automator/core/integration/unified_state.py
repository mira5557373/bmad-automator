"""G7 — unified read/write surface for the sprint-status / Phase dual store.

This module is the single source of truth that callers should use whenever
they want both halves of M48's dual store treated as one atomic value:

* :func:`read_unified_state` returns
  ``(sprint_status, phase_value, needs_repair)`` for one story key. The
  read path is lock-free in the steady-state happy case (both stores
  present and consistent). When the two stores disagree (mtime conflict)
  or the legacy phase store is empty (single-store migration), the reader
  takes the per-project filelock just long enough to materialise /
  project the missing side, then returns.
* :func:`write_unified_state` writes both stores atomically under a
  single per-project filelock, in **phase-first → sprint-status-second**
  order so a crash between the two writes always leaves a recoverable
  state: the next reader sees a phase-newer-than-sprint conflict,
  last-write-wins resolves to the phase side, and the projection
  re-aligns sprint-status.
* :func:`unified_state_lock` exposes the underlying
  :class:`filelock.FileLock` for advanced callers that need to bracket a
  multi-row update.

Conflict resolution
-------------------

When both files exist on disk but disagree, the resolver picks the winner
by ``st_mtime_ns``; on mtime ties (common on coarse-granular filesystems
and on ``os.utime`` re-stamps), the entry whose status maps to
:data:`TERMINAL_PHASES` wins (terminal phase is semantically "more
recent"); if neither or both are terminal, the phase store wins.

The same-volume precondition (``st_dev`` equality) runs ONLY inside the
LWW resolver — the migration path (phase store absent) skips it because
``Path.stat()`` would raise ``FileNotFoundError`` before the LWW check
could fire.

Read-order ↔ write-order (three modes, gap D-R-03)
--------------------------------------------------

* **Steady-state read** — reader reads sprint-status first, phase second
  (REVERSE of the writer's order); the reverse pairing guarantees a
  reader observing the new sprint-status also sees the new phase store.
* **Steady-state write** — writer writes phase first, sprint-status
  second (forward).
* **Migration write from inside read** — phase-only single-store
  mutation; ordering immaterial because no second file is touched.

Concurrency model
-----------------

Readers do not take the lock by default. To bound the writer-between-stats
race, ``read_unified_state`` uses a stat-twice-or-retry pattern (cap 3
attempts); on the third failure it acquires the lock briefly with
``read_lock_timeout`` (default 2.0 s, distinct from the writer's 10.0 s
``lock_timeout``). On read-lock-timeout the reader returns its best-effort
current pair with ``needs_repair=True`` rather than blocking indefinitely.

The reader's repair path uses a self-cancellation guard (gap D-R-09): the
resolver RE-reads both files under the lock and only projects if the
locked re-read still shows a conflict with the same winner.

The ``observe_only=True`` kwarg disables every write side-effect; the
function returns the same monomorphic 3-tuple shape and sets
``needs_repair=True`` whenever the on-disk state was divergent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

import filelock

from ..artifact_paths import implementation_artifacts_dir, sprint_status_path
from ..sprint import sprint_status_get
from ..utils import file_exists, read_text, write_atomic
from . import _unified_state_repair as _repair
from .sprint_phase_map import (
    Phase,
    is_consistent,
    phase_for_sprint_status,
    phase_store_path,
    read_phase_store,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UnifiedStateError(ValueError):
    """Raised when a unified-state operation cannot proceed safely.

    Sits side-by-side with M48's :class:`DualStoreError` — NOT a subclass.
    G7 is a layer on top of M48, not a fork of it.
    """


class UnifiedStateFileMissingError(UnifiedStateError):
    """Sprint-status YAML or phase-store YAML does not exist on disk."""


class UnifiedStateRowMissingError(UnifiedStateError):
    """The file exists but the requested story row is absent."""


# ---------------------------------------------------------------------------
# Lock helper
# ---------------------------------------------------------------------------


def _lock_path(project_root: str | Path) -> Path:
    return implementation_artifacts_dir(project_root) / ".unified-state.lock"


def unified_state_lock(project_root: str | Path) -> filelock.FileLock:
    """Return the :class:`filelock.FileLock` for the project's unified state.

    Lock file lives at ``<implementation_artifacts_dir>/.unified-state.lock``;
    created on first acquisition, never deleted. Advanced callers may
    bracket multi-row updates with ``with unified_state_lock(root): ...``.
    """

    lock_file = _lock_path(project_root)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    return filelock.FileLock(str(lock_file))


# ---------------------------------------------------------------------------
# Sprint-status row writer (the first sprint-status writer in the codebase)
# ---------------------------------------------------------------------------


def _row_pattern(key: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?m)^(\s*){re.escape(key)}(\s*:\s*)(\S+)(\s*(?:#.*)?)$"
    )


def _write_sprint_status_row(
    project_root: str | Path, story_key: str, new_status: str
) -> None:
    """Mutate exactly one row in sprint-status.yaml — gap D01.

    Contract:

    * Preserve all non-target lines byte-exact (comments, ordering,
      trailing whitespace, file's trailing newline).
    * Preserve the trailing comment / whitespace on the target row.
    * No YAML round-trip — text-only regex mutation.
    * Round-trip-verify via :func:`sprint_status_get` after the write.
    * Caller already holds the unified-state filelock — do NOT
      re-acquire.
    * Raise :class:`UnifiedStateFileMissingError` if the file is absent.
    * Raise :class:`UnifiedStateRowMissingError` if the row is absent.
    """

    path = Path(sprint_status_path(project_root))
    if not file_exists(path):
        raise UnifiedStateFileMissingError(
            f"sprint-status.yaml not found at {path}"
        )
    content = read_text(path)
    matched_key: str | None = None
    if _row_pattern(story_key).search(content):
        matched_key = story_key
    else:
        # The on-disk row may be keyed by the slug — defer to the canonical
        # resolver to find the matching row.
        probe = sprint_status_get(str(project_root), story_key)
        if probe.found and probe.story and _row_pattern(probe.story).search(content):
            matched_key = probe.story
    if matched_key is None:
        raise UnifiedStateRowMissingError(
            f"sprint-status row for {story_key!r} not found"
        )
    pattern = _row_pattern(matched_key)

    def _sub(match: re.Match[str]) -> str:
        indent, sep, _old_status, trailing = match.groups()
        return f"{indent}{matched_key}{sep}{new_status}{trailing}"

    new_content, count = pattern.subn(_sub, content, count=1)
    if count != 1:
        raise UnifiedStateRowMissingError(
            f"sprint-status row for {matched_key!r} unexpectedly absent during mutation"
        )
    write_atomic(path, new_content)
    after = sprint_status_get(str(project_root), story_key)
    if after.status != new_status:
        raise UnifiedStateError(
            f"sprint-status round-trip mismatch: wrote {new_status!r}, read {after.status!r}"
        )


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


def read_unified_state(
    project_root: str | Path,
    story_key: str,
    *,
    observe_only: bool = False,
    read_lock_timeout: float = 2.0,
) -> Tuple[str, str, bool]:
    """Read the unified ``(sprint_status, phase_value, needs_repair)`` triple.

    Monomorphic 3-tuple return shape (gap D-R-01) — the ``observe_only``
    flag only controls whether writes happen on the repair path, NOT the
    return arity.

    .. warning::
       Calling this function with the default ``observe_only=False`` may
       write to disk (legacy migration and LWW conflict repair). Pass
       ``observe_only=True`` for read-only callers (forensic / audit /
       snapshot tooling).
    """

    sprint_path = Path(sprint_status_path(project_root))
    phase_path = phase_store_path(project_root)

    # STEADY-STATE READ — sprint-status first, phase second (REVERSE of
    # the writer's phase-first → sprint-second order; gap D-R-03 mode (a)).
    attempts = 0
    while True:
        attempts += 1
        sprint_mtime = _repair.safe_mtime_ns(sprint_path)
        phase_mtime = _repair.safe_mtime_ns(phase_path)
        sprint_state = sprint_status_get(str(project_root), story_key)
        phase_store = read_phase_store(project_root)
        sprint_mtime_after = _repair.safe_mtime_ns(sprint_path)
        phase_mtime_after = _repair.safe_mtime_ns(phase_path)
        stale = (
            sprint_mtime_after != sprint_mtime
            or phase_mtime_after != phase_mtime
        )
        if not stale:
            break
        if attempts >= 3:
            # Escalate to brief locked snapshot under read_lock_timeout
            # (gap D-R-04). Best-effort on lock-timeout.
            lock = unified_state_lock(project_root)
            try:
                lock.acquire(timeout=read_lock_timeout)
            except filelock.Timeout:
                return _best_effort_tuple(
                    sprint_state, phase_store, story_key, divergent=True
                )
            try:
                sprint_state = sprint_status_get(str(project_root), story_key)
                phase_store = read_phase_store(project_root)
            finally:
                lock.release()
            break

    if not sprint_state.found:
        if not file_exists(sprint_path):
            raise UnifiedStateFileMissingError(
                f"sprint-status.yaml not found at {sprint_path}"
            )
        raise UnifiedStateRowMissingError(
            f"sprint-status row for {story_key!r} not found"
        )

    stored_phase = phase_store.get(sprint_state.story) or phase_store.get(story_key)

    if stored_phase is not None:
        if is_consistent(sprint_state.status, stored_phase):
            # Steady-state happy path — no lock taken.
            return (sprint_state.status, stored_phase.value, False)
        # Conflict — dispatch to LWW resolver (both files exist).
        return _repair.resolve_lww_under_lock(
            project_root,
            story_key,
            observe_only=observe_only,
            lock_timeout=read_lock_timeout,
        )

    # Phase entry missing — MIGRATION WRITE (gap D-R-03 mode (c):
    # single-store mutation, ordering immaterial). Same-volume precondition
    # is intentionally SKIPPED here — phase store does not exist on disk.
    derived = phase_for_sprint_status(sprint_state.status)
    if derived is None:
        # Unknown sprint-status — return (status, "pending", True) without
        # writing; surfacing the misspelling lets the operator fix it.
        return (sprint_state.status, "pending", True)

    if observe_only:
        # Read-only: derived pair with needs_repair=True (gap D-R-05).
        return (sprint_state.status, derived.value, True)

    lock = unified_state_lock(project_root)
    try:
        lock.acquire(timeout=read_lock_timeout)
    except filelock.Timeout:
        return (sprint_state.status, derived.value, True)
    try:
        # Re-check under the lock — another reader may have materialised.
        phase_store_now = read_phase_store(project_root)
        existing = phase_store_now.get(sprint_state.story) or phase_store_now.get(
            story_key
        )
        if existing is not None:
            return (sprint_state.status, existing.value, False)
        canonical = _repair.canonical_key(project_root, story_key)
        _repair.rewrite_phase_with_canonical(project_root, canonical, derived)
    finally:
        lock.release()
    return (sprint_state.status, derived.value, False)


def _best_effort_tuple(
    sprint_state, phase_store, story_key: str, *, divergent: bool
) -> Tuple[str, str, bool]:
    if not sprint_state.found:
        return ("not_found", "pending", True)
    stored = phase_store.get(sprint_state.story) or phase_store.get(story_key)
    if stored is None:
        derived = phase_for_sprint_status(sprint_state.status)
        if derived is None:
            return (sprint_state.status, "pending", True)
        return (sprint_state.status, derived.value, True)
    return (sprint_state.status, stored.value, divergent)


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------


def write_unified_state(
    project_root: str | Path,
    story_key: str,
    sprint_status: str,
    phase: Phase | str,
    *,
    lock_timeout: float = 10.0,
) -> None:
    """Atomically write ``(sprint_status, phase)`` to both stores.

    Acquires :func:`unified_state_lock` for the duration. Writes the phase
    store FIRST, sprint-status SECOND (steady-state write order — gap
    D-R-03 mode (b)). A crash between the two writes leaves a recoverable
    state — the next reader sees a phase-newer-than-sprint conflict and
    LWW repairs sprint-status.

    Args:
        project_root: project root path.
        story_key: any shape accepted by :func:`normalize_story_key`;
            stored under the canonical dotted id (gap D-R-07).
        sprint_status: the sprint-status string (e.g. ``"in-progress"``).
        phase: :class:`Phase` member or its kebab-case string value.
        lock_timeout: filelock timeout in seconds (default 10.0).

    Raises:
        UnifiedStateError: on inconsistent pair, unrecognisable
            ``story_key``, lock timeout, cross-filesystem mismatch, or
            sprint-status round-trip mismatch.
    """

    if isinstance(phase, Phase):
        phase_member = phase
    elif isinstance(phase, str):
        try:
            phase_member = Phase(phase.strip())
        except ValueError as exc:
            raise UnifiedStateError(f"unknown phase: {phase!r}") from exc
    else:
        raise UnifiedStateError(
            f"phase must be Phase or str, got {type(phase).__name__}"
        )

    if not is_consistent(sprint_status, phase_member):
        raise UnifiedStateError(
            f"inconsistent pair: sprint_status={sprint_status!r}, "
            f"phase={phase_member.value!r}"
        )

    canonical = _repair.canonical_key(project_root, story_key)

    lock = unified_state_lock(project_root)
    try:
        lock.acquire(timeout=lock_timeout)
    except filelock.Timeout as exc:
        raise UnifiedStateError(
            f"unified-state lock timeout={lock_timeout}s for story_key={story_key!r}"
        ) from exc
    try:
        # STEADY-STATE WRITE — phase first (gap D-R-03 mode (b)).
        _repair.rewrite_phase_with_canonical(project_root, canonical, phase_member)
        # STEADY-STATE WRITE — sprint-status second (gap D-R-03 mode (b)).
        _write_sprint_status_row(project_root, story_key, sprint_status)
    finally:
        lock.release()


__all__ = [
    "UnifiedStateError",
    "UnifiedStateFileMissingError",
    "UnifiedStateRowMissingError",
    "read_unified_state",
    "unified_state_lock",
    "write_unified_state",
]
