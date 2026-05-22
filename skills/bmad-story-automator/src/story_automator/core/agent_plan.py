from __future__ import annotations

import json
from typing import Any

from .agent_config import extract_json_block, normalize_fallback_value
from .diagnostics import DiagnosticIssue, issues_from_exception, serialize_issues
from .utils import read_text


TASKS = ("create", "dev", "auto", "review")
COMPLEXITY_LEVELS = {"low", "medium", "high"}


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
        for task in TASKS:
            selection = tasks.get(task)
            task_field = f"{field}.tasks.{task}"
            if not isinstance(selection, dict):
                issues.append(_issue("missing_field", task_field, "task selection object", selection, f"Agents plan must include {task} task selection"))
                continue
            primary = selection.get("primary")
            if not isinstance(primary, str) or not primary.strip():
                issues.append(_issue("missing_field", f"{task_field}.primary", "non-empty string", primary, f"{task} primary agent must be a non-empty string"))
            fallback = selection.get("fallback", False)
            if not (fallback is False or isinstance(fallback, str)):
                issues.append(_issue("invalid_type", f"{task_field}.fallback", "false or string", fallback, f"{task} fallback must be false or a string"))
            elif isinstance(fallback, str):
                normalize_fallback_value(fallback)
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
