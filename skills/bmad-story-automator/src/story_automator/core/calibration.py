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
from pathlib import Path

from .common import iso_now


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


def build_calibration(jsonl_path: str | Path) -> CalibrationTable:
    """Build a CalibrationTable by streaming a JSONL telemetry ledger.

    Missing paths return an empty table (not an exception). Each
    successfully parsed line increments `total_events_scanned`;
    only StoryCompleted / StoryFailed records contribute to `entries`.
    """

    path = Path(jsonl_path)
    source_path = str(path)
    if not path.is_file():
        return CalibrationTable(
            entries={},
            generated_at=iso_now(),
            source_path=source_path,
            total_events_scanned=0,
        )
    # Real aggregation lands in Task 6; placeholder so a green file
    # cannot silently pass without the streaming path being written.
    raise NotImplementedError("streaming aggregation lands in Task 6")
