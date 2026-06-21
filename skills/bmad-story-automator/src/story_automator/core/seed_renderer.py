"""Seed-template renderer — variable resolution, content rendering, instantiation.

Spec references: §5 (template system), §16 M24 (golden seed-template bundle).
"""

from __future__ import annotations


class SeedRenderError(ValueError):
    """Raised on rendering or instantiation failure."""


def resolve_variables(
    manifest: dict, provided: dict[str, str]
) -> dict[str, str]:
    """Merge *provided* variables with manifest defaults.

    Raises `SeedRenderError` if a required variable is missing.
    Extra keys in *provided* are kept for forward-compat.
    """
    result = dict(provided)
    variables = manifest.get("variables") or {}

    for var_name, var_def in variables.items():
        if var_name in result:
            continue
        default = var_def.get("default")
        if default is not None:
            result[var_name] = default
        elif var_def.get("required"):
            raise SeedRenderError(f"required variable {var_name!r} not provided")

    return result
