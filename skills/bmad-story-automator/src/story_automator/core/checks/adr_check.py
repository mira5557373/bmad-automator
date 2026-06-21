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
# M51 (partial): 29-criterion ADR rubric — additive constants only
# Full M51 implementation deferred; this exposes the closed criterion set
# so downstream collectors and adjudicator can begin honoring it.
# ===========================================================================

ADR_CRITERIA: tuple[str, ...] = (
    "title-present", "status-present", "status-canonical",
    "context-present", "context-substantive", "decision-present",
    "decision-explicit", "consequences-present", "consequences-substantive",
    "alternatives-considered", "alternatives-rejected-with-reason",
    "tradeoffs-named", "deciders-named", "date-present", "date-iso8601",
    "tags-present", "supersedes-or-superseded-by", "related-adrs-linked",
    "evidence-cited", "metrics-defined", "review-triggers", "rollback-plan",
    "telemetry-required", "approval-recorded", "risk-acknowledged",
    "non-goals-named", "scope-bounded", "owner-named", "renewal-cadence",
)

assert len(ADR_CRITERIA) == 29

OPTIONAL_CRITERIA: frozenset[str] = frozenset({
    "supersedes-or-superseded-by", "related-adrs-linked", "renewal-cadence",
})

CRITERION_VERDICTS: tuple[str, str, str] = ("PASS", "FAIL", "NOT_APPLICABLE")


class AdrCriterionError(ValueError):
    pass
