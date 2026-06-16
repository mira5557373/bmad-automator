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
from typing import Any

from .telemetry_events import (
    CostCharged,
    Event,
    RetroFired,
    RetryAttempt,
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

    def attempts_by_story(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for event in self.iter_events():
            if isinstance(event, RetryAttempt):
                key = (event.epic, event.story_key)
                counts[key] = counts.get(key, 0) + 1
        return counts

    def retro_inputs(self, epic: str) -> dict[str, Any]:
        latest: RetroFired | None = None
        for event in self.iter_events():
            if isinstance(event, RetroFired) and event.epic == epic:
                latest = event
        if latest is None:
            return {}
        return {
            "stories_completed": latest.stories_completed,
            "total_cost_usd": latest.total_cost_usd,
            "duration_s": latest.duration_s,
        }


__all__ = ["TelemetryReader"]
