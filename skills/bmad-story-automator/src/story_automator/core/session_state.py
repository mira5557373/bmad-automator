from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .diagnostics import DiagnosticIssue, serialize_issue
from .utils import read_text

STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SessionStateLoadResult:
    ok: bool
    state: dict[str, object]
    issue: DiagnosticIssue | None
    exists: bool


def load_session_state(path: str | Path) -> dict[str, object]:
    target = Path(path)
    if not target.exists():
        return {}
    try:
        raw = json.loads(read_text(target))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def load_session_state_diagnostics(path: str | Path) -> SessionStateLoadResult:
    target = Path(path)
    if not target.exists():
        return SessionStateLoadResult(False, {}, _session_issue("session_state.missing", "file exists", "", "Session state file is missing"), False)
    try:
        text = read_text(target)
    except OSError as exc:
        return SessionStateLoadResult(False, {}, _session_issue("session_state.unreadable", "readable JSON file", str(exc), "Session state file is unreadable"), True)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return SessionStateLoadResult(False, {}, _session_issue("session_state.invalid_json", "valid JSON object", str(exc), "Session state file contains invalid JSON"), True)
    if not isinstance(raw, dict):
        return SessionStateLoadResult(False, {}, _session_issue("session_state.invalid_type", "JSON object", raw, "Session state file must contain a JSON object"), True)
    version = raw.get("schemaVersion")
    if version not in (None, STATE_SCHEMA_VERSION):
        return SessionStateLoadResult(True, raw, _session_issue("session_state.unexpected_schema_version", STATE_SCHEMA_VERSION, version, "Session state schema version is newer or unexpected", severity="warning"), True)
    return SessionStateLoadResult(True, raw, None, True)


def serialized_session_state_issue(path: str | Path) -> object | None:
    result = load_session_state_diagnostics(path)
    if result.issue is None or result.issue.type == "session_state.missing":
        return None
    return serialize_issue(result.issue)


def _session_issue(issue_type: str, expected: object, actual: object, message: str, *, severity: str = "error") -> DiagnosticIssue:
    return DiagnosticIssue(
        type=issue_type,
        field="session_state",
        expected=expected,
        actual=actual,
        message=message,
        recovery="Remove the stale runtime state file or restart the monitored session.",
        code=issue_type.upper().replace(".", "_"),
        severity=severity,
        source="monitor-session",
    )
