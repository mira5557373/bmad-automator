"""Phase-shaped budget enforcement (M59).

Layers per-phase, per-persona spend ceilings on top of
``budget_ceilings`` primitives. Two phases are first-class today:

- ``dev-running`` — code is being authored / executed by the dev
  persona, with QA running alongside. P0 overspend here demotes to a
  ``retry_cheap`` action so the orchestrator can pick a smaller model
  and try again before escalating.
- ``review-verify`` — code review and verification. Overspend here
  always *pauses* the story; spending more on verification past the
  ceiling is a smell, not a recoverable transient.

Per-persona sub-ceilings prevent a single greedy persona (e.g. a chatty
QA agent) from starving the others within the same phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..budget_ceilings import (
    PhaseBudgetCeiling,
    BudgetLedger,
    OverspendAction,
    classify_overspend,
)

# Public phase identifiers — re-exported as constants so callers don't
# have to memorize string literals or risk typo-divergence.
PHASE_DEV_RUNNING = "dev-running"
PHASE_REVIEW_VERIFY = "review-verify"

_VALID_PHASES = {PHASE_DEV_RUNNING, PHASE_REVIEW_VERIFY}


class PhaseBudgetError(ValueError):
    """Raised when phase or persona is unknown, or spend is malformed.

    Inherits from ``ValueError`` so the orchestrator's existing input
    handling (which already catches ``ValueError`` for misconfigured
    policy) degrades gracefully without a new ``except`` arm.
    """


@dataclass(frozen=True)
class PhasePolicy:
    """Per-phase policy: per-persona ceilings plus a phase-wide overall.

    The phase-wide ceiling is the sum-cap across personas; if the
    persona ceilings already sum to <= phase_total, the phase total is
    effectively a no-op safety net.
    """

    persona_ceilings: Mapping[str, PhaseBudgetCeiling]
    phase_total: PhaseBudgetCeiling


@dataclass(frozen=True)
class PhaseBudgetConfig:
    """Static configuration for all phases the budget system knows about."""

    phases: Mapping[str, PhasePolicy]


@dataclass
class PhaseBudgetState:
    """Mutable, in-memory ledger for an orchestration run.

    A single state object covers all phases; the ``ledger`` keys use the
    convention ``"<phase>::<persona>"`` for persona-scoped spend and
    ``"<phase>::__total__"`` for phase-wide spend.
    """

    ledger: BudgetLedger = field(default_factory=BudgetLedger)


@dataclass(frozen=True)
class PhaseSpendOutcome:
    """Result of a single ``enforce_phase_spend`` call."""

    action: OverspendAction
    overspent: bool
    persona_spent: int
    persona_remaining: int
    phase_spent: int
    phase_remaining: int


def _persona_key(phase: str, persona: str) -> str:
    return f"{phase}::{persona}"


def _phase_total_key(phase: str) -> str:
    return f"{phase}::__total__"


def default_phase_budget_config() -> PhaseBudgetConfig:
    """Return the M59 baseline configuration.

    Numbers are deliberately round and conservative; downstream
    deployments can override by constructing a custom
    ``PhaseBudgetConfig``. Units are opaque "budget points" — callers
    typically map them to cents-of-LLM-spend or tokens.
    """

    dev_running = PhasePolicy(
        persona_ceilings={
            "developer": PhaseBudgetCeiling(limit=600, priority="P0"),
            "qa": PhaseBudgetCeiling(limit=300, priority="P1"),
            "scribe": PhaseBudgetCeiling(limit=100, priority="P2"),
        },
        phase_total=PhaseBudgetCeiling(limit=1000, priority="P0"),
    )
    review_verify = PhasePolicy(
        persona_ceilings={
            "reviewer": PhaseBudgetCeiling(limit=400, priority="P0"),
            "qa": PhaseBudgetCeiling(limit=200, priority="P1"),
            "scribe": PhaseBudgetCeiling(limit=100, priority="P2"),
        },
        phase_total=PhaseBudgetCeiling(limit=700, priority="P0"),
    )
    return PhaseBudgetConfig(
        phases={
            PHASE_DEV_RUNNING: dev_running,
            PHASE_REVIEW_VERIFY: review_verify,
        }
    )


def _require_phase(config: PhaseBudgetConfig, phase: str) -> PhasePolicy:
    if phase not in _VALID_PHASES or phase not in config.phases:
        raise PhaseBudgetError(f"unknown phase: {phase!r}")
    return config.phases[phase]


def _require_persona(policy: PhasePolicy, persona: str) -> PhaseBudgetCeiling:
    ceiling = policy.persona_ceilings.get(persona)
    if ceiling is None:
        raise PhaseBudgetError(
            f"unknown persona {persona!r} for phase (known: {sorted(policy.persona_ceilings)})"
        )
    return ceiling


def persona_remaining(
    config: PhaseBudgetConfig,
    state: PhaseBudgetState,
    phase: str,
    persona: str,
) -> int:
    """Return how many budget units ``persona`` has left in ``phase``."""

    policy = _require_phase(config, phase)
    ceiling = _require_persona(policy, persona)
    spent = state.ledger.total(_persona_key(phase, persona))
    return max(0, ceiling.limit - spent)


def phase_remaining(
    config: PhaseBudgetConfig,
    state: PhaseBudgetState,
    phase: str,
) -> int:
    """Return how many budget units remain in the phase-wide pool."""

    policy = _require_phase(config, phase)
    spent = state.ledger.total(_phase_total_key(phase))
    return max(0, policy.phase_total.limit - spent)


def enforce_phase_spend(
    *,
    config: PhaseBudgetConfig,
    state: PhaseBudgetState,
    phase: str,
    persona: str,
    priority: str,
    spend: int,
) -> PhaseSpendOutcome:
    """Record ``spend`` against ``(phase, persona)`` and classify the result.

    Returns a ``PhaseSpendOutcome`` describing the action the
    orchestrator should take. We always *record* the spend so the
    ledger reflects reality; the action describes what to do *next*.
    """

    if not isinstance(spend, int):
        raise PhaseBudgetError(f"spend must be int, got {type(spend).__name__}")
    if spend < 0:
        raise PhaseBudgetError(f"spend must be >= 0, got {spend}")

    policy = _require_phase(config, phase)
    persona_ceiling = _require_persona(policy, persona)

    persona_key = _persona_key(phase, persona)
    phase_key = _phase_total_key(phase)

    persona_spent = state.ledger.record(persona_key, spend)
    phase_spent = state.ledger.record(phase_key, spend)

    persona_over = persona_spent > persona_ceiling.limit
    phase_over = phase_spent > policy.phase_total.limit
    overspent = persona_over or phase_over

    if overspent:
        action = classify_overspend(priority=priority, phase=phase)
    else:
        action = OverspendAction.ALLOW

    return PhaseSpendOutcome(
        action=action,
        overspent=overspent,
        persona_spent=persona_spent,
        persona_remaining=max(0, persona_ceiling.limit - persona_spent),
        phase_spent=phase_spent,
        phase_remaining=max(0, policy.phase_total.limit - phase_spent),
    )


def summarize_phase_state(
    config: PhaseBudgetConfig,
    state: PhaseBudgetState,
    phase: str,
) -> dict[str, Any]:
    """Return a JSON-serializable summary of a phase's spend state.

    Intended for telemetry and operator UIs; keys are stable.
    """

    policy = _require_phase(config, phase)
    personas: dict[str, dict[str, int]] = {}
    for persona, ceiling in policy.persona_ceilings.items():
        spent = state.ledger.total(_persona_key(phase, persona))
        personas[persona] = {
            "limit": ceiling.limit,
            "spent": spent,
            "remaining": max(0, ceiling.limit - spent),
        }
    phase_spent = state.ledger.total(_phase_total_key(phase))
    return {
        "phase": phase,
        "phase_limit": policy.phase_total.limit,
        "phase_spent": phase_spent,
        "phase_remaining": max(0, policy.phase_total.limit - phase_spent),
        "personas": personas,
    }


__all__ = [
    "PHASE_DEV_RUNNING",
    "PHASE_REVIEW_VERIFY",
    "PhaseBudgetConfig",
    "PhaseBudgetError",
    "PhaseBudgetState",
    "PhasePolicy",
    "PhaseSpendOutcome",
    "default_phase_budget_config",
    "enforce_phase_spend",
    "persona_remaining",
    "phase_remaining",
    "summarize_phase_state",
]
