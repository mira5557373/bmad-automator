"""``story-automator drift`` CLI subcommand.

Thin shell-callable wrapper around M08 calibration + M09 drift detection.
Builds two CalibrationTable snapshots from a baseline and a current
telemetry JSONL ledger, computes a DriftReport, and prints it. Default
output is one compact JSON object (for jq in BMAD step markdown); pass
``--format text`` for the plain-ASCII ``format_drift_report`` rendering.

Read-only by design: build_calibration performs no writes and tolerates
missing ledger paths (returns an empty table), so this command never
creates files and never raises on a nonexistent ledger.
"""

from __future__ import annotations

from ..core.calibration import build_calibration
from ..core.common import print_json
from ..core.drift_detector import (
    DriftEntry,
    DriftReport,
    compute_drift,
    format_drift_report,
)

_VALID_FORMATS = ("json", "text")


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


def _entry_to_dict(entry: DriftEntry) -> dict[str, object]:
    return {
        "model_id": entry.model_id,
        "task_kind": entry.task_kind,
        "baseline_success_rate": entry.baseline_success_rate,
        "current_success_rate": entry.current_success_rate,
        "delta": entry.delta,
        "classification": entry.classification.value,
    }


def _report_to_dict(report: DriftReport) -> dict[str, object]:
    return {
        "generated_at": report.generated_at,
        "baseline_source": report.baseline_source,
        "current_source": report.current_source,
        "entries": [_entry_to_dict(entry) for entry in report.entries],
    }


def cmd_drift(args: list[str]) -> int:
    """Entry point for ``story-automator drift``.

    Required flags:
        --baseline <path-to-baseline-events.jsonl>
        --current  <path-to-current-events.jsonl>
    Optional:
        --format {json,text}   (default: json)
    """
    params = _flag_map(args)
    baseline_path = params.get("baseline", "")
    current_path = params.get("current", "")
    output_format = params.get("format", "json")
    if not baseline_path:
        print_json({"ok": False, "error": "missing_baseline"})
        return 1
    if not current_path:
        print_json({"ok": False, "error": "missing_current"})
        return 1
    if output_format not in _VALID_FORMATS:
        print_json(
            {"ok": False, "error": "invalid_format", "format": output_format}
        )
        return 1
    baseline = build_calibration(baseline_path)
    current = build_calibration(current_path)
    report = compute_drift(baseline, current)
    if output_format == "text":
        print(format_drift_report(report), end="")
        return 0
    print_json({"ok": True, **_report_to_dict(report)})
    return 0
