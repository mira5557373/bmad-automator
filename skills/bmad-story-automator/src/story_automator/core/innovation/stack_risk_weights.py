from __future__ import annotations

"""Stack risk weights — folder taxonomy to per-stack risk multiplier.

This module classifies changed paths into a small, stable set of *stack* groups
(backend, frontend, tests, docs, config, scripts, other) and assigns each group
a risk multiplier. Higher multipliers reflect the empirical likelihood that a
defect in that stack escapes the gate into production behaviour. Docs-only
edits, by contrast, are weighted close to neutral (1.0) because reviewers can
catch their failure modes quickly and the runtime is not affected.

Design invariants:

* Pure function: same inputs -> same outputs, no side effects, no I/O.
* Fail-closed: unknown stack ids raise :class:`StackRiskError`.
* Unknown paths fall through to ``other`` (multiplier 1.0) rather than raising,
  so callers can hand the module an arbitrary changed-file list without
  pre-validation. Use :func:`validate_taxonomy` when constructing custom maps.
* No I/O. Callers wire in their own changed-file list and aggregation choice.

The default taxonomy uses *prefix* matching (longest-prefix wins) and a small
extension-based fallback for top-level files such as ``README.md`` or
``package.json`` that have no directory prefix.

Typical usage::

    from story_automator.core.innovation.stack_risk_weights import (
        risk_multiplier,
    )

    base = 7.2  # base risk score from earlier gate machinery
    multiplier = risk_multiplier(changed_paths, strategy="weighted")
    weighted_score = base * multiplier
"""

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StackRiskError(ValueError):
    """Raised when stack-risk inputs or registries are malformed."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StackWeight:
    """Per-stack risk multiplier.

    ``multiplier`` is a non-negative float used as a scalar against a base risk
    score. Values >1.0 amplify risk for the stack; values <1.0 dampen it.
    """

    stack: str
    multiplier: float
    note: str = ""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


VALID_STACK_IDS: tuple[str, ...] = (
    "backend",
    "frontend",
    "tests",
    "docs",
    "config",
    "scripts",
    "other",
)
"""Canonical stack identifiers used by the bundled taxonomy."""


VALID_STRATEGIES: tuple[str, ...] = ("max", "mean", "weighted")
"""Aggregation strategies recognized by :func:`aggregate_weights`."""


# ---------------------------------------------------------------------------
# Bundled taxonomy
# ---------------------------------------------------------------------------


# Prefix patterns are checked longest-first. Each list captures common prefixes
# we see in BMAD-shaped repos: a Python source root, a Node/Web frontend, a
# tests root, docs, config manifests, and bin/scripts.
DEFAULT_PATH_TAXONOMY: dict[str, list[str]] = {
    "backend": [
        "skills/bmad-story-automator/src/",
        "src/story_automator/",
        "src/",
        "skills/bmad-story-automator/scripts/story-automator",
    ],
    "frontend": [
        "web/",
        "ui/",
        "frontend/",
        "app/",
    ],
    "tests": [
        "tests/",
        "skills/bmad-story-automator/tests/",
    ],
    "docs": [
        "docs/",
        "README",
        ".github/ISSUE_TEMPLATE",
    ],
    "config": [
        ".claude-plugin/",
        ".github/workflows/",
        "package.json",
        "package-lock.json",
        "pyproject.toml",
        "requirements",
        "tsconfig",
    ],
    "scripts": [
        "scripts/",
        "bin/",
        "install.sh",
    ],
}
"""Bundled folder/file taxonomy. Each stack id maps to a list of path prefixes."""


# Extension fallbacks for top-level files without a directory prefix.
_EXTENSION_FALLBACK: dict[str, str] = {
    ".md": "docs",
    ".rst": "docs",
    ".txt": "docs",
    ".json": "config",
    ".toml": "config",
    ".yml": "config",
    ".yaml": "config",
    ".cfg": "config",
    ".ini": "config",
    ".sh": "scripts",
    ".bash": "scripts",
}


# Default per-stack multipliers. Backend changes touch the production runtime
# so they carry the highest weight; docs the lowest. ``other`` is neutral so an
# unclassified path neither amplifies nor dampens risk.
DEFAULT_STACK_WEIGHTS: dict[str, StackWeight] = {
    "backend": StackWeight(
        stack="backend",
        multiplier=1.5,
        note="Touches runtime; defects escape easily.",
    ),
    "frontend": StackWeight(
        stack="frontend",
        multiplier=1.2,
        note="User-visible surface; visual review usually catches issues.",
    ),
    "tests": StackWeight(
        stack="tests",
        multiplier=0.8,
        note="Test-only churn; gate catches behavioural regressions.",
    ),
    "docs": StackWeight(
        stack="docs",
        multiplier=0.5,
        note="Docs do not affect runtime; reviewers catch errors quickly.",
    ),
    "config": StackWeight(
        stack="config",
        multiplier=1.3,
        note="Wiring/manifest changes have broad blast radius.",
    ),
    "scripts": StackWeight(
        stack="scripts",
        multiplier=1.1,
        note="Operator-facing scripts; impact between docs and backend.",
    ),
    "other": StackWeight(
        stack="other",
        multiplier=1.0,
        note="Unclassified path; neutral multiplier.",
    ),
}


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def is_known_stack(stack: str) -> bool:
    """Return ``True`` if ``stack`` is in :data:`VALID_STACK_IDS`."""

    return isinstance(stack, str) and stack in VALID_STACK_IDS


def validate_taxonomy(taxonomy: Mapping[str, Sequence[str]]) -> None:
    """Raise :class:`StackRiskError` if ``taxonomy`` is malformed."""

    if not isinstance(taxonomy, Mapping) or not taxonomy:
        raise StackRiskError("taxonomy must be a non-empty mapping")
    for stack, patterns in taxonomy.items():
        if not isinstance(stack, str) or not stack:
            raise StackRiskError(f"taxonomy stack id must be a non-empty string: {stack!r}")
        if not isinstance(patterns, (list, tuple)):
            raise StackRiskError(
                f"taxonomy entry for {stack!r} must be a list/tuple of patterns"
            )
        for pat in patterns:
            if not isinstance(pat, str) or not pat:
                raise StackRiskError(
                    f"taxonomy pattern for {stack!r} must be a non-empty string"
                )


def validate_weights(weights: Mapping[str, StackWeight]) -> None:
    """Raise :class:`StackRiskError` if ``weights`` is malformed."""

    if not isinstance(weights, Mapping) or not weights:
        raise StackRiskError("weights must be a non-empty mapping")
    for stack, entry in weights.items():
        if not isinstance(stack, str) or not stack:
            raise StackRiskError(f"weight stack id must be a non-empty string: {stack!r}")
        if not isinstance(entry, StackWeight):
            raise StackRiskError(f"weight for {stack!r} must be a StackWeight")
        if entry.multiplier < 0.0:
            raise StackRiskError(
                f"weight multiplier for {stack!r} must be non-negative; got {entry.multiplier}"
            )


def register_stack(
    registry: dict[str, StackWeight],
    stack: str,
    multiplier: float,
    note: str = "",
) -> None:
    """Add a new stack id to a weights registry.

    Raises :class:`StackRiskError` if the stack id is blank, already present,
    or the multiplier is negative.
    """

    if not isinstance(stack, str) or not stack.strip():
        raise StackRiskError("stack id must be a non-empty string")
    if stack in registry:
        raise StackRiskError(f"stack {stack!r} already registered")
    if not isinstance(multiplier, (int, float)) or multiplier < 0.0:
        raise StackRiskError(
            f"multiplier for {stack!r} must be a non-negative number; got {multiplier!r}"
        )
    registry[stack] = StackWeight(stack=stack, multiplier=float(multiplier), note=note)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _normalize_path(path: str) -> str:
    """Trim and normalise a path string for matching."""

    if not isinstance(path, str):
        raise StackRiskError(f"path must be a string; got {type(path).__name__}")
    cleaned = path.strip()
    if not cleaned:
        raise StackRiskError("path must be a non-empty string")
    # Treat both ``./`` and absolute leading slashes as relative for matching.
    if cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def classify_path(
    path: str,
    taxonomy: Mapping[str, Sequence[str]] = DEFAULT_PATH_TAXONOMY,
) -> str:
    """Return the stack id that owns ``path`` according to ``taxonomy``.

    The match uses longest-prefix-wins across all configured patterns. If no
    pattern matches, an extension-based fallback is consulted; failing that,
    the path is classified as ``"other"``.
    """

    cleaned = _normalize_path(path)

    best_stack: str | None = None
    best_len = -1
    for stack, patterns in taxonomy.items():
        for pat in patterns:
            if cleaned.startswith(pat) and len(pat) > best_len:
                best_stack = stack
                best_len = len(pat)
    if best_stack is not None:
        return best_stack

    # Extension fallback for top-level files (e.g. ``README.md``).
    lowered = cleaned.lower()
    for ext, stack in _EXTENSION_FALLBACK.items():
        if lowered.endswith(ext):
            return stack

    return "other"


def classify_paths(
    paths: Iterable[str],
    taxonomy: Mapping[str, Sequence[str]] = DEFAULT_PATH_TAXONOMY,
) -> dict[str, list[str]]:
    """Group ``paths`` by their classified stack id.

    Paths that classify as ``"other"`` are *omitted* from the returned mapping
    so callers can iterate "real" stacks without filtering. The original input
    order is preserved within each group.
    """

    grouped: dict[str, list[str]] = {}
    for p in paths:
        stack = classify_path(p, taxonomy)
        if stack == "other":
            continue
        grouped.setdefault(stack, []).append(p)
    return grouped


# ---------------------------------------------------------------------------
# Weight lookup
# ---------------------------------------------------------------------------


def weight_for_stack(
    stack: str,
    weights: Mapping[str, StackWeight] = DEFAULT_STACK_WEIGHTS,
) -> StackWeight:
    """Return the :class:`StackWeight` for ``stack``.

    Raises :class:`StackRiskError` if the stack id is not present in the
    weights registry.
    """

    if not isinstance(stack, str) or stack not in weights:
        raise StackRiskError(f"unknown stack id: {stack!r}")
    return weights[stack]


def weight_for_path(
    path: str,
    weights: Mapping[str, StackWeight] = DEFAULT_STACK_WEIGHTS,
    taxonomy: Mapping[str, Sequence[str]] = DEFAULT_PATH_TAXONOMY,
) -> StackWeight:
    """Return the :class:`StackWeight` for the stack that owns ``path``."""

    return weight_for_stack(classify_path(path, taxonomy), weights)


# ---------------------------------------------------------------------------
# Apply / aggregate
# ---------------------------------------------------------------------------


def apply_weight(base: float, weight: StackWeight) -> float:
    """Return ``base * weight.multiplier``.

    Raises :class:`StackRiskError` if ``base`` is negative — risk scores are
    non-negative by convention.
    """

    if not isinstance(base, (int, float)):
        raise StackRiskError(f"base must be numeric; got {type(base).__name__}")
    if base < 0.0:
        raise StackRiskError(f"base risk must be non-negative; got {base}")
    return float(base) * weight.multiplier


def aggregate_weights(
    paths: Sequence[str],
    strategy: str = "weighted",
    weights: Mapping[str, StackWeight] = DEFAULT_STACK_WEIGHTS,
    taxonomy: Mapping[str, Sequence[str]] = DEFAULT_PATH_TAXONOMY,
) -> float:
    """Aggregate per-path multipliers across ``paths`` using ``strategy``.

    Strategies:

    * ``"max"`` — the largest multiplier among all paths (most conservative).
    * ``"mean"`` — unweighted mean across *unique* stacks present.
    * ``"weighted"`` — mean across paths, so a stack appearing many times
      dominates the result (production realism).

    Empty path lists return ``1.0`` (neutral). Unknown strategies raise
    :class:`StackRiskError`.
    """

    if strategy not in VALID_STRATEGIES:
        raise StackRiskError(
            f"unknown aggregation strategy {strategy!r}; expected one of {VALID_STRATEGIES}"
        )

    path_list = list(paths)
    if not path_list:
        return 1.0

    multipliers = [
        weight_for_path(p, weights, taxonomy).multiplier for p in path_list
    ]

    if strategy == "max":
        return max(multipliers)
    if strategy == "weighted":
        return sum(multipliers) / len(multipliers)
    # mean: unique stacks
    seen: dict[str, float] = {}
    for p, m in zip(path_list, multipliers):
        stack = classify_path(p, taxonomy)
        seen.setdefault(stack, m)
    if not seen:
        return 1.0
    return sum(seen.values()) / len(seen)


def risk_multiplier(
    paths: Sequence[str],
    strategy: str = "weighted",
    weights: Mapping[str, StackWeight] = DEFAULT_STACK_WEIGHTS,
    taxonomy: Mapping[str, Sequence[str]] = DEFAULT_PATH_TAXONOMY,
) -> float:
    """Convenience wrapper returning the aggregate multiplier for ``paths``."""

    return aggregate_weights(paths, strategy=strategy, weights=weights, taxonomy=taxonomy)


# ---------------------------------------------------------------------------
# Explain
# ---------------------------------------------------------------------------


def explain_classification(
    paths: Sequence[str],
    taxonomy: Mapping[str, Sequence[str]] = DEFAULT_PATH_TAXONOMY,
) -> str:
    """Return a human-readable explanation of how ``paths`` were classified."""

    if not paths:
        return "stack-risk: no paths supplied; multiplier defaults to 1.0."

    grouped = classify_paths(paths, taxonomy)
    lines: list[str] = []
    for stack in sorted(grouped):
        members = grouped[stack]
        lines.append(f"- {stack} ({len(members)}): " + ", ".join(members))

    # Surface any unclassified (other) paths so the operator sees them.
    other = [p for p in paths if classify_path(p, taxonomy) == "other"]
    if other:
        lines.append(f"- other ({len(other)}): " + ", ".join(other))

    return "stack-risk classification:\n" + "\n".join(lines)
