"""Invariant registry loader and validator (§6.4).

Loads DG/ADR invariant entries from YAML files referenced by
profile.invariants.registry_file. Uses a minimal YAML subset
parser (stdlib only) for the flat list-of-dicts format.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from .gate_schema import GateSchemaError, validate_invariant_entry

__all__ = [
    "load_yaml_registry",
    "validate_registry",
    "load_invariant_registry",
]

_log = logging.getLogger(__name__)


def load_yaml_registry(path: str) -> list[dict[str, str]]:
    """Parse a simple YAML invariant registry file.

    Supports: flat list of key-value dicts, comments, blank lines.
    Each entry starts with ``- key: value`` and continues with
    ``  key: value`` lines.
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in lines:
        stripped = raw.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        if stripped.startswith("- "):
            if current is not None:
                entries.append(current)
            key, _, value = stripped[2:].partition(":")
            current = {key.strip(): value.strip()}
        elif stripped.startswith("  ") and current is not None:
            key, _, value = stripped.strip().partition(":")
            current[key.strip()] = value.strip()
    if current is not None:
        entries.append(current)
    return entries


def validate_registry(
    entries: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Validate each registry entry against gate_schema rules."""
    errors: list[str] = []
    for i, entry in enumerate(entries):
        try:
            validate_invariant_entry(entry)
        except GateSchemaError as exc:
            entry_id = entry.get("id", f"entry[{i}]")
            errors.append(f"{entry_id}: {exc}")
    return len(errors) == 0, errors


def load_invariant_registry(
    profile: dict[str, Any],
    base_dir: str,
) -> list[dict[str, str]]:
    """Load invariant registry from profile-referenced file.

    Resolves profile.invariants.registry_file relative to base_dir
    (unless it's an absolute path). Returns empty list if no file
    is configured or if the file cannot be read.
    """
    invariants = profile.get("invariants") or {}
    registry_file = invariants.get("registry_file")
    if not registry_file:
        return []
    if not os.path.isabs(registry_file):
        registry_file = os.path.join(base_dir, registry_file)
    entries = load_yaml_registry(registry_file)
    ok, errors = validate_registry(entries)
    if not ok:
        for err in errors:
            _log.warning("invariant registry validation: %s", err)
        valid: list[dict[str, str]] = []
        for entry in entries:
            try:
                validate_invariant_entry(entry)
                valid.append(entry)
            except GateSchemaError:
                pass
        return valid
    return entries
