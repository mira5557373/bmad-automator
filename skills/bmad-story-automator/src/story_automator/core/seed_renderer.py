"""Seed-template renderer — variable resolution, content rendering, instantiation.

Spec references: §5 (template system), §16 M24 (golden seed-template bundle).
"""

from __future__ import annotations

import os
import string
from dataclasses import dataclass, field
from pathlib import Path


class SeedRenderError(ValueError):
    """Raised on rendering or instantiation failure."""


def resolve_variables(manifest: dict, provided: dict[str, str]) -> dict[str, str]:
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


def list_template_files(manifest: dict, category: str | None = None) -> list[dict[str, str]]:
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
            result.append(
                {
                    "src": entry["src"],
                    "dst": entry["dst"],
                    "on_conflict": entry.get("on_conflict", "skip"),
                    "category": cat_name,
                }
            )

    return result


def render_template_content(content: str, variables: dict[str, str]) -> str:
    """Render ``$variable`` / ``${variable}`` placeholders via safe_substitute."""
    return string.Template(content).safe_substitute(variables)


@dataclass
class InstantiationResult:
    """Tracks the outcome of template instantiation."""

    written: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def instantiate_template(
    bundle_dir: Path,
    manifest: dict,
    target_dir: Path,
    variables: dict[str, str],
    *,
    category: str | None = None,
) -> InstantiationResult:
    """Instantiate template files from *bundle_dir* into *target_dir*.

    Resolves variables, reads each ``src`` template, renders, and writes
    to ``target_dir / dst``.  Returns an `InstantiationResult` tracking
    written, skipped, and errored files.
    """
    resolved = resolve_variables(manifest, variables)
    files = list_template_files(manifest, category=category)
    result = InstantiationResult()
    resolved_target = target_dir.resolve()
    resolved_bundle = bundle_dir.resolve()

    for entry in files:
        src_path = (bundle_dir / entry["src"]).resolve()
        dst_rel = entry["dst"].replace("/", os.sep)
        dst_path = (target_dir / dst_rel).resolve()

        try:
            src_path.relative_to(resolved_bundle)
        except ValueError:
            raise SeedRenderError(f"src path escapes bundle dir: {entry['src']!r}") from None

        try:
            dst_path.relative_to(resolved_target)
        except ValueError:
            raise SeedRenderError(f"dst path escapes target dir: {entry['dst']!r}") from None

        if not src_path.is_file():
            result.errors.append(f"src not found: {entry['src']}")
            continue

        if dst_path.exists() and entry["on_conflict"] == "skip":
            result.skipped.append(str(dst_path))
            continue

        content = src_path.read_text(encoding="utf-8")
        rendered = render_template_content(content, resolved)

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_text(rendered, encoding="utf-8")
        result.written.append(str(dst_path))

    return result
