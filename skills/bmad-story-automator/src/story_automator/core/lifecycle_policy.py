"""Lifecycle policy data model + loader + validators (W0-M01).

Sibling module to ``core/runtime_policy.py`` (which governs the existing
sprint-engine policy). This module owns the *macro lifecycle* policy: the
phase-DAG of nodes (B1-brief, B2-prd, ...), the entry-mode router map, and
the structural + closed-world + cycle validators that gate any attempt to
load it.

Pure-Python, stdlib-only. The scheduler in ``lifecycle_scheduler.py`` consumes
the ``Policy`` dataclass; the per-run state in ``lifecycle_status.py``
references the canonical JSON form (``canonical_policy_json``) to fingerprint
the policy a status file was created against.
"""

from __future__ import annotations

__all__ = ["PolicyError", "load_policy"]


class PolicyError(ValueError):
    """Raised on any structural, closed-world, or DAG-cycle violation.

    Subclass of ValueError so callers handling generic ValueError continue
    to catch it, but a typed exception keeps the observability NFR honest
    (later milestones can classify by type rather than message text).
    """


def load_policy(json_text: str):  # type: ignore[no-untyped-def]
    """Parse + validate a lifecycle policy. Implementation lands in Task 2."""
    raise NotImplementedError
