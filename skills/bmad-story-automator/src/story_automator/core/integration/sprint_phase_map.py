"""Sprint-status / bmad-auto Phase dual-store map.

M48 — story-automator owns ``sprint-status.yaml`` as the authoritative
ledger of story progress; bmad-auto's :class:`Phase` lifecycle is the
authoritative ledger of *what stage of the dev loop* a story is in. Both
stores must agree on every story.

This module is the canonical bridge:

* :class:`Phase` mirrors the 11-value bmad-auto lifecycle (inlined here
  because ``core/phase_bridge`` is not yet on this branch — when it
  lands, this file may switch to ``from ..phase_bridge import Phase``
  with no other change).
* :data:`SPRINT_STATUS_TO_PHASE` is the deterministic forward map.
* :data:`PHASE_TO_SPRINT_STATUS` is the inverse (lossy — many phases
  collapse onto one sprint-status string).
* :func:`compute_dual_state` reads both stores for one story and
  returns a paired snapshot, flagging inconsistencies.
* :func:`validate_dual_store` walks every story across both stores
  and reports mismatches.
* :func:`write_phase` is the atomic, idempotent writer for the phase
  store sibling of ``sprint-status.yaml``.

Stdlib only. Side-effects limited to atomic file writes via
:func:`story_automator.core.utils.write_atomic`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..artifact_paths import implementation_artifacts_dir
from ..sprint import sprint_status_get
from ..story_keys import sprint_status_file
from ..utils import file_exists, read_text, trim_lines, write_atomic


# ---------------------------------------------------------------------------
# Phase enum (mirrors bmad-auto's automator.model.Phase)
# ---------------------------------------------------------------------------


class Phase(StrEnum):
    """Story lifecycle phase — mirrors bmad-auto's 11-value StrEnum.

    Values are kebab-case ASCII so they round-trip through YAML/JSON and
    are stable across both stores.
    """

    PENDING = "pending"
    DEV_RUNNING = "dev-running"
    DEV_VERIFY = "dev-verify"
    REVIEW_RUNNING = "review-running"
    REVIEW_VERIFY = "review-verify"
    COMMITTING = "committing"
    TRIAGE_RUNNING = "triage-running"
    TRIAGE_VERIFY = "triage-verify"
    DONE = "done"
    DEFERRED = "deferred"
    ESCALATED = "escalated"


TERMINAL_PHASES: frozenset[Phase] = frozenset(
    {Phase.DONE, Phase.DEFERRED, Phase.ESCALATED}
)
"""Phases after which no further story work happens."""


# ---------------------------------------------------------------------------
# Sprint-status vocabulary
# ---------------------------------------------------------------------------


# The canonical sprint-status string vocabulary read from sprint-status.yaml.
# Values not in this set are still parsed by sprint_status_get (so that a
# misspelled status surfaces as inconsistency rather than a crash) but are
# treated as unknown by the dual-store invariant.
SPRINT_STATUS_TO_PHASE: dict[str, Phase] = {
    "done": Phase.DONE,
    "deferred": Phase.DEFERRED,
    "escalated": Phase.ESCALATED,
    "in-progress": Phase.DEV_RUNNING,
    "dev-running": Phase.DEV_RUNNING,
    "dev-verify": Phase.DEV_VERIFY,
    "review-running": Phase.REVIEW_RUNNING,
    "review-verify": Phase.REVIEW_VERIFY,
    "committing": Phase.COMMITTING,
    "triage-running": Phase.TRIAGE_RUNNING,
    "triage-verify": Phase.TRIAGE_VERIFY,
    "not_started": Phase.PENDING,
    "not-started": Phase.PENDING,
    "pending": Phase.PENDING,
}
"""Forward map: sprint-status string → bmad-auto :class:`Phase`."""


# Inverse map: phase → canonical sprint-status string. Lossy by design.
# These are the strings story-automator writes back into sprint-status.yaml.
PHASE_TO_SPRINT_STATUS: dict[Phase, str] = {
    Phase.PENDING: "not_started",
    Phase.DEV_RUNNING: "in-progress",
    Phase.DEV_VERIFY: "dev-verify",
    Phase.REVIEW_RUNNING: "review-running",
    Phase.REVIEW_VERIFY: "review-verify",
    Phase.COMMITTING: "committing",
    Phase.TRIAGE_RUNNING: "triage-running",
    Phase.TRIAGE_VERIFY: "triage-verify",
    Phase.DONE: "done",
    Phase.DEFERRED: "deferred",
    Phase.ESCALATED: "escalated",
}
"""Inverse map: :class:`Phase` → canonical sprint-status string."""


# Reverse the inverse map back to phases — when callers ask "is this
# pair consistent?" we accept any sprint-status string in the forward map
# that points to a Phase whose own canonical string matches.
def _consistent_status_for_phase(phase: Phase) -> frozenset[str]:
    canonical = PHASE_TO_SPRINT_STATUS[phase]
    extras = {s for s, p in SPRINT_STATUS_TO_PHASE.items() if p is phase}
    extras.add(canonical)
    return frozenset(extras)


_PHASE_TO_ACCEPTED_STATUSES: dict[Phase, frozenset[str]] = {
    phase: _consistent_status_for_phase(phase) for phase in Phase
}


# ---------------------------------------------------------------------------
# Errors and dataclasses
# ---------------------------------------------------------------------------


class DualStoreError(ValueError):
    """Raised when a dual-store operation cannot proceed safely.

    Examples: unknown sprint-status string, unknown phase string, corrupt
    phase-store file.
    """


@dataclass(frozen=True)
class Inconsistency:
    """One row's worth of disagreement between the two stores."""

    story_key: str
    sprint_status: str  # empty string if the sprint-status row is missing
    phase: Phase


class DualStoreInconsistencyError(DualStoreError):
    """Raised by strict callers when any row is inconsistent.

    Carries the full list of findings so the caller can surface them
    without re-running ``validate_dual_store``.
    """

    def __init__(self, message: str, findings: list[Inconsistency]) -> None:
        super().__init__(message)
        self.findings: list[Inconsistency] = list(findings)


@dataclass(frozen=True)
class DualStoreState:
    """Paired snapshot of one story's sprint-status and Phase.

    * ``found`` — whether the sprint-status row was located.
    * ``sprint_status`` — raw string from sprint-status.yaml
      (``"unknown"`` / ``"not_found"`` when missing).
    * ``phase`` — the Phase recorded in the phase store; falls back to
      the phase derived from sprint-status when the store has no entry.
    * ``phase_derived`` — True when ``phase`` came from sprint-status
      rather than the explicit phase store.
    * ``consistent`` — True iff both stores agree (or only one store has
      a value and the derived match holds).
    """

    found: bool
    story_key: str
    sprint_status: str
    phase: Phase
    phase_derived: bool
    consistent: bool


# ---------------------------------------------------------------------------
# Pure translators
# ---------------------------------------------------------------------------


def phase_for_sprint_status(status: str) -> Phase | None:
    """Return the Phase for a sprint-status string, or ``None`` if unknown.

    Fail-soft — unknown statuses return ``None`` so callers can surface
    the inconsistency without exploding mid-iteration.
    """

    if not isinstance(status, str):
        return None
    return SPRINT_STATUS_TO_PHASE.get(status.strip())


def sprint_status_for_phase(phase: Phase | str) -> str:
    """Return the canonical sprint-status string for ``phase``.

    Accepts either a :class:`Phase` member or its string value. Raises
    :class:`DualStoreError` for unknown inputs — this is the strict
    direction because we are about to write the result back into a
    user-visible store.
    """

    if isinstance(phase, Phase):
        return PHASE_TO_SPRINT_STATUS[phase]
    if not isinstance(phase, str):
        raise DualStoreError(f"phase must be Phase or str, got {type(phase).__name__}")
    try:
        member = Phase(phase.strip())
    except ValueError as exc:
        raise DualStoreError(f"unknown phase: {phase!r}") from exc
    return PHASE_TO_SPRINT_STATUS[member]


def is_consistent(sprint_status: str, phase: Phase | str) -> bool:
    """Return True iff ``sprint_status`` and ``phase`` agree.

    Fail-closed on unknown inputs — an unparseable store cannot be
    trusted, so this function returns False rather than guessing.
    """

    if not isinstance(sprint_status, str):
        return False
    if isinstance(phase, Phase):
        member: Phase = phase
    elif isinstance(phase, str):
        try:
            member = Phase(phase.strip())
        except ValueError:
            return False
    else:
        return False
    return sprint_status.strip() in _PHASE_TO_ACCEPTED_STATUSES[member]


# ---------------------------------------------------------------------------
# Phase store — sibling of sprint-status.yaml
# ---------------------------------------------------------------------------


def phase_store_path(project_root: str | Path) -> Path:
    """Return the path to the phase store for ``project_root``.

    Layout: ``<implementation_artifacts_dir>/phase-store.yaml``. Lives
    next to ``sprint-status.yaml`` so backups / archival pick it up
    automatically.
    """

    return implementation_artifacts_dir(project_root) / "phase-store.yaml"


_PHASE_LINE = re.compile(r"^\s*([^:#\s][^:]*):\s*([A-Za-z][A-Za-z0-9-]*)\s*(?:#.*)?$")


def read_phase_store(project_root: str | Path) -> dict[str, Phase]:
    """Read the phase store file and return ``{story_key: Phase}``.

    A missing file is treated as an empty store. An unparseable phase
    value raises :class:`DualStoreError` — this is loud because the
    store is small and operator-visible.
    """

    path = phase_store_path(project_root)
    if not file_exists(path):
        return {}
    out: dict[str, Phase] = {}
    for raw in trim_lines(read_text(path)):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _PHASE_LINE.match(stripped)
        if match is None:
            # Tolerate unrelated lines (e.g. a yaml document header).
            continue
        key, value = match.group(1).strip(), match.group(2).strip()
        try:
            out[key] = Phase(value)
        except ValueError as exc:
            raise DualStoreError(
                f"phase store has unknown phase {value!r} for key {key!r}"
            ) from exc
    return out


def write_phase(
    project_root: str | Path, story_key: str, phase: Phase | str
) -> None:
    """Write ``{story_key: phase}`` into the phase store.

    Atomic — writes via :func:`write_atomic`. Idempotent — if the entry
    already exists with the same value the file is rewritten with
    identical bytes (so callers can call this on every state transition
    without worrying about no-op churn corrupting hash chains).

    Raises :class:`DualStoreError` for unknown phase strings.
    """

    member = _coerce_phase(phase)
    if not isinstance(story_key, str) or not story_key.strip():
        raise DualStoreError("story_key must be a non-empty string")
    key = story_key.strip()
    existing = read_phase_store(project_root)
    existing[key] = member
    _write_phase_store(project_root, existing)


def _coerce_phase(phase: Phase | str) -> Phase:
    if isinstance(phase, Phase):
        return phase
    if not isinstance(phase, str):
        raise DualStoreError(
            f"phase must be Phase or str, got {type(phase).__name__}"
        )
    try:
        return Phase(phase.strip())
    except ValueError as exc:
        raise DualStoreError(f"unknown phase: {phase!r}") from exc


def _write_phase_store(
    project_root: str | Path, entries: dict[str, Phase]
) -> None:
    path = phase_store_path(project_root)
    # Deterministic ordering — sort by key so diffs stay small.
    lines = [f"{key}: {entries[key].value}" for key in sorted(entries)]
    body = "\n".join(lines) + ("\n" if lines else "")
    write_atomic(path, body)


# ---------------------------------------------------------------------------
# Dual-store compute + validation
# ---------------------------------------------------------------------------


def compute_dual_state(project_root: str | Path, story_key: str) -> DualStoreState:
    """Read both stores for ``story_key`` and return the paired snapshot.

    Behavior:

    * If sprint-status.yaml has no row, ``found`` is False and the rest
      of the fields are best-effort defaults.
    * If the phase store has no entry, Phase is derived from sprint
      status (``phase_derived=True``).
    * ``consistent`` is True iff the stored Phase (or derived Phase) and
      sprint-status agree under :func:`is_consistent`.
    """

    if not isinstance(story_key, str) or not story_key.strip():
        raise DualStoreError("story_key must be a non-empty string")
    key = story_key.strip()
    sprint = sprint_status_get(str(project_root), key)
    phase_store = read_phase_store(project_root)

    # Phase store may key by canonical id ("1.1") or the descriptive slug
    # row ("1-1-host-feasibility-probe"). Try the literal key first,
    # then the sprint-status canonical key.
    stored_phase = phase_store.get(key) or phase_store.get(sprint.story)

    if not sprint.found:
        if stored_phase is None:
            return DualStoreState(
                found=False,
                story_key=key,
                sprint_status=sprint.status,
                phase=Phase.PENDING,
                phase_derived=True,
                consistent=False,
            )
        # Sprint missing but phase known — flag inconsistent.
        return DualStoreState(
            found=False,
            story_key=key,
            sprint_status=sprint.status,
            phase=stored_phase,
            phase_derived=False,
            consistent=False,
        )

    if stored_phase is None:
        derived = phase_for_sprint_status(sprint.status)
        if derived is None:
            return DualStoreState(
                found=True,
                story_key=sprint.story,
                sprint_status=sprint.status,
                phase=Phase.PENDING,
                phase_derived=True,
                consistent=False,
            )
        return DualStoreState(
            found=True,
            story_key=sprint.story,
            sprint_status=sprint.status,
            phase=derived,
            phase_derived=True,
            consistent=True,
        )

    return DualStoreState(
        found=True,
        story_key=sprint.story,
        sprint_status=sprint.status,
        phase=stored_phase,
        phase_derived=False,
        consistent=is_consistent(sprint.status, stored_phase),
    )


def validate_dual_store(project_root: str | Path) -> list[Inconsistency]:
    """Walk every story in both stores and return mismatched rows.

    Strategy:

    * Iterate every phase-store entry; for each one resolve the
      corresponding sprint-status row and check consistency.
    * Orphan phase-store entries (no sprint-status row) are reported
      with ``sprint_status=""``.
    * Sprint-status rows without a phase entry are *not* flagged — they
      are derivable, so the dual-store invariant is preserved by
      ``compute_dual_state`` at read time.

    Returns a deterministic list ordered by story key.
    """

    phase_store = read_phase_store(project_root)
    if not phase_store:
        return []

    findings: list[Inconsistency] = []
    sprint_path = sprint_status_file(str(project_root))
    sprint_present = file_exists(sprint_path)

    for key in sorted(phase_store):
        phase = phase_store[key]
        if not sprint_present:
            findings.append(Inconsistency(key, "", phase))
            continue
        state = sprint_status_get(str(project_root), key)
        if not state.found:
            findings.append(Inconsistency(key, "", phase))
            continue
        if not is_consistent(state.status, phase):
            findings.append(Inconsistency(key, state.status, phase))
    return findings


__all__ = [
    "DualStoreError",
    "DualStoreInconsistencyError",
    "DualStoreState",
    "Inconsistency",
    "PHASE_TO_SPRINT_STATUS",
    "Phase",
    "SPRINT_STATUS_TO_PHASE",
    "TERMINAL_PHASES",
    "compute_dual_state",
    "is_consistent",
    "phase_for_sprint_status",
    "phase_store_path",
    "read_phase_store",
    "sprint_status_for_phase",
    "validate_dual_store",
    "write_phase",
]
