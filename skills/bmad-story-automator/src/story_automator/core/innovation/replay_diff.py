"""Cross-CLI replay-diff analysis.

This module is layered on top of the factory's collector + evidence output.
A *replay* is the act of running the same target_ref/collector across N
``CLIProfile`` instances (e.g. ``claude-code``, ``codex``, ``gemini-cli``).
The replay-diff aligns the resulting :class:`EvidenceRecord` instances into
a ``(collector_id, target_ref) -> {cli_id -> record}`` table and reports
per-collector verdict divergence under a closed status vocabulary.

The closed vocabulary makes downstream tooling (dashboards, escalations,
CI gates) trivial:

* :data:`AGREEMENT` — every profile produced the same verdict.
* :data:`DIVERGENCE` — at least two profiles disagreed.
* :data:`MISSING_CLI` — at least one profile produced no record for the key.
* :data:`UNKNOWN_CLI` — a record carried a ``cli_id`` not declared in the
  replay's profile set (caught at alignment time; surfaced for completeness).

Design constraints:

* stdlib only — no third-party deps (enforced by ``test_no_unauthorized_imports``).
* Self-contained — defines lightweight :class:`CLIProfileRef` and
  :class:`EvidenceRecord` so downstream integration can wire in the richer
  ``core/gate_schema`` types without changing this module's contract.
* Deterministic — sort order, tie-breaks, and rendering are all stable so the
  output is safe to diff across CI runs.
* Side-effect free — no logging, no global state, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Closed status vocabulary.
# ---------------------------------------------------------------------------

AGREEMENT: str = "agreement"
DIVERGENCE: str = "divergence"
MISSING_CLI: str = "missing-cli"
UNKNOWN_CLI: str = "unknown-cli"

VALID_STATUSES: tuple[str, ...] = (AGREEMENT, DIVERGENCE, MISSING_CLI, UNKNOWN_CLI)

# Collectors emit only these verdict strings.  Anything outside the set is
# rejected eagerly so divergence rows can't silently absorb typos.
VALID_VERDICTS: tuple[str, ...] = ("pass", "fail", "error", "timeout", "skipped", "na")


# ---------------------------------------------------------------------------
# Errors.
# ---------------------------------------------------------------------------


class ReplayDiffError(ValueError):
    """Raised when replay-diff inputs are malformed.

    Subclasses :class:`ValueError` so callers can distinguish operator errors
    (bad inputs) from programming errors without a custom hierarchy.
    """


# ---------------------------------------------------------------------------
# Lightweight schemas.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CLIProfileRef:
    """Minimal reference to a CLI profile participating in a replay.

    Only the ``cli_id`` is load-bearing; ``label`` is a human-readable hint
    used by :func:`format_report`. This struct is intentionally *not* the
    same as ``core/cli_profile.CLIProfile`` — replay-diff doesn't need the
    binary/prompt-template surface and we want this module to import nothing
    from the factory runtime.
    """

    cli_id: str
    label: str = ""


@dataclass(frozen=True)
class EvidenceRecord:
    """One collector outcome from one CLIProfile replay.

    The fields mirror a subset of ``core/gate_schema.EvidenceRecord`` so that
    a downstream integration layer can adapt the richer schema into this
    struct without losing information that matters for divergence reporting.
    """

    cli_id: str
    collector_id: str
    target_ref: str
    verdict: str
    evidence_hash: str = ""
    started_at: str = ""
    ended_at: str = ""
    exit_code: int = 0
    attrs: Mapping[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Report rows.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayDiffRow:
    """One row of a :class:`ReplayDiffReport`.

    A row describes one ``(collector_id, target_ref)`` key after alignment.
    ``verdicts_by_cli`` only contains entries for CLIs that produced a
    record; missing CLIs are surfaced separately via ``missing_clis``.
    ``dominant_verdict`` is the majority verdict across the *present* CLIs
    (alphabetical tie-break) and is the empty string when no CLI produced a
    record at all.
    """

    collector_id: str
    target_ref: str
    status: str
    dominant_verdict: str
    verdicts_by_cli: Mapping[str, str]
    missing_clis: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "collector_id": self.collector_id,
            "target_ref": self.target_ref,
            "status": self.status,
            "dominant_verdict": self.dominant_verdict,
            "verdicts_by_cli": dict(self.verdicts_by_cli),
            "missing_clis": list(self.missing_clis),
        }


@dataclass(frozen=True)
class ReplayDiffReport:
    """Full replay-diff result.

    ``rows`` is sorted lexicographically by ``(collector_id, target_ref)`` so
    consecutive runs of the same inputs always produce byte-identical output.
    """

    profiles: tuple[CLIProfileRef, ...]
    rows: tuple[ReplayDiffRow, ...]

    def total_rows(self) -> int:
        return len(self.rows)

    def count(self, status: str) -> int:
        if status not in VALID_STATUSES:
            raise ReplayDiffError(f"unknown status: {status!r}")
        return sum(1 for row in self.rows if row.status == status)

    def cli_ids(self) -> tuple[str, ...]:
        return tuple(p.cli_id for p in self.profiles)

    def to_dict(self) -> dict[str, object]:
        counts = {status: self.count(status) for status in VALID_STATUSES}
        return {
            "summary": {
                "total_rows": self.total_rows(),
                "counts": counts,
            },
            "cli_ids": list(self.cli_ids()),
            "rows": [row.to_dict() for row in self.rows],
        }


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------


def _validate_profiles(profiles: Sequence[CLIProfileRef]) -> tuple[CLIProfileRef, ...]:
    """Return profiles as a tuple after rejecting empty/duplicate sets."""
    profile_tuple = tuple(profiles)
    if not profile_tuple:
        raise ReplayDiffError("at least one CLIProfileRef is required")
    seen: set[str] = set()
    for profile in profile_tuple:
        if not profile.cli_id:
            raise ReplayDiffError("CLIProfileRef.cli_id must be non-empty")
        if profile.cli_id in seen:
            raise ReplayDiffError(
                f"duplicate CLIProfileRef.cli_id: {profile.cli_id!r}"
            )
        seen.add(profile.cli_id)
    return profile_tuple


def _validate_record(record: EvidenceRecord, known_cli_ids: set[str]) -> None:
    if record.cli_id not in known_cli_ids:
        raise ReplayDiffError(
            f"evidence record references unknown cli_id {record.cli_id!r} "
            f"(known: {sorted(known_cli_ids)})"
        )
    if record.verdict not in VALID_VERDICTS:
        raise ReplayDiffError(
            f"evidence record has invalid verdict {record.verdict!r} "
            f"(allowed: {VALID_VERDICTS})"
        )
    if not record.collector_id:
        raise ReplayDiffError("evidence record collector_id must be non-empty")
    if not record.target_ref:
        raise ReplayDiffError("evidence record target_ref must be non-empty")


def _dominant_verdict(verdicts_by_cli: Mapping[str, str]) -> str:
    """Return the majority verdict; tie-break is the alphabetically smaller.

    The tie-break is documented so consumers can rely on the result being
    deterministic across runs and across Python versions.
    """
    if not verdicts_by_cli:
        return ""
    counts: dict[str, int] = {}
    for verdict in verdicts_by_cli.values():
        counts[verdict] = counts.get(verdict, 0) + 1
    # Sort by (-count, verdict) — highest count wins; alphabetical tie-break.
    best = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return best[0][0]


def _row_status(
    verdicts_by_cli: Mapping[str, str], missing_clis: Sequence[str]
) -> str:
    if missing_clis:
        return MISSING_CLI
    unique_verdicts = set(verdicts_by_cli.values())
    if len(unique_verdicts) <= 1:
        return AGREEMENT
    return DIVERGENCE


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def align_records(
    records: Iterable[EvidenceRecord],
    profiles: Sequence[CLIProfileRef],
) -> dict[tuple[str, str], dict[str, EvidenceRecord]]:
    """Align ``records`` into a ``(collector_id, target_ref) -> {cli_id -> record}`` table.

    A profile set is supplied so the function can reject records that belong
    to an unknown CLI before they corrupt the alignment table. Duplicate
    records for the same ``(collector_id, target_ref, cli_id)`` key are
    rejected — duplicates almost always mean the replay harness merged two
    runs by accident, and silently dropping one would mask the bug.
    """
    profile_tuple = _validate_profiles(profiles)
    known_cli_ids = {p.cli_id for p in profile_tuple}
    table: dict[tuple[str, str], dict[str, EvidenceRecord]] = {}
    for record in records:
        _validate_record(record, known_cli_ids)
        key = (record.collector_id, record.target_ref)
        bucket = table.setdefault(key, {})
        if record.cli_id in bucket:
            raise ReplayDiffError(
                "duplicate evidence record for "
                f"(collector_id={record.collector_id!r}, "
                f"target_ref={record.target_ref!r}, "
                f"cli_id={record.cli_id!r})"
            )
        bucket[record.cli_id] = record
    return table


def verdict_divergence(
    aligned: Mapping[tuple[str, str], Mapping[str, EvidenceRecord]],
    profiles: Sequence[CLIProfileRef],
) -> tuple[ReplayDiffRow, ...]:
    """Compute per-key divergence rows from an alignment table.

    Rows are sorted by ``(collector_id, target_ref)`` so the output is stable
    across replays — this matters when the diff is piped through ``diff``,
    or stored as JSON for CI to compare run-over-run.
    """
    profile_tuple = _validate_profiles(profiles)
    expected = tuple(p.cli_id for p in profile_tuple)
    rows: list[ReplayDiffRow] = []
    for key in sorted(aligned.keys()):
        collector_id, target_ref = key
        per_cli = aligned[key]
        verdicts: dict[str, str] = {}
        # Use the profile order so emitted dicts are deterministic.
        for cli_id in expected:
            record = per_cli.get(cli_id)
            if record is not None:
                verdicts[cli_id] = record.verdict
        missing = tuple(cli_id for cli_id in expected if cli_id not in verdicts)
        status = _row_status(verdicts, missing)
        dominant = _dominant_verdict(verdicts)
        rows.append(
            ReplayDiffRow(
                collector_id=collector_id,
                target_ref=target_ref,
                status=status,
                dominant_verdict=dominant,
                verdicts_by_cli=verdicts,
                missing_clis=missing,
            )
        )
    return tuple(rows)


def replay_diff(
    records: Iterable[EvidenceRecord],
    profiles: Sequence[CLIProfileRef],
) -> ReplayDiffReport:
    """Top-level entry point — align, diff, and wrap the result in a report.

    The return value is a :class:`ReplayDiffReport`, which is JSON-serializable
    via :meth:`ReplayDiffReport.to_dict` and renderable via :func:`format_report`.
    """
    profile_tuple = _validate_profiles(profiles)
    materialized = list(records)
    aligned = align_records(materialized, profile_tuple)
    rows = verdict_divergence(aligned, profile_tuple)
    return ReplayDiffReport(profiles=profile_tuple, rows=rows)


# ---------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------


def _format_row(row: ReplayDiffRow, cli_ids: Sequence[str]) -> str:
    parts = [f"  - {row.collector_id} :: {row.target_ref} -> {row.status}"]
    if row.dominant_verdict:
        parts.append(f"    dominant: {row.dominant_verdict}")
    if row.verdicts_by_cli:
        verdicts = ", ".join(
            f"{cli_id}={row.verdicts_by_cli[cli_id]}"
            for cli_id in cli_ids
            if cli_id in row.verdicts_by_cli
        )
        parts.append(f"    verdicts: {verdicts}")
    if row.missing_clis:
        parts.append(f"    missing: {', '.join(row.missing_clis)}")
    return "\n".join(parts)


def format_report(report: ReplayDiffReport) -> str:
    """Render a :class:`ReplayDiffReport` as a deterministic text block.

    The format is line-oriented and free of trailing whitespace so it stays
    stable under ``ruff``/``pre-commit`` whitespace checks if a caller writes
    it to a tracked file.
    """
    cli_ids = report.cli_ids()
    header = (
        "cross-cli replay diff",
        f"  profiles: {', '.join(cli_ids)}",
        f"  total rows: {report.total_rows()}",
        "  counts: "
        + ", ".join(f"{status}={report.count(status)}" for status in VALID_STATUSES),
    )
    body = tuple(_format_row(row, cli_ids) for row in report.rows)
    return "\n".join((*header, *body))
