"""Budget ceiling data types and config reader (M03 sub-milestone M1).

This module ships the data substrate for M03 budget enforcement: the
``CeilingDecision`` enum, the ``BudgetCeiling`` dataclass, and the
tolerant ``parse_ceilings_config`` reader. The evaluator, bypass
helper, and BMAD step wiring are scheduled for M03-M2 / M03-M3.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

__all__ = ["BudgetCeiling", "CeilingDecision"]


class CeilingDecision(enum.Enum):
    """Tri-state verdict returned by ceiling evaluation.

    Declaration order is load-bearing: callers may compare verdicts by
    member index when merging multi-ceiling results (REQ-10), so the
    sequence ALLOW < WARN < BLOCK must never be reordered.
    """

    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass(kw_only=True)
class BudgetCeiling:
    """Single configured spending ceiling read from ``workflow.json``.

    ``window`` is one of ``"per_run"``, ``"24h"``, ``"7d"``, ``"30d"``
    (REQ-03). ``warn_at`` is a fraction in ``(0.0, 1.0]`` multiplied
    against ``limit_usd`` to produce the WARN threshold. ``gate_names``
    enumerates which preflight gate names this ceiling applies to:
    elements are drawn from ``{"init", "story_start", "retry_start"}``
    per REQ-07, but this dataclass does not enforce that set — the
    evaluator (M03-M2) is the only consumer that filters on it.
    """

    name: str
    window: str
    limit_usd: float
    warn_at: float
    gate_names: tuple[str, ...]


_PARSE_WARNINGS: list[dict[str, str]] = []
"""Structured parse warnings, cleared at the start of each
``parse_ceilings_config`` call (REQ-05). Each entry is a dict with
``index`` (str repr of the position in the array), ``reason``
(short slug), and ``detail`` (free-form message). Intentionally
module-level, not part of the function return, so callers that care
about warnings can opt in without complicating the happy-path
signature."""
