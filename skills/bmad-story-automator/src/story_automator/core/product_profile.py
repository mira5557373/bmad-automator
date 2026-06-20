"""Product Profile subsystem.

Loads, validates, and snapshots the per-product profile that specializes
the general factory (gate rubric, toolchain, matrix, rules, invariants).

Layered resolution (mirrors runtime_policy):
    bundled default  ->  project override  ->  env overrides

Paths:
    bundled: <skills_root>/bmad-story-automator/data/profiles/<id>.json
    project override: <project_root>/_bmad/bmm/story-automator.profile.json
    env selection: STORY_AUTOMATOR_PROFILE
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .runtime_layout import bundled_story_skill_root
from .utils import get_project_root, read_text


class ProfileError(ValueError):
    pass


VALID_TOP_LEVEL_KEYS = {
    "version",
    "id",
    "snapshot",
    "seed_template",
    "toolchain",
    "matrix",
    "categories",
    "categories_na",
    "rules",
    "invariants",
    "forbidden_until",
    "cost_tier",
    "timeouts",
}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_CODE_CATEGORIES = {
    "correctness", "traceability", "test_quality", "mutation",
    "static", "security", "compliance", "license", "supply_chain",
    "api_compat", "migrations", "performance", "accessibility",
    "observability", "invariants", "agentic", "docs", "process",
}
VALID_SYSTEM_CATEGORIES = {
    "reliability", "resilience", "durable_hitl",
    "blast_radius", "cost_to_serve",
}
DEFAULT_TIMEOUTS: dict[str, int] = {
    "security": 300,
    "performance": 600,
    "accessibility": 180,
    "test_quality": 900,
    "correctness": 1800,
}
DEFAULT_TIMEOUT_FALLBACK = 120

_PROFILES_DIR = "data/profiles"
_PROFILE_ID_ENV = "STORY_AUTOMATOR_PROFILE"


def _validate_profile_shape(profile: dict[str, Any]) -> None:
    unknown_keys = sorted(set(profile) - VALID_TOP_LEVEL_KEYS)
    if unknown_keys:
        raise ProfileError(
            f"unknown top-level profile keys: {', '.join(unknown_keys)}"
        )
    _validate_version_and_id(profile)
    _validate_matrix(profile.get("matrix"))
    _validate_categories(profile.get("categories"))


def _validate_version_and_id(profile: dict[str, Any]) -> None:
    version = profile.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProfileError("profile.version must be a positive integer")
    pid = profile.get("id")
    if not isinstance(pid, str) or not pid.strip():
        raise ProfileError("profile.id must be a non-empty string")


def _validate_matrix(matrix: Any) -> None:
    if not isinstance(matrix, dict):
        raise ProfileError("matrix must be an object")
    missing = sorted(VALID_PRIORITIES - set(matrix))
    if missing:
        raise ProfileError(
            f"matrix priorities must include all of "
            f"{sorted(VALID_PRIORITIES)}; missing: {missing}"
        )
    unknown = sorted(set(matrix) - VALID_PRIORITIES)
    if unknown:
        raise ProfileError(f"unknown matrix priorities: {', '.join(unknown)}")
    for prio, value in matrix.items():
        if not isinstance(value, dict):
            raise ProfileError(f"matrix.{prio} must be an object")
        coverage = value.get("coverage_pct")
        if (
            not isinstance(coverage, int)
            or isinstance(coverage, bool)
            or coverage < 0
            or coverage > 100
        ):
            raise ProfileError(
                f"matrix.{prio}.coverage_pct must be int 0..100"
            )
        levels = value.get("levels")
        if not isinstance(levels, list) or not all(
            isinstance(item, str) for item in levels
        ):
            raise ProfileError(
                f"matrix.{prio}.levels must be a string array"
            )


def _validate_categories(categories: Any) -> None:
    if not isinstance(categories, dict):
        raise ProfileError("categories must be an object")
    for tier, allowed in (
        ("code", VALID_CODE_CATEGORIES),
        ("system", VALID_SYSTEM_CATEGORIES),
    ):
        items = categories.get(tier, [])
        if not isinstance(items, list) or not all(
            isinstance(item, str) for item in items
        ):
            raise ProfileError(f"categories.{tier} must be a string array")
        unknown = sorted(set(items) - allowed)
        if unknown:
            raise ProfileError(
                f"unknown {tier} categories: {', '.join(unknown)}"
            )


def load_bundled_profile(
    profile_id: str = "default",
    project_root: str | None = None,
) -> dict[str, Any]:
    bundle_root = _bundle_root(project_root)
    profiles_dir = bundle_root / _PROFILES_DIR
    path = profiles_dir / f"{profile_id}.json"
    if not path.is_file():
        available = sorted(p.stem for p in profiles_dir.glob("*.json"))
        raise ProfileError(
            f"unknown bundled profile {profile_id!r}; available: {available}"
        )
    profile = _read_json(path)
    _validate_profile_shape(profile)
    return profile


def _bundle_root(project_root: str | None) -> Path:
    root = Path(project_root or get_project_root()).resolve()
    try:
        return bundled_story_skill_root(root)
    except FileNotFoundError as exc:
        raise ProfileError("bundled story automator not found") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(read_text(path))
    except FileNotFoundError as exc:
        raise ProfileError(f"profile file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(
            f"profile json invalid: {path}: {exc.msg} (line {exc.lineno})"
        ) from exc
    if not isinstance(payload, dict):
        raise ProfileError(f"profile json must be an object: {path}")
    return payload
