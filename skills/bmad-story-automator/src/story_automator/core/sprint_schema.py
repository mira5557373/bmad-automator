"""Sprint-status YAML schema validator.

Validates the in-memory representation of a ``sprint-status.yaml`` document
(typically the dict returned by ``yaml.safe_load``).

The validator enforces:

* Exactly the required top-level keys are present.
* No unknown top-level keys appear.
* ``stories`` is a list of dicts and each story entry has a status that
  canonicalizes to one of the documented BMAD lifecycle states.

The canonicalization helper is kept local to this module (a small,
case/whitespace-insensitive mapping) so the validator has no runtime
dependency on a separate ``story_status`` module. If/when a shared
``core/story_status.canonicalize`` is introduced, this module can switch
to importing it without changing its public surface.
"""

from __future__ import annotations

from typing import Any, Iterable

REQUIRED_TOP_LEVEL: tuple[str, ...] = ("epic", "sprint_id", "started_at", "stories")
ALLOWED_TOP_LEVEL: tuple[str, ...] = REQUIRED_TOP_LEVEL + ("notes", "carry_over")

# Canonical BMAD story lifecycle states. Kept as a frozen set so callers
# can't mutate it accidentally.
_CANONICAL_STATUSES: frozenset[str] = frozenset(
    {
        "Draft",
        "Approved",
        "InProgress",
        "Review",
        "Done",
    }
)

# Map of normalized (lowercased, whitespace/hyphen/underscore stripped) status
# strings to their canonical capitalization.
_STATUS_ALIASES: dict[str, str] = {
    "draft": "Draft",
    "approved": "Approved",
    "inprogress": "InProgress",
    "in_progress": "InProgress",
    "in-progress": "InProgress",
    "in progress": "InProgress",
    "review": "Review",
    "readyforreview": "Review",
    "ready_for_review": "Review",
    "ready-for-review": "Review",
    "ready for review": "Review",
    "done": "Done",
    "completed": "Done",
}


class SprintSchemaError(ValueError):
    """Raised when a sprint-status payload fails schema validation."""


def _canonicalize_status(raw: Any) -> str:
    """Return the canonical capitalization for ``raw`` or raise.

    Accepts any string that matches a canonical status (case-insensitively)
    or one of the aliases in ``_STATUS_ALIASES``. Whitespace is normalized.
    """
    if not isinstance(raw, str):
        raise SprintSchemaError(f"story status must be a string, got {type(raw).__name__}")
    stripped = raw.strip()
    if not stripped:
        raise SprintSchemaError("story status must not be empty")
    # Direct match against canonical set first (cheap & exact).
    if stripped in _CANONICAL_STATUSES:
        return stripped
    key = stripped.lower()
    if key in _STATUS_ALIASES:
        return _STATUS_ALIASES[key]
    # Try a more aggressive normalization (collapse whitespace).
    collapsed = " ".join(stripped.lower().split())
    if collapsed in _STATUS_ALIASES:
        return _STATUS_ALIASES[collapsed]
    raise SprintSchemaError(
        f"invalid story status: {raw!r} (expected one of {sorted(_CANONICAL_STATUSES)})"
    )


def _validate_top_level_keys(data: dict) -> None:
    keys = set(data.keys())
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in keys]
    if missing:
        raise SprintSchemaError(f"missing required key(s): {', '.join(missing)}")
    unknown = sorted(keys - set(ALLOWED_TOP_LEVEL))
    if unknown:
        raise SprintSchemaError(f"unknown top-level key(s): {', '.join(unknown)}")


def _validate_stories(stories: Any) -> None:
    if not isinstance(stories, list):
        raise SprintSchemaError(
            f"'stories' must be a list, got {type(stories).__name__}"
        )
    for index, entry in enumerate(stories):
        if not isinstance(entry, dict):
            raise SprintSchemaError(
                f"stories[{index}] must be a mapping, got {type(entry).__name__}"
            )
        if "status" not in entry:
            raise SprintSchemaError(f"stories[{index}] is missing 'status'")
        _canonicalize_status(entry["status"])


def validate_sprint_status(data: dict) -> None:
    """Validate a parsed sprint-status YAML document.

    Raises :class:`SprintSchemaError` (a ``ValueError`` subclass) on the
    first violation. Returns ``None`` on success.
    """
    if not isinstance(data, dict):
        raise SprintSchemaError(
            f"sprint-status payload must be a mapping, got {type(data).__name__}"
        )
    _validate_top_level_keys(data)
    _validate_stories(data["stories"])


__all__: Iterable[str] = (
    "ALLOWED_TOP_LEVEL",
    "REQUIRED_TOP_LEVEL",
    "SprintSchemaError",
    "validate_sprint_status",
)
