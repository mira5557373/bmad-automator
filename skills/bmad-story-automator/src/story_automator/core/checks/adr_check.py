"""Check ADR files for Production-Readiness section.

Standalone script invoked by the adr-process collector.
Scans docs/architecture/decisions/*.md for a heading matching
"Production-Readiness" or "Production Readiness" (case-insensitive).
Exit 0 = all ADRs have it (or no ADR dir/files). Exit 1 = missing.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import re
import sys

_SECTION_RE = re.compile(
    r"^#+\s+Production[- ]Readiness", re.MULTILINE | re.IGNORECASE
)
_ADR_RELDIR = os.path.join("docs", "architecture", "decisions")


def _has_prod_readiness_section(content: str) -> bool:
    return bool(_SECTION_RE.search(content))


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: adr_check.py <checkout>")
        return 2
    checkout = args[0]
    adr_dir = os.path.join(checkout, _ADR_RELDIR)
    if not os.path.isdir(adr_dir):
        print(f"no ADR directory: {_ADR_RELDIR}")
        return 0
    adr_files = sorted(f for f in os.listdir(adr_dir) if f.endswith(".md"))
    if not adr_files:
        print("no ADR files found")
        return 0
    missing: list[str] = []
    for adr_file in adr_files:
        path = os.path.join(adr_dir, adr_file)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if not _has_prod_readiness_section(content):
            missing.append(adr_file)
            print(f"MISSING Production-Readiness: {adr_file}")
    if missing:
        print(f"{len(missing)} ADR(s) missing Production-Readiness section")
        return 1
    print(f"all {len(adr_files)} ADR(s) have Production-Readiness section")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# ===========================================================================
# M51: 29-criterion TEA ADR rubric
# ---------------------------------------------------------------------------
# Closed, ordered criteria + matcher + lookup. The legacy
# ``_has_prod_readiness_section`` helper above is preserved so the existing
# process collector keeps compiling while callers migrate to
# ``evaluate_adr_criteria``.
# ===========================================================================

from typing import Any  # noqa: E402

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

assert len(ADR_CRITERIA) == 29
assert len(set(ADR_CRITERIA)) == 29

#: Closed verdict vocabulary. ``NOT_APPLICABLE`` is reserved for the
#: collector to emit when a profile or waiver suppresses a criterion.
CRITERION_VERDICTS: tuple[str, str, str] = ("PASS", "FAIL", "NOT_APPLICABLE")

#: Criteria the rubric considers advisory rather than blocking. The matcher
#: still evaluates them, but :func:`missing_criteria` filters them out so the
#: gate does not block on a missing optional section.
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


class AdrCriterionError(ValueError):
    """Raised when an unknown criterion is requested or input is malformed.

    Subclasses :class:`ValueError` so generic ``except ValueError`` blocks
    in upstream collectors still catch it.
    """


_VALID_CRITERIA: frozenset[str] = frozenset(ADR_CRITERIA)


def _normalize_criterion_text(text: str) -> str:
    """Return a case- and punctuation-insensitive fingerprint of ``text``.

    Treats hyphens and underscores as spaces, collapses whitespace, and
    lowercases so headings such as ``"Production-Readiness"``,
    ``"production readiness"``, and ``"Production_Readiness"`` collapse to
    the same fingerprint.
    """

    if not isinstance(text, str):
        return ""
    lowered = text.lower().replace("-", " ").replace("_", " ")
    return " ".join(lowered.split())


def _criterion_pattern(criterion: str) -> re.Pattern[str]:
    """Build a heading regex for ``criterion``.

    Matches an ATX-style heading (``#`` … ``######``) whose text equals the
    criterion under :func:`_normalize_criterion_text` semantics. Match is
    anchored to a line start so prose mentioning the criterion mid-sentence
    does not falsely satisfy it.
    """

    fingerprint = _normalize_criterion_text(criterion)
    parts = [re.escape(token) for token in fingerprint.split()]
    body = r"[\s\-_]+".join(parts)
    pattern = rf"^#+\s+{body}\s*:?\s*$"
    return re.compile(pattern, re.MULTILINE | re.IGNORECASE)


# Pre-compile the per-criterion patterns once at import time so repeated
# evaluations across many ADRs stay cheap.
_CRITERION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (criterion, _criterion_pattern(criterion)) for criterion in ADR_CRITERIA
)


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
