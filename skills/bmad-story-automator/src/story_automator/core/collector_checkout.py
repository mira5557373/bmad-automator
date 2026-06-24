"""Fresh checkout management for evidence collectors (spec §7).

Creates temporary git worktrees at a specific commit SHA so collectors
run against pristine source, not the child's modified working copy.
This closes the TOCTOU gap: the child cannot modify code between
generation and evidence collection.
"""

from __future__ import annotations

import re
import shutil
import string
import subprocess
import tempfile
import time
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

# G2 — name_hint sanitization constants (spec §5.1, §5.3).
# Sanitize-FIRST (drop chars not in [A-Za-z0-9._-]) then truncate-SECOND
# (take LAST 32 chars of the sanitized string) to preserve a disambiguating
# tail when multiple collector ids share a long prefix.
_NAME_HINT_TAIL_CAP: int = 32
_ALLOWED_NAME_HINT_CHARSET: frozenset[str] = frozenset(string.ascii_letters + string.digits + "._-")

# G2 — transient git-lock retry constants (spec §3 add_timeout row, §4
# collector_checkout box, AC-C-08). On `git worktree add` returning
# non-zero with stderr matching the transient regex, sleep briefly and
# retry up to _MAX_WORKTREE_ADD_ATTEMPTS total attempts.
_TRANSIENT_LOCK_RE = re.compile(
    r"(could not lock|already locked|index\.lock|"
    r"config\.lock|locked by another process)",
    re.IGNORECASE,
)
_MAX_WORKTREE_ADD_ATTEMPTS: int = 3
_WORKTREE_ADD_BACKOFF_S: float = 0.05


class CollectorCheckoutError(RuntimeError):
    """Raised when a collector checkout cannot be created or validated."""


def _sanitize_name_hint(hint: str) -> str:
    """Sanitize an operator-supplied name_hint into a worktree-suffix-safe ASCII slug.

    Order is sanitize-FIRST (drop chars not in [A-Za-z0-9._-]) then
    truncate-SECOND (take LAST 32 chars of the sanitized string). The
    "last 32" tail preserves the disambiguating suffix when multiple
    collector ids share a long prefix.

    Empty / whitespace-only / fully-rejected input returns "".
    """
    if not hint:
        return ""
    sanitized = "".join(ch for ch in hint if ch in _ALLOWED_NAME_HINT_CHARSET)
    if not sanitized:
        return ""
    return sanitized[-_NAME_HINT_TAIL_CAP:]


def _is_transient_lock_error(stderr: str) -> bool:
    """True iff `stderr` looks like a transient git lock collision worth retrying.

    Matches case-insensitively against the union of:
    "could not lock", "already locked", "index.lock", "config.lock",
    "locked by another process".
    """
    if not stderr:
        return False
    return bool(_TRANSIENT_LOCK_RE.search(stderr))


def create_collector_checkout(
    project_root: str | Path,
    commit_sha: str,
    *,
    name_hint: str = "",
    add_timeout: int | None = None,
) -> Path:
    """Create a detached git worktree at commit_sha for collectors.

    Returns the path to the worktree directory.  Caller must call
    cleanup_collector_checkout() when done, or use the
    collector_checkout() context manager.

    Optional kwargs (G2 — additive, byte-identical defaults):
      - name_hint: optional disambiguating tag appended to the checkout
        directory suffix. Empty default preserves the historical
        `sa-collector-XXXX-<sha8>` shape. Non-empty input is run through
        _sanitize_name_hint (sanitize-first, take-last-32 chars).
      - add_timeout: optional override for the `git worktree add` timeout.
        `None` (default) means use _GIT_TIMEOUT = 30 (byte-identical).
        The per-unit isolation dispatcher passes 90 to accommodate
        contended slow disks.
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
        raise CollectorCheckoutError(f"git rev-parse timed out resolving {sha_input}") from exc
    if resolve.returncode != 0:
        raise CollectorCheckoutError(
            f"commit_sha {sha_input!r} does not resolve to a commit: {resolve.stderr.strip()}"
        )
    resolved_sha = resolve.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", resolved_sha):
        raise CollectorCheckoutError(f"git rev-parse returned non-hex output: {resolved_sha!r}")

    # G2 — additive suffix: optional `-<sanitized_name_hint>` segment.
    suffix_parts = [f"-{resolved_sha[:8]}"]
    if name_hint:
        sanitized = _sanitize_name_hint(name_hint)
        if sanitized:
            suffix_parts.append(f"-{sanitized}")
    checkout_dir = Path(tempfile.mkdtemp(prefix="sa-collector-", suffix="".join(suffix_parts)))

    # G2 — additive timeout override. None preserves byte-identical
    # behavior (timeout=30).
    timeout_s = _GIT_TIMEOUT if add_timeout is None else int(add_timeout)

    try:
        # G2 — bounded retry on transient git lock contention
        # (AC-C-08, AC-C-09). Non-transient failures break immediately.
        result: subprocess.CompletedProcess[str] | None = None
        last_stderr = ""
        for attempt in range(_MAX_WORKTREE_ADD_ATTEMPTS):
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
                timeout=timeout_s,
                env=scrub_env_for_subprocess(),
            )
            if result.returncode == 0:
                break
            last_stderr = result.stderr or ""
            if not _is_transient_lock_error(last_stderr):
                break
            # Avoid sleeping after the FINAL attempt — it can't help.
            if attempt < _MAX_WORKTREE_ADD_ATTEMPTS - 1:
                time.sleep(_WORKTREE_ADD_BACKOFF_S)
        assert result is not None  # loop runs at least once
        if result.returncode != 0:
            shutil.rmtree(checkout_dir, ignore_errors=True)
            raise CollectorCheckoutError(
                f"git worktree add failed (exit {result.returncode}): {last_stderr.strip()}"
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
