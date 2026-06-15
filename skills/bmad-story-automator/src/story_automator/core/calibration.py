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


@dataclass(kw_only=True)
class CalibrationTable:
    """An aggregated calibration table built from a telemetry JSONL ledger.

    `entries` is keyed by `(model_id, task_kind)`. `generated_at` is the
    `iso_now()` timestamp at the moment `build_calibration` finished;
    `source_path` is the string form of the ledger path that was scanned
    (even when the file did not exist); `total_events_scanned` counts
    every successfully parsed line, including UnknownEvent and event
    types unrelated to story completion.
    """

    entries: dict[tuple[str, str], CalibrationEntry]
    generated_at: str
    source_path: str
    total_events_scanned: int
