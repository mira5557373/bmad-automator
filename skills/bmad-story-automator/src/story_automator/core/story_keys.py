from __future__ import annotations

import re
from dataclasses import dataclass

from .artifact_paths import implementation_artifacts_dir, sprint_status_path
from .utils import file_exists, read_text


@dataclass(frozen=True)
class StoryKey:
    id: str
    prefix: str
    key: str


def sprint_status_file(project_root: str) -> str:
    return str(sprint_status_path(project_root))


def normalize_story_key(project_root: str, value: str) -> StoryKey | None:
    if re.fullmatch(r"\d+\.\d+", value):
        story_id = value
        prefix = value.replace(".", "-")
        key = ""
    elif re.fullmatch(r"\d+-\d+", value):
        prefix = value
        story_id = value.replace("-", ".")
        key = ""
    elif re.fullmatch(r"\d+-\d+-.+", value):
        key = value
        prefix = "-".join(value.split("-", 2)[:2])
        story_id = prefix.replace("-", ".")
    else:
        return None

    artifacts = implementation_artifacts_dir(project_root)
    if not key:
        matches = sorted(artifacts.glob(f"{prefix}-*.md"))
        if matches:
            key = matches[0].stem
    if not key:
        status_file = sprint_status_file(project_root)
        if file_exists(status_file):
            content = read_text(status_file)
            match = re.search(rf"(?m)^\s*({re.escape(prefix)}-[^:\s]+)\s*:", content)
            if match:
                key = match.group(1).strip()
    if not key:
        key = prefix
    return StoryKey(id=story_id, prefix=prefix, key=key)
