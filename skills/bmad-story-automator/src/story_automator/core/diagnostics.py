from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DIAGNOSTIC_EVENTS_FILE_ENV = "STORY_AUTOMATOR_DIAGNOSTICS_FILE"
MAX_STRING_LENGTH = 160
MAX_COLLECTION_ITEMS = 6
SENSITIVE_KEY_RE = re.compile(r"(authorization|credential|password|secret|token|api[_-]?key|access[_-]?key)", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|credential|password|secret|token|api[_-]?key|access[_-]?key)\b\s*[:=]\s*([^\s,;]+)"
)
ABSOLUTE_PATH_RE = re.compile(r"(?<![\w.-])(?:/[^\s,;:]+)+")


@dataclass(frozen=True)
class DiagnosticIssue:
    type: str
    field: str = ""
    expected: Any = ""
    actual: Any = ""
    message: str = ""
    recovery: str = ""
    code: str = ""
    severity: str = "error"
    source: str = ""


@dataclass(frozen=True)
class DiagnosticEvent:
    name: str
    source: str
    message: str = ""
    severity: str = "info"
    issues: list[DiagnosticIssue] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


def serialize_issue(issue: DiagnosticIssue) -> dict[str, Any]:
    return {
        "type": issue.type,
        "field": issue.field,
        "expected": _json_safe(issue.expected),
        "actual": redact_actual(issue.actual),
        "message": redact_actual(issue.message),
        "recovery": issue.recovery,
        "code": issue.code,
        "severity": issue.severity,
        "source": issue.source,
    }


def serialize_issues(issues: list[DiagnosticIssue] | tuple[DiagnosticIssue, ...]) -> list[dict[str, Any]]:
    return [serialize_issue(issue) for issue in issues]


def serialize_event(event: DiagnosticEvent) -> dict[str, Any]:
    return {
        "name": event.name,
        "source": event.source,
        "message": event.message,
        "severity": event.severity,
        "issues": serialize_issues(event.issues),
        "context": redact_actual(event.context),
    }


def emit_diagnostic_event(event: DiagnosticEvent, path: str | Path | None = None) -> bool:
    target = str(path or os.environ.get(DIAGNOSTIC_EVENTS_FILE_ENV, "")).strip()
    if not target:
        return False
    try:
        output = Path(target).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(serialize_event(event), separators=(",", ":")) + "\n")
    except OSError:
        return False
    return True


def legacy_issue_message(issue: DiagnosticIssue) -> str:
    if issue.message:
        return issue.message
    if issue.field and issue.expected:
        return f"{issue.field}: expected {issue.expected}"
    if issue.field:
        return issue.field
    return issue.type


def issues_from_exception(exc: Exception, source: str, field: str = "") -> list[DiagnosticIssue]:
    raw_message = str(exc)
    message = redact_actual(raw_message) if raw_message else exc.__class__.__name__
    return [
        DiagnosticIssue(
            type=exc.__class__.__name__,
            field=field,
            actual=str(exc),
            message=str(message) or exc.__class__.__name__,
            severity="error",
            source=source,
        )
    ]


def redact_actual(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Path):
        return _redact_string(str(value))
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for idx, (key, item) in enumerate(value.items()):
            if idx >= MAX_COLLECTION_ITEMS:
                redacted["..."] = f"{len(value) - MAX_COLLECTION_ITEMS} more"
                break
            key_text = str(key)
            redacted[key_text] = "<redacted>" if SENSITIVE_KEY_RE.search(key_text) else redact_actual(item)
        return redacted
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        redacted_items = [redact_actual(item) for item in items[:MAX_COLLECTION_ITEMS]]
        if len(items) > MAX_COLLECTION_ITEMS:
            redacted_items.append(f"... {len(items) - MAX_COLLECTION_ITEMS} more")
        return redacted_items
    return _redact_string(str(value))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _redact_string(value: str) -> str:
    value = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    value = ABSOLUTE_PATH_RE.sub(_path_placeholder, value)
    if len(value) > MAX_STRING_LENGTH:
        return f"{value[:MAX_STRING_LENGTH]}...<truncated {len(value) - MAX_STRING_LENGTH} chars>"
    return value


def _path_placeholder(match: re.Match[str]) -> str:
    path = match.group(0)
    name = Path(path).name
    return f"<path:{name}>" if name else "<path>"
