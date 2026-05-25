from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent_config import normalize_fallback_value, normalize_model, parse_agent_config_json, resolve_agent_for_task
from .diagnostics import DiagnosticIssue, issues_from_exception, legacy_issue_message, serialize_issues
from .frontmatter import extract_json_block, find_frontmatter_value
from .utils import ensure_dir, iso_now, read_text, write_atomic


TASKS = ("create", "dev", "auto", "review", "retro")
REQUIRED_TASKS = ("create", "dev", "auto", "review")
COMPLEXITY_LEVELS = {"low", "medium", "high"}


class AgentPlanInputError(ValueError):
    def __init__(self, field: str, exc: Exception) -> None:
        super().__init__(str(exc) or exc.__class__.__name__)
        self.field = field


def validate_complexity_payload(payload: object) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    if not isinstance(payload, dict):
        return [_issue("invalid_type", "payload", "object", payload, "Complexity payload must be an object")]
    stories = payload.get("stories")
    if not isinstance(stories, list):
        return [_issue("invalid_type", "stories", "array", stories, "Complexity stories must be an array")]
    for index, story in enumerate(stories):
        field = f"stories[{index}]"
        if not isinstance(story, dict):
            issues.append(_issue("invalid_type", field, "object", story, "Complexity story must be an object"))
            continue
        story_id = story.get("storyId")
        if not isinstance(story_id, str) or not story_id.strip():
            issues.append(_issue("missing_field", f"{field}.storyId", "non-empty string", story_id, "Complexity storyId must be a non-empty string"))
        complexity = story.get("complexity")
        if complexity is None:
            complexity = {}
        elif not isinstance(complexity, dict):
            issues.append(_issue("invalid_type", f"{field}.complexity", "object", complexity, "Complexity must be an object"))
            continue
        level = str(complexity.get("level") or "medium").strip().lower()
        if level not in COMPLEXITY_LEVELS:
            issues.append(_issue("invalid_value", f"{field}.complexity.level", sorted(COMPLEXITY_LEVELS), level, "Complexity level must be low, medium, or high"))
    return issues


def validate_agents_plan_payload(payload: object) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    if not isinstance(payload, dict):
        return [_issue("invalid_type", "payload", "object", payload, "Agents plan must be an object")]
    stories = payload.get("stories")
    if not isinstance(stories, list):
        return [_issue("invalid_type", "stories", "array", stories, "Agents plan stories must be an array")]
    for index, story in enumerate(stories):
        field = f"stories[{index}]"
        if not isinstance(story, dict):
            issues.append(_issue("invalid_type", field, "object", story, "Agents plan story must be an object"))
            continue
        story_id = story.get("storyId")
        if not isinstance(story_id, str) or not story_id.strip():
            issues.append(_issue("missing_field", f"{field}.storyId", "non-empty string", story_id, "Agents plan storyId must be a non-empty string"))
        tasks = story.get("tasks")
        if not isinstance(tasks, dict):
            issues.append(_issue("invalid_type", f"{field}.tasks", "object", tasks, "Agents plan tasks must be an object"))
            continue
        for task in REQUIRED_TASKS:
            selection = tasks.get(task)
            task_field = f"{field}.tasks.{task}"
            if not isinstance(selection, dict):
                issues.append(_issue("missing_field", task_field, "task selection object", selection, f"Agents plan must include {task} task selection"))
                continue
            _validate_task_selection(issues, selection, task_field, task)
        for task, selection in tasks.items():
            if task in REQUIRED_TASKS:
                continue
            if task != "retro":
                continue
            task_field = f"{field}.tasks.{task}"
            if isinstance(selection, dict):
                _validate_task_selection(issues, selection, task_field, task)
            else:
                issues.append(_issue("invalid_type", task_field, "task selection object", selection, f"{task} task selection must be an object"))
    return issues


def load_complexity_payload(path: str) -> tuple[dict[str, Any], list[DiagnosticIssue]]:
    try:
        payload = json.loads(read_text(path))
    except Exception as exc:
        return {}, issues_from_exception(exc, source="agent-plan", field="complexityFile")
    issues = validate_complexity_payload(payload)
    return payload if isinstance(payload, dict) else {}, issues


def load_agents_plan(path: str) -> tuple[dict[str, Any], list[DiagnosticIssue]]:
    payload, issues = _load_agents_plan_payload(path)
    if issues:
        return payload, issues
    issues = validate_agents_plan_payload(payload)
    return payload if isinstance(payload, dict) else {}, issues


def load_agents_plan_for_resolution(path: str, story_id: str, task: str) -> tuple[dict[str, Any], list[DiagnosticIssue]]:
    payload, issues = _load_agents_plan_payload(path)
    if issues:
        return payload, issues
    issues = _validate_agents_plan_resolution(payload, story_id, task)
    return payload if isinstance(payload, dict) else {}, issues


def build_agents_file(
    state_file: str | Path,
    complexity_file: str | Path,
    output_path: str | Path,
    config_json: str,
    complexity_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        config = parse_agent_config_json(config_json)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AgentPlanInputError("config-json", exc) from exc
    if complexity_payload is None:
        complexity_payload, issues = load_complexity_payload(str(complexity_file))
    else:
        issues = validate_complexity_payload(complexity_payload)
    if issues:
        message = "; ".join(legacy_issue_message(issue) for issue in issues)
        raise AgentPlanInputError("complexity-file", ValueError(message)) from None

    stories = []
    for story in complexity_payload.get("stories", []):
        level = _story_complexity_level(story)
        stories.append({"storyId": story.get("storyId"), "title": str(story.get("title") or ""), "complexity": level, "tasks": _tasks_for(config, level)})
    try:
        epic = find_frontmatter_value(state_file, "epic")
        epic_name = find_frontmatter_value(state_file, "epicName")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise AgentPlanInputError("state-file", exc) from exc

    created_at = iso_now()
    payload = {"version": "1.0.0", "stateFile": str(state_file), "epic": epic, "epicName": epic_name, "createdAt": created_at, "stories": stories}
    header = f"---\nstateFile: {json.dumps(str(state_file))}\ncreatedAt: {json.dumps(created_at)}\n---\n\n# Agents Plan: {epic_name}\n\n```json\n{json.dumps(payload, indent=2)}\n```\n"
    try:
        ensure_dir(Path(output_path).parent)
        write_atomic(output_path, header)
    except OSError as exc:
        raise AgentPlanInputError("output", exc) from exc
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
            "model": normalize_model(selection.get("model")),
            "complexity": story.get("complexity"),
        }
    return {"ok": False, "error": "story_not_found"}


def _load_agents_plan_payload(path: str) -> tuple[dict[str, Any], list[DiagnosticIssue]]:
    try:
        text = read_text(path)
        block = extract_json_block(text)
        if not block:
            return {}, [_issue("missing_field", "agentsFile", "json object", "", "Agents file must contain a JSON object")]
        payload = json.loads(block)
    except Exception as exc:
        return {}, issues_from_exception(exc, source="agent-plan", field="agentsFile")
    if not isinstance(payload, dict):
        return {}, [_issue("invalid_type", "payload", "object", payload, "Agents plan must be an object")]
    stories = payload.get("stories")
    if not isinstance(stories, list):
        return payload, [_issue("invalid_type", "stories", "array", stories, "Agents plan stories must be an array")]
    return payload, []


def _story_complexity_level(story: dict[str, Any]) -> str:
    complexity = story.get("complexity")
    if complexity is None:
        return "medium"
    if not isinstance(complexity, dict):
        raise AgentPlanInputError("complexity-file", ValueError("Complexity must be an object"))
    return str(complexity.get("level") or "medium").strip().lower() or "medium"


def _validate_agents_plan_resolution(payload: dict[str, Any], story_id: str, task: str) -> list[DiagnosticIssue]:
    stories = payload.get("stories") or []
    for index, story in enumerate(stories):
        field = f"stories[{index}]"
        if not isinstance(story, dict):
            return [_issue("invalid_type", field, "object", story, "Agents plan story must be an object")]
        if story.get("storyId") != story_id:
            continue
        tasks = story.get("tasks")
        if not isinstance(tasks, dict):
            return [_issue("invalid_type", f"{field}.tasks", "object", tasks, "Agents plan tasks must be an object")]
        selection = tasks.get(task)
        if selection is None:
            return []
        if not isinstance(selection, dict):
            return [_issue("invalid_type", f"{field}.tasks.{task}", "task selection object", selection, f"{task} task selection must be an object")]
        primary = selection.get("primary")
        if not isinstance(primary, str) or not primary.strip():
            return [_issue("missing_field", f"{field}.tasks.{task}.primary", "non-empty string", primary, f"{task} primary agent must be a non-empty string")]
        fallback = selection.get("fallback", False)
        if not (fallback is False or isinstance(fallback, str)):
            return [_issue("invalid_type", f"{field}.tasks.{task}.fallback", "false or string", fallback, f"{task} fallback must be false or a string")]
        return []
    return []


def agent_plan_error(error: str, issues: list[DiagnosticIssue]) -> dict[str, object]:
    return {"ok": False, "error": error, "structuredIssues": serialize_issues(issues)}


def _tasks_for(config: Any, level: str) -> dict[str, dict[str, str | bool]]:
    tasks = {}
    for task in TASKS:
        primary, fallback, model = resolve_agent_for_task(config, level, task)
        entry: dict[str, str | bool] = {"primary": primary, "fallback": False if fallback == "false" else fallback}
        if model:
            entry["model"] = model
        tasks[task] = entry
    return tasks


def _validate_task_selection(issues: list[DiagnosticIssue], selection: dict[str, Any], task_field: str, task: str) -> None:
    primary = selection.get("primary")
    if not isinstance(primary, str) or not primary.strip():
        issues.append(_issue("missing_field", f"{task_field}.primary", "non-empty string", primary, f"{task} primary agent must be a non-empty string"))
    fallback = selection.get("fallback", False)
    if not (fallback is False or isinstance(fallback, str)):
        issues.append(_issue("invalid_type", f"{task_field}.fallback", "false or string", fallback, f"{task} fallback must be false or a string"))


def _issue(issue_type: str, field: str, expected: Any, actual: Any, message: str) -> DiagnosticIssue:
    return DiagnosticIssue(
        type=issue_type,
        field=field,
        expected=expected,
        actual=actual,
        message=message,
        recovery="Fix the agent plan or complexity JSON payload and retry.",
        code=f"AGENT_PLAN_{issue_type.upper()}",
        source="agent-plan",
    )
