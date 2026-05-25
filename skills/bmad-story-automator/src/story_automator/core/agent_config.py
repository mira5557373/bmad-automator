from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .agent_config_frontmatter import extract_agent_config_frontmatter
from .common import ensure_dir, file_exists, read_text, write_atomic
from .frontmatter import extract_frontmatter
from .runtime_layout import runtime_provider


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


AGENT_COMPLEXITY_LEVELS = {"low", "medium", "high"}
AGENT_TASKS = {"create", "dev", "auto", "review", "retro"}


def load_presets_file(path: str | Path) -> dict[str, Any]:
    preset_path = Path(path)
    if not file_exists(preset_path):
        return {"version": "1.0.0", "presets": []}
    data = json.loads(read_text(preset_path))
    if not isinstance(data, dict):
        raise ValueError("presets file must be an object")
    data.setdefault("version", "1.0.0")
    data.setdefault("presets", [])
    if not isinstance(data["presets"], list):
        raise ValueError("presets file presets must be an array")
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
        raise ValueError("unexpected nested agentConfig key; pass the inner config object directly")
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
        if level not in AGENT_COMPLEXITY_LEVELS:
            raise ValueError(f"agentConfig.complexityOverrides.{level} is not supported")
        if not isinstance(value, dict):
            raise ValueError(f"agentConfig.complexityOverrides.{level} must be an object")
        parsed = _parse_task_map(value, field=f"complexityOverrides.{level}", strict_entries=True)
        if parsed:
            config.complexity_overrides[level] = parsed
    for level in ("low", "medium", "high"):
        if level not in data:
            continue
        if not isinstance(data[level], dict):
            raise ValueError(f"agentConfig.{level} must be an object")
        parsed = _parse_task_map(data[level], field=level, strict_entries=True)
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
    try:
        config = extract_agent_config_frontmatter(frontmatter)
    except ValueError:
        return False
    for key in ("defaultPrimary", "primary", "defaultFallback", "fallback"):
        value = config.get(key)
        if value not in ("", [], {}, None):
            return True
    for key in ("perTask", "complexityOverrides", "retro"):
        if key in config:
            return True
    return False


def _parse_task_map(raw: Any, *, field: str = "", strict_entries: bool = False) -> dict[str, AgentTaskConfig]:
    if not isinstance(raw, dict):
        return {}
    output: dict[str, AgentTaskConfig] = {}
    for task, entry in raw.items():
        if strict_entries and task not in AGENT_TASKS:
            raise ValueError(f"agentConfig.{field}.{task} is not supported")
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
    allowed = {"primary", "fallback", "model"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"{field}.{unknown[0]} is not supported")
    if "primary" in raw and not _is_non_empty_string(raw["primary"]):
        raise ValueError(f"{field}.primary must be a non-empty string")
    if "fallback" in raw and not (raw["fallback"] is False or _is_non_empty_string(raw["fallback"])):
        raise ValueError(f"{field}.fallback must be a non-empty string or false")


def _is_non_empty_string(raw: Any) -> bool:
    return isinstance(raw, str) and bool(raw.strip())


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
    from .frontmatter import extract_json_block as _extract_json_block

    return _extract_json_block(text)


def build_agents_file(
    state_file: str | Path,
    complexity_file: str | Path,
    output_path: str | Path,
    config_json: str,
    complexity_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .agent_plan import build_agents_file as _build_agents_file

    return _build_agents_file(state_file, complexity_file, output_path, config_json, complexity_payload=complexity_payload)


def resolve_agents(agents_file: str | Path, story_id: str, task: str) -> dict[str, Any]:
    from .agent_plan import resolve_agents as _resolve_agents

    return _resolve_agents(agents_file, story_id, task)


def resolve_agents_payload(payload: dict[str, Any], story_id: str, task: str) -> dict[str, Any]:
    from .agent_plan import resolve_agents_payload as _resolve_agents_payload

    return _resolve_agents_payload(payload, story_id, task)


def __getattr__(name: str) -> Any:
    if name == "AgentPlanInputError":
        from .agent_plan import AgentPlanInputError

        return AgentPlanInputError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
