"""Diff-based evidence scoping (§18 performance target).

Determines which files changed between a baseline and current commit,
maps file patterns to evidence categories, and computes the set of
categories that need re-evaluation.  Enables the ≤10 min wall-clock
target by skipping unchanged categories.
"""
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from .audit import scrub_env_for_subprocess

__all__ = [
    "DiffScopeError",
    "compute_changed_files",
    "DEFAULT_FILE_CATEGORY_MAP",
    "affected_categories",
    "compute_diff_scope",
]

_GIT_TIMEOUT = 30


class DiffScopeError(RuntimeError):
    """Raised when diff-scope computation fails."""


DEFAULT_FILE_CATEGORY_MAP: dict[str, frozenset[str]] = {
    "*.py": frozenset({"correctness", "static", "security"}),
    "*.pyi": frozenset({"static"}),
    "*.ts": frozenset({"correctness", "static", "security"}),
    "*.tsx": frozenset({"correctness", "static", "security", "accessibility"}),
    "*.js": frozenset({"correctness", "static", "security"}),
    "*.jsx": frozenset({"correctness", "static", "security", "accessibility"}),
    "*.sql": frozenset({"migrations", "security"}),
    "*.tf": frozenset({"security", "compliance"}),
    "*.hcl": frozenset({"security", "compliance"}),
    "*.md": frozenset({"docs"}),
    "*.yaml": frozenset({"invariants", "compliance"}),
    "*.yml": frozenset({"invariants", "compliance"}),
    "Dockerfile": frozenset({"security", "supply_chain"}),
    "Dockerfile.*": frozenset({"security", "supply_chain"}),
    "*.lock": frozenset({"security", "supply_chain"}),
}


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
            env=scrub_env_for_subprocess(),
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


def _matches_pattern(filepath: str, pattern: str) -> bool:
    """Match a file path against a glob pattern.

    Patterns containing '/' match the full path.
    Patterns without '/' match only the filename (basename).
    """
    if "/" in pattern:
        return fnmatch.fnmatch(filepath, pattern)
    name = filepath.rsplit("/", maxsplit=1)[-1]
    return fnmatch.fnmatch(name, pattern)


def affected_categories(
    changed_files: set[str],
    file_category_map: dict[str, frozenset[str]] | None = None,
) -> set[str]:
    """Map changed files to the set of affected evidence categories."""
    mapping = (
        file_category_map
        if file_category_map is not None
        else DEFAULT_FILE_CATEGORY_MAP
    )
    categories: set[str] = set()
    for filepath in changed_files:
        for pattern, cats in mapping.items():
            if _matches_pattern(filepath, pattern):
                categories.update(cats)
    return categories


def compute_diff_scope(
    project_root: str | Path,
    baseline_sha: str,
    current_sha: str = "HEAD",
    file_category_map: dict[str, frozenset[str]] | None = None,
) -> set[str]:
    """Compute categories affected by changes since baseline.

    §18: enables diff-scoped gate evaluation for ≤10 min wall-clock.
    Returns empty set when no files changed.
    """
    changed = compute_changed_files(project_root, baseline_sha, current_sha)
    if not changed:
        return set()
    return affected_categories(changed, file_category_map)
