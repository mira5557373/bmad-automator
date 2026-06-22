"""Worktree-aware baseline_commit capture (M49).

When bauto runs under ``scm.isolation=worktree``, the production-gate diff
scope is computed against the **baseline commit** — the commit from which the
worktree branch diverged from the parent branch (typically ``main``).

This module provides a minimal, pure-stdlib helper that:

* Detects whether a path is a linked git worktree (``.git`` is a file, not a
  directory — git's signal for "this is a secondary checkout sharing the
  parent's object store").
* Walks up from any sub-path to find the worktree root.
* Resolves the parent ref. An explicit override always wins; otherwise the
  first existing candidate from ``DEFAULT_PARENT_REF_CANDIDATES`` is used.
* Computes the baseline commit as ``git merge-base HEAD <parent_ref>``.
* Bundles the lot into a small metadata dict suitable for emission via the
  existing evidence_io / gate_audit layers — without importing them, so the
  module stays test-light and free of telemetry coupling.

Guardrails honoured:

* stdlib only (no ``filelock`` or ``psutil`` needed here).
* Does not import ``core/telemetry_events.py`` — pure helper.
* Single error type (``WorktreeBaselineError``) so callers can fail-closed
  without parsing free-form ``subprocess.CalledProcessError`` strings.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..audit import scrub_env_for_subprocess
from typing import Any

__all__ = [
    "DEFAULT_PARENT_REF_CANDIDATES",
    "ISOLATION_WORKTREE",
    "WorktreeBaselineError",
    "is_worktree",
    "find_worktree_root",
    "resolve_parent_ref",
    "capture_baseline_commit",
    "worktree_baseline_metadata",
]


# Order matters: first existing candidate wins. Mirrors the conventional
# default-branch fallback chain used by GitHub / GitLab tooling, with the
# trailing ``trunk`` matching some BMAD/internal repos.
DEFAULT_PARENT_REF_CANDIDATES = ("main", "master", "trunk")

ISOLATION_WORKTREE = "worktree"

# Cap subprocess calls so a wedged git invocation (file lock, hung credential
# helper) cannot stall the orchestrator indefinitely. 30s is comfortably above
# any local merge-base computation on repos this codebase targets.
_GIT_TIMEOUT_SECONDS = 30


class WorktreeBaselineError(RuntimeError):
    """Raised when a worktree baseline cannot be resolved."""


# --- Internal git plumbing ---------------------------------------------------


def _run_git(*args: str, cwd: str | Path) -> str:
    """Run a git command, returning stripped stdout.

    Raises ``WorktreeBaselineError`` on non-zero exit, timeout, or missing
    binary — never propagates ``subprocess.CalledProcessError`` directly, so
    callers can pattern-match a single exception type.
    """
    try:
        result = subprocess.run(
            ("git", *args),
            cwd=str(cwd),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=scrub_env_for_subprocess(),
        )
    except FileNotFoundError as exc:
        raise WorktreeBaselineError("git executable not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorktreeBaselineError(
            f"git {' '.join(args)} timed out after {_GIT_TIMEOUT_SECONDS}s"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise WorktreeBaselineError(
            f"git {' '.join(args)} failed (exit {exc.returncode}): {stderr}"
        ) from exc
    return result.stdout.strip()


def _ref_exists(repo_path: str | Path, ref: str) -> bool:
    """Return True if ``ref`` resolves to a commit inside ``repo_path``."""
    try:
        subprocess.run(
            ("git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"),
            cwd=str(repo_path),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=scrub_env_for_subprocess(),
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return True


# --- Detection ---------------------------------------------------------------


def is_worktree(path: str | Path) -> bool:
    """Return True if ``path`` is a *linked* git worktree.

    Git represents linked worktrees by storing a ``.git`` **file** (containing
    a ``gitdir: ...`` pointer) at the worktree root, whereas the main checkout
    has a ``.git`` directory. We rely on that signal — it is identical across
    git versions and platforms.

    Raises ``WorktreeBaselineError`` if ``path`` is not a git working tree at
    all, so callers do not have to disambiguate "not a worktree" from "not a
    git repo" via a boolean.
    """
    root = Path(path)
    if not root.exists():
        raise WorktreeBaselineError(f"path does not exist: {root}")
    try:
        toplevel = _run_git("rev-parse", "--show-toplevel", cwd=root)
    except WorktreeBaselineError as exc:
        raise WorktreeBaselineError(f"{root} is not inside a git working tree") from exc
    git_marker = Path(toplevel) / ".git"
    return git_marker.is_file()


def find_worktree_root(path: str | Path) -> Path:
    """Return the worktree root (``rev-parse --show-toplevel``) as a Path.

    Works for both the main checkout and linked worktrees — callers that
    need to distinguish should pair this with :func:`is_worktree`.
    """
    start = Path(path)
    if not start.exists():
        raise WorktreeBaselineError(f"path does not exist: {start}")
    toplevel = _run_git("rev-parse", "--show-toplevel", cwd=start)
    return Path(toplevel)


# --- Parent-ref resolution ---------------------------------------------------


def resolve_parent_ref(
    path: str | Path,
    override: str | None = None,
    candidates: tuple[str, ...] = DEFAULT_PARENT_REF_CANDIDATES,
) -> str:
    """Return the parent ref to diff a worktree against.

    Resolution order:

    1. If ``override`` is given, it must resolve to a commit inside the repo
       (otherwise ``WorktreeBaselineError`` — fail-closed, never silently
       fall back to the candidate list since that would mask operator typos).
    2. Otherwise, return the first entry of ``candidates`` that exists.
    3. If none exists, raise ``WorktreeBaselineError``.
    """
    root = Path(path)
    if override is not None:
        if not override.strip():
            raise WorktreeBaselineError("parent_ref override must not be empty")
        if not _ref_exists(root, override):
            raise WorktreeBaselineError(
                f"parent_ref override {override!r} does not exist in repo at {root}"
            )
        return override
    for candidate in candidates:
        if _ref_exists(root, candidate):
            return candidate
    raise WorktreeBaselineError(
        f"no default branch found among {list(candidates)} at {root}; "
        "pass parent_ref explicitly"
    )


# --- Baseline capture --------------------------------------------------------


def capture_baseline_commit(
    path: str | Path,
    parent_ref: str | None = None,
) -> str:
    """Return the 40-char baseline commit SHA for a worktree.

    The baseline is ``git merge-base HEAD <parent_ref>`` — the most recent
    common ancestor between the worktree's HEAD and the parent ref. This is
    what the production-gate diff scope is computed against.

    Raises ``WorktreeBaselineError`` if ``path`` is not a linked worktree, the
    parent ref cannot be resolved, or no merge base exists (e.g. unrelated
    histories grafted into the same repo).
    """
    if not is_worktree(path):
        raise WorktreeBaselineError(
            f"{path} is not a linked git worktree; "
            "baseline_commit capture only applies to scm.isolation=worktree"
        )
    root = find_worktree_root(path)
    ref = resolve_parent_ref(root, override=parent_ref)
    sha = _run_git("merge-base", "HEAD", ref, cwd=root)
    if len(sha) != 40 or not all(c in "0123456789abcdef" for c in sha):
        raise WorktreeBaselineError(
            f"git merge-base returned a non-canonical SHA: {sha!r}"
        )
    return sha


def worktree_baseline_metadata(
    path: str | Path,
    parent_ref: str | None = None,
) -> dict[str, Any]:
    """Return the full baseline metadata payload for a worktree.

    Shape (stable, closed):

    .. code-block:: python

       {
           "isolation": "worktree",
           "worktree_root": "<absolute path>",
           "worktree_branch": "<short ref>",
           "worktree_head": "<40-char SHA>",
           "parent_ref": "<resolved ref>",
           "baseline_commit": "<40-char SHA>",
       }

    Suitable for direct embedding into a gate evidence record's ``scope``
    block by the caller — this module deliberately does not import
    ``evidence_io`` to avoid pulling telemetry into a pure helper.
    """
    if not is_worktree(path):
        raise WorktreeBaselineError(
            f"{path} is not a linked git worktree; "
            "baseline metadata capture only applies to scm.isolation=worktree"
        )
    root = find_worktree_root(path)
    ref = resolve_parent_ref(root, override=parent_ref)
    head_sha = _run_git("rev-parse", "HEAD", cwd=root)
    baseline_sha = _run_git("merge-base", "HEAD", ref, cwd=root)
    # ``rev-parse --abbrev-ref HEAD`` returns the short branch name, or
    # ``HEAD`` if detached — both are acceptable; callers can distinguish.
    branch = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    return {
        "isolation": ISOLATION_WORKTREE,
        "worktree_root": str(root.resolve()),
        "worktree_branch": branch,
        "worktree_head": head_sha,
        "parent_ref": ref,
        "baseline_commit": baseline_sha,
    }
