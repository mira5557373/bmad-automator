"""Lifecycle DAG scheduler (W0-M01).

Pure-function topological scheduler over the macro-lifecycle DAG. Performs
no IO and no execution: callers pass a ``Policy``, a ``RunStatus``, an
``artifact_exists`` callable, the run ``mode``, and a ``max_concurrency`` cap,
and receive an ordered list of runnable node ids back. The phase-runner
(W0-M02) is responsible for actually invoking child agents and updating
node states.
"""

from __future__ import annotations

from collections.abc import Callable

from story_automator.core.lifecycle_policy import NodeDef, Policy
from story_automator.core.lifecycle_status import RunStatus

__all__ = ["SchedulerError", "runnable_nodes", "topological_order"]

_VALID_MODES: frozenset[str] = frozenset({"greenfield", "brownfield"})


class SchedulerError(RuntimeError):
    """Raised on scheduler-internal invariant violations."""


def _active_nodes(policy: Policy, mode: str) -> dict[str, NodeDef]:
    """Restrict the DAG to nodes whose ``modes`` includes ``mode``. Out-of-
    mode nodes are filtered out entirely; their existence as deps of
    in-mode nodes is invisible (treated as already-satisfied)."""

    if mode not in _VALID_MODES:
        raise SchedulerError(
            f"mode {mode!r} is not one of {sorted(_VALID_MODES)!r}"
        )
    return {
        node_id: node
        for node_id, node in policy.nodes.items()
        if mode in node.modes
    }


def topological_order(policy: Policy, *, mode: str) -> list[str]:
    """Return all in-mode node ids in a deterministic topological order.

    Uses Kahn's algorithm with lexicographic tie-breaking — when multiple
    nodes have in-degree zero at the same time, they're emitted in
    sorted(node_id) order. The policy is already known-acyclic
    (validated at load time), so failure to drain the queue is a
    scheduler-internal bug, not a policy problem — raise SchedulerError.
    """

    active = _active_nodes(policy, mode)
    in_degree: dict[str, int] = {node_id: 0 for node_id in active}
    for node in active.values():
        for dep in node.deps:
            if dep in active:
                in_degree[node.id] = in_degree[node.id] + 1

    queue: list[str] = sorted(n for n, d in in_degree.items() if d == 0)
    order: list[str] = []
    while queue:
        node_id = queue.pop(0)
        order.append(node_id)
        for candidate in active.values():
            if (
                node_id in candidate.deps
                and candidate.id not in order
                and candidate.id not in queue
            ):
                in_degree[candidate.id] -= 1
                if in_degree[candidate.id] == 0:
                    queue.append(candidate.id)
                    queue.sort()

    if len(order) != len(active):
        raise SchedulerError(
            f"topological sort drained only {len(order)}/{len(active)} nodes; "
            f"residual: {sorted(set(active) - set(order))!r}"
        )
    return order


def runnable_nodes(
    policy: Policy,
    status: RunStatus,
    *,
    artifact_exists: Callable[[str], bool],
    max_concurrency: int = 1,
) -> list[str]:
    """Return runnable nodes. Mode is read from ``status.mode``. Full
    implementation lands in Task 11."""

    raise NotImplementedError
