"""Profile versioning — semver split for auto-tuning.

Splits profile.version into {breaking, feature} so auto-tuning can
bump the feature version without forcing re-evaluation of existing
gate files. Breaking changes (matrix thresholds, categories, rules)
force re-gates; feature changes (timeouts, cost_tier) do not.
"""
from __future__ import annotations

import copy
import dataclasses
from typing import Any


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
    result = copy.deepcopy(profile)
    pv = parse_profile_version(result)
    if change_type == "breaking":
        new_pv = ProfileVersion(breaking=pv.breaking + 1, feature=0)
    else:
        new_pv = ProfileVersion(breaking=pv.breaking, feature=pv.feature + 1)
    result["version"] = format_profile_version(new_pv)
    return result
