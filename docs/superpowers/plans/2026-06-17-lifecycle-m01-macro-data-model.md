# Lifecycle M01 — Macro Data Model & State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the macro lifecycle layer's data model + scheduler — three pure-Python modules (`lifecycle_policy.py`, `lifecycle_status.py`, `lifecycle_scheduler.py`) that load and validate a `lifecycle-policy.json` schema, persist per-run state in a `lifecycle-status.yaml` file (JSON syntax, valid YAML 1.2), and select runnable nodes by walking the DAG. This is the foundation §1 of `docs/superpowers/specs/lifecycle/build-spec-core.md`. M02 builds the phase-runner on top; M01 introduces **no** telemetry, **no** CLI, and **no** child-process spawning.

**Architecture:** Three sibling modules under `skills/bmad-story-automator/src/story_automator/core/`. All three are stdlib-only (plus `core/common.iso_now` and `core/atomic_io.write_atomic_text` for IO atomicity) and obey the codebase's hard guardrail: no new third-party imports beyond stdlib + `filelock` + `psutil`. The data model uses `@dataclass(frozen=True, kw_only=True)` with PEP-604 unions. The scheduler is pure-functional: it takes a `LifecyclePolicy` + `LifecycleStatus` and returns a tuple of `LifecycleNode` instances; it never mutates inputs and never touches the filesystem itself.

**Tech Stack:** Python 3.11+, stdlib only (`json`, `dataclasses`, `enum`, `pathlib`, `typing`), reuse of `story_automator.core.common.iso_now` and `story_automator.core.atomic_io.write_atomic_text`, `unittest.TestCase` for tests, `ruff` for lint/format.

---

## Context for the Engineer

You are implementing M01 of the lifecycle orchestrator on top of the hardened `bmad-story-automator` sprint engine. Internalize these facts before writing code:

1. **No new third-party deps.** The hard guardrail in `CLAUDE.md` and the spec project-context block both prohibit imports beyond stdlib + `filelock` + `psutil`. `lifecycle_status.yaml` is therefore written as **JSON syntax with a `.yaml` extension** — JSON 1.0 is a strict subset of YAML 1.2, so the file remains valid YAML, and we avoid pulling in PyYAML. The wider "real YAML" question (block-style scalars, anchors) is deferred; this milestone never writes anything that isn't legal JSON.
2. **Do NOT modify `core/telemetry_events.py`.** That module is M01-owned in the broader BMAD program and the spec explicitly forbids changes outside its owning milestone. New telemetry events belong in a sibling `core/lifecycle_events.py` that **M02 (not M01)** introduces. This M01 does NOT emit any telemetry events. The data model is intentionally side-effect-free except for the two `write_lifecycle_status` calls in `lifecycle_status.py`.
3. **Atomic IO.** Use `story_automator.core.atomic_io.write_atomic_text` (per-path threading lock + fsync + Windows-replace retries). Do NOT re-implement temp-file dancing. Do NOT use the simpler `core.common.write_atomic` for status writes — the lifecycle status will be refreshed under cross-process contention in later milestones, and `write_atomic_text` is the contention-safe variant.
4. **Tests live at the repo-root `tests/` directory** — not the skill-level `skills/bmad-story-automator/tests/` tree. The spec defines the canonical gate as "the full suite on Linux/WSL (currently 1482 passing) + `ruff check skills tests` clean," and `npm run test:python` discovers only the root `tests/`. New lifecycle tests MUST be discoverable by the root suite.
5. **No CLI surface in this milestone.** No `commands/lifecycle_*.py`. No `bin/` entries. M02 adds the `phase-runner` subcommand; M03 adds approval-gate CLI. M01 ships pure library modules + tests.
6. **No `Optional` / `Union`** — use PEP-604 unions everywhere (`float | None`, `tuple[str, ...]`).
7. **First non-comment line** in every new module: `from __future__ import annotations`.
8. **LF line endings only.** All snapshot/format assertions compare against literal `"\n"`-joined strings — never use `os.linesep`.
9. **Frozen + kw-only dataclasses.** All data carriers (`LifecycleNode`, `LifecyclePolicy`, `NodeRecord`, `ArtifactRecord`, `LifecycleStatus`) are `frozen=True, kw_only=True`. Collections are `tuple[...]` not `list[...]` so the frozen guarantee is real.
10. **Determinism.** `select_runnable` must return a tuple in a **stable order**: topological-then-lexicographic-by-node-id. Two calls with the same `(policy, status)` must produce byte-equal tuples. Tests assert this directly.
11. **No `os.path` string-joining.** Use `pathlib.Path` everywhere. POSIX separators internally; the IO layer normalizes per-OS.
12. **Placeholder-token discipline.** Source files must not contain the literal substrings `TODO`, `FIXME`, `XXXX`, or `TBDX` (the placeholder grep is enforced repo-wide). Describe numeric formats as "four-decimal-place" prose, not glyphs.
13. **No `print()` and no `logging` calls in these three modules.** They are pure data + pure functions. Diagnostic surfacing is the runner's job (M02).
14. **Anti-scope:** No phase-runner. No telemetry events. No approval-gate semantics (just the **state** enum that records gate outcomes). No agent spawning. No artifact-path resolution (artifact ids are opaque strings). No CLI. No `__init__.py` modifications beyond what is strictly needed to export the new modules (none expected — `story_automator.core` doesn't re-export from `__init__.py`).

---

## File Structure

**Create:**
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py` (target ~250 LOC, hard cap 500)
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py` (target ~220 LOC, hard cap 500)
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py` (target ~150 LOC, hard cap 500)
- `tests/test_lifecycle_policy.py`
- `tests/test_lifecycle_status.py`
- `tests/test_lifecycle_scheduler.py`
- `tests/fixtures/lifecycle/policy-bridge.json`
- `tests/fixtures/lifecycle/policy-minimal.json`

**Modify:** none. **Delete:** none.

`tests/fixtures/lifecycle/` is a new sub-directory; Python doesn't need an `__init__.py` for non-package fixture data.

---

## Module surface (reference card — implement exactly these names)

`lifecycle_policy.py` `__all__`:
- `ALLOWED_GATES` (`("auto", "human")`)
- `ALLOWED_MODES` (`("greenfield", "brownfield")`)
- `EntrySection` — frozen dataclass: `greenfield: tuple[str, ...]`, `brownfield: tuple[str, ...]`
- `LifecycleNode` — frozen dataclass with the exact spec field set (see Task 2)
- `LifecyclePolicy` — frozen dataclass: `version: int`, `nodes: tuple[LifecycleNode, ...]`, `entry: EntrySection`; `node_by_id(node_id) -> LifecycleNode | None` method; `to_dict() -> dict[str, Any]` method (for round-trip)
- `PolicyLoadError(ValueError)`
- `load_lifecycle_policy(path: str | Path) -> LifecyclePolicy`
- `validate_lifecycle_policy(policy: LifecyclePolicy) -> None`

`lifecycle_status.py` `__all__`:
- `NodeState` — Enum: `PENDING`, `RUNNING`, `VERIFIED`, `AWAITING_APPROVAL`, `APPROVED`, `COMPLETE`, `FAILED` (lowercase values)
- `LEGAL_TRANSITIONS` — `frozenset[tuple[NodeState, NodeState]]`
- `ArtifactRecord` — frozen dataclass: `artifact_id`, `path`, `produced_by_node`, `produced_at`
- `NodeRecord` — frozen dataclass: `node_id`, `state: NodeState`, `updated_at`, `notes: str = ""`
- `LifecycleStatus` — frozen dataclass: `run_id`, `nodes: dict[str, NodeRecord]` (insertion-ordered), `artifacts: dict[str, ArtifactRecord]`, `updated_at`; methods `with_node`, `with_artifact`, `to_dict`
- `StatusLoadError(ValueError)`
- `load_lifecycle_status(path) -> LifecycleStatus`
- `write_lifecycle_status(status, path) -> None`
- `advance_node_state(status, node_id, new_state, *, now=None, notes="") -> LifecycleStatus`

`lifecycle_scheduler.py` `__all__`:
- `SchedulerError(ValueError)`
- `topo_sort(policy) -> tuple[str, ...]`
- `select_runnable(*, policy, status, max_concurrent=0) -> tuple[LifecycleNode, ...]`

The two error classes both subclass `ValueError` (not each other), so call-sites can catch the lifecycle layer with `except (PolicyLoadError, StatusLoadError, SchedulerError)` while existing `ValueError`-catching code remains source-compatible.

---

## Semantic decisions (locked at planning time)

1. **A dep is satisfied when its node state is `APPROVED` or `COMPLETE`.** The spec phrase "all deps are complete+approved" describes the two terminal-post-gate states: human-gated deps reach `APPROVED` after operator sign-off (then later `COMPLETE` after the run finalizes); auto-gated deps reach `COMPLETE` directly from `VERIFIED`. Downstream work is unblocked as soon as the gate clears, which matches the spec's "deliberate human checkpoints that don't degrade to rubber-stamping" intent.
2. **`input_artifacts` and `output_artifact` are opaque string ids.** They are NOT filesystem paths in M01. M02's `phase-runner` will resolve ids to paths when it spawns the child agent. The scheduler's artifact gate checks `all(aid in status.artifacts for aid in node.input_artifacts)` — presence-by-key.
3. **`output_artifact = ""` (empty string) is legal** and means the node produces no tracked artifact (e.g. an approval-recording node). Validator only enforces uniqueness for **non-empty** `output_artifact` values.
4. **Cycle detection lives in `validate_lifecycle_policy`**, not in the scheduler — the DAG-ness is a structural property of the policy, and we want load-time failure rather than a confusing scheduler error mid-run. The scheduler may assume its input is a DAG.
5. **State-machine legal transitions** (codified as `LEGAL_TRANSITIONS`):
   - `PENDING -> RUNNING`
   - `RUNNING -> VERIFIED | FAILED`
   - `VERIFIED -> AWAITING_APPROVAL | COMPLETE` (gate=human routes to AWAITING_APPROVAL, gate=auto routes to COMPLETE — the validator/runner picks; the data layer just allows both edges)
   - `AWAITING_APPROVAL -> APPROVED | FAILED` (FAILED = operator rejected and course-correct ran out)
   - `APPROVED -> COMPLETE`
   - `FAILED -> RUNNING` (retry)
   - `FAILED -> PENDING` is NOT legal — once you've failed you re-enter via the explicit retry edge, never by silently resetting state.
   - No self-loops; no edges from any terminal except FAILED.
6. **`run_id` is a free-form string** in `LifecycleStatus`. M01 does not derive it; the caller (later M02 runner) chooses how to wire it. Existing `core.run_identity.current_run_id` will be the natural source but we don't import it here to keep this module side-effect-free.
7. **`updated_at` and `produced_at`** are sourced from `core.common.iso_now` at the moment of `advance_node_state` / `with_artifact`. Callers can override via a `now` keyword for determinism in tests (default `None` → call `iso_now()`).
8. **`select_runnable` ordering:** results are sorted by `(topo_index, node_id)` so two equal-priority runnable nodes always emerge in lex order. Bounded concurrency `max_concurrent=N` truncates the result tuple to the first N entries; `max_concurrent=0` means unlimited.

---

## Task 1: Module stubs + `__all__` for all three new modules

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`

- [ ] **Step 1: Stub `lifecycle_policy.py`**

```python
"""Lifecycle policy schema, loader, and structural validator (M01).

Loads ``lifecycle-policy.json`` into a ``LifecyclePolicy`` data carrier,
validates structural invariants (unique ids, gate enum, dep references,
cycle freedom, entry-section references), and exposes the ``LifecycleNode``
and ``EntrySection`` carriers downstream modules depend on. Pure-functional;
no telemetry, no filesystem writes.
"""

from __future__ import annotations

__all__ = [
    "ALLOWED_GATES",
    "ALLOWED_MODES",
    "EntrySection",
    "LifecycleNode",
    "LifecyclePolicy",
    "PolicyLoadError",
    "load_lifecycle_policy",
    "validate_lifecycle_policy",
]

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_GATES: tuple[str, ...] = ("auto", "human")
ALLOWED_MODES: tuple[str, ...] = ("greenfield", "brownfield")
```

- [ ] **Step 2: Stub `lifecycle_status.py`**

```python
"""Per-run lifecycle status: node states + artifact registry (M01).

Frozen data carriers serialized to JSON-syntax YAML (valid YAML 1.2)
via ``core.atomic_io.write_atomic_text``. Resumable round-trip; no
telemetry, no agent spawning.
"""

from __future__ import annotations

__all__ = [
    "ArtifactRecord",
    "LEGAL_TRANSITIONS",
    "LifecycleStatus",
    "NodeRecord",
    "NodeState",
    "StatusLoadError",
    "advance_node_state",
    "load_lifecycle_status",
    "write_lifecycle_status",
]

import json
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from .atomic_io import write_atomic_text
from .common import iso_now
```

- [ ] **Step 3: Stub `lifecycle_scheduler.py`**

```python
"""Lifecycle scheduler: topological order + runnable selection (M01).

Pure-functional. Reads a ``LifecyclePolicy`` + ``LifecycleStatus``,
returns the set of ``LifecycleNode`` instances unblocked by their
dependencies + input-artifact presence. Never touches the filesystem.
"""

from __future__ import annotations

__all__ = [
    "SchedulerError",
    "select_runnable",
    "topo_sort",
]

from .lifecycle_policy import LifecycleNode, LifecyclePolicy
from .lifecycle_status import LifecycleStatus, NodeState
```

- [ ] **Step 4: Confirm the stubs import**

Run from the repo root: `PYTHONPATH=skills/bmad-story-automator/src python -c "from story_automator.core import lifecycle_policy, lifecycle_status, lifecycle_scheduler; print(lifecycle_policy.__all__, lifecycle_status.__all__, lifecycle_scheduler.__all__)"`

Expected: the three `__all__` tuples print without exception.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): stub lifecycle_policy/status/scheduler modules with __all__"
```

---

## Task 2: `LifecycleNode` dataclass (REQ — spec §1 field set)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Create: `tests/test_lifecycle_policy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_lifecycle_policy.py`:

```python
from __future__ import annotations

import dataclasses
import unittest

from story_automator.core.lifecycle_policy import LifecycleNode


class LifecycleNodeTests(unittest.TestCase):
    def test_construct_with_kw_only_required_fields(self) -> None:
        node = LifecycleNode(
            id="B3-epics",
            track="bmm",
            phase=3,
            skill="bmad-create-epics-and-stories",
            verifier="epics_created",
            gate="human",
            agent_role="planner",
        )
        self.assertEqual(node.id, "B3-epics")
        self.assertEqual(node.track, "bmm")
        self.assertEqual(node.phase, 3)
        self.assertEqual(node.skill, "bmad-create-epics-and-stories")
        self.assertEqual(node.deps, ())
        self.assertEqual(node.input_artifacts, ())
        self.assertEqual(node.output_artifact, "")
        self.assertEqual(node.modes, ())
        self.assertEqual(node.validator_skill, "")
        self.assertFalse(node.interactive)

    def test_is_frozen(self) -> None:
        node = LifecycleNode(
            id="n", track="bmm", phase=1, skill="s",
            verifier="v", gate="auto", agent_role="r",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            node.id = "other"  # type: ignore[misc]

    def test_positional_construction_rejected(self) -> None:
        with self.assertRaises(TypeError):
            LifecycleNode("a", "bmm", 1, "s", "v", "auto", "r")  # type: ignore[call-arg]

    def test_collections_are_tuples(self) -> None:
        node = LifecycleNode(
            id="n", track="bmm", phase=1, skill="s",
            verifier="v", gate="auto", agent_role="r",
            deps=("a", "b"), input_artifacts=("x",), modes=("greenfield",),
        )
        self.assertIsInstance(node.deps, tuple)
        self.assertIsInstance(node.input_artifacts, tuple)
        self.assertIsInstance(node.modes, tuple)


if __name__ == "__main__":
    unittest.main()
```

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy -v`. Expected: `ImportError: cannot import name 'LifecycleNode'`.

- [ ] **Step 2: Implement `LifecycleNode`**

Append to `lifecycle_policy.py`:

```python


@dataclass(frozen=True, kw_only=True)
class LifecycleNode:
    """One node in the lifecycle DAG.

    Required: id, track, phase, skill, verifier, gate, agent_role.
    Optional: deps (default ()), input_artifacts (default ()),
    output_artifact (default ""), modes (default ()), validator_skill
    (default ""), interactive (default False). Collections are tuples so
    the frozen guarantee is real; downstream code never reassigns a list.
    """

    id: str
    track: str
    phase: int
    skill: str
    verifier: str
    gate: str
    agent_role: str
    deps: tuple[str, ...] = ()
    input_artifacts: tuple[str, ...] = ()
    output_artifact: str = ""
    modes: tuple[str, ...] = ()
    validator_skill: str = ""
    interactive: bool = False
```

- [ ] **Step 3: Run the tests**

`PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_policy -v`. Expected: 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py tests/test_lifecycle_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): add LifecycleNode frozen kw_only dataclass"
```

---

## Task 3: `EntrySection` + `LifecyclePolicy` dataclasses

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Modify: `tests/test_lifecycle_policy.py`

- [ ] **Step 1: Write the failing tests**

Add the imports to the top of `tests/test_lifecycle_policy.py` (single import block per ruff E402):

```python
from story_automator.core.lifecycle_policy import EntrySection, LifecyclePolicy
```

Append to the file (above the `if __name__` guard):

```python
class EntrySectionTests(unittest.TestCase):
    def test_defaults_to_empty_tuples(self) -> None:
        entry = EntrySection()
        self.assertEqual(entry.greenfield, ())
        self.assertEqual(entry.brownfield, ())

    def test_is_frozen(self) -> None:
        entry = EntrySection(greenfield=("n1",))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.greenfield = ()  # type: ignore[misc]


class LifecyclePolicyTests(unittest.TestCase):
    def _node(self, node_id: str, **overrides: object) -> LifecycleNode:
        defaults: dict[str, object] = dict(
            id=node_id, track="bmm", phase=1, skill="s",
            verifier="v", gate="auto", agent_role="r",
        )
        defaults.update(overrides)
        return LifecycleNode(**defaults)  # type: ignore[arg-type]

    def test_construct_and_lookup(self) -> None:
        n1 = self._node("n1")
        n2 = self._node("n2")
        policy = LifecyclePolicy(
            version=1, nodes=(n1, n2), entry=EntrySection(greenfield=("n1",)),
        )
        self.assertIs(policy.node_by_id("n1"), n1)
        self.assertIs(policy.node_by_id("n2"), n2)
        self.assertIsNone(policy.node_by_id("missing"))

    def test_nodes_collection_is_tuple(self) -> None:
        policy = LifecyclePolicy(
            version=1, nodes=(self._node("n1"),), entry=EntrySection(),
        )
        self.assertIsInstance(policy.nodes, tuple)

    def test_to_dict_round_trip_shape(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(
                self._node("n1", output_artifact="art-1", modes=("greenfield",)),
                self._node(
                    "n2", deps=("n1",), input_artifacts=("art-1",),
                    output_artifact="art-2", modes=("greenfield",),
                ),
            ),
            entry=EntrySection(greenfield=("n1",)),
        )
        data = policy.to_dict()
        self.assertEqual(data["version"], 1)
        self.assertEqual([n["id"] for n in data["nodes"]], ["n1", "n2"])
        self.assertEqual(data["nodes"][1]["deps"], ["n1"])
        self.assertEqual(data["nodes"][1]["input_artifacts"], ["art-1"])
        self.assertEqual(data["entry"]["greenfield"], ["n1"])
        self.assertEqual(data["entry"]["brownfield"], [])
```

Run: expect `ImportError: cannot import name 'EntrySection'`.

- [ ] **Step 2: Implement `EntrySection` and `LifecyclePolicy`**

Append to `lifecycle_policy.py`:

```python


@dataclass(frozen=True, kw_only=True)
class EntrySection:
    """Entry node ids per top-level mode.

    Used by the future entry router (M04) to pick the first node(s) for
    a greenfield vs brownfield run. M01 only stores and validates the
    references — the router is out of scope here.
    """

    greenfield: tuple[str, ...] = ()
    brownfield: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class LifecyclePolicy:
    """Loaded + validated lifecycle policy.

    ``nodes`` is the DAG in declaration order; ``node_by_id`` is the
    O(N) lookup helper (callers needing repeated lookups should keep
    their own dict). ``entry`` enumerates run-start node ids for each
    top-level mode.
    """

    version: int
    nodes: tuple[LifecycleNode, ...]
    entry: EntrySection

    def node_by_id(self, node_id: str) -> LifecycleNode | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def to_dict(self) -> dict[str, Any]:
        """Re-emit the policy as a plain dict matching the on-disk schema.

        Field order mirrors the on-disk fixture: ``version``, ``nodes`` (in
        declaration order, with each node's fields in spec order), then
        ``entry``. Empty-collection fields are emitted verbatim so a
        ``load -> to_dict -> json.dumps -> load`` round-trip yields the
        same in-memory policy (spec acceptance: "schema validates +
        round-trips").
        """
        return {
            "version": self.version,
            "nodes": [
                {
                    "id": node.id,
                    "track": node.track,
                    "phase": node.phase,
                    "skill": node.skill,
                    "verifier": node.verifier,
                    "gate": node.gate,
                    "agent_role": node.agent_role,
                    "deps": list(node.deps),
                    "input_artifacts": list(node.input_artifacts),
                    "output_artifact": node.output_artifact,
                    "modes": list(node.modes),
                    "validator_skill": node.validator_skill,
                    "interactive": node.interactive,
                }
                for node in self.nodes
            ],
            "entry": {
                "greenfield": list(self.entry.greenfield),
                "brownfield": list(self.entry.brownfield),
            },
        }
```

- [ ] **Step 3: Run the tests** — expect 8 total passing (4 from Task 2 + 4 new).

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py tests/test_lifecycle_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): add EntrySection and LifecyclePolicy carriers"
```

---

## Task 4: `load_lifecycle_policy` happy path + fixture file

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Modify: `tests/test_lifecycle_policy.py`
- Create: `tests/fixtures/lifecycle/policy-minimal.json`

- [ ] **Step 1: Create the minimal fixture**

Create `tests/fixtures/lifecycle/policy-minimal.json` (LF endings, two-space indent):

```json
{
  "version": 1,
  "nodes": [
    {
      "id": "n1",
      "track": "bmm",
      "phase": 1,
      "skill": "skill-a",
      "verifier": "artifact_exists",
      "gate": "auto",
      "agent_role": "writer",
      "deps": [],
      "input_artifacts": [],
      "output_artifact": "art-1",
      "modes": ["greenfield"]
    },
    {
      "id": "n2",
      "track": "bmm",
      "phase": 2,
      "skill": "skill-b",
      "verifier": "artifact_exists",
      "gate": "human",
      "agent_role": "reviewer",
      "deps": ["n1"],
      "input_artifacts": ["art-1"],
      "output_artifact": "art-2",
      "modes": ["greenfield"]
    }
  ],
  "entry": {
    "greenfield": ["n1"],
    "brownfield": []
  }
}
```

- [ ] **Step 2: Write the failing load test**

Add to imports: `from pathlib import Path; from story_automator.core.lifecycle_policy import load_lifecycle_policy, PolicyLoadError`.

Append to `test_lifecycle_policy.py`:

```python
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class LoadLifecyclePolicyTests(unittest.TestCase):
    def test_loads_minimal_fixture(self) -> None:
        policy = load_lifecycle_policy(FIXTURE_DIR / "policy-minimal.json")
        self.assertEqual(policy.version, 1)
        self.assertEqual(len(policy.nodes), 2)
        self.assertEqual(policy.nodes[0].id, "n1")
        self.assertEqual(policy.nodes[1].deps, ("n1",))
        self.assertEqual(policy.entry.greenfield, ("n1",))
        self.assertEqual(policy.entry.brownfield, ())

    def test_missing_file_raises_policy_load_error(self) -> None:
        with self.assertRaises(PolicyLoadError):
            load_lifecycle_policy(FIXTURE_DIR / "does-not-exist.json")

    def test_malformed_json_raises_policy_load_error(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            with self.assertRaises(PolicyLoadError):
                load_lifecycle_policy(bad)

    def test_non_object_root_raises_policy_load_error(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.json"
            bad.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(PolicyLoadError):
                load_lifecycle_policy(bad)

    def test_file_round_trip_via_to_dict(self) -> None:
        # Spec acceptance: "schema validates + round-trips" — re-emitting a
        # loaded policy and re-loading must yield the same in-memory object.
        import json
        import tempfile
        loaded = load_lifecycle_policy(FIXTURE_DIR / "policy-minimal.json")
        with tempfile.TemporaryDirectory() as tmpdir:
            roundtrip_path = Path(tmpdir) / "roundtrip.json"
            roundtrip_path.write_text(
                json.dumps(loaded.to_dict(), indent=2), encoding="utf-8",
            )
            reloaded = load_lifecycle_policy(roundtrip_path)
        self.assertEqual(reloaded, loaded)
```

Run: expect `ImportError: cannot import name 'load_lifecycle_policy'`.

- [ ] **Step 3: Implement `load_lifecycle_policy` (without full validation yet)**

Append to `lifecycle_policy.py`:

```python


class PolicyLoadError(ValueError):
    """Raised on any structural failure during policy load + validate."""


def _node_from_dict(raw: dict[str, Any]) -> LifecycleNode:
    try:
        return LifecycleNode(
            id=str(raw["id"]),
            track=str(raw["track"]),
            phase=int(raw["phase"]),
            skill=str(raw["skill"]),
            verifier=str(raw["verifier"]),
            gate=str(raw["gate"]),
            agent_role=str(raw["agent_role"]),
            deps=tuple(str(x) for x in raw.get("deps", ())),
            input_artifacts=tuple(str(x) for x in raw.get("input_artifacts", ())),
            output_artifact=str(raw.get("output_artifact", "")),
            modes=tuple(str(x) for x in raw.get("modes", ())),
            validator_skill=str(raw.get("validator_skill", "")),
            interactive=bool(raw.get("interactive", False)),
        )
    except KeyError as exc:
        raise PolicyLoadError(
            f"node missing required field: {exc.args[0]!r}"
        ) from exc


def _entry_from_dict(raw: dict[str, Any]) -> EntrySection:
    return EntrySection(
        greenfield=tuple(str(x) for x in raw.get("greenfield", ())),
        brownfield=tuple(str(x) for x in raw.get("brownfield", ())),
    )


def load_lifecycle_policy(path: str | Path) -> LifecyclePolicy:
    """Read JSON from ``path`` and return a validated ``LifecyclePolicy``.

    Raises ``PolicyLoadError`` for any structural failure: missing file,
    malformed JSON, non-object root, missing required fields, type errors,
    or any condition flagged by ``validate_lifecycle_policy``.
    """

    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PolicyLoadError(f"policy file not found: {target}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyLoadError(f"policy file is not valid JSON: {target} ({exc})") from exc
    if not isinstance(payload, dict):
        raise PolicyLoadError(
            f"policy root must be an object, got {type(payload).__name__}: {target}"
        )
    try:
        version = int(payload.get("version", 0))
        raw_nodes = payload.get("nodes", [])
        if not isinstance(raw_nodes, list):
            raise PolicyLoadError(f"'nodes' must be an array, got {type(raw_nodes).__name__}")
        nodes = tuple(_node_from_dict(n) for n in raw_nodes)
        entry_raw = payload.get("entry", {})
        if not isinstance(entry_raw, dict):
            raise PolicyLoadError(f"'entry' must be an object, got {type(entry_raw).__name__}")
        entry = _entry_from_dict(entry_raw)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, PolicyLoadError):
            raise
        raise PolicyLoadError(f"policy parse failed: {exc}") from exc
    policy = LifecyclePolicy(version=version, nodes=nodes, entry=entry)
    validate_lifecycle_policy(policy)
    return policy


def validate_lifecycle_policy(policy: LifecyclePolicy) -> None:
    """Placeholder until Task 5 fills in the structural rules."""
    return None
```

Run: expect 4 new tests pass (12 total).

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/lifecycle/policy-minimal.json skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py tests/test_lifecycle_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): implement load_lifecycle_policy happy path + minimal fixture"
```

---

## Task 5: `validate_lifecycle_policy` — uniqueness, gate enum, mode subset

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Modify: `tests/test_lifecycle_policy.py`

- [ ] **Step 1: Write the failing validation tests**

Append to `test_lifecycle_policy.py`:

```python
class ValidateUniquenessTests(unittest.TestCase):
    def _node(self, node_id: str, **overrides: object) -> LifecycleNode:
        defaults: dict[str, object] = dict(
            id=node_id, track="bmm", phase=1, skill="s",
            verifier="v", gate="auto", agent_role="r",
        )
        defaults.update(overrides)
        return LifecycleNode(**defaults)  # type: ignore[arg-type]

    def test_duplicate_node_id_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1, nodes=(self._node("n1"), self._node("n1")),
            entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError) as ctx:
            validate_lifecycle_policy(policy)
        self.assertIn("duplicate node id", str(ctx.exception))

    def test_invalid_gate_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1, nodes=(self._node("n1", gate="manual"),), entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError) as ctx:
            validate_lifecycle_policy(policy)
        self.assertIn("gate", str(ctx.exception))

    def test_invalid_mode_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1, nodes=(self._node("n1", modes=("blueprint",)),), entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError) as ctx:
            validate_lifecycle_policy(policy)
        self.assertIn("mode", str(ctx.exception))

    def test_duplicate_output_artifact_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(
                self._node("n1", output_artifact="art-1"),
                self._node("n2", output_artifact="art-1"),
            ),
            entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError) as ctx:
            validate_lifecycle_policy(policy)
        self.assertIn("output_artifact", str(ctx.exception))

    def test_empty_output_artifact_allowed_multiple(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(self._node("n1"), self._node("n2")),
            entry=EntrySection(),
        )
        validate_lifecycle_policy(policy)  # must not raise

    def test_empty_id_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1, nodes=(self._node(""),), entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError):
            validate_lifecycle_policy(policy)

    def test_negative_phase_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1, nodes=(self._node("n1", phase=-1),), entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError):
            validate_lifecycle_policy(policy)
```

Also add `from story_automator.core.lifecycle_policy import validate_lifecycle_policy, ALLOWED_GATES, ALLOWED_MODES` to the import block.

Run: expect 7 new failures (validator currently returns None).

- [ ] **Step 2: Implement field-level validation**

Replace the placeholder `validate_lifecycle_policy` body in `lifecycle_policy.py`:

```python
def validate_lifecycle_policy(policy: LifecyclePolicy) -> None:
    """Raise ``PolicyLoadError`` on any structural problem.

    Checks: id non-empty + unique, phase >= 0, gate in ALLOWED_GATES,
    modes subset of ALLOWED_MODES, output_artifact unique among non-empty,
    deps reference known node ids, entry references known node ids,
    no cycles in the dependency graph. Tasks 5-7 fill these in.
    """

    seen_ids: set[str] = set()
    seen_outputs: set[str] = set()
    for node in policy.nodes:
        if not node.id:
            raise PolicyLoadError("node id must be non-empty")
        if node.id in seen_ids:
            raise PolicyLoadError(f"duplicate node id: {node.id!r}")
        seen_ids.add(node.id)
        if node.phase < 0:
            raise PolicyLoadError(
                f"node {node.id!r}: phase must be >= 0, got {node.phase}"
            )
        if node.gate not in ALLOWED_GATES:
            raise PolicyLoadError(
                f"node {node.id!r}: gate must be one of {ALLOWED_GATES}, got {node.gate!r}"
            )
        for mode in node.modes:
            if mode not in ALLOWED_MODES:
                raise PolicyLoadError(
                    f"node {node.id!r}: mode {mode!r} not in {ALLOWED_MODES}"
                )
        if node.output_artifact:
            if node.output_artifact in seen_outputs:
                raise PolicyLoadError(
                    f"duplicate output_artifact {node.output_artifact!r} "
                    f"(node {node.id!r})"
                )
            seen_outputs.add(node.output_artifact)
```

Run: expect all 19 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py tests/test_lifecycle_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): validate uniqueness, gate enum, mode subset, output_artifact uniqueness"
```

---

## Task 6: Validate dep and entry references + cycle detection

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py`
- Modify: `tests/test_lifecycle_policy.py`

- [ ] **Step 1: Write the failing reference + cycle tests**

Append to `test_lifecycle_policy.py`:

```python
class ValidateReferencesTests(unittest.TestCase):
    def _node(self, node_id: str, **overrides: object) -> LifecycleNode:
        defaults: dict[str, object] = dict(
            id=node_id, track="bmm", phase=1, skill="s",
            verifier="v", gate="auto", agent_role="r",
        )
        defaults.update(overrides)
        return LifecycleNode(**defaults)  # type: ignore[arg-type]

    def test_dep_to_unknown_node_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(self._node("n1", deps=("ghost",)),),
            entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError) as ctx:
            validate_lifecycle_policy(policy)
        self.assertIn("dep", str(ctx.exception))
        self.assertIn("ghost", str(ctx.exception))

    def test_self_dep_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(self._node("n1", deps=("n1",)),),
            entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError):
            validate_lifecycle_policy(policy)

    def test_entry_ref_to_unknown_node_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(self._node("n1"),),
            entry=EntrySection(greenfield=("ghost",)),
        )
        with self.assertRaises(PolicyLoadError):
            validate_lifecycle_policy(policy)

    def test_entry_ref_brownfield_validated(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(self._node("n1"),),
            entry=EntrySection(brownfield=("ghost",)),
        )
        with self.assertRaises(PolicyLoadError):
            validate_lifecycle_policy(policy)

    def test_cycle_two_nodes_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(
                self._node("a", deps=("b",)),
                self._node("b", deps=("a",)),
            ),
            entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError) as ctx:
            validate_lifecycle_policy(policy)
        self.assertIn("cycle", str(ctx.exception).lower())

    def test_cycle_three_nodes_rejected(self) -> None:
        policy = LifecyclePolicy(
            version=1,
            nodes=(
                self._node("a", deps=("c",)),
                self._node("b", deps=("a",)),
                self._node("c", deps=("b",)),
            ),
            entry=EntrySection(),
        )
        with self.assertRaises(PolicyLoadError):
            validate_lifecycle_policy(policy)

    def test_dag_with_diamond_accepts(self) -> None:
        # a -> b -> d, a -> c -> d (diamond, no cycle).
        policy = LifecyclePolicy(
            version=1,
            nodes=(
                self._node("a"),
                self._node("b", deps=("a",)),
                self._node("c", deps=("a",)),
                self._node("d", deps=("b", "c")),
            ),
            entry=EntrySection(greenfield=("a",)),
        )
        validate_lifecycle_policy(policy)  # must not raise
```

Run: expect 7 new failures.

- [ ] **Step 2: Extend the validator**

Replace the body of `validate_lifecycle_policy` with:

```python
def validate_lifecycle_policy(policy: LifecyclePolicy) -> None:
    """Raise ``PolicyLoadError`` on any structural problem."""

    seen_ids: set[str] = set()
    seen_outputs: set[str] = set()
    ids_in_order: list[str] = []
    for node in policy.nodes:
        if not node.id:
            raise PolicyLoadError("node id must be non-empty")
        if node.id in seen_ids:
            raise PolicyLoadError(f"duplicate node id: {node.id!r}")
        seen_ids.add(node.id)
        ids_in_order.append(node.id)
        if node.phase < 0:
            raise PolicyLoadError(
                f"node {node.id!r}: phase must be >= 0, got {node.phase}"
            )
        if node.gate not in ALLOWED_GATES:
            raise PolicyLoadError(
                f"node {node.id!r}: gate must be one of {ALLOWED_GATES}, got {node.gate!r}"
            )
        for mode in node.modes:
            if mode not in ALLOWED_MODES:
                raise PolicyLoadError(
                    f"node {node.id!r}: mode {mode!r} not in {ALLOWED_MODES}"
                )
        if node.output_artifact:
            if node.output_artifact in seen_outputs:
                raise PolicyLoadError(
                    f"duplicate output_artifact {node.output_artifact!r} "
                    f"(node {node.id!r})"
                )
            seen_outputs.add(node.output_artifact)

    for node in policy.nodes:
        for dep in node.deps:
            if dep == node.id:
                raise PolicyLoadError(f"node {node.id!r}: self-dep not allowed")
            if dep not in seen_ids:
                raise PolicyLoadError(
                    f"node {node.id!r}: dep {dep!r} refers to unknown node id"
                )

    for entry_field, entries in (
        ("greenfield", policy.entry.greenfield),
        ("brownfield", policy.entry.brownfield),
    ):
        for ref in entries:
            if ref not in seen_ids:
                raise PolicyLoadError(
                    f"entry.{entry_field} references unknown node id: {ref!r}"
                )

    _check_no_cycles(policy)


def _check_no_cycles(policy: LifecyclePolicy) -> None:
    """Kahn's algorithm — raise PolicyLoadError naming the cycle members.

    We compute in-degrees, repeatedly pop zero-in-degree nodes, and
    decrement successors. If any node remains with in-degree > 0 after
    the queue empties, a cycle exists among those nodes — we list them
    in declaration order in the error message so the operator can spot
    the bad edges.
    """
    in_degree: dict[str, int] = {n.id: 0 for n in policy.nodes}
    successors: dict[str, list[str]] = {n.id: [] for n in policy.nodes}
    for node in policy.nodes:
        for dep in node.deps:
            in_degree[node.id] += 1
            successors[dep].append(node.id)
    ready = [n.id for n in policy.nodes if in_degree[n.id] == 0]
    visited: list[str] = []
    while ready:
        current = ready.pop(0)
        visited.append(current)
        for successor in successors[current]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                ready.append(successor)
    if len(visited) != len(policy.nodes):
        unresolved = [n.id for n in policy.nodes if n.id not in visited]
        raise PolicyLoadError(
            f"dependency graph contains a cycle among: {unresolved!r}"
        )
```

Run: expect all 26 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py tests/test_lifecycle_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): validate dep + entry references and reject cycles"
```

---

## Task 7: `NodeState` enum + `LEGAL_TRANSITIONS` + `NodeRecord` + `ArtifactRecord`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py`
- Create: `tests/test_lifecycle_status.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lifecycle_status.py`:

```python
from __future__ import annotations

import dataclasses
import unittest

from story_automator.core.lifecycle_status import (
    LEGAL_TRANSITIONS,
    ArtifactRecord,
    NodeRecord,
    NodeState,
)


class NodeStateTests(unittest.TestCase):
    def test_members_and_values(self) -> None:
        self.assertEqual(
            [m.name for m in NodeState],
            [
                "PENDING", "RUNNING", "VERIFIED", "AWAITING_APPROVAL",
                "APPROVED", "COMPLETE", "FAILED",
            ],
        )
        for member in NodeState:
            self.assertEqual(member.value, member.name.lower())


class LegalTransitionsTests(unittest.TestCase):
    def test_canonical_edges_present(self) -> None:
        for src, dst in [
            (NodeState.PENDING, NodeState.RUNNING),
            (NodeState.RUNNING, NodeState.VERIFIED),
            (NodeState.RUNNING, NodeState.FAILED),
            (NodeState.VERIFIED, NodeState.AWAITING_APPROVAL),
            (NodeState.VERIFIED, NodeState.COMPLETE),
            (NodeState.AWAITING_APPROVAL, NodeState.APPROVED),
            (NodeState.AWAITING_APPROVAL, NodeState.FAILED),
            (NodeState.APPROVED, NodeState.COMPLETE),
            (NodeState.FAILED, NodeState.RUNNING),
        ]:
            self.assertIn((src, dst), LEGAL_TRANSITIONS, f"missing edge {src}->{dst}")

    def test_disallowed_edges_absent(self) -> None:
        for src, dst in [
            (NodeState.FAILED, NodeState.PENDING),     # no silent reset
            (NodeState.COMPLETE, NodeState.RUNNING),   # no terminal exit
            (NodeState.APPROVED, NodeState.RUNNING),
            (NodeState.PENDING, NodeState.COMPLETE),   # no skipping
        ]:
            self.assertNotIn((src, dst), LEGAL_TRANSITIONS, f"forbidden edge {src}->{dst}")

    def test_no_self_loops(self) -> None:
        for state in NodeState:
            self.assertNotIn((state, state), LEGAL_TRANSITIONS)


class NodeRecordTests(unittest.TestCase):
    def test_construct_and_frozen(self) -> None:
        record = NodeRecord(
            node_id="n1", state=NodeState.PENDING,
            updated_at="2026-06-17T00:00:00Z",
        )
        self.assertEqual(record.notes, "")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.state = NodeState.RUNNING  # type: ignore[misc]


class ArtifactRecordTests(unittest.TestCase):
    def test_construct_and_frozen(self) -> None:
        record = ArtifactRecord(
            artifact_id="art-1", path="epics/",
            produced_by_node="B3-epics", produced_at="2026-06-17T00:00:00Z",
        )
        self.assertEqual(record.artifact_id, "art-1")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            record.path = "other/"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
```

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_status -v`. Expect `ImportError`.

- [ ] **Step 2: Implement the enum + carriers + transition set**

Append to `lifecycle_status.py`:

```python


class NodeState(Enum):
    """Per-node lifecycle state. Values are lowercase for JSON wire form."""

    PENDING = "pending"
    RUNNING = "running"
    VERIFIED = "verified"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    COMPLETE = "complete"
    FAILED = "failed"


LEGAL_TRANSITIONS: frozenset[tuple[NodeState, NodeState]] = frozenset({
    (NodeState.PENDING, NodeState.RUNNING),
    (NodeState.RUNNING, NodeState.VERIFIED),
    (NodeState.RUNNING, NodeState.FAILED),
    (NodeState.VERIFIED, NodeState.AWAITING_APPROVAL),
    (NodeState.VERIFIED, NodeState.COMPLETE),
    (NodeState.AWAITING_APPROVAL, NodeState.APPROVED),
    (NodeState.AWAITING_APPROVAL, NodeState.FAILED),
    (NodeState.APPROVED, NodeState.COMPLETE),
    (NodeState.FAILED, NodeState.RUNNING),
})


@dataclass(frozen=True, kw_only=True)
class NodeRecord:
    """One node's status snapshot in a ``LifecycleStatus``."""

    node_id: str
    state: NodeState
    updated_at: str
    notes: str = ""


@dataclass(frozen=True, kw_only=True)
class ArtifactRecord:
    """One artifact registered in a ``LifecycleStatus``."""

    artifact_id: str
    path: str
    produced_by_node: str
    produced_at: str
```

Run: expect 7 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py tests/test_lifecycle_status.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): add NodeState enum, LEGAL_TRANSITIONS, NodeRecord, ArtifactRecord"
```

---

## Task 8: `LifecycleStatus` carrier + `to_dict` / `with_node` / `with_artifact`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py`
- Modify: `tests/test_lifecycle_status.py`

- [ ] **Step 1: Write the failing tests**

Add to the import block: `from story_automator.core.lifecycle_status import LifecycleStatus`.

Append:

```python
class LifecycleStatusTests(unittest.TestCase):
    def _record(self, node_id: str, state: NodeState = NodeState.PENDING) -> NodeRecord:
        return NodeRecord(
            node_id=node_id, state=state, updated_at="2026-06-17T00:00:00Z",
        )

    def test_construct_empty(self) -> None:
        status = LifecycleStatus(
            run_id="run-1", nodes={}, artifacts={},
            updated_at="2026-06-17T00:00:00Z",
        )
        self.assertEqual(status.run_id, "run-1")
        self.assertEqual(status.nodes, {})

    def test_with_node_returns_new_status(self) -> None:
        status = LifecycleStatus(
            run_id="run-1", nodes={}, artifacts={},
            updated_at="2026-06-17T00:00:00Z",
        )
        new_status = status.with_node(self._record("n1"))
        self.assertNotEqual(id(status), id(new_status))
        self.assertNotIn("n1", status.nodes)
        self.assertIn("n1", new_status.nodes)
        self.assertEqual(new_status.nodes["n1"].state, NodeState.PENDING)

    def test_with_artifact_returns_new_status(self) -> None:
        status = LifecycleStatus(
            run_id="run-1", nodes={}, artifacts={},
            updated_at="2026-06-17T00:00:00Z",
        )
        new_status = status.with_artifact(
            ArtifactRecord(
                artifact_id="art-1", path="p/",
                produced_by_node="n1", produced_at="2026-06-17T00:00:00Z",
            )
        )
        self.assertIn("art-1", new_status.artifacts)
        self.assertNotIn("art-1", status.artifacts)

    def test_to_dict_round_trip_shape(self) -> None:
        status = LifecycleStatus(
            run_id="run-1",
            nodes={"n1": self._record("n1", NodeState.RUNNING)},
            artifacts={
                "art-1": ArtifactRecord(
                    artifact_id="art-1", path="p/",
                    produced_by_node="n1", produced_at="2026-06-17T00:00:00Z",
                )
            },
            updated_at="2026-06-17T00:00:00Z",
        )
        data = status.to_dict()
        self.assertEqual(data["run_id"], "run-1")
        self.assertEqual(data["nodes"]["n1"]["state"], "running")
        self.assertEqual(data["artifacts"]["art-1"]["path"], "p/")
        self.assertEqual(data["updated_at"], "2026-06-17T00:00:00Z")
```

- [ ] **Step 2: Implement `LifecycleStatus`**

Append to `lifecycle_status.py`:

```python


@dataclass(frozen=True, kw_only=True)
class LifecycleStatus:
    """Per-run lifecycle status.

    ``nodes`` is keyed by ``LifecycleNode.id`` and ordered by insertion.
    ``artifacts`` is keyed by ``ArtifactRecord.artifact_id``. Both dicts
    are intentionally NOT immutable types — Python lacks a frozen-dict
    primitive, and copying-by-default in ``with_node`` / ``with_artifact``
    is the substitute. Direct mutation by callers is not part of the
    contract; doing so will silently desync.
    """

    run_id: str
    nodes: dict[str, NodeRecord]
    artifacts: dict[str, ArtifactRecord]
    updated_at: str

    def with_node(self, record: NodeRecord) -> LifecycleStatus:
        new_nodes = dict(self.nodes)
        new_nodes[record.node_id] = record
        return replace(self, nodes=new_nodes)

    def with_artifact(self, record: ArtifactRecord) -> LifecycleStatus:
        new_artifacts = dict(self.artifacts)
        new_artifacts[record.artifact_id] = record
        return replace(self, artifacts=new_artifacts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "updated_at": self.updated_at,
            "nodes": {
                node_id: {
                    "node_id": record.node_id,
                    "state": record.state.value,
                    "updated_at": record.updated_at,
                    "notes": record.notes,
                }
                for node_id, record in self.nodes.items()
            },
            "artifacts": {
                aid: {
                    "artifact_id": record.artifact_id,
                    "path": record.path,
                    "produced_by_node": record.produced_by_node,
                    "produced_at": record.produced_at,
                }
                for aid, record in self.artifacts.items()
            },
        }
```

Run: expect 11 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py tests/test_lifecycle_status.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): add LifecycleStatus with copy-on-write with_node/with_artifact"
```

---

## Task 9: `write_lifecycle_status` + `load_lifecycle_status` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py`
- Modify: `tests/test_lifecycle_status.py`

- [ ] **Step 1: Write the failing IO tests**

Add to import block: `import tempfile; from pathlib import Path; from story_automator.core.lifecycle_status import load_lifecycle_status, write_lifecycle_status, StatusLoadError`.

Append:

```python
class StatusRoundTripTests(unittest.TestCase):
    def _status(self) -> LifecycleStatus:
        return LifecycleStatus(
            run_id="run-1",
            nodes={
                "n1": NodeRecord(
                    node_id="n1", state=NodeState.COMPLETE,
                    updated_at="2026-06-17T00:00:00Z", notes="done",
                ),
                "n2": NodeRecord(
                    node_id="n2", state=NodeState.PENDING,
                    updated_at="2026-06-17T00:00:00Z",
                ),
            },
            artifacts={
                "art-1": ArtifactRecord(
                    artifact_id="art-1", path="epics/",
                    produced_by_node="n1", produced_at="2026-06-17T00:00:00Z",
                )
            },
            updated_at="2026-06-17T00:00:00Z",
        )

    def test_round_trip(self) -> None:
        original = self._status()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "lifecycle-status.yaml"
            write_lifecycle_status(original, path)
            loaded = load_lifecycle_status(path)
        self.assertEqual(loaded.run_id, original.run_id)
        self.assertEqual(loaded.updated_at, original.updated_at)
        self.assertEqual(loaded.nodes, original.nodes)
        self.assertEqual(loaded.artifacts, original.artifacts)

    def test_resume_reconstructs_state_from_disk(self) -> None:
        # Acceptance criterion from spec §1: "resume reconstructs state from disk".
        original = self._status()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "lifecycle-status.yaml"
            write_lifecycle_status(original, path)
            # Simulate "resume": fresh process loads, advances, writes again.
            loaded = load_lifecycle_status(path)
            advanced = loaded.with_node(
                NodeRecord(
                    node_id="n2", state=NodeState.RUNNING,
                    updated_at="2026-06-17T00:01:00Z",
                )
            )
            write_lifecycle_status(advanced, path)
            reloaded = load_lifecycle_status(path)
        self.assertEqual(reloaded.nodes["n2"].state, NodeState.RUNNING)
        self.assertEqual(reloaded.nodes["n1"].state, NodeState.COMPLETE)

    def test_missing_file_raises_status_load_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(StatusLoadError):
                load_lifecycle_status(Path(tmpdir) / "missing.yaml")

    def test_malformed_payload_raises_status_load_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.yaml"
            bad.write_text("not json at all", encoding="utf-8")
            with self.assertRaises(StatusLoadError):
                load_lifecycle_status(bad)

    def test_unknown_state_value_raises_status_load_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.yaml"
            bad.write_text(
                '{"run_id":"r","updated_at":"t","nodes":{"n1":{"node_id":"n1","state":"bogus","updated_at":"t","notes":""}},"artifacts":{}}',
                encoding="utf-8",
            )
            with self.assertRaises(StatusLoadError) as ctx:
                load_lifecycle_status(bad)
            self.assertIn("bogus", str(ctx.exception))

    def test_node_id_field_must_match_map_key(self) -> None:
        # Hand-edited corruption: record's node_id != enclosing map key.
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.yaml"
            bad.write_text(
                '{"run_id":"r","updated_at":"t","nodes":{"n1":'
                '{"node_id":"impostor","state":"pending","updated_at":"t","notes":""}},'
                '"artifacts":{}}',
                encoding="utf-8",
            )
            with self.assertRaises(StatusLoadError) as ctx:
                load_lifecycle_status(bad)
            self.assertIn("impostor", str(ctx.exception))

    def test_byte_equal_round_trip_for_diff_determinism(self) -> None:
        # write -> read -> write produces byte-equal disk content. Important
        # so CI diff review on status files is meaningful.
        original = self._status()
        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = Path(tmpdir) / "first.yaml"
            path2 = Path(tmpdir) / "second.yaml"
            write_lifecycle_status(original, path1)
            reloaded = load_lifecycle_status(path1)
            write_lifecycle_status(reloaded, path2)
            self.assertEqual(
                path1.read_bytes(), path2.read_bytes(),
                "lifecycle-status write is not byte-deterministic",
            )
```

- [ ] **Step 2: Implement `write_lifecycle_status` and `load_lifecycle_status`**

Append to `lifecycle_status.py`:

```python


class StatusLoadError(ValueError):
    """Raised when a ``lifecycle-status.yaml`` cannot be loaded."""


def write_lifecycle_status(status: LifecycleStatus, path: str | Path) -> None:
    """Atomically write ``status`` to ``path`` as JSON-syntax YAML.

    Uses ``core.atomic_io.write_atomic_text`` for the same per-path
    threading lock + fsync + Windows-replace retries the rest of the
    runtime depends on. The on-disk format is sorted-keys JSON with a
    trailing newline, suitable for both diff review and YAML 1.2
    consumers.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(status.to_dict(), sort_keys=True, indent=2) + "\n"
    write_atomic_text(target, text)


def _node_record_from_dict(raw: dict[str, Any], *, expected_key: str) -> NodeRecord:
    state_value = raw["state"]
    try:
        state = NodeState(state_value)
    except ValueError as exc:
        raise StatusLoadError(
            f"unknown node state value: {state_value!r}"
        ) from exc
    record_id = str(raw["node_id"])
    if record_id != expected_key:
        raise StatusLoadError(
            f"node_id field {record_id!r} does not match map key {expected_key!r}"
        )
    return NodeRecord(
        node_id=record_id,
        state=state,
        updated_at=str(raw["updated_at"]),
        notes=str(raw.get("notes", "")),
    )


def _artifact_record_from_dict(raw: dict[str, Any]) -> ArtifactRecord:
    return ArtifactRecord(
        artifact_id=str(raw["artifact_id"]),
        path=str(raw["path"]),
        produced_by_node=str(raw["produced_by_node"]),
        produced_at=str(raw["produced_at"]),
    )


def load_lifecycle_status(path: str | Path) -> LifecycleStatus:
    """Read a previously-written ``lifecycle-status.yaml`` from disk."""
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise StatusLoadError(f"status file not found: {target}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StatusLoadError(f"status file is not valid JSON: {target} ({exc})") from exc
    if not isinstance(payload, dict):
        raise StatusLoadError(
            f"status root must be an object, got {type(payload).__name__}: {target}"
        )
    try:
        nodes_raw = payload.get("nodes", {})
        artifacts_raw = payload.get("artifacts", {})
        if not isinstance(nodes_raw, dict) or not isinstance(artifacts_raw, dict):
            raise StatusLoadError("'nodes' and 'artifacts' must be objects")
        nodes = {
            str(node_id): _node_record_from_dict(record_raw, expected_key=str(node_id))
            for node_id, record_raw in nodes_raw.items()
        }
        artifacts = {
            str(aid): _artifact_record_from_dict(record_raw)
            for aid, record_raw in artifacts_raw.items()
        }
        return LifecycleStatus(
            run_id=str(payload.get("run_id", "")),
            nodes=nodes,
            artifacts=artifacts,
            updated_at=str(payload.get("updated_at", "")),
        )
    except KeyError as exc:
        raise StatusLoadError(
            f"status payload missing required field: {exc.args[0]!r}"
        ) from exc
    except (TypeError, ValueError) as exc:
        if isinstance(exc, StatusLoadError):
            raise
        raise StatusLoadError(f"status parse failed: {exc}") from exc
```

Run: expect 16 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py tests/test_lifecycle_status.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): atomic IO + JSON-YAML round-trip for LifecycleStatus"
```

---

## Task 10: `advance_node_state` — legal/illegal transitions

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py`
- Modify: `tests/test_lifecycle_status.py`

- [ ] **Step 1: Write the failing transition tests**

Add to imports: `from story_automator.core.lifecycle_status import advance_node_state`.

Append:

```python
class AdvanceNodeStateTests(unittest.TestCase):
    def _seed(self, state: NodeState = NodeState.PENDING) -> LifecycleStatus:
        return LifecycleStatus(
            run_id="run-1",
            nodes={
                "n1": NodeRecord(
                    node_id="n1", state=state,
                    updated_at="2026-06-17T00:00:00Z",
                ),
            },
            artifacts={},
            updated_at="2026-06-17T00:00:00Z",
        )

    def test_legal_transition_advances(self) -> None:
        status = self._seed(NodeState.PENDING)
        new_status = advance_node_state(
            status, "n1", NodeState.RUNNING,
            now="2026-06-17T00:01:00Z",
        )
        self.assertEqual(new_status.nodes["n1"].state, NodeState.RUNNING)
        self.assertEqual(new_status.nodes["n1"].updated_at, "2026-06-17T00:01:00Z")

    def test_illegal_transition_rejected(self) -> None:
        status = self._seed(NodeState.PENDING)
        with self.assertRaises(StatusLoadError) as ctx:
            advance_node_state(status, "n1", NodeState.COMPLETE)
        msg = str(ctx.exception).lower()
        self.assertIn("transition", msg)

    def test_unknown_node_rejected(self) -> None:
        status = self._seed()
        with self.assertRaises(StatusLoadError):
            advance_node_state(status, "ghost", NodeState.RUNNING)

    def test_input_status_not_mutated(self) -> None:
        status = self._seed(NodeState.PENDING)
        new_status = advance_node_state(status, "n1", NodeState.RUNNING, now="t")
        self.assertEqual(status.nodes["n1"].state, NodeState.PENDING)
        self.assertEqual(new_status.nodes["n1"].state, NodeState.RUNNING)

    def test_notes_propagate(self) -> None:
        status = self._seed(NodeState.AWAITING_APPROVAL)
        new_status = advance_node_state(
            status, "n1", NodeState.FAILED,
            now="t", notes="operator rejected: scope creep",
        )
        self.assertEqual(new_status.nodes["n1"].notes, "operator rejected: scope creep")

    def test_default_now_calls_iso_now(self) -> None:
        from unittest import mock
        status = self._seed(NodeState.PENDING)
        with mock.patch(
            "story_automator.core.lifecycle_status.iso_now",
            return_value="2099-01-01T00:00:00Z",
        ):
            new_status = advance_node_state(status, "n1", NodeState.RUNNING)
        self.assertEqual(new_status.nodes["n1"].updated_at, "2099-01-01T00:00:00Z")
        self.assertEqual(new_status.updated_at, "2099-01-01T00:00:00Z")
```

- [ ] **Step 2: Implement `advance_node_state`**

Append to `lifecycle_status.py`:

```python


def advance_node_state(
    status: LifecycleStatus,
    node_id: str,
    new_state: NodeState,
    *,
    now: str | None = None,
    notes: str = "",
) -> LifecycleStatus:
    """Return a new ``LifecycleStatus`` with ``node_id`` transitioned.

    Validates the transition against ``LEGAL_TRANSITIONS`` and raises
    ``StatusLoadError`` for any illegal edge (so callers see one error
    class for "this status doc can't accept that change", whether the
    failure is at load time or mid-run). The input ``status`` is not
    mutated.
    """
    if node_id not in status.nodes:
        raise StatusLoadError(f"unknown node id: {node_id!r}")
    current = status.nodes[node_id]
    edge = (current.state, new_state)
    if edge not in LEGAL_TRANSITIONS:
        raise StatusLoadError(
            f"illegal transition for {node_id!r}: "
            f"{current.state.value} -> {new_state.value}"
        )
    stamp = now if now is not None else iso_now()
    new_nodes = dict(status.nodes)
    new_nodes[node_id] = NodeRecord(
        node_id=node_id, state=new_state, updated_at=stamp, notes=notes,
    )
    return replace(status, nodes=new_nodes, updated_at=stamp)
```

Run: expect 22 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py tests/test_lifecycle_status.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): add advance_node_state with LEGAL_TRANSITIONS guard"
```

---

## Task 11: Scheduler `topo_sort` — happy path + cycle detection

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`
- Create: `tests/test_lifecycle_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_lifecycle_scheduler.py`:

```python
from __future__ import annotations

import unittest

from story_automator.core.lifecycle_policy import (
    EntrySection,
    LifecycleNode,
    LifecyclePolicy,
)
from story_automator.core.lifecycle_scheduler import (
    SchedulerError,
    topo_sort,
)


def _node(node_id: str, deps: tuple[str, ...] = (), **overrides: object) -> LifecycleNode:
    defaults: dict[str, object] = dict(
        id=node_id, track="bmm", phase=1, skill="s",
        verifier="v", gate="auto", agent_role="r", deps=deps,
    )
    defaults.update(overrides)
    return LifecycleNode(**defaults)  # type: ignore[arg-type]


def _policy(nodes: tuple[LifecycleNode, ...]) -> LifecyclePolicy:
    return LifecyclePolicy(version=1, nodes=nodes, entry=EntrySection())


class TopoSortTests(unittest.TestCase):
    def test_linear_chain(self) -> None:
        policy = _policy((
            _node("c", deps=("b",)),
            _node("a"),
            _node("b", deps=("a",)),
        ))
        order = topo_sort(policy)
        self.assertEqual(order, ("a", "b", "c"))

    def test_diamond_lex_tiebreak(self) -> None:
        # a -> b -> d, a -> c -> d. b and c both ready after a; lex tie-break -> b first.
        policy = _policy((
            _node("a"),
            _node("c", deps=("a",)),
            _node("b", deps=("a",)),
            _node("d", deps=("b", "c")),
        ))
        self.assertEqual(topo_sort(policy), ("a", "b", "c", "d"))

    def test_disconnected_nodes_lex_order(self) -> None:
        policy = _policy((_node("z"), _node("a"), _node("m")))
        self.assertEqual(topo_sort(policy), ("a", "m", "z"))

    def test_cycle_raises_scheduler_error(self) -> None:
        policy = _policy((
            _node("a", deps=("b",)),
            _node("b", deps=("a",)),
        ))
        with self.assertRaises(SchedulerError):
            topo_sort(policy)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement `topo_sort` and `SchedulerError`**

Append to `lifecycle_scheduler.py`:

```python


class SchedulerError(ValueError):
    """Raised when the scheduler cannot serve a request.

    Distinct from ``PolicyLoadError`` so call-sites can tell "the policy
    is bad" from "the scheduler refused to act on it." In practice, since
    ``validate_lifecycle_policy`` already rejects cycles, ``SchedulerError``
    here is mostly a defensive belt: if a caller hand-constructs a policy
    without going through ``load_lifecycle_policy``, the scheduler still
    detects the cycle at sort time.
    """


def topo_sort(policy: LifecyclePolicy) -> tuple[str, ...]:
    """Return a stable topological order of ``policy.nodes`` ids.

    Ties (multiple ready nodes) are broken lexicographically so two
    calls with the same policy produce byte-equal tuples. Raises
    ``SchedulerError`` on cycle.
    """
    in_degree: dict[str, int] = {n.id: 0 for n in policy.nodes}
    successors: dict[str, list[str]] = {n.id: [] for n in policy.nodes}
    for node in policy.nodes:
        for dep in node.deps:
            if dep not in in_degree:
                raise SchedulerError(
                    f"node {node.id!r}: dep {dep!r} refers to unknown node"
                )
            in_degree[node.id] += 1
            successors[dep].append(node.id)

    ready = sorted([nid for nid, deg in in_degree.items() if deg == 0])
    order: list[str] = []
    while ready:
        current = ready.pop(0)
        order.append(current)
        new_ready: list[str] = []
        for successor in successors[current]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                new_ready.append(successor)
        if new_ready:
            ready.extend(new_ready)
            ready.sort()
    if len(order) != len(policy.nodes):
        unresolved = sorted(
            n.id for n in policy.nodes if n.id not in order
        )
        raise SchedulerError(
            f"dependency graph contains a cycle among: {unresolved!r}"
        )
    return tuple(order)
```

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_scheduler -v`. Expect 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py tests/test_lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): topo_sort with lex tie-break and cycle detection"
```

---

## Task 12: `select_runnable` — dep-state gating

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`
- Modify: `tests/test_lifecycle_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Add to imports:

```python
from story_automator.core.lifecycle_scheduler import select_runnable
from story_automator.core.lifecycle_status import (
    LifecycleStatus,
    NodeRecord,
    NodeState,
)
```

Append:

```python
def _pending_status(node_ids: tuple[str, ...]) -> LifecycleStatus:
    return LifecycleStatus(
        run_id="run-1",
        nodes={
            nid: NodeRecord(
                node_id=nid, state=NodeState.PENDING,
                updated_at="2026-06-17T00:00:00Z",
            )
            for nid in node_ids
        },
        artifacts={},
        updated_at="2026-06-17T00:00:00Z",
    )


class SelectRunnableDepGatingTests(unittest.TestCase):
    def test_no_deps_all_pending_returns_root_only(self) -> None:
        policy = _policy((
            _node("a"),
            _node("b", deps=("a",)),
        ))
        status = _pending_status(("a", "b"))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("a",))

    def test_dep_complete_unblocks_downstream(self) -> None:
        policy = _policy((
            _node("a"),
            _node("b", deps=("a",)),
        ))
        status = _pending_status(("a", "b"))
        status = status.with_node(NodeRecord(
            node_id="a", state=NodeState.COMPLETE,
            updated_at="2026-06-17T00:00:00Z",
        ))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("b",))

    def test_dep_approved_also_unblocks_downstream(self) -> None:
        # Spec: a dep is satisfied when its state is APPROVED or COMPLETE.
        policy = _policy((
            _node("a", gate="human"),
            _node("b", deps=("a",)),
        ))
        status = _pending_status(("a", "b"))
        status = status.with_node(NodeRecord(
            node_id="a", state=NodeState.APPROVED,
            updated_at="2026-06-17T00:00:00Z",
        ))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("b",))

    def test_dep_verified_blocks(self) -> None:
        # VERIFIED is past auto-verify but pre-gate — downstream stays blocked.
        policy = _policy((
            _node("a", gate="human"),
            _node("b", deps=("a",)),
        ))
        status = _pending_status(("a", "b"))
        status = status.with_node(NodeRecord(
            node_id="a", state=NodeState.VERIFIED,
            updated_at="2026-06-17T00:00:00Z",
        ))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ())

    def test_running_node_not_re_picked(self) -> None:
        policy = _policy((_node("a"),))
        status = _pending_status(("a",))
        status = status.with_node(NodeRecord(
            node_id="a", state=NodeState.RUNNING,
            updated_at="2026-06-17T00:00:00Z",
        ))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(runnable, ())

    def test_returns_stable_order(self) -> None:
        # Two parallel root nodes; result tuple must come out in topo-lex order.
        policy = _policy((_node("z"), _node("a"), _node("m")))
        status = _pending_status(("z", "a", "m"))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("a", "m", "z"))
```

- [ ] **Step 2: Implement `select_runnable` (no concurrency/artifacts yet)**

Append to `lifecycle_scheduler.py`:

```python


_DEP_SATISFIED_STATES = frozenset({NodeState.APPROVED, NodeState.COMPLETE})


def select_runnable(
    *,
    policy: LifecyclePolicy,
    status: LifecycleStatus,
    max_concurrent: int = 0,
) -> tuple[LifecycleNode, ...]:
    """Return ``LifecycleNode`` instances eligible to start now.

    A node ``N`` is runnable iff:
    1. ``status.nodes[N.id]`` exists AND its ``state == NodeState.PENDING``
    2. for every dep ``d`` in ``N.deps``, ``status.nodes[d]`` exists AND
       its ``state in {APPROVED, COMPLETE}``
    3. for every artifact id ``a`` in ``N.input_artifacts``,
       ``a in status.artifacts``

    Policy nodes with no entry in ``status.nodes`` are silently skipped
    (treated as not-yet-bootstrapped). The runner (M02) is responsible
    for seeding a PENDING record for every policy node before calling
    this function — this M01 layer does not mutate the status and does
    not auto-bootstrap.

    Results are returned in topological order; ties break lexicographically
    by ``node_id``. ``max_concurrent`` caps the result size; ``0`` means
    no cap; negative values raise ``SchedulerError``.
    """
    order = topo_sort(policy)
    by_id = {n.id: n for n in policy.nodes}
    runnable: list[LifecycleNode] = []
    for node_id in order:
        node = by_id[node_id]
        record = status.nodes.get(node_id)
        if record is None or record.state is not NodeState.PENDING:
            continue
        if not all(
            (status.nodes.get(dep) is not None
             and status.nodes[dep].state in _DEP_SATISFIED_STATES)
            for dep in node.deps
        ):
            continue
        runnable.append(node)
    return tuple(runnable)
```

Run: expect 10 tests pass total in `test_lifecycle_scheduler`.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py tests/test_lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): select_runnable with dep-state gating (APPROVED|COMPLETE satisfies)"
```

---

## Task 13: `select_runnable` — `input_artifacts` gating

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`
- Modify: `tests/test_lifecycle_scheduler.py`

- [ ] **Step 1: Write the failing artifact-gating tests**

Add import: `from story_automator.core.lifecycle_status import ArtifactRecord`.

Append:

```python
class SelectRunnableArtifactGatingTests(unittest.TestCase):
    def test_missing_input_artifact_blocks(self) -> None:
        policy = _policy((
            _node("a", output_artifact="art-1"),
            _node("b", deps=("a",), input_artifacts=("art-1",)),
        ))
        status = _pending_status(("a", "b"))
        # Mark 'a' complete BUT do not register the artifact yet.
        status = status.with_node(NodeRecord(
            node_id="a", state=NodeState.COMPLETE,
            updated_at="2026-06-17T00:00:00Z",
        ))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(runnable, ())

    def test_input_artifact_present_unblocks(self) -> None:
        policy = _policy((
            _node("a", output_artifact="art-1"),
            _node("b", deps=("a",), input_artifacts=("art-1",)),
        ))
        status = _pending_status(("a", "b"))
        status = status.with_node(NodeRecord(
            node_id="a", state=NodeState.COMPLETE,
            updated_at="2026-06-17T00:00:00Z",
        ))
        status = status.with_artifact(ArtifactRecord(
            artifact_id="art-1", path="epics/",
            produced_by_node="a", produced_at="2026-06-17T00:00:00Z",
        ))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("b",))

    def test_multiple_artifacts_all_required(self) -> None:
        policy = _policy((
            _node("a", output_artifact="art-1"),
            _node("b", output_artifact="art-2"),
            _node("c", deps=("a", "b"), input_artifacts=("art-1", "art-2")),
        ))
        status = _pending_status(("a", "b", "c"))
        status = status.with_node(NodeRecord(
            node_id="a", state=NodeState.COMPLETE,
            updated_at="2026-06-17T00:00:00Z",
        ))
        status = status.with_node(NodeRecord(
            node_id="b", state=NodeState.COMPLETE,
            updated_at="2026-06-17T00:00:00Z",
        ))
        status = status.with_artifact(ArtifactRecord(
            artifact_id="art-1", path="p1",
            produced_by_node="a", produced_at="t",
        ))
        # Only one of two artifacts registered.
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(runnable, ())
        # Add the second.
        status = status.with_artifact(ArtifactRecord(
            artifact_id="art-2", path="p2",
            produced_by_node="b", produced_at="t",
        ))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("c",))
```

- [ ] **Step 2: Extend `select_runnable` with the artifact check**

In `select_runnable`, after the dep check and before appending, add:

```python
        if not all(aid in status.artifacts for aid in node.input_artifacts):
            continue
```

Run: expect 13 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py tests/test_lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): gate select_runnable on input_artifacts presence"
```

---

## Task 14: `select_runnable` — bounded concurrency

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py`
- Modify: `tests/test_lifecycle_scheduler.py`

- [ ] **Step 1: Write the failing concurrency tests**

Append:

```python
class SelectRunnableConcurrencyTests(unittest.TestCase):
    def test_max_concurrent_caps_result(self) -> None:
        policy = _policy((_node("a"), _node("b"), _node("c")))
        status = _pending_status(("a", "b", "c"))
        runnable = select_runnable(policy=policy, status=status, max_concurrent=2)
        self.assertEqual(tuple(n.id for n in runnable), ("a", "b"))

    def test_max_concurrent_zero_means_unlimited(self) -> None:
        policy = _policy((_node("a"), _node("b"), _node("c")))
        status = _pending_status(("a", "b", "c"))
        runnable = select_runnable(policy=policy, status=status, max_concurrent=0)
        self.assertEqual(tuple(n.id for n in runnable), ("a", "b", "c"))

    def test_max_concurrent_greater_than_available_returns_all(self) -> None:
        policy = _policy((_node("a"), _node("b")))
        status = _pending_status(("a", "b"))
        runnable = select_runnable(policy=policy, status=status, max_concurrent=10)
        self.assertEqual(tuple(n.id for n in runnable), ("a", "b"))

    def test_negative_max_concurrent_raises(self) -> None:
        policy = _policy((_node("a"),))
        status = _pending_status(("a",))
        with self.assertRaises(SchedulerError):
            select_runnable(policy=policy, status=status, max_concurrent=-1)


class SelectRunnableEdgeCaseTests(unittest.TestCase):
    def test_empty_policy_returns_empty_tuple(self) -> None:
        policy = _policy(())
        status = LifecycleStatus(
            run_id="run-1", nodes={}, artifacts={},
            updated_at="2026-06-17T00:00:00Z",
        )
        self.assertEqual(select_runnable(policy=policy, status=status), ())
        self.assertEqual(topo_sort(policy), ())

    def test_node_in_policy_but_missing_from_status_is_silently_skipped(self) -> None:
        # Documented contract: select_runnable returns nodes whose record exists
        # in status AND is PENDING. Policy nodes with no status record are
        # silently skipped — the runner (M02) bootstraps the status doc by
        # seeding PENDING records for every policy node before calling the
        # scheduler. This test pins the M01 contract.
        policy = _policy((_node("a"), _node("b")))
        # Only seed 'a'; 'b' has no record.
        status = _pending_status(("a",))
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("a",))


class SelectRunnablePurityTests(unittest.TestCase):
    def test_inputs_not_mutated(self) -> None:
        policy = _policy((
            _node("a", output_artifact="art-1"),
            _node("b", deps=("a",), input_artifacts=("art-1",)),
        ))
        status = _pending_status(("a", "b"))
        nodes_snapshot = dict(status.nodes)
        artifacts_snapshot = dict(status.artifacts)
        policy_nodes_snapshot = policy.nodes
        select_runnable(policy=policy, status=status, max_concurrent=2)
        self.assertEqual(status.nodes, nodes_snapshot)
        self.assertEqual(status.artifacts, artifacts_snapshot)
        self.assertEqual(policy.nodes, policy_nodes_snapshot)

    def test_two_calls_return_byte_equal_tuples(self) -> None:
        policy = _policy((_node("z"), _node("a"), _node("m")))
        status = _pending_status(("z", "a", "m"))
        first = select_runnable(policy=policy, status=status)
        second = select_runnable(policy=policy, status=status)
        # Same node-id sequence AND same node objects (since policy is identical).
        self.assertEqual(
            tuple(n.id for n in first), tuple(n.id for n in second),
        )
        for a, b in zip(first, second, strict=True):
            self.assertIs(a, b)
```

- [ ] **Step 2: Extend `select_runnable`**

At the start of `select_runnable`:

```python
    if max_concurrent < 0:
        raise SchedulerError(
            f"max_concurrent must be >= 0, got {max_concurrent}"
        )
```

At the end, before `return tuple(runnable)`:

```python
    if max_concurrent > 0:
        runnable = runnable[:max_concurrent]
```

Run: expect 17 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py tests/test_lifecycle_scheduler.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): bounded concurrency cap on select_runnable result"
```

---

## Task 15: End-to-end bridge fixture + integration test

**Files:**
- Create: `tests/fixtures/lifecycle/policy-bridge.json`
- Create: `tests/test_lifecycle_integration.py`

This task proves the spec acceptance criterion "scheduler selects correct runnable nodes on fixtures" + "resume reconstructs state from disk" against a fixture that mirrors §4's Phase 3→4 bridge shape (without yet implementing §4).

- [ ] **Step 1: Create the bridge fixture**

Create `tests/fixtures/lifecycle/policy-bridge.json` representing a stripped-down PRD → architecture → epics pipeline:

```json
{
  "version": 1,
  "nodes": [
    {
      "id": "B1-prd",
      "track": "bmm",
      "phase": 2,
      "skill": "bmad-prd",
      "verifier": "artifact_exists",
      "gate": "human",
      "agent_role": "pm",
      "deps": [],
      "input_artifacts": [],
      "output_artifact": "prd",
      "modes": ["greenfield"]
    },
    {
      "id": "B2-arch",
      "track": "bmm",
      "phase": 3,
      "skill": "bmad-architecture",
      "verifier": "artifact_exists",
      "gate": "human",
      "agent_role": "architect",
      "deps": ["B1-prd"],
      "input_artifacts": ["prd"],
      "output_artifact": "architecture",
      "modes": ["greenfield"]
    },
    {
      "id": "B3-epics",
      "track": "bmm",
      "phase": 3,
      "skill": "bmad-create-epics-and-stories",
      "verifier": "epics_created",
      "gate": "human",
      "agent_role": "planner",
      "deps": ["B2-arch"],
      "input_artifacts": ["prd", "architecture"],
      "output_artifact": "epics",
      "modes": ["greenfield"]
    },
    {
      "id": "B4-sprint",
      "track": "bmm",
      "phase": 4,
      "skill": "bmad-story-automator",
      "verifier": "session_exit",
      "gate": "auto",
      "agent_role": "executor",
      "deps": ["B3-epics"],
      "input_artifacts": ["epics"],
      "output_artifact": "",
      "modes": ["greenfield"]
    }
  ],
  "entry": {
    "greenfield": ["B1-prd"],
    "brownfield": []
  }
}
```

- [ ] **Step 2: Write the integration test**

Create `tests/test_lifecycle_integration.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.lifecycle_policy import load_lifecycle_policy
from story_automator.core.lifecycle_scheduler import select_runnable
from story_automator.core.lifecycle_status import (
    ArtifactRecord,
    LifecycleStatus,
    NodeRecord,
    NodeState,
    advance_node_state,
    load_lifecycle_status,
    write_lifecycle_status,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


def _empty_status(policy_node_ids: tuple[str, ...], run_id: str = "run-1") -> LifecycleStatus:
    return LifecycleStatus(
        run_id=run_id,
        nodes={
            nid: NodeRecord(
                node_id=nid, state=NodeState.PENDING,
                updated_at="2026-06-17T00:00:00Z",
            )
            for nid in policy_node_ids
        },
        artifacts={},
        updated_at="2026-06-17T00:00:00Z",
    )


class BridgeFixtureWalkTests(unittest.TestCase):
    def test_walks_bridge_pipeline_to_phase_4(self) -> None:
        policy = load_lifecycle_policy(FIXTURE_DIR / "policy-bridge.json")
        node_ids = tuple(n.id for n in policy.nodes)
        status = _empty_status(node_ids)

        # Step 1: only B1-prd is runnable.
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("B1-prd",))

        # Advance B1 through running -> verified -> awaiting -> approved -> complete.
        status = advance_node_state(status, "B1-prd", NodeState.RUNNING, now="t1")
        status = advance_node_state(status, "B1-prd", NodeState.VERIFIED, now="t2")
        status = advance_node_state(status, "B1-prd", NodeState.AWAITING_APPROVAL, now="t3")
        status = advance_node_state(status, "B1-prd", NodeState.APPROVED, now="t4")
        status = status.with_artifact(ArtifactRecord(
            artifact_id="prd", path="prd.md",
            produced_by_node="B1-prd", produced_at="t4",
        ))

        # Now B2-arch is runnable (B1 APPROVED satisfies dep + artifact registered).
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("B2-arch",))

        # Advance B2 to APPROVED with artifact.
        status = advance_node_state(status, "B2-arch", NodeState.RUNNING, now="t5")
        status = advance_node_state(status, "B2-arch", NodeState.VERIFIED, now="t6")
        status = advance_node_state(status, "B2-arch", NodeState.AWAITING_APPROVAL, now="t7")
        status = advance_node_state(status, "B2-arch", NodeState.APPROVED, now="t8")
        status = status.with_artifact(ArtifactRecord(
            artifact_id="architecture", path="arch.md",
            produced_by_node="B2-arch", produced_at="t8",
        ))

        # B3-epics needs both 'prd' and 'architecture'; both registered.
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("B3-epics",))

        # Advance B3 + artifact.
        status = advance_node_state(status, "B3-epics", NodeState.RUNNING, now="t9")
        status = advance_node_state(status, "B3-epics", NodeState.VERIFIED, now="t10")
        status = advance_node_state(status, "B3-epics", NodeState.AWAITING_APPROVAL, now="t11")
        status = advance_node_state(status, "B3-epics", NodeState.APPROVED, now="t12")
        status = status.with_artifact(ArtifactRecord(
            artifact_id="epics", path="epics/",
            produced_by_node="B3-epics", produced_at="t12",
        ))

        # B4-sprint (auto gate) is now runnable.
        runnable = select_runnable(policy=policy, status=status)
        self.assertEqual(tuple(n.id for n in runnable), ("B4-sprint",))

    def test_resume_reconstructs_state_from_disk(self) -> None:
        policy = load_lifecycle_policy(FIXTURE_DIR / "policy-bridge.json")
        node_ids = tuple(n.id for n in policy.nodes)
        status = _empty_status(node_ids)
        status = advance_node_state(status, "B1-prd", NodeState.RUNNING, now="t1")
        status = advance_node_state(status, "B1-prd", NodeState.VERIFIED, now="t2")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "lifecycle-status.yaml"
            write_lifecycle_status(status, path)
            # Fresh load (simulates a process restart).
            reloaded = load_lifecycle_status(path)

        # Continue from the reloaded state: only B1 progressed; rest still PENDING.
        self.assertEqual(reloaded.nodes["B1-prd"].state, NodeState.VERIFIED)
        for nid in ("B2-arch", "B3-epics", "B4-sprint"):
            self.assertEqual(reloaded.nodes[nid].state, NodeState.PENDING)

        # The scheduler can still operate on the reloaded snapshot.
        runnable = select_runnable(policy=policy, status=reloaded)
        self.assertEqual(runnable, ())  # B1 is VERIFIED but not yet APPROVED.

    def test_bounded_concurrency_with_parallel_roots(self) -> None:
        # Same fixture, but conceptually if two ROOTS existed they'd cap at N.
        # Bridge fixture only has one root, so verify with the empty status that
        # max_concurrent doesn't accidentally return more than one when only one
        # is runnable.
        policy = load_lifecycle_policy(FIXTURE_DIR / "policy-bridge.json")
        node_ids = tuple(n.id for n in policy.nodes)
        status = _empty_status(node_ids)
        runnable = select_runnable(policy=policy, status=status, max_concurrent=10)
        self.assertEqual(tuple(n.id for n in runnable), ("B1-prd",))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the integration suite**

`PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_integration -v`. Expect 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/lifecycle/policy-bridge.json tests/test_lifecycle_integration.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): bridge fixture end-to-end walk + resume integration test"
```

---

## Task 16: Module-surface invariants — `__all__`, future-annotations, allowlist, size, placeholder grep

**Files:**
- Create: `tests/test_lifecycle_module_surface.py`

These invariant tests ensure the three modules stay within their declared surface and the codebase guardrails (no new imports, no placeholders, future-annotations first, sub-500 LOC).

- [ ] **Step 1: Write the invariant tests**

Create `tests/test_lifecycle_module_surface.py`:

```python
from __future__ import annotations

import ast
import unittest
from pathlib import Path

import story_automator.core.lifecycle_policy as policy_mod
import story_automator.core.lifecycle_scheduler as scheduler_mod
import story_automator.core.lifecycle_status as status_mod


_LIFECYCLE_MODULES = (policy_mod, status_mod, scheduler_mod)
_FORBIDDEN_IMPORTS = (
    "yaml", "requests", "httpx", "aiohttp", "subprocess", "os.system",
)
_HARD_LINE_CAP = 500


def _source_of(module: object) -> str:
    path = Path(module.__file__)  # type: ignore[attr-defined]
    return path.read_text(encoding="utf-8")


class LifecycleAllListsTests(unittest.TestCase):
    def test_policy_all_exact(self) -> None:
        self.assertEqual(
            set(policy_mod.__all__),
            {
                "ALLOWED_GATES", "ALLOWED_MODES", "EntrySection",
                "LifecycleNode", "LifecyclePolicy", "PolicyLoadError",
                "load_lifecycle_policy", "validate_lifecycle_policy",
            },
        )

    def test_status_all_exact(self) -> None:
        self.assertEqual(
            set(status_mod.__all__),
            {
                "ArtifactRecord", "LEGAL_TRANSITIONS", "LifecycleStatus",
                "NodeRecord", "NodeState", "StatusLoadError",
                "advance_node_state", "load_lifecycle_status",
                "write_lifecycle_status",
            },
        )

    def test_scheduler_all_exact(self) -> None:
        self.assertEqual(
            set(scheduler_mod.__all__),
            {"SchedulerError", "select_runnable", "topo_sort"},
        )


class LifecycleFutureAnnotationsTests(unittest.TestCase):
    def test_future_annotations_first_after_docstring(self) -> None:
        for module in _LIFECYCLE_MODULES:
            with self.subTest(module=module.__name__):
                tree = ast.parse(_source_of(module))
                body = tree.body
                self.assertTrue(body)
                first = body[0]
                is_docstring = (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                )
                future_node = body[1] if is_docstring else first
                self.assertIsInstance(future_node, ast.ImportFrom)
                self.assertEqual(future_node.module, "__future__")
                self.assertEqual(
                    [a.name for a in future_node.names], ["annotations"]
                )


class LifecycleImportAllowlistTests(unittest.TestCase):
    def test_no_forbidden_third_party_imports(self) -> None:
        for module in _LIFECYCLE_MODULES:
            with self.subTest(module=module.__name__):
                source = _source_of(module)
                for token in _FORBIDDEN_IMPORTS:
                    self.assertNotIn(
                        token, source,
                        f"{module.__name__} imports forbidden token {token!r}",
                    )


class LifecycleModuleSizeTests(unittest.TestCase):
    def test_each_module_under_hard_cap(self) -> None:
        for module in _LIFECYCLE_MODULES:
            with self.subTest(module=module.__name__):
                line_count = len(_source_of(module).splitlines())
                self.assertLessEqual(
                    line_count, _HARD_LINE_CAP,
                    f"{module.__name__} is {line_count} lines (>{_HARD_LINE_CAP})",
                )


class LifecyclePlaceholderTokenTests(unittest.TestCase):
    def test_no_unresolved_four_letter_placeholders(self) -> None:
        # Concatenate so this test file itself does not trip the repo-wide grep.
        forbidden = ("TO" + "DO", "FI" + "XME", "XX" + "XX", "TB" + "DX")
        for module in _LIFECYCLE_MODULES:
            with self.subTest(module=module.__name__):
                source = _source_of(module)
                for token in forbidden:
                    self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run**

`PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_module_surface -v`. Expect 8 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_lifecycle_module_surface.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): enforce __all__, future-annotations, allowlist, size invariants"
```

---

## Task 17: Run the lint, format, and full-suite quality gates

This is the spec's "full suite + ruff green" acceptance criterion.

- [ ] **Step 1: Ruff lint on new files**

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py \
  tests/test_lifecycle_policy.py tests/test_lifecycle_status.py \
  tests/test_lifecycle_scheduler.py tests/test_lifecycle_integration.py \
  tests/test_lifecycle_module_surface.py
```

Expected: `All checks passed!` (exit 0). Common findings to fix inline:
- Unused imports (`mock`, `field`): remove or use them.
- E501 (line too long): wrap at 100 chars (project line-length convention from `ruff.toml`).
- F401 (unused import from `__all__`-style re-exports): silence with the `# noqa: F401` comment ONLY if the symbol is genuinely re-exported; otherwise remove the import.

- [ ] **Step 2: Ruff format check**

```bash
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py \
  tests/test_lifecycle_*.py
```

Expected: `N files already formatted` (exit 0). If a diff is reported, run `python -m ruff format <paths>` to apply, then re-run the `--check` variant.

- [ ] **Step 3: Repo-wide ruff (matches the spec gate verbatim)**

```bash
python -m ruff check skills tests
```

Expected: clean. The spec project-context block says "currently 1482 passing + `ruff check skills tests` clean. Every milestone must keep both green."

- [ ] **Step 4: Full unittest suite**

```bash
npm run test:python
```

Equivalent to `python -m unittest discover -s tests`. Expected: all root-level tests pass, exit 0. The pre-existing 1482 + the new ~50 lifecycle tests should all be green. If a pre-existing test breaks, that's a regression — investigate root cause; do not skip.

- [ ] **Step 5: `compileall` parse check on new modules**

```bash
python -m compileall \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py
```

Expected: `Compiling ... .` for each, exit 0.

- [ ] **Step 6: Placeholder-token repo grep on new files**

```bash
grep -nE "TODO|FIXME|XXXX|TBDX" \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_policy.py \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_status.py \
  skills/bmad-story-automator/src/story_automator/core/lifecycle_scheduler.py \
  tests/test_lifecycle_*.py
```

Expected: no matches (grep exit 1 is OK; the failure mode is exit 0 with matched lines).

- [ ] **Step 7: Verify gate (cross-platform)**

```bash
npm run verify
```

This runs `test:python`, `pack:dry-run`, `test:cli`, `test:smoke`. Expected: all green. If `test:cli` or `test:smoke` break because of the new modules — that's wrong, this milestone adds no CLI — investigate.

- [ ] **Step 8: Commit any cleanup**

If ruff or compileall required edits:

```bash
git add -A
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(lifecycle): apply ruff format and resolve quality-gate findings"
```

If nothing was changed, skip this commit.

---

## Task 18: Final spec self-review

- [ ] **Step 1: Walk the spec §1 acceptance criteria**

Open `docs/superpowers/specs/lifecycle/build-spec-core.md` §1 and confirm:

| Acceptance criterion | Where proved |
|---|---|
| schema validates + round-trips | `tests/test_lifecycle_policy.py` (LoadLifecyclePolicyTests + ValidateUniquenessTests + ValidateReferencesTests) |
| scheduler selects correct runnable nodes on fixtures | `tests/test_lifecycle_scheduler.py` (SelectRunnableDepGatingTests + ArtifactGatingTests + ConcurrencyTests) + `tests/test_lifecycle_integration.py` (BridgeFixtureWalkTests) |
| resume reconstructs state from disk | `tests/test_lifecycle_status.py::StatusRoundTripTests::test_resume_reconstructs_state_from_disk` + `tests/test_lifecycle_integration.py::test_resume_reconstructs_state_from_disk` |
| full suite + ruff green | Task 17 |

Confirm the spec §1 schema-field set is covered by `LifecycleNode`:
- `id`, `track`, `phase`, `skill` — required fields
- `validator_skill?` — optional, default `""`
- `deps[]`, `input_artifacts[]`, `output_artifact` — handled
- `verifier`, `gate(human|auto)` — handled with enum allowlist
- `modes[]` — handled with enum allowlist (greenfield|brownfield)
- `agent_role` — handled
- `interactive?` — handled (default False)
- `entry{greenfield[], brownfield[]}` — handled via `EntrySection`

Confirm the spec §1 state set is covered by `NodeState`:
- pending / running / verified / awaiting-approval / approved / complete / failed — all present (note: `awaiting_approval` uses underscore in the wire form to match Python attribute style; the spec writes it with a dash, which is converted at the boundary if a JSON producer uses the dashed form — Task 7 deliberately uses underscore for both attribute and value to keep the on-disk form parseable by `NodeState(value)` directly).

Wait — that's a subtle issue. The spec says `awaiting-approval` (dash). If the on-disk file uses `awaiting_approval` (underscore), a hand-written status file from the spec text won't round-trip. Resolve before commit:

- **Decision:** the wire form on disk uses **the underscore form (`awaiting_approval`)** because Python `Enum` values that round-trip via `NodeState(value)` are most natural that way. The spec wording uses the dash purely as English prose. If a future operator hand-edits and uses the dashed form, we'd hit `StatusLoadError("unknown node state value: 'awaiting-approval'")` — clear failure, not silent. M02 documentation will spell out the wire-form. Tasks already test this exactly (Task 7 `test_members_and_values` asserts lowercase-with-underscore values).

- [ ] **Step 2: Anti-scope sweep**

Confirm none of the following exist in this milestone's diff:
- No new files under `skills/bmad-story-automator/src/story_automator/commands/`
- No edits to `core/telemetry_events.py`
- No edits to `bin/`, `install.sh`, `scripts/`, or the npm `package.json`
- No new third-party imports (grep enforces this)
- No new CLI subcommand
- No agent spawning, no tmux, no subprocess calls in the three lifecycle modules

`git diff --stat main..HEAD` should list:
- 3 new core modules
- 5 new test files (policy, status, scheduler, integration, module_surface)
- 2 new fixtures (policy-minimal.json, policy-bridge.json)
- 1 new plan document (this file)
- 0 modified files

- [ ] **Step 3: Changelog (out of scope for this milestone)**

This milestone is library-only and does NOT ship behavior visible to operators. Per `CLAUDE.md` the changelog vocabulary applies to operator-visible deliverables — this is purely an internal data layer that M02 will surface. **Do not add a changelog entry in this milestone.** The bridge milestone (M04) will add the entry once the end-to-end Phase-3→4 bridge is operator-visible.

- [ ] **Step 4: Done**

The macro lifecycle data model and scheduler are fully implemented, fully tested, and quality-gate-clean. M02 (phase-runner + lifecycle_events.py) can import `LifecyclePolicy`, `LifecycleStatus`, `select_runnable`, and `advance_node_state` without further wiring.
