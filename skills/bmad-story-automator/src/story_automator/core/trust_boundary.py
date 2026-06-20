"""Trust boundary enforcement for the factory's evidence-integrity model.

Spec §7: collectors run on the orchestrator host, never by the generation
child.  Evidence + gate files are written outside the child's working tree
and hash-chained into audit.  The child's self-reports are unverified
hints, never evidence (Blind Hunter principle).
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "TrustBoundaryError",
    "is_child_session",
    "assert_host_context",
    "CHILD_STRIPPED_VARS",
    "CHILD_FORCED_VARS",
    "sandbox_env",
    "verify_sandbox_env",
    "sandbox_tmux_env_args",
    "is_path_under",
    "validate_evidence_path_isolation",
    "resolve_host_evidence_dir",
]

_CHILD_ENV_VAR = "STORY_AUTOMATOR_CHILD"
_TRUTHY_VALUES = frozenset({"true", "1", "yes"})


class TrustBoundaryError(RuntimeError):
    """Raised when a trust-boundary-protected operation is attempted
    from a child session (generation agent)."""


def is_child_session(env: dict[str, str] | None = None) -> bool:
    """Return True if the current process is a generation child session."""
    source = env if env is not None else os.environ
    return source.get(_CHILD_ENV_VAR, "").strip().lower() in _TRUTHY_VALUES


def assert_host_context(
    operation: str = "",
    *,
    env: dict[str, str] | None = None,
) -> None:
    """Raise TrustBoundaryError if called from a child session.

    Every security-critical operation (evidence persistence, collector
    execution) calls this guard before proceeding.
    """
    if is_child_session(env):
        label = f": {operation}" if operation else ""
        raise TrustBoundaryError(
            f"trust boundary violation{label} — "
            f"operation requires host context but {_CHILD_ENV_VAR} is set"
        )


CHILD_STRIPPED_VARS: frozenset[str] = frozenset({
    "BMAD_AUDIT_KEY",
    "CLAUDECODE",
    "BASH_ENV",
})

CHILD_FORCED_VARS: dict[str, str] = {
    "STORY_AUTOMATOR_CHILD": "true",
}


def sandbox_env(
    *,
    agent: str = "",
    extras: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a sanitized env dict for a child generation session.

    Strips security-sensitive vars, forces the child-session flag,
    and optionally sets the AI_AGENT identifier.
    """
    env = dict(os.environ)
    for var in CHILD_STRIPPED_VARS:
        env.pop(var, None)
    env.update(CHILD_FORCED_VARS)
    if agent:
        env["AI_AGENT"] = agent
    if extras:
        env.update(extras)
    return env


def verify_sandbox_env(env: dict[str, str]) -> tuple[bool, list[str]]:
    """Validate that a child env meets sandbox requirements.

    Returns (ok, list_of_violations).
    """
    violations: list[str] = []
    for var in CHILD_STRIPPED_VARS:
        if env.get(var, ""):
            violations.append(f"security-sensitive var {var} not stripped")
    for var, expected in CHILD_FORCED_VARS.items():
        if env.get(var) != expected:
            violations.append(f"required var {var}={expected!r} not set")
    return (len(violations) == 0, violations)


def sandbox_tmux_env_args(agent: str = "") -> list[str]:
    """Return tmux ``-e`` flag pairs for a sandboxed child session.

    Deterministic order: forced vars, then agent (if set), then
    stripped vars (alphabetical).  Matches the env semantics of
    ``tmux new-session -e KEY=VALUE``.
    """
    args: list[str] = []
    for var in sorted(CHILD_FORCED_VARS):
        args.extend(["-e", f"{var}={CHILD_FORCED_VARS[var]}"])
    if agent:
        args.extend(["-e", f"AI_AGENT={agent}"])
    for var in sorted(CHILD_STRIPPED_VARS):
        args.extend(["-e", f"{var}="])
    return args


def is_path_under(parent: Path, child: Path) -> bool:
    """Return True if child path is inside (or equal to) parent, resolving symlinks."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_evidence_path_isolation(
    evidence_path: Path,
    child_working_tree: Path,
) -> tuple[bool, str]:
    """Validate that evidence_path is NOT under the child's working tree.

    §7: evidence + gate files must be written outside the child's tmux
    working tree so the generation agent cannot tamper with them.
    """
    if is_path_under(child_working_tree, evidence_path):
        return (
            False,
            f"evidence path {evidence_path} is under child working tree "
            f"{child_working_tree}",
        )
    return (True, "")


def resolve_host_evidence_dir(project_root: str | Path) -> Path:
    """Return the canonical host-controlled gate artifact directory."""
    return Path(project_root).resolve() / "_bmad" / "gate"
