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
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from story_automator.core.common import iso_now
from story_automator.core.lifecycle_events import (
    LifecyclePhaseCompleted,
    LifecyclePhaseFailed,
    LifecyclePhaseStarted,
)
from story_automator.core.lifecycle_policy import NodeDef, Policy
from story_automator.core.lifecycle_scheduler import runnable_nodes
from story_automator.core.lifecycle_status import (
    NodeState,
    RunStatus,
    save_status,
)
from story_automator.core.run_identity import current_run_id

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


_TMUX_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def _session_name_for_node(node: NodeDef, run_id: str) -> str:
    """Build a tmux-safe session name for ``node``.

    tmux rejects ``.``, ``:``, and whitespace in session names; the policy
    loader only enforces that node ids are non-empty strings, so any node
    id outside ``[A-Za-z0-9_-]`` must be sanitized here or the spawn will
    fail with an opaque "duplicate session" or "bad name" error.
    """
    safe_node = _TMUX_NAME_UNSAFE.sub("-", node.id)
    base = f"lifecycle-{safe_node}"
    if run_id:
        base += f"-{run_id[-12:]}"
    return base[:160]


def _is_sprint_delegate_node(node: NodeDef) -> bool:
    return node.track == "bmm" and node.phase == 4


def _default_verifier_dispatch(
    name: str,
    *,
    node: NodeDef,
    project_root: str,
    **kwargs: Any,
) -> dict[str, Any]:
    from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

    return run_lifecycle_verifier(name, node=node, project_root=project_root, **kwargs)


def _emit_safe(emitter: Any, event: Any) -> None:
    """Best-effort emit. A flaky sink must never break a run.

    Catches ``Exception`` (not just ``OSError``) because the emitter is an
    injected boundary — a malformed dataclass field (``TypeError``), an
    invalid JSON serialization (``ValueError``), or any other emitter-side
    bug must never abort the runner's state-transition path. ``BaseException``
    is intentionally not caught so ``KeyboardInterrupt`` / ``SystemExit``
    still propagate.
    """
    if emitter is None:
        return
    try:
        emitter.emit(event)
    except Exception as exc:  # noqa: BLE001 — emit boundary; see docstring
        logger.warning(
            "lifecycle telemetry emit failed for %s: %s: %s",
            type(event).__name__,
            type(exc).__name__,
            exc,
        )


def _duration(started_at: str, completed_at: str) -> float:
    """Best-effort ISO-8601 timestamp delta in seconds."""
    try:
        a = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        b = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds())
    except (TypeError, ValueError):
        return 0.0


def run_next_node(
    policy: Policy,
    status: RunStatus,
    *,
    project_root: str,
    status_path: Path,
    spawn_agent: Callable[..., tuple[str, int]] | None = None,
    monitor_session: Callable[[list[str]], int] | None = None,
    sprint_delegate: Callable[..., dict[str, Any]] | None = None,
    verifier_dispatch: Callable[..., dict[str, Any]] | None = None,
    validator_dispatch: Callable[..., dict[str, Any]] | None = None,
    emitter: Any = None,
    clock: Callable[[], str] = iso_now,
    artifact_exists: Callable[[str], bool] | None = None,
) -> RunResult | None:
    """Execute one runnable node end-to-end. Returns None if nothing is runnable."""
    if spawn_agent is None or monitor_session is None:
        raise RunnerError(
            "run_next_node requires both `spawn_agent` and `monitor_session` "
            "callables; production wiring passes the tmux defaults in the "
            "CLI layer (W0-M04)"
        )
    if artifact_exists is None:
        root_path = Path(project_root)

        def artifact_exists(p: str) -> bool:
            return (root_path / p).exists()

    candidates = runnable_nodes(
        policy,
        status,
        artifact_exists=artifact_exists,
        max_concurrency=1,
    )
    if not candidates:
        return None
    node_id = candidates[0]
    node = policy.nodes[node_id]

    # Precondition checks BEFORE persisting RUNNING — a raise here must not
    # leave a node stuck in RUNNING on disk with no live process.
    if _is_sprint_delegate_node(node) and sprint_delegate is None:
        raise RunnerError(
            f"node {node.id!r} (track=bmm phase=4) requires a "
            f"`sprint_delegate` callable; the production CLI wires "
            f"this in W0-M04. Pass a stub in tests."
        )

    status.nodes[node_id].attempts += 1
    started_at = clock()
    _transition_node(
        status,
        status_path,
        node_id,
        NodeState.RUNNING,
        started_at=started_at,
    )

    run_id = current_run_id(project_root)

    _emit_safe(
        emitter,
        LifecyclePhaseStarted(
            timestamp=started_at,
            run_id=run_id,
            node_id=node.id,
            phase=node.phase,
            track=node.track,
            skill=node.skill,
            agent_role=node.agent_role,
        ),
    )

    def _fail(reason: str, error_class: str, last_error: str) -> RunResult:
        completed_at = clock()
        _transition_node(
            status,
            status_path,
            node_id,
            NodeState.FAILED,
            completed_at=completed_at,
            last_error=last_error,
        )
        _emit_safe(
            emitter,
            LifecyclePhaseFailed(
                timestamp=completed_at,
                run_id=run_id,
                node_id=node.id,
                phase=node.phase,
                track=node.track,
                reason=reason,
                error_class=error_class,
                attempt=status.nodes[node_id].attempts,
            ),
        )
        return RunResult(
            node_id=node_id,
            final_state="failed",
            verified=False,
            reason=reason,
            duration_s=_duration(started_at, completed_at),
        )

    def _complete(gate_decision_str: str, terminal_state: NodeState) -> RunResult:
        completed_at = clock()
        _transition_node(
            status,
            status_path,
            node_id,
            terminal_state,
            completed_at=completed_at,
            gate_decision=None if terminal_state is NodeState.AWAITING_APPROVAL else "",
        )
        _emit_safe(
            emitter,
            LifecyclePhaseCompleted(
                timestamp=completed_at,
                run_id=run_id,
                node_id=node.id,
                phase=node.phase,
                track=node.track,
                duration_s=_duration(started_at, completed_at),
                gate_decision=gate_decision_str,
            ),
        )
        final_state = (
            "awaiting_approval" if terminal_state is NodeState.AWAITING_APPROVAL else "complete"
        )
        return RunResult(
            node_id=node_id,
            final_state=final_state,
            verified=True,
            reason="",
            duration_s=_duration(started_at, completed_at),
        )

    # --- phase-4 sprint-delegate branch ---
    if _is_sprint_delegate_node(node):
        # sprint_delegate-is-None precondition is enforced before the
        # RUNNING transition above; reaching here implies it is non-None.
        assert sprint_delegate is not None
        try:
            delegate_result = sprint_delegate(
                node=node,
                project_root=project_root,
                status=status,
                run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            return _fail(
                "delegate_raised",
                type(exc).__name__,
                f"delegate_raised: {type(exc).__name__}: {exc}",
            )
        if not isinstance(delegate_result, dict):
            return _fail(
                "delegate_invalid_result",
                "DelegateInvalidResult",
                f"sprint_delegate returned {type(delegate_result).__name__}, expected dict",
            )
        if bool(delegate_result.get("verified")):
            if node.gate == "human":
                return _complete("awaiting_approval", NodeState.AWAITING_APPROVAL)
            return _complete("auto_complete", NodeState.COMPLETE)
        reason = str(delegate_result.get("reason") or "delegate_rejected")
        return _fail(
            reason,
            "DelegateRejected",
            f"delegate_rejected: {reason}",
        )

    # --- spawn the child agent ---
    session = _session_name_for_node(node, run_id)
    command = f"# lifecycle: invoke skill {node.skill} for node {node.id}"
    agent = node.agent_role
    try:
        spawn_out, spawn_code = spawn_agent(session, command, agent, project_root)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "spawn_raised",
            type(exc).__name__,
            f"spawn_raised: {type(exc).__name__}: {exc}",
        )

    if spawn_code != 0:
        return _fail(
            "spawn_failed",
            "SpawnFailed",
            f"spawn_failed: exit={spawn_code}: {spawn_out.strip()}",
        )

    # --- monitor to terminal state ---
    monitor_args = [session, "--json", "--story-key", node_id]
    try:
        monitor_rc = monitor_session(monitor_args)
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "monitor_raised",
            type(exc).__name__,
            f"monitor_raised: {type(exc).__name__}: {exc}",
        )

    if monitor_rc != 0:
        return _fail(
            "monitor_nonzero",
            "MonitorNonzero",
            f"monitor_nonzero: rc={monitor_rc}",
        )

    # --- verifier dispatch ---
    dispatcher = verifier_dispatch or _default_verifier_dispatch
    try:
        verdict = dispatcher(
            node.verifier,
            node=node,
            project_root=project_root,
            validator_dispatch=validator_dispatch,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "verifier_raised",
            type(exc).__name__,
            f"verifier_raised: {type(exc).__name__}: {exc}",
        )
    if not isinstance(verdict, dict):
        return _fail(
            "verifier_invalid_result",
            "VerifierInvalidResult",
            f"verifier_dispatch for {node.verifier!r} returned "
            f"{type(verdict).__name__}, expected dict",
        )

    if not bool(verdict.get("verified")):
        reason = str(verdict.get("reason") or "verifier_rejected")
        return _fail(
            reason,
            "VerifierRejected",
            f"verifier_rejected: {reason}",
        )

    # --- gate handling: human → AWAITING_APPROVAL; auto → COMPLETE ---
    if node.gate == "human":
        return _complete("awaiting_approval", NodeState.AWAITING_APPROVAL)
    return _complete("auto_complete", NodeState.COMPLETE)
