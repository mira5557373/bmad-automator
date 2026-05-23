from __future__ import annotations

import json
import re
from pathlib import Path

from story_automator.core.artifact_paths import implementation_artifacts_dir
from story_automator.core.agent_config import AgentConfigResolved, load_agent_config_from_state, parse_agent_config_json, resolve_agent_for_task
from story_automator.core.agent_plan import AgentPlanInputError, agent_plan_error, build_agents_file, load_agents_plan_for_resolution, load_complexity_payload, resolve_agents_payload
from story_automator.core.diagnostics import issues_from_exception
from story_automator.core.frontmatter import find_frontmatter_value, parse_frontmatter
from story_automator.core.sprint import sprint_status_epic
from story_automator.core.story_keys import StoryKey, normalize_story_key, normalize_story_key_for_epic
from story_automator.core.utils import file_exists, get_project_root, print_json, read_text, trim_lines


def check_epic_complete_action(args: list[str]) -> int:
    try:
        if len(args) < 2:
            print_json({"ok": False, "error": "epic_number and story_id required"})
            return 1
        epic, story = args[0], args[1]
        project_root = get_project_root()
        state_file = ""
        tail = args[2:]
        for idx, arg in enumerate(tail):
            if arg == "--state-file" and idx + 1 < len(tail):
                state_file = tail[idx + 1]
        story_norm = normalize_story_key_for_epic(project_root, epic, story)
        story_epic = story_norm.id.rsplit(".", 1)[0] if story_norm is not None else story.split(".", 1)[0]
        epic_value = _epic_json_value(epic)
        if story_epic != epic:
            print_json({"ok": True, "isLastStory": False, "epic": epic_value, "storyId": story, "reason": "story_not_in_epic"})
            return 0
        stories: list[str] = []
        if state_file and file_exists(state_file):
            story_range = parse_frontmatter(read_text(state_file)).get("storyRange", [])
            stories = [sid for sid in story_range if isinstance(sid, str) and _story_matches_epic(project_root, epic, sid)]
            source = "state_file"
        else:
            stories, _ = sprint_status_epic(project_root, epic)
            source = "sprint_status"
        if stories:
            stories = sorted(_dedupe_stories_for_epic(project_root, epic, stories), key=lambda item: _story_sort_key(project_root, item, epic))
            last = stories[-1]
            print_json({"ok": True, "isLastStory": _same_story(project_root, epic, story, last), "epic": epic_value, "storyId": story, "lastInEpic": last, "epicStoryCount": len(stories), "source": source})
            return 0
        print_json({"ok": True, "isLastStory": False, "epic": epic_value, "storyId": story, "reason": "could_not_determine", "source": "fallback"})
        return 0
    except (OSError, ValueError) as exc:
        print_json({"ok": False, "isLastStory": False, "epic": _epic_json_value(args[0]) if args else "", "storyId": args[1] if len(args) > 1 else "", "reason": str(exc), "source": "unknown"})
        return 1


def get_epic_stories_action(args: list[str]) -> int:
    try:
        if not args:
            print_json({"ok": False, "error": "epic_number_required"})
            return 1
        epic = args[0]
        state_file = ""
        tail = args[1:]
        for idx, arg in enumerate(tail):
            if arg == "--state-file" and idx + 1 < len(tail):
                state_file = tail[idx + 1]
        if state_file and file_exists(state_file):
            project_root = get_project_root()
            stories = [sid for sid in parse_frontmatter(read_text(state_file)).get("storyRange", []) if isinstance(sid, str) and _story_matches_epic(project_root, epic, sid)]
            if stories:
                stories = _dedupe_stories_for_epic(project_root, epic, stories)
                print_json({"ok": True, "epic": epic, "stories": stories, "count": len(stories), "source": "state_file"})
                return 0
        stories, _ = sprint_status_epic(get_project_root(), epic)
        if stories:
            print_json({"ok": True, "epic": epic, "stories": stories, "count": len(stories), "source": "sprint_status"})
            return 0
        epic_file = find_epic_file(epic)
        if epic_file:
            project_root = get_project_root()
            stories = sorted(_story_ids_from_epic_file(epic_file, epic), key=lambda item: _story_sort_key(project_root, item, epic))
            if stories:
                print_json({"ok": True, "epic": epic, "stories": stories, "count": len(stories), "source": "epic_file"})
                return 0
        print_json({"ok": False, "epic": epic, "error": "no_stories_found", "count": 0})
        return 0
    except (OSError, ValueError) as exc:
        print_json({"ok": False, "epic": args[0] if args else "", "error": str(exc), "count": 0})
        return 1


def check_blocking_action(args: list[str]) -> int:
    try:
        if not args:
            print_json({"ok": False, "error": "story_id_required"})
            return 1
        project_root = get_project_root()
        norm = normalize_story_key(project_root, args[0])
        if norm is None:
            print_json({"ok": False, "error": "could_not_normalize_key", "input": args[0]})
            return 1
        epic = norm.id.split(".", 1)[0]
        epic_file = find_epic_file(epic)
        if not epic_file:
            print_json({"ok": True, "blocking": True, "story": norm.id, "epic": epic, "dependents": [], "reason": "epic_file_not_found", "source": "unknown"})
            return 0
        dependents: list[str] = []
        current_story = ""
        for line in trim_lines(read_text(epic_file)):
            match = re.match(r"^###\s+Story\s+([^:]+):", line)
            if match:
                candidate_story = match.group(1).strip()
                current_story = candidate_story if _story_matches_epic(project_root, epic, candidate_story) else ""
                continue
            if current_story and re.search(r"(?i)Dependencies:|\*\*Dependencies\*\*:", line):
                if _line_references_story(project_root, epic, norm, args[0], line):
                    dependents.append(current_story)
        if dependents:
            print_json({"ok": True, "blocking": True, "story": norm.id, "epic": epic, "dependents": sorted(set(dependents), key=lambda item: _story_sort_key(project_root, item, epic)), "reason": "dependent_stories", "source": "epic_file"})
            return 0
        print_json({"ok": True, "blocking": False, "story": norm.id, "epic": epic, "dependents": [], "reason": "no_dependents_found", "source": "epic_file"})
        return 0
    except (OSError, ValueError) as exc:
        print_json({"ok": False, "blocking": True, "story": args[0] if args else "", "error": str(exc), "dependents": [], "source": "unknown"})
        return 1


def agents_build_action(args: list[str]) -> int:
    options = {"state-file": "", "complexity-file": "", "output": "", "config-json": ""}
    idx = 0
    while idx < len(args):
        key = args[idx].lstrip("-")
        if idx + 1 < len(args):
            options[key] = args[idx + 1]
            idx += 2
        else:
            idx += 1
    if not all(options.values()) or not file_exists(options["state-file"]) or not file_exists(options["complexity-file"]):
        print_json({"ok": False, "error": "missing_args" if not all(options.values()) else "file_not_found"})
        return 1
    complexity_payload, issues = load_complexity_payload(options["complexity-file"])
    if issues:
        print_json(agent_plan_error("invalid_complexity_json", issues))
        return 1
    try:
        payload = build_agents_file(options["state-file"], options["complexity-file"], options["output"], options["config-json"], complexity_payload=complexity_payload)
    except AgentPlanInputError as exc:
        cause = exc.__cause__ if isinstance(exc.__cause__, Exception) else exc
        print_json(agent_plan_error("invalid_agent_config", issues_from_exception(cause, source="agent-plan", field=exc.field)))
        return 1
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print_json(agent_plan_error("invalid_agent_config", issues_from_exception(exc, source="agent-plan", field="config-json")))
        return 1
    print_json(payload)
    return 0


def agents_resolve_action(args: list[str]) -> int:
    options = {"state-file": "", "agents-file": "", "story": "", "task": ""}
    idx = 0
    while idx < len(args):
        key = args[idx].lstrip("-")
        if idx + 1 < len(args):
            options[key] = args[idx + 1]
            idx += 2
        else:
            idx += 1
    if not options["story"] or not options["task"] or (not options["state-file"] and not options["agents-file"]):
        print_json({"ok": False, "error": "missing_args"})
        return 1
    agents_path = options["agents-file"] or find_frontmatter_value(options["state-file"], "agentsFile")
    if not agents_path or not file_exists(agents_path):
        print_json({"ok": False, "error": "agents_file_not_found"})
        return 1
    agents_plan, issues = load_agents_plan_for_resolution(agents_path, options["story"], options["task"])
    if issues:
        print_json(agent_plan_error("invalid_agents_json", issues))
        return 1
    payload = resolve_agents_payload(agents_plan, options["story"], options["task"])
    print_json(payload)
    return 0 if bool(payload.get("ok")) else 1


def retro_agent_action(args: list[str]) -> int:
    options = {"state-file": ""}
    idx = 0
    while idx < len(args):
        key = args[idx].lstrip("-")
        if idx + 1 < len(args):
            options[key] = args[idx + 1]
            idx += 2
        else:
            idx += 1
    if not options["state-file"]:
        print_json({"ok": False, "error": "missing_args"})
        return 1
    if not file_exists(options["state-file"]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    try:
        config = _load_agent_config_from_state(options["state-file"])
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print_json(agent_plan_error("invalid_agent_config", issues_from_exception(exc, source="agent-plan", field="state-file")))
        return 1
    primary, fallback, model = resolve_agent_for_task(config, "medium", "retro")
    print_json({"ok": True, "task": "retro", "primary": primary, "fallback": fallback, "model": model})
    return 0


def find_epic_file(epic: str) -> str:
    root = Path(get_project_root())
    for base in (implementation_artifacts_dir(root), root / "docs" / "epics"):
        exact = base / f"epic-{epic}.md"
        if exact.is_file() and _epic_file_has_story(exact, epic, project_root=str(root)):
            return str(exact)
        matches = sorted(base.glob(f"epic-{epic}-*.md"))
        for match in matches:
            if _epic_file_has_story(match, epic, project_root=str(root)):
                return str(match)
    return ""


def _epic_file_has_story(epic_file: Path, epic: str, *, project_root: str) -> bool:
    story_re = re.compile(r"^###\s+Story\s+([^:]+):")
    for line in trim_lines(read_text(epic_file)):
        match = story_re.match(line)
        if match and _story_matches_epic(project_root, epic, match.group(1).strip()):
            return True
    return False


def _epic_json_value(epic: str) -> int | str:
    return int(epic) if epic.isdigit() else epic


def _story_ids_from_epic_file(epic_file: str, epic: str) -> list[str]:
    story_re = re.compile(r"^###\s+Story\s+([^:]+):")
    stories: list[str] = []
    seen_ids: set[str] = set()
    project_root = get_project_root()
    for line in trim_lines(read_text(epic_file)):
        match = story_re.match(line)
        if not match:
            continue
        story = match.group(1).strip()
        norm = normalize_story_key_for_epic(project_root, epic, story)
        if norm is None or norm.id.rsplit(".", 1)[0] != epic or norm.id in seen_ids:
            continue
        stories.append(story)
        seen_ids.add(norm.id)
    return stories


def _story_matches_epic(project_root: str, epic: str, story: str) -> bool:
    norm = normalize_story_key_for_epic(project_root, epic, story)
    if norm is not None:
        return norm.id.rsplit(".", 1)[0] == epic
    return False


def _story_sort_key(project_root: str, story: str, epic: str = "") -> tuple[int, str]:
    norm = normalize_story_key_for_epic(project_root, epic, story) if epic else normalize_story_key(project_root, story)
    if norm is not None:
        _, _, story_num = norm.id.rpartition(".")
        if story_num.isdigit():
            return (int(story_num), norm.id)
    return (0, story)


def _same_story(project_root: str, epic: str, left: str, right: str) -> bool:
    left_norm = normalize_story_key_for_epic(project_root, epic, left)
    right_norm = normalize_story_key_for_epic(project_root, epic, right)
    if left_norm is not None and right_norm is not None:
        if _is_explicit_full_key(left, left_norm):
            return left == right
        return left_norm.id == right_norm.id
    return left == right


def _dedupe_stories_for_epic(project_root: str, epic: str, stories: list[str]) -> list[str]:
    story_order: list[str] = []
    story_rows: dict[str, tuple[int, str]] = {}
    for story in stories:
        norm = normalize_story_key_for_epic(project_root, epic, story)
        story_id = norm.id if norm is not None else story
        if story_id not in story_rows:
            story_order.append(story_id)
        rank = _story_key_rank(story, norm)
        previous = story_rows.get(story_id)
        if previous is None or rank >= previous[0]:
            story_rows[story_id] = (rank, story)
    return [story_rows[story_id][1] for story_id in story_order]


def _story_key_rank(story: str, norm: StoryKey | None) -> int:
    if norm is not None and story == norm.key and story not in {norm.id, norm.prefix}:
        return 2
    return 1


def _line_references_story(project_root: str, epic: str, target: StoryKey, requested_story: str, line: str) -> bool:
    requested_full_key = _is_explicit_full_key(requested_story, target)
    for match in re.finditer(r"\b(?:\d+\.\d+|\d+-\d+(?:-[\w]+)*|[A-Za-z][\w-]*(?:\.\d+|-\d+(?:-[\w]+)*))\b", line):
        token = match.group(0)
        norm = normalize_story_key_for_epic(project_root, epic, token)
        if norm is not None and norm.id == target.id:
            if requested_full_key and _is_explicit_full_key(token, norm):
                return token == requested_story
            return True
    return False


def _is_explicit_full_key(value: str, norm: StoryKey) -> bool:
    return value == norm.key and value not in {norm.id, norm.prefix}


def parse_agent_config(raw: str) -> dict:
    config = parse_agent_config_json(raw)
    return {
        "defaultPrimary": config.default_primary,
        "defaultFallback": config.default_fallback,
        "defaultModel": config.default_model,
        "perTask": {
            task: _task_config_to_dict(task_config)
            for task, task_config in config.per_task.items()
        },
        "complexityOverrides": {
            level: {
                task: _task_config_to_dict(task_config)
                for task, task_config in task_map.items()
            }
            for level, task_map in config.complexity_overrides.items()
        },
    }


def resolve_agent(config: dict | AgentConfigResolved, level: str, task: str) -> tuple[str, str, str]:
    core_config = config if isinstance(config, AgentConfigResolved) else _legacy_config_to_core(config)
    return resolve_agent_for_task(core_config, level, task)


def _task_config_to_dict(task_config: object) -> dict[str, object]:
    primary = getattr(task_config, "primary", "")
    fallback = getattr(task_config, "fallback", None)
    model = getattr(task_config, "model", None)
    payload: dict[str, object] = {"primary": primary, "fallback": fallback}
    if model is not None:
        payload["model"] = model
    return payload


def _load_agent_config_from_state(state_file: str) -> AgentConfigResolved:
    return load_agent_config_from_state(state_file)


def _legacy_config_to_core(config: dict) -> AgentConfigResolved:
    return parse_agent_config_json(
        json.dumps(
            {
                "defaultPrimary": config.get("defaultPrimary", "auto"),
                "defaultFallback": config.get("defaultFallback", False),
                "defaultModel": config.get("defaultModel", ""),
                "perTask": config.get("perTask", {}),
                "complexityOverrides": config.get("complexityOverrides", {}),
            }
        )
    )
