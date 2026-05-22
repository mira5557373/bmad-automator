from __future__ import annotations

import re
from dataclasses import dataclass

from .story_keys import normalize_story_key, sprint_status_file
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
    return SprintStatus(False, story_key, "not_found", False)


def sprint_status_epic(project_root: str, epic: str) -> tuple[list[str], int]:
    status_file = sprint_status_file(project_root)
    if not file_exists(status_file):
        return ([], 0)
    stories: list[str] = []
    seen: set[str] = set()
    done_count = 0
    for line in trim_lines(read_text(status_file)):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 1)
        if len(parts) < 2:
            continue
        key = parts[0].strip()
        norm = normalize_story_key(project_root, key)
        if norm is None or norm.id.rsplit(".", 1)[0] != epic:
            continue
        if key in seen:
            continue
        stories.append(key)
        seen.add(key)
        status = parts[1].strip().split()
        if status and status[0] == "done":
            done_count += 1
    return (stories, done_count)
