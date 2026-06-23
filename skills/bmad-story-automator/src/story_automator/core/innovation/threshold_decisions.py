"""Append-only decision ledger for C5 self-improving-gate proposals.

The C5 milestone introduces a proposer (``threshold_proposer.py``) and
an apply step (``threshold_apply.py``) for tuning ``PRIORITY_THRESHOLDS``
in ``core/gate_rules.py``. Every accept / reject / superseded /
confirm_failed decision against a ``ThresholdProposal`` is recorded on
disk as one JSONL line under
``<project_root>/_bmad/calibration/decisions.jsonl``.

The writer pattern is intentionally identical to
:func:`spec_drift_persistence.append_drift_event` — the durable
``os.open(O_WRONLY|O_CREAT|O_APPEND, 0o600)`` + ``os.fsync(fd)`` idiom
inside the filelock-held region — so a crash after lock release cannot
lose the most recent decision. The filelock at
``_bmad/calibration/.calibration.lock`` (30s timeout) serializes
proposal writes, decision appends, and apply runs across processes.

Stdlib + ``filelock`` only — honors the project's hard dep guardrail.
The module is deliberately small (≪ 500 LOC) so the audit-floor
``ThresholdLockIsolationInvariant`` AST scan over
``core/innovation/threshold_*.py`` stays trivially structural.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from filelock import FileLock, Timeout

from story_automator.core.common import compact_json, iso_now

__all__ = [
    "ACTIONS",
    "ACTION_ACCEPT",
    "ACTION_CONFIRM_FAILED",
    "ACTION_REJECT",
    "ACTION_SUPERSEDED",
    "CALIBRATION_LOCK_TIMEOUT_S",
    "DecisionLedgerError",
    "DecisionRecord",
    "calibration_dir",
    "calibration_lock_path",
    "decisions_path",
    "latest_decision_for",
    "load_decisions",
    "record_decision",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


ACTION_ACCEPT: Literal["accept"] = "accept"
ACTION_REJECT: Literal["reject"] = "reject"
ACTION_SUPERSEDED: Literal["superseded"] = "superseded"
ACTION_CONFIRM_FAILED: Literal["confirm_failed"] = "confirm_failed"

ACTIONS: frozenset[str] = frozenset(
    {ACTION_ACCEPT, ACTION_REJECT, ACTION_SUPERSEDED, ACTION_CONFIRM_FAILED}
)
"""Closed action vocabulary for the decision ledger (spec §5.3)."""


CALIBRATION_LOCK_TIMEOUT_S: float = 30.0
"""Filelock timeout (seconds) for ``.calibration.lock`` acquisition.

Matches the 30s convention used elsewhere in the gate stack
(``DRIFT_LOCK_TIMEOUT_S``, gate-orchestrator locks). Short enough to
fail fast on a wedged holder, long enough to absorb realistic
contention between proposer / decision / apply writers."""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DecisionLedgerError(RuntimeError):
    """Raised when the ledger cannot be written / read durably.

    Surfaced for: invalid ``action`` value, lock-acquire timeout, and
    corrupt-but-non-empty existing ledger lines on read. A missing
    ledger file (no decisions yet) returns an empty list — that is not
    an error.
    """


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def calibration_dir(project_root: Path | str, *, create: bool = False) -> Path:
    """Return ``<project_root>/_bmad/calibration/``.

    ``create=True`` lazily makes the directory (parents=True). Used by
    :func:`record_decision` so the first append on a fresh ``_bmad/``
    tree succeeds without the caller pre-creating anything (AC-D-07).
    """
    root = Path(project_root) / "_bmad" / "calibration"
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def decisions_path(project_root: Path | str) -> Path:
    """Path of the append-only ``decisions.jsonl`` ledger."""
    return calibration_dir(project_root) / "decisions.jsonl"


def calibration_lock_path(project_root: Path | str) -> Path:
    """Path of the ``.calibration.lock`` filelock sidecar.

    The lock lives in ``_bmad/calibration/`` so it shares a directory
    with the artifacts it serializes (proposals, decisions, applied
    records) — same-volume by construction, which keeps the
    ``os.replace`` atomicity contract of any later
    ``write_atomic_text`` calls intact.

    The audit-floor ``ThresholdLockIsolationInvariant`` AST-rejects
    any ``FileLock(...)`` construction in ``core/innovation/threshold_*``
    whose literal path arg does not end with ``.calibration.lock`` —
    that is why we centralize the path via this helper and only ever
    pass its return value as the ``FileLock`` argument.
    """
    return calibration_dir(project_root) / ".calibration.lock"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass(kw_only=True, frozen=True)
class DecisionRecord:
    """One operator decision against a ``ThresholdProposal``.

    Fields mirror the on-disk JSONL shape in spec §5.3 exactly:

    * ``proposal_id`` — 16-hex deterministic id of the targeted
      proposal.
    * ``action`` — one of :data:`ACTIONS` (``accept`` / ``reject`` /
      ``superseded`` / ``confirm_failed``).
    * ``operator_id`` — ``"local"`` for single-user CI / VPS deployments,
      or a richer identifier when multi-operator policy lands.
    * ``decided_at_iso`` — UTC iso8601 (``YYYY-MM-DDTHH:MM:SSZ``)
      stamped at write time by :func:`record_decision`.
    * ``operator_note`` — free-form rationale; empty string when not
      provided (spec example for ``accept`` shows ``""``).
    """

    proposal_id: str
    action: str
    operator_id: str
    decided_at_iso: str
    operator_note: str

    def to_dict(self) -> dict:
        """Serialize to the canonical JSONL shape (field order fixed)."""
        return {
            "proposal_id": self.proposal_id,
            "action": self.action,
            "operator_id": self.operator_id,
            "decided_at_iso": self.decided_at_iso,
            "operator_note": self.operator_note,
        }


def _record_from_dict(data: dict) -> DecisionRecord:
    """Build a :class:`DecisionRecord` from one parsed JSONL line.

    Tolerant of an absent ``operator_note`` field (defaults to ``""``)
    so older lines without it still round-trip; everything else is
    required and surfaces a ``KeyError`` to the caller, which
    :func:`load_decisions` translates into ``DecisionLedgerError``.
    """
    return DecisionRecord(
        proposal_id=str(data["proposal_id"]),
        action=str(data["action"]),
        operator_id=str(data["operator_id"]),
        decided_at_iso=str(data["decided_at_iso"]),
        operator_note=str(data.get("operator_note", "")),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def record_decision(
    project_root: Path | str,
    proposal_id: str,
    action: str,
    operator_id: str,
    operator_note: str = "",
) -> DecisionRecord:
    """Append one durable JSONL decision line to ``decisions.jsonl``.

    Acquires ``.calibration.lock`` (30s timeout), then performs:

    1. ``os.open(O_WRONLY | O_CREAT | O_APPEND, 0o600)``
    2. ``os.write(fd, payload + b"\\n")``
    3. ``os.fsync(fd)`` — **before** lock release so a crash after
       release still has the durable line on disk (AC-D-06).
    4. ``os.close(fd)``
    5. Release lock.

    The ``_bmad/calibration/`` directory is lazily created under the
    lock so the first decision on a fresh ``_bmad/`` tree succeeds
    (AC-D-07). Returns the :class:`DecisionRecord` that was appended,
    so callers can stamp audit events without re-reading the file.
    """
    if action not in ACTIONS:
        raise DecisionLedgerError(f"invalid action {action!r}: must be one of {sorted(ACTIONS)}")

    record = DecisionRecord(
        proposal_id=proposal_id,
        action=action,
        operator_id=operator_id,
        decided_at_iso=iso_now(),
        operator_note=operator_note,
    )
    payload = compact_json(record.to_dict()).encode("utf-8") + b"\n"

    calibration_dir(project_root, create=True)
    target = decisions_path(project_root)
    lock = FileLock(str(calibration_lock_path(project_root)))
    try:
        lock.acquire(timeout=CALIBRATION_LOCK_TIMEOUT_S)
    except Timeout as err:
        raise DecisionLedgerError(
            f"timeout acquiring calibration lock at {calibration_lock_path(project_root)}"
        ) from err
    try:
        fd = os.open(
            str(target),
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        lock.release()
    return record


def load_decisions(
    project_root: Path | str,
    proposal_id: str | None = None,
) -> list[DecisionRecord]:
    """Return all decisions, optionally filtered by ``proposal_id``.

    Read order is the file's natural append order — callers can rely
    on the last matching entry being the most recent (used by
    :func:`latest_decision_for`).

    Missing ledger file (no decisions yet) returns ``[]`` rather than
    raising; this matches the read-no-lock-needed contract — proposals
    are immutable after first write and the JSONL is append-only, so
    a partial line is the only failure mode and it surfaces as
    ``DecisionLedgerError`` for corruption transparency.

    Empty / whitespace-only lines are silently skipped so a stray
    newline at end-of-file does not break iteration.
    """
    path = decisions_path(project_root)
    if not path.exists():
        return []

    out: list[DecisionRecord] = []
    try:
        text = path.read_text("utf-8")
    except OSError as err:
        raise DecisionLedgerError(f"could not read decisions ledger at {path}: {err!r}") from err

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as err:
            raise DecisionLedgerError(f"corrupt JSONL at {path} line {line_no}: {err!r}") from err
        try:
            record = _record_from_dict(data)
        except KeyError as err:
            raise DecisionLedgerError(
                f"missing required field at {path} line {line_no}: {err!r}"
            ) from err
        if proposal_id is None or record.proposal_id == proposal_id:
            out.append(record)
    return out


def latest_decision_for(
    project_root: Path | str,
    proposal_id: str,
) -> DecisionRecord | None:
    """Return the most recent decision for ``proposal_id``, or ``None``.

    Used by the proposer's auto-supersede gate: a prior pending
    proposal is only superseded when the latest decision against it
    is NOT one of ``{accept, reject}`` (AC-P-13). Returns ``None`` when
    no decisions exist for the id (including the case where the
    ledger file is absent entirely).
    """
    filtered = load_decisions(project_root, proposal_id=proposal_id)
    if not filtered:
        return None
    return filtered[-1]
