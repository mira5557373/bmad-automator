"""Per-model calibration tracker (M08).

Walks the M02 JSONL telemetry ledger and aggregates StoryCompleted /
StoryFailed events into a (model_id, task_kind) -> success_rate table.
Passive and side-effect free: no writes, no network, no subprocess.
"""

from __future__ import annotations

__all__ = [
    "CalibrationEntry",
    "CalibrationTable",
    "build_calibration",
    "format_calibration_report",
    "lookup_success_rate",
]

from dataclasses import dataclass


@dataclass(kw_only=True, frozen=True)
class CalibrationEntry:
    """A single (model_id, task_kind) row in the calibration table.

    `success_rate` is in the closed interval [0.0, 1.0]; the aggregator
    rounds to four decimal places before constructing the entry.
    """

    model_id: str
    task_kind: str
    success_rate: float
    sample_count: int
    last_seen_iso: str
