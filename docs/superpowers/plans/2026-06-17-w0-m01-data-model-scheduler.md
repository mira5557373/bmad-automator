# W0-M01 — Lifecycle Data Model & DAG Scheduler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the macro-layer **lifecycle data model + DAG scheduler** specified in `docs/superpowers/specs/lifecycle/build-spec-full.md` §1 (Wave 0) and `design-spec.md` §3 — three new pure-Python modules under `skills/bmad-story-automator/src/story_automator/core/` plus a fixtures-driven test battery — so a downstream milestone (W0-M02 phase-runner) can wire a real agent into the same scheduler.

**Architecture:** Three new sibling modules — `lifecycle_policy.py` (schema dataclasses + JSON loader + structural validator + closed-world validator + cycle detector), `lifecycle_status.py` (per-run state + artifact registry + atomic load/save reusing `core.atomic_io.write_atomic_text`), and `lifecycle_scheduler.py` (pure-function topological sort + mode-aware filtering + runnable selection with bounded-concurrency cap). The scheduler performs **no IO and no execution** — it takes a `Policy`, a `RunStatus`, and an injected `artifact_exists` callable and returns an ordered list of runnable node ids. Phase-runner, verifiers, gates, telemetry events, and CLI surface are explicit non-goals (they live in §2/§3 and follow-on milestones).

**Tech Stack:** Python 3.11+ stdlib only (`dataclasses`, `enum`, `json`, `hashlib`, `pathlib`, `typing`) plus the existing project module `story_automator.core.atomic_io.write_atomic_text` for crash-safe status persistence. **No new third-party imports.** Tests use `unittest.TestCase` with in-process fixtures (no subprocesses, no tmux, no network). Lint via `ruff`; suite via `npm run test:python`.

---

## Scope for this milestone

**In scope (build-spec-full.md §1 acceptance criteria):**
1. `lifecycle-policy.json` node schema — id, track, phase, skill, validator_skill?, deps[], input_artifacts[], output_artifact, verifier, gate(human|auto), modes[], agent_role, interactive? — plus `entry.{greenfield,brownfield}`.
2. Loader + structural validator + closed-world reference validator + DAG-cycle detector.
3. `lifecycle-status` per-run node states + artifact registry; atomic write via `atomic_io.write_atomic_text`.
4. Topological scheduler with bounded concurrency and mode-aware filtering.
5. Resumable from disk: write status, reload, scheduler picks correct next set.
6. Acceptance fixtures + tests: schema round-trips; scheduler selects correct runnable nodes; resume reconstructs state.

**Out of scope (explicit non-goals — belong to later milestones):**
- Phase-runner / child-agent spawning (W0-M02, design-spec §3.4 second half)
- Phase verifiers (`artifact_exists`, `structural_complete`, validator-skill wrappers) (W0-M02)
- Approval-gate primitive (`await-approval` / `approve` / `reject`) (W0-M03)
- `core/lifecycle_events.py` (`LifecyclePhaseStarted/Completed/Failed`) — created in W0-M02
- Entry-mode router CLI (`lifecycle-helper` commands) (W0-M04)
- Telemetry emission for lifecycle events — `core/telemetry_events.py` is M01-owned and **must not be touched** in any milestone outside M01
- Real artifact-content verification (the scheduler accepts an injected `artifact_exists` callable; deciding what "exists" means is a verifier concern in §2)

## Design decisions worth recording (so reviewers don't relitigate them)

1. **File extension is `.json`, not `.yaml`.** The spec mentions `lifecycle-status.yaml`, but Python stdlib has no YAML and the no-deps guardrail (CLAUDE.md "Hard guardrails") forbids PyYAML. JSON is the only stdlib-portable structured format and matches the existing `data/orchestration-policy.json` pattern. The file is named `lifecycle-status.json`; the spec's intent — a structured persistent state file — is fully satisfied. A subsequent milestone can rename to `.yaml` (JSON is a YAML 1.2 subset) if the operator insists on the extension, but the on-disk bytes stay JSON until PyYAML is whitelisted.
2. **Scheduler is a pure function.** No IO, no logging, no event emission. Inputs: `Policy`, `RunStatus`, `artifact_exists: Callable[[str], bool]`, `max_concurrency: int`. The run mode comes from `status.mode` — a single source of truth removes the "mode parameter drifts from status" footgun. Output: `list[str]` (node ids in deterministic order). This keeps unit tests deterministic and lets §2's phase-runner own the execution + telemetry concerns.
3. **Deterministic tie-breaking.** When the topological order would otherwise be ambiguous (multiple runnable nodes with no precedence between them), nodes are emitted in **lexicographic node-id order**. Tests can rely on this.
4. **Mode-aware filtering.** The scheduler restricts the active DAG to nodes whose `modes` list includes the run mode. Deps that reference out-of-mode nodes are filtered out of the in-mode subgraph; an in-mode node may not depend on an out-of-mode node (caught at load time when the run mode is known). The data-model validator performs *structural* checks (deps reference some defined node) without knowing the run mode.
5. **NodeState enum, with `SKIPPED` actively emitted by `new_run_status`.** The full set { `pending`, `ready`, `running`, `awaiting_approval`, `complete`, `failed`, `skipped` } is in the schema. `new_run_status` seeds in-mode nodes as `PENDING` and out-of-mode nodes as `SKIPPED` — keeping the status file honest about node counts (no "16/20 complete" when 4 are unreachable) and giving the scheduler an explicit signal that a node is intentionally not run rather than just slow to start. §1 scheduler reads `PENDING` / `COMPLETE` / `SKIPPED` and produces no further transitions; §2 (phase-runner) drives the others.
6. **Artifact registry is provenance metadata, not the existence oracle.** The scheduler's "input artifact exists" check goes through the injected `artifact_exists` callable (the caller — phase-runner in W0-M02 — decides what "exists" means; for unit tests it's a stub, for production it's a `Path(...).is_file()` against the project root). The `RunStatus.artifacts` registry records which node produced which artifact, when, and a SHA-256 — useful for §17 provenance but **not** consulted by the §1 scheduler. Decoupling these two keeps the scheduler honest about the filesystem.
7. **Policy hash is computed and stored in `RunStatus`.** A status file produced against one policy must refuse to resume against a different one (the node-id set or DAG could have changed). Hashing the canonicalized policy JSON and storing it in `RunStatus.policy_hash` gives a cheap mismatch detector; reload-time mismatch raises a typed `PolicyMismatch` error.
8. **No CLI surface in this milestone.** All acceptance tests drive the Python API directly. CLI commands (`lifecycle-helper run-node`, `await-approval`, `approve`, `reject`, `status`) are W0-M03/M04 work.
9. **The scheduler does NOT enforce state-transition legality.** A phase-runner that marks a `gate=human` node `COMPLETE` without going through `AWAITING_APPROVAL` will not be stopped by the W0-M01 scheduler — the scheduler is a pure read of "what's runnable next given this status?" and is not a state machine guardian. Enforcing legal transitions (verifier pass → AWAITING_APPROVAL for gated nodes; approval before COMPLETE) is the phase-runner's (W0-M02) and approval-gate's (W0-M03) job. Tests in W0-M01 exercise scheduler outputs given valid status mutations; they do not exercise scheduler rejection of illegal status mutations because none exists by design.

## File structure

| File | New / Modified | Responsibility |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py` | **Create** | `NodeDef`, `EntryMap`, `Policy` dataclasses; `load_policy(json_text) -> Policy`; `policy_to_dict(policy) -> dict`; structural + closed-world + cycle validators; `PolicyError` exception type; `canonical_policy_json(policy) -> str` (stable serialization for hashing). |
| `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py` | **Create** | `NodeState` enum; `NodeRun`, `ArtifactRecord`, `RunStatus` dataclasses; `new_run_status(policy, run_id, mode) -> RunStatus`; `load_status(path) -> RunStatus`; `save_status(path, status) -> None` (atomic via `atomic_io.write_atomic_text`); `status_to_dict` / `status_from_dict`; `PolicyMismatch` exception type. |
| `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py` | **Create** | `runnable_nodes(policy, status, *, mode, artifact_exists, max_concurrency=1) -> list[str]`; `topological_order(policy, *, mode) -> list[str]`; `SchedulerError` exception type. |
| `tests/test_lifecycle_policy.py` | **Create** | Loader, structural, closed-world, cycle, round-trip, canonical-form tests. |
| `tests/test_lifecycle_status.py` | **Create** | NodeState enum, RunStatus dataclass, atomic save+load round-trip, resume after partial completion, PolicyMismatch detection. |
| `tests/test_lifecycle_scheduler.py` | **Create** | Topological order, runnable selection (deps + inputs), bounded concurrency cap, mode-aware filtering, deterministic tie-breaking. |
| `tests/test_lifecycle_acceptance.py` | **Create** | The three §1 acceptance bullets in one end-to-end test — schema round-trips; scheduler picks correct sequence; resume after partial completion picks correct next set. |
| `tests/fixtures/lifecycle/greenfield-minimal.policy.json` | **Create** | 4-node DAG (B1-brief → B2-prd → B3-arch → B3-epics); modes=["greenfield"]. |
| `tests/fixtures/lifecycle/brownfield-minimal.policy.json` | **Create** | 5-node DAG (B0-document-project → B2-prd → B3-arch → B3-epics; B1-brief absent or skipped); brownfield mode. |
| `tests/fixtures/lifecycle/full-both-modes.policy.json` | **Create** | Mixed-mode policy covering greenfield + brownfield entries and an out-of-mode dep example. |
| `tests/fixtures/lifecycle/invalid-cycle.policy.json` | **Create** | Two-node mutual-dep cycle for cycle-detection negative test. |
| `tests/fixtures/lifecycle/invalid-missing-dep.policy.json` | **Create** | Node referencing a non-existent dep id. |
| `tests/fixtures/lifecycle/invalid-bad-enum.policy.json` | **Create** | `gate: "manual"` (not `human`/`auto`) — enum-violation negative test. |
| `tests/fixtures/lifecycle/invalid-entry-ref.policy.json` | **Create** | `entry.greenfield` references a non-existent node id. |

No existing file is modified. The hard guardrail "Do NOT touch `core/telemetry_events.py` outside M01" is preserved by construction.

---

## Task 1: Module skeletons and exception types

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`
- Create: `tests/test_lifecycle_policy.py`
- Create: `tests/test_lifecycle_status.py`
- Create: `tests/test_lifecycle_scheduler.py`

- [ ] **Step 1: Write the failing skeleton-import tests**

Create `tests/test_lifecycle_policy.py`:

```python
from __future__ import annotations

import unittest


class LifecyclePolicyModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_policy  # noqa: F401

    def test_exposes_policy_error(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError

        self.assertTrue(issubclass(PolicyError, ValueError))

    def test_exposes_load_policy(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy

        self.assertTrue(callable(load_policy))
```

Create `tests/test_lifecycle_status.py`:

```python
from __future__ import annotations

import unittest


class LifecycleStatusModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_status  # noqa: F401

    def test_exposes_policy_mismatch(self) -> None:
        from story_automator.core.lifecycle_status import PolicyMismatch

        self.assertTrue(issubclass(PolicyMismatch, ValueError))

    def test_exposes_node_state(self) -> None:
        from story_automator.core.lifecycle_status import NodeState

        self.assertEqual(NodeState.PENDING.value, "pending")
        self.assertEqual(NodeState.COMPLETE.value, "complete")
```

Create `tests/test_lifecycle_scheduler.py`:

```python
from __future__ import annotations

import unittest


class LifecycleSchedulerModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_scheduler  # noqa: F401

    def test_exposes_scheduler_error(self) -> None:
        from story_automator.core.lifecycle_scheduler import SchedulerError

        self.assertTrue(issubclass(SchedulerError, RuntimeError))

    def test_exposes_runnable_nodes(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes

        self.assertTrue(callable(runnable_nodes))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy tests.test_lifecycle_status tests.test_lifecycle_scheduler -v`

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create the three minimal module skeletons**

Create `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`:

```python
"""Lifecycle policy data model + loader + validators (W0-M01).

Sibling module to `core/runtime_policy.py` (which governs the existing
sprint-engine policy). This module owns the *macro lifecycle* policy: the
phase-DAG of nodes (B1-brief, B2-prd, ...), the entry-mode router map, and
the structural + closed-world + cycle validators that gate any attempt to
load it.

Pure-Python, stdlib-only. The scheduler in `lifecycle_scheduler.py` consumes
the `Policy` dataclass; the per-run state in `lifecycle_status.py` references
the canonical JSON form (`canonical_policy_json`) to fingerprint the policy
a status file was created against.
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
```

Create `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py`:

```python
"""Lifecycle per-run status + artifact registry (W0-M01).

Persists the macro-lifecycle run state to a JSON file (`lifecycle-status.json`
by convention; the spec writes `.yaml` but stdlib has no YAML and the
no-deps guardrail forbids PyYAML — JSON is the on-disk format). Reuses
`core.atomic_io.write_atomic_text` for crash-safe writes.
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
```

Create `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`:

```python
"""Lifecycle DAG scheduler (W0-M01).

Pure-function topological scheduler over the macro-lifecycle DAG. Performs
no IO and no execution: callers pass a `Policy`, a `RunStatus`, an
`artifact_exists` callable, the run `mode`, and a `max_concurrency` cap,
and receive an ordered list of runnable node ids back. The phase-runner
(W0-M02) is responsible for actually invoking child agents and updating
node states.
"""

from __future__ import annotations

__all__ = ["SchedulerError", "runnable_nodes"]


class SchedulerError(RuntimeError):
    """Raised on scheduler-internal invariants violations (e.g. a topo sort
    over an already-validated DAG that somehow can't make progress).

    Policy-level errors surface as `PolicyError`; this is the residual
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy tests.test_lifecycle_status tests.test_lifecycle_scheduler -v`

Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
        skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py \
        skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py \
        tests/test_lifecycle_policy.py \
        tests/test_lifecycle_status.py \
        tests/test_lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): scaffold policy/status/scheduler modules with typed errors"
```

---

## Task 2: Policy dataclasses + JSON loader (happy path)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Modify: `tests/test_lifecycle_policy.py`
- Create: `tests/fixtures/lifecycle/greenfield-minimal.policy.json`

- [ ] **Step 1: Write the happy-path fixture**

Create `tests/fixtures/lifecycle/greenfield-minimal.policy.json`:

```json
{
  "version": 1,
  "nodes": {
    "B1-brief": {
      "track": "bmm",
      "phase": 1,
      "skill": "bmad-product-brief",
      "validator_skill": null,
      "deps": [],
      "input_artifacts": [],
      "output_artifact": "docs/product-brief.md",
      "verifier": "structural",
      "gate": "human",
      "modes": ["greenfield"],
      "agent_role": "analyst",
      "interactive": true
    },
    "B2-prd": {
      "track": "bmm",
      "phase": 2,
      "skill": "bmad-create-prd",
      "validator_skill": "bmad-validate-prd",
      "deps": ["B1-brief"],
      "input_artifacts": ["docs/product-brief.md"],
      "output_artifact": "docs/prd.md",
      "verifier": "prd_valid",
      "gate": "human",
      "modes": ["greenfield"],
      "agent_role": "pm",
      "interactive": true
    },
    "B3-arch": {
      "track": "bmm",
      "phase": 3,
      "skill": "bmad-create-architecture",
      "validator_skill": null,
      "deps": ["B2-prd"],
      "input_artifacts": ["docs/prd.md"],
      "output_artifact": "docs/architecture.md",
      "verifier": "structural",
      "gate": "human",
      "modes": ["greenfield"],
      "agent_role": "architect",
      "interactive": false
    },
    "B3-epics": {
      "track": "bmm",
      "phase": 3,
      "skill": "bmad-create-epics-and-stories",
      "validator_skill": "bmad-check-implementation-readiness",
      "deps": ["B3-arch"],
      "input_artifacts": ["docs/prd.md", "docs/architecture.md"],
      "output_artifact": "epics/",
      "verifier": "epics_created",
      "gate": "human",
      "modes": ["greenfield"],
      "agent_role": "pm",
      "interactive": false
    }
  },
  "entry": {
    "greenfield": ["B1-brief"],
    "brownfield": []
  }
}
```

- [ ] **Step 2: Write the failing loader test**

Append to `tests/test_lifecycle_policy.py`:

```python
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class LoadPolicyHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy

        self.load_policy = load_policy
        self.json_text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )

    def test_returns_policy_with_expected_node_ids(self) -> None:
        policy = self.load_policy(self.json_text)
        self.assertEqual(
            sorted(policy.nodes.keys()),
            ["B1-brief", "B2-prd", "B3-arch", "B3-epics"],
        )

    def test_node_fields_round_trip_from_fixture(self) -> None:
        policy = self.load_policy(self.json_text)
        b2 = policy.nodes["B2-prd"]
        self.assertEqual(b2.track, "bmm")
        self.assertEqual(b2.phase, 2)
        self.assertEqual(b2.skill, "bmad-create-prd")
        self.assertEqual(b2.validator_skill, "bmad-validate-prd")
        self.assertEqual(b2.deps, ["B1-brief"])
        self.assertEqual(b2.input_artifacts, ["docs/product-brief.md"])
        self.assertEqual(b2.output_artifact, "docs/prd.md")
        self.assertEqual(b2.verifier, "prd_valid")
        self.assertEqual(b2.gate, "human")
        self.assertEqual(b2.modes, ["greenfield"])
        self.assertEqual(b2.agent_role, "pm")
        self.assertTrue(b2.interactive)

    def test_optional_validator_skill_defaults_to_none(self) -> None:
        policy = self.load_policy(self.json_text)
        self.assertIsNone(policy.nodes["B1-brief"].validator_skill)

    def test_entry_map_populated(self) -> None:
        policy = self.load_policy(self.json_text)
        self.assertEqual(policy.entry.greenfield, ["B1-brief"])
        self.assertEqual(policy.entry.brownfield, [])

    def test_version_captured(self) -> None:
        policy = self.load_policy(self.json_text)
        self.assertEqual(policy.version, 1)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy -v`

Expected: FAIL — `NotImplementedError` in `load_policy`.

- [ ] **Step 4: Implement dataclasses + loader**

Replace the body of `lifecycle_policy.py`:

```python
"""Lifecycle policy data model + loader + validators (W0-M01).

Sibling module to `core/runtime_policy.py` (which governs the existing
sprint-engine policy). This module owns the *macro lifecycle* policy: the
phase-DAG of nodes (B1-brief, B2-prd, ...), the entry-mode router map, and
the structural + closed-world + cycle validators that gate any attempt to
load it.

Pure-Python, stdlib-only. The scheduler in `lifecycle_scheduler.py` consumes
the `Policy` dataclass; the per-run state in `lifecycle_status.py` references
the canonical JSON form (`canonical_policy_json`) to fingerprint the policy
a status file was created against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    (Tasks 3-5 land each layer). Any failure raises `PolicyError`
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
        raise PolicyError("policy.entry must be an object with greenfield/brownfield keys")
    entry = EntryMap(
        greenfield=_parse_str_list(entry_raw.get("greenfield", []), where="entry.greenfield"),
        brownfield=_parse_str_list(entry_raw.get("brownfield", []), where="entry.brownfield"),
    )

    return Policy(version=version, nodes=nodes, entry=entry)


def _parse_node(node_id: str, raw: Any) -> NodeDef:
    if not isinstance(raw, dict):
        raise PolicyError(f"node {node_id!r} must be an object, got {type(raw).__name__}")

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
    modes = _parse_str_list(raw.get("modes", []), where=f"node {node_id!r} field 'modes'")
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
    """Inverse of `load_policy`: produce the dict form for serialization
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

    The hash this produces lives in `RunStatus.policy_hash`; a status file
    written against one policy refuses to resume against a different
    canonical form. Field-order stability is non-negotiable.
    """

    return json.dumps(policy_to_dict(policy), sort_keys=True, separators=(",", ":"))
```

> Field order in the loader (`required(...)` calls and `_parse_str_list` ordering) is the contract — Tasks 6 and 7 depend on this. Don't rearrange.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy -v`

Expected: PASS (8 tests so far).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
        tests/test_lifecycle_policy.py \
        tests/fixtures/lifecycle/greenfield-minimal.policy.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): policy dataclasses + JSON loader with structural validation"
```

---

## Task 3: Policy validator — enums + required fields (negative tests)

**Files:**
- Modify: `tests/test_lifecycle_policy.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Create: `tests/fixtures/lifecycle/invalid-bad-enum.policy.json`

- [ ] **Step 1: Write the bad-enum fixture**

Create `tests/fixtures/lifecycle/invalid-bad-enum.policy.json`:

```json
{
  "version": 1,
  "nodes": {
    "B1-brief": {
      "track": "bmm",
      "phase": 1,
      "skill": "bmad-product-brief",
      "validator_skill": null,
      "deps": [],
      "input_artifacts": [],
      "output_artifact": "docs/product-brief.md",
      "verifier": "structural",
      "gate": "manual",
      "modes": ["greenfield"],
      "agent_role": "analyst",
      "interactive": true
    }
  },
  "entry": {"greenfield": ["B1-brief"], "brownfield": []}
}
```

- [ ] **Step 2: Write the failing enum-violation tests**

Append to `tests/test_lifecycle_policy.py`:

```python
class PolicyEnumValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError, load_policy

        self.PolicyError = PolicyError
        self.load_policy = load_policy

    def test_invalid_gate_value_raises(self) -> None:
        text = (FIXTURE_DIR / "invalid-bad-enum.policy.json").read_text(encoding="utf-8")
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(text)
        self.assertIn("gate", str(ctx.exception))
        self.assertIn("B1-brief", str(ctx.exception))

    def test_invalid_mode_value_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B1-brief"]["modes"] = ["greenfeld"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("modes", str(ctx.exception))

    def test_empty_modes_list_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B1-brief"]["modes"] = []
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("modes", str(ctx.exception))

    def test_missing_required_field_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        del raw["nodes"]["B2-prd"]["skill"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("skill", str(ctx.exception))

    def test_non_int_phase_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B2-prd"]["phase"] = "two"
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("phase", str(ctx.exception))

    def test_invalid_json_input_raises_policy_error(self) -> None:
        # `load_policy` wraps json.JSONDecodeError in PolicyError so callers
        # see a single typed error class for "policy didn't load," whether
        # the bytes were malformed or the shape was wrong.
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy("{not: valid, json}")
        self.assertIn("JSON", str(ctx.exception))

    def test_top_level_non_object_raises(self) -> None:
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy("[]")
        self.assertIn("object", str(ctx.exception))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy.PolicyEnumValidationTests -v`

Expected: FAIL — `gate: "manual"` currently passes the type check, and an empty modes list currently slips through.

- [ ] **Step 4: Add enum + non-empty validation**

In `lifecycle_policy.py`, modify `_parse_node` — replace the `gate = required("gate", str)` line with:

```python
    gate = required("gate", str)
    if gate not in _VALID_GATES:
        raise PolicyError(
            f"node {node_id!r} field 'gate' must be one of {sorted(_VALID_GATES)!r}, "
            f"got {gate!r}"
        )
```

Replace the `modes = _parse_str_list(...)` line with:

```python
    modes = _parse_str_list(raw.get("modes", []), where=f"node {node_id!r} field 'modes'")
    if not modes:
        raise PolicyError(f"node {node_id!r} field 'modes' must be non-empty")
    bad_modes = [m for m in modes if m not in _VALID_MODES]
    if bad_modes:
        raise PolicyError(
            f"node {node_id!r} field 'modes' contains invalid values "
            f"{bad_modes!r}; must be subset of {sorted(_VALID_MODES)!r}"
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy -v`

Expected: PASS (13 tests).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
        tests/test_lifecycle_policy.py \
        tests/fixtures/lifecycle/invalid-bad-enum.policy.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): validate gate + modes enums and required fields"
```

---

## Task 4: Closed-world reference validation (deps + entry ids exist)

**Files:**
- Modify: `tests/test_lifecycle_policy.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Create: `tests/fixtures/lifecycle/invalid-missing-dep.policy.json`
- Create: `tests/fixtures/lifecycle/invalid-entry-ref.policy.json`

- [ ] **Step 1: Write the negative fixtures**

Create `tests/fixtures/lifecycle/invalid-missing-dep.policy.json`:

```json
{
  "version": 1,
  "nodes": {
    "B1-brief": {
      "track": "bmm",
      "phase": 1,
      "skill": "bmad-product-brief",
      "validator_skill": null,
      "deps": ["B0-ghost"],
      "input_artifacts": [],
      "output_artifact": "docs/product-brief.md",
      "verifier": "structural",
      "gate": "human",
      "modes": ["greenfield"],
      "agent_role": "analyst",
      "interactive": true
    }
  },
  "entry": {"greenfield": ["B1-brief"], "brownfield": []}
}
```

Create `tests/fixtures/lifecycle/invalid-entry-ref.policy.json`:

```json
{
  "version": 1,
  "nodes": {
    "B1-brief": {
      "track": "bmm",
      "phase": 1,
      "skill": "bmad-product-brief",
      "validator_skill": null,
      "deps": [],
      "input_artifacts": [],
      "output_artifact": "docs/product-brief.md",
      "verifier": "structural",
      "gate": "human",
      "modes": ["greenfield"],
      "agent_role": "analyst",
      "interactive": true
    }
  },
  "entry": {"greenfield": ["ZZ-not-a-node"], "brownfield": []}
}
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_lifecycle_policy.py`:

```python
class PolicyClosedWorldTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError, load_policy

        self.PolicyError = PolicyError
        self.load_policy = load_policy

    def test_dep_referencing_unknown_node_raises(self) -> None:
        text = (FIXTURE_DIR / "invalid-missing-dep.policy.json").read_text(encoding="utf-8")
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(text)
        msg = str(ctx.exception)
        self.assertIn("B1-brief", msg)
        self.assertIn("B0-ghost", msg)

    def test_entry_referencing_unknown_node_raises(self) -> None:
        text = (FIXTURE_DIR / "invalid-entry-ref.policy.json").read_text(encoding="utf-8")
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(text)
        msg = str(ctx.exception)
        self.assertIn("entry", msg)
        self.assertIn("ZZ-not-a-node", msg)

    def test_self_dep_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B2-prd"]["deps"] = ["B2-prd"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("B2-prd", str(ctx.exception))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy.PolicyClosedWorldTests -v`

Expected: FAIL — closed-world validation does not exist.

- [ ] **Step 4: Add closed-world validation at the end of `load_policy`**

In `lifecycle_policy.py`, modify `load_policy` — before the `return Policy(...)` line, insert:

```python
    _validate_closed_world(nodes, entry)
```

Then add the helper at module scope:

```python
def _validate_closed_world(
    nodes: dict[str, NodeDef], entry: EntryMap
) -> None:
    """Every dep id and entry id must reference a defined node; a node
    may not depend on itself.

    Self-deps cause a trivial 1-node cycle the topo-sort would also catch,
    but flagging them here gives a clearer error message than the cycle-
    detection path (which surfaces them as "cycle through {B2-prd}").
    """

    known = set(nodes.keys())
    for node_id, node in nodes.items():
        for dep in node.deps:
            if dep == node_id:
                raise PolicyError(f"node {node_id!r} cannot depend on itself")
            if dep not in known:
                raise PolicyError(
                    f"node {node_id!r} dep {dep!r} is not a defined node"
                )

    for mode_name, mode_entry in (
        ("greenfield", entry.greenfield),
        ("brownfield", entry.brownfield),
    ):
        for entry_id in mode_entry:
            if entry_id not in known:
                raise PolicyError(
                    f"entry.{mode_name} references unknown node {entry_id!r}"
                )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy -v`

Expected: PASS (16 tests).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
        tests/test_lifecycle_policy.py \
        tests/fixtures/lifecycle/invalid-missing-dep.policy.json \
        tests/fixtures/lifecycle/invalid-entry-ref.policy.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): closed-world validation for deps + entry references + self-dep"
```

---

## Task 5: DAG cycle detection (Kahn's algorithm)

**Files:**
- Modify: `tests/test_lifecycle_policy.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Create: `tests/fixtures/lifecycle/invalid-cycle.policy.json`

- [ ] **Step 1: Write the cycle fixture**

Create `tests/fixtures/lifecycle/invalid-cycle.policy.json`:

```json
{
  "version": 1,
  "nodes": {
    "A-one": {
      "track": "bmm",
      "phase": 1,
      "skill": "bmad-noop",
      "validator_skill": null,
      "deps": ["A-two"],
      "input_artifacts": [],
      "output_artifact": "docs/a.md",
      "verifier": "structural",
      "gate": "auto",
      "modes": ["greenfield"],
      "agent_role": "analyst",
      "interactive": false
    },
    "A-two": {
      "track": "bmm",
      "phase": 1,
      "skill": "bmad-noop",
      "validator_skill": null,
      "deps": ["A-one"],
      "input_artifacts": [],
      "output_artifact": "docs/b.md",
      "verifier": "structural",
      "gate": "auto",
      "modes": ["greenfield"],
      "agent_role": "analyst",
      "interactive": false
    }
  },
  "entry": {"greenfield": ["A-one"], "brownfield": []}
}
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_lifecycle_policy.py`:

```python
class PolicyCycleDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError, load_policy

        self.PolicyError = PolicyError
        self.load_policy = load_policy

    def test_two_node_cycle_detected(self) -> None:
        text = (FIXTURE_DIR / "invalid-cycle.policy.json").read_text(encoding="utf-8")
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(text)
        msg = str(ctx.exception).lower()
        self.assertIn("cycle", msg)

    def test_three_node_cycle_detected(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        # Inject a B1 -> B3-epics -> B3-arch -> B2-prd -> B1 cycle
        raw["nodes"]["B1-brief"]["deps"] = ["B3-epics"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("cycle", str(ctx.exception).lower())

    def test_dag_with_diamond_passes(self) -> None:
        # B1 -> B2, B1 -> B3, B2 -> B4, B3 -> B4 (diamond, no cycle)
        import json as _json

        policy = {
            "version": 1,
            "nodes": {
                name: {
                    "track": "bmm",
                    "phase": 1,
                    "skill": "bmad-noop",
                    "validator_skill": None,
                    "deps": deps,
                    "input_artifacts": [],
                    "output_artifact": f"docs/{name}.md",
                    "verifier": "structural",
                    "gate": "auto",
                    "modes": ["greenfield"],
                    "agent_role": "analyst",
                    "interactive": False,
                }
                for name, deps in [
                    ("B1", []),
                    ("B2", ["B1"]),
                    ("B3", ["B1"]),
                    ("B4", ["B2", "B3"]),
                ]
            },
            "entry": {"greenfield": ["B1"], "brownfield": []},
        }
        # Should NOT raise — diamond is a valid DAG.
        self.load_policy(_json.dumps(policy))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy.PolicyCycleDetectionTests -v`

Expected: FAIL — cycle detection does not exist.

- [ ] **Step 4: Add cycle detection via Kahn's algorithm**

In `lifecycle_policy.py`, modify `load_policy` — after `_validate_closed_world(...)` insert:

```python
    _validate_acyclic(nodes)
```

Then add the helper at module scope:

```python
def _validate_acyclic(nodes: dict[str, NodeDef]) -> None:
    """Kahn's algorithm: build in-degree counts, peel off zero-in-degree
    nodes; if any nodes remain, those nodes participate in a cycle.

    The error message lists the residual nodes in sorted order so the
    operator can pinpoint the offending cycle quickly. We don't enumerate
    every cycle in the SCC — for the lifecycle policy's expected size
    (~40 nodes max per design-spec §5) the residual node list is enough."""

    in_degree: dict[str, int] = {node_id: 0 for node_id in nodes}
    for node in nodes.values():
        # in_degree[X] = number of edges coming INTO X = number of deps X declares.
        # _validate_closed_world has already proven every dep references a defined
        # node, so the indexing into `nodes` later in Kahn's loop is safe.
        in_degree[node.id] = len(node.deps)

    queue: list[str] = sorted(n for n, d in in_degree.items() if d == 0)
    visited: set[str] = set()
    while queue:
        node_id = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        # For each successor of node_id (i.e. any node that lists node_id
        # in its deps), decrement and enqueue if it hits zero.
        for candidate in nodes.values():
            if node_id in candidate.deps and candidate.id not in visited:
                in_degree[candidate.id] -= 1
                if in_degree[candidate.id] == 0:
                    # Insert in sorted position so the output remains
                    # deterministic regardless of dict iteration order.
                    queue.append(candidate.id)
                    queue.sort()

    residual = sorted(set(nodes.keys()) - visited)
    if residual:
        raise PolicyError(
            f"policy contains a cycle through nodes: {residual!r}"
        )
```

> **Algorithmic note:** for ~40 nodes the O(N²) edge-scan is negligible and avoids building a separate adjacency-list structure. Keep it simple. The `queue.sort()` makes the visit order lexicographic-stable so Task 10's `topological_order` (which reuses this same algorithm) is deterministic.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy -v`

Expected: PASS (19 tests).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
        tests/test_lifecycle_policy.py \
        tests/fixtures/lifecycle/invalid-cycle.policy.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): DAG cycle detection via Kahn's algorithm"
```

---

## Task 6: Policy round-trip + canonical-form hashing

**Files:**
- Modify: `tests/test_lifecycle_policy.py`

- [ ] **Step 1: Write the failing round-trip tests**

Append to `tests/test_lifecycle_policy.py`:

```python
class PolicyRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import (
            canonical_policy_json,
            load_policy,
            policy_to_dict,
        )

        self.canonical_policy_json = canonical_policy_json
        self.load_policy = load_policy
        self.policy_to_dict = policy_to_dict
        self.text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )

    def test_load_then_to_dict_then_load_is_identity(self) -> None:
        import json as _json

        policy = self.load_policy(self.text)
        round_tripped = self.load_policy(_json.dumps(self.policy_to_dict(policy)))
        self.assertEqual(
            self.policy_to_dict(policy),
            self.policy_to_dict(round_tripped),
        )

    def test_canonical_form_is_sorted_and_separators_compact(self) -> None:
        policy = self.load_policy(self.text)
        canonical = self.canonical_policy_json(policy)
        self.assertNotIn(", ", canonical)
        self.assertNotIn(": ", canonical)
        # Confirm key sort by sniffing the prefix.
        self.assertTrue(canonical.startswith('{"entry":'))

    def test_canonical_form_stable_across_dict_orderings(self) -> None:
        import json as _json

        raw = _json.loads(self.text)
        permuted = {
            "entry": raw["entry"],
            "nodes": dict(reversed(list(raw["nodes"].items()))),
            "version": raw["version"],
        }
        a = self.load_policy(self.text)
        b = self.load_policy(_json.dumps(permuted))
        self.assertEqual(self.canonical_policy_json(a), self.canonical_policy_json(b))
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy.PolicyRoundTripTests -v`

Expected: PASS — `canonical_policy_json` and `policy_to_dict` already exist from Task 2. If a test fails, fix the canonical form (sort_keys, separators) — do NOT loosen the test.

- [ ] **Step 3: Commit (documentation tests only — no source changes)**

```bash
git add tests/test_lifecycle_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): policy round-trip + canonical-form invariants"
```

---

## Task 7: Status data model — NodeState, NodeRun, ArtifactRecord, RunStatus

**Files:**
- Modify: `tests/test_lifecycle_status.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py`

- [ ] **Step 1: Write the failing dataclass tests**

First, add the imports that downstream tasks (8, 9) will also need. Edit the top of `tests/test_lifecycle_status.py` so the imports section reads:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"
```

(The Task 1 skeleton had only `import unittest`; the additional imports land here so Tasks 8 and 9 don't have to re-import.)

Then append to `tests/test_lifecycle_status.py`:

```python
class StatusDataModelTests(unittest.TestCase):
    def test_all_node_states_enumerated(self) -> None:
        from story_automator.core.lifecycle_status import NodeState

        self.assertEqual(
            {member.value for member in NodeState},
            {
                "pending",
                "ready",
                "running",
                "awaiting_approval",
                "complete",
                "failed",
                "skipped",
            },
        )

    def test_node_run_defaults(self) -> None:
        from story_automator.core.lifecycle_status import NodeRun, NodeState

        run = NodeRun(state=NodeState.PENDING)
        self.assertEqual(run.state, NodeState.PENDING)
        self.assertEqual(run.attempts, 0)
        self.assertEqual(run.started_at, "")
        self.assertEqual(run.completed_at, "")
        self.assertEqual(run.last_error, "")
        self.assertIsNone(run.gate_decision)
        self.assertEqual(run.gate_notes, "")

    def test_artifact_record_fields(self) -> None:
        from story_automator.core.lifecycle_status import ArtifactRecord

        rec = ArtifactRecord(
            path="docs/prd.md",
            produced_by_node="B2-prd",
            produced_at="2026-06-17T10:00:00Z",
            sha256="0" * 64,
        )
        self.assertEqual(rec.path, "docs/prd.md")
        self.assertEqual(rec.produced_by_node, "B2-prd")

    def test_new_run_status_seeds_pending_per_node(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            NodeState,
            new_run_status,
        )

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )
        policy = load_policy(text)
        status = new_run_status(
            policy, run_id="run-abc", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        self.assertEqual(status.run_id, "run-abc")
        self.assertEqual(status.mode, "greenfield")
        self.assertEqual(status.started_at, "2026-06-17T10:00:00Z")
        self.assertEqual(set(status.nodes.keys()), set(policy.nodes.keys()))
        for node_id, run in status.nodes.items():
            self.assertEqual(run.state, NodeState.PENDING, msg=f"{node_id}")
        self.assertEqual(status.artifacts, {})

    def test_new_run_status_records_policy_hash(self) -> None:
        from story_automator.core.lifecycle_policy import canonical_policy_json, load_policy
        from story_automator.core.lifecycle_status import new_run_status

        import hashlib

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )
        policy = load_policy(text)
        status = new_run_status(
            policy, run_id="r1", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        expected = hashlib.sha256(canonical_policy_json(policy).encode("utf-8")).hexdigest()
        self.assertEqual(status.policy_hash, expected)

    def test_new_run_status_marks_out_of_mode_nodes_skipped(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import NodeState, new_run_status

        # Inline mixed-mode policy so Task 7 doesn't depend on the
        # brownfield fixture (which Task 13 creates).
        raw = {
            "version": 1,
            "nodes": {
                "GF-only": {
                    "track": "bmm", "phase": 1, "skill": "bmad-noop",
                    "validator_skill": None, "deps": [], "input_artifacts": [],
                    "output_artifact": "docs/gf.md", "verifier": "structural",
                    "gate": "auto", "modes": ["greenfield"],
                    "agent_role": "analyst", "interactive": False,
                },
                "BF-only": {
                    "track": "bmm", "phase": 1, "skill": "bmad-noop",
                    "validator_skill": None, "deps": [], "input_artifacts": [],
                    "output_artifact": "docs/bf.md", "verifier": "structural",
                    "gate": "auto", "modes": ["brownfield"],
                    "agent_role": "analyst", "interactive": False,
                },
                "Both": {
                    "track": "bmm", "phase": 1, "skill": "bmad-noop",
                    "validator_skill": None, "deps": [], "input_artifacts": [],
                    "output_artifact": "docs/both.md", "verifier": "structural",
                    "gate": "auto", "modes": ["greenfield", "brownfield"],
                    "agent_role": "analyst", "interactive": False,
                },
            },
            "entry": {"greenfield": ["GF-only"], "brownfield": ["BF-only"]},
        }
        policy = load_policy(json.dumps(raw))
        status = new_run_status(
            policy, run_id="r", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        self.assertEqual(status.nodes["GF-only"].state, NodeState.PENDING)
        self.assertEqual(status.nodes["Both"].state, NodeState.PENDING)
        self.assertEqual(status.nodes["BF-only"].state, NodeState.SKIPPED)

    def test_new_run_status_rejects_unknown_mode(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import new_run_status

        policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        with self.assertRaises(ValueError):
            new_run_status(
                policy, run_id="r", mode="midfield", started_at="2026-06-17T10:00:00Z"
            )
```

(The `FIXTURE_DIR` constant has already been added to the imports block above.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_status.StatusDataModelTests -v`

Expected: FAIL — dataclasses do not exist.

- [ ] **Step 3: Implement status dataclasses + factory**

Replace the body of `lifecycle_status.py`:

```python
"""Lifecycle per-run status + artifact registry (W0-M01).

Persists the macro-lifecycle run state to a JSON file (`lifecycle-status.json`
by convention; the spec writes `.yaml` but stdlib has no YAML and the
no-deps guardrail forbids PyYAML — JSON is the on-disk format). Reuses
`core.atomic_io.write_atomic_text` for crash-safe writes.
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
    PolicyError,
    canonical_policy_json,
    load_policy,
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
    `state`, `started_at`, etc. in place between scheduler invocations."""

    state: NodeState
    attempts: int = 0
    started_at: str = ""
    completed_at: str = ""
    last_error: str = ""
    gate_decision: str | None = None  # "approved" | "rejected" | None
    gate_notes: str = ""


@dataclass(kw_only=True)
class ArtifactRecord:
    """Provenance record for a produced artifact. The scheduler does NOT
    consult this — input-artifact existence goes through the injected
    `artifact_exists` callable. This is purely for §17 provenance."""

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
    """Seed a fresh status for `policy`.

    - In-mode nodes (those whose `modes` list includes `mode`) start `PENDING`.
    - Out-of-mode nodes start `SKIPPED` — the scheduler ignores them anyway via
      mode filtering, but recording the skip up front keeps node counts and
      future telemetry honest ("16 PENDING + 4 SKIPPED" not "20 PENDING with
      4 mysteriously never selected").
    - `mode` itself is validated against `_VALID_MODES`; unknown values raise
      `ValueError` (the typed `PolicyMismatch` is reserved for hash-mismatch on
      reload, not initial-construction misuse).
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
    """Inverse of `status_to_dict`. Unknown NodeState values raise ValueError
    via the Enum lookup (intentional — we'd rather fail loud than silently
    coerce to an unknown state)."""

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
    """Atomic write via `core.atomic_io.write_atomic_text`. The caller must
    ensure `path.parent` exists (matching the atomic_io convention)."""

    payload = json.dumps(status_to_dict(status), separators=(",", ":"))
    write_atomic_text(Path(path), payload)


def load_status(path: Path, *, expected_policy: Policy | None = None) -> RunStatus:
    """Load a status file. If `expected_policy` is supplied, the recorded
    `policy_hash` must match the canonical hash of `expected_policy`;
    otherwise raise `PolicyMismatch`. The mismatch is non-recoverable
    (the operator must reconcile the policy or start a fresh run)."""

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
```

> Note: this introduces an import edge `lifecycle_status` → `lifecycle_policy`. The reverse edge does NOT exist — keep it that way; the dependency must remain one-directional so Task 11's scheduler can depend on both without a cycle.

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_status -v`

Expected: PASS (10 tests — 3 skeleton from Task 1 + 7 in `StatusDataModelTests`).

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py \
        tests/test_lifecycle_status.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): status dataclasses + new_run_status + (de)serialization"
```

---

## Task 8: Status atomic save+load round-trip + PolicyMismatch detection

**Files:**
- Modify: `tests/test_lifecycle_status.py`

- [ ] **Step 1: Write the failing IO tests**

Append to `tests/test_lifecycle_status.py` (the `tempfile` import was added in Task 7's import block):

```python
class StatusSaveLoadRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _load_policy(self):
        from story_automator.core.lifecycle_policy import load_policy

        return load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )

    def test_save_then_load_is_identity(self) -> None:
        from story_automator.core.lifecycle_status import (
            load_status,
            new_run_status,
            save_status,
            status_to_dict,
        )

        policy = self._load_policy()
        original = new_run_status(
            policy, run_id="r-1", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        target = self.dir / "lifecycle-status.json"
        save_status(target, original)
        loaded = load_status(target, expected_policy=policy)

        self.assertEqual(status_to_dict(loaded), status_to_dict(original))

    def test_save_uses_atomic_io_no_orphan_tmp_files(self) -> None:
        from story_automator.core.lifecycle_status import (
            new_run_status,
            save_status,
        )

        policy = self._load_policy()
        status = new_run_status(
            policy, run_id="r-2", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        target = self.dir / "lifecycle-status.json"
        save_status(target, status)
        save_status(target, status)
        save_status(target, status)

        siblings = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(siblings, ["lifecycle-status.json"])

    def test_load_with_mismatched_policy_hash_raises(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            PolicyMismatch,
            new_run_status,
            save_status,
            load_status,
        )

        policy_a = self._load_policy()
        status = new_run_status(
            policy_a, run_id="r-3", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        target = self.dir / "lifecycle-status.json"
        save_status(target, status)

        # Mutate the policy to produce a different hash, then attempt to
        # load the status against it.
        import json as _json

        raw = _json.loads(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        raw["nodes"]["B2-prd"]["skill"] = "bmad-create-prd-v2"  # different bytes
        policy_b = load_policy(_json.dumps(raw))

        with self.assertRaises(PolicyMismatch):
            load_status(target, expected_policy=policy_b)

    def test_load_without_expected_policy_skips_hash_check(self) -> None:
        from story_automator.core.lifecycle_status import (
            new_run_status,
            save_status,
            load_status,
        )

        policy = self._load_policy()
        status = new_run_status(
            policy, run_id="r-4", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        target = self.dir / "lifecycle-status.json"
        save_status(target, status)

        # Should load cleanly with no policy provided.
        loaded = load_status(target)
        self.assertEqual(loaded.run_id, "r-4")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_status.StatusSaveLoadRoundTripTests -v`

Expected: PASS — Task 7 already implemented `save_status` / `load_status` / `PolicyMismatch`. If any test fails, fix the source — do NOT loosen the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_status.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): atomic save+load round-trip + policy-hash mismatch"
```

---

## Task 9: Resume — modify-state, save, reload, scheduler sees the change

**Files:**
- Modify: `tests/test_lifecycle_status.py`

- [ ] **Step 1: Write the failing resume test**

Append to `tests/test_lifecycle_status.py`:

```python
class StatusResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_status_resume_after_partial_completion(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            NodeState,
            ArtifactRecord,
            load_status,
            new_run_status,
            save_status,
        )

        policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="r-5", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        # Mark B1-brief complete and record its output as an artifact.
        status.nodes["B1-brief"].state = NodeState.COMPLETE
        status.nodes["B1-brief"].started_at = "2026-06-17T10:01:00Z"
        status.nodes["B1-brief"].completed_at = "2026-06-17T10:05:00Z"
        status.nodes["B1-brief"].attempts = 1
        status.artifacts["docs/product-brief.md"] = ArtifactRecord(
            path="docs/product-brief.md",
            produced_by_node="B1-brief",
            produced_at="2026-06-17T10:05:00Z",
            sha256="a" * 64,
        )

        target = self.dir / "lifecycle-status.json"
        save_status(target, status)

        loaded = load_status(target, expected_policy=policy)
        self.assertEqual(loaded.nodes["B1-brief"].state, NodeState.COMPLETE)
        self.assertEqual(loaded.nodes["B1-brief"].attempts, 1)
        self.assertEqual(loaded.nodes["B2-prd"].state, NodeState.PENDING)
        self.assertIn("docs/product-brief.md", loaded.artifacts)
        self.assertEqual(
            loaded.artifacts["docs/product-brief.md"].produced_by_node, "B1-brief"
        )

    def test_unknown_node_state_value_raises_clear_error(self) -> None:
        from story_automator.core.lifecycle_status import load_status

        bad = {
            "version": 1,
            "run_id": "r-6",
            "mode": "greenfield",
            "started_at": "2026-06-17T10:00:00Z",
            "policy_hash": "0" * 64,
            "nodes": {
                "B1-brief": {
                    "state": "not-a-real-state",
                    "attempts": 0,
                    "started_at": "",
                    "completed_at": "",
                    "last_error": "",
                    "gate_decision": None,
                    "gate_notes": "",
                }
            },
            "artifacts": {},
        }
        target = self.dir / "lifecycle-status.json"
        target.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_status(target)
```

(The `json` module was imported at the top of `tests/test_lifecycle_status.py` in Task 7 — no extra import is needed at the bottom.)

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_status.StatusResumeTests -v`

Expected: PASS — Task 7's `NodeState(value)` lookup raises `ValueError` for unknown values; the resume happy-path uses already-implemented save/load.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_status.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): resume after partial completion + unknown-state error path"
```

---

## Task 10: Scheduler — topological order (deterministic)

**Files:**
- Modify: `tests/test_lifecycle_scheduler.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`

- [ ] **Step 1: Write the failing topo-order tests**

Append to `tests/test_lifecycle_scheduler.py`:

```python
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class TopologicalOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy

        self.policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )

    def test_linear_chain_emits_in_dep_order(self) -> None:
        from story_automator.core.lifecycle_scheduler import topological_order

        order = topological_order(self.policy, mode="greenfield")
        self.assertEqual(order, ["B1-brief", "B2-prd", "B3-arch", "B3-epics"])

    def test_topo_order_lexicographic_when_independent(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import topological_order

        import json as _json

        # Three independent nodes — should come back in lex order regardless
        # of declaration order in the JSON.
        nodes_decl_order = ["Z-third", "A-first", "M-second"]
        raw = {
            "version": 1,
            "nodes": {
                name: {
                    "track": "bmm",
                    "phase": 1,
                    "skill": "bmad-noop",
                    "validator_skill": None,
                    "deps": [],
                    "input_artifacts": [],
                    "output_artifact": f"docs/{name}.md",
                    "verifier": "structural",
                    "gate": "auto",
                    "modes": ["greenfield"],
                    "agent_role": "analyst",
                    "interactive": False,
                }
                for name in nodes_decl_order
            },
            "entry": {"greenfield": ["A-first"], "brownfield": []},
        }
        policy = load_policy(_json.dumps(raw))
        self.assertEqual(
            topological_order(policy, mode="greenfield"),
            ["A-first", "M-second", "Z-third"],
        )

    def test_topo_order_filters_out_of_mode_nodes(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import topological_order

        import json as _json

        raw = {
            "version": 1,
            "nodes": {
                "B0-document": {
                    "track": "bmm",
                    "phase": 0,
                    "skill": "bmad-document-project",
                    "validator_skill": None,
                    "deps": [],
                    "input_artifacts": [],
                    "output_artifact": "docs/context.md",
                    "verifier": "structural",
                    "gate": "auto",
                    "modes": ["brownfield"],
                    "agent_role": "analyst",
                    "interactive": False,
                },
                "B1-brief": {
                    "track": "bmm",
                    "phase": 1,
                    "skill": "bmad-product-brief",
                    "validator_skill": None,
                    "deps": [],
                    "input_artifacts": [],
                    "output_artifact": "docs/product-brief.md",
                    "verifier": "structural",
                    "gate": "human",
                    "modes": ["greenfield", "brownfield"],
                    "agent_role": "analyst",
                    "interactive": True,
                },
            },
            "entry": {"greenfield": ["B1-brief"], "brownfield": ["B0-document"]},
        }
        policy = load_policy(_json.dumps(raw))
        # greenfield: B0-document is filtered out.
        self.assertEqual(topological_order(policy, mode="greenfield"), ["B1-brief"])
        # brownfield: both nodes; lex order applies.
        self.assertEqual(
            topological_order(policy, mode="brownfield"),
            ["B0-document", "B1-brief"],
        )

    def test_topo_order_invalid_mode_raises(self) -> None:
        from story_automator.core.lifecycle_scheduler import (
            SchedulerError,
            topological_order,
        )

        with self.assertRaises(SchedulerError):
            topological_order(self.policy, mode="bogus")

    def test_topo_order_empty_active_set_returns_empty_list(self) -> None:
        # A policy whose nodes are all greenfield-mode evaluated in brownfield
        # mode produces an empty active set; topological_order must return [].
        from story_automator.core.lifecycle_scheduler import topological_order

        self.assertEqual(topological_order(self.policy, mode="brownfield"), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_scheduler.TopologicalOrderTests -v`

Expected: FAIL — `topological_order` does not exist.

- [ ] **Step 3: Implement topological_order**

Replace the body of `lifecycle_scheduler.py`:

```python
"""Lifecycle DAG scheduler (W0-M01).

Pure-function topological scheduler over the macro-lifecycle DAG. Performs
no IO and no execution: callers pass a `Policy`, a `RunStatus`, an
`artifact_exists` callable, the run `mode`, and a `max_concurrency` cap,
and receive an ordered list of runnable node ids back. The phase-runner
(W0-M02) is responsible for actually invoking child agents and updating
node states.
"""

from __future__ import annotations

from collections.abc import Callable

from story_automator.core.lifecycle_policy import NodeDef, Policy
from story_automator.core.lifecycle_status import NodeState, RunStatus

__all__ = ["SchedulerError", "runnable_nodes", "topological_order"]

_VALID_MODES: frozenset[str] = frozenset({"greenfield", "brownfield"})


class SchedulerError(RuntimeError):
    """Raised on scheduler-internal invariant violations."""


def _active_nodes(policy: Policy, mode: str) -> dict[str, NodeDef]:
    """Restrict the DAG to nodes whose `modes` includes `mode`. Out-of-
    mode nodes are filtered out entirely; their existence as deps of
    in-mode nodes is invisible (treated as already-satisfied)."""

    if mode not in _VALID_MODES:
        raise SchedulerError(
            f"mode {mode!r} is not one of {sorted(_VALID_MODES)!r}"
        )
    return {node_id: node for node_id, node in policy.nodes.items() if mode in node.modes}


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
            if dep in active:  # out-of-mode deps are invisible
                in_degree[node.id] = in_degree[node.id] + 1

    queue: list[str] = sorted(n for n, d in in_degree.items() if d == 0)
    order: list[str] = []
    while queue:
        node_id = queue.pop(0)
        order.append(node_id)
        for candidate in active.values():
            if node_id in candidate.deps and candidate.id not in order and candidate.id not in queue:
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
    """Return runnable nodes. Mode is read from status.mode (single source of
    truth — eliminates "mode arg drifts from status" footguns). Full
    implementation lands in Task 11."""

    raise NotImplementedError
```

> The two `O(N²)` edge scans (in `_validate_acyclic` from Task 5 and `topological_order` here) are intentional: simple, easy to read, fast for the lifecycle DAG's expected size. Don't optimize prematurely.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_scheduler -v`

Expected: PASS (5 topo tests + 3 skeleton tests = 8 total in this file).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py \
        tests/test_lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): deterministic topological order with mode-aware filtering"
```

---

## Task 11: Scheduler — runnable_nodes (deps complete + inputs exist)

**Files:**
- Modify: `tests/test_lifecycle_scheduler.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`

- [ ] **Step 1: Write the failing runnable tests**

Append to `tests/test_lifecycle_scheduler.py`:

```python
class RunnableNodesTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import new_run_status

        self.policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        self.status = new_run_status(
            self.policy,
            run_id="r-7",
            mode="greenfield",
            started_at="2026-06-17T10:00:00Z",
        )

    def test_initial_state_only_entry_node_is_runnable(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes

        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _path: False,
            max_concurrency=10,
        )
        # B1-brief has no deps and no input_artifacts; it's runnable.
        self.assertEqual(out, ["B1-brief"])

    def test_node_blocked_until_deps_complete(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        # Even if the input artifact magically "exists", B2-prd is blocked
        # until B1-brief is COMPLETE.
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _path: True,
            max_concurrency=10,
        )
        self.assertEqual(out, ["B1-brief"])  # only B1; B2 still blocked by B1

        # Mark B1-brief complete; B2-prd should now be runnable iff inputs exist.
        self.status.nodes["B1-brief"].state = NodeState.COMPLETE
        out2 = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda path: path == "docs/product-brief.md",
            max_concurrency=10,
        )
        self.assertEqual(out2, ["B2-prd"])

    def test_node_blocked_when_input_artifact_missing(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        self.status.nodes["B1-brief"].state = NodeState.COMPLETE
        # B2-prd needs docs/product-brief.md — say it doesn't exist on disk.
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _path: False,
            max_concurrency=10,
        )
        self.assertEqual(out, [])

    def test_complete_and_failed_nodes_never_returned(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        self.status.nodes["B1-brief"].state = NodeState.COMPLETE
        self.status.nodes["B2-prd"].state = NodeState.FAILED
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _p: True,
            max_concurrency=10,
        )
        # B2-prd has FAILED so it isn't pending; B3-arch is blocked by B2-prd
        # not being COMPLETE.
        self.assertEqual(out, [])

    def test_running_node_is_not_returned_again(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        # Simulate phase-runner picked B1-brief and marked it RUNNING.
        self.status.nodes["B1-brief"].state = NodeState.RUNNING
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _p: True,
            max_concurrency=10,
        )
        self.assertEqual(out, [])  # RUNNING is not pending; B2 still blocked.

    def test_awaiting_approval_blocks_downstream(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        self.status.nodes["B1-brief"].state = NodeState.AWAITING_APPROVAL
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _p: True,
            max_concurrency=10,
        )
        # B1-brief is not yet COMPLETE so downstream nodes stay blocked.
        self.assertEqual(out, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_scheduler.RunnableNodesTests -v`

Expected: FAIL — `runnable_nodes` raises `NotImplementedError`.

- [ ] **Step 3: Implement runnable_nodes**

In `lifecycle_scheduler.py`, replace the `runnable_nodes` stub with:

```python
def runnable_nodes(
    policy: Policy,
    status: RunStatus,
    *,
    artifact_exists: Callable[[str], bool],
    max_concurrency: int = 1,
) -> list[str]:
    """Return up to `max_concurrency` runnable nodes for the run.

    Run mode is read from `status.mode` — single source of truth. A node
    is runnable when:
      1. it's in-mode (its `modes` includes `status.mode`),
      2. its status is `PENDING`,
      3. every (in-mode) dep is `COMPLETE`,
      4. every `input_artifact` returns True from `artifact_exists`.

    Result order is the topological order from `topological_order`
    (deterministic, lex-tie-broken). Capped at `max_concurrency`.
    The scheduler does NOT mutate `status` — that's the phase-runner's
    job in W0-M02. Out-of-mode nodes (whose state is `SKIPPED` per
    `new_run_status`) and `FAILED`/`AWAITING_APPROVAL`/`RUNNING`/
    `COMPLETE` nodes are all skipped at the `state != PENDING` check.
    """

    if max_concurrency < 1:
        raise SchedulerError(
            f"max_concurrency must be >= 1, got {max_concurrency!r}"
        )

    mode = status.mode
    active = _active_nodes(policy, mode)
    order = topological_order(policy, mode=mode)

    runnable: list[str] = []
    for node_id in order:
        if len(runnable) >= max_concurrency:
            break
        node = active[node_id]
        run = status.nodes.get(node_id)
        if run is None or run.state != NodeState.PENDING:
            continue
        if not all(
            status.nodes[dep].state == NodeState.COMPLETE
            for dep in node.deps
            if dep in active
        ):
            continue
        if not all(artifact_exists(path) for path in node.input_artifacts):
            continue
        runnable.append(node_id)

    return runnable
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_scheduler -v`

Expected: PASS (14 tests in this file).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py \
        tests/test_lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): runnable_nodes with deps-complete + inputs-exist + state-filter"
```

---

## Task 12: Scheduler — bounded concurrency cap

**Files:**
- Modify: `tests/test_lifecycle_scheduler.py`

- [ ] **Step 1: Write the failing concurrency tests**

Append to `tests/test_lifecycle_scheduler.py`:

```python
class ConcurrencyCapTests(unittest.TestCase):
    def _diamond_policy(self):
        """B1 -> {B2a, B2b, B2c}; all three are independent siblings."""
        from story_automator.core.lifecycle_policy import load_policy
        import json as _json

        raw = {
            "version": 1,
            "nodes": {
                "B1": {
                    "track": "bmm",
                    "phase": 1,
                    "skill": "bmad-noop",
                    "validator_skill": None,
                    "deps": [],
                    "input_artifacts": [],
                    "output_artifact": "docs/b1.md",
                    "verifier": "structural",
                    "gate": "auto",
                    "modes": ["greenfield"],
                    "agent_role": "analyst",
                    "interactive": False,
                },
                **{
                    name: {
                        "track": "bmm",
                        "phase": 2,
                        "skill": "bmad-noop",
                        "validator_skill": None,
                        "deps": ["B1"],
                        "input_artifacts": ["docs/b1.md"],
                        "output_artifact": f"docs/{name}.md",
                        "verifier": "structural",
                        "gate": "auto",
                        "modes": ["greenfield"],
                        "agent_role": "analyst",
                        "interactive": False,
                    }
                    for name in ("B2a", "B2b", "B2c")
                },
            },
            "entry": {"greenfield": ["B1"], "brownfield": []},
        }
        return load_policy(_json.dumps(raw))

    def test_cap_limits_returned_runnable_set(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState, new_run_status

        policy = self._diamond_policy()
        status = new_run_status(
            policy, run_id="r-c", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        status.nodes["B1"].state = NodeState.COMPLETE

        # All three B2* are eligible; cap to 2.
        out = runnable_nodes(
            policy,
            status,
            artifact_exists=lambda _p: True,
            max_concurrency=2,
        )
        self.assertEqual(out, ["B2a", "B2b"])  # lex order, first two

        # Cap to 1 keeps just B2a.
        out1 = runnable_nodes(
            policy,
            status,
            artifact_exists=lambda _p: True,
            max_concurrency=1,
        )
        self.assertEqual(out1, ["B2a"])

        # Cap >= count returns all.
        out_all = runnable_nodes(
            policy,
            status,
            artifact_exists=lambda _p: True,
            max_concurrency=10,
        )
        self.assertEqual(out_all, ["B2a", "B2b", "B2c"])

    def test_cap_zero_raises(self) -> None:
        from story_automator.core.lifecycle_scheduler import (
            SchedulerError,
            runnable_nodes,
        )
        from story_automator.core.lifecycle_status import new_run_status

        policy = self._diamond_policy()
        status = new_run_status(
            policy, run_id="r-c", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        with self.assertRaises(SchedulerError):
            runnable_nodes(
                policy,
                status,
                artifact_exists=lambda _p: True,
                max_concurrency=0,
            )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_scheduler.ConcurrencyCapTests -v`

Expected: PASS — Task 11 already implements the cap. If a test fails, fix the source — do NOT lower the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): bounded-concurrency cap (lex-first-N) + invalid-cap error"
```

---

## Task 13: End-to-end acceptance — schema round-trip + scheduler selects + resume reconstructs

**Files:**
- Create: `tests/test_lifecycle_acceptance.py`
- Create: `tests/fixtures/lifecycle/brownfield-minimal.policy.json`

- [ ] **Step 1: Write the brownfield fixture**

Create `tests/fixtures/lifecycle/brownfield-minimal.policy.json`:

```json
{
  "version": 1,
  "nodes": {
    "B0-document-project": {
      "track": "bmm",
      "phase": 0,
      "skill": "bmad-document-project",
      "validator_skill": null,
      "deps": [],
      "input_artifacts": [],
      "output_artifact": "docs/project-context.md",
      "verifier": "structural",
      "gate": "auto",
      "modes": ["brownfield"],
      "agent_role": "analyst",
      "interactive": false
    },
    "B2-prd": {
      "track": "bmm",
      "phase": 2,
      "skill": "bmad-create-prd",
      "validator_skill": "bmad-validate-prd",
      "deps": ["B0-document-project"],
      "input_artifacts": ["docs/project-context.md"],
      "output_artifact": "docs/prd.md",
      "verifier": "prd_valid",
      "gate": "human",
      "modes": ["brownfield"],
      "agent_role": "pm",
      "interactive": true
    },
    "B3-arch": {
      "track": "bmm",
      "phase": 3,
      "skill": "bmad-create-architecture",
      "validator_skill": null,
      "deps": ["B2-prd"],
      "input_artifacts": ["docs/prd.md"],
      "output_artifact": "docs/architecture.md",
      "verifier": "structural",
      "gate": "human",
      "modes": ["brownfield"],
      "agent_role": "architect",
      "interactive": false
    }
  },
  "entry": {"greenfield": [], "brownfield": ["B0-document-project"]}
}
```

- [ ] **Step 2: Write the acceptance test**

Create `tests/test_lifecycle_acceptance.py`:

```python
"""W0-M01 acceptance: schema round-trips; scheduler selects correct runnable
nodes; resume reconstructs state. Mirrors the build-spec-full.md §1 contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class W0M01AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_schema_round_trips_greenfield(self) -> None:
        from story_automator.core.lifecycle_policy import (
            canonical_policy_json,
            load_policy,
            policy_to_dict,
        )

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )
        policy_a = load_policy(text)
        policy_b = load_policy(json.dumps(policy_to_dict(policy_a)))
        self.assertEqual(canonical_policy_json(policy_a), canonical_policy_json(policy_b))

    def test_schema_round_trips_brownfield(self) -> None:
        from story_automator.core.lifecycle_policy import (
            canonical_policy_json,
            load_policy,
            policy_to_dict,
        )

        text = (FIXTURE_DIR / "brownfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )
        policy_a = load_policy(text)
        policy_b = load_policy(json.dumps(policy_to_dict(policy_a)))
        self.assertEqual(canonical_policy_json(policy_a), canonical_policy_json(policy_b))

    def test_scheduler_selects_correct_runnable_sequence(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState, new_run_status

        policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="r-acc", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )

        artifacts_present: set[str] = set()

        def exists(path: str) -> bool:
            return path in artifacts_present

        # Step 1: only B1-brief is runnable.
        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            ["B1-brief"],
        )

        # Simulate B1 completing and producing its artifact.
        status.nodes["B1-brief"].state = NodeState.COMPLETE
        artifacts_present.add("docs/product-brief.md")

        # Step 2: B2-prd unblocks.
        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            ["B2-prd"],
        )

        # Simulate B2 completing.
        status.nodes["B2-prd"].state = NodeState.COMPLETE
        artifacts_present.add("docs/prd.md")

        # Step 3: B3-arch unblocks.
        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            ["B3-arch"],
        )

        # B3-arch completes.
        status.nodes["B3-arch"].state = NodeState.COMPLETE
        artifacts_present.add("docs/architecture.md")

        # Step 4: B3-epics unblocks (needs both prd + architecture).
        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            ["B3-epics"],
        )

        # B3-epics completes — nothing left to run.
        status.nodes["B3-epics"].state = NodeState.COMPLETE
        artifacts_present.add("epics/")
        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            [],
        )

    def test_resume_reconstructs_state_after_persist(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import (
            ArtifactRecord,
            NodeState,
            load_status,
            new_run_status,
            save_status,
        )

        policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="r-resume", mode="greenfield",
            started_at="2026-06-17T10:00:00Z",
        )

        # Drive partway: B1 done + artifact recorded.
        status.nodes["B1-brief"].state = NodeState.COMPLETE
        status.artifacts["docs/product-brief.md"] = ArtifactRecord(
            path="docs/product-brief.md",
            produced_by_node="B1-brief",
            produced_at="2026-06-17T10:05:00Z",
            sha256="a" * 64,
        )

        target = self.dir / "lifecycle-status.json"
        save_status(target, status)

        # Simulate a crash + restart by reloading from disk into a fresh object.
        revived = load_status(target, expected_policy=policy)

        # Scheduler against the revived status must pick exactly B2-prd next.
        out = runnable_nodes(
            policy, revived,
            artifact_exists={"docs/product-brief.md"}.__contains__,
            max_concurrency=10,
        )
        self.assertEqual(out, ["B2-prd"])
        # And the artifact registry survived the round-trip.
        self.assertEqual(
            revived.artifacts["docs/product-brief.md"].produced_by_node, "B1-brief"
        )

    def test_brownfield_scheduler_starts_at_b0_document_project(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import new_run_status

        policy = load_policy(
            (FIXTURE_DIR / "brownfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="r-bf", mode="brownfield",
            started_at="2026-06-17T10:00:00Z",
        )
        out = runnable_nodes(
            policy, status,
            artifact_exists=lambda _p: False,
            max_concurrency=10,
        )
        self.assertEqual(out, ["B0-document-project"])
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_acceptance -v`

Expected: PASS (5 acceptance tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_lifecycle_acceptance.py \
        tests/fixtures/lifecycle/brownfield-minimal.policy.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): W0-M01 acceptance — round-trip + scheduler + resume"
```

---

## Task 14: Quality gates — ruff, module size, full suite, coverage

**Files:** none modified unless a gate fails.

- [ ] **Step 1: Ruff lint**

Run: `python -m ruff check skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py tests/test_lifecycle_policy.py tests/test_lifecycle_status.py tests/test_lifecycle_scheduler.py tests/test_lifecycle_acceptance.py`

Expected: exit 0. If failures arise, fix the source — do not suppress with `# noqa` unless the lint is genuinely wrong.

- [ ] **Step 2: Ruff format check**

Run: `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py tests/test_lifecycle_policy.py tests/test_lifecycle_status.py tests/test_lifecycle_scheduler.py tests/test_lifecycle_acceptance.py`

If it fails: run `python -m ruff format <same paths>` and re-run the check.

- [ ] **Step 3: Module size guardrail**

Each new module must stay under the 500-LOC soft limit from CLAUDE.md.

On bash: `wc -l skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`

Expected: each ≤ 500. Typical expected sizes: policy ~280, status ~220, scheduler ~120 LOC.

- [ ] **Step 4: Import allowlist audit**

Run: `python -c "import ast, sys; mods=['skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py','skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py','skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py']; allowed=set(['__future__','collections','collections.abc','dataclasses','enum','hashlib','json','pathlib','typing','story_automator.core.atomic_io','story_automator.core.lifecycle_policy','story_automator.core.lifecycle_status']); [print(m, n.module or n.names[0].name) for m in mods for n in ast.walk(ast.parse(open(m).read())) if isinstance(n,(ast.Import,ast.ImportFrom))]"`

Manually verify every printed import is in the allowlist (or is the project's `story_automator.core.*`). No `filelock`, `psutil`, or any third-party module should appear directly in these new files — they're transitively pulled in by `atomic_io.write_atomic_text`, which is the only such bridge.

- [ ] **Step 5: Full suite regression**

Run: `npm run test:python`

Expected: PASS — all previously-existing tests + the 4 new lifecycle test files (`test_lifecycle_policy.py`, `test_lifecycle_status.py`, `test_lifecycle_scheduler.py`, `test_lifecycle_acceptance.py`) all green. Approximate new test count: ~35-40.

- [ ] **Step 6: Coverage gate for new modules**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/lifecycle_policy,skills/bmad-story-automator/src/story_automator/core/lifecycle_status,skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler \
  -m unittest discover -s tests
python -m coverage report -m --fail-under=85
```

Expected: PASS (≥85% on each new module). If a branch is uncovered, add a focused test — do NOT lower the gate. The most-likely uncovered branches: error-message format edge cases in `_parse_node`, the `SchedulerError` raise in `topological_order` (caught by Task 10's `bogus mode` test).

- [ ] **Step 7: `npm run verify` smoke**

Run: `npm run verify`

Expected: PASS. This runs `test:python`, `pack:dry-run`, `test:cli`, and `test:smoke` — the canonical release-style gate from CLAUDE.md.

- [ ] **Step 8: Commit any formatting fixes (skip if Step 2 reported no changes)**

```bash
git add -u skills/bmad-story-automator/src/story_automator/core/ tests/
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(lifecycle): ruff format pass"
```

If no fixes were needed, skip — do not create an empty commit.

---

## Task 15: Operator documentation — concise module map + how to extend

**Files:**
- Modify: `docs/superpowers/specs/lifecycle/build-spec-full.md` (footer note only — append a "W0-M01 status" line; **do not edit any other section**)
- Create: `docs/changelog/2026-06-17.md` (or append to today's existing file if present)

- [ ] **Step 1: Append a status note to the lifecycle build spec**

Open `docs/superpowers/specs/lifecycle/build-spec-full.md`. Locate the end of the document. Append (do NOT modify any pre-existing section):

```markdown

---

## Implementation status

- **W0-M01 (Lifecycle data model + DAG scheduler)** — landed YYYY-MM-DD (today). Three modules: `core/lifecycle_policy.py`, `core/lifecycle_status.py`, `core/lifecycle_scheduler.py`. Scheduler is a pure function (no IO, no execution); status persistence uses `core.atomic_io.write_atomic_text`. Status file is JSON (`lifecycle-status.json`) — see plan §2 for the no-deps rationale around the spec's `.yaml` filename. Phase-runner, verifiers, gates, telemetry events, and CLI surface remain unimplemented and are scheduled for W0-M02 / W0-M03 / W0-M04 respectively.
```

Replace `YYYY-MM-DD` with today's date once you commit (or leave it as a literal and adjust in the commit message).

- [ ] **Step 2: Add a dated changelog entry**

If `docs/changelog/2026-06-17.md` does not exist, create it:

```markdown
# 2026-06-17

## 261117 - [FULL] W0-M01 lifecycle data model + DAG scheduler

### Summary
Adds the macro-lifecycle layer's data model and scheduler — three new sibling modules under `core/` that load + validate the `lifecycle-policy.json` schema, persist per-run state to `lifecycle-status.json` (atomic, crash-safe), and select runnable nodes from the DAG with deterministic topological order, mode-aware filtering, and bounded concurrency. Pure-Python, stdlib-only, zero new dependencies.

### Added
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py` — `NodeDef`, `EntryMap`, `Policy` dataclasses; JSON loader; structural + closed-world + cycle validators; canonical-form hashing.
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py` — `NodeState` enum (7 states); `NodeRun`, `ArtifactRecord`, `RunStatus`; atomic save/load reusing `core.atomic_io.write_atomic_text`; `PolicyMismatch` typed exception.
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py` — `topological_order` (Kahn's, lex tie-break); `runnable_nodes` (deps-complete + inputs-exist + state-filter + concurrency cap).
- `tests/test_lifecycle_policy.py`, `tests/test_lifecycle_status.py`, `tests/test_lifecycle_scheduler.py`, `tests/test_lifecycle_acceptance.py`.
- 7 fixtures under `tests/fixtures/lifecycle/`.

### Files
- `core/lifecycle_policy.py`, `core/lifecycle_status.py`, `core/lifecycle_scheduler.py` (new)
- `tests/test_lifecycle_{policy,status,scheduler,acceptance}.py` (new)
- `tests/fixtures/lifecycle/*.policy.json` (new)
- `docs/superpowers/specs/lifecycle/build-spec-full.md` (appended status footnote)

### QA Notes
- Lint: `ruff check` clean on all new modules.
- Tests: `npm run test:python` green; the four new lifecycle test files contribute ~38 tests.
- Coverage: ≥85% on each new module.
- Module size: each module < 300 LOC; well under the 500-LOC soft limit.
- Cross-platform: tests use stdlib + `unittest`; no subprocess, no tmux, no network; runs on Windows git-bash and WSL Ubuntu.
- Guardrail compliance: no third-party imports introduced; `core/telemetry_events.py` untouched.
```

Replace `261117` with today's `YYMMDD` if different.

- [ ] **Step 3: Commit docs**

```bash
git add docs/superpowers/specs/lifecycle/build-spec-full.md docs/changelog/2026-06-17.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(lifecycle): W0-M01 status footnote + changelog entry"
```

> Per CLAUDE.md hard guardrails: do NOT modify any pre-existing changelog heading or sub-section heading. Only append new content. The `261117` date heading is new; if it already exists in `docs/changelog/2026-06-17.md`, append the bullets under the existing heading instead of duplicating it.

---

## Self-Review Checklist

**1. Spec coverage (build-spec-full.md §1 + design-spec.md §3):**
- `lifecycle-policy.json` node schema with all 12 documented fields — Task 2 (NodeDef dataclass).
- `entry.{greenfield,brownfield}` — Task 2 (EntryMap dataclass).
- Loader + validator — Tasks 2, 3, 4, 5.
- `lifecycle-status.yaml` per-run node states + artifact registry — Task 7 (RunStatus + ArtifactRecord; JSON not YAML — see "Design decisions" §1).
- `atomic_write` reuse — Task 7 (uses `core.atomic_io.write_atomic_text`).
- Topological scheduler with bounded concurrency — Tasks 10, 11, 12.
- Resumable from disk — Tasks 7, 8, 9; Task 13 (acceptance).
- §1 acceptance: schema round-trips (Task 6, Task 13); scheduler selects correct runnable nodes (Task 11, Task 13); resume reconstructs state (Task 9, Task 13).

**2. Placeholder scan:** No "TODO", "TBD", or "implement later" markers in code blocks. Each task supplies the actual code the engineer types.

**3. Type consistency:**
- `Policy.nodes: dict[str, NodeDef]` — used identically across loader, validator, scheduler.
- `NodeState` enum values are referenced as `NodeState.PENDING` / `NodeState.COMPLETE` consistently in scheduler and acceptance tests.
- `runnable_nodes(policy, status, *, mode, artifact_exists, max_concurrency=1) -> list[str]` — signature stable across Task 10 stub, Task 11 implementation, Tasks 12 and 13 tests.
- `topological_order(policy, *, mode) -> list[str]` — signature stable across Task 10.
- `save_status(path, status) -> None` and `load_status(path, *, expected_policy=None) -> RunStatus` — signatures stable across Tasks 7-9 and 13.
- `_active_nodes(policy, mode) -> dict[str, NodeDef]` and the `_VALID_MODES` frozenset are shared between `topological_order` and `runnable_nodes` — defined once, used twice.

**4. Cross-task name drift:** No drift. The scheduler's `_active_nodes` is reused in both top-level functions; the policy's `_validate_acyclic` and the scheduler's `topological_order` share Kahn's-algorithm logic but operate on different inputs (full policy.nodes vs. mode-filtered subset) — deliberate, not duplication-to-DRY.

**5. Guardrail compliance:**
- No new third-party imports — verified in Task 14 Step 4.
- `core/telemetry_events.py` untouched — verified by absence of any `Edit`/`Write` against that path in the plan.
- No fifth changelog tag — Task 15 uses `[FULL]` from the existing four-tag vocabulary.
- Module size ≤ 500 LOC — verified in Task 14 Step 3.
- Conventional Commits + `Generated-By:` trailer — every commit step in the plan uses both.

**6. TDD discipline:** Every task that introduces production code follows "test first → run failing → implement → run green → commit." Tasks 6, 8, 9, 12 are pure-test additions documenting behavior the prior task already implemented — these are explicitly flagged as "should already pass."

---

## Notes for the implementer

1. **Why three modules instead of one.** Separating policy/status/scheduler enforces the dependency direction: scheduler depends on policy + status; status depends on policy (for the hash); policy depends on nothing. A single `lifecycle.py` would invite circular reasoning and tempt later milestones to add execution-side concerns into the data model.

2. **Why the scheduler is pure.** Phase-runner (W0-M02) needs to call the scheduler tightly between every state transition. If the scheduler did IO or emitted events, every call site would need a mock harness. Pure functions are trivial to test and trivial to compose; the cost is a slightly larger caller (the phase-runner threads the status object through). Worth it.

3. **Why JSON, not YAML, for the status file.** The CLAUDE.md guardrail forbids new third-party deps. Python stdlib has no YAML. A hand-rolled YAML subset that supports the actual shape (nested dicts, enum strings, ISO timestamps, SHA-256 hashes) is approximately the same effort as the existing `parse_simple_frontmatter` — useful, but not in scope for W0-M01. JSON satisfies every documented use case in the spec.

4. **Why `policy_hash` rather than a version string.** A version string is human-friendly but doesn't catch silent edits (someone fixes a typo in a node's `output_artifact` path without bumping the version). The canonical SHA-256 hash catches every byte-level change. A `version: int` field stays as the schema-format version (currently `1`); the hash is the content fingerprint.

5. **Why lex tie-breaking instead of declared order.** JSON object key order is preserved in Python 3.7+, BUT the topological scheduler must be deterministic across input forms. Tests that load a policy and then load the same policy with permuted node-declaration order (Task 6 round-trip) would otherwise produce different scheduler outputs — a confusing test failure pattern. Lex order eliminates the source of nondeterminism.

6. **Why no CLI command in W0-M01.** The acceptance criteria are about the data model + scheduler API. A CLI command (`lifecycle-helper status`) adds testing surface (output parsing, exit-code semantics) that doesn't validate any §1 behavior. CLI lives in W0-M03/M04. Implementers should resist the urge.

7. **Why `_active_nodes` filters silently.** Out-of-mode nodes are not an error — they're legitimately not part of this run. The scheduler simply doesn't see them. A "node-skipped" telemetry event would be useful but belongs to W0-M02's phase-runner (this is data flow, not control flow).

8. **The `tests/fixtures/lifecycle/full-both-modes.policy.json` fixture in the File-Structure table is NOT consumed by any task** in this plan — it's listed as an anticipated fixture for W0-M02 (phase-runner) end-to-end testing. If you're strict about YAGNI, skip creating it in W0-M01 and create it as part of W0-M02. The same goes for `invalid-mode.policy.json` if not referenced — only create what tests actually consume. (The plan above only writes the fixtures that are actually consumed: `greenfield-minimal`, `brownfield-minimal`, `invalid-bad-enum`, `invalid-missing-dep`, `invalid-cycle`, `invalid-entry-ref`.)
