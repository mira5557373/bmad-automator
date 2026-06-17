"""Lifecycle phase runner (W0-M02).

Single-turn driver: ``run_next_node`` picks one runnable node off the
scheduler, executes it (spawning a child agent via the existing tmux
runtime OR delegating to the sprint orchestrator on track=bmm+phase=4),
verifies the output, and transitions the run state atomically. The caller
owns the outer loop. Every side-effect goes through an injectable callable
with a stdlib default — spawn, monitor, sprint-delegate, verifier dispatch,
emitter, clock — so unit tests run without tmux, Claude, or the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from story_automator.core.lifecycle_status import (
    NodeState,
    RunStatus,
    save_status,
)

__all__ = [
    "RunResult",
    "RunnerError",
    "run_next_node",
]

logger = logging.getLogger(__name__)


class RunnerError(RuntimeError):
    """Raised on runner-internal invariant violations."""


@dataclass(kw_only=True)
class RunResult:
    """One-node outcome returned by ``run_next_node``."""

    node_id: str
    final_state: str
    verified: bool
    reason: str
    duration_s: float


def _transition_node(
    status: RunStatus,
    status_path: Path,
    node_id: str,
    new_state: NodeState,
    *,
    started_at: str = "",
    completed_at: str = "",
    last_error: str = "",
    gate_decision: str | None = None,
    gate_notes: str = "",
) -> None:
    """Mutate ``status.nodes[node_id]`` to ``new_state`` + persist atomically."""
    run = status.nodes.get(node_id)
    if run is None:
        raise RunnerError(
            f"transition target node {node_id!r} missing from status.nodes; "
            f"refusing to silently insert a node not present in the policy "
            f"this status file was created against"
        )
    run.state = new_state
    if started_at:
        run.started_at = started_at
    if completed_at:
        run.completed_at = completed_at
    if last_error:
        run.last_error = last_error
    if gate_decision is not None:
        run.gate_decision = gate_decision
    if gate_notes:
        run.gate_notes = gate_notes
    save_status(status_path, status)


def run_next_node(
    policy,
    status: RunStatus,
    *,
    project_root: str,
    status_path: Path,
    **_kwargs: Any,
) -> RunResult | None:
    """Stub — full implementation lands in Tasks 7+."""
    raise NotImplementedError("run_next_node lands in Task 7+")
