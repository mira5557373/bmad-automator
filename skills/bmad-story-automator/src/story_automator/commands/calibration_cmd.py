"""``story-automator calibration`` CLI subcommand wrapping the M08 tracker.

Thin shell-callable wrapper around ``core.calibration``. Walks the M02 JSONL
telemetry ledger and prints a single compact JSON object describing the
per-``(model_id, task_kind)`` success-rate table, so BMAD step markdown can
read it via ``jq``. Read-only by design — does not write the ledger, does not
call audit-log routines, and does not prompt for input. A missing ledger is
NOT an error: ``build_calibration`` returns an empty table and the command
prints ``ok:true`` with no entries.
"""

from __future__ import annotations

from pathlib import Path

from ..core.calibration import (
    build_calibration,
    format_calibration_report,
    lookup_success_rate,
)
from ..core.common import print_json
from ..core.utils import get_project_root


def _flag_map(args: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--") and index + 1 < len(args):
            output[token[2:]] = args[index + 1]
            index += 2
            continue
        index += 1
    return output


def cmd_calibration(args: list[str]) -> int:
    """Entry point for ``story-automator calibration``.

    Optional flags:
        --events <path>              telemetry JSONL ledger
                                     (default: <PROJECT_ROOT>/telemetry/events.jsonl)
        --report                     also include the plain-text report string
        --model <id> --task <kind>   look up a single (model, task) success rate
    """
    params = _flag_map(args)
    events_path = params.get("events") or str(
        Path(get_project_root()) / "telemetry" / "events.jsonl"
    )
    try:
        table = build_calibration(events_path)
    except OSError as exc:
        # A real I/O error (e.g., PermissionError on an existing ledger) would
        # emit a stack trace to stderr — skill markdown parses stdout JSON via
        # jq and would silently treat non-JSON as no calibration data. Surface
        # it as a structured failure with ok=false instead.
        print_json({"ok": False, "error": "io_error", "detail": str(exc)})
        return 1
    payload: dict = {
        "ok": True,
        "source_path": table.source_path,
        "generated_at": table.generated_at,
        "total_events_scanned": table.total_events_scanned,
        "entries": [
            {
                "model_id": entry.model_id,
                "task_kind": entry.task_kind,
                "success_rate": entry.success_rate,
                "sample_count": entry.sample_count,
                "last_seen_iso": entry.last_seen_iso,
            }
            for _, entry in sorted(table.entries.items())
        ],
    }
    model = params.get("model")
    task = params.get("task")
    if model and task:
        payload["lookup"] = {
            "model_id": model,
            "task_kind": task,
            "success_rate": lookup_success_rate(table, model, task),
        }
    # --report is a boolean flag with no value, so _flag_map (which only
    # captures --flag VALUE pairs) will not record it; detect it directly.
    if "--report" in args:
        payload["report"] = format_calibration_report(table)
    print_json(payload)
    return 0
