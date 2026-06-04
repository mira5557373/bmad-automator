from __future__ import annotations

import json
import re

from story_automator.core.frontmatter import parse_simple_frontmatter
from story_automator.core.orchestration_events import emit_state_fields_updated, emit_state_transition
from story_automator.core.state_validation import parse_state_update_argument, status_transition_error_payload, validate_status_transition
from story_automator.core.utils import file_exists, print_json, read_text, write_atomic


def state_update_action(args: list[str]) -> int:
    if not args or not file_exists(args[0]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    text = read_text(args[0])
    frontmatter, body = _split_frontmatter(text)
    fields = parse_simple_frontmatter(frontmatter)
    updates = _parse_updates(args[1:])
    if isinstance(updates, dict):
        print_json(updates)
        return 1

    pending_status = str(fields.get("status") or "")
    final_status = ""
    for key, value in updates:
        if key != "status":
            continue
        issue = validate_status_transition(pending_status, value)
        if issue:
            payload = status_transition_error_payload(pending_status, value, issue)
            emit_state_transition(args[0], result="blocked", current_status=pending_status, attempted_status=value, issue=issue)
            print_json(payload)
            return 1
        pending_status = value
        final_status = value

    frontmatter, updated = _replace_frontmatter_values(frontmatter, updates)
    if not updated:
        print_json({"ok": False, "error": "keys_not_found", "updated": []})
        return 1
    write_atomic(args[0], frontmatter + body)
    if final_status:
        emit_state_transition(args[0], result="applied", new_status=final_status)
    event_fields = list(dict.fromkeys(key for key in updated if key in {"epic", "currentStory", "currentStep", "lastUpdated"}))
    if event_fields:
        updated_fields = parse_simple_frontmatter(frontmatter)
        emit_state_fields_updated(args[0], event_fields, {key: updated_fields.get(key, "") for key in event_fields})
    print_json({"ok": True, "updated": updated})
    return 0


def _parse_updates(args: list[str]) -> list[tuple[str, str]] | dict[str, object]:
    updates: list[tuple[str, str]] = []
    idx = 0
    while idx < len(args):
        if args[idx] == "--set":
            parsed = parse_state_update_argument(args[idx + 1] if idx + 1 < len(args) else "")
            if isinstance(parsed, dict):
                return parsed
            updates.append(parsed)
            idx += 2
            continue
        idx += 1
    return updates


def _replace_frontmatter_values(frontmatter: str, updates: list[tuple[str, str]]) -> tuple[str, list[str]]:
    found = {
        key
        for key, _value in updates
        if re.search(rf"(?m)^{re.escape(key)}:.*$", frontmatter)
    }
    if len(found) != len({key for key, _value in updates}):
        return frontmatter, []

    updated: list[str] = []
    for key, value in updates:
        rendered = _render_frontmatter_value(value)
        replaced, count = re.subn(rf"(?m)^{re.escape(key)}:.*$", lambda m, k=key, v=rendered: f"{k}: {v}", frontmatter)
        if count:
            frontmatter = replaced
            updated.append(key)
    return frontmatter, updated


def _render_frontmatter_value(value: str) -> str:
    stripped = value.strip()
    lower = stripped.lower()
    if (
        value != stripped
        or lower in {"true", "false", "null"}
        or re.fullmatch(r"0[0-9]+", stripped)
        or "# " in stripped
        or stripped.startswith("#")
        or ": " in stripped
    ):
        return json.dumps(stripped)
    return value


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return f"{parts[0]}---{parts[1]}---", parts[2]
