"""Per-model calibration tracker (M08).

Walks the M02 JSONL telemetry ledger and aggregates StoryCompleted /
StoryFailed events into a (model_id, task_kind) -> success_rate table.
Passive and side-effect free: no writes, no network, no shell-outs.
"""

from __future__ import annotations

__all__ = [
    "CalibrationEntry",
    "CalibrationTable",
    "build_calibration",
    "format_calibration_report",
    "lookup_success_rate",
]

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .common import iso_now
from .telemetry_events import StoryCompleted, StoryFailed, StoryStarted, parse_event


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


def _iter_event_lines(path: Path) -> Iterator[str]:
    """Yield non-blank decoded JSONL lines, tolerating CRLF and blanks.

    The caller is responsible for parsing; this helper is pure I/O.
    """

    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            yield line


def _bump_bucket(
    buckets: dict[tuple[str, str], list],
    key: tuple[str, str],
    *,
    completed: bool,
    timestamp: object,
) -> None:
    """Record one completion/failure under ``key`` in ``buckets``."""

    bucket = buckets.setdefault(key, [0, 0, ""])
    if completed:
        bucket[0] += 1
    else:
        bucket[1] += 1
    # Guard the order comparison: dataclasses do not enforce field
    # annotations and parse_event does cls(**payload), so a numeric or
    # null timestamp can slip through. A bare `>` against the "" seed
    # would raise TypeError ('int' > 'str'). Only strings participate
    # in last-seen tracking; ISO lexicographic ordering is preserved.
    if isinstance(timestamp, str) and timestamp > bucket[2]:
        bucket[2] = timestamp


def _accumulate_buckets(
    lines: Iterable[str],
) -> tuple[int, dict[tuple[str, str], list]]:
    """Aggregate decoded JSONL lines into per-key buckets.

    Returns `(total_scanned, buckets)` where `buckets[key]` is a
    `[completed_count, failed_count, last_seen_iso]` triple. Lines that
    fail `parse_event` (malformed JSON, missing event_type, unknown
    typed fields) are silently dropped and do NOT increment
    `total_scanned`. Unknown event types parse successfully (they
    become `UnknownEvent`) and DO increment `total_scanned` but do not
    contribute to any bucket.

    Bucket keys are ``(model_id, task_kind)``. M01 ``StoryCompleted`` /
    ``StoryFailed`` events do not carry those fields, so when they are
    absent the key is recovered by correlating the completion back to its
    ``StoryStarted`` event (same ``run_id`` + ``story_key``) and using
    ``(model, complexity)``. Without this correlation the table is
    permanently empty on real ledgers, silently defaulting every M03 cost
    estimate and M08 drift baseline to the 0.5 unseen-pair fallback. The
    direct-attribute path is retained so a future schema (or a test shim)
    that does emit ``model_id``/``task_kind`` keeps working unchanged.
    """

    total_scanned = 0
    buckets: dict[tuple[str, str], list] = {}
    correlation: dict[tuple[str, str], tuple[str, str]] = {}
    pending: list[tuple[bool, str, str, object]] = []
    for line in lines:
        try:
            event = parse_event(line)
        except (ValueError, json.JSONDecodeError, TypeError):
            continue
        total_scanned += 1
        if isinstance(event, StoryStarted):
            run_id = getattr(event, "run_id", None)
            story_key = getattr(event, "story_key", None)
            model = getattr(event, "model", None)
            complexity = getattr(event, "complexity", None)
            if (
                isinstance(run_id, str)
                and isinstance(story_key, str)
                and isinstance(model, str)
                and isinstance(complexity, str)
            ):
                correlation[(run_id, story_key)] = (model, complexity)
            continue
        if not isinstance(event, (StoryCompleted, StoryFailed)):
            continue
        completed = isinstance(event, StoryCompleted)
        model_id = getattr(event, "model_id", None)
        task_kind = getattr(event, "task_kind", None)
        if isinstance(model_id, str) and isinstance(task_kind, str):
            _bump_bucket(
                buckets, (model_id, task_kind), completed=completed, timestamp=event.timestamp
            )
            continue
        # No direct model_id/task_kind — defer until the full StoryStarted
        # correlation map is known (a started event can appear after its
        # completion in a merged or out-of-order ledger).
        run_id = getattr(event, "run_id", None)
        story_key = getattr(event, "story_key", None)
        if isinstance(run_id, str) and isinstance(story_key, str):
            pending.append((completed, run_id, story_key, event.timestamp))
    for completed, run_id, story_key, timestamp in pending:
        key = correlation.get((run_id, story_key))
        if key is None:
            continue
        _bump_bucket(buckets, key, completed=completed, timestamp=timestamp)
    return total_scanned, buckets


def _materialize_entries(
    buckets: dict[tuple[str, str], list],
) -> dict[tuple[str, str], CalibrationEntry]:
    """Convert raw bucket triples into immutable CalibrationEntry rows.

    Rounds success_rate to four decimal places per REQ-07.
    """

    entries: dict[tuple[str, str], CalibrationEntry] = {}
    for (model_id, task_kind), (completed, failed, last_seen) in buckets.items():
        sample_count = completed + failed
        success_rate = round(completed / sample_count, 4)
        entries[(model_id, task_kind)] = CalibrationEntry(
            model_id=model_id,
            task_kind=task_kind,
            success_rate=success_rate,
            sample_count=sample_count,
            last_seen_iso=last_seen,
        )
    return entries


def build_calibration(jsonl_path: str | Path) -> CalibrationTable:
    """Build a CalibrationTable by streaming a JSONL telemetry ledger.

    Missing paths return an empty table (not an exception). Each
    successfully parsed line increments `total_events_scanned`;
    only StoryCompleted / StoryFailed records with both `model_id`
    and `task_kind` attributes contribute to `entries`.
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
    total_scanned, buckets = _accumulate_buckets(_iter_event_lines(path))
    return CalibrationTable(
        entries=_materialize_entries(buckets),
        generated_at=iso_now(),
        source_path=source_path,
        total_events_scanned=total_scanned,
    )


def lookup_success_rate(
    table: CalibrationTable,
    model_id: str,
    task_kind: str,
    default: float = 0.5,
) -> float:
    """Return the stored success rate for `(model_id, task_kind)`.

    The default is 0.5, which models maximum uncertainty for an
    unseen pair — see REQ-09. Callers (e.g. M03's `sw estimate`) rely
    on this exact default; changing it without coordinating with M03
    would silently shift cost-estimate confidence bands.
    """

    entry = table.entries.get((model_id, task_kind))
    if entry is None:
        return default
    return entry.success_rate


def format_calibration_report(table: CalibrationTable) -> str:
    """Emit a deterministic plain-ASCII calibration report.

    Line 1: `source: <path>`.
    Line 2: tab-separated column header.
    Body: one row per entry, sorted by `(model_id, task_kind)`.
    Trailing newline (single).

    Caller note: `last_seen_iso` is rendered verbatim. The aggregator
    guarantees ASCII when the timestamps come from `iso_now()`, which
    is the only producer M02 uses.
    """

    lines: list[str] = [f"source: {table.source_path}"]
    lines.append("model_id\ttask_kind\tsuccess_rate\tsample_count\tlast_seen_iso")
    for key in sorted(table.entries.keys()):
        entry = table.entries[key]
        lines.append(
            f"{entry.model_id}\t{entry.task_kind}\t{entry.success_rate:.4f}\t"
            f"{entry.sample_count}\t{entry.last_seen_iso}"
        )
    return "\n".join(lines) + "\n"
