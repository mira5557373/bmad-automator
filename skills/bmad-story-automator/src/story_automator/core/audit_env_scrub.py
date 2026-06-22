"""Trust-boundary scrub helper for the BMAD_AUDIT_KEY env var (D-04).

This sibling module owns the canonical implementation of
``scrub_env_for_subprocess`` and the closed allowlist of env keys it strips.
``core/audit.py`` re-exports the helper so the historical import path
``from story_automator.core.audit import scrub_env_for_subprocess`` keeps
working for the ~25 existing call sites without modification.

Why a separate module? ``audit.py`` is approaching its 500-LOC soft budget,
and the AST regression test in ``tests/test_audit_regression.py`` must skip
the *implementation* file of the helper. Pinning that skip to a structural
``ast.FunctionDef`` lookup (rather than a hard-coded ``audit.py`` filename)
makes the invariant rename-proof: split the helper across more files, or
rename the host module, and the AST scan still finds the correct skip
target automatically.
"""

from __future__ import annotations

import os
from typing import Mapping


__all__ = ["scrub_env_for_subprocess"]


# Closed allowlist of env keys to strip before spawning a child. Kept as a
# module-private frozenset so callers cannot mutate it at runtime. Widening
# this set is a security-policy change and must be done by editing this
# constant explicitly (not by re-binding it from outside).
_AUDIT_ENV_KEYS_TO_SCRUB: frozenset[str] = frozenset({"BMAD_AUDIT_KEY"})


def scrub_env_for_subprocess(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``env`` with audit-key entries removed (D-04).

    Pass this to ``subprocess.run`` / ``Popen`` ``env=`` so children cannot
    read or forge the audit chain. Idempotent. If ``env`` is None, copies
    ``os.environ``. The parent process is never mutated, so
    ``load_key_from_env()`` keeps working unchanged.
    """
    source = dict(os.environ if env is None else env)
    for key in _AUDIT_ENV_KEYS_TO_SCRUB:
        source.pop(key, None)
    return source
