from __future__ import annotations

from pathlib import Path

from .utils import write_atomic

VALID_INITIAL_STATUSES: frozenset[str] = frozenset({"backlog", "ready-for-dev"})


def _header_line(epic: int, story: int, title: str) -> str:
    return f"# Story {epic}.{story}: {title}"


def write_story_header(
    path: str | Path, *, epic: int, story: int, title: str
) -> Path:
    target = Path(path)
    write_atomic(target, _header_line(epic, story, title) + "\n")
    return target


def _has_status_sentinel(content: str) -> bool:
    for line in content.splitlines():
        if line.strip().startswith("Status:"):
            return True
    return False


def seed_status_sentinel(
    path: str | Path, status: str = "ready-for-dev"
) -> None:
    if status not in VALID_INITIAL_STATUSES:
        raise ValueError(
            f"invalid initial status {status!r}; "
            f"valid options: {sorted(VALID_INITIAL_STATUSES)}"
        )
    target = Path(path)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if _has_status_sentinel(existing):
        return
    if existing and not existing.endswith("\n"):
        existing += "\n"
    new_content = existing + f"Status: {status}\n"
    write_atomic(target, new_content)


def write_story_skeleton(
    path: str | Path,
    *,
    epic: int,
    story: int,
    title: str,
    status: str = "ready-for-dev",
) -> Path:
    if status not in VALID_INITIAL_STATUSES:
        raise ValueError(
            f"invalid initial status {status!r}; "
            f"valid options: {sorted(VALID_INITIAL_STATUSES)}"
        )
    target = Path(path)
    body = (
        _header_line(epic, story, title)
        + "\n\n"
        + f"Status: {status}\n\n"
        + "## Story\n\n"
        + "## Acceptance Criteria\n\n"
        + "## Dev Notes\n\n"
        + "## Tasks\n\n"
        + "## File List\n\n"
        + "## QA Notes\n"
    )
    write_atomic(target, body)
    return target
