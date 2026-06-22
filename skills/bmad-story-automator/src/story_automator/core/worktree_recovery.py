"""Orphan-worktree recovery — Phase 2 cleanup helper.

A collector run creates a detached worktree under ``/tmp/sa-collector-*``
via :mod:`collector_checkout`. If the orchestrator process is SIGKILL'd
between ``git worktree add`` and the context-manager's cleanup, the
worktree stays registered in ``.git/worktrees/`` AND its scratch dir
lingers in ``/tmp``. Across many crashes the orphan set grows and
``git worktree add`` starts colliding on stale references.

This module provides a single entry point — :func:`recover_orphan_worktrees`
— that the orchestrator can call at startup (alongside
``recover_from_crash``) to:

  1. Run ``git worktree prune`` so the registry is consistent.
  2. Best-effort delete any ``/tmp/sa-collector-*`` scratch dir whose
     mtime is older than ``min_age_s`` (default 1 h) AND whose path
     is no longer present in the registry.

Both steps are read/write but idempotent — running them on a clean
repo is a no-op.

Determinism: the returned descriptor does NOT contain timestamps;
only counts + the list of removed paths. Safe to log.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .audit import scrub_env_for_subprocess

_PRUNE_TIMEOUT_S = 30
_LIST_TIMEOUT_S = 15

# Prefix used by collector_checkout.create_collector_checkout when it
# tempfile.mkdtemp()s a scratch dir. If that constant changes, update
# this — we keep it as a local literal for now since they're created
# under tempfile.gettempdir() and we don't want a cross-module import.
_COLLECTOR_PREFIX = "sa-collector-"


def _registered_worktrees(project_root: str | Path) -> set[str]:
    """Absolute paths of every registered worktree in this repo.

    Uses ``git worktree list --porcelain``. Returns an empty set on
    error (we don't want a stat failure to block recovery).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=_LIST_TIMEOUT_S,
            env=scrub_env_for_subprocess(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()
    if result.returncode != 0:
        return set()
    paths: set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            paths.add(line[len("worktree "):].strip())
    return paths


def _prune_registry(project_root: str | Path) -> bool:
    """Run ``git worktree prune``. Returns True on success."""
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "worktree", "prune"],
            capture_output=True,
            timeout=_PRUNE_TIMEOUT_S,
            env=scrub_env_for_subprocess(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def _scratch_candidates() -> list[Path]:
    """All ``/tmp/sa-collector-*`` directories currently on disk."""
    tmp_root = Path(tempfile.gettempdir())
    if not tmp_root.is_dir():
        return []
    try:
        return [
            p for p in tmp_root.iterdir()
            if p.name.startswith(_COLLECTOR_PREFIX) and p.is_dir()
        ]
    except OSError:
        return []


def recover_orphan_worktrees(
    project_root: str | Path,
    *,
    min_age_s: float = 3600.0,
    now: float | None = None,
) -> dict[str, Any]:
    """Clean up orphaned collector worktrees + their scratch dirs.

    Parameters:
        project_root: repo root containing ``.git/``.
        min_age_s: minimum age (seconds) a scratch dir must have
            before it is eligible for deletion. Defaults to 1 hour;
            this protects an in-flight collector that hasn't yet
            registered with ``git worktree add``.
        now: injected current time (for tests). When ``None``, we
            call ``time.time()`` once at the start. Determinism in
            the returned descriptor is preserved either way — we do
            NOT include ``now`` in the payload.

    Returns:
        A descriptor of what was done::

            {
                "pruned": True,           # git worktree prune ran
                "registered_paths": int,  # surviving worktrees post-prune
                "scratch_removed": [str], # /tmp paths we deleted
                "scratch_kept": [str],    # /tmp paths we left alone
            }
    """
    root = Path(project_root)
    cutoff = (time.time() if now is None else now) - min_age_s

    pruned = _prune_registry(root)
    registered = _registered_worktrees(root)
    # Normalize paths so `/tmp/x` and `/private/tmp/x` (macOS) match.
    registered_resolved = {str(Path(p).resolve()) for p in registered}

    removed: list[str] = []
    kept: list[str] = []
    for candidate in _scratch_candidates():
        candidate_resolved = str(candidate.resolve())
        if candidate_resolved in registered_resolved:
            # Active worktree — never touch.
            kept.append(candidate_resolved)
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            kept.append(candidate_resolved)
            continue
        if mtime > cutoff:
            kept.append(candidate_resolved)
            continue
        try:
            shutil.rmtree(candidate, ignore_errors=False)
            removed.append(candidate_resolved)
        except OSError:
            # Permission denied or busy — leave it alone, surface as kept.
            kept.append(candidate_resolved)

    return {
        "pruned": pruned,
        "registered_paths": len(registered_resolved),
        "scratch_removed": sorted(removed),
        "scratch_kept": sorted(kept),
    }


def list_orphan_candidates(
    project_root: str | Path,
    *,
    min_age_s: float = 3600.0,
    now: float | None = None,
) -> list[str]:
    """Dry-run helper — return paths :func:`recover_orphan_worktrees`
    WOULD delete without actually deleting. Useful for tooling +
    operator-facing status output.
    """
    root = Path(project_root)
    cutoff = (time.time() if now is None else now) - min_age_s
    registered = _registered_worktrees(root)
    registered_resolved = {str(Path(p).resolve()) for p in registered}
    candidates: list[str] = []
    for cand in _scratch_candidates():
        cr = str(cand.resolve())
        if cr in registered_resolved:
            continue
        try:
            mtime = cand.stat().st_mtime
        except OSError:
            continue
        if mtime <= cutoff:
            candidates.append(cr)
    return sorted(candidates)
