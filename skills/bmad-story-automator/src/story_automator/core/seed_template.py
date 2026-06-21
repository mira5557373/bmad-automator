"""Seed-template bundle loader — ref parsing, manifest schema, bundle resolution.

Spec references: §5 (template system), §16 M24 (golden seed-template bundle).
"""

from __future__ import annotations

import os

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
