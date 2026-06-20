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

import fnmatch
import json
import os
from pathlib import Path
from typing import Any

from .runtime_layout import bundled_story_skill_root
from .utils import ensure_dir, get_project_root, iso_now, md5_hex8, read_text, write_atomic


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
_OVERRIDE_PATH = Path("_bmad") / "bmm" / "story-automator.profile.json"


def _validate_profile_shape(profile: dict[str, Any]) -> None:
    unknown_keys = sorted(set(profile) - VALID_TOP_LEVEL_KEYS)
    if unknown_keys:
        raise ProfileError(
            f"unknown top-level profile keys: {', '.join(unknown_keys)}"
        )
    _validate_version_and_id(profile)
    _validate_matrix(profile.get("matrix"))
    _validate_categories(profile.get("categories"))
    _validate_toolchain(profile.get("toolchain"))
    _validate_rules(profile.get("rules"))
    _validate_seed_template(profile.get("seed_template"))
    _validate_invariants(profile.get("invariants"))
    _validate_snapshot(profile.get("snapshot"))
    _validate_cost_tier(profile.get("cost_tier"))
    _validate_categories_na(profile.get("categories_na"))
    _validate_timeouts(profile.get("timeouts"))
    _validate_forbidden_until(profile.get("forbidden_until"))


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


def _validate_toolchain(toolchain: Any) -> None:
    if toolchain is None:
        return
    if not isinstance(toolchain, dict):
        raise ProfileError("toolchain must be an object")
    for language, entries in toolchain.items():
        if not isinstance(entries, list):
            raise ProfileError(f"toolchain.{language} must be an array")
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ProfileError(f"toolchain.{language}[{idx}] must be an object")
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise ProfileError(f"toolchain.{language}[{idx}].name must be a non-empty string")
            if "version_min" in entry and not isinstance(entry["version_min"], str):
                raise ProfileError(f"toolchain.{language}[{idx}].version_min must be a string")
            if "required" in entry and not isinstance(entry["required"], bool):
                raise ProfileError(f"toolchain.{language}[{idx}].required must be a bool")


def _validate_rules(rules: Any) -> None:
    if rules is None:
        return
    if not isinstance(rules, dict):
        raise ProfileError("rules must be an object")
    for category, body in rules.items():
        if not isinstance(body, dict):
            raise ProfileError(f"rules.{category} must be an object")


def _validate_seed_template(seed: Any) -> None:
    if seed is None:
        return
    if not isinstance(seed, dict):
        raise ProfileError("seed_template must be an object")
    if "ref" in seed and not isinstance(seed["ref"], str):
        raise ProfileError("seed_template.ref must be a string")
    if "url" in seed and not isinstance(seed["url"], str):
        raise ProfileError("seed_template.url must be a string")


def _validate_invariants(invariants: Any) -> None:
    if invariants is None:
        return
    if not isinstance(invariants, dict):
        raise ProfileError("invariants must be an object")
    if "registry_file" in invariants and not isinstance(invariants["registry_file"], str):
        raise ProfileError("invariants.registry_file must be a string")


def _validate_snapshot(snapshot: Any) -> None:
    if snapshot is None:
        return
    if not isinstance(snapshot, dict):
        raise ProfileError("snapshot must be an object")
    rel = snapshot.get("relativeDir")
    if rel is not None and (not isinstance(rel, str) or not rel.strip()):
        raise ProfileError("snapshot.relativeDir must be a non-empty string")


_COST_TIER_NUMERIC = {"arpu_monthly", "max_pod_cost_per_tenant"}


def _validate_cost_tier(cost_tier: Any) -> None:
    if cost_tier is None:
        return
    if not isinstance(cost_tier, dict):
        raise ProfileError("cost_tier must be an object")
    if "sku_id" in cost_tier and not isinstance(cost_tier["sku_id"], str):
        raise ProfileError("cost_tier.sku_id must be a string")
    for key in _COST_TIER_NUMERIC:
        value = cost_tier.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ProfileError(f"cost_tier.{key} must be a non-negative number")


def _validate_categories_na(categories_na: Any) -> None:
    if categories_na is None:
        return
    if not isinstance(categories_na, list) or not all(
        isinstance(item, str) for item in categories_na
    ):
        raise ProfileError("categories_na must be a string array")
    unknown = sorted(set(categories_na) - VALID_CODE_CATEGORIES - VALID_SYSTEM_CATEGORIES)
    if unknown:
        raise ProfileError(
            f"unknown categories_na entries: {', '.join(unknown)}"
        )


def _validate_timeouts(timeouts: Any) -> None:
    if timeouts is None:
        return
    if not isinstance(timeouts, dict):
        raise ProfileError("timeouts must be an object")
    for category, seconds in timeouts.items():
        if category not in VALID_CODE_CATEGORIES and category not in VALID_SYSTEM_CATEGORIES:
            raise ProfileError(f"unknown category in timeouts: {category}")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ProfileError(
                f"timeouts.{category} must be a positive integer"
            )


def _validate_forbidden_until(mapping: Any) -> None:
    if mapping is None:
        return
    if not isinstance(mapping, dict):
        raise ProfileError("forbidden_until must be an object")
    for adr, patterns in mapping.items():
        if not isinstance(adr, str) or not adr:
            raise ProfileError("forbidden_until keys must be non-empty strings")
        if not isinstance(patterns, list) or not all(
            isinstance(p, str) and p for p in patterns
        ):
            raise ProfileError(
                f"forbidden_until.{adr} must be a string array"
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


def load_effective_profile(
    project_root: str | None = None,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    resolved_id = (
        profile_id
        or os.environ.get(_PROFILE_ID_ENV, "").strip()
        or "default"
    )
    bundled = load_bundled_profile(resolved_id, project_root=str(root))
    override_path = root / _OVERRIDE_PATH
    if override_path.is_file():
        override = _read_json(override_path)
        merged = _deep_merge(bundled, override)
    else:
        merged = bundled
    _validate_profile_shape(merged)
    return merged


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = (
                _deep_merge(merged[key], value) if key in merged else value
            )
        return merged
    if isinstance(override, list):
        return list(override)
    return override


def required_for_priority(
    profile: dict[str, Any], priority: str
) -> dict[str, Any]:
    if priority not in VALID_PRIORITIES:
        raise ProfileError(f"unknown priority: {priority}")
    entry = (profile.get("matrix") or {}).get(priority) or {}
    return {
        "coverage_pct": int(entry.get("coverage_pct", 0)),
        "levels": list(entry.get("levels") or []),
    }


def toolchain_for(
    profile: dict[str, Any], language: str
) -> list[dict[str, Any]]:
    entries = (profile.get("toolchain") or {}).get(language) or []
    return [dict(entry) for entry in entries]


def rule_for(profile: dict[str, Any], category: str) -> dict[str, Any]:
    return dict((profile.get("rules") or {}).get(category) or {})


def is_story_blocked(
    profile: dict[str, Any], story_id: str
) -> tuple[bool, str]:
    mapping = profile.get("forbidden_until") or {}
    for adr in sorted(mapping):
        for pattern in mapping[adr]:
            if fnmatch.fnmatchcase(story_id, pattern):
                return True, adr
    return False, ""


def compute_profile_hash(profile: dict[str, Any]) -> str:
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    return md5_hex8(canonical)


def snapshot_effective_profile(
    project_root: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    profile = load_effective_profile(str(root))
    snapshot_dir = _resolve_snapshot_dir(profile, root)
    ensure_dir(snapshot_dir)
    stable_json = _stable_profile_json(profile)
    snapshot_hash = md5_hex8(stable_json)
    stamp = (
        iso_now()
        .replace("-", "")
        .replace(":", "")
        .replace("T", "-")
        .replace("Z", "")
    )
    snapshot_path = snapshot_dir / f"{stamp}-{snapshot_hash}.json"
    write_atomic(snapshot_path, stable_json)
    return {
        "profile": profile,
        "profileVersion": profile.get("version", 1),
        "profileSnapshotHash": snapshot_hash,
        "profileSnapshotFile": _display_path(snapshot_path, root),
        "profileHash": compute_profile_hash(profile),
    }


def load_profile_snapshot(
    snapshot_file: str,
    *,
    project_root: str | None = None,
    expected_hash: str = "",
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    path = Path(snapshot_file)
    if not path.is_absolute():
        path = root / path
    path = _ensure_within(path, root, "profile snapshot")
    if not path.is_file():
        raise ProfileError(f"profile snapshot missing: {path}")
    raw = read_text(path)
    actual_hash = md5_hex8(raw)
    if expected_hash and actual_hash != expected_hash:
        raise ProfileError(
            f"profile snapshot hash mismatch: "
            f"expected {expected_hash}, got {actual_hash}"
        )
    profile = json.loads(raw)
    _validate_profile_shape(profile)
    return profile


def _resolve_snapshot_dir(
    profile: dict[str, Any], project_root: Path
) -> Path:
    snapshot = profile.get("snapshot") or {}
    relative_dir = str(snapshot.get("relativeDir") or "").strip()
    if not relative_dir:
        raise ProfileError("snapshot.relativeDir missing")
    raw = Path(relative_dir)
    candidate = raw if raw.is_absolute() else project_root / raw
    return _ensure_within(candidate, project_root.resolve(), "snapshot.relativeDir")


def _stable_profile_json(profile: dict[str, Any]) -> str:
    return json.dumps(profile, indent=2, sort_keys=True) + "\n"


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _ensure_within(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ProfileError(f"{label} escapes allowed root: {path}") from exc
    return resolved
