"""Bridge between Product Profile and BMAD customize.toml (§5).

Extracts profile invariants, rules, and constraints into dicts
suitable for injection into generation agents via BMAD's
customize.toml 3-layer merge + persistent_facts + activation
prepend/append — no fork of BMAD required.
"""
from __future__ import annotations

from typing import Any

from .product_profile import compute_profile_hash


def profile_customize_facts(profile: dict[str, Any]) -> dict[str, Any]:
    """Build persistent_facts for BMAD customize.toml 3-layer merge."""
    facts: dict[str, Any] = {
        "profile_id": profile.get("id", ""),
        "profile_version": profile.get("version", 1),
        "profile_hash": compute_profile_hash(profile),
    }
    invariants = profile.get("invariants") or {}
    if invariants.get("registry_file"):
        facts["invariants_registry"] = invariants["registry_file"]

    forbidden = profile.get("forbidden_until") or {}
    if forbidden:
        facts["forbidden_adrs"] = sorted(forbidden.keys())
        facts["forbidden_patterns"] = {
            adr: patterns for adr, patterns in sorted(forbidden.items())
        }

    rules = profile.get("rules") or {}
    if rules:
        facts["gate_rules"] = {
            cat: dict(body) for cat, body in rules.items()
            if isinstance(body, dict)
        }

    categories_na = profile.get("categories_na") or []
    if categories_na:
        facts["categories_na"] = list(categories_na)

    return facts


def profile_activation_blocks(profile: dict[str, Any]) -> dict[str, str]:
    """Generate activation prepend/append content for BMAD agents.

    Returns {"prepend": str, "append": str} for customize.toml injection.
    """
    lines: list[str] = []
    profile_id = profile.get("id", "unknown")
    lines.append(f"Product Profile: {profile_id} v{profile.get('version', 1)}")

    forbidden = profile.get("forbidden_until") or {}
    if forbidden:
        lines.append("Blocked ADRs/DGs: " + ", ".join(sorted(forbidden)))

    invariants = profile.get("invariants") or {}
    registry = invariants.get("registry_file", "")
    if registry:
        lines.append(f"Invariant registry: {registry}")

    categories_na = profile.get("categories_na") or []
    if categories_na:
        lines.append(f"N/A categories: {', '.join(categories_na)}")

    return {
        "prepend": "\n".join(lines) if lines else "",
        "append": "",
    }
