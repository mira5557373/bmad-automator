"""Fresh checkout management for evidence collectors (spec §7).

Creates temporary git worktrees at a specific commit SHA so collectors
run against pristine source, not the child's modified working copy.
This closes the TOCTOU gap: the child cannot modify code between
generation and evidence collection.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from .audit import scrub_env_for_subprocess

__all__ = [
    "CollectorCheckoutError",
    "create_collector_checkout",
    "cleanup_collector_checkout",
    "collector_checkout",
]

_GIT_TIMEOUT = 30
_PRUNE_TIMEOUT = 15
# Hex SHA inputs only — refnames (HEAD, branches, tags) are rejected at the
# entry point so the verifier compares actual_sha to a full resolved 40-char
# SHA, not a 7-char prefix (bug A-04+G7).
_SHA_RE = re.compile(r"[0-9a-f]{4,40}")


class CollectorCheckoutError(RuntimeError):
    """Raised when a collector checkout cannot be created or validated."""


def create_collector_checkout(
    project_root: str | Path,
    commit_sha: str,
) -> Path:
    """Create a detached git worktree at commit_sha for collectors.

    Returns the path to the worktree directory.  Caller must call
    cleanup_collector_checkout() when done, or use the
    collector_checkout() context manager.
    """
    root = Path(project_root).resolve()
    if not (root / ".git").exists() and not (root / ".git").is_file():
        raise CollectorCheckoutError(f"not a git repository: {root}")
    if not commit_sha or not commit_sha.strip():
        raise CollectorCheckoutError("commit_sha must not be empty")
    # Bug A-04+G7: reject refnames (HEAD, main, tags) at the entry point.
    # Only lower-case hex of length >=4 is accepted; everything else is
    # rejected before any git invocation.
    sha_input = commit_sha.strip().lower()
    if not _SHA_RE.fullmatch(sha_input):
        raise CollectorCheckoutError(
            f"commit_sha must be a hex SHA (4-40 chars [0-9a-f]); refnames "
            f"are not accepted: {commit_sha!r}"
        )
    # Resolve to a full 40-char SHA against the PARENT repo first so the
    # downstream equality check has something canonical to compare against.
    try:
        resolve = subprocess.run(
            ["git", "rev-parse", "--verify", f"{sha_input}^{{commit}}"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            env=scrub_env_for_subprocess(),
        )
    except subprocess.TimeoutExpired as exc:
        raise CollectorCheckoutError(
            f"git rev-parse timed out resolving {sha_input}"
        ) from exc
    if resolve.returncode != 0:
        raise CollectorCheckoutError(
            f"commit_sha {sha_input!r} does not resolve to a commit: "
            f"{resolve.stderr.strip()}"
        )
    resolved_sha = resolve.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", resolved_sha):
        raise CollectorCheckoutError(
            f"git rev-parse returned non-hex output: {resolved_sha!r}"
        )
    checkout_dir = Path(
        tempfile.mkdtemp(prefix="sa-collector-", suffix=f"-{resolved_sha[:8]}")
    )
    try:
        result = subprocess.run(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(checkout_dir),
                resolved_sha,
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
            env=scrub_env_for_subprocess(),
        )
        if result.returncode != 0:
            shutil.rmtree(checkout_dir, ignore_errors=True)
            raise CollectorCheckoutError(
                f"git worktree add failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )
        verify = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(checkout_dir),
            capture_output=True,
            text=True,
            timeout=10,
            env=scrub_env_for_subprocess(),
        )
        actual_sha = verify.stdout.strip()
        if actual_sha != resolved_sha:
            cleanup_collector_checkout(checkout_dir, root)
            raise CollectorCheckoutError(
                f"checkout SHA mismatch: expected {resolved_sha}, got {actual_sha}"
            )
        return checkout_dir
    except subprocess.TimeoutExpired:
        shutil.rmtree(checkout_dir, ignore_errors=True)
        raise CollectorCheckoutError("git worktree add timed out")
    except CollectorCheckoutError:
        raise
    except OSError as exc:
        shutil.rmtree(checkout_dir, ignore_errors=True)
        raise CollectorCheckoutError(f"checkout failed: {exc}") from exc


def cleanup_collector_checkout(
    checkout_path: Path,
    project_root: str | Path | None = None,
) -> None:
    """Remove a collector worktree and its directory.

    Best-effort: never raises on cleanup failure.
    """
    if project_root is not None:
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(checkout_path)],
                cwd=str(Path(project_root).resolve()),
                capture_output=True,
                timeout=_PRUNE_TIMEOUT,
                env=scrub_env_for_subprocess(),
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
    shutil.rmtree(checkout_path, ignore_errors=True)


@contextmanager
def collector_checkout(
    project_root: str | Path,
    commit_sha: str,
) -> Generator[Path, None, None]:
    """Context manager: create a collector checkout, clean up on exit."""
    checkout = create_collector_checkout(project_root, commit_sha)
    try:
        yield checkout
    finally:
        cleanup_collector_checkout(checkout, project_root)
