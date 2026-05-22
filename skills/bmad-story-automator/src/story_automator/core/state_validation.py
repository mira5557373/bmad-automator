from __future__ import annotations

import re
from typing import Any

from .agent_config import has_agent_config_runtime_source
from .diagnostics import DiagnosticIssue, legacy_issue_message, serialize_issues
from .runtime_policy import PolicyError, load_policy_for_state


VALID_STATUSES = {"INITIALIZING", "READY", "IN_PROGRESS", "PAUSED", "EXECUTION_COMPLETE", "COMPLETE", "ABORTED"}
ALLOWED_STATUS_TRANSITIONS = {
    "INITIALIZING": {"INITIALIZING", "READY", "ABORTED"},
    "READY": {"READY", "IN_PROGRESS", "PAUSED", "ABORTED"},
    "IN_PROGRESS": {"IN_PROGRESS", "PAUSED", "EXECUTION_COMPLETE", "COMPLETE", "ABORTED"},
    "PAUSED": {"PAUSED", "IN_PROGRESS", "ABORTED"},
    "EXECUTION_COMPLETE": {"EXECUTION_COMPLETE", "COMPLETE", "ABORTED"},
    "COMPLETE": {"COMPLETE"},
    "ABORTED": {"ABORTED"},
}


def validate_state_fields(state_path: str, fields: dict[str, Any], frontmatter: str) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    _required(issues, fields, "epic")
    _required(issues, fields, "epicName")
    _required(issues, fields, "storyRange")
    _required(issues, fields, "status", lambda value: isinstance(value, str) and value in VALID_STATUSES)
    _required(issues, fields, "lastUpdated", lambda value: isinstance(value, str) and re.search(r"\d{4}-\d{2}-\d{2}T", value))
    if not has_runtime_command_config(fields, frontmatter):
        issues.append(
            DiagnosticIssue(
                type="missing_field",
                field="aiCommand",
                expected="non-empty aiCommand or usable agentConfig",
                actual=fields.get("aiCommand", ""),
                message="Missing or empty aiCommand",
                recovery="Set aiCommand or provide an agentConfig block with a default agent.",
                code="STATE_RUNTIME_CONFIG_MISSING",
                source="validate-state",
            )
        )
    try:
        load_policy_for_state(state_path)
    except PolicyError as exc:
        issues.append(
            DiagnosticIssue(
                type="invalid_value",
                field="policySnapshotFile",
                expected="valid policy snapshot metadata or legacy state",
                actual=str(exc),
                message=str(exc),
                recovery="Restore the referenced policy snapshot or rebuild the orchestration state.",
                code="STATE_POLICY_SNAPSHOT_INVALID",
                source="validate-state",
            )
        )
    return issues


def validate_status_transition(current: str, attempted: str) -> DiagnosticIssue | None:
    if attempted not in VALID_STATUSES:
        return DiagnosticIssue(
            type="invalid_value",
            field="status",
            expected=sorted(VALID_STATUSES),
            actual=attempted,
            message=f"Invalid status {attempted}",
            recovery="Choose a valid orchestration status.",
            code="STATE_STATUS_INVALID",
            source="state-update",
        )
    if current not in VALID_STATUSES:
        return None
    allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
    if attempted in allowed:
        return None
    return DiagnosticIssue(
        type="invalid_status_transition",
        field="status",
        expected=sorted(allowed),
        actual=attempted,
        message=f"Invalid status transition from {current or '<missing>'} to {attempted}",
        recovery="Choose one of the allowedTransitions values for the current state.",
        code="STATE_STATUS_TRANSITION_INVALID",
        source="state-update",
    )


def status_transition_error_payload(current: str, attempted: str) -> dict[str, Any] | None:
    issue = validate_status_transition(current, attempted)
    if not issue:
        return None
    return {
        "ok": False,
        "error": "invalid_status_transition",
        "currentStatus": current,
        "attemptedStatus": attempted,
        "allowedTransitions": sorted(ALLOWED_STATUS_TRANSITIONS.get(current, set())),
        "issues": [legacy_issue_message(issue)],
        "structuredIssues": serialize_issues([issue]),
    }


def state_validation_payload(issues: list[DiagnosticIssue]) -> dict[str, Any]:
    legacy_issues = [legacy_issue_message(issue) for issue in issues]
    return {
        "ok": True,
        "structure": "issues" if issues else "ok",
        "issues": legacy_issues,
        "structuredIssues": serialize_issues(issues),
        "issueCount": len(issues),
    }


def has_runtime_command_config(fields: dict[str, Any], frontmatter: str) -> bool:
    ai_command = fields.get("aiCommand")
    if isinstance(ai_command, str) and ai_command.strip():
        return True
    if isinstance(ai_command, list) and any(isinstance(item, str) and item.strip() for item in ai_command):
        return True
    return has_agent_config_runtime_source(frontmatter)


def _required(
    issues: list[DiagnosticIssue],
    fields: dict[str, Any],
    key: str,
    validator: Any = None,
) -> None:
    value = fields.get(key)
    if value in ("", [], None):
        issues.append(
            DiagnosticIssue(
                type="missing_field",
                field=key,
                expected="non-empty value",
                actual=value,
                message=f"Missing or empty {key}",
                recovery=f"Add a valid {key} value to state frontmatter.",
                code=f"STATE_{key.upper()}_MISSING",
                source="validate-state",
            )
        )
        return
    if validator and not validator(value):
        issues.append(
            DiagnosticIssue(
                type="invalid_value",
                field=key,
                expected=_expected_for(key),
                actual=value,
                message=f"Invalid {key}",
                recovery=f"Update {key} to match the expected state frontmatter contract.",
                code=f"STATE_{key.upper()}_INVALID",
                source="validate-state",
            )
        )


def _expected_for(key: str) -> Any:
    if key == "status":
        return sorted(VALID_STATUSES)
    if key == "lastUpdated":
        return "ISO-like timestamp containing YYYY-MM-DDT"
    return "valid value"
