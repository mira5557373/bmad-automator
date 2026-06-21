"""Profile versioning — semver split for auto-tuning.

Splits profile.version into {breaking, feature} so auto-tuning can
bump the feature version without forcing re-evaluation of existing
gate files. Breaking changes (matrix thresholds, categories, rules)
force re-gates; feature changes (timeouts, cost_tier) do not.
"""
from __future__ import annotations

import copy
import dataclasses
import json
from typing import Any

from .utils import md5_hex8


@dataclasses.dataclass(frozen=True)
class ProfileVersion:
    breaking: int = 1
    feature: int = 0


def parse_profile_version(profile: dict[str, Any]) -> ProfileVersion:
    """Parse version from profile, handling both int and dict formats."""
    version = profile.get("version")
    if isinstance(version, dict):
        return ProfileVersion(
            breaking=int(version.get("breaking", 1)),
            feature=int(version.get("feature", 0)),
        )
    if isinstance(version, int) and not isinstance(version, bool):
        return ProfileVersion(breaking=version, feature=0)
    return ProfileVersion()


def format_profile_version(pv: ProfileVersion) -> dict[str, int]:
    """Serialize a ProfileVersion to a dict."""
    return {"breaking": pv.breaking, "feature": pv.feature}


def has_semver_profile(profile: dict[str, Any]) -> bool:
    """True if the profile uses the dict version format."""
    return isinstance(profile.get("version"), dict)


def bump_profile_version(
    profile: dict[str, Any],
    change_type: str,
) -> dict[str, Any]:
    """Return a copy of the profile with a bumped version.

    change_type="feature" bumps the feature version.
    change_type="breaking" bumps breaking and resets feature to 0.
    """
    if change_type not in ("feature", "breaking"):
        raise ValueError(
            f"change_type must be 'feature' or 'breaking', got {change_type!r}"
        )
    result = copy.deepcopy(profile)
    pv = parse_profile_version(result)
    if change_type == "breaking":
        new_pv = ProfileVersion(breaking=pv.breaking + 1, feature=0)
    else:
        new_pv = ProfileVersion(breaking=pv.breaking, feature=pv.feature + 1)
    result["version"] = format_profile_version(new_pv)
    return result


BREAKING_FIELDS: frozenset[str] = frozenset({
    "matrix", "categories", "categories_na", "rules",
    "invariants", "toolchain", "forbidden_until",
})

FEATURE_FIELDS: frozenset[str] = frozenset({
    "timeouts", "cost_tier", "snapshot", "seed_template",
})


def is_breaking_change(
    old_profile: dict[str, Any],
    new_profile: dict[str, Any],
) -> bool:
    """True if any breaking-sensitive field changed."""
    for field in BREAKING_FIELDS:
        old_val = json.dumps(old_profile.get(field), sort_keys=True)
        new_val = json.dumps(new_profile.get(field), sort_keys=True)
        if old_val != new_val:
            return True
    return False


def classify_changes(
    old_profile: dict[str, Any],
    new_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """List changed fields with their breaking/feature classification."""
    changes: list[dict[str, Any]] = []
    for field in sorted(BREAKING_FIELDS | FEATURE_FIELDS):
        old_val = json.dumps(old_profile.get(field), sort_keys=True)
        new_val = json.dumps(new_profile.get(field), sort_keys=True)
        if old_val != new_val:
            change_type = "breaking" if field in BREAKING_FIELDS else "feature"
            changes.append({
                "field": field,
                "change_type": change_type,
                "old_value": old_profile.get(field),
                "new_value": new_profile.get(field),
            })
    return changes


def compute_breaking_hash(profile: dict[str, Any]) -> str:
    """Hash only breaking-sensitive fields for gate reuse comparison."""
    breaking_data = {
        field: profile.get(field) for field in sorted(BREAKING_FIELDS)
    }
    canonical = json.dumps(breaking_data, sort_keys=True, separators=(",", ":"))
    return md5_hex8(canonical)
