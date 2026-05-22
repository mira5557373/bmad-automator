from __future__ import annotations

from typing import Any

from .diagnostics import DiagnosticEvent, emit_diagnostic_event
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
    structured_issue: object | None = None,
) -> int:
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
        if structured_issue is not None:
            payload["structuredIssues"] = [structured_issue]
        print_json(payload)
    else:
        print(f"{state},{done},{total},{output_file},{reason}")
    return 0
