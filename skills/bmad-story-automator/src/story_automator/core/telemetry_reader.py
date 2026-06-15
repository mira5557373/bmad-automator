"""Streaming TelemetryReader over M02 JSONL output.

REQ-06..REQ-08. Reads the file line-by-line and dispatches each non-
blank line through ``parse_event`` from
``story_automator.core.telemetry_events``. Aggregations filter by
``isinstance`` on the typed M01 classes so untyped or unknown lines are
ignored by rollups even though ``iter_events`` still yields them.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any  # noqa: F401

from .telemetry_events import (
    CostCharged,
    Event,
    RetroFired,  # noqa: F401
    RetryAttempt,  # noqa: F401
    parse_event,
)


class TelemetryReader:
    def __init__(self, path: str | Path) -> None:
        self._path: Path = Path(path)

    def iter_events(self) -> Iterator[Event]:
        if not self._path.is_file():
            return
        with open(self._path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                yield parse_event(line)

    def cost_by_epic(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for event in self.iter_events():
            if isinstance(event, CostCharged):
                totals[event.epic] = totals.get(event.epic, 0.0) + event.cost_usd
        return totals


__all__ = ["TelemetryReader"]
