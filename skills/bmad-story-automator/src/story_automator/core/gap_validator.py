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
from pathlib import Path

from .common import iso_now

__all__ = [
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


_BASE_CONFIDENCE: float = 0.8
_PASS_BONUS: float = 0.05
_CONFIDENCE_CEILING: float = 1.0


def _resolve_inside_root(
    file_path: str,
    root_resolved: Path,
) -> tuple[Path | None, str | None]:
    """Return `(resolved_path, None)` if `file_path` lives inside the root.

    Returns `(None, note)` if the candidate escapes the root — including
    absolute paths outside the root, `..` traversal escaping the root,
    and symlinks whose `resolve()` lands outside the root. `note` is a
    human-readable reason mentioning the rejected path.
    """
    candidate = Path(file_path)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (root_resolved / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, f"path does not exist or escapes repo_root: {file_path}"
    if not resolved.is_file():
        return None, f"path does not exist or escapes repo_root: {file_path}"
    return resolved, None


def _check_line_in_range(
    resolved_path: Path | None,
    line: int,
) -> tuple[bool, str | None]:
    """Return `(True, None)` if `1 <= line <= file_line_count`.

    Returns `(False, note)` otherwise. If `resolved_path` is None (path
    rejection already noted by the caller), returns `(False, None)` so
    the caller doesn't double-note the same root cause.
    """
    if resolved_path is None:
        return False, None
    try:
        text = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"could not read {resolved_path.name} for line check: {exc}"
    except UnicodeDecodeError as exc:
        return False, f"could not decode {resolved_path.name} as UTF-8: {exc}"
    if not text:
        line_count = 0
    else:
        line_count = len(text.splitlines())
    if 1 <= line <= line_count:
        return True, None
    return False, f"line {line} outside file range 1..{line_count}"


def _empty_overall_confidence() -> float:
    """Overall confidence when no gaps were submitted.

    Returning 1.0 expresses "no gaps to validate = trivially valid".
    Centralised here so the value is easy to change if the operator
    later prefers 0.0 ("no evidence either way").
    """
    return 1.0


def validate_gaps(gaps: list[Gap], *, repo_root: Path) -> ValidationReport:
    """Validate each gap's file/line/symbol citation against `repo_root`.

    Preconditions: `repo_root` is an existing directory; each gap's
        `file_path` is interpreted relative to `repo_root`. Absolute
        paths, `..` traversal escaping the root, and outward-pointing
        symlinks are rejected with `path_exists=False`.
    Postconditions: returns a `ValidationReport` whose `statuses` list
        is one-for-one with the input `gaps`, in the same order. Per-gap
        confidence lies in `[0.8, 0.95]` (cap 1.0); failed checks
        contribute one note each. Aggregate `overall_confidence` is the
        arithmetic mean of per-gap confidence rounded to 6 dp, or 1.0
        when `gaps` is empty.
    Raises: nothing under normal operation — IO errors during the
        line-range or symbol checks are converted into `False` results
        with an explanatory note, so a torn source tree degrades
        gracefully rather than aborting the report.
    """
    statuses: list[GapStatus] = []
    root_resolved = Path(repo_root).resolve()
    for gap in gaps:
        notes: list[str] = []
        resolved, escape_note = _resolve_inside_root(gap.file_path, root_resolved)
        path_exists = resolved is not None
        if escape_note is not None:
            notes.append(escape_note)

        line_in_range, line_note = _check_line_in_range(resolved, gap.line)
        if line_note is not None:
            notes.append(line_note)
        symbol_present = False  # Placeholder — Task 10 implements symbol check.

        if not symbol_present:
            notes.append(f"symbol {gap.symbol!r} not found in {gap.file_path}")

        confidence = _BASE_CONFIDENCE + _PASS_BONUS * sum(
            [path_exists, line_in_range, symbol_present]
        )
        confidence = min(confidence, _CONFIDENCE_CEILING)
        statuses.append(
            GapStatus(
                gap=gap,
                path_exists=path_exists,
                line_in_range=line_in_range,
                symbol_present=symbol_present,
                confidence=confidence,
                notes=notes,
            )
        )
    if statuses:
        overall = round(
            sum(s.confidence for s in statuses) / len(statuses),
            6,
        )
    else:
        overall = _empty_overall_confidence()
    return ValidationReport(
        statuses=statuses,
        overall_confidence=overall,
        validated_at=iso_now(),
    )
