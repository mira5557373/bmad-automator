"""Lifecycle DAG scheduler (W0-M01).

Pure-function topological scheduler over the macro-lifecycle DAG. Performs
no IO and no execution: callers pass a ``Policy``, a ``RunStatus``, an
``artifact_exists`` callable, the run ``mode``, and a ``max_concurrency`` cap,
and receive an ordered list of runnable node ids back. The phase-runner
(W0-M02) is responsible for actually invoking child agents and updating
node states.
"""

from __future__ import annotations

__all__ = ["SchedulerError", "runnable_nodes"]


class SchedulerError(RuntimeError):
    """Raised on scheduler-internal invariants violations (e.g. a topo sort
    over an already-validated DAG that somehow can't make progress).

    Policy-level errors surface as ``PolicyError``; this is the residual
    category for "validated input still doesn't schedule" — almost always
    a bug in the scheduler itself.
    """


def runnable_nodes(  # type: ignore[no-untyped-def]
    policy,
    status,
    *,
    artifact_exists,
    max_concurrency=1,
):
    """Return the runnable-node id list. Implementation lands in Task 11."""
    raise NotImplementedError
