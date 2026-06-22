"""Git-state primitives for the baseline-commit lie detector.

Ported from bmad-auto/src/automator/verify.py (MIT-licensed). The
functions named here mirror bmad-auto's contracts byte-for-byte (modulo
stdlib subprocess vs. our existing helpers), so a future rebase onto
bmad-auto's runtime can swap implementations transparently.

Purpose: the gate's pre-collector check needs three primitives —
"what HEAD is now", "do the two SHAs refer to the same commit
(tolerating abbreviated forms)", and "have any tracked or untracked
changes appeared since baseline". Together they let
``run_production_gate`` reject the most common LLM hallucination —
claiming work was committed when the worktree is unchanged — without
running any collector.

These are all read-only and stdlib-only. They respect the hard
guardrail (no new Python deps beyond stdlib + filelock + psutil).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .audit import scrub_env_for_subprocess

GIT_TIMEOUT_S = 120


class GitError(RuntimeError):
    """A git command exited non-zero or could not be executed."""


def _git(repo: str | Path, *args: str) -> tuple[int, str]:
    """Run a git command in ``repo`` and return ``(returncode, stripped_output)``.

    stdout + stderr are merged (matches bmad-auto verify._git). 120 s
    timeout guards against rogue hung-git processes (network paths,
    misconfigured remotes).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
            env=scrub_env_for_subprocess(),
        )
    except FileNotFoundError as exc:  # `git` not on PATH
        raise GitError(f"git executable not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(
            f"git {' '.join(args)} timed out after {GIT_TIMEOUT_S}s in {repo}"
        ) from exc
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def rev_parse_head(repo: str | Path) -> str:
    """Return the SHA of ``HEAD`` in ``repo``.

    Raises :class:`GitError` if the call fails (e.g. ``repo`` is not a
    git repository). Used by the gate orchestrator to capture the
    baseline commit before dispatching a dev session.
    """
    rc, out = _git(repo, "rev-parse", "HEAD")
    if rc != 0:
        raise GitError(f"git rev-parse HEAD failed in {repo}: {out}")
    return out


def same_commit(a: str, b: str) -> bool:
    """True iff two SHAs (possibly abbreviated to >= 7 chars) refer to the same commit.

    Sessions sometimes report ``git rev-parse --short HEAD`` (7-char
    default) and we record the full 40-char SHA. Either prefix being a
    prefix of the other is considered "same commit" — this mirrors
    bmad-auto/verify.same_commit.
    """
    if len(a) < 7 or len(b) < 7:
        return a == b
    return a.startswith(b) or b.startswith(a)


def has_changes_since(repo: str | Path, baseline: str) -> bool:
    """True iff the worktree has tracked-or-untracked changes since ``baseline``.

    - ``git diff --quiet baseline --`` returns non-zero on tracked changes.
    - ``git ls-files --others --exclude-standard`` lists untracked files
      that are not .gitignored.

    Either condition flips the result to True. Used by the gate's
    lie-detector to reject a session that claims work was committed
    when nothing actually changed.
    """
    rc, _ = _git(repo, "diff", "--quiet", baseline, "--")
    if rc != 0:
        return True
    rc, out = _git(repo, "ls-files", "--others", "--exclude-standard")
    return rc == 0 and out != ""


def untracked_files(repo: str | Path) -> set[str]:
    """Repo-relative posix paths of untracked, non-ignored files.

    Mirrors ``git clean -fd`` (without -x) — i.e. it ignores files
    matched by ``.gitignore``. The result is suitable for diffing
    against an earlier baseline-untracked set (a file appearing only
    in the "now" set is rollback-eligible; one in both sets was there
    at baseline and must be preserved).
    """
    rc, out = _git(repo, "ls-files", "--others", "--exclude-standard")
    if rc != 0:
        raise GitError(f"git ls-files --others failed in {repo}: {out}")
    return {line.strip() for line in out.splitlines() if line.strip()}


def worktree_clean(repo: str | Path) -> bool:
    """True iff ``git status --porcelain`` is empty (no tracked or untracked changes).

    Lighter-weight than ``has_changes_since`` when no baseline SHA is
    available. Used by the worktree-recovery routine in Phase 2 to
    decide whether a checkout is rollback-candidate.
    """
    rc, out = _git(repo, "status", "--porcelain")
    if rc != 0:
        raise GitError(f"git status failed in {repo}: {out}")
    return out == ""
