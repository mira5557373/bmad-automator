"""Drift detector (M09).

Pure-functional comparator: takes two CalibrationTable snapshots
(baseline + current), classifies each (model_id, task_kind) pair's
shift into one of four severity bands, and emits a deterministic
DriftReport plus a plain-ASCII formatter. No I/O, no telemetry reads,
no alarms.
"""

from __future__ import annotations

__all__ = [
    "DriftClassification",
    "DriftEntry",
    "DriftReport",
    "compute_drift",
    "format_drift_report",
]

from dataclasses import dataclass
from enum import Enum

from .calibration import CalibrationTable
from .common import iso_now

STABLE_MAX = 0.05
MINOR_MAX = 0.10
MAJOR_MAX = 0.20
_MISSING_RATE_DEFAULT = 0.5


class DriftClassification(Enum):
    """Four-tier categorical band over |delta|."""

    STABLE = "stable"
    MINOR_DRIFT = "minor_drift"
    MAJOR_DRIFT = "major_drift"
    SEVERE_DRIFT = "severe_drift"


@dataclass(kw_only=True, frozen=True)
class DriftEntry:
    """One row in a DriftReport.

    `delta == current_success_rate - baseline_success_rate`, rounded to
    four decimals by the producer (`compute_drift`). Stored verbatim
    here so consumers can render without re-rounding.
    """

    model_id: str
    task_kind: str
    baseline_success_rate: float
    current_success_rate: float
    delta: float
    classification: DriftClassification


@dataclass(kw_only=True)
class DriftReport:
    """Output of `compute_drift`.

    `entries` is ordered by descending `abs(delta)`, then ascending
    `model_id`, then ascending `task_kind`. `baseline_source` and
    `current_source` echo the `source_path` of each input
    CalibrationTable so the report is self-describing without an
    out-of-band caller note.

    `entries` is a mutable list (per REQ-05); mutating or reordering
    it after construction breaks the documented sort invariant. Treat
    it as read-only at consumer sites.
    """

    entries: list[DriftEntry]
    generated_at: str
    baseline_source: str
    current_source: str


def _classify(delta: float) -> DriftClassification:
    """Bin `delta` into a DriftClassification using REQ-07 bands.

    Bands are half-open: the lower bound belongs to the higher tier.
    This matches the spec language "`|delta| < 0.05` is STABLE,
    `0.05 <= |delta| < 0.10` is MINOR_DRIFT, ...".
    """

    magnitude = abs(delta)
    if magnitude < STABLE_MAX:
        return DriftClassification.STABLE
    if magnitude < MINOR_MAX:
        return DriftClassification.MINOR_DRIFT
    if magnitude < MAJOR_MAX:
        return DriftClassification.MAJOR_DRIFT
    return DriftClassification.SEVERE_DRIFT


def compute_drift(
    baseline: CalibrationTable,
    current: CalibrationTable,
) -> DriftReport:
    """Compare two CalibrationTable snapshots, return a DriftReport.

    Signature is positional per REQ-06. Per REQ-08, any key missing on
    one side is filled with 0.5 (matches `lookup_success_rate`'s
    default).
    """

    keys = set(baseline.entries.keys()) | set(current.entries.keys())
    entries: list[DriftEntry] = []
    for key in keys:
        baseline_entry = baseline.entries.get(key)
        current_entry = current.entries.get(key)
        baseline_rate = (
            baseline_entry.success_rate
            if baseline_entry is not None
            else _MISSING_RATE_DEFAULT
        )
        current_rate = (
            current_entry.success_rate
            if current_entry is not None
            else _MISSING_RATE_DEFAULT
        )
        delta = round(current_rate - baseline_rate, 4)
        model_id, task_kind = key
        entries.append(
            DriftEntry(
                model_id=model_id,
                task_kind=task_kind,
                baseline_success_rate=baseline_rate,
                current_success_rate=current_rate,
                delta=delta,
                classification=_classify(delta),
            )
        )
    entries.sort(key=lambda e: (-abs(e.delta), e.model_id, e.task_kind))
    return DriftReport(
        entries=entries,
        generated_at=iso_now(),
        baseline_source=baseline.source_path,
        current_source=current.source_path,
    )


def format_drift_report(report: DriftReport) -> str:
    """Render a DriftReport as deterministic plain-ASCII text.

    Line 1 names both sources. Line 2 is the tab-separated header row.
    Body rows render `baseline_success_rate` and `current_success_rate`
    with four decimal places, and `delta` with an explicit sign and
    four decimal places. The final character is a single trailing
    newline.

    Precondition: `model_id`, `task_kind`, `baseline_source`, and
    `current_source` must be ASCII strings free of literal tabs and
    newlines. Telemetry-emitted model identifiers from M02 already
    satisfy this; non-ASCII inputs would silently break the spec
    REQ-10 plain-ASCII guarantee and could corrupt TSV column
    alignment.
    """

    lines: list[str] = [
        f"baseline: {report.baseline_source}\tcurrent: {report.current_source}",
        "model_id\ttask_kind\tbaseline\tcurrent\tdelta\tclassification",
    ]
    for entry in report.entries:
        lines.append(
            f"{entry.model_id}\t{entry.task_kind}\t"
            f"{entry.baseline_success_rate:.4f}\t"
            f"{entry.current_success_rate:.4f}\t"
            f"{entry.delta:+.4f}\t"
            f"{entry.classification.value}"
        )
    return "\n".join(lines) + "\n"
