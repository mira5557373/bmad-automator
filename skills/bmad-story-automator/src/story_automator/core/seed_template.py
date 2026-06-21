"""Seed-template bundle loader — ref parsing, manifest schema, bundle resolution.

Spec references: §5 (template system), §16 M24 (golden seed-template bundle).
"""

from __future__ import annotations

import os
from pathlib import Path

from story_automator.core.runtime_layout import bundled_story_skill_root

TEMPLATE_SCHEMA_VERSION = 1


class SeedTemplateError(ValueError):
    """Raised on invalid template ref, manifest, or bundle resolution failure."""


def resolve_template_ref(ref: str) -> tuple[str, str]:
    """Parse ``"id@version"`` into ``(template_id, version)``.

    Returns ``("", "")`` for empty/whitespace-only refs.
    Raises `SeedTemplateError` on path traversal, slashes, or multiple ``@``.
    """
    ref = ref.strip()
    if not ref:
        return ("", "")

    if ref.count("@") > 1:
        raise SeedTemplateError(f"invalid template ref (multiple '@'): {ref!r}")

    if "@" in ref:
        template_id, version = ref.split("@", 1)
    else:
        template_id, version = ref, ""

    if ".." in template_id or "/" in template_id or os.sep in template_id:
        raise SeedTemplateError(f"invalid template ref (path traversal): {ref!r}")

    return (template_id, version)


VALID_CONFLICT_MODES = frozenset({"skip", "overwrite"})


def validate_manifest(manifest: dict) -> None:
    """Validate a template manifest dict against the schema.

    Raises `SeedTemplateError` on any structural or semantic violation.
    """
    if manifest.get("schema_version") != TEMPLATE_SCHEMA_VERSION:
        raise SeedTemplateError(
            f"unsupported schema_version: {manifest.get('schema_version')!r} "
            f"(expected {TEMPLATE_SCHEMA_VERSION})"
        )

    for field in ("template_id", "template_version"):
        val = manifest.get(field)
        if not isinstance(val, str) or not val:
            raise SeedTemplateError(f"{field} must be a non-empty string")

    categories = manifest.get("categories")
    if not isinstance(categories, dict) or not categories:
        raise SeedTemplateError("categories must be a non-empty dict")

    seen_dst: set[str] = set()

    for cat_name, cat in categories.items():
        if not isinstance(cat.get("description"), str):
            raise SeedTemplateError(
                f"category {cat_name!r}: description must be a string"
            )
        files = cat.get("files")
        if not isinstance(files, list):
            raise SeedTemplateError(
                f"category {cat_name!r}: files must be a list"
            )
        for entry in files:
            for key in ("src", "dst"):
                if not isinstance(entry.get(key), str) or not entry[key]:
                    raise SeedTemplateError(
                        f"category {cat_name!r}: file entry missing {key}"
                    )
            conflict = entry.get("on_conflict")
            if conflict is not None and conflict not in VALID_CONFLICT_MODES:
                raise SeedTemplateError(
                    f"category {cat_name!r}: invalid on_conflict {conflict!r}"
                )
            dst = entry["dst"]
            if dst in seen_dst:
                raise SeedTemplateError(f"duplicate dst path: {dst!r}")
            seen_dst.add(dst)

    variables = manifest.get("variables")
    if variables is not None:
        if not isinstance(variables, dict):
            raise SeedTemplateError("variables must be a dict")
        for var_name, var_def in variables.items():
            if not var_name.isidentifier():
                raise SeedTemplateError(
                    f"variable name {var_name!r} is not a valid Python identifier"
                )
            if not isinstance(var_def, dict):
                raise SeedTemplateError(
                    f"variable {var_name!r}: definition must be a dict"
                )
            req = var_def.get("required")
            if req is not None and not isinstance(req, bool):
                raise SeedTemplateError(
                    f"variable {var_name!r}: required must be a bool"
                )


_TEMPLATES_DIR = "data/templates"


def resolve_bundle_dir(
    template_id: str, project_root: str | None = None
) -> Path:
    """Resolve the bundle directory for a template id.

    Returns the absolute path to ``data/templates/<template_id>/`` under
    the bundled skill root.  Raises `SeedTemplateError` if the directory
    does not exist or the id contains path traversal.
    """
    if ".." in template_id or "/" in template_id or os.sep in template_id:
        raise SeedTemplateError(
            f"invalid template_id (path traversal): {template_id!r}"
        )

    skill_root = bundled_story_skill_root(project_root)
    bundle = (skill_root / _TEMPLATES_DIR / template_id).resolve()

    if not bundle.is_dir():
        raise SeedTemplateError(
            f"template bundle not found: {bundle}"
        )

    return bundle
