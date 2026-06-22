"""Private repair helpers for :mod:`unified_state` (pre-authorized split).

Hosts the LWW conflict resolver, the canonical-key reconciliation
helpers, and the stat-twice escalation primitives. Kept as a sibling
private module so the public-surface module (``unified_state.py``)
stays comfortably under the 500-LOC soft limit while the docstrings
that explain the conflict-resolution semantics keep their full depth.

Nothing in this module is part of the public surface (no ``__all__``).
Imports must come exclusively through ``unified_state.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import filelock

from ..artifact_paths import sprint_status_path
from ..sprint import sprint_status_get
from ..story_keys import normalize_story_key
from ..utils import write_atomic
from .sprint_phase_map import (
    Phase,
    TERMINAL_PHASES,
    is_consistent,
    phase_for_sprint_status,
    phase_store_path,
    read_phase_store,
    sprint_status_for_phase,
)


def safe_mtime_ns(path: Path) -> int:
    """Return ``path.stat().st_mtime_ns`` or ``-1`` for missing files."""

    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return -1


def lww_winner(sprint_stat, phase_stat, sprint_status_str: str, stored_phase: Phase) -> str:
    """Return ``"phase"`` or ``"sprint"`` — whichever wins LWW.

    Tie-break (gap D08): on equal ``st_mtime_ns``, the entry whose
    status / phase is terminal (in :data:`TERMINAL_PHASES`) wins; if
    neither or both are terminal, phase store wins (legacy default).
    """

    s_ns = sprint_stat.st_mtime_ns
    p_ns = phase_stat.st_mtime_ns
    if p_ns > s_ns:
        return "phase"
    if s_ns > p_ns:
        return "sprint"
    derived_sprint = phase_for_sprint_status(sprint_status_str)
    sprint_terminal = derived_sprint in TERMINAL_PHASES if derived_sprint else False
    phase_terminal = stored_phase in TERMINAL_PHASES
    if phase_terminal and not sprint_terminal:
        return "phase"
    if sprint_terminal and not phase_terminal:
        return "sprint"
    return "phase"


def canonical_key(project_root: str | Path, story_key: str) -> str:
    """Resolve ``story_key`` to its canonical dotted form via
    :func:`normalize_story_key` (gap D-R-07: NOT via
    ``SprintStatus.story``, which returns the matched-row key — possibly
    the slug — and would persist the slug, the inverse of intended
    reconciliation).
    """

    from .unified_state import UnifiedStateError

    canonical = normalize_story_key(str(project_root), story_key)
    if canonical is None:
        raise UnifiedStateError(f"unrecognisable story_key: {story_key!r}")
    return canonical.id


def rewrite_phase_with_canonical(
    project_root: str | Path, canonical: str, phase: Phase
) -> None:
    """Write ``{canonical: phase}`` and delete slug-keyed orphans.

    For every existing phase-store key whose canonical id equals
    ``canonical`` AND whose literal value differs from ``canonical``, the
    entry is dropped (slug-keyed orphan removal — gap D10).
    """

    existing = read_phase_store(project_root)
    cleaned: dict[str, Phase] = {}
    for key, value in existing.items():
        norm = normalize_story_key(str(project_root), key)
        if norm is not None and norm.id == canonical and key != canonical:
            continue
        cleaned[key] = value
    cleaned[canonical] = phase
    persist_phase_store(project_root, cleaned)


def persist_phase_store(project_root: str | Path, entries: dict[str, Phase]) -> None:
    """Persist ``entries`` to the phase store via :func:`write_atomic`.

    Re-implements M48's private ``_write_phase_store`` body — calling
    M48's private symbol would couple G7 to a non-frozen surface.
    """

    path = phase_store_path(project_root)
    lines = [f"{key}: {entries[key].value}" for key in sorted(entries)]
    body = "\n".join(lines) + ("\n" if lines else "")
    write_atomic(path, body)


def project_lww_pair_observe_only(
    project_root: str | Path, story_key: str, sprint_stat, phase_stat
) -> Tuple[str, str, bool]:
    """Compute the LWW-projected pair without writing (observe_only path).

    The on-disk state is divergent; the function never writes but the
    caller wants to know which value WOULD have won had repair fired.
    """

    sprint_state = sprint_status_get(str(project_root), story_key)
    phase_store = read_phase_store(project_root)
    stored_phase = phase_store.get(sprint_state.story) or phase_store.get(story_key)
    if not sprint_state.found:
        return ("not_found", "pending", True)
    if stored_phase is None:
        return (sprint_state.status, "pending", True)
    winner = lww_winner(sprint_stat, phase_stat, sprint_state.status, stored_phase)
    if winner == "phase":
        return (sprint_status_for_phase(stored_phase), stored_phase.value, True)
    derived = phase_for_sprint_status(sprint_state.status)
    if derived is None:
        return (sprint_state.status, stored_phase.value, True)
    return (sprint_state.status, derived.value, True)


def resolve_lww_under_lock(
    project_root: str | Path,
    story_key: str,
    *,
    observe_only: bool,
    lock_timeout: float,
) -> Tuple[str, str, bool]:
    """Acquire the unified-state lock and project the LWW loser.

    Self-cancellation guard (gap D-R-09): re-reads both files under the
    lock and re-runs the conflict check; projection fires ONLY if the
    locked re-read still shows a conflict with the same winner.
    """

    from .unified_state import (
        UnifiedStateError,
        UnifiedStateRowMissingError,
        _write_sprint_status_row,
        unified_state_lock,
    )

    sprint_path = Path(sprint_status_path(project_root))
    phase_path = phase_store_path(project_root)

    sprint_stat = sprint_path.stat()
    phase_stat = phase_path.stat()
    if sprint_stat.st_dev != phase_stat.st_dev:
        raise UnifiedStateError(
            "cross-filesystem unified state not supported; "
            "phase store and sprint-status must share a volume"
        )

    if observe_only:
        return project_lww_pair_observe_only(
            project_root, story_key, sprint_stat, phase_stat
        )

    lock = unified_state_lock(project_root)
    try:
        lock.acquire(timeout=lock_timeout)
    except filelock.Timeout as exc:
        raise UnifiedStateError(
            f"unified-state lock timeout={lock_timeout}s during LWW repair"
        ) from exc
    try:
        sprint_state = sprint_status_get(str(project_root), story_key)
        phase_store = read_phase_store(project_root)
        if not sprint_state.found:
            raise UnifiedStateRowMissingError(
                f"sprint-status row for {story_key!r} not found"
            )
        stored_phase = phase_store.get(sprint_state.story) or phase_store.get(
            story_key
        )
        if stored_phase is None:
            derived = phase_for_sprint_status(sprint_state.status)
            if derived is None:
                return (sprint_state.status, "pending", True)
            return (sprint_state.status, derived.value, False)
        if is_consistent(sprint_state.status, stored_phase):
            return (sprint_state.status, stored_phase.value, False)

        sprint_stat = sprint_path.stat()
        phase_stat = phase_path.stat()
        winner = lww_winner(
            sprint_stat, phase_stat, sprint_state.status, stored_phase
        )
        if winner == "phase":
            projected_status = sprint_status_for_phase(stored_phase)
            _write_sprint_status_row(project_root, story_key, projected_status)
            return (projected_status, stored_phase.value, False)
        derived = phase_for_sprint_status(sprint_state.status)
        if derived is None:
            return (sprint_state.status, stored_phase.value, True)
        ck = canonical_key(project_root, story_key)
        rewrite_phase_with_canonical(project_root, ck, derived)
        return (sprint_state.status, derived.value, False)
    finally:
        lock.release()
