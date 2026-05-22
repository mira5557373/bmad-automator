from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import ensure_dir, file_exists, iso_now, read_text, write_atomic
from .frontmatter import extract_frontmatter, find_frontmatter_value
from .runtime_layout import runtime_provider
from .utils import unquote_scalar


@dataclass
class AgentTaskConfig:
    primary: str = ""
    fallback: Any = None
    # Three-state field: `None` = key not provided (inherit defaultModel);
    # `""`   = key present but normalized to a sentinel (explicit "use CLI
    #          default" — must CLEAR an inherited defaultModel);
    # `<id>` = explicit model override.
    model: str | None = None


@dataclass
class AgentConfigResolved:
    default_primary: str = "auto"
    default_fallback: str = "false"
    default_model: str = ""
    per_task: dict[str, AgentTaskConfig] = field(default_factory=dict)
    complexity_overrides: dict[str, dict[str, AgentTaskConfig]] = field(default_factory=dict)


AGENT_CONFIG_HEADER_RE = re.compile(r"^agentConfig:\s*(?:#.*)?$")


def load_presets_file(path: str | Path) -> dict[str, Any]:
    preset_path = Path(path)
    if not file_exists(preset_path):
        return {"version": "1.0.0", "presets": []}
    data = json.loads(read_text(preset_path))
    data.setdefault("version", "1.0.0")
    data.setdefault("presets", [])
    return data


def save_presets_file(path: str | Path, data: dict[str, Any]) -> None:
    ensure_dir(Path(path).parent)
    write_atomic(path, json.dumps(data, indent=2) + "\n")


def parse_agent_config_json(raw: str) -> AgentConfigResolved:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("agentConfig must be an object")
    config = AgentConfigResolved()
    if "agentConfig" in data and data.get("agentConfig") not in ("", None):
        raise ValueError("agentConfig must be an object")
    config.default_primary = data.get("defaultPrimary") or data.get("primary") or "auto"
    if "defaultFallback" in data:
        fallback_raw = data.get("defaultFallback")
    elif "fallback" in data:
        fallback_raw = data.get("fallback")
    else:
        fallback_raw = False
    normalized_fallback = normalize_fallback_value(fallback_raw)
    config.default_fallback = normalized_fallback or "false"
    config.default_model = _normalize_model(data.get("defaultModel"))
    config.per_task = _parse_task_map(data.get("perTask"))
    retro_task = _parse_task_entry(data.get("retro"))
    if retro_task is not None:
        config.per_task.setdefault("retro", retro_task)
    complexity_raw = data.get("complexityOverrides", {})
    if "complexityOverrides" in data and complexity_raw is None:
        raise ValueError("agentConfig.complexityOverrides must be an object")
    if not isinstance(complexity_raw, dict):
        raise ValueError("agentConfig.complexityOverrides must be an object")
    for level, value in complexity_raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"agentConfig.complexityOverrides.{level} must be an object")
        parsed = _parse_task_map(value, field=f"complexityOverrides.{level}", strict_entries=True)
        if parsed:
            config.complexity_overrides[level] = parsed
    for level in ("low", "medium", "high"):
        if level not in data:
            continue
        parsed = _parse_task_map(data[level])
        if not parsed:
            continue
        existing = config.complexity_overrides.setdefault(level, {})
        for task, entry in parsed.items():
            existing.setdefault(task, entry)
    return config


def load_agent_config_from_state(state_file: str | Path) -> AgentConfigResolved:
    text = read_text(state_file)
    if text.startswith("---") and len(text.split("---", 2)) < 3:
        raise ValueError("state frontmatter is unterminated")
    return parse_agent_config_frontmatter(extract_frontmatter(text))


def parse_agent_config_frontmatter(frontmatter: str) -> AgentConfigResolved:
    return parse_agent_config_json(json.dumps(extract_agent_config_frontmatter(frontmatter)))


def has_agent_config_runtime_source(frontmatter: str) -> bool:
    config = extract_agent_config_frontmatter(frontmatter)
    for key in ("defaultPrimary", "primary", "defaultFallback", "fallback"):
        value = config.get(key)
        if value not in ("", [], None):
            return True
    for key in ("perTask", "complexityOverrides", "retro"):
        if key in config:
            return True
    return False


def extract_agent_config_frontmatter(frontmatter: str) -> dict[str, object]:
    config: dict[str, object] = {}
    in_agent_config = False
    in_per_task = False
    in_complexity_overrides = False
    current_task = ""
    current_level = ""

    for raw_line in frontmatter.splitlines():
        if not in_agent_config:
            if AGENT_CONFIG_HEADER_RE.match(raw_line.strip()):
                in_agent_config = True
                continue
            if raw_line.strip().startswith("agentConfig:"):
                key, raw = raw_line.strip().split(":", 1)
                config[_parse_key(key)] = _parse_scalar(raw)
            continue

        if raw_line.startswith("\t"):
            config["agentConfig"] = _parse_scalar(raw_line.strip())
            continue

        if raw_line and not raw_line.startswith(" "):
            break

        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent != 2 and _is_misindented_agent_config_section(stripped, in_per_task, in_complexity_overrides):
            config[_parse_key(stripped.split(":", 1)[0])] = _parse_scalar(stripped)
        if indent == 2:
            current_task = ""
            current_level = ""
            if stripped == "perTask:":
                in_per_task = True
                in_complexity_overrides = False
                config.setdefault("perTask", {})
                continue
            if stripped == "perTask: {}":
                in_per_task = False
                in_complexity_overrides = False
                config.setdefault("perTask", {})
                continue
            if stripped == "complexityOverrides:":
                in_complexity_overrides = True
                in_per_task = False
                config.setdefault("complexityOverrides", {})
                continue
            if stripped == "complexityOverrides: {}":
                in_complexity_overrides = False
                in_per_task = False
                config.setdefault("complexityOverrides", {})
                continue
            in_per_task = False
            in_complexity_overrides = False
            if stripped == "retro:":
                config.setdefault("retro", {})
                current_task = "retro"
                continue
            if ":" in stripped:
                key, raw = stripped.split(":", 1)
                config[_parse_key(key)] = _parse_scalar(raw)
            continue

        if indent == 4 and in_per_task and stripped.endswith(":"):
            current_task = _parse_key(stripped[:-1])
            per_task = config.setdefault("perTask", {})
            if isinstance(per_task, dict):
                per_task.setdefault(current_task, {})
            continue

        if indent == 4 and in_complexity_overrides and ":" in stripped:
            key, raw = stripped.split(":", 1)
            current_level = _parse_key(key)
            current_task = ""
            overrides = config.setdefault("complexityOverrides", {})
            if isinstance(overrides, dict):
                if current_level.startswith("-"):
                    overrides[current_level] = _parse_scalar(stripped)
                    continue
                if _has_scalar_value(raw):
                    overrides[current_level] = _parse_scalar(raw.strip())
                else:
                    overrides.setdefault(current_level, {})
            continue

        if indent == 4 and current_task == "retro" and ":" in stripped:
            key, raw = stripped.split(":", 1)
            retro = config.setdefault("retro", {})
            if isinstance(retro, dict):
                retro[_parse_key(key)] = _parse_scalar(raw.strip())
            continue

        if indent == 6 and in_per_task and current_task and ":" in stripped:
            key, raw = stripped.split(":", 1)
            per_task = config.setdefault("perTask", {})
            if isinstance(per_task, dict):
                task_cfg = per_task.setdefault(current_task, {})
                if isinstance(task_cfg, dict):
                    task_cfg[_parse_key(key)] = _parse_scalar(raw.strip())
            continue

        if indent == 6 and in_complexity_overrides and current_level and stripped.startswith("-"):
            overrides = config.setdefault("complexityOverrides", {})
            if isinstance(overrides, dict):
                overrides[current_level] = _parse_scalar(stripped)
            continue

        if indent == 6 and in_complexity_overrides and current_level and ":" in stripped:
            key, raw = stripped.split(":", 1)
            current_task = _parse_key(key)
            overrides = config.setdefault("complexityOverrides", {})
            if isinstance(overrides, dict):
                level_cfg = overrides.setdefault(current_level, {})
                if isinstance(level_cfg, dict):
                    if _has_scalar_value(raw):
                        level_cfg[current_task] = _parse_scalar(raw.strip())
                    else:
                        level_cfg.setdefault(current_task, {})
            continue

        if indent >= 8 and in_complexity_overrides and current_level and current_task and stripped.startswith("-"):
            overrides = config.setdefault("complexityOverrides", {})
            if isinstance(overrides, dict):
                level_cfg = overrides.setdefault(current_level, {})
                if isinstance(level_cfg, dict):
                    level_cfg[current_task] = _parse_scalar(stripped)
            continue

        if indent == 8 and in_complexity_overrides and current_level and current_task and ":" in stripped:
            key, raw = stripped.split(":", 1)
            overrides = config.setdefault("complexityOverrides", {})
            if isinstance(overrides, dict):
                level_cfg = overrides.setdefault(current_level, {})
                if isinstance(level_cfg, dict):
                    task_cfg = level_cfg.setdefault(current_task, {})
                    if isinstance(task_cfg, dict):
                        task_cfg[_parse_key(key)] = _parse_scalar(raw.strip())
            continue

        if in_complexity_overrides and indent > 2:
            overrides = config.setdefault("complexityOverrides", {})
            if current_level and isinstance(overrides, dict):
                if current_task:
                    level_cfg = overrides.setdefault(current_level, {})
                    if isinstance(level_cfg, dict):
                        level_cfg[current_task] = _parse_scalar(stripped)
                else:
                    overrides[current_level] = _parse_scalar(stripped)
            else:
                config["complexityOverrides"] = _parse_scalar(stripped)

    return config


def _parse_task_map(raw: Any, *, field: str = "", strict_entries: bool = False) -> dict[str, AgentTaskConfig]:
    if not isinstance(raw, dict):
        return {}
    output: dict[str, AgentTaskConfig] = {}
    for task, entry in raw.items():
        if strict_entries and not isinstance(entry, dict):
            raise ValueError(f"agentConfig.{field}.{task} must be an object")
        if strict_entries and isinstance(entry, dict):
            _validate_task_entry(entry, f"agentConfig.{field}.{task}")
        parsed = _parse_task_entry(entry)
        if parsed is None or not _task_config_has_values(parsed):
            continue
        output[task] = parsed
    return output


def _parse_task_entry(raw: Any) -> AgentTaskConfig | None:
    if not isinstance(raw, dict):
        return None
    # Distinguish "model key absent" (None → inherit) from "model key present
    # but a sentinel/empty value" ("" → explicit clear of inherited default).
    model: str | None
    if "model" in raw:
        model = _normalize_model(raw.get("model"))
    else:
        model = None
    primary = raw.get("primary")
    return AgentTaskConfig(
        primary=str(primary or ""),
        fallback=raw.get("fallback"),
        model=model,
    )


# Tokens that mean "use the CLI's built-in default" — never persisted, never
# forwarded as `--model`. Kept in one place (`MODEL_SENTINELS` /
# `normalize_model`) so every layer agrees on what counts as an opt-out.
MODEL_SENTINELS = frozenset({"false", "none", "null", "auto", "default"})


def normalize_model(raw: Any) -> str:
    """Return a real model ID, or `""` for any sentinel / falsy / non-string.

    Used by every consumer (config parser, dict resolver, state serializer)
    so the sentinel set stays in lock-step across layers.
    """
    if raw is None or raw is False:
        return ""
    value = str(raw).strip()
    if not value:
        return ""
    if value.lower() in MODEL_SENTINELS:
        return ""
    return value


# Backward-compatible private alias for in-module callers.
_normalize_model = normalize_model


def _validate_task_entry(raw: dict[str, Any], field: str) -> None:
    allowed = {"primary", "fallback"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{field}.{unknown[0]} is not supported")
    if "primary" in raw and _is_empty_agent_value(raw["primary"]):
        raise ValueError(f"{field}.primary must be a non-empty string")
    if "fallback" in raw and _is_empty_agent_value(raw["fallback"]):
        raise ValueError(f"{field}.fallback must be a non-empty string or false")


def _is_empty_agent_value(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


def render_agent_config_frontmatter(raw_config: dict[str, Any]) -> str:
    config = parse_agent_config_json(json.dumps(raw_config))
    lines = [
        "agentConfig:",
        f"  defaultPrimary: {json.dumps(config.default_primary)}",
        f"  defaultFallback: {_render_fallback(config.default_fallback)}",
    ]
    if "defaultModel" in raw_config:
        lines.append(f"  defaultModel: {json.dumps(config.default_model)}")
    _append_task_map(lines, "perTask", config.per_task, indent=2)
    override_lines: list[str] = []
    for level in sorted(config.complexity_overrides):
        task_map = _non_empty_task_map(config.complexity_overrides[level])
        if not task_map:
            continue
        override_lines.append(f"    {level}:")
        _append_task_entries(override_lines, task_map, indent=6)
    if override_lines:
        lines.append("  complexityOverrides:")
        lines.extend(override_lines)
    return "\n".join(lines) + "\n"


def _append_task_map(lines: list[str], label: str, task_map: dict[str, AgentTaskConfig], *, indent: int) -> None:
    task_map = _non_empty_task_map(task_map)
    if not task_map:
        return
    lines.append(f"{' ' * indent}{label}:")
    _append_task_entries(lines, task_map, indent=indent + 2)


def _append_task_entries(lines: list[str], task_map: dict[str, AgentTaskConfig], *, indent: int) -> None:
    for task in sorted(task_map):
        entry = task_map[task]
        lines.append(f"{' ' * indent}{task}:")
        if entry.primary:
            lines.append(f"{' ' * (indent + 2)}primary: {json.dumps(entry.primary)}")
        if entry.fallback is not None:
            lines.append(f"{' ' * (indent + 2)}fallback: {_render_fallback(entry.fallback)}")
        if entry.model is not None:
            lines.append(f"{' ' * (indent + 2)}model: {json.dumps(entry.model)}")


def _non_empty_task_map(task_map: dict[str, AgentTaskConfig]) -> dict[str, AgentTaskConfig]:
    return {
        task: entry
        for task, entry in task_map.items()
        if _task_config_has_values(entry)
    }


def _task_config_has_values(entry: AgentTaskConfig) -> bool:
    return bool(entry.primary or entry.fallback is not None or entry.model is not None)


def _render_fallback(raw: Any) -> str:
    normalized = normalize_fallback_value(raw)
    if normalized == "false":
        return "false"
    return json.dumps(normalized)


def normalize_fallback_value(raw: Any) -> str:
    if isinstance(raw, str):
        lower = raw.strip().lower()
        if lower in {"false", "none", "null"}:
            return "false"
        return lower
    if isinstance(raw, bool):
        return "true" if raw else "false"
    return ""


def resolve_agent_for_task(config: AgentConfigResolved, complexity: str, task: str) -> tuple[str, str, str]:
    primary = config.default_primary or "auto"
    fallback = config.default_fallback or "false"
    model = config.default_model or ""
    per_task = config.per_task.get(task)
    if per_task:
        if per_task.primary:
            primary = per_task.primary
        if per_task.fallback is not None:
            fallback = normalize_fallback_value(per_task.fallback)
        # `is not None` so an explicit sentinel ("" after _normalize_model)
        # clears an inherited defaultModel — the documented opt-out semantics.
        if per_task.model is not None:
            model = per_task.model
    by_level = config.complexity_overrides.get(complexity, {})
    override = by_level.get(task)
    if override:
        if override.primary:
            primary = override.primary
        if override.fallback is not None:
            fallback = normalize_fallback_value(override.fallback)
        if override.model is not None:
            model = override.model
    return _resolve_primary_agent(primary), _resolve_fallback_agent(fallback), model


def _resolve_primary_agent(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value in {"", "auto", "runtime"}:
        return runtime_provider()
    return value


def _resolve_fallback_agent(raw: Any) -> str:
    value = normalize_fallback_value(raw)
    normalized = str(value).strip().lower()
    if normalized in {"", "auto", "runtime"}:
        return "false"
    return normalized


def extract_json_block(text: str) -> str:
    match = re.search(r"(?s)```json\s*(\{.*?\})\s*```", text)
    if match:
        return match.group(1)
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    return ""


def build_agents_file(state_file: str | Path, complexity_file: str | Path, output_path: str | Path, config_json: str) -> dict[str, Any]:
    config = parse_agent_config_json(config_json)
    complexity_payload = json.loads(read_text(complexity_file))
    stories = []
    for story in complexity_payload.get("stories", []):
        level = str(((story.get("complexity") or {}).get("level")) or "medium").strip().lower() or "medium"
        tasks = {}
        for task in ("create", "dev", "auto", "review"):
            primary, fallback, model = resolve_agent_for_task(config, level, task)
            entry: dict[str, Any] = {
                "primary": primary,
                "fallback": False if fallback == "false" else fallback,
            }
            if model:
                entry["model"] = model
            tasks[task] = entry
        stories.append(
            {
                "storyId": story.get("storyId"),
                "title": story.get("title"),
                "complexity": level,
                "tasks": tasks,
            }
        )
    payload = {
        "version": "1.0.0",
        "stateFile": str(state_file),
        "epic": find_frontmatter_value(state_file, "epic"),
        "epicName": find_frontmatter_value(state_file, "epicName"),
        "createdAt": iso_now(),
        "stories": stories,
    }
    header = (
        f"---\nstateFile: {json.dumps(str(state_file))}\ncreatedAt: {json.dumps(payload['createdAt'])}\n---\n\n"
        f"# Agents Plan: {payload['epicName']}\n\n```json\n{json.dumps(payload, indent=2)}\n```\n"
    )
    ensure_dir(Path(output_path).parent)
    write_atomic(output_path, header)
    return {"ok": True, "path": str(output_path), "stories": len(stories)}


def resolve_agents(agents_file: str | Path, story_id: str, task: str) -> dict[str, Any]:
    text = read_text(agents_file)
    block = extract_json_block(text)
    if not block:
        return {"ok": False, "error": "agents_json_missing"}
    payload = json.loads(block)
    return resolve_agents_payload(payload, story_id, task)


def resolve_agents_payload(payload: dict[str, Any], story_id: str, task: str) -> dict[str, Any]:
    for story in payload.get("stories", []):
        if story.get("storyId") != story_id:
            continue
        selection = (story.get("tasks") or {}).get(task)
        if not selection:
            return {"ok": False, "error": "task_not_found"}
        fallback = normalize_fallback_value(selection.get("fallback"))
        return {
            "ok": True,
            "story": story_id,
            "task": task,
            "primary": selection.get("primary"),
            "fallback": fallback,
            "model": _normalize_model(selection.get("model")),
            "complexity": story.get("complexity"),
        }
    return {"ok": False, "error": "story_not_found"}


def _parse_scalar(raw: str) -> object:
    value = unquote_scalar(_strip_inline_yaml_comment(raw))
    lower = value.lower()
    if lower == "false":
        return False
    if lower == "true":
        return True
    return value


def _parse_key(raw: str) -> str:
    return unquote_scalar(raw.strip())


def _is_misindented_agent_config_section(stripped: str, in_per_task: bool, in_complexity_overrides: bool) -> bool:
    if ":" not in stripped:
        return False
    key, _ = stripped.split(":", 1)
    parsed_key = _parse_key(key)
    if parsed_key in {"perTask", "complexityOverrides"}:
        return True
    return parsed_key == "retro" and not in_per_task and not in_complexity_overrides


def _has_scalar_value(raw: str) -> bool:
    return bool(_strip_inline_yaml_comment(raw).strip())


def _strip_inline_yaml_comment(raw: str) -> str:
    text = raw.strip()
    in_quote = ""
    escaped = False
    for idx, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_quote == '"':
            escaped = True
            continue
        if char in {'"', "'"}:
            if in_quote == char:
                in_quote = ""
            elif not in_quote:
                in_quote = char
            continue
        if char == "#" and not in_quote and (idx == 0 or text[idx - 1].isspace()):
            return text[:idx].rstrip()
    return text
