"""ramr_review_dispatch — pre-flight RAMR routing for the BMAD review session.

The BMAD ``bmad-story-automator-review`` skill runs an adversarial code review
of a story. M55 (:func:`phase_bridge.enforce_independent_models`) catches
``(cli_id, model)`` collisions at gate time, but by then the review session has
already burned tokens producing a verdict that the gate will reject anyway.

This module pushes that check *forward* to the dispatch boundary: before any
review tmux session is spawned, the caller asks
:func:`select_reviewer_assignment` for the routing decision. The helper:

1. Routes a reviewer assignment via :func:`ramr.route` (persona=``reviewer``,
   phase=``review``).
2. If RAMR's first choice collides with the dev assignment, it scans the
   registry for an alternative ``(cli_id, model)`` that breaks the collision.
3. If no alternative exists (single-CLI / single-model registry), it raises
   :class:`ReviewDispatchEscalation` — the operator must broaden the registry
   or accept the bias risk explicitly via waiver.
4. Otherwise it runs :func:`enforce_independent_models` as a belt-and-braces
   check and returns the :class:`DispatchResult` ready for the review session
   launcher.

Design invariants (mirroring the M55 module):

* Pure function: same inputs → same outputs, no I/O, no telemetry.
* Fail-closed: malformed inputs raise :class:`ReviewDispatchError`; routing
  collisions raise :class:`ReviewDispatchEscalation` (a distinct subclass so
  callers can convert to a PREFERENCE escalation event).
* No new third-party imports — stdlib + the in-tree RAMR + phase_bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..innovation.ramr import (
    DEFAULT_CLI_REGISTRY,
    RAMRError,
    RoutingDecision,
    route,
)
from ..phase_bridge import (
    AntiBiasViolation,
    Phase,
    PhaseAssignment,
    enforce_independent_models,
)


class ReviewDispatchError(ValueError):
    """Raised when ``select_reviewer_assignment`` inputs are malformed.

    Programmer error (missing dev assignment, wrong phase, bad risk string).
    The caller should fix the call site, not retry.
    """


class ReviewDispatchEscalation(RuntimeError):
    """Raised when RAMR cannot find a reviewer that differs from the dev pair.

    The caller is expected to translate this into a PREFERENCE escalation
    event (operator must broaden the CLI registry or sign a waiver). The
    review session must NOT be spawned in this state — that would burn the
    same engine on both sides and the M55 gate would reject it anyway.
    """


@dataclass(frozen=True)
class DispatchResult:
    """Routing outcome for a single review session dispatch.

    Attributes:
        story_key: The story this dispatch is bound to (for evidence logs).
        assignment: The :class:`PhaseAssignment` for the upcoming
            ``dev-verify`` review session.
        routing_decision: The RAMR :class:`RoutingDecision` that produced
            ``assignment`` (preserves rationale + max_tokens + temperature
            so callers can record the full decision in evidence).
    """

    story_key: str
    assignment: PhaseAssignment
    routing_decision: RoutingDecision


def _validate_dev_assignment(dev: object) -> PhaseAssignment:
    if dev is None:
        raise ReviewDispatchError("dev_assignment is required")
    if not isinstance(dev, PhaseAssignment):
        raise ReviewDispatchError(
            f"dev_assignment must be a PhaseAssignment, got "
            f"{type(dev).__name__}"
        )
    if dev.phase is not Phase.DEV_RUNNING:
        raise ReviewDispatchError(
            f"dev_assignment.phase must be {Phase.DEV_RUNNING!r}, "
            f"got {dev.phase!r}"
        )
    if not dev.cli_id.strip():
        raise ReviewDispatchError("dev_assignment.cli_id must be non-empty")
    if not dev.model.strip():
        raise ReviewDispatchError("dev_assignment.model must be non-empty")
    return dev


def _validate_story_key(story_key: object) -> str:
    if not isinstance(story_key, str) or not story_key.strip():
        raise ReviewDispatchError(
            "story_key must be a non-empty string"
        )
    return story_key.strip()


def _try_alternative_reviewer(
    *,
    dev: PhaseAssignment,
    risk: str,
    persona: str,
    registry: Mapping[str, Mapping[str, Any]],
    valid_personas: Sequence[str] | None,
    primary: RoutingDecision,
) -> RoutingDecision | None:
    """Scan ``registry`` for an alternative cli_id whose model differs from dev.

    Returns a fresh :class:`RoutingDecision` (built by re-routing with a
    one-entry registry) or ``None`` when no alternative exists. The
    function never mutates the input registry.
    """
    dev_cli_lower = dev.cli_id.strip().casefold()
    candidates: list[str] = []
    for cli_id, entry in registry.items():
        if not isinstance(entry, Mapping):
            continue
        if cli_id == primary.cli_id:
            continue
        cli_lower = cli_id.strip().casefold()
        model = str(entry.get("model", ""))
        if cli_lower == dev_cli_lower and model == dev.model:
            # Same pair as dev — would still collide.
            continue
        candidates.append(cli_id)
    if not candidates:
        return None

    # Walk candidates in registry-insertion order so behavior is deterministic.
    for cli_id in candidates:
        alt_registry = {cli_id: dict(registry[cli_id])}
        try:
            alt = route(
                persona=persona,
                risk=risk,
                phase="review",
                cli_registry=alt_registry,
                valid_personas=valid_personas,
            )
        except RAMRError:
            continue
        # Verify the alternative actually breaks the collision.
        if alt.cli_id.strip().casefold() == dev_cli_lower and alt.model == dev.model:
            continue
        return alt
    return None


def select_reviewer_assignment(
    *,
    story_key: str,
    risk: str,
    dev_assignment: PhaseAssignment,
    persona: str = "reviewer",
    cli_registry: Mapping[str, Mapping[str, Any]] | None = None,
    valid_personas: Sequence[str] | None = None,
) -> DispatchResult:
    """Return the reviewer :class:`DispatchResult` for an upcoming review.

    Args:
        story_key: Story identifier (e.g. ``"STORY-123"``) — included in the
            returned record and surfaced in escalation messages.
        risk: Risk priority (``"P0"..."P3"``); forwarded to RAMR.
        dev_assignment: The :class:`PhaseAssignment` describing the
            ``dev-running`` engine. Used to detect ``(cli_id, model)``
            collisions before the review session is spawned.
        persona: BMAD persona for the review session. Defaults to
            ``"reviewer"``. Custom personas are validated by RAMR.
        cli_registry: Optional registry override (defaults to
            :data:`ramr.DEFAULT_CLI_REGISTRY`).
        valid_personas: Optional persona allow-list override.

    Raises:
        ReviewDispatchError: Inputs are malformed (missing or wrong-phased
            dev assignment, empty story key, invalid risk/persona).
        ReviewDispatchEscalation: RAMR cannot find a reviewer ``(cli_id,
            model)`` that differs from ``dev_assignment``. Callers must
            translate this into a PREFERENCE escalation — the review
            session must not be launched.
    """
    story_key_n = _validate_story_key(story_key)
    dev = _validate_dev_assignment(dev_assignment)
    registry = (
        cli_registry if cli_registry is not None else DEFAULT_CLI_REGISTRY
    )

    try:
        decision = route(
            persona=persona,
            risk=risk,
            phase="review",
            cli_registry=registry,
            valid_personas=valid_personas,
        )
    except RAMRError as exc:
        raise ReviewDispatchError(str(exc)) from exc

    # M55 enforce_independent_models requires DEV_VERIFY for the verify side.
    candidate = PhaseAssignment(
        phase=Phase.DEV_VERIFY,
        cli_id=decision.cli_id,
        model=decision.model,
    )

    try:
        enforce_independent_models(dev, candidate)
    except AntiBiasViolation:
        # Try to recover by routing through an alternative registry entry.
        alt_decision = _try_alternative_reviewer(
            dev=dev,
            risk=risk,
            persona=persona,
            registry=registry,
            valid_personas=valid_personas,
            primary=decision,
        )
        if alt_decision is None:
            raise ReviewDispatchEscalation(
                f"RAMR cannot route a reviewer that differs from the dev "
                f"(cli_id={dev.cli_id!r}, model={dev.model!r}) for story "
                f"{story_key_n!r} at risk={risk!r}: registry has no "
                f"alternative entry. Broaden the CLI registry or sign a "
                f"PREFERENCE waiver."
            ) from None
        candidate = PhaseAssignment(
            phase=Phase.DEV_VERIFY,
            cli_id=alt_decision.cli_id,
            model=alt_decision.model,
        )
        # Belt-and-braces: the alternative must pass the M55 check too.
        try:
            enforce_independent_models(dev, candidate)
        except AntiBiasViolation as exc:
            raise ReviewDispatchEscalation(
                f"RAMR alternative for story {story_key_n!r} still collides "
                f"with the dev assignment: {exc}"
            ) from exc
        decision = alt_decision

    return DispatchResult(
        story_key=story_key_n,
        assignment=candidate,
        routing_decision=decision,
    )


__all__ = [
    "DispatchResult",
    "ReviewDispatchError",
    "ReviewDispatchEscalation",
    "select_reviewer_assignment",
]
