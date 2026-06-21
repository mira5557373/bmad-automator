from __future__ import annotations

"""Adversarial review assignment + acceptance gate (M57).

Enforces two invariants for the production-ready factory:

1. **Distinct reviewer.** For P0/P1 stories, the adversarial review MUST be
   executed by a `(cli_id, model)` pair different from the one that produced
   the implementation. Both axes must differ — a same-CLI/different-model
   reviewer is not adversarial enough (shared system prompts, shared
   tool-use idioms, shared training cutoff biases). A same-model/different-CLI
   reviewer is rejected for the same reason.

2. **Substantive output.** An accepted submission must surface at least one
   *substantive* finding tied to an evidence record. "Substantive" means:
   - severity is `high` or `critical`, AND
   - the finding's `evidence` list is non-empty (so we can audit-trace the
     claim back to a real artifact — file, log, gate record, etc.), AND
   - the message is non-blank.

   The rule prevents "LGTM" rubber-stamping by adversarial reviewers and
   forces them to commit to an auditable claim. P2/P3 stories don't require a
   substantive finding (a clean review is a valid outcome at lower priority).

This module is intentionally pure: no I/O, no telemetry, no subprocess. It
sits next to the policy layer so callers (review_verify, gate_orchestrator,
review_taxonomy) can wire it without pulling in heavy dependencies.

Stdlib + typing only — honors the project's hard guardrail on imports.
"""

from dataclasses import dataclass, field
from typing import Iterable, Sequence


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AdversarialReviewError(ValueError):
    """Caller supplied malformed input (bad priority, missing dev agent ids)."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Severities considered weighty enough to count as a substantive review claim.
# Lower-case to match the canonical severity vocabulary used elsewhere in the
# review_taxonomy / gate_schema modules. Anything not in this set (low, info,
# nit, advisory, debug, unknown, ...) is treated as non-substantive.
_SUBSTANTIVE_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})

# Priorities that REQUIRE an adversarial reviewer at all. P2/P3 stories may
# still receive one if a candidate is available, but the orchestrator does not
# block on it. The string form is canonical upper-case ASCII to match the rest
# of the story / readiness vocabulary.
_VALID_PRIORITIES: frozenset[str] = frozenset({"P0", "P1", "P2", "P3"})
_MANDATORY_PRIORITIES: frozenset[str] = frozenset({"P0", "P1"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceLink:
    """A pointer from a review finding to a concrete evidence record.

    `record_id` should match the evidence id used by `evidence_io.py` / the
    gate audit log so downstream tooling can resolve it deterministically.
    """

    record_id: str
    source: str
    uri: str = ""


@dataclass(frozen=True)
class ReviewFinding:
    """One adversarial-review finding.

    `evidence` MUST be non-empty for the finding to count as substantive.
    """

    finding_id: str
    rule_id: str
    severity: str
    message: str
    evidence: Sequence[EvidenceLink] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReviewAssignment:
    """Result of the assignment step — who reviews, and who they review."""

    reviewer_cli_id: str
    reviewer_model: str
    dev_cli_id: str
    dev_model: str
    priority: str


@dataclass(frozen=True)
class AssignmentResult:
    """Return wrapper for `assign_reviewer`.

    `required` says whether the priority makes adversarial review mandatory.
    `assignment` is `None` when no distinct candidate is available; `reasons`
    carries machine-readable codes the orchestrator can route on.
    """

    required: bool
    assignment: ReviewAssignment | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubmissionResult:
    """Return wrapper for `accept_review_submission`."""

    accepted: bool
    substantive_count: int
    reasons: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_agent(agent: dict[str, str], *, label: str) -> tuple[str, str]:
    """Pull (cli_id, model) out of an agent dict; raise on missing pieces."""

    if not isinstance(agent, dict):
        raise AdversarialReviewError(f"{label}_agent must be a mapping")
    cli_id = (agent.get("cli_id") or "").strip()
    model = (agent.get("model") or "").strip()
    if not cli_id:
        raise AdversarialReviewError(f"{label}_agent missing cli_id")
    if not model:
        raise AdversarialReviewError(f"{label}_agent missing model")
    return cli_id, model


def _validate_priority(priority: str) -> str:
    if priority not in _VALID_PRIORITIES:
        raise AdversarialReviewError(
            f"invalid priority {priority!r}; expected one of {sorted(_VALID_PRIORITIES)}"
        )
    return priority


def _is_distinct(dev_cli: str, dev_model: str, cand: dict[str, str]) -> bool:
    """A candidate is distinct iff BOTH cli_id and model differ from dev."""

    if not isinstance(cand, dict):
        return False
    cand_cli = (cand.get("cli_id") or "").strip()
    cand_model = (cand.get("model") or "").strip()
    if not cand_cli or not cand_model:
        return False
    return cand_cli != dev_cli and cand_model != dev_model


# ---------------------------------------------------------------------------
# Public surface — assignment
# ---------------------------------------------------------------------------


def assign_reviewer(
    *,
    dev_agent: dict[str, str],
    candidates: Sequence[dict[str, str]],
    priority: str,
) -> AssignmentResult:
    """Pick the first candidate distinct from `dev_agent`.

    Distinctness requires BOTH (cli_id, model) to differ — a same-CLI
    reviewer is not adversarial regardless of model, and a same-model
    reviewer is not adversarial regardless of CLI.

    Behavior by priority:
    - P0/P1 → adversarial review is mandatory; `required=True`. If no
      distinct candidate exists, returns `assignment=None` and the caller
      MUST treat that as a blocker.
    - P2/P3 → `required=False`. We still try to assign one (best-effort)
      but the absence of a distinct candidate is not a blocker.
    """

    dev_cli, dev_model = _validate_agent(dev_agent, label="dev")
    pri = _validate_priority(priority)
    required = pri in _MANDATORY_PRIORITIES

    reasons: list[str] = []

    if not candidates:
        reasons.append("empty_candidate_pool")
        # P2/P3 doesn't require an assignment, so we still report required=False.
        return AssignmentResult(required=required, assignment=None, reasons=tuple(reasons))

    # P2/P3 stories explicitly opt out of the auto-assign — the orchestrator
    # treats this as "no adversarial review required". Returning None for the
    # assignment makes the caller's branch dead-simple: if assignment is None
    # AND required is True, block; otherwise proceed.
    if not required:
        return AssignmentResult(required=False, assignment=None, reasons=())

    for cand in candidates:
        if _is_distinct(dev_cli, dev_model, cand):
            cand_cli = cand["cli_id"].strip()
            cand_model = cand["model"].strip()
            return AssignmentResult(
                required=True,
                assignment=ReviewAssignment(
                    reviewer_cli_id=cand_cli,
                    reviewer_model=cand_model,
                    dev_cli_id=dev_cli,
                    dev_model=dev_model,
                    priority=pri,
                ),
                reasons=(),
            )

    reasons.append("no_distinct_reviewer")
    return AssignmentResult(required=True, assignment=None, reasons=tuple(reasons))


# ---------------------------------------------------------------------------
# Public surface — finding evaluation
# ---------------------------------------------------------------------------


def is_substantive(finding: ReviewFinding) -> bool:
    """A finding counts as substantive iff severity is high/critical AND it
    carries at least one evidence record AND has a non-blank message.
    """

    if not isinstance(finding, ReviewFinding):
        return False
    severity = (finding.severity or "").strip().lower()
    if severity not in _SUBSTANTIVE_SEVERITIES:
        return False
    message = (finding.message or "").strip()
    if not message:
        return False
    if not finding.evidence:
        return False
    # Defensive: an evidence record without a record_id can't be audited.
    for ev in finding.evidence:
        if isinstance(ev, EvidenceLink) and ev.record_id.strip():
            return True
    return False


def summarize_findings(findings: Iterable[ReviewFinding]) -> dict[str, int]:
    """Roll up findings into a severity histogram plus a `substantive` counter.

    Returned keys are stable regardless of input distribution so downstream
    code (telemetry, audit) can safely index in.
    """

    counts: dict[str, int] = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
        "other": 0,
        "substantive": 0,
        "total": 0,
    }
    known_buckets = {"critical", "high", "medium", "low", "info"}
    for f in findings:
        counts["total"] += 1
        sev = (f.severity or "").strip().lower()
        if sev in known_buckets:
            counts[sev] += 1
        else:
            counts["other"] += 1
        if is_substantive(f):
            counts["substantive"] += 1
    return counts


# ---------------------------------------------------------------------------
# Public surface — acceptance
# ---------------------------------------------------------------------------


def accept_review_submission(
    *,
    assignment: ReviewAssignment,
    findings: Sequence[ReviewFinding],
) -> SubmissionResult:
    """Validate a completed adversarial review.

    Acceptance rules:
    - reviewer's (cli_id, model) MUST differ from dev's on both axes
      (defense-in-depth: re-checked here in case the assignment got mutated
      between selection and submission);
    - for P0/P1, the submission MUST contain at least one substantive finding;
    - for P2/P3, an empty/non-substantive submission is acceptable.

    The function never raises on bad findings — callers want a structured
    `SubmissionResult` so they can route the verdict into the gate.
    """

    reasons: list[str] = []
    substantive = 0

    if not isinstance(assignment, ReviewAssignment):
        return SubmissionResult(
            accepted=False,
            substantive_count=0,
            reasons=("invalid_assignment",),
        )

    # Re-validate distinctness; the assignment was already vetted but the
    # gate-of-record check belongs here too.
    same_cli = assignment.reviewer_cli_id.strip() == assignment.dev_cli_id.strip()
    same_model = assignment.reviewer_model.strip() == assignment.dev_model.strip()
    if same_cli or same_model:
        reasons.append("reviewer_not_distinct")

    priority = assignment.priority
    mandatory = priority in _MANDATORY_PRIORITIES

    if not findings:
        if mandatory:
            reasons.append("no_findings")
    else:
        for f in findings:
            if is_substantive(f):
                substantive += 1
        if mandatory and substantive == 0:
            reasons.append("no_substantive_finding")

    accepted = not reasons
    return SubmissionResult(
        accepted=accepted,
        substantive_count=substantive,
        reasons=tuple(reasons),
    )


__all__ = [
    "AdversarialReviewError",
    "AssignmentResult",
    "EvidenceLink",
    "ReviewAssignment",
    "ReviewFinding",
    "SubmissionResult",
    "accept_review_submission",
    "assign_reviewer",
    "is_substantive",
    "summarize_findings",
]
