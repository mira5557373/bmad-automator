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

from dataclasses import dataclass  # noqa: F401
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
