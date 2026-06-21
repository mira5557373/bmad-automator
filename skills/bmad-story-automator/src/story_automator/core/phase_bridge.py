"""Phase bridge — RAMR anti-bias roundtrip enforcement (M55).

Mirrors the small slice of bmad-auto's lifecycle ``Phase`` enum we need to
police the ``dev-running -> dev-verify`` hand-off, plus the helpers that
enforce the RAMR (Risk-Aware Model Routing) independent-model constraint:

    ``dev-verify`` MUST use a different ``(cli_id, model)`` pair than
    ``dev-running`` — at least one of the two dimensions must differ.

If both are identical the gate auto-FAILs: a story cannot be "verified" by
the same engine that wrote the code, because that collapses the adversarial
review into a self-check and silently disarms the gate.

Public surface:

- :class:`Phase` — minimal subset of bmad-auto phases used for this check.
- :class:`PhaseAssignment` — ``(phase, cli_id, model)`` triple naming the
  engine that ran (or will run) a phase.
- :class:`AntiBiasViolation` — raised when the dev-running / dev-verify
  pair collapses to the same ``(cli_id, model)``.
- :func:`enforce_independent_models` — strict gate, raises on violation.
- :func:`check_anti_bias_roundtrip` — non-raising form returning a dict
  evidence record suitable for embedding in a gate evidence file.
- :func:`verdict_for_assignments` — ``"pass" | "fail"`` shorthand for the
  adjudicator.

This module is stdlib-only and side-effect-free; safe to import from any
layer (commands, collectors, orchestrator).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Phase(StrEnum):
    """Lifecycle phase — minimal subset used by the M55 roundtrip check.

    Only the two phases that take part in the RAMR independence constraint
    are modelled here. Full bmad-auto phase coverage lives in a separate
    bridge module (M25); this file is intentionally narrow so the M55 gate
    can be imported without pulling in unrelated lifecycle state.
    """

    DEV_RUNNING = "dev-running"
    DEV_VERIFY = "dev-verify"


@dataclass(frozen=True)
class PhaseAssignment:
    """Engine that executed (or will execute) a given phase.

    Attributes:
        phase: Which lifecycle phase this assignment describes.
        cli_id: Identifier of the CLI / agent runtime (e.g. ``"claude"``,
            ``"codex"``). Compared case-insensitively after stripping
            whitespace.
        model: Model identifier (e.g. ``"opus-4"``, ``"gpt-5"``). Compared
            case-sensitively because model IDs are vendor-canonical
            strings; an empty model is rejected (ambiguous).
    """

    phase: Phase
    cli_id: str
    model: str


class AntiBiasViolation(RuntimeError):
    """Raised when dev-verify reuses the dev-running ``(cli_id, model)``.

    The gate cannot accept this configuration: verification by the same
    engine that produced the work eliminates the adversarial property the
    review phase exists to provide.
    """


def _normalize_cli(cli_id: str) -> str:
    """Case-fold + strip a CLI ID so casing typos do not fake independence."""

    return cli_id.strip().casefold()


def _require_dev_pair(running: PhaseAssignment, verify: PhaseAssignment) -> None:
    """Validate the assignment phases form the dev-running -> dev-verify pair."""

    if running.phase is not Phase.DEV_RUNNING:
        raise ValueError(
            f"running assignment must be {Phase.DEV_RUNNING!r}, "
            f"got {running.phase!r}"
        )
    if verify.phase is not Phase.DEV_VERIFY:
        raise ValueError(
            f"verify assignment must be {Phase.DEV_VERIFY!r}, "
            f"got {verify.phase!r}"
        )


def _require_models_populated(
    running: PhaseAssignment, verify: PhaseAssignment
) -> None:
    """Refuse to certify independence when either model field is empty."""

    if not running.model.strip():
        raise ValueError("running assignment has empty model — cannot certify")
    if not verify.model.strip():
        raise ValueError("verify assignment has empty model — cannot certify")


def _pair_is_identical(
    running: PhaseAssignment, verify: PhaseAssignment
) -> bool:
    """Return True when running and verify share both cli_id and model.

    CLI IDs are normalized (case-folded, stripped) so accidental casing
    differences do not fake independence. Models are compared as-is
    because model IDs are vendor-canonical strings.
    """

    same_cli = _normalize_cli(running.cli_id) == _normalize_cli(verify.cli_id)
    same_model = running.model == verify.model
    return same_cli and same_model


def enforce_independent_models(
    running: PhaseAssignment, verify: PhaseAssignment
) -> None:
    """Strict gate — raises :class:`AntiBiasViolation` on RAMR collapse.

    Args:
        running: Engine that ran (or will run) the ``dev-running`` phase.
        verify: Engine that ran (or will run) the ``dev-verify`` phase.

    Raises:
        ValueError: If the assignment phases do not form the expected
            ``dev-running -> dev-verify`` pair, or if either model field
            is empty.
        AntiBiasViolation: If both ``cli_id`` (case-folded) and ``model``
            match between the two assignments.
    """

    _require_dev_pair(running, verify)
    _require_models_populated(running, verify)
    if _pair_is_identical(running, verify):
        raise AntiBiasViolation(
            f"RAMR violation: dev-verify uses the same "
            f"(cli_id={verify.cli_id!r}, model={verify.model!r}) as "
            f"dev-running — at least one dimension must differ"
        )


def check_anti_bias_roundtrip(
    running: PhaseAssignment, verify: PhaseAssignment
) -> dict[str, Any]:
    """Non-raising form of :func:`enforce_independent_models`.

    Returns an evidence-shaped dict suitable for embedding in a gate
    evidence record. Phase mis-pairing and empty models still raise
    :class:`ValueError` — those are programmer errors, not policy
    violations.
    """

    _require_dev_pair(running, verify)
    _require_models_populated(running, verify)
    running_pair = {"cli_id": running.cli_id, "model": running.model}
    verify_pair = {"cli_id": verify.cli_id, "model": verify.model}
    if _pair_is_identical(running, verify):
        return {
            "ok": False,
            "violation": "ramr_same_cli_and_model",
            "running": running_pair,
            "verify": verify_pair,
        }
    return {
        "ok": True,
        "running": running_pair,
        "verify": verify_pair,
    }


def verdict_for_assignments(
    running: PhaseAssignment, verify: PhaseAssignment
) -> str:
    """Return ``"pass"`` or ``"fail"`` for the adjudicator.

    Convenience wrapper around :func:`check_anti_bias_roundtrip`. Raises
    on phase mis-pairing or empty models (programmer error).
    """

    return "pass" if check_anti_bias_roundtrip(running, verify)["ok"] else "fail"


__all__ = [
    "AntiBiasViolation",
    "Phase",
    "PhaseAssignment",
    "check_anti_bias_roundtrip",
    "enforce_independent_models",
    "verdict_for_assignments",
]
