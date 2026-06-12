from __future__ import annotations

from typing import Any

from .diagnostics import DiagnosticEvent, DiagnosticIssue, emit_diagnostic_event, serialize_issues
from .utils import print_json


def emit_monitor_result(
    json_output: bool,
    state: str,
    done: int,
    total: int,
    output_file: str,
    reason: str,
    *,
    output_verified: bool | None = None,
    structured_issue: dict[str, Any] | None = None,
) -> int:
    normalized_issue = _normalize_structured_issue(structured_issue)
    emit_diagnostic_event(
        DiagnosticEvent(
            name="session.lifecycle.result",
            source="monitor-session",
            message=f"monitor-session finished with {state}",
            severity="error" if state in {"crashed", "timeout", "incomplete"} else "info",
            context={
                "finalState": state,
                "todosDone": done,
                "todosTotal": total,
                "outputFile": output_file,
                "reason": reason,
                "outputVerified": False if output_verified is None else output_verified,
            },
        )
    )
    if json_output:
        payload: dict[str, Any] = {
            "final_state": state,
            "todos_done": done,
            "todos_total": total,
            "output_file": output_file,
            "exit_reason": reason,
            "output_verified": False if output_verified is None else output_verified,
        }
        if normalized_issue is not None:
            payload["structuredIssues"] = [normalized_issue]
        print_json(payload)
    else:
        print(f"{state},{done},{total},{output_file},{reason}")
    return 0


def _normalize_structured_issue(structured_issue: dict[str, Any] | None) -> dict[str, Any] | None:
    if structured_issue is None:
        return None
    if isinstance(structured_issue, dict) and isinstance(structured_issue.get("type"), str) and isinstance(structured_issue.get("field"), str):
        return structured_issue
    issue = DiagnosticIssue(
        type="invalid_type",
        field="structured_issue",
        expected="serialized diagnostic issue object",
        actual=type(structured_issue).__name__,
        message="Monitor structured issue must be a serialized diagnostic issue object",
        recovery="Pass a serialized DiagnosticIssue with at least type and field.",
        code="MONITOR_STRUCTURED_ISSUE_INVALID",
        source="monitor-session",
    )
    return serialize_issues([issue])[0]
