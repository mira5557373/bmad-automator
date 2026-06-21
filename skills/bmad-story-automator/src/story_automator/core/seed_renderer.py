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


def list_template_files(
    manifest: dict, category: str | None = None
) -> list[dict[str, str]]:
    """List file entries from the manifest, optionally filtered by category.

    Each returned dict has ``src``, ``dst``, ``on_conflict``, ``category``.
    Raises `SeedRenderError` if *category* is given but not found.
    """
    categories = manifest.get("categories", {})

    if category is not None and category not in categories:
        raise SeedRenderError(f"unknown category: {category!r}")

    result: list[dict[str, str]] = []
    for cat_name, cat in categories.items():
        if category is not None and cat_name != category:
            continue
        for entry in cat.get("files", []):
            result.append({
                "src": entry["src"],
                "dst": entry["dst"],
                "on_conflict": entry.get("on_conflict", "skip"),
                "category": cat_name,
            })

    return result
