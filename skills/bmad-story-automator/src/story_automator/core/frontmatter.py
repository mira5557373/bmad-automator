from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .utils import parse_string_list_literal, read_text, trim_lines, unquote_scalar, write_atomic


_FENCE_LINE = re.compile(r"(?m)^---[ \t]*$")


def _split_fenced(text: str) -> list[str] | None:
    # The document must OPEN with a fence line that is exactly "---"
    # (plus optional trailing whitespace). Splitting on the bare substring
    # "---" would incorrectly terminate the frontmatter at the first "---"
    # appearing inside a quoted value (e.g. customInstructions), silently
    # dropping every key after it. Anchoring to whole lines avoids that.
    if not re.match(r"^---[ \t]*(?:\n|$)", text):
        return None
    parts = _FENCE_LINE.split(text, maxsplit=2)
    if len(parts) < 3:
        return None
    return parts


def extract_frontmatter(text: str) -> str:
    parts = _split_fenced(text)
    return "" if parts is None else parts[1].lstrip("\n")


def split_frontmatter(text: str) -> tuple[str, str]:
    parts = _split_fenced(text)
    if parts is None:
        return "", text
    return parts[1].lstrip("\n"), parts[2].lstrip("\n")


def parse_simple_frontmatter(text: str) -> dict[str, Any]:
    front = extract_frontmatter(text)
    if not front:
        return {}
    fields: dict[str, Any] = {}
    current_key = ""
    for line in trim_lines(front):
        if line.strip().startswith("#"):
            continue
        if re.match(r"^\S[^:]*:", line):
            key, raw = line.split(":", 1)
            key = key.strip()
            raw = raw.strip()
            if raw == "":
                fields[key] = []
                current_key = key
                continue
            parsed_list = parse_string_list_literal(raw)
            if parsed_list is not None:
                fields[key] = parsed_list
            else:
                fields[key] = unquote_scalar(raw)
            current_key = ""
            continue
        if current_key and line.strip().startswith("-"):
            fields.setdefault(current_key, [])
            fields[current_key].append(unquote_scalar(line.strip()[1:].strip()))
    return fields


def parse_frontmatter(text: str) -> dict[str, Any]:
    return parse_simple_frontmatter(text)


def find_frontmatter_value(path: str | Path, key: str) -> str:
    fields = parse_simple_frontmatter(read_text(path))
    value = fields.get(key, "")
    if isinstance(value, list):
        return ""
    return str(value)


def _document_preamble(text: str) -> list[str]:
    """Lines from the top of a doc up to its first ``## `` section heading.

    BMAD story files (bmad-create-story/template.md) carry ``Status:`` as a
    plain line after the ``# Story`` title rather than inside a ``---`` fence,
    so a fence-only reader would never see it. Scanning the preamble recovers
    those values without misreading body prose.
    """
    out: list[str] = []
    for line in trim_lines(text):
        if line.lstrip().startswith("## "):
            break
        out.append(line)
    return out


def find_frontmatter_value_case(path: str | Path, key: str) -> str:
    text = read_text(path)
    front = extract_frontmatter(text)
    # Prefer a real --- fence (story-automator state docs); fall back to the
    # document preamble for fenceless BMAD story files.
    lines = trim_lines(front) if front else _document_preamble(text)
    for line in lines:
        if ":" not in line:
            continue
        left, raw = line.split(":", 1)
        if left.strip().lower() == key.lower():
            return unquote_scalar(raw.strip())
    return ""


def extract_title(text: str) -> str:
    """Title from a BMAD story's first H1 (``# Story 1.1: Login`` -> ``Login``).

    BMAD story files put the title in the heading, not a ``Title:`` field.
    """
    for line in trim_lines(text):
        stripped = line.strip()
        if stripped.startswith("# "):
            heading = stripped[2:].strip()
            return heading.split(":", 1)[1].strip() if ":" in heading else heading
    return ""


def extract_last_action(path: str | Path) -> str:
    lines = trim_lines(read_text(path))
    for index, line in enumerate(lines):
        if not line.startswith("## Action Log"):
            continue
        # Scan every line under the header and return the LAST non-blank
        # one, stopping at the next section header. The previous +2 offset
        # returned the FIRST action (and crashed-to-"" on a one-entry log).
        last = ""
        for body in lines[index + 1:]:
            stripped = body.strip()
            if stripped.startswith("## "):
                break
            if stripped:
                last = stripped.lstrip("*-").strip()
        return last
    return ""


def read_story_range_from_state(path: str | Path) -> list[str]:
    text = read_text(path)
    for block in (extract_frontmatter(text), text):
        if not block.strip():
            continue
        lines = trim_lines(block)
        in_range = False
        story_range: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("storyRange:"):
                raw = stripped.split(":", 1)[1].strip()
                parsed = parse_string_list_literal(raw)
                if parsed is not None:
                    return parsed
                in_range = True
                continue
            if in_range and stripped.startswith("-"):
                story_range.append(unquote_scalar(stripped[1:].strip()))
                continue
            if in_range and re.match(r"^\S[^:]*:", line):
                break
        if story_range:
            return story_range
    return []


def update_simple_frontmatter(path: str | Path, updates: dict[str, str]) -> list[str]:
    path = Path(path)
    lines = trim_lines(read_text(path))
    # Bound the rewrite to the frontmatter region so a body line that
    # happens to start with "<key>:" (e.g. prose like "status: blocked on
    # X") is never clobbered. Fenced files update between the opening and
    # closing "---"; fence-less files update the leading key:value block up
    # to the first blank line (the conventional body separator).
    start = 0
    end = len(lines)
    if lines and lines[0].strip() == "---":
        start = 1
        end = len(lines)
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
    else:
        for i, line in enumerate(lines):
            if line.strip() == "":
                end = i
                break
    updated: list[str] = []
    for idx in range(start, end):
        line = lines[idx]
        for key, value in updates.items():
            if line.startswith(f"{key}:"):
                lines[idx] = f"{key}: {value}"
                updated.append(key)
    if updated:
        write_atomic(path, "\n".join(lines) + "\n")
    return updated


def extract_json_block(text: str) -> str:
    # Prefer a fenced ```json block, then fall back to the first complete
    # JSON object embedded anywhere in the text. ``raw_decode`` finds the
    # end of a balanced object, so this tolerates trailing prose and nested
    # braces — both of which a non-greedy ``\{.*?\}`` regex mishandles.
    candidates: list[str] = []
    fence = re.search(r"```json\s*(.+?)```", text, flags=re.DOTALL)
    if fence:
        candidates.append(fence.group(1))
    candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        start = candidate.find("{")
        if start == -1:
            continue
        try:
            _obj, end = decoder.raw_decode(candidate, start)
        except ValueError:
            continue
        return candidate[start:end]
    return ""


def dump_json_pretty(payload: Any) -> str:
    return json.dumps(payload, indent=2) + "\n"
