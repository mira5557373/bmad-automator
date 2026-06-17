"""Lifecycle per-run status + artifact registry (W0-M01).

Persists the macro-lifecycle run state to a JSON file (``lifecycle-status.json``
by convention; the spec writes ``.yaml`` but stdlib has no YAML and the
no-deps guardrail forbids PyYAML — JSON is the on-disk format). Reuses
``core.atomic_io.write_atomic_text`` for crash-safe writes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from story_automator.core.atomic_io import write_atomic_text
from story_automator.core.lifecycle_policy import (
    Policy,
    canonical_policy_json,
)

__all__ = [
    "ArtifactRecord",
    "NodeRun",
    "NodeState",
    "PolicyMismatch",
    "RunStatus",
    "load_status",
    "new_run_status",
    "save_status",
    "status_from_dict",
    "status_to_dict",
]


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
    policy it's being loaded against."""


@dataclass(kw_only=True)
class NodeRun:
    """Per-node run record. Mutable: the phase-runner (W0-M02) updates
    ``state``, ``started_at``, etc. in place between scheduler invocations."""

    state: NodeState
    attempts: int = 0
    started_at: str = ""
    completed_at: str = ""
    last_error: str = ""
    gate_decision: str | None = None
    gate_notes: str = ""


@dataclass(kw_only=True)
class ArtifactRecord:
    """Provenance record for a produced artifact. The scheduler does NOT
    consult this — input-artifact existence goes through the injected
    ``artifact_exists`` callable. This is purely for §17 provenance."""

    path: str
    produced_by_node: str
    produced_at: str
    sha256: str = ""


@dataclass(kw_only=True)
class RunStatus:
    """The full per-run status document. Persisted as JSON."""

    version: int = 1
    run_id: str
    mode: str
    started_at: str
    policy_hash: str
    nodes: dict[str, NodeRun]
    artifacts: dict[str, ArtifactRecord] = field(default_factory=dict)


_VALID_MODES: frozenset[str] = frozenset({"greenfield", "brownfield"})


def _policy_hash(policy: Policy) -> str:
    return hashlib.sha256(canonical_policy_json(policy).encode("utf-8")).hexdigest()


def new_run_status(
    policy: Policy, *, run_id: str, mode: str, started_at: str
) -> RunStatus:
    """Seed a fresh status for ``policy``.

    - In-mode nodes (those whose ``modes`` list includes ``mode``) start PENDING.
    - Out-of-mode nodes start SKIPPED — the scheduler ignores them anyway via
      mode filtering, but recording the skip up front keeps node counts honest.
    - ``mode`` itself is validated against ``_VALID_MODES``; unknown values raise
      ``ValueError``.
    """

    if mode not in _VALID_MODES:
        raise ValueError(
            f"mode must be one of {sorted(_VALID_MODES)!r}, got {mode!r}"
        )
    return RunStatus(
        run_id=run_id,
        mode=mode,
        started_at=started_at,
        policy_hash=_policy_hash(policy),
        nodes={
            node_id: NodeRun(
                state=NodeState.PENDING if mode in node.modes else NodeState.SKIPPED
            )
            for node_id, node in policy.nodes.items()
        },
        artifacts={},
    )


def status_to_dict(status: RunStatus) -> dict[str, Any]:
    """JSON-safe dict. NodeState enum members serialize as their .value string."""

    return {
        "version": status.version,
        "run_id": status.run_id,
        "mode": status.mode,
        "started_at": status.started_at,
        "policy_hash": status.policy_hash,
        "nodes": {
            node_id: {
                "state": run.state.value,
                "attempts": run.attempts,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "last_error": run.last_error,
                "gate_decision": run.gate_decision,
                "gate_notes": run.gate_notes,
            }
            for node_id, run in status.nodes.items()
        },
        "artifacts": {
            art_path: asdict(rec) for art_path, rec in status.artifacts.items()
        },
    }


def status_from_dict(data: dict[str, Any]) -> RunStatus:
    """Inverse of ``status_to_dict``. Unknown NodeState values raise ValueError
    via the Enum lookup (intentional — fail loud rather than coerce)."""

    if not isinstance(data, dict):
        raise ValueError(f"status payload must be an object, got {type(data).__name__}")
    nodes_raw = data.get("nodes")
    if not isinstance(nodes_raw, dict):
        raise ValueError("status.nodes must be an object")
    artifacts_raw = data.get("artifacts", {})
    if not isinstance(artifacts_raw, dict):
        raise ValueError("status.artifacts must be an object")

    nodes = {
        node_id: NodeRun(
            state=NodeState(run_raw["state"]),
            attempts=int(run_raw.get("attempts", 0)),
            started_at=str(run_raw.get("started_at", "")),
            completed_at=str(run_raw.get("completed_at", "")),
            last_error=str(run_raw.get("last_error", "")),
            gate_decision=run_raw.get("gate_decision"),
            gate_notes=str(run_raw.get("gate_notes", "")),
        )
        for node_id, run_raw in nodes_raw.items()
    }
    artifacts = {
        art_path: ArtifactRecord(
            path=str(rec_raw.get("path", art_path)),
            produced_by_node=str(rec_raw["produced_by_node"]),
            produced_at=str(rec_raw["produced_at"]),
            sha256=str(rec_raw.get("sha256", "")),
        )
        for art_path, rec_raw in artifacts_raw.items()
    }
    mode_value = str(data["mode"])
    if mode_value not in _VALID_MODES:
        raise ValueError(
            f"status.mode must be one of {sorted(_VALID_MODES)!r}, got {mode_value!r}"
        )
    return RunStatus(
        version=int(data.get("version", 1)),
        run_id=str(data["run_id"]),
        mode=mode_value,
        started_at=str(data["started_at"]),
        policy_hash=str(data["policy_hash"]),
        nodes=nodes,
        artifacts=artifacts,
    )


def save_status(path: Path, status: RunStatus) -> None:
    """Atomic write via ``core.atomic_io.write_atomic_text``. The caller must
    ensure ``path.parent`` exists (matching the atomic_io convention)."""

    payload = json.dumps(status_to_dict(status), separators=(",", ":"))
    write_atomic_text(Path(path), payload)


def load_status(path: Path, *, expected_policy: Policy | None = None) -> RunStatus:
    """Load a status file. If ``expected_policy`` is supplied, the recorded
    ``policy_hash`` must match the canonical hash of ``expected_policy``;
    otherwise raise ``PolicyMismatch``."""

    payload = Path(path).read_text(encoding="utf-8")
    data = json.loads(payload)
    status = status_from_dict(data)
    if expected_policy is not None:
        expected_hash = _policy_hash(expected_policy)
        if status.policy_hash != expected_hash:
            raise PolicyMismatch(
                f"status policy_hash {status.policy_hash!r} != "
                f"expected {expected_hash!r}"
            )
    return status
