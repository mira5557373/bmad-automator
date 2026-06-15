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

import json
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


_ALLOWED_SEVERITIES: frozenset[str] = frozenset({"blocker", "major", "minor"})
_REQUIRED_GAP_KEYS: tuple[str, ...] = (
    "file_path",
    "line",
    "symbol",
    "description",
    "severity",
)


def parse_gap_list(payload: str) -> list[Gap]:
    """Parse a `{"gaps": [...]}` JSON document into a list of `Gap`.

    Preconditions: `payload` must be valid JSON whose top-level value is
        an object containing a `"gaps"` key holding a list of objects.
        Each object must contain `file_path` (str), `line` (int),
        `symbol` (str), `description` (str), and `severity` (one of
        "blocker", "major", "minor").
    Postconditions: returns a `list[Gap]` preserving input order.
    Raises: ValueError with a field-locating message when a required
        key is missing, when `line` is not an integer, or when
        `severity` is outside the allowed set. json.JSONDecodeError
        propagates for malformed JSON (it is itself a ValueError, so
        callers catching ValueError catch both).
    """
    data = json.loads(payload)
    if not isinstance(data, dict) or "gaps" not in data:
        raise ValueError("payload must be a JSON object with a top-level 'gaps' key")
    raw_gaps = data["gaps"]
    if not isinstance(raw_gaps, list):
        raise ValueError("'gaps' must be a JSON array")

    out: list[Gap] = []
    for index, raw in enumerate(raw_gaps):
        if not isinstance(raw, dict):
            raise ValueError(f"gaps[{index}] must be a JSON object")
        for key in _REQUIRED_GAP_KEYS:
            if key not in raw:
                raise ValueError(f"gaps[{index}] missing required key {key!r}")
        line_value = raw["line"]
        # `bool` is a subclass of `int` in Python; reject it explicitly so
        # `"line": true` does not silently parse as `line=1`.
        if isinstance(line_value, bool) or not isinstance(line_value, int):
            raise ValueError(
                f"gaps[{index}].line must be an integer, got {type(line_value).__name__}"
            )
        severity = raw["severity"]
        if severity not in _ALLOWED_SEVERITIES:
            raise ValueError(
                f"gaps[{index}].severity must be one of "
                f"{sorted(_ALLOWED_SEVERITIES)!r}, got {severity!r}"
            )
        out.append(
            Gap(
                file_path=str(raw["file_path"]),
                line=line_value,
                symbol=str(raw["symbol"]),
                description=str(raw["description"]),
                severity=severity,
            )
        )
    return out
