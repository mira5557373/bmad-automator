"""VerifyOutcome — typed ok/retry/escalate verdict from a verifier.

Ported (with attribution) from bmad-auto/src/automator/verify.py:39–62
(MIT-licensed). Adapted to our fork's typing conventions but the wire
semantics are byte-compatible.

Used by adoption-phase verifiers (Phase 1+) to return structured outcomes
that the gate orchestrator can route on:

  - ``ok=True`` → proceed
  - ``ok=False`` with ``severity==""`` → retryable (transient or feedback-fixable)
  - ``ok=False`` with ``severity!=""`` → escalate to human; not retryable

The ``fixable`` flag distinguishes a failure that carries enough evidence
for a feedback-driven repair session (e.g. concrete failing test output)
from one that just wants a retry from scratch.

Determinism contract: this dataclass carries no timestamps, no PIDs, no
run-IDs — only the boolean decision + a string reason — so it is safe to
include in a gate-file payload without breaking replay (per
docs/spec/frozen-gate-surface.md guardrail #6).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# The severity is intentionally a free-form string so future severities
# (e.g. "REGRESSION", "BUDGET") can be added without a type bump. The two
# values currently emitted by bmad-auto are CRITICAL and PREFERENCE.
Severity = Literal["", "CRITICAL", "PREFERENCE"]


@dataclass(frozen=True)
class VerifyOutcome:
    """Typed result from a verifier.

    Attributes:
        ok: True when verification passed; routing terminates here.
        reason: short token describing the failure (for logs/telemetry).
            Empty when ``ok``.
        severity: ``""`` for retryable failures; ``"CRITICAL"`` /
            ``"PREFERENCE"`` for escalate-to-human paths. When set,
            ``retryable`` is False.
        fixable: True iff the failure carries concrete evidence a
            feedback-driven repair session can act on (e.g. a failing
            test transcript). Only meaningful when ``not ok``.
    """

    ok: bool
    reason: str = ""
    severity: str = ""
    fixable: bool = False

    @classmethod
    def passed(cls) -> "VerifyOutcome":
        """The happy path."""
        return cls(ok=True)

    @classmethod
    def retry(cls, reason: str, fixable: bool = False) -> "VerifyOutcome":
        """A retryable failure. ``fixable=True`` signals that the caller can
        feed a transcript back to the agent for a targeted fix."""
        return cls(ok=False, reason=reason, fixable=fixable)

    @classmethod
    def escalate(cls, reason: str, severity: str = "CRITICAL") -> "VerifyOutcome":
        """Non-retryable failure. Operator/human review required."""
        return cls(ok=False, reason=reason, severity=severity)

    @property
    def retryable(self) -> bool:
        """A failed outcome with no severity is retryable."""
        return not self.ok and not self.severity

    def to_dict(self) -> dict[str, object]:
        """Stable wire form for embedding in gate-file payloads.

        Field order is deterministic (alpha). No timestamps. Safe to
        include in the audit chain.
        """
        return {
            "fixable": self.fixable,
            "ok": self.ok,
            "reason": self.reason,
            "severity": self.severity,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "VerifyOutcome":
        """Inverse of :meth:`to_dict`. Tolerant of missing fields (older
        gate files predating this schema)."""
        return cls(
            ok=bool(payload.get("ok", False)),
            reason=str(payload.get("reason", "")),
            severity=str(payload.get("severity", "")),
            fixable=bool(payload.get("fixable", False)),
        )
