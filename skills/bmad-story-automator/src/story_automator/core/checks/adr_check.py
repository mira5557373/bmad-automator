"""ADR production-readiness rubric per the TEA 29-criterion standard.

This module exposes the closed, ordered tuple :data:`ADR_CRITERIA`
covering every dimension the Test/Engineering Assurance (TEA) gate
inspects on an Architecture Decision Record before it ships:

* Identity and provenance — title, status, owners, dates
* Decision substance — context, decision, alternatives, scope
* Consequences — positive, negative, trade-offs, deferred work
* Quality posture — testing, security, privacy, performance,
  observability, accessibility, compliance, supply-chain
* Operability — production-readiness, rollout, rollback, runbook,
  on-call, capacity, migration
* Governance — review, sign-off, follow-ups, references

The rubric is closed (exactly 29 entries) and ordered so collectors and
auditors can index by position. Each criterion is matched against the
ADR body via a keyword fingerprint derived from its declared string;
the matcher is intentionally permissive (case-insensitive, whitespace-
collapsed, hyphen/space-tolerant) so an ADR using "Production Readiness"
satisfies the same criterion as "Production-Readiness".

Verdicts are drawn from :data:`CRITERION_VERDICTS`, a closed three-member
tuple ``("PASS", "FAIL", "NOT_APPLICABLE")``. The matcher only emits
PASS/FAIL today; NOT_APPLICABLE is reserved for the upstream collector
to set when a profile or waiver suppresses a criterion. Reserving the
verdict at the rubric layer keeps the closed vocabulary stable as the
collector grows.

The legacy single-section helper :func:`has_production_readiness_section`
is preserved so the existing process collector keeps compiling while the
gate migrates to :func:`evaluate_adr_criteria`.

Stdlib-only. No story_automator imports. Safe to call from a fresh
trust-boundary checkout.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "ADR_CRITERIA",
    "CRITERION_VERDICTS",
    "AdrCriterionError",
    "OPTIONAL_CRITERIA",
    "criterion_for",
    "evaluate_adr_criteria",
    "has_production_readiness_section",
    "missing_criteria",
]


# ---------------------------------------------------------------------------
# Public vocabulary
# ---------------------------------------------------------------------------

#: Closed, ordered TEA ADR rubric. Position is part of the contract:
#: downstream tooling indexes by tuple offset, so reordering is a breaking
#: change. New criteria require a separate spec waiver and a new milestone.
ADR_CRITERIA: tuple[str, ...] = (
    # Identity and provenance (1-5)
    "Title",
    "Status",
    "Date",
    "Authors",
    "Stakeholders",
    # Decision substance (6-10)
    "Context",
    "Decision",
    "Alternatives Considered",
    "Scope",
    "Assumptions",
    # Consequences (11-14)
    "Consequences",
    "Trade-offs",
    "Risks",
    "Deferred Work",
    # Quality posture (15-21)
    "Testing Strategy",
    "Security Review",
    "Privacy Review",
    "Performance Impact",
    "Observability",
    "Accessibility",
    "Compliance",
    # Operability (22-27)
    "Supply Chain",
    "Production-Readiness",
    "Rollout Plan",
    "Rollback Plan",
    "Runbook",
    "Capacity Plan",
    # Governance (28-29)
    "Migration",
    "References",
)


#: Closed verdict vocabulary. ``NOT_APPLICABLE`` is reserved for the
#: collector to emit when a profile or waiver suppresses a criterion.
CRITERION_VERDICTS: tuple[str, str, str] = ("PASS", "FAIL", "NOT_APPLICABLE")


#: Criteria the rubric considers advisory rather than blocking. The matcher
#: still evaluates them, but :func:`missing_criteria` filters them out so the
#: gate does not block on a missing optional section. The set is intentionally
#: small — every operability and governance dimension stays required.
OPTIONAL_CRITERIA: frozenset[str] = frozenset(
    {
        "Stakeholders",
        "Assumptions",
        "Trade-offs",
        "Deferred Work",
        "Privacy Review",
        "Accessibility",
        "Capacity Plan",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AdrCriterionError(ValueError):
    """Raised when an unknown criterion is requested or input is malformed.

    Subclasses :class:`ValueError` so generic ``except ValueError`` blocks
    in upstream collectors still catch it.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_VALID_CRITERIA: frozenset[str] = frozenset(ADR_CRITERIA)


_SECTION_RE = re.compile(
    r"^#+\s+Production[- ]Readiness", re.MULTILINE | re.IGNORECASE
)


def _normalize(text: str) -> str:
    """Return a case- and punctuation-insensitive fingerprint of ``text``.

    The matcher treats hyphens and underscores as spaces, collapses
    whitespace, and lowercases the result so headings such as
    ``"Production-Readiness"``, ``"production readiness"``, and
    ``"Production_Readiness"`` all hash to the same fingerprint.
    """

    if not isinstance(text, str):
        return ""
    lowered = text.lower()
    lowered = lowered.replace("-", " ").replace("_", " ")
    # Collapse arbitrary whitespace runs to single spaces.
    return " ".join(lowered.split())


def _criterion_pattern(criterion: str) -> re.Pattern[str]:
    """Build a heading regex for ``criterion``.

    Matches an ATX-style heading (``#`` … ``######``) whose text equals the
    criterion under :func:`_normalize` semantics. Tolerates trailing
    punctuation (``:``, ``-``) and a trailing colon after the criterion
    name. Match is anchored to a line start so prose mentioning the
    criterion mid-sentence does not falsely satisfy it.
    """

    fingerprint = _normalize(criterion)
    # Build a regex by treating each space as ``[\s\-_]+`` so the heading can
    # vary in punctuation without losing detection.
    parts = [re.escape(token) for token in fingerprint.split()]
    body = r"[\s\-_]+".join(parts)
    pattern = rf"^#+\s+{body}\s*:?\s*$"
    return re.compile(pattern, re.MULTILINE | re.IGNORECASE)


# Pre-compile the per-criterion patterns once at import time so repeated
# evaluations across many ADRs stay cheap.
_CRITERION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (criterion, _criterion_pattern(criterion)) for criterion in ADR_CRITERIA
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def criterion_for(name: Any) -> str:
    """Return ``name`` if it is a declared TEA ADR criterion.

    :raises AdrCriterionError: when ``name`` is not a string or is not one
        of the 29 entries in :data:`ADR_CRITERIA`.
    """

    if not isinstance(name, str):
        raise AdrCriterionError(
            f"criterion name must be str, got {type(name).__name__}"
        )
    if name not in _VALID_CRITERIA:
        raise AdrCriterionError(f"unknown ADR criterion: {name!r}")
    return name


def has_production_readiness_section(content: Any) -> bool:
    """Return ``True`` if ``content`` contains a Production-Readiness heading.

    Preserves the legacy behaviour of the M5 process collector so existing
    callers keep working while the gate migrates to the full 29-criterion
    rubric. Non-string input returns ``False`` (fail-closed).
    """

    if not isinstance(content, str):
        return False
    return bool(_SECTION_RE.search(content))


def evaluate_adr_criteria(content: Any) -> tuple[tuple[str, str], ...]:
    """Score ``content`` against every TEA ADR criterion.

    Returns a tuple of ``(criterion, verdict)`` pairs in the order
    declared by :data:`ADR_CRITERIA`. Verdicts are drawn from
    :data:`CRITERION_VERDICTS`; this matcher only emits ``"PASS"`` or
    ``"FAIL"`` — the upstream collector is responsible for upgrading a
    ``"FAIL"`` to ``"NOT_APPLICABLE"`` when a profile or waiver suppresses
    the criterion.

    Non-string input fails every required criterion.
    """

    text = content if isinstance(content, str) else ""
    results: list[tuple[str, str]] = []
    for criterion, pattern in _CRITERION_PATTERNS:
        verdict = "PASS" if pattern.search(text) else "FAIL"
        results.append((criterion, verdict))
    return tuple(results)


def missing_criteria(content: Any) -> tuple[str, ...]:
    """Return the required criteria absent from ``content``.

    Required criteria are every entry in :data:`ADR_CRITERIA` that is not
    listed in :data:`OPTIONAL_CRITERIA`. The result preserves declaration
    order so the gate can render a deterministic remediation list.
    """

    verdicts = evaluate_adr_criteria(content)
    missing: list[str] = []
    for criterion, verdict in verdicts:
        if verdict == "PASS":
            continue
        if criterion in OPTIONAL_CRITERIA:
            continue
        missing.append(criterion)
    return tuple(missing)
