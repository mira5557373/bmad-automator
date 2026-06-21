"""Phase bridge — story lifecycle phase enum ported from bmad-auto.

Mirrors the 11-value ``Phase`` StrEnum defined in
``external/bmad-auto/src/automator/model.py`` so the story-automator can
interoperate with bmad-auto state files and pause-stage semantics.

Public surface:

- :class:`Phase` — 11 kebab-case lifecycle states.
- :data:`TERMINAL_PHASES` — phases that end a story (done/deferred/escalated).
- :data:`PAUSE_STAGES` — string identifiers for pauseable orchestrator stages.
- :data:`STEP_TO_PHASES` / :data:`PHASE_TO_STEP` — bidirectional mapping
  between the 5-step story-automator pipeline and the 11-phase bmad-auto
  lifecycle.
- :func:`is_terminal_phase`, :func:`pause_stage_for_phase`,
  :func:`step_for_phase`, :func:`phases_for_step` — convenience helpers.

This module is import-light (stdlib only) and free of side effects, so it
is safe to import from any layer (commands, collectors, orchestrator).
"""

from __future__ import annotations

from enum import StrEnum


class Phase(StrEnum):
    """Story lifecycle phase — mirrors bmad-auto's ``automator.model.Phase``.

    Values are kebab-case strings so they round-trip cleanly through JSON
    state files shared with bmad-auto.
    """

    PENDING = "pending"
    DEV_RUNNING = "dev-running"
    DEV_VERIFY = "dev-verify"
    REVIEW_RUNNING = "review-running"
    REVIEW_VERIFY = "review-verify"
    COMMITTING = "committing"
    # sweep-only: triage session classifying open deferred-work entries
    TRIAGE_RUNNING = "triage-running"
    TRIAGE_VERIFY = "triage-verify"
    DONE = "done"
    DEFERRED = "deferred"
    ESCALATED = "escalated"


TERMINAL_PHASES: frozenset[Phase] = frozenset(
    {Phase.DONE, Phase.DEFERRED, Phase.ESCALATED}
)
"""Phases after which no further work happens on the story."""


PAUSE_STAGES: frozenset[str] = frozenset(
    {"spec-approval", "epic-boundary", "escalation", "story-gate"}
)
"""String identifiers recorded in ``RunState.paused_stage`` by bmad-auto."""


# Story-automator's 5-step pipeline mapped onto bmad-auto's 11 phases.
#
# - ``create`` = pending — work has been queued but not yet picked up
# - ``dev``    = active development + its verify hand-off
# - ``auto``   = automated commit hand-off
# - ``review`` = adversarial review running + its verify hand-off
# - ``retro``  = retrospective sweep (triage running + verify) plus the
#                terminal states (done/deferred/escalated) that close the
#                story's retro book
STEP_TO_PHASES: dict[str, frozenset[Phase]] = {
    "create": frozenset({Phase.PENDING}),
    "dev": frozenset({Phase.DEV_RUNNING, Phase.DEV_VERIFY}),
    "auto": frozenset({Phase.COMMITTING}),
    "review": frozenset({Phase.REVIEW_RUNNING, Phase.REVIEW_VERIFY}),
    "retro": frozenset(
        {
            Phase.TRIAGE_RUNNING,
            Phase.TRIAGE_VERIFY,
            Phase.DONE,
            Phase.DEFERRED,
            Phase.ESCALATED,
        }
    ),
}
"""Forward map: 5-step pipeline name → set of bmad-auto phases."""


def _build_phase_to_step() -> dict[Phase, str]:
    mapping: dict[Phase, str] = {}
    for step, phases in STEP_TO_PHASES.items():
        for phase in phases:
            if phase in mapping:  # pragma: no cover - guarded by tests
                raise RuntimeError(
                    f"phase {phase!r} mapped to multiple steps "
                    f"({mapping[phase]!r} and {step!r})"
                )
            mapping[phase] = step
    return mapping


PHASE_TO_STEP: dict[Phase, str] = _build_phase_to_step()
"""Inverse map: bmad-auto phase → 5-step pipeline name."""


# Phase → pause-stage when paused. Only ``ESCALATED`` has a one-to-one
# mapping; other pause stages (spec-approval, epic-boundary, story-gate)
# are recorded by the orchestrator at workflow boundaries, not by a phase.
_PHASE_TO_PAUSE_STAGE: dict[Phase, str] = {
    Phase.ESCALATED: "escalation",
}


def is_terminal_phase(phase: Phase | str) -> bool:
    """Return True if ``phase`` ends the story's lifecycle.

    Accepts either a :class:`Phase` member or its string value, so callers
    that loaded a phase from JSON do not need to coerce first. Unknown
    strings return False (fail-soft — the caller is expected to validate
    inputs separately if strictness is required).
    """

    try:
        normalized = Phase(phase) if not isinstance(phase, Phase) else phase
    except ValueError:
        return False
    return normalized in TERMINAL_PHASES


def pause_stage_for_phase(phase: Phase | str) -> str | None:
    """Return the pause-stage string for ``phase``, or None if not pauseable.

    Accepts either a :class:`Phase` or its string value. Unknown inputs
    return None (fail-soft).
    """

    try:
        normalized = Phase(phase) if not isinstance(phase, Phase) else phase
    except ValueError:
        return None
    return _PHASE_TO_PAUSE_STAGE.get(normalized)


def step_for_phase(phase: Phase | str) -> str:
    """Return the 5-step pipeline name for ``phase``.

    Raises :class:`KeyError` if ``phase`` is not a valid :class:`Phase`.
    """

    if not isinstance(phase, Phase):
        try:
            phase = Phase(phase)
        except ValueError as exc:
            raise KeyError(phase) from exc
    return PHASE_TO_STEP[phase]


def phases_for_step(step: str) -> frozenset[Phase]:
    """Return the frozen set of phases that belong to ``step``.

    Raises :class:`KeyError` if ``step`` is not one of the 5 known steps.
    """

    return STEP_TO_PHASES[step]


__all__ = [
    "PAUSE_STAGES",
    "PHASE_TO_STEP",
    "STEP_TO_PHASES",
    "TERMINAL_PHASES",
    "Phase",
    "is_terminal_phase",
    "pause_stage_for_phase",
    "phases_for_step",
    "step_for_phase",
]
