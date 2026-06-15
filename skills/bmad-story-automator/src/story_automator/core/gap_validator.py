"""Layer 1 of the M06a trust-but-verify stack: deterministic gap validation.

This module exposes three frozen dataclasses (`Gap`, `GapStatus`,
`ValidationReport`) and two functions (`parse_gap_list`, `validate_gaps`).
`parse_gap_list` deserializes a `{"gaps": [...]}` JSON document into a
list of `Gap` values. `validate_gaps` checks each gap's cited file path,
line number, and symbol against the local source tree rooted at
`repo_root`, returning a per-gap confidence in the closed interval
`[0.0, 1.0]` plus an aggregate `ValidationReport`.

Layer 1 is intentionally decoupled from Layer 2 (`spec_compliance.py`)
and Layer 3 (`feature_tester.py`): no cross-layer imports, no shared
state, no subprocess calls, no network I/O. The verifier never reads
files outside `repo_root` — path-escape attempts (absolute paths,
`..` traversal, outward-pointing symlinks) are reported as
`path_exists=False` with a note.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

__all__ = [  # noqa: F822 — symbols are added incrementally in later M06a-M1 tasks
    "Gap",
    "GapStatus",
    "ValidationReport",
    "parse_gap_list",
    "validate_gaps",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class Gap:
    """A review-skill gap claim: file/line/symbol citation plus metadata.

    Preconditions: `severity` must be one of "blocker", "major", "minor"
        — enforced by `parse_gap_list`, not by this dataclass itself.
    Postconditions: instance is frozen; all five fields are present.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    file_path: str
    line: int
    symbol: str
    description: str
    severity: str


@dataclass(frozen=True, kw_only=True)
class GapStatus:
    """Result of validating a single `Gap` against the local source tree.

    Preconditions: `confidence` must lie in `[0.0, 1.0]`; `notes` must be
        a list of human-readable strings explaining failed checks.
    Postconditions: instance is frozen; `gap` is the original `Gap`.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    gap: Gap
    path_exists: bool
    line_in_range: bool
    symbol_present: bool
    confidence: float
    notes: list[str]


@dataclass(frozen=True, kw_only=True)
class ValidationReport:
    """Aggregate report from `validate_gaps`.

    Preconditions: `statuses` must be a list (possibly empty);
        `overall_confidence` in `[0.0, 1.0]`; `validated_at` is an
        ISO-8601 timestamp produced by `core.common.iso_now()`.
    Postconditions: instance is frozen.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    statuses: list[GapStatus]
    overall_confidence: float
    validated_at: str
