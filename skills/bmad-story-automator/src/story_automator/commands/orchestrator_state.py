from __future__ import annotations

import re
from pathlib import Path

from story_automator.core.frontmatter import parse_simple_frontmatter
from story_automator.core.orchestration_events import emit_state_fields_updated, emit_state_transition
from story_automator.core.state_validation import parse_state_update_argument, status_transition_error_payload, validate_status_transition
from story_automator.core.utils import file_exists, print_json, read_text


def state_update_action(args: list[str]) -> int:
    if not args or not file_exists(args[0]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    text = read_text(args[0])
    fields = parse_simple_frontmatter(text)
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

    frontmatter, body = _split_frontmatter(text)
    frontmatter, updated = _replace_frontmatter_values(frontmatter, updates)
    if not updated:
        print_json({"ok": False, "error": "keys_not_found", "updated": []})
        return 1
    Path(args[0]).write_text(frontmatter + body, encoding="utf-8")
    if final_status:
        emit_state_transition(args[0], result="applied", new_status=final_status)
    event_fields = [key for key in updated if key in {"epic", "currentStory", "currentStep", "lastUpdated"}]
    if event_fields:
        emit_state_fields_updated(args[0], event_fields, {key: value for key, value in updates if key in event_fields})
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
    updated: list[str] = []
    for key, value in updates:
        replaced, count = re.subn(rf"(?m)^{re.escape(key)}:.*$", lambda m, k=key, v=value: f"{k}: {v}", frontmatter)
        if count:
            frontmatter = replaced
            updated.append(key)
    return frontmatter, updated


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return text, ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text, ""
    return f"{parts[0]}---{parts[1]}---", parts[2]
