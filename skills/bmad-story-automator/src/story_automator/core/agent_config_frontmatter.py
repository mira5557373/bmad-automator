from __future__ import annotations

from typing import Any

from .utils import unquote_scalar


def extract_agent_config_frontmatter(frontmatter: str) -> dict[str, object]:
    for index, raw_line in enumerate(frontmatter.splitlines()):
        stripped = raw_line.strip()
        if stripped.startswith("agentConfig:"):
            return _extract_agent_config_block(frontmatter.splitlines(), index)
    return {}


def _extract_agent_config_block(lines: list[str], header_index: int) -> dict[str, object]:
    _, raw_value = lines[header_index].strip().split(":", 1)
    raw_value = _strip_inline_yaml_comment(raw_value)
    if raw_value:
        parsed = _parse_scalar(raw_value)
        return parsed if isinstance(parsed, dict) else {"agentConfig": parsed}

    block: list[str] = []
    for raw_line in lines[header_index + 1 :]:
        if raw_line.startswith("\t"):
            raise ValueError("agentConfig block must use spaces, not tabs")
        if raw_line and not raw_line.startswith(" "):
            if raw_line.strip().startswith(("perTask:", "complexityOverrides:", "retro:")):
                raise ValueError("agentConfig nested sections must be indented")
            break
        block.append(raw_line)
    return _parse_indented_map(block)


def _parse_indented_map(lines: list[str]) -> dict[str, object]:
    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(0, root)]
    for raw_line in lines:
        line = _strip_inline_yaml_comment(raw_line.rstrip())
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError("agentConfig indentation must use two-space levels")
        stripped = line.strip()
        if stripped.startswith("-"):
            raise ValueError("agentConfig lists are not supported")
        if ":" not in stripped:
            raise ValueError("agentConfig entries must be key/value pairs")

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack or indent != stack[-1][0] + 2:
            raise ValueError("agentConfig indentation is invalid")

        key, raw_value = stripped.split(":", 1)
        parent = stack[-1][1]
        value = _parse_scalar(raw_value)
        parent[_parse_key(key)] = value
        if isinstance(value, dict) and not raw_value.strip():
            stack.append((indent, value))
    return root


def _parse_scalar(raw: str) -> object:
    value = _strip_inline_yaml_comment(raw).strip()
    if not value:
        return {}
    if value.startswith("{") and value.endswith("}"):
        return _parse_inline_map(value)
    value = unquote_scalar(value)
    lower = value.lower()
    if lower == "false":
        return False
    if lower == "true":
        return True
    return value


def _parse_inline_map(raw: str) -> dict[str, object]:
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return {}
    output: dict[str, object] = {}
    for item in _split_top_level(inner, ","):
        if ":" not in item:
            raise ValueError("agentConfig inline maps must contain key/value pairs")
        key, value = _split_key_value(item)
        output[_parse_key(key)] = _parse_scalar(value)
    return output


def _split_key_value(raw: str) -> tuple[str, str]:
    parts = _split_top_level(raw, ":", maxsplit=1)
    if len(parts) != 2:
        raise ValueError("agentConfig inline maps must contain key/value pairs")
    return parts[0], parts[1]


def _split_top_level(raw: str, separator: str, *, maxsplit: int = 0) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote = ""
    escaped = False
    for idx, char in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in {'"', "'"}:
            if quote == char:
                quote = ""
            elif not quote:
                quote = char
            continue
        if quote:
            continue
        if char == "{":
            depth += 1
            continue
        if char == "}":
            depth -= 1
            continue
        if char == separator and depth == 0 and (not maxsplit or len(parts) < maxsplit):
            parts.append(raw[start:idx].strip())
            start = idx + 1
    parts.append(raw[start:].strip())
    return parts


def _parse_key(raw: str) -> str:
    return unquote_scalar(raw.strip())


def _strip_inline_yaml_comment(raw: str) -> str:
    text = raw.rstrip()
    quote = ""
    escaped = False
    for idx, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in {'"', "'"}:
            if quote == char:
                quote = ""
            elif not quote:
                quote = char
            continue
        if char == "#" and not quote and (idx == 0 or text[idx - 1].isspace()):
            return text[:idx].rstrip()
    return text
