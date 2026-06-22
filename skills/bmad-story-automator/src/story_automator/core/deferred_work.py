"""Deferred-work log for the bmad-story-automator factory.

Operators occasionally need to record work that the factory cannot complete
inside the current story but which must be revisited later. This module
appends those entries to a single Markdown ledger under the project root and
exposes a small parser for downstream tooling (dashboards, gate summaries,
remediation prompts).

Design constraints (per CLAUDE.md and the runtime self-containment guard
enforced by ``tests/test_no_unauthorized_imports.py``):

* Stdlib + first-party only — no third-party deps in the shipped runtime.
* Atomic write semantics via :func:`story_automator.core.utils.write_atomic`
  so concurrent appenders never see a half-written file.
* Process-level mutual exclusion via a tiny ``O_CREAT|O_EXCL`` lockfile so
  two child sessions cannot race on the read-modify-write sequence required
  to *append* to the ledger. The lock spins with exponential back-off up to
  a short bound, then steals a stale lock whose mtime is older than the
  steal threshold — this matches the failure mode of ``filelock`` without
  pulling in the dependency, and keeps single-user latency negligible.
* Severity is a closed vocabulary; unknown values raise ``ValueError``
  fail-fast at the call site rather than poisoning the log.
"""
from __future__ import annotations

import errno
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from story_automator.core.utils import read_text, write_atomic


DEFERRED_WORK_PATH_RELATIVE = "_bmad/bmm/deferred-work.md"

VALID_SEVERITIES = frozenset({"CRITICAL", "PREFERENCE"})

_HEADER_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_FIELD_RE = re.compile(r"^-\s+\*\*(?P<key>[A-Za-z_]+)\*\*:\s+(?P<value>.*?)\s*$")


def _deferred_work_path(project_root: Path | str) -> Path:
    return Path(project_root) / DEFERRED_WORK_PATH_RELATIVE


def _lock_path(target: Path) -> Path:
    # Sibling lock file — keeps the lock co-located with the artifact so
    # cleanup is obvious during ops triage. We cannot reuse the artifact
    # itself because the atomic rename performed by ``write_atomic`` would
    # invalidate any open handle.
    return target.with_name(target.name + ".lock")


# Steal a lock whose mtime exceeds this; well above the longest plausible
# append, well below anything a human operator would tolerate.
_LOCK_STEAL_SECONDS = 30.0
# Total wall-clock budget before we give up acquiring; chosen to be large
# enough to ride out any single legitimate appender on shared storage.
_LOCK_WAIT_SECONDS = 10.0


class _AppendLock:
    """Stdlib-only advisory lock backed by ``O_CREAT|O_EXCL``."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._held = False

    def __enter__(self) -> "_AppendLock":
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        delay = 0.005
        while True:
            try:
                fd = os.open(
                    str(self._path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                os.close(fd)
                self._held = True
                return self
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
                # Steal the lock if it is older than the steal threshold —
                # this is the recovery story for a child that crashed mid
                # append.
                try:
                    age = time.time() - self._path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > _LOCK_STEAL_SECONDS:
                    try:
                        self._path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"could not acquire append lock at {self._path}"
                    ) from exc
                time.sleep(delay)
                delay = min(delay * 2, 0.1)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._held:
            try:
                self._path.unlink()
            except FileNotFoundError:
                pass


def _format_entry(
    *,
    title: str,
    reason: str,
    owner_story: str,
    severity: str,
    recorded_at: str,
) -> str:
    return (
        f"\n## {title}\n"
        f"- **severity**: {severity}\n"
        f"- **owner_story**: {owner_story}\n"
        f"- **recorded_at**: {recorded_at}\n"
        f"- **reason**: {reason}\n"
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_entry(
    project_root: Path | str,
    *,
    title: str,
    reason: str,
    owner_story: str,
    severity: str = "PREFERENCE",
) -> Path:
    """Append a deferred-work entry to the project's ledger.

    Parameters
    ----------
    project_root:
        Absolute path to the project root. The ledger lives at
        ``<project_root>/_bmad/bmm/deferred-work.md``.
    title:
        Short human-readable summary of the deferred item. Used as the
        Markdown section heading.
    reason:
        Why the work was deferred. Free-form prose, single line preferred.
    owner_story:
        Story key (e.g. ``story-1.2.3``) that surfaced the deferral.
    severity:
        Must be a member of :data:`VALID_SEVERITIES`.

    Returns
    -------
    pathlib.Path
        The path the entry was written to.

    Raises
    ------
    ValueError
        If ``severity`` is not a recognised value.
    """

    if severity not in VALID_SEVERITIES:
        valid = ", ".join(sorted(VALID_SEVERITIES))
        raise ValueError(
            f"unknown severity {severity!r}; expected one of: {valid}"
        )

    target = _deferred_work_path(project_root)
    target.parent.mkdir(parents=True, exist_ok=True)

    entry = _format_entry(
        title=title,
        reason=reason,
        owner_story=owner_story,
        severity=severity,
        recorded_at=_now_iso(),
    )

    with _AppendLock(_lock_path(target)):
        existing = ""
        if target.exists():
            existing = read_text(target)
            if existing and not existing.endswith("\n"):
                existing = existing + "\n"
        else:
            existing = "# Deferred work\n"
        write_atomic(target, existing + entry)

    return target


def list_entries(project_root: Path | str) -> list[dict[str, Any]]:
    """Parse the deferred-work ledger back into structured entries.

    Returns an empty list if the ledger has never been written. The parser is
    intentionally tolerant: unknown ``- **key**: value`` fields are preserved,
    and entries without a recognisable title heading are skipped silently.
    """

    target = _deferred_work_path(project_root)
    if not target.exists():
        return []

    contents = read_text(target)
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in contents.splitlines():
        header = _HEADER_RE.match(raw_line)
        if header:
            if current is not None:
                entries.append(current)
            current = {"title": header.group("title")}
            continue
        if current is None:
            continue
        field = _FIELD_RE.match(raw_line)
        if field:
            current[field.group("key")] = field.group("value")

    if current is not None:
        entries.append(current)
    return entries
