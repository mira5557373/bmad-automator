"""Drift detector (M09).

Pure-functional comparator: takes two CalibrationTable snapshots
(baseline + current), classifies each (model_id, task_kind) pair's
shift into one of four severity bands, and emits a deterministic
DriftReport plus a plain-ASCII formatter. No I/O, no telemetry reads,
no alarms.
"""

from __future__ import annotations

__all__ = [  # noqa: F822
    "DriftClassification",
    "DriftEntry",
    "DriftReport",
    "compute_drift",
    "format_drift_report",
]

from dataclasses import dataclass
from enum import Enum

from .calibration import CalibrationTable  # noqa: F401
from .common import iso_now  # noqa: F401

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
    """

    entries: list[DriftEntry]
    generated_at: str
    baseline_source: str
    current_source: str
