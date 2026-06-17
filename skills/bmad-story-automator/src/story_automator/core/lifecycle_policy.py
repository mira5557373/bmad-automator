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

import json
from dataclasses import dataclass
from typing import Any

__all__ = [
    "EntryMap",
    "NodeDef",
    "Policy",
    "PolicyError",
    "canonical_policy_json",
    "load_policy",
    "policy_to_dict",
]

_VALID_GATES: frozenset[str] = frozenset({"human", "auto"})
_VALID_MODES: frozenset[str] = frozenset({"greenfield", "brownfield"})


class PolicyError(ValueError):
    """Raised on any structural, closed-world, or DAG-cycle violation."""


@dataclass(frozen=True, kw_only=True)
class NodeDef:
    """One node in the macro-lifecycle DAG. Frozen so accidental mutation
    after load is impossible — the scheduler treats Policy as immutable."""

    id: str
    track: str
    phase: int
    skill: str
    validator_skill: str | None
    deps: list[str]
    input_artifacts: list[str]
    output_artifact: str
    verifier: str
    gate: str
    modes: list[str]
    agent_role: str
    interactive: bool


@dataclass(frozen=True, kw_only=True)
class EntryMap:
    """Per-mode entry node ids."""

    greenfield: list[str]
    brownfield: list[str]


@dataclass(frozen=True, kw_only=True)
class Policy:
    """The whole macro-lifecycle policy: version, nodes, entry map."""

    version: int
    nodes: dict[str, NodeDef]
    entry: EntryMap


def load_policy(json_text: str) -> Policy:
    """Parse and validate a lifecycle-policy JSON document.

    Performs (in order): JSON parse, structural-shape validation,
    field-by-field type / enum validation, closed-world reference
    validation (deps + entry ids exist), and DAG cycle detection
    (Tasks 3-5 land each layer). Any failure raises ``PolicyError``
    with a message naming the offending node or field.
    """

    try:
        raw: Any = json.loads(json_text)
    except json.JSONDecodeError as err:
        raise PolicyError(f"policy is not valid JSON: {err}") from err

    if not isinstance(raw, dict):
        raise PolicyError(
            f"policy top-level must be a JSON object, got {type(raw).__name__}"
        )

    version = raw.get("version")
    if not isinstance(version, int):
        raise PolicyError(f"policy.version must be int, got {type(version).__name__}")

    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, dict) or not nodes_raw:
        raise PolicyError("policy.nodes must be a non-empty object")

    nodes: dict[str, NodeDef] = {}
    for node_id, node_raw in nodes_raw.items():
        if not isinstance(node_id, str) or not node_id:
            raise PolicyError(f"node id must be a non-empty string, got {node_id!r}")
        nodes[node_id] = _parse_node(node_id, node_raw)

    entry_raw = raw.get("entry")
    if not isinstance(entry_raw, dict):
        raise PolicyError(
            "policy.entry must be an object with greenfield/brownfield keys"
        )
    entry = EntryMap(
        greenfield=_parse_str_list(
            entry_raw.get("greenfield", []), where="entry.greenfield"
        ),
        brownfield=_parse_str_list(
            entry_raw.get("brownfield", []), where="entry.brownfield"
        ),
    )

    return Policy(version=version, nodes=nodes, entry=entry)


def _parse_node(node_id: str, raw: Any) -> NodeDef:
    if not isinstance(raw, dict):
        raise PolicyError(
            f"node {node_id!r} must be an object, got {type(raw).__name__}"
        )

    def required(key: str, expected_type: type) -> Any:
        if key not in raw:
            raise PolicyError(f"node {node_id!r} missing required field {key!r}")
        value = raw[key]
        if not isinstance(value, expected_type):
            raise PolicyError(
                f"node {node_id!r} field {key!r} must be {expected_type.__name__}, "
                f"got {type(value).__name__}"
            )
        return value

    track = required("track", str)
    phase = required("phase", int)
    skill = required("skill", str)
    validator_skill_raw = raw.get("validator_skill")
    if validator_skill_raw is not None and not isinstance(validator_skill_raw, str):
        raise PolicyError(
            f"node {node_id!r} field 'validator_skill' must be string or null"
        )

    deps = _parse_str_list(raw.get("deps", []), where=f"node {node_id!r} field 'deps'")
    input_artifacts = _parse_str_list(
        raw.get("input_artifacts", []),
        where=f"node {node_id!r} field 'input_artifacts'",
    )
    output_artifact = required("output_artifact", str)
    verifier = required("verifier", str)
    gate = required("gate", str)
    modes = _parse_str_list(
        raw.get("modes", []), where=f"node {node_id!r} field 'modes'"
    )
    agent_role = required("agent_role", str)
    interactive = bool(raw.get("interactive", False))

    return NodeDef(
        id=node_id,
        track=track,
        phase=phase,
        skill=skill,
        validator_skill=validator_skill_raw,
        deps=list(deps),
        input_artifacts=list(input_artifacts),
        output_artifact=output_artifact,
        verifier=verifier,
        gate=gate,
        modes=list(modes),
        agent_role=agent_role,
        interactive=interactive,
    )


def _parse_str_list(value: Any, *, where: str) -> list[str]:
    if not isinstance(value, list):
        raise PolicyError(f"{where} must be a list, got {type(value).__name__}")
    for item in value:
        if not isinstance(item, str):
            raise PolicyError(
                f"{where} items must be strings, got {type(item).__name__}: {item!r}"
            )
    return list(value)


def policy_to_dict(policy: Policy) -> dict[str, Any]:
    """Inverse of ``load_policy``: produce the dict form for serialization
    tests + canonical hashing. Field order matches the loader's reads."""

    return {
        "version": policy.version,
        "nodes": {
            node_id: {
                "track": node.track,
                "phase": node.phase,
                "skill": node.skill,
                "validator_skill": node.validator_skill,
                "deps": list(node.deps),
                "input_artifacts": list(node.input_artifacts),
                "output_artifact": node.output_artifact,
                "verifier": node.verifier,
                "gate": node.gate,
                "modes": list(node.modes),
                "agent_role": node.agent_role,
                "interactive": node.interactive,
            }
            for node_id, node in policy.nodes.items()
        },
        "entry": {
            "greenfield": list(policy.entry.greenfield),
            "brownfield": list(policy.entry.brownfield),
        },
    }


def canonical_policy_json(policy: Policy) -> str:
    """Stable JSON for hashing — keys sorted, separators (',', ':').

    The hash this produces lives in ``RunStatus.policy_hash``; a status file
    written against one policy refuses to resume against a different
    canonical form. Field-order stability is non-negotiable.
    """

    return json.dumps(policy_to_dict(policy), sort_keys=True, separators=(",", ":"))
