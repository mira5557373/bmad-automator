"""Budget ceilings — primitives for per-key spend limits and overspend
classification.

This module is intentionally small and self-contained: it provides only
the dataclasses (``BudgetCeiling``, ``BudgetLedger``) and the policy
function (``classify_overspend``) that downstream phase-shaped budget
machinery (see ``story_automator.core.innovation.phase_budget``) builds on.

Design choices
--------------
- ``BudgetLedger`` is an in-memory accumulator keyed by an arbitrary
  string (we use ``"<phase>::<persona>"`` keys from the phase budget
  layer). Persistence is the caller's job; this keeps the primitive
  reusable for tests and for one-shot orchestration runs.
- Overspend classification is centralized so that policy changes (e.g.
  "P0 in dev-running should *escalate* not *retry-cheap*") have exactly
  one place to land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

# Phase identifiers — duplicated as string constants in phase_budget.py
# for the caller's convenience; defined here too so this module can
# classify overspend without importing the higher layer (avoids cycles).
_PHASE_DEV_RUNNING = "dev-running"
_PHASE_REVIEW_VERIFY = "review-verify"


class OverspendAction(str, Enum):
    """Action returned by ``classify_overspend`` / phase budget enforcement.

    - ``ALLOW``: spend is within ceiling, no policy action required.
    - ``RETRY_CHEAP``: dev-running P0 overspend — demote to a cheaper
      retry (smaller model, fewer tokens) instead of escalating.
    - ``PAUSE``: review/verify overspend — pause the story for human
      re-scope. Verification cannot be safely "retried cheap".
    - ``ESCALATE``: catch-all for non-P0 dev-running overspend that
      still exceeds the per-persona ceiling.
    """

    ALLOW = "allow"
    RETRY_CHEAP = "retry_cheap"
    PAUSE = "pause"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class BudgetCeiling:
    """A single hard ceiling expressed as ``limit`` units for ``priority``.

    The unit is opaque (cents, tokens, seconds) and chosen by the caller;
    we only require that it be non-negative integer-shaped so spend math
    stays exact.
    """

    limit: int
    priority: str

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or self.limit <= 0:
            raise ValueError(f"BudgetCeiling.limit must be a positive int, got {self.limit!r}")
        if not isinstance(self.priority, str) or not self.priority:
            raise ValueError(f"BudgetCeiling.priority must be a non-empty string, got {self.priority!r}")


@dataclass
class BudgetLedger:
    """Mutable, in-memory tally of spend by string key.

    The key shape is up to the caller — phase_budget uses
    ``"<phase>::<persona>"``. ``record`` is additive; there is no
    decrement on purpose (refunds would mask leaks).
    """

    spend: dict[str, int] = field(default_factory=dict)

    def record(self, key: str, amount: int) -> int:
        if amount < 0:
            raise ValueError(f"BudgetLedger.record amount must be >= 0, got {amount}")
        self.spend[key] = self.spend.get(key, 0) + int(amount)
        return self.spend[key]

    def total(self, key: str) -> int:
        return int(self.spend.get(key, 0))

    def snapshot(self) -> Mapping[str, int]:
        return dict(self.spend)


def classify_overspend(*, priority: str, phase: str) -> OverspendAction:
    """Return the policy action for an overspend in ``phase`` at ``priority``.

    Policy (M59):
    - review-verify   → always PAUSE  (verification overspend is a smell)
    - dev-running P0  → RETRY_CHEAP   (retry with a smaller model)
    - dev-running !P0 → ESCALATE      (non-P0 overspend bubbles up)

    Callers may pass an unknown phase string; we default to ESCALATE so
    that integration mistakes are loud rather than silent.
    """

    if phase == _PHASE_REVIEW_VERIFY:
        return OverspendAction.PAUSE
    if phase == _PHASE_DEV_RUNNING:
        if priority == "P0":
            return OverspendAction.RETRY_CHEAP
        return OverspendAction.ESCALATE
    return OverspendAction.ESCALATE


__all__ = [
    "BudgetCeiling",
    "BudgetLedger",
    "OverspendAction",
    "classify_overspend",
]
