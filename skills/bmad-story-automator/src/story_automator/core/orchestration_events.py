from __future__ import annotations

from .diagnostics import DiagnosticEvent, DiagnosticIssue, emit_diagnostic_event


def emit_state_transition(
    state_file: str,
    *,
    result: str,
    current_status: str = "",
    attempted_status: str = "",
    new_status: str = "",
    issue: DiagnosticIssue | None = None,
) -> None:
    context = {"stateFile": state_file, "result": result}
    if current_status:
        context["currentStatus"] = current_status
    if attempted_status:
        context["attemptedStatus"] = attempted_status
    if new_status:
        context["newStatus"] = new_status
    emit_diagnostic_event(
        DiagnosticEvent(
            name="state.transition",
            source="state-update",
            message=f"State status transition {result}",
            severity="error" if issue else "info",
            issues=[issue] if issue else [],
            context=context,
        )
    )


def emit_state_fields_updated(state_file: str, updated_fields: list[str], values: dict[str, str]) -> None:
    emit_diagnostic_event(
        DiagnosticEvent(
            name="state.fields_updated",
            source="state-update",
            message="Orchestration state fields updated",
            context={"stateFile": state_file, "updatedFields": updated_fields, "values": values},
        )
    )


def emit_policy_load_failed(trigger: str, state_file: str, error: str) -> None:
    emit_diagnostic_event(
        DiagnosticEvent(
            name="policy.load_failed",
            source="escalate",
            message="Runtime policy load failed",
            severity="error",
            context={"trigger": trigger, "stateFile": state_file, "error": error},
        )
    )


def emit_policy_decision(trigger: str, escalate: bool, context: dict[str, object]) -> None:
    payload = {"trigger": trigger, "escalate": escalate}
    payload.update(context)
    emit_diagnostic_event(
        DiagnosticEvent(
            name="policy.decision",
            source="escalate",
            message="Escalation policy evaluated",
            severity="warning" if escalate else "info",
            context=payload,
        )
    )
