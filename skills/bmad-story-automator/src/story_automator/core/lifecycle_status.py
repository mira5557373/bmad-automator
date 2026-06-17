"""Lifecycle per-run status + artifact registry (W0-M01).

Persists the macro-lifecycle run state to a JSON file (``lifecycle-status.json``
by convention; the spec writes ``.yaml`` but stdlib has no YAML and the
no-deps guardrail forbids PyYAML — JSON is the on-disk format). Reuses
``core.atomic_io.write_atomic_text`` for crash-safe writes.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["NodeState", "PolicyMismatch"]


class NodeState(str, Enum):
    """States a node may occupy during a lifecycle run.

    W0-M01 scheduler only emits PENDING -> COMPLETE transitions. The other
    values are accepted on load so later milestones (phase-runner, approval
    gate) can drive them without a schema change.
    """

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class PolicyMismatch(ValueError):
    """Raised when a status file's recorded policy_hash differs from the
    policy it's being loaded against.

    A run that resumes against a changed policy could silently re-execute
    or skip nodes; surfacing this as a typed error forces the operator
    to either revert the policy or start a fresh run.
    """
