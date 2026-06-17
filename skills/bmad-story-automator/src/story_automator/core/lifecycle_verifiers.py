"""Lifecycle phase-verifier registry (W0-M02).

Sibling module to ``core/success_verifiers.py``. That module governs the
existing *sprint-track* verifiers and is **not modified by W0-M02**. This
module adds a parallel registry for the *macro-lifecycle* verifiers
referenced by ``NodeDef.verifier`` strings in lifecycle policy JSON:
``artifact_exists``, ``structural_complete``, and ``validator_skill``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from story_automator.core.lifecycle_policy import NodeDef

__all__ = [
    "LIFECYCLE_VERIFIERS",
    "VerifierError",
    "VerifierFn",
    "artifact_exists",
    "run_lifecycle_verifier",
    "structural_complete",
    "validator_skill",
]


class VerifierError(ValueError):
    """Raised when a verifier name is unknown or its arguments are invalid."""


VerifierFn = Callable[..., dict[str, Any]]


def artifact_exists(
    *,
    node: NodeDef,
    project_root: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    """The node's ``output_artifact`` is present (and non-empty if a dir)."""
    root = Path(project_root)
    artifact_path = node.output_artifact
    full = root / artifact_path
    payload: dict[str, Any] = {
        "verified": False,
        "path": artifact_path,
        "verifier": "artifact_exists",
    }
    if artifact_path.endswith("/"):
        if not full.is_dir():
            payload["reason"] = "artifact_missing"
            return payload
        any_file = any(p.is_file() for p in full.rglob("*"))
        if not any_file:
            payload["reason"] = "artifact_empty"
            return payload
        payload["verified"] = True
        return payload
    if not full.is_file():
        payload["reason"] = "artifact_missing"
        return payload
    if full.stat().st_size == 0:
        payload["reason"] = "artifact_empty"
        return payload
    payload["verified"] = True
    return payload


def structural_complete(
    *,
    node: NodeDef,
    project_root: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Artifact exists + (for ``.md`` outputs) has parseable frontmatter."""
    base = artifact_exists(node=node, project_root=project_root)
    base["verifier"] = "structural_complete"
    if not base["verified"]:
        return base
    full = Path(project_root) / node.output_artifact
    if node.output_artifact.endswith("/"):
        return base
    if full.suffix.lower() != ".md":
        return base
    from story_automator.core.frontmatter import parse_simple_frontmatter

    text = full.read_text(encoding="utf-8")
    if not text.startswith("---"):
        base["verified"] = False
        base["reason"] = "frontmatter_missing"
        return base
    fields = parse_simple_frontmatter(text)
    if not fields:
        base["verified"] = False
        base["reason"] = "frontmatter_unparseable"
        return base
    base["frontmatter_keys"] = sorted(fields.keys())
    return base


def validator_skill(
    *,
    node: NodeDef,
    project_root: str,
    validator_dispatch: Callable[..., dict[str, Any]] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Defer to ``node.validator_skill`` via the injected dispatch callable."""
    if not node.validator_skill:
        return {
            "verified": False,
            "reason": "validator_skill_not_configured",
            "verifier": "validator_skill",
        }
    if validator_dispatch is None:
        raise VerifierError(
            f"verifier 'validator_skill' for node {node.id!r} needs a "
            f"`validator_dispatch` callable; pass one from the runner"
        )
    result = validator_dispatch(
        validator_skill=node.validator_skill,
        node=node,
        project_root=project_root,
    )
    if not isinstance(result, dict):
        raise VerifierError(
            f"validator_dispatch for {node.validator_skill!r} returned "
            f"{type(result).__name__}, expected dict"
        )
    result.setdefault("verifier", "validator_skill")
    return result


LIFECYCLE_VERIFIERS: dict[str, VerifierFn] = {
    "artifact_exists": artifact_exists,
    "structural_complete": structural_complete,
    "validator_skill": validator_skill,
}


def run_lifecycle_verifier(
    name: str,
    *,
    node: NodeDef,
    project_root: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Dispatch ``name`` to the registry. Raises ``VerifierError`` on unknown
    names. Each verifier returns a ``{"verified": bool, ...}`` dict — never
    raises for "verifier said no"; only raises for malformed inputs."""
    verifier = LIFECYCLE_VERIFIERS.get(name)
    if verifier is None:
        raise VerifierError(
            f"unknown lifecycle verifier {name!r}; "
            f"known: {sorted(LIFECYCLE_VERIFIERS)!r}"
        )
    return verifier(node=node, project_root=project_root, **kwargs)
