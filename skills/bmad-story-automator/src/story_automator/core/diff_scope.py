"""Diff-based evidence scoping (§18 performance target).

Determines which files changed between a baseline and current commit,
maps file patterns to evidence categories, and computes the set of
categories that need re-evaluation.  Enables the ≤10 min wall-clock
target by skipping unchanged categories.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = [
    "DiffScopeError",
    "compute_changed_files",
]

_GIT_TIMEOUT = 30


class DiffScopeError(RuntimeError):
    """Raised when diff-scope computation fails."""


def compute_changed_files(
    project_root: str | Path,
    baseline_sha: str,
    current_sha: str = "HEAD",
) -> set[str]:
    """Return file paths changed between baseline and current commit."""
    root = str(Path(project_root).resolve())
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{baseline_sha}..{current_sha}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise DiffScopeError("git diff timed out") from exc
    except FileNotFoundError as exc:
        raise DiffScopeError("git not found") from exc
    if result.returncode != 0:
        raise DiffScopeError(
            f"git diff failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    }
