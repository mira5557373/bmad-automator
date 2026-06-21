from __future__ import annotations

"""RAMR — Risk-Aware Model Routing.

Given a BMAD persona, a risk level (P0..P3), and a workflow phase, produce a
deterministic routing decision: which CLI tool to invoke, which model to use,
and the per-call ``max_tokens`` and ``temperature`` budget.

Design invariants:

* Pure function: same inputs -> same outputs, no side effects, no I/O.
* Fail-closed: unknown inputs raise :class:`RAMRError`; never silently degrade.
* High risk (P0) -> stronger model, lower temperature, larger token budget so
  the model spends more deliberation on the call.
* Low risk (P3) -> cheaper model, slightly higher temperature, smaller token
  budget (these calls happen often and rarely move the gate verdict).
* Persona shapes the registry preference (reviewer / analyst personas prefer
  reasoning-strong CLIs; dev/qa personas prefer the default coding CLI).
* Phase further refines the choice (review/security phases bias toward
  reasoning-strong CLIs even when the persona is generic).

The module is intentionally dependency-light: no imports from other gate
subsystems. Callers can feed in their own CLI registry to override the
bundled defaults, e.g. for self-hosted models.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RAMRError(ValueError):
    """Raised when a RAMR input or registry is malformed."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


VALID_RISK_LEVELS: tuple[str, ...] = ("P0", "P1", "P2", "P3")
"""Canonical risk levels, ordered from highest (P0) to lowest (P3)."""


VALID_PHASES: tuple[str, ...] = (
    "plan",
    "design",
    "implement",
    "test",
    "review",
    "security",
    "deploy",
    "retro",
)
"""Workflow phases recognized by the router."""


DEFAULT_PERSONAS: tuple[str, ...] = (
    "analyst",
    "architect",
    "dev",
    "pm",
    "po",
    "qa",
    "reviewer",
    "sm",
)
"""Canonical BMAD personas. Custom personas can be passed via ``valid_personas``."""


# Personas that bias toward stronger reasoning models even on moderate risk.
_REASONING_PERSONAS: frozenset[str] = frozenset(
    {"architect", "reviewer", "analyst", "po"}
)


# Phases that bias toward stronger reasoning models even on moderate risk.
_REASONING_PHASES: frozenset[str] = frozenset(
    {"design", "review", "security", "retro"}
)


# ---------------------------------------------------------------------------
# Bundled CLI registry
# ---------------------------------------------------------------------------


# The default registry maps a stable cli_id -> baseline call parameters.
# ``temperature`` and ``max_tokens`` here are *baseline* values; the router
# scales them by risk before returning a decision.
DEFAULT_CLI_REGISTRY: dict[str, dict[str, Any]] = {
    "claude_opus": {
        "model": "claude-opus-4-7",
        "max_tokens": 8000,
        "temperature": 0.2,
        "tier": "strong",
    },
    "claude_sonnet": {
        "model": "claude-sonnet-4-5",
        "max_tokens": 6000,
        "temperature": 0.3,
        "tier": "balanced",
    },
    "claude_haiku": {
        "model": "claude-haiku-4-0",
        "max_tokens": 3000,
        "temperature": 0.4,
        "tier": "fast",
    },
}


# Ordering preferences. The router walks these lists from left to right and
# picks the first cli_id present in the (possibly user-overridden) registry.
_TIER_PREFERENCE_BY_RISK: dict[str, tuple[str, ...]] = {
    "P0": ("strong", "balanced", "fast"),
    "P1": ("strong", "balanced", "fast"),
    "P2": ("balanced", "strong", "fast"),
    "P3": ("fast", "balanced", "strong"),
}


# Per-risk multipliers applied to baseline temperature and max_tokens.
_RISK_TEMP_OVERRIDE: dict[str, float] = {
    "P0": 0.0,
    "P1": 0.2,
    "P2": 0.4,
    "P3": 0.7,
}


_RISK_TOKEN_MULT: dict[str, float] = {
    "P0": 1.5,
    "P1": 1.25,
    "P2": 1.0,
    "P3": 0.75,
}


# ---------------------------------------------------------------------------
# Decision schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutingDecision:
    """Immutable routing decision for one (persona, risk, phase) tuple."""

    persona: str
    risk: str
    phase: str
    cli_id: str
    model: str
    max_tokens: int
    temperature: float
    rationale: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_risk(value: Any) -> str:
    """Return the canonical risk string for ``value`` or raise :class:`RAMRError`."""
    if not isinstance(value, str) or not value.strip():
        raise RAMRError(f"risk must be a non-empty string, got {value!r}")
    candidate = value.strip().upper()
    if candidate not in VALID_RISK_LEVELS:
        raise RAMRError(
            f"unknown risk level {value!r}; expected one of {VALID_RISK_LEVELS}"
        )
    return candidate


def normalize_persona(
    value: Any,
    *,
    valid_personas: Sequence[str] | None = None,
) -> str:
    """Return the canonical persona string for ``value`` or raise.

    ``valid_personas`` defaults to :data:`DEFAULT_PERSONAS`.
    """
    if not isinstance(value, str) or not value.strip():
        raise RAMRError(f"persona must be a non-empty string, got {value!r}")
    allowed = tuple(valid_personas) if valid_personas is not None else DEFAULT_PERSONAS
    candidate = value.strip().lower()
    if candidate not in allowed:
        raise RAMRError(
            f"unknown persona {value!r}; expected one of {allowed}"
        )
    return candidate


def normalize_phase(value: Any) -> str:
    """Return the canonical phase string for ``value`` or raise."""
    if not isinstance(value, str) or not value.strip():
        raise RAMRError(f"phase must be a non-empty string, got {value!r}")
    candidate = value.strip().lower()
    if candidate not in VALID_PHASES:
        raise RAMRError(
            f"unknown phase {value!r}; expected one of {VALID_PHASES}"
        )
    return candidate


# ---------------------------------------------------------------------------
# Registry validation
# ---------------------------------------------------------------------------


_REQUIRED_REGISTRY_FIELDS: tuple[str, ...] = ("model", "max_tokens", "temperature")


def validate_cli_registry(registry: Mapping[str, Any]) -> None:
    """Raise :class:`RAMRError` if ``registry`` is malformed.

    A registry is well-formed when:

    * it is a non-empty mapping
    * every value is a mapping containing ``model``, ``max_tokens``,
      ``temperature``
    * ``max_tokens`` is a positive int
    * ``temperature`` is a float in ``[0.0, 1.0]``
    * ``model`` is a non-empty string
    """
    if not isinstance(registry, Mapping) or not registry:
        raise RAMRError("cli_registry must be a non-empty mapping")
    for cli_id, entry in registry.items():
        if not isinstance(cli_id, str) or not cli_id.strip():
            raise RAMRError(f"cli_registry key {cli_id!r} must be a non-empty string")
        if not isinstance(entry, Mapping):
            raise RAMRError(
                f"cli_registry[{cli_id!r}] must be a mapping, got {type(entry).__name__}"
            )
        for required in _REQUIRED_REGISTRY_FIELDS:
            if required not in entry:
                raise RAMRError(
                    f"cli_registry[{cli_id!r}] missing required field {required!r}"
                )
        model = entry["model"]
        if not isinstance(model, str) or not model.strip():
            raise RAMRError(
                f"cli_registry[{cli_id!r}].model must be a non-empty string"
            )
        max_tokens = entry["max_tokens"]
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            raise RAMRError(
                f"cli_registry[{cli_id!r}].max_tokens must be a positive int, "
                f"got {max_tokens!r}"
            )
        temperature = entry["temperature"]
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
            raise RAMRError(
                f"cli_registry[{cli_id!r}].temperature must be a number, "
                f"got {temperature!r}"
            )
        if not (0.0 <= float(temperature) <= 1.0):
            raise RAMRError(
                f"cli_registry[{cli_id!r}].temperature must lie in [0.0, 1.0]"
            )


# ---------------------------------------------------------------------------
# Risk-scaled values
# ---------------------------------------------------------------------------


def risk_temperature(risk: str, *, baseline: float = 0.3) -> float:
    """Return the risk-scaled temperature.

    Higher risk -> lower temperature (more deterministic).
    The function blends ``baseline`` with a risk-specific ceiling; the result
    is monotonically increasing across ``P0..P3``.
    """
    risk = normalize_risk(risk)
    if not (0.0 <= baseline <= 1.0):
        raise RAMRError(f"baseline temperature must lie in [0.0, 1.0], got {baseline}")
    ceiling = _RISK_TEMP_OVERRIDE[risk]
    # Blend: weight risk ceiling more heavily for high risk, baseline for low risk.
    weight = {"P0": 1.0, "P1": 0.7, "P2": 0.5, "P3": 0.3}[risk]
    blended = ceiling * weight + baseline * (1.0 - weight)
    return round(max(0.0, min(1.0, blended)), 4)


def risk_max_tokens(risk: str, *, baseline: int = 4000) -> int:
    """Return the risk-scaled ``max_tokens`` budget.

    Higher risk -> larger budget (more room for deliberation).
    """
    risk = normalize_risk(risk)
    if not isinstance(baseline, int) or isinstance(baseline, bool) or baseline <= 0:
        raise RAMRError(f"baseline max_tokens must be a positive int, got {baseline!r}")
    return int(baseline * _RISK_TOKEN_MULT[risk])


# ---------------------------------------------------------------------------
# CLI selection
# ---------------------------------------------------------------------------


def select_cli_for_risk(
    risk: str,
    cli_registry: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    persona: str | None = None,
    phase: str | None = None,
) -> str:
    """Return the cli_id that best fits ``risk`` for the optional persona/phase.

    Selection algorithm:

    1. Walk the tier preference list for the given risk
       (e.g. ``("strong", "balanced", "fast")`` for ``P0``).
    2. If ``persona`` or ``phase`` is in the reasoning sets and the candidate
       tier is ``"fast"`` while a ``"strong"`` or ``"balanced"`` is available,
       upgrade.
    3. Pick the first entry whose ``tier`` matches the (possibly upgraded)
       preferred tier. If no entry has a ``tier``, fall back to the first
       registry key in insertion order.
    """
    risk = normalize_risk(risk)
    registry = cli_registry if cli_registry is not None else DEFAULT_CLI_REGISTRY
    validate_cli_registry(registry)
    preferences = list(_TIER_PREFERENCE_BY_RISK[risk])
    if persona is not None or phase is not None:
        wants_reasoning = (
            (persona is not None and persona in _REASONING_PERSONAS)
            or (phase is not None and phase in _REASONING_PHASES)
        )
        if wants_reasoning:
            # Move "strong" to the front, "fast" to the back.
            preferences = [t for t in preferences if t != "fast"] + [
                t for t in preferences if t == "fast"
            ]
            if "strong" not in preferences:
                preferences.insert(0, "strong")
    for tier in preferences:
        for cli_id, entry in registry.items():
            if entry.get("tier") == tier:
                return cli_id
    # No tier metadata at all -> deterministic fallback to first key.
    return next(iter(registry.keys()))


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route(
    *,
    persona: str,
    risk: str,
    phase: str,
    cli_registry: Mapping[str, Mapping[str, Any]] | None = None,
    valid_personas: Sequence[str] | None = None,
    baseline_temperature: float = 0.3,
    baseline_max_tokens: int = 4000,
) -> RoutingDecision:
    """Return the :class:`RoutingDecision` for the given inputs.

    This is the public entry point of RAMR. The function is pure: given the
    same arguments (and the same registry) it returns equal decisions.
    """
    persona_n = normalize_persona(persona, valid_personas=valid_personas)
    risk_n = normalize_risk(risk)
    phase_n = normalize_phase(phase)
    registry = cli_registry if cli_registry is not None else DEFAULT_CLI_REGISTRY
    validate_cli_registry(registry)

    cli_id = select_cli_for_risk(
        risk_n, registry, persona=persona_n, phase=phase_n
    )
    entry = registry[cli_id]
    model = str(entry["model"])

    base_temp = float(entry.get("temperature", baseline_temperature))
    base_tokens = int(entry.get("max_tokens", baseline_max_tokens))
    temperature = risk_temperature(risk_n, baseline=base_temp)
    max_tokens = risk_max_tokens(risk_n, baseline=base_tokens)

    rationale = (
        f"risk={risk_n}: scaled temperature to {temperature:.4f} and "
        f"max_tokens to {max_tokens} from baseline ({base_temp:.4f}, "
        f"{base_tokens}).",
        f"persona={persona_n}: "
        + (
            "reasoning persona biased toward stronger CLIs."
            if persona_n in _REASONING_PERSONAS
            else "no persona-driven upgrade."
        ),
        f"phase={phase_n}: "
        + (
            "reasoning phase biased toward stronger CLIs."
            if phase_n in _REASONING_PHASES
            else "no phase-driven upgrade."
        ),
        f"selected cli_id={cli_id} (model={model}).",
    )

    return RoutingDecision(
        persona=persona_n,
        risk=risk_n,
        phase=phase_n,
        cli_id=cli_id,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        rationale=rationale,
    )


def route_many(
    triples: Iterable[tuple[str, str, str]],
    *,
    cli_registry: Mapping[str, Mapping[str, Any]] | None = None,
    valid_personas: Sequence[str] | None = None,
) -> list[RoutingDecision]:
    """Return one :class:`RoutingDecision` per ``(persona, risk, phase)`` triple.

    The input order is preserved in the output list. Any malformed triple
    short-circuits with :class:`RAMRError`.
    """
    out: list[RoutingDecision] = []
    for index, triple in enumerate(triples):
        if not isinstance(triple, tuple) or len(triple) != 3:
            raise RAMRError(
                f"route_many: input #{index} must be a (persona, risk, phase) tuple, "
                f"got {triple!r}"
            )
        persona, risk, phase = triple
        out.append(
            route(
                persona=persona,
                risk=risk,
                phase=phase,
                cli_registry=cli_registry,
                valid_personas=valid_personas,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Explanation
# ---------------------------------------------------------------------------


def explain_decision(decision: RoutingDecision) -> dict[str, Any]:
    """Return a JSON-friendly dict describing ``decision``.

    The ``rationale`` key is a single human-readable string joining the
    decision's rationale tuple with newlines. This is convenient for inclusion
    in CLI output or in evidence records.
    """
    if not isinstance(decision, RoutingDecision):
        raise RAMRError(
            f"explain_decision requires a RoutingDecision, got {type(decision).__name__}"
        )
    return {
        "persona": decision.persona,
        "risk": decision.risk,
        "phase": decision.phase,
        "cli_id": decision.cli_id,
        "model": decision.model,
        "max_tokens": decision.max_tokens,
        "temperature": decision.temperature,
        "rationale": "\n".join(decision.rationale),
    }


__all__ = [
    "RAMRError",
    "RoutingDecision",
    "DEFAULT_CLI_REGISTRY",
    "DEFAULT_PERSONAS",
    "VALID_RISK_LEVELS",
    "VALID_PHASES",
    "route",
    "route_many",
    "normalize_risk",
    "normalize_persona",
    "normalize_phase",
    "validate_cli_registry",
    "risk_temperature",
    "risk_max_tokens",
    "select_cli_for_risk",
    "explain_decision",
]
