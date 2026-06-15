"""Budget ceiling data types and config reader (M03 sub-milestone M1).

This module ships the data substrate for M03 budget enforcement: the
``CeilingDecision`` enum, the ``BudgetCeiling`` dataclass, and the
tolerant ``parse_ceilings_config`` reader. The evaluator, bypass
helper, and BMAD step wiring are scheduled for M03-M2 / M03-M3.
"""

from __future__ import annotations

import enum

__all__ = ["CeilingDecision"]


class CeilingDecision(enum.Enum):
    """Tri-state verdict returned by ceiling evaluation.

    Declaration order is load-bearing: callers may compare verdicts by
    member index when merging multi-ceiling results (REQ-10), so the
    sequence ALLOW < WARN < BLOCK must never be reordered.
    """

    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"
