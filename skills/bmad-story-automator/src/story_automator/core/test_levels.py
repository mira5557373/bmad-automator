from __future__ import annotations

"""Canonical test-level vocabulary.

Defines the four-member taxonomy used to classify tests across the
factory (e2e, api, component, unit) plus the legacy aliases the bmad
ecosystem produces (integration -> api, ui -> component, end-to-end ->
e2e, unit-test -> unit, func/functional -> api). Designed to be the
single source of truth for level normalization and bucketing.
"""

CANONICAL_LEVELS: tuple[str, ...] = ("e2e", "api", "component", "unit")

LEVEL_ALIASES: dict[str, str] = {
    "integration": "api",
    "ui": "component",
    "unit-test": "unit",
    "end-to-end": "e2e",
    "func": "api",
    "functional": "api",
}


class TestLevelError(ValueError):
    """Raised when a test-level token is not a member of the taxonomy."""


def is_canonical(level: object) -> bool:
    """Return True if ``level`` is exactly a canonical taxonomy member.

    Strict: case-sensitive and string-only. Use ``canonicalize_level`` to
    first normalize case / aliases.
    """
    return isinstance(level, str) and level in CANONICAL_LEVELS


def canonicalize_level(raw: object) -> str:
    """Normalize a test-level token to its canonical lowercase form.

    Accepts the canonical members and the aliases declared in
    ``LEVEL_ALIASES``. Case-insensitive; surrounding whitespace is
    stripped. Raises ``TestLevelError`` for non-string input, empty
    input, and unknown tokens.
    """
    if not isinstance(raw, str):
        raise TestLevelError(
            f"test level must be a string, got {type(raw).__name__}"
        )
    candidate = raw.strip().lower()
    if not candidate:
        raise TestLevelError("test level must be a non-empty string")
    if candidate in CANONICAL_LEVELS:
        return candidate
    if candidate in LEVEL_ALIASES:
        return LEVEL_ALIASES[candidate]
    raise TestLevelError(
        f"unknown test level: {raw!r} (valid: "
        f"{list(CANONICAL_LEVELS)} or aliases "
        f"{sorted(LEVEL_ALIASES)})"
    )


def bucket_levels(levels: list[str]) -> dict[str, list[str]]:
    """Group ``levels`` under their canonical bucket, preserving originals.

    The returned dict always contains every canonical level as a key
    (empty list when no input maps there) so callers can iterate
    deterministically without ``KeyError`` guards. Each list preserves
    the order in which entries appeared in ``levels`` and stores the
    original (un-normalized) token, so callers can surface the original
    spelling in diagnostics while still grouping by canonical bucket.

    Raises ``TestLevelError`` if any entry cannot be canonicalized.
    """
    buckets: dict[str, list[str]] = {level: [] for level in CANONICAL_LEVELS}
    for entry in levels:
        canonical = canonicalize_level(entry)
        buckets[canonical].append(entry)
    return buckets
