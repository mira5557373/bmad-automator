from __future__ import annotations

import json
import re

from story_automator.core.frontmatter import parse_frontmatter_content
from story_automator.core.diagnostics import (
    issues_from_exception,
    legacy_issue_message,
    redact_actual,
    serialize_issues,
)
from story_automator.core.orchestration_events import emit_state_fields_updated, emit_state_transition
from story_automator.core.state_validation import (
    parse_state_update_argument,
    state_update_duplicate_key_error_payload,
    status_transition_error_payload,
    validate_status_transition,
)
from story_automator.core.utils import file_exists, print_json, read_text, write_atomic


def state_update_action(args: list[str]) -> int:
    if not args or not file_exists(args[0]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    text = read_text(args[0])
    frontmatter, body = _split_frontmatter(text)
    fields = parse_frontmatter_content(_frontmatter_content(frontmatter))
    updates = _parse_updates(args[1:])
    if isinstance(updates, dict):
        print_json(updates)
        return 1
    preflight_error = _frontmatter_update_error(frontmatter, updates)
    if preflight_error:
        print_json({"ok": False, "error": preflight_error, "updated": []})
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

    frontmatter, updated, applied_values, error = _replace_frontmatter_values(frontmatter, updates)
    if not updated:
        print_json({"ok": False, "error": error or "keys_not_found", "updated": []})
        return 1
    try:
        write_atomic(args[0], frontmatter + body)
    except OSError as exc:
        issues = issues_from_exception(exc, source="state-update", field="state-file")
        print_json(
            {
                "ok": False,
                "error": "write_failed",
                "issues": [str(redact_actual(legacy_issue_message(issue))) for issue in issues],
                "structuredIssues": serialize_issues(issues),
            }
        )
        return 1
    if final_status:
        emit_state_transition(args[0], result="applied", new_status=final_status)
    event_fields = list(dict.fromkeys(key for key in updated if key in {"epic", "currentStory", "currentStep", "lastUpdated"}))
    if event_fields:
        emit_state_fields_updated(args[0], event_fields, {key: applied_values.get(key, "") for key in event_fields})
    print_json({"ok": True, "updated": list(dict.fromkeys(updated))})
    return 0


def _parse_updates(args: list[str]) -> list[tuple[str, str]] | dict[str, object]:
    updates: list[tuple[str, str]] = []
    seen: set[str] = set()
    idx = 0
    while idx < len(args):
        if args[idx] == "--set":
            parsed = parse_state_update_argument(args[idx + 1] if idx + 1 < len(args) else "")
            if isinstance(parsed, dict):
                return parsed
            if parsed[0] in seen:
                return state_update_duplicate_key_error_payload(parsed[0])
            seen.add(parsed[0])
            updates.append(parsed)
            idx += 2
            continue
        idx += 1
    return updates


def _replace_frontmatter_values(frontmatter: str, updates: list[tuple[str, str]]) -> tuple[str, list[str], dict[str, str], str]:
    preflight_error = _frontmatter_update_error(frontmatter, updates)
    if preflight_error:
        return frontmatter, [], {}, preflight_error

    updated: list[str] = []
    applied_values: dict[str, str] = {}
    for key, value in updates:
        rendered = _render_frontmatter_value(key, value)
        replaced, count = re.subn(rf"(?m)^{re.escape(key)}:.*$", lambda m, k=key, v=rendered: f"{k}: {v}", frontmatter, count=1)
        if count:
            frontmatter = replaced
            updated.append(key)
            applied_values[key] = rendered
    return frontmatter, updated, applied_values, ""


def _frontmatter_update_error(frontmatter: str, updates: list[tuple[str, str]]) -> str:
    missing: list[str] = []
    duplicate: list[str] = []
    for key, _value in updates:
        count = len(re.findall(rf"(?m)^{re.escape(key)}:.*$", frontmatter))
        if count == 0:
            missing.append(key)
        elif count > 1:
            duplicate.append(key)
    if missing:
        return "keys_not_found"
    if duplicate:
        return "duplicate_frontmatter_key"
    return ""


def _render_frontmatter_value(key: str, value: str) -> str:
    stripped = value.strip()
    if key == "status":
        return stripped
    lower = stripped.lower()
    if (
        value != stripped
        or lower in {"true", "false", "null"}
        or re.fullmatch(r"0[0-9]+", stripped)
        or "# " in stripped
        or stripped.startswith("#")
        or ": " in stripped
    ):
        return json.dumps(value if value != stripped else stripped)
    return value


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return f"{parts[0]}---{parts[1]}---", parts[2]


def _frontmatter_content(frontmatter: str) -> str:
    if not frontmatter.startswith("---"):
        return frontmatter
    parts = frontmatter.split("---", 2)
    return parts[1] if len(parts) >= 3 else frontmatter
