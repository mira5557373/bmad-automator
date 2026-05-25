from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .utils import file_exists, read_text


@dataclass(frozen=True)
class StoryKey:
    id: str
    prefix: str
    key: str


def sprint_status_file(project_root: str) -> str:
    preferred = Path(project_root) / "_bmad-output" / "implementation-artifacts" / "sprint-status.yaml"
    if preferred.is_file():
        return str(preferred)
    legacy = Path(project_root) / "_bmad-output" / "sprint-status.yaml"
    if legacy.is_file():
        return str(legacy)
    return str(preferred)


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
    elif re.fullmatch(r"[A-Za-z][\w-]*\.\d+", value):
        story_id = value
        epic_part, _, story_num = value.partition(".")
        prefix = f"{epic_part}-{story_num}"
        key = ""
    elif re.fullmatch(r"[A-Za-z][\w-]*-\d+", value):
        prefix = value
        epic_part, _, story_num = value.rpartition("-")
        story_id = f"{epic_part}.{story_num}"
        key = ""
    elif re.fullmatch(r"[A-Za-z][\w-]*-\d+-.+", value):
        split = _split_non_numeric_full_key(project_root, value)
        if split is None:
            return None
        epic_part, story_num = split
        prefix = f"{epic_part}-{story_num}"
        story_id = f"{epic_part}.{story_num}"
        key = value
    else:
        return None

    return _complete_story_key(project_root, story_id, prefix, key)


def normalize_story_key_for_epic(project_root: str, epic: str, value: str) -> StoryKey | None:
    dotted = re.fullmatch(rf"{re.escape(epic)}\.(\d+)", value)
    if dotted:
        story_num = dotted.group(1)
        return _complete_story_key(project_root, f"{epic}.{story_num}", f"{epic}-{story_num}", "")

    dashed = re.fullmatch(rf"{re.escape(epic)}-(\d+)(?:-.+)?", value)
    if dashed:
        if _has_known_longer_epic(project_root, epic, value):
            return None
        story_num = dashed.group(1)
        prefix = f"{epic}-{story_num}"
        key = value if value != prefix else ""
        return _complete_story_key(project_root, f"{epic}.{story_num}", prefix, key)

    return normalize_story_key(project_root, value)


def _complete_story_key(project_root: str, story_id: str, prefix: str, key: str) -> StoryKey:
    artifacts = Path(project_root) / "_bmad-output" / "implementation-artifacts"
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


def _split_non_numeric_full_key(project_root: str, value: str) -> tuple[str, str] | None:
    matches = list(re.finditer(r"(?=-(\d+)-)", value))
    if not matches:
        return None
    single_story = [
        match
        for match in matches[1:]
        if _is_single_story_key(project_root, value, match)
    ]
    if single_story:
        match = max(single_story, key=lambda item: item.start())
        return value[: match.start()], match.group(1)
    known = [match for match in matches if _epic_exists(project_root, value[: match.start()])]
    match = max(known, key=lambda item: item.start()) if known else _single_story_epic_match(project_root, value, matches)
    return value[: match.start()], match.group(1)


def _has_known_longer_epic(project_root: str, epic: str, value: str) -> bool:
    for match in re.finditer(r"(?=-(\d+)-)", value):
        candidate_epic = value[: match.start()]
        if candidate_epic == epic or not candidate_epic.startswith(f"{epic}-"):
            continue
        if _epic_exists(project_root, candidate_epic) or _is_single_story_key(project_root, value, match):
            return True
    return False


def _epic_exists(project_root: str, epic: str) -> bool:
    if _epic_file_exists(project_root, epic):
        return True
    status_file = sprint_status_file(project_root)
    if not file_exists(status_file):
        return False
    pattern = re.compile(rf"(?m)^\s*{re.escape(epic)}-(\d+)(?:-[^:\s]+)?\s*:")
    story_nums = {match.group(1) for match in pattern.finditer(read_text(status_file))}
    return len(story_nums) > 1


def _is_single_story_key(project_root: str, value: str, match: re.Match[str]) -> bool:
    status_file = sprint_status_file(project_root)
    return (
        match.group(1) == "1"
        and file_exists(status_file)
        and re.search(rf"(?m)^\s*{re.escape(value)}\s*:", read_text(status_file)) is not None
    )


def _single_story_epic_match(project_root: str, value: str, matches: list[re.Match[str]]) -> re.Match[str]:
    status_file = sprint_status_file(project_root)
    if not file_exists(status_file) or not re.search(rf"(?m)^\s*{re.escape(value)}\s*:", read_text(status_file)):
        return matches[0]
    for match in reversed(matches[1:]):
        if _is_single_story_key(project_root, value, match):
            return match
    return matches[0]


def _epic_file_exists(project_root: str, epic: str) -> bool:
    root = Path(project_root)
    for base in (root / "_bmad-output" / "implementation-artifacts", root / "docs" / "epics"):
        if (base / f"epic-{epic}.md").is_file() or next(base.glob(f"epic-{epic}-*.md"), None) is not None:
            return True
    return False
