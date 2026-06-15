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

__all__ = [  # noqa: F822 — symbols are added incrementally in later M06a-M1 tasks
    "Gap",
    "GapStatus",
    "ValidationReport",
    "parse_gap_list",
    "validate_gaps",
]

logger = logging.getLogger(__name__)
