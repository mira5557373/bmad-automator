from __future__ import annotations

import re

VALID_REVIEW_ACTIONS: frozenset[str] = frozenset(
    {"decision_needed", "patch", "defer", "dismiss"}
)


class ReviewActionError(ValueError):
    """Raised when a review action string is not a valid taxonomy member."""


def canonicalize_action(raw: object) -> str:
    """Normalize a review-action token to its canonical lowercase form.

    Case-insensitive; surrounding whitespace is stripped. Raises
    ReviewActionError if the value is not a string or does not match a
    member of VALID_REVIEW_ACTIONS.
    """
    if not isinstance(raw, str):
        raise ReviewActionError(
            f"review action must be a string, got {type(raw).__name__}"
        )
    candidate = raw.strip().lower()
    if candidate not in VALID_REVIEW_ACTIONS:
        raise ReviewActionError(
            f"unknown review action: {raw!r} (valid: "
            f"{sorted(VALID_REVIEW_ACTIONS)})"
        )
    return candidate


def format_review_row(
    *,
    action: str,
    finding: str,
    file_ref: str = "",
    line: int | None = None,
) -> str:
    """Render a single review row in the canonical markdown form.

    Shape:
        "[Review][<action>] <file>:<line> <finding>"

    When ``file_ref`` is empty the ``<file>:<line>`` segment is omitted;
    when ``line`` is None but ``file_ref`` is present only the file is
    rendered. Action is canonicalized before formatting.
    """
    canonical = canonicalize_action(action)
    if not isinstance(finding, str) or not finding.strip():
        raise ValueError("finding must be a non-empty string")
    finding_text = finding.strip()
    file_text = file_ref.strip() if isinstance(file_ref, str) else ""

    parts = [f"[Review][{canonical}]"]
    if file_text:
        if line is not None:
            parts.append(f"{file_text}:{line}")
        else:
            parts.append(file_text)
    parts.append(finding_text)
    return " ".join(parts)


# Anchored parser for the canonical row form. The action token must be one
# of the taxonomy members; downstream canonicalize_action enforces that.
_ROW_RE = re.compile(
    r"^\[Review\]\[(?P<action>[A-Za-z_]+)\]\s+"
    r"(?:(?P<file>\S+?)(?::(?P<line>\d+))?\s+)?"
    r"(?P<finding>.+?)\s*$"
)


def parse_review_row(row: object) -> dict | None:
    """Inverse of format_review_row.

    Returns a dict with keys ``action``, ``file_ref``, ``line``, ``finding``
    on success, or None if ``row`` is not a recognizable canonical review
    row (including unknown action tokens).
    """
    if not isinstance(row, str):
        return None
    match = _ROW_RE.match(row)
    if not match:
        return None
    try:
        action = canonicalize_action(match.group("action"))
    except ReviewActionError:
        return None

    file_group = match.group("file") or ""
    line_group = match.group("line")
    # Heuristic: a bare token that parses as canonical file_ref but is
    # actually the first word of the finding (i.e. no explicit colon-line
    # and no path separator). Treat as part of finding.
    if file_group and line_group is None and "/" not in file_group and "." not in file_group:
        finding = (file_group + " " + match.group("finding")).strip()
        return {
            "action": action,
            "file_ref": "",
            "line": None,
            "finding": finding,
        }

    return {
        "action": action,
        "file_ref": file_group,
        "line": int(line_group) if line_group is not None else None,
        "finding": match.group("finding").strip(),
    }
