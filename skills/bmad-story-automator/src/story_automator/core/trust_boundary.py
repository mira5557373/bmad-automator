"""Trust boundary enforcement for the factory's evidence-integrity model.

Spec §7: collectors run on the orchestrator host, never by the generation
child.  Evidence + gate files are written outside the child's working tree
and hash-chained into audit.  The child's self-reports are unverified
hints, never evidence (Blind Hunter principle).
"""
from __future__ import annotations

import os

__all__ = [
    "TrustBoundaryError",
    "is_child_session",
    "assert_host_context",
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
