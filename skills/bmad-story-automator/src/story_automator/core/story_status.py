from __future__ import annotations

VALID_STATUSES: frozenset[str] = frozenset(
    {"backlog", "ready-for-dev", "in-progress", "review", "done"}
)

LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "backlog": frozenset({"ready-for-dev"}),
    "ready-for-dev": frozenset({"in-progress", "backlog"}),
    "in-progress": frozenset({"review", "ready-for-dev"}),
    "review": frozenset({"in-progress", "done"}),
    "done": frozenset(),
}

LEGACY_ALIASES: dict[str, str] = {
    "drafted": "ready-for-dev",
    "contexted": "in-progress",
}

_ACTIONABLE: frozenset[str] = frozenset({"backlog", "ready-for-dev"})


class StoryStatusError(ValueError):
    """Raised on unknown statuses or illegal transitions."""


def canonicalize(value: object) -> str:
    """Normalize *value* into a canonical status string.

    Strips surrounding whitespace, lower-cases, and resolves legacy aliases.
    Raises :class:`StoryStatusError` if *value* is not a string or does not
    map to a known status.
    """
    if not isinstance(value, str):
        raise StoryStatusError(f"status must be a string, got {type(value).__name__}")
    cleaned = value.strip().lower()
    if not cleaned:
        raise StoryStatusError("status is empty")
    if cleaned in LEGACY_ALIASES:
        cleaned = LEGACY_ALIASES[cleaned]
    if cleaned not in VALID_STATUSES:
        raise StoryStatusError(f"unknown story status: {value!r}")
    return cleaned


def is_valid(value: object) -> bool:
    """Return True iff *value* is already a canonical status string.

    Legacy aliases ("drafted", "contexted") return False here — callers must
    use :func:`canonicalize` first if they wish to accept aliases.
    """
    return isinstance(value, str) and value in VALID_STATUSES


def transition(current: object, target: object) -> str:
    """Validate and return the canonical *target* status.

    Both *current* and *target* are canonicalized (aliases resolved). Raises
    :class:`StoryStatusError` if either is unknown or if the resulting
    transition is not present in :data:`LEGAL_TRANSITIONS`.
    """
    src = canonicalize(current)
    dst = canonicalize(target)
    if dst not in LEGAL_TRANSITIONS[src]:
        raise StoryStatusError(f"illegal story status transition: {src!r} -> {dst!r}")
    return dst


def is_terminal(value: object) -> bool:
    """Return True iff *value* canonicalizes to a terminal status (``done``)."""
    return canonicalize(value) == "done"


def is_actionable(value: object) -> bool:
    """Return True iff *value* canonicalizes to a status the operator can act on.

    Actionable statuses are ``backlog`` and ``ready-for-dev`` — stories awaiting
    grooming or pickup. Stories already in flight (``in-progress``, ``review``)
    or completed (``done``) are not actionable here.
    """
    return canonicalize(value) in _ACTIONABLE


__all__ = [
    "LEGACY_ALIASES",
    "LEGAL_TRANSITIONS",
    "StoryStatusError",
    "VALID_STATUSES",
    "canonicalize",
    "is_actionable",
    "is_terminal",
    "is_valid",
    "transition",
]
