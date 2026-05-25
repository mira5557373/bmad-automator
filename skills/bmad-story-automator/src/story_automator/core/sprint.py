from __future__ import annotations

import re
from dataclasses import dataclass

from .story_keys import StoryKey, normalize_story_key, normalize_story_key_for_epic, sprint_status_file
from .utils import file_exists, read_text, trim_lines


@dataclass(frozen=True)
class SprintStatus:
    found: bool
    story: str
    status: str
    done: bool
    reason: str = ""


def sprint_status_get(project_root: str, story_key: str) -> SprintStatus:
    status_file = sprint_status_file(project_root)
    if not file_exists(status_file):
        return SprintStatus(False, story_key, "unknown", False, "sprint-status.yaml not found")
    content = read_text(status_file)
    match = re.search(rf"(?m)^\s*{re.escape(story_key)}:\s*(\S+)", content)
    if match:
        status = match.group(1).strip()
        return SprintStatus(True, story_key, status, status == "done")
    norm = normalize_story_key(project_root, story_key)
    if norm is not None:
        match = re.search(rf"(?m)^\s*{re.escape(norm.key)}:\s*(\S+)", content)
        if match:
            status = match.group(1).strip()
            return SprintStatus(True, norm.key, status, status == "done")
        match = re.search(rf"(?m)^\s*({re.escape(norm.prefix)}-[^:\s]+)\s*:\s*(\S+)", content)
        if match:
            status = match.group(2).strip()
            return SprintStatus(True, match.group(1).strip(), status, status == "done")
    return SprintStatus(False, story_key, "not_found", False)


def sprint_status_epic(project_root: str, epic: str) -> tuple[list[str], int]:
    status_file = sprint_status_file(project_root)
    if not file_exists(status_file):
        return ([], 0)
    story_order: list[str] = []
    story_rows: dict[str, tuple[int, str, str]] = {}
    for line in trim_lines(read_text(status_file)):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 1)
        if len(parts) < 2:
            continue
        key = parts[0].strip()
        norm = normalize_story_key_for_epic(project_root, epic, key)
        if norm is None or norm.id.rsplit(".", 1)[0] != epic:
            continue
        status = parts[1].strip().split()
        rank = _status_key_rank(key, norm)
        if norm.id not in story_rows:
            story_order.append(norm.id)
        previous = story_rows.get(norm.id)
        if previous is None or rank >= previous[0]:
            story_rows[norm.id] = (rank, key, status[0] if status else "")
    stories = [story_rows[story_id][1] for story_id in story_order]
    done_count = sum(1 for story_id in story_order if story_rows[story_id][2] == "done")
    return (stories, done_count)


def _status_key_rank(key: str, norm: StoryKey) -> int:
    if key == norm.key and key not in {norm.id, norm.prefix}:
        return 2
    return 1
