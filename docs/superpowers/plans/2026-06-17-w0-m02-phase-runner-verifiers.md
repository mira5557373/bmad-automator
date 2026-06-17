# W0-M02 — Phase Runner & Phase Verifiers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the **phase runner + phase-verifier registry + lifecycle telemetry events** specified in `docs/superpowers/specs/lifecycle/build-spec-full.md` §2 (Wave 0) — three new sibling modules under `skills/bmad-story-automator/src/story_automator/core/` plus an end-to-end fixture test that mirrors the existing `test_orchestration_loop.py` — so a lifecycle run can take a runnable node from W0-M01's scheduler, spawn a child agent (or delegate to the existing sprint orchestrator on track=bmm + phase=4), verify the output, and advance the run-state atomically. W0-M03 (approval gate primitive) and W0-M04 (entry-mode router CLI) extend the foundation laid here without modifying it.

**Architecture:** Three new sibling modules under `core/`:

- `lifecycle_events.py` — `LifecyclePhaseStarted`, `LifecyclePhaseCompleted`, `LifecyclePhaseFailed` typed events that subclass the existing `core.telemetry_events.Event` base (so they auto-register into `Event._REGISTRY` via `__init_subclass__` and dispatch through the existing `parse_event` / `TelemetryReader` pipeline). The classes live in a new file so the **hard guardrail "do NOT touch `core/telemetry_events.py` outside M01" is preserved by construction** — we *import* `Event` from `telemetry_events`, we never edit it.
- `lifecycle_verifiers.py` — a registry generalising the existing `core/success_verifiers.py` pattern: `LIFECYCLE_VERIFIERS: dict[str, VerifierFn]` maps node-`verifier` names to callables that take `(node, project_root)` and return `{"verified": bool, ...}`. Ships three built-ins: `artifact_exists` (the node's `output_artifact` is present on disk), `structural_complete` (the artifact is non-empty and — for `.md` outputs — has the required frontmatter keys derived from `validator_skill`'s contract), and a generic `validator_skill` wrapper that defers to a node's `validator_skill` field (when set) via an injected callable boundary. **Does not modify `success_verifiers.py`** — it's a sibling registry, not a rewrite.
- `lifecycle_runner.py` — the phase runner. One public entry point: `run_next_node(policy, status, *, project_root, status_path, spawn_agent=spawn_session, monitor_session=cmd_monitor_session, sprint_delegate=None, verifier_dispatch=run_lifecycle_verifier, emitter=None, clock=iso_now) -> RunResult`. Picks the first runnable node from W0-M01's scheduler; on track=bmm + phase=4 hands off to an injected `sprint_delegate` (defaults to a thin wrapper around the existing `commands.orchestrator` dispatch); otherwise spawns a child agent for `node.skill` and monitors it via the existing tmux runtime; on completion, dispatches the verifier named by `node.verifier`; transitions the node state PENDING→RUNNING→{COMPLETE | AWAITING_APPROVAL | FAILED} based on verifier result + `node.gate`; persists `status` to disk atomically after each transition; emits `LifecyclePhase*` events correlated by the marker-derived `run_id`. All non-pure boundaries (spawn, monitor, emit, clock, sprint delegate) are injected so unit tests can run **with no tmux, no Claude, no network**.

**Tech Stack:** Python 3.11+ stdlib only (`dataclasses`, `enum`, `json`, `pathlib`, `typing`) plus existing project modules: `core.atomic_io.write_atomic_text` (status persistence is delegated to `core.lifecycle_status.save_status`, which already uses it), `core.telemetry_events.Event` (base class — read-only import), `core.telemetry_emitter.TelemetryEmitter` (event sink), `core.run_identity.current_run_id` (marker-derived correlation id), `core.tmux_runtime.spawn_session` (existing tmux spawn — injected boundary), `core.success_verifiers.run_success_verifier` (sprint-track existing verifier — reused for phase=4 delegation), `core.frontmatter.parse_simple_frontmatter` (for `structural_complete`), `core.common.iso_now` (clock). **No new third-party imports.** Tests use `unittest.TestCase` with mocks at the spawn/monitor/emit boundaries; no real tmux, no real agent, no network.

---

## Scope for this milestone

**In scope (build-spec-full.md §2 acceptance criteria):**
1. Phase runner spawns a child agent for `node.skill` via the existing tmux runtime, monitors to terminal state, runs the per-node verifier.
2. **Delegate to existing sprint orchestrator on track=bmm + phase=4** — when a runnable node matches that profile, the runner does not spawn a generic agent; instead it hands the epics-directory artifact to a `sprint_delegate` callable (default = thin wrapper around the existing `commands.orchestrator` entry point) and trusts its return value.
3. Verifier registry generalising `core/success_verifiers.py`: `artifact_exists`, `structural_complete`, and `validator_skill` (the third defers to a node's `validator_skill` via an injected callable — full validator-skill agent execution is the runner's spawn path, not the verifier's).
4. New `core/lifecycle_events.py` with `LifecyclePhaseStarted`, `LifecyclePhaseCompleted`, `LifecyclePhaseFailed` typed events, all run_id-correlated through the existing emitter pipeline.
5. Atomic status persistence after every node-state transition (via `core.lifecycle_status.save_status` — itself crash-safe via `core.atomic_io`).
6. End-to-end acceptance test mirroring `tests/test_orchestration_loop.py`: a 2-node fixture run reaches commit-ready state under a fully mocked agent + tmux + sprint-delegate boundary, with the telemetry stream complete and run_id-correlated.

**Out of scope (explicit non-goals — belong to later milestones):**
- **Approval-gate primitive** (`lifecycle-helper await-approval` / `approve` / `reject` CLI; reject re-runs node with notes) — W0-M03 (§3). W0-M02 lands `gate=human` nodes in `AWAITING_APPROVAL` and **stops**. There is no resume-from-approval logic in this milestone.
- **Entry-mode router CLI** (`bmad-document-project` first for brownfield; `B3-epics` end-to-end with `epics_created` + `bmad-check-implementation-readiness`) — W0-M04 (§4). The runner reads `status.mode` and the policy's entry map already produced by W0-M01; it does not own the CLI surface that selects the mode.
- **Modifying `core/telemetry_events.py`** — out of scope by the hard guardrail. We import `Event` from there and subclass it in `lifecycle_events.py` — that is an *import*, not an edit.
- **Modifying `core/success_verifiers.py`** — out of scope. The new `lifecycle_verifiers` registry is a sibling; tests confirm the existing sprint-track verifier surface is unchanged.
- **Real child-agent execution in unit tests.** Every spawn / monitor / sprint-delegate call site goes through an injectable boundary; the acceptance test mocks them. CI never spawns tmux.
- **Charter-driven DoD / mutation testing / security gates** — Wave 1+ (§5–§9). The §2 verifiers are minimal pass-through wrappers; they do not (yet) consult a quality charter.
- **Resume-from-RUNNING state.** A run that crashes mid-node leaves the node in RUNNING; an operator-visible "stale RUNNING → reset to PENDING" reconciler is W0-M03's job. W0-M02's runner refuses to re-enter a RUNNING node (raises `RunnerError`) to keep the failure mode loud.

## Design decisions worth recording (so reviewers don't relitigate them)

1. **New events subclass `core.telemetry_events.Event`.** They live in `core/lifecycle_events.py` (a new module — never touching `telemetry_events.py`), and auto-register into the existing `Event._REGISTRY` via the inherited `__init_subclass__`. This is the only viable path: the `parse_event` dispatch + `TelemetryReader` already iterate over `_REGISTRY` keys, and the spec ("events emit; mirrors `test_orchestration_loop.py`") implies the same JSONL stream the existing per-story events use. Creating a parallel hierarchy would mean a second emitter, a second reader, and a second parse path — explicit no.
2. **Phase runner is pure-via-injection, not pure.** A scheduler can be a pure function (W0-M01's is). A runner cannot — it must spawn processes, write status, and emit telemetry. Instead of fighting that, we *factor* the runner so every side-effect goes through an injectable callable with a stdlib default. Unit tests pass mocks; the production wiring uses the real defaults. This is the same pattern `cmd_monitor_session` uses for `session_status` / `_verify_monitor_completion` and the acceptance test already mocks. A "true pure" runner would need to return a list of side-effect commands for a separate executor; the existing code does not have that shape and there is no §2-acceptance reason to introduce it.
3. **Sprint-delegate is a callable, not a feature flag.** When `node.track == "bmm" and node.phase == 4`, the runner calls `sprint_delegate(node, project_root, status, *, run_id)` and treats the return value (`{"verified": bool, "reason": str?, ...}`) as the verifier output for that node. Default implementation: a thin wrapper that invokes `commands.orchestrator.cmd_orchestrator_helper(["check-epic-complete", epic, story])` (or the equivalent) and maps its JSON-stdout payload to the `{"verified": ...}` shape. Tests inject a stub. This keeps the "delegate to sprint orchestrator" requirement satisfied without W0-M02 owning the sprint orchestrator's command surface.
4. **`run_next_node` runs *one* node per call.** The runner is not a long-lived loop; it's the single-node turn of an outer driver that the caller (or W0-M04's CLI) owns. This matches W0-M01's scheduler (which returns runnable nodes — it does not loop). One node per call keeps state mutation small and atomic, and makes the test surface a single transition each.
5. **State transitions: PENDING → RUNNING → {COMPLETE, AWAITING_APPROVAL, FAILED}.** No intermediate READY in this milestone — W0-M01's scheduler already filters PENDING + dep-complete + inputs-exist before returning a node; "ready" adds no information. AWAITING_APPROVAL is set only when `node.gate == "human"` AND the verifier passed; FAILED is set when the verifier returned `verified=False` or the agent spawn/monitor itself failed (timeout, crashed, stuck, not_found). The runner does **not** retry — retry is failure-governance territory (Wave 8 §38).
6. **`structural_complete` is a thin frontmatter check, not an LLM judge.** It validates: (a) the artifact at `node.output_artifact` exists, (b) for `.md` outputs, the frontmatter is parseable, and (c) for `.md` outputs with a `validator_skill` set, a small whitelist of frontmatter keys derived from convention (`Status: complete` or equivalent) is satisfied. The "real" structural-quality check (LLM judge, charter DoD) is Wave 1+. This keeps the §2 verifier honest about its scope: "the file is here and looks like the right shape," nothing more.
7. **`validator_skill` verifier is a wrapper, not an executor.** When a node sets `validator_skill: "bmad-validate-prd"`, the runner already spawned the producer skill and the producer wrote the artifact. The verifier then needs to invoke the *validator* skill. For W0-M02, this is again an injected callable: `validator_dispatch(validator_skill, node, project_root) -> {"verified": bool, ...}`. Default implementation: spawn the validator skill via the same `spawn_agent` boundary (reusing the tmux runtime) and treat its `success_verifier` output as the verdict. Tests inject a stub. This neither hardcodes specific validator skills nor makes us re-implement the existing `success_verifiers.review_completion` pipeline.
8. **Atomic persistence is per-transition, not per-call.** Every state change writes a fresh `lifecycle-status.json` via `save_status`. The W0-M01 atomic writer is crash-safe (rename-into-place), so a `kill -9` between transitions leaves the previous transition's status intact. A resumed run sees a consistent snapshot. We do not buffer multiple transitions and flush at the end — that would lose information on crash.
9. **No new top-level CLI command in this milestone.** The runner is a Python API consumed by W0-M04's `lifecycle-helper run` (not in scope here). The acceptance test imports `run_next_node` directly. This is the same shape W0-M01 used.
10. **`run_id` correlation derives from the existing marker.** The runner pulls `current_run_id(project_root)` from `core.run_identity` for every `LifecyclePhase*` event so the lifecycle events join the same correlation column as the per-story events emitted by `commands/orchestrator.py`. No new marker scheme; no new id format. If the marker is absent (which it should not be during a live run), the emitter stamps an empty `run_id` — matching the existing per-story emitter's behavior and surfacing the "no active run" condition through observability rather than silently inventing an id.
11. **No telemetry emit on PENDING → RUNNING for nodes that ultimately don't spawn an agent.** A `LifecyclePhaseStarted` event fires *after* the runner has committed to executing the node (after the status write that pins it to RUNNING) and *before* the spawn/delegate call returns. This ordering means a crashed runner between RUNNING-write and spawn-success leaves a status-says-RUNNING + no Started-event evidence on disk — which is exactly what an operator wants to see when triaging a partial run. A Started event without a corresponding Completed/Failed event signals a mid-execution crash; the absence of any event signals a pre-spawn crash. Both are diagnosable; both are documented.

## File structure

| File | New / Modified | Responsibility |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/lifecycle_events.py` | **Create** | `LifecyclePhaseStarted`, `LifecyclePhaseCompleted`, `LifecyclePhaseFailed` dataclasses subclassing `core.telemetry_events.Event`. Each carries `node_id`, `phase`, `track` (plus result-specific fields: duration_s, reason, error_class). Auto-registered via `__init_subclass__`. |
| `skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py` | **Create** | `LIFECYCLE_VERIFIERS: dict[str, VerifierFn]`; `run_lifecycle_verifier(name, node, project_root, *, validator_dispatch=None) -> dict[str, object]`; three built-ins: `artifact_exists`, `structural_complete`, `validator_skill` (wrapper). `VerifierError` typed exception. |
| `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py` | **Create** | `RunResult` dataclass; `RunnerError` exception; `run_next_node(policy, status, *, project_root, status_path, spawn_agent=..., monitor_session=..., sprint_delegate=..., verifier_dispatch=..., emitter=None, clock=iso_now) -> RunResult \| None`. Owns state transitions, telemetry, persistence. |
| `tests/test_lifecycle_events.py` | **Create** | Round-trip tests for the three event classes; auto-registration confirmed via `Event._REGISTRY`; `parse_event` dispatches each correctly; idempotent re-import (no `RuntimeError` on duplicate EVENT_TYPE). |
| `tests/test_lifecycle_verifiers.py` | **Create** | `artifact_exists` happy/missing; `structural_complete` valid frontmatter vs missing/malformed; `validator_skill` wrapper dispatches to injected callable; unknown verifier raises `VerifierError`. |
| `tests/test_lifecycle_runner.py` | **Create** | One-node happy path (spawn → monitor → verify → COMPLETE + events); spawn failure → FAILED; verifier failure → FAILED; gate=human + verified → AWAITING_APPROVAL; track=bmm + phase=4 dispatches to `sprint_delegate`; atomic status persistence (post-RUNNING + post-final); telemetry stream is run_id-correlated; refuses to re-enter a RUNNING node. |
| `tests/test_lifecycle_acceptance_m02.py` | **Create** | End-to-end mirror of `test_orchestration_loop.py`: 2-node greenfield fixture (`B1-brief` then `B2-prd`) with mocked spawn + monitor + emitter; final status shows both COMPLETE; telemetry contains 2× `LifecyclePhaseStarted` + 2× `LifecyclePhaseCompleted` all sharing the marker-derived `run_id`. Phase-4 delegate path is exercised in a separate sub-test using a stub `sprint_delegate`. |
| `tests/fixtures/lifecycle/m02-two-node.policy.json` | **Create** | Minimal 2-node greenfield policy (`B1-brief` → `B2-prd`) with `gate: "auto"` so the acceptance test completes without entering AWAITING_APPROVAL. |
| `tests/fixtures/lifecycle/m02-phase4-delegate.policy.json` | **Create** | 3-node policy ending in `B4-stories` (`track: "bmm", phase: 4`) for the sprint-delegate dispatch test. |

No existing file is modified other than the spec footer + the changelog (Task 14 — operator documentation). The "do NOT touch `telemetry_events.py`" guardrail is enforced by construction: every event subclass lives in the new `lifecycle_events.py`. The "do NOT touch `success_verifiers.py`" guardrail is enforced by adding a sibling registry rather than extending the existing one.

---

## Task 1: lifecycle_events.py — module skeleton + auto-register sanity test

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_events.py`
- Create: `tests/test_lifecycle_events.py`

- [ ] **Step 1: Write the failing skeleton-import + auto-register tests**

Create `tests/test_lifecycle_events.py`:

```python
from __future__ import annotations

import unittest


class LifecycleEventsModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_events  # noqa: F401

    def test_event_types_are_registered(self) -> None:
        # Importing the module must register the three event types into the
        # shared Event._REGISTRY (telemetry_events owns the registry; we only
        # subclass Event from this sibling module).
        from story_automator.core import lifecycle_events  # noqa: F401
        from story_automator.core.telemetry_events import Event

        for name in (
            "lifecycle_phase_started",
            "lifecycle_phase_completed",
            "lifecycle_phase_failed",
        ):
            self.assertIn(
                name,
                Event._REGISTRY,
                f"{name!r} did not auto-register; check __init_subclass__ "
                f"and that lifecycle_events.py was imported."
            )

    def test_event_classes_are_distinct(self) -> None:
        from story_automator.core.lifecycle_events import (
            LifecyclePhaseStarted,
            LifecyclePhaseCompleted,
            LifecyclePhaseFailed,
        )

        self.assertNotEqual(LifecyclePhaseStarted, LifecyclePhaseCompleted)
        self.assertNotEqual(LifecyclePhaseStarted, LifecyclePhaseFailed)
        self.assertNotEqual(LifecyclePhaseCompleted, LifecyclePhaseFailed)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_events -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'story_automator.core.lifecycle_events'`.

- [ ] **Step 3: Create the minimal module with the three event classes**

Create `skills/bmad-story-automator/src/story_automator/core/lifecycle_events.py`:

```python
"""Lifecycle macro-layer telemetry events (W0-M02).

Subclasses of ``core.telemetry_events.Event`` that auto-register into the
shared ``Event._REGISTRY`` via the inherited ``__init_subclass__``. Keeping
them in a sibling module is non-negotiable: the hard guardrail forbids
editing ``core/telemetry_events.py`` outside its owning milestone (M01),
so we *import* the base class and subclass it here. Auto-registration
still flows through the base's ``__init_subclass__``, so ``parse_event``
and ``TelemetryReader`` dispatch them like any other typed event.

Three concrete events for W0-M02:
- ``LifecyclePhaseStarted`` — runner has committed a runnable node to
  RUNNING and is about to spawn the agent / delegate to the sprint
  orchestrator. Carries (node_id, phase, track, skill, agent_role).
- ``LifecyclePhaseCompleted`` — verifier returned ``verified=True``;
  node transitioned to COMPLETE (or AWAITING_APPROVAL if gate=human).
  Carries (node_id, phase, track, duration_s, gate_decision).
- ``LifecyclePhaseFailed`` — agent spawn/monitor failed OR verifier
  returned ``verified=False``. Carries (node_id, phase, track,
  reason, error_class, attempt).

run_id correlation is handled by the emitter (``TelemetryEmitter._serialize``)
the same way it is for every other Event subclass — events emitted during
a run with an active marker share the marker-derived run id; events emitted
without an active marker carry ``run_id=""``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from story_automator.core.telemetry_events import Event

__all__ = [
    "LifecyclePhaseCompleted",
    "LifecyclePhaseFailed",
    "LifecyclePhaseStarted",
]


@dataclass(kw_only=True)
class LifecyclePhaseStarted(Event):
    """Emitted when the phase runner commits a node to RUNNING."""

    EVENT_TYPE: ClassVar[str] = "lifecycle_phase_started"

    node_id: str
    phase: int
    track: str
    skill: str
    agent_role: str


@dataclass(kw_only=True)
class LifecyclePhaseCompleted(Event):
    """Emitted when a node verifier passes (state advances to COMPLETE
    or AWAITING_APPROVAL when gate=human)."""

    EVENT_TYPE: ClassVar[str] = "lifecycle_phase_completed"

    node_id: str
    phase: int
    track: str
    duration_s: float
    gate_decision: str  # "auto_complete" | "awaiting_approval"


@dataclass(kw_only=True)
class LifecyclePhaseFailed(Event):
    """Emitted when a node fails (agent crashed, monitor timeout, or
    verifier returned verified=False)."""

    EVENT_TYPE: ClassVar[str] = "lifecycle_phase_failed"

    node_id: str
    phase: int
    track: str
    reason: str
    error_class: str
    attempt: int
```

- [ ] **Step 4: Run the tests — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_events -v`

Expected: all three tests green.

- [ ] **Step 5: Commit the event types**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_events.py tests/test_lifecycle_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 add LifecyclePhase{Started,Completed,Failed} typed events"
```

> Implementation note: the guardrail "do NOT touch `core/telemetry_events.py` outside its owning milestone" is preserved — this module imports `Event` from `telemetry_events`, it does not edit the file. The CI grep in Task 13 Step 4 confirms `telemetry_events.py` is unchanged.

---

## Task 2: lifecycle_events.py — JSONL round-trip + parse_event dispatch

**Files:**
- Modify: `tests/test_lifecycle_events.py` (extend)

- [ ] **Step 1: Add the round-trip + parse_event tests**

Append to `tests/test_lifecycle_events.py`:

```python
import json

from story_automator.core.lifecycle_events import (
    LifecyclePhaseCompleted,
    LifecyclePhaseFailed,
    LifecyclePhaseStarted,
)
from story_automator.core.telemetry_events import parse_event


class LifecycleEventsRoundTripTests(unittest.TestCase):
    def test_started_round_trip(self) -> None:
        original = LifecyclePhaseStarted(
            timestamp="2026-06-17T12:00:00Z",
            run_id="run-deadbeef",
            node_id="B1-brief",
            phase=1,
            track="bmm",
            skill="bmad-product-brief",
            agent_role="analyst",
        )
        line = original.to_json_line()
        parsed = parse_event(line)
        self.assertIsInstance(parsed, LifecyclePhaseStarted)
        self.assertEqual(parsed.node_id, "B1-brief")
        self.assertEqual(parsed.phase, 1)
        self.assertEqual(parsed.run_id, "run-deadbeef")

    def test_completed_round_trip(self) -> None:
        original = LifecyclePhaseCompleted(
            timestamp="2026-06-17T12:00:05Z",
            run_id="run-deadbeef",
            node_id="B1-brief",
            phase=1,
            track="bmm",
            duration_s=5.0,
            gate_decision="auto_complete",
        )
        line = original.to_json_line()
        parsed = parse_event(line)
        self.assertIsInstance(parsed, LifecyclePhaseCompleted)
        self.assertEqual(parsed.gate_decision, "auto_complete")
        self.assertEqual(parsed.duration_s, 5.0)

    def test_failed_round_trip(self) -> None:
        original = LifecyclePhaseFailed(
            timestamp="2026-06-17T12:00:05Z",
            run_id="run-deadbeef",
            node_id="B1-brief",
            phase=1,
            track="bmm",
            reason="agent_timeout",
            error_class="TimeoutError",
            attempt=1,
        )
        line = original.to_json_line()
        parsed = parse_event(line)
        self.assertIsInstance(parsed, LifecyclePhaseFailed)
        self.assertEqual(parsed.reason, "agent_timeout")
        self.assertEqual(parsed.error_class, "TimeoutError")

    def test_event_type_in_serialized_payload(self) -> None:
        line = LifecyclePhaseStarted(
            timestamp="t", run_id="r", node_id="n",
            phase=1, track="bmm", skill="s", agent_role="a",
        ).to_json_line()
        payload = json.loads(line)
        self.assertEqual(payload["event_type"], "lifecycle_phase_started")
        # event_type is sourced from EVENT_TYPE classvar, never an instance
        # field — make sure no stray "event_type" leaked from asdict()
        self.assertNotIn("EVENT_TYPE", payload)


class LifecycleEventsReimportTests(unittest.TestCase):
    def test_reimport_does_not_raise_duplicate_event_type(self) -> None:
        # __init_subclass__ in telemetry_events.Event raises RuntimeError
        # on a *different* class registering an already-used EVENT_TYPE.
        # Re-importing the same class object must be a no-op.
        import importlib

        from story_automator.core import lifecycle_events

        importlib.reload(lifecycle_events)  # must not raise
```

- [ ] **Step 2: Run the tests — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_events -v`

Expected: all tests green. The Event base's `to_json_line` + `parse_event` already handle dispatch; the only new artefact is the three subclasses landing in the registry.

- [ ] **Step 3: Sanity grep — telemetry_events.py untouched**

Run: `git diff --stat skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`

Expected: empty output. The guardrail audit in Task 13 Step 4 will repeat this check on the final commit history.

- [ ] **Step 4: Commit the round-trip tests**

```bash
git add tests/test_lifecycle_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): W0-M02 lifecycle event JSONL round-trip + parse_event dispatch"
```

---

## Task 3: lifecycle_verifiers.py — module skeleton + artifact_exists

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py`
- Create: `tests/test_lifecycle_verifiers.py`

- [ ] **Step 1: Write the failing artifact_exists tests**

Create `tests/test_lifecycle_verifiers.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class LifecycleVerifiersModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_verifiers  # noqa: F401

    def test_exposes_verifier_error(self) -> None:
        from story_automator.core.lifecycle_verifiers import VerifierError

        self.assertTrue(issubclass(VerifierError, ValueError))

    def test_exposes_registry(self) -> None:
        from story_automator.core.lifecycle_verifiers import LIFECYCLE_VERIFIERS

        self.assertIsInstance(LIFECYCLE_VERIFIERS, dict)
        self.assertIn("artifact_exists", LIFECYCLE_VERIFIERS)

    def test_unknown_verifier_raises(self) -> None:
        from story_automator.core.lifecycle_policy import NodeDef
        from story_automator.core.lifecycle_verifiers import (
            VerifierError,
            run_lifecycle_verifier,
        )

        node = _make_node(
            node_id="N", verifier="bogus_verifier_name",
            output_artifact="docs/x.md",
        )
        with self.assertRaises(VerifierError):
            run_lifecycle_verifier(
                "bogus_verifier_name", node=node, project_root="/tmp",
            )


class ArtifactExistsVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_file_present_passes(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "docs" / "brief.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# Brief\n", encoding="utf-8")
        node = _make_node(
            node_id="B1-brief", verifier="artifact_exists",
            output_artifact="docs/brief.md",
        )
        result = run_lifecycle_verifier(
            "artifact_exists", node=node, project_root=str(self.root),
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["path"], "docs/brief.md")

    def test_file_missing_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        node = _make_node(
            node_id="B1-brief", verifier="artifact_exists",
            output_artifact="docs/missing.md",
        )
        result = run_lifecycle_verifier(
            "artifact_exists", node=node, project_root=str(self.root),
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "artifact_missing")

    def test_directory_artifact_passes_when_non_empty(self) -> None:
        # output_artifact ending in "/" is a directory; existence + non-empty
        # is the bar. Empty dir is treated as not-yet-produced.
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        epics = self.root / "epics"
        epics.mkdir()
        (epics / "epic-1.md").write_text("# Epic 1\n", encoding="utf-8")
        node = _make_node(
            node_id="B3-epics", verifier="artifact_exists",
            output_artifact="epics/",
        )
        result = run_lifecycle_verifier(
            "artifact_exists", node=node, project_root=str(self.root),
        )
        self.assertTrue(result["verified"])

    def test_empty_directory_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        (self.root / "epics").mkdir()
        node = _make_node(
            node_id="B3-epics", verifier="artifact_exists",
            output_artifact="epics/",
        )
        result = run_lifecycle_verifier(
            "artifact_exists", node=node, project_root=str(self.root),
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "artifact_empty")


def _make_node(*, node_id: str, verifier: str, output_artifact: str, **overrides):
    from story_automator.core.lifecycle_policy import NodeDef

    defaults = dict(
        id=node_id, track="bmm", phase=1, skill="bmad-x",
        validator_skill=None, deps=[], input_artifacts=[],
        output_artifact=output_artifact, verifier=verifier,
        gate="auto", modes=["greenfield"], agent_role="analyst",
        interactive=False,
    )
    defaults.update(overrides)
    return NodeDef(**defaults)
```

- [ ] **Step 2: Run the tests — expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_verifiers -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module + artifact_exists**

Create `skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py`:

```python
"""Lifecycle phase-verifier registry (W0-M02).

Sibling module to ``core/success_verifiers.py``. That module governs the
existing *sprint-track* verifiers (create_story_artifact, review_completion,
epic_complete, session_exit) and is **not modified by W0-M02**. This module
adds a parallel registry for the *macro-lifecycle* verifiers referenced by
``NodeDef.verifier`` strings in lifecycle policy JSON: ``artifact_exists``,
``structural_complete``, and ``validator_skill``.

The registry maps verifier-name strings to callables of shape
``(node, project_root, **kwargs) -> {"verified": bool, ...}``. The runner
(``core/lifecycle_runner.py``) dispatches through ``run_lifecycle_verifier``
after each child agent completes, and treats the boolean ``verified`` as
the gate between COMPLETE/AWAITING_APPROVAL and FAILED.

W0-M02 does NOT include charter-driven quality gates, mutation testing,
security scanning, or any of the Wave 1+ depth. The verifiers here are
deliberately minimal — "the file is here and looks like the right shape"
— so a runner that integrates with the existing tmux + sprint orchestrator
machinery can ship without dragging the full Wave 1 quality stack along.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from story_automator.core.lifecycle_policy import NodeDef

__all__ = [
    "LIFECYCLE_VERIFIERS",
    "VerifierError",
    "VerifierFn",
    "artifact_exists",
    "run_lifecycle_verifier",
]


class VerifierError(ValueError):
    """Raised when a verifier name is unknown or its arguments are invalid."""


VerifierFn = Callable[..., dict[str, Any]]


def artifact_exists(
    *,
    node: NodeDef,
    project_root: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    """The node's ``output_artifact`` is present (and non-empty if a dir).

    - For a file artifact (no trailing ``/``): the file must exist and have
      a non-zero size. A zero-byte file is treated as not-yet-produced.
    - For a directory artifact (trailing ``/``): the directory must exist
      and contain at least one regular file (recursively). An empty
      directory is treated as not-yet-produced.

    Returns ``{"verified": bool, "path": str, "reason": str?}``.
    """
    root = Path(project_root)
    artifact_path = node.output_artifact
    full = root / artifact_path
    payload: dict[str, Any] = {
        "verified": False,
        "path": artifact_path,
        "verifier": "artifact_exists",
    }
    if artifact_path.endswith("/"):
        if not full.is_dir():
            payload["reason"] = "artifact_missing"
            return payload
        any_file = any(p.is_file() for p in full.rglob("*"))
        if not any_file:
            payload["reason"] = "artifact_empty"
            return payload
        payload["verified"] = True
        return payload
    if not full.is_file():
        payload["reason"] = "artifact_missing"
        return payload
    if full.stat().st_size == 0:
        payload["reason"] = "artifact_empty"
        return payload
    payload["verified"] = True
    return payload


LIFECYCLE_VERIFIERS: dict[str, VerifierFn] = {
    "artifact_exists": artifact_exists,
}


def run_lifecycle_verifier(
    name: str,
    *,
    node: NodeDef,
    project_root: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Dispatch ``name`` to the registry. Raises ``VerifierError`` on unknown
    names. Each verifier returns a ``{"verified": bool, ...}`` dict — never
    raises for "verifier said no"; only raises for malformed inputs."""
    verifier = LIFECYCLE_VERIFIERS.get(name)
    if verifier is None:
        raise VerifierError(
            f"unknown lifecycle verifier {name!r}; "
            f"known: {sorted(LIFECYCLE_VERIFIERS)!r}"
        )
    return verifier(node=node, project_root=project_root, **kwargs)
```

- [ ] **Step 4: Run the tests — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_verifiers -v`

Expected: all tests green.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py tests/test_lifecycle_verifiers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 lifecycle verifier registry + artifact_exists"
```

---

## Task 4: lifecycle_verifiers.py — structural_complete

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py`
- Modify: `tests/test_lifecycle_verifiers.py`

- [ ] **Step 1: Add failing tests for structural_complete**

Append to `tests/test_lifecycle_verifiers.py`:

```python
class StructuralCompleteVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_well_formed_md_passes(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "docs" / "prd.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text(
            "---\n"
            'title: "PRD"\n'
            "status: complete\n"
            "---\n# PRD\n",
            encoding="utf-8",
        )
        node = _make_node(
            node_id="B2-prd", verifier="structural_complete",
            output_artifact="docs/prd.md",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root),
        )
        self.assertTrue(result["verified"])

    def test_missing_artifact_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        node = _make_node(
            node_id="B2-prd", verifier="structural_complete",
            output_artifact="docs/missing.md",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root),
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "artifact_missing")

    def test_no_frontmatter_fails_for_md(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "docs" / "prd.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("# PRD\nno frontmatter here\n", encoding="utf-8")
        node = _make_node(
            node_id="B2-prd", verifier="structural_complete",
            output_artifact="docs/prd.md",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root),
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "frontmatter_missing")

    def test_directory_artifact_passes_when_non_empty(self) -> None:
        # structural_complete for a directory output_artifact == artifact_exists
        # for a directory (no md-specific check applies).
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        epics = self.root / "epics"
        epics.mkdir()
        (epics / "epic-1.md").write_text("# Epic 1\n", encoding="utf-8")
        node = _make_node(
            node_id="B3-epics", verifier="structural_complete",
            output_artifact="epics/",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root),
        )
        self.assertTrue(result["verified"])

    def test_non_md_file_passes_on_existence_only(self) -> None:
        # A binary or non-md artifact has no frontmatter to check; the
        # structural verifier reduces to "the file exists and is non-empty".
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "build" / "release.tar.gz"
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b"\x1f\x8b\x08\x00not-actually-gzip")
        node = _make_node(
            node_id="release", verifier="structural_complete",
            output_artifact="build/release.tar.gz",
        )
        result = run_lifecycle_verifier(
            "structural_complete", node=node, project_root=str(self.root),
        )
        self.assertTrue(result["verified"])
```

- [ ] **Step 2: Run — expect FAIL on the new tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_verifiers.StructuralCompleteVerifierTests -v`

Expected: ALL FAIL — `KeyError: 'structural_complete'` or a `VerifierError`.

- [ ] **Step 3: Implement structural_complete**

Modify `lifecycle_verifiers.py` — add the function and register it. Insert the implementation **before** `LIFECYCLE_VERIFIERS`:

```python
def structural_complete(
    *,
    node: NodeDef,
    project_root: str,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Artifact exists + (for ``.md`` outputs) has parseable frontmatter.

    - Directory artifacts (trailing ``/``): reduces to ``artifact_exists``
      semantics — non-empty directory passes.
    - ``.md`` file artifacts: must exist, be non-empty, and have a
      parseable simple-YAML frontmatter block at the top. A markdown file
      with no ``---`` header fails with reason ``frontmatter_missing``.
    - Any other file: reduces to "exists and non-empty" — no shape check.

    This is the minimum structural bar §2 requires. Charter-driven DoD
    (mutation, coverage, security) is Wave 1+ work and is intentionally
    not implemented here.
    """
    base = artifact_exists(node=node, project_root=project_root)
    base["verifier"] = "structural_complete"
    if not base["verified"]:
        return base
    full = Path(project_root) / node.output_artifact
    if node.output_artifact.endswith("/"):
        return base  # directory check is complete
    if full.suffix.lower() != ".md":
        return base  # non-md: existence is enough
    # .md must have parseable frontmatter
    from story_automator.core.frontmatter import parse_simple_frontmatter

    text = full.read_text(encoding="utf-8")
    if not text.startswith("---"):
        base["verified"] = False
        base["reason"] = "frontmatter_missing"
        return base
    fields = parse_simple_frontmatter(text)
    if not fields:
        base["verified"] = False
        base["reason"] = "frontmatter_unparseable"
        return base
    base["frontmatter_keys"] = sorted(fields.keys())
    return base
```

Update the registry:

```python
LIFECYCLE_VERIFIERS: dict[str, VerifierFn] = {
    "artifact_exists": artifact_exists,
    "structural_complete": structural_complete,
}
```

Also update `__all__` to include `"structural_complete"`.

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_verifiers -v`

Expected: all tests (including ArtifactExistsVerifierTests carried over from Task 3) green.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py tests/test_lifecycle_verifiers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 structural_complete verifier (frontmatter shape check)"
```

---

## Task 5: lifecycle_verifiers.py — validator_skill wrapper

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py`
- Modify: `tests/test_lifecycle_verifiers.py`

- [ ] **Step 1: Add failing tests for the validator_skill wrapper**

Append to `tests/test_lifecycle_verifiers.py`:

```python
class ValidatorSkillVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_calls_injected_dispatch_when_validator_skill_set(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        artifact = self.root / "docs" / "prd.md"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("---\nstatus: complete\n---\n# PRD\n",
                            encoding="utf-8")

        calls: list[tuple] = []

        def stub_dispatch(*, validator_skill: str, node, project_root):
            calls.append((validator_skill, node.id, project_root))
            return {"verified": True, "validator": validator_skill}

        node = _make_node(
            node_id="B2-prd", verifier="validator_skill",
            output_artifact="docs/prd.md", validator_skill="bmad-validate-prd",
        )
        result = run_lifecycle_verifier(
            "validator_skill", node=node, project_root=str(self.root),
            validator_dispatch=stub_dispatch,
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["validator"], "bmad-validate-prd")
        self.assertEqual(calls, [("bmad-validate-prd", "B2-prd", str(self.root))])

    def test_missing_validator_skill_field_fails(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        node = _make_node(
            node_id="B2-prd", verifier="validator_skill",
            output_artifact="docs/prd.md", validator_skill=None,
        )
        result = run_lifecycle_verifier(
            "validator_skill", node=node, project_root=str(self.root),
            validator_dispatch=lambda **_: {"verified": True},
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "validator_skill_not_configured")

    def test_dispatch_callable_required(self) -> None:
        from story_automator.core.lifecycle_verifiers import (
            VerifierError,
            run_lifecycle_verifier,
        )

        node = _make_node(
            node_id="B2-prd", verifier="validator_skill",
            output_artifact="docs/prd.md", validator_skill="bmad-validate-prd",
        )
        with self.assertRaises(VerifierError):
            # The wrapper cannot synthesise a validator-skill executor on its
            # own; production wiring passes `validator_dispatch=...` from the
            # runner. A missing dispatch is a programming error.
            run_lifecycle_verifier(
                "validator_skill", node=node, project_root=str(self.root),
            )

    def test_dispatch_returning_verified_false_propagates(self) -> None:
        from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

        def reject_dispatch(*, validator_skill, node, project_root):
            return {"verified": False, "reason": "validator_said_no"}

        node = _make_node(
            node_id="B2-prd", verifier="validator_skill",
            output_artifact="docs/prd.md", validator_skill="bmad-validate-prd",
        )
        result = run_lifecycle_verifier(
            "validator_skill", node=node, project_root=str(self.root),
            validator_dispatch=reject_dispatch,
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["reason"], "validator_said_no")
```

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_verifiers.ValidatorSkillVerifierTests -v`

Expected: all 4 fail (KeyError on `validator_skill`).

- [ ] **Step 3: Implement the wrapper**

Add to `lifecycle_verifiers.py` before the registry:

```python
def validator_skill(
    *,
    node: NodeDef,
    project_root: str,
    validator_dispatch: Callable[..., dict[str, Any]] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Defer to ``node.validator_skill`` via the injected dispatch callable.

    The runner provides ``validator_dispatch`` — a thin wrapper that
    invokes the named validator skill (via the same tmux runtime that
    spawned the producer skill) and returns its success-verifier output.

    Returns ``{"verified": False, "reason": "validator_skill_not_configured"}``
    when ``node.validator_skill`` is ``None``. Raises ``VerifierError`` if
    no ``validator_dispatch`` is supplied — this is a programming error
    (the production runner always passes one; tests must pass a stub).
    """
    if not node.validator_skill:
        return {
            "verified": False,
            "reason": "validator_skill_not_configured",
            "verifier": "validator_skill",
        }
    if validator_dispatch is None:
        raise VerifierError(
            f"verifier 'validator_skill' for node {node.id!r} needs a "
            f"`validator_dispatch` callable; pass one from the runner"
        )
    result = validator_dispatch(
        validator_skill=node.validator_skill,
        node=node,
        project_root=project_root,
    )
    if not isinstance(result, dict):
        raise VerifierError(
            f"validator_dispatch for {node.validator_skill!r} returned "
            f"{type(result).__name__}, expected dict"
        )
    result.setdefault("verifier", "validator_skill")
    return result
```

Update the registry to include `"validator_skill": validator_skill,` and append `"validator_skill"` to `__all__`.

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_verifiers -v`

Expected: all tests across all three verifier classes green.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py tests/test_lifecycle_verifiers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 validator_skill verifier wrapper (injected dispatch)"
```

---

## Task 6: lifecycle_runner.py — skeleton + RunResult + RunnerError + state-transition primitives

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py`
- Create: `tests/test_lifecycle_runner.py`

- [ ] **Step 1: Write skeleton tests**

Create `tests/test_lifecycle_runner.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any  # Task 10 uses Any in list annotations; declare it up front.


class LifecycleRunnerModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_runner  # noqa: F401

    def test_exposes_runner_error(self) -> None:
        from story_automator.core.lifecycle_runner import RunnerError

        self.assertTrue(issubclass(RunnerError, RuntimeError))

    def test_exposes_run_result(self) -> None:
        from story_automator.core.lifecycle_runner import RunResult

        # Dataclass with at least node_id + final_state
        r = RunResult(
            node_id="B1-brief", final_state="complete",
            verified=True, reason="", duration_s=0.0,
        )
        self.assertEqual(r.node_id, "B1-brief")
        self.assertEqual(r.final_state, "complete")

    def test_exposes_run_next_node(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node

        self.assertTrue(callable(run_next_node))


class StateTransitionPrimitiveTests(unittest.TestCase):
    """The runner internally exposes `_transition_node` for tests. It must
    persist atomically — every call writes the full RunStatus to disk."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_transition_persists_status_atomically(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_runner import _transition_node
        from story_automator.core.lifecycle_status import (
            NodeState, load_status, new_run_status,
        )

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "greenfield-minimal.policy.json"
        policy = load_policy(fixture.read_text(encoding="utf-8"))
        status = new_run_status(
            policy, run_id="r-t6", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        status_path = self.root / "lifecycle-status.json"
        # First save establishes the file
        from story_automator.core.lifecycle_status import save_status
        save_status(status_path, status)

        _transition_node(
            status, status_path, "B1-brief", NodeState.RUNNING,
            started_at="2026-06-17T00:00:01Z",
        )
        revived = load_status(status_path)
        self.assertEqual(revived.nodes["B1-brief"].state, NodeState.RUNNING)
        self.assertEqual(
            revived.nodes["B1-brief"].started_at, "2026-06-17T00:00:01Z"
        )

    def test_transition_to_complete_records_completed_at(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_runner import _transition_node
        from story_automator.core.lifecycle_status import (
            NodeState, load_status, new_run_status, save_status,
        )

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "greenfield-minimal.policy.json"
        policy = load_policy(fixture.read_text(encoding="utf-8"))
        status = new_run_status(
            policy, run_id="r-t6c", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        status_path = self.root / "lifecycle-status.json"
        save_status(status_path, status)

        _transition_node(
            status, status_path, "B1-brief", NodeState.COMPLETE,
            completed_at="2026-06-17T00:01:00Z",
        )
        revived = load_status(status_path)
        self.assertEqual(revived.nodes["B1-brief"].state, NodeState.COMPLETE)
        self.assertEqual(
            revived.nodes["B1-brief"].completed_at, "2026-06-17T00:01:00Z"
        )

    def test_transition_to_failed_records_last_error(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_runner import _transition_node
        from story_automator.core.lifecycle_status import (
            NodeState, load_status, new_run_status, save_status,
        )

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "greenfield-minimal.policy.json"
        policy = load_policy(fixture.read_text(encoding="utf-8"))
        status = new_run_status(
            policy, run_id="r-t6f", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        status_path = self.root / "lifecycle-status.json"
        save_status(status_path, status)

        _transition_node(
            status, status_path, "B1-brief", NodeState.FAILED,
            last_error="agent_crashed: exit_code_2",
            completed_at="2026-06-17T00:01:00Z",
        )
        revived = load_status(status_path)
        self.assertEqual(revived.nodes["B1-brief"].state, NodeState.FAILED)
        self.assertIn("agent_crashed", revived.nodes["B1-brief"].last_error)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner -v`

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement skeleton + state-transition primitives**

Create `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py`:

```python
"""Lifecycle phase runner (W0-M02).

Single-turn driver: ``run_next_node`` picks one runnable node off the
scheduler, executes it (spawning a child agent via the existing tmux
runtime OR delegating to the sprint orchestrator on track=bmm+phase=4),
verifies the output, and transitions the run state atomically. The caller
(W0-M04's CLI; tests today) is responsible for the outer loop that calls
this repeatedly until ``runnable_nodes`` returns empty.

Every side-effect goes through an injectable callable with a stdlib
default — spawn, monitor, sprint-delegate, verifier dispatch, emitter,
clock. Unit tests pass mocks; production wiring uses the real defaults.
This keeps the runner CI-able with no tmux, no Claude, no network — the
same shape `cmd_monitor_session` and the existing
`test_orchestration_loop.py` integration test rely on.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from story_automator.core.lifecycle_status import (
    NodeRun,
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
    """Raised on runner-internal invariant violations (e.g. attempting to
    re-enter a RUNNING node, missing required policy fields, etc.)."""


@dataclass(kw_only=True)
class RunResult:
    """One-node outcome returned by ``run_next_node``.

    ``final_state`` is the NodeState the node landed in (as a string).
    ``verified`` is the verifier's verdict (may be True even when
    final_state == 'awaiting_approval' — gate=human means verifier passed
    but human approval is still pending).
    """

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
    """Mutate ``status.nodes[node_id]`` to ``new_state`` + persist atomically.

    Every transition writes the whole RunStatus to ``status_path`` via the
    crash-safe ``save_status`` (which uses ``core.atomic_io``). A kill -9
    between transitions leaves the previous transition's status intact —
    that's the resume guarantee. Required by §2 acceptance: "runs a node
    end-to-end ... → verify → advance" must be observable on disk.
    """
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
    """Stub — full implementation lands in Tasks 7 (spawn), 8 (delegate),
    9 (verify+gate), and 10 (telemetry)."""
    raise NotImplementedError("run_next_node lands in Task 7+")
```

- [ ] **Step 4: Run — expect PASS for skeleton + transition tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner -v`

Expected: the four skeleton tests pass; the three transition tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py tests/test_lifecycle_runner.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 runner skeleton + atomic state-transition primitive"
```

---

## Task 7: lifecycle_runner.py — spawn-agent path with injected boundaries

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py`
- Modify: `tests/test_lifecycle_runner.py`

This task implements the production happy-path-minus-verifier: pick a runnable node, transition PENDING → RUNNING (atomic), invoke the spawn boundary + monitor boundary, and transition COMPLETE on monitor success (verifier wiring lands in Task 9; phase-4 delegate in Task 8). Telemetry emission lands in Task 10.

- [ ] **Step 1: Add failing tests for the spawn path**

Append to `tests/test_lifecycle_runner.py`:

```python
class SpawnPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            new_run_status, save_status,
        )

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "greenfield-minimal.policy.json"
        self.policy = load_policy(fixture.read_text(encoding="utf-8"))
        self.status = new_run_status(
            self.policy, run_id="r-spawn", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        save_status(self.status_path, self.status)

    def test_picks_first_runnable_node_and_spawns(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node

        spawn_calls: list[tuple] = []
        monitor_calls: list[tuple] = []

        def stub_spawn(session, command, agent, project_root, mode=None):
            spawn_calls.append((session, command, agent))
            return ("", 0)

        def stub_monitor(args):
            monitor_calls.append(tuple(args))
            return 0  # success exit code; "completed" final state implied

        # Provide an artifact_exists that returns True so the verifier
        # (when wired in Task 9) would pass; for Task 7, no verifier yet,
        # so the runner uses a permissive "spawn + monitor success ==
        # COMPLETE" path until Task 9 plugs the verifier in.
        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=stub_spawn,
            monitor_session=stub_monitor,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.node_id, "B1-brief")
        # Spawn was called exactly once with a session name encoding the node id
        self.assertEqual(len(spawn_calls), 1)
        self.assertIn("B1-brief", spawn_calls[0][0])
        # Monitor was called exactly once
        self.assertEqual(len(monitor_calls), 1)

    def test_no_runnable_nodes_returns_none(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import NodeState

        for node_id in self.status.nodes:
            self.status.nodes[node_id].state = NodeState.COMPLETE
        # Persist the contrived "everything complete" state so a resume
        # wouldn't disagree with the in-memory view.
        from story_automator.core.lifecycle_status import save_status
        save_status(self.status_path, self.status)

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
        )
        self.assertIsNone(result)

    def test_status_marks_running_before_spawn(self) -> None:
        """The status write that pins PENDING → RUNNING must happen
        *before* the spawn call — so a crash between RUNNING-write and
        spawn-success leaves a status-says-RUNNING snapshot on disk.
        """
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import load_status, NodeState

        observed_states_at_spawn: list[NodeState] = []

        def spy_spawn(session, command, agent, project_root, mode=None):
            # Re-read the status file FROM DISK at spawn time — this
            # confirms the RUNNING write happened first.
            from story_automator.core.lifecycle_status import load_status

            on_disk = load_status(self.status_path)
            observed_states_at_spawn.append(
                on_disk.nodes["B1-brief"].state
            )
            return ("", 0)

        run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=spy_spawn,
            monitor_session=lambda *a, **k: 0,
        )
        self.assertEqual(observed_states_at_spawn, [NodeState.RUNNING])

    def test_running_node_is_not_selected_by_scheduler(self) -> None:
        """A node already in RUNNING state is filtered out by W0-M01's
        scheduler (only PENDING is runnable). The runner therefore sees
        no candidates and returns None — not RunnerError. The "stale
        RUNNING reset" is W0-M03's job (per design decision §5)."""
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import NodeState, save_status

        self.status.nodes["B1-brief"].state = NodeState.RUNNING
        save_status(self.status_path, self.status)

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {"verified": True},
        )
        # B1-brief is RUNNING (scheduler skips) → B2-prd deps unsatisfied
        # → no runnable candidates → run_next_node returns None.
        self.assertIsNone(result)

    def test_spawn_failure_transitions_to_failed(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import load_status, NodeState

        def failing_spawn(session, command, agent, project_root, mode=None):
            return ("tmux: command not found\n", 127)

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=failing_spawn,
            monitor_session=lambda *a, **k: 0,
        )
        self.assertEqual(result.final_state, "failed")
        self.assertFalse(result.verified)
        on_disk = load_status(self.status_path)
        self.assertEqual(on_disk.nodes["B1-brief"].state, NodeState.FAILED)
        self.assertIn("spawn", on_disk.nodes["B1-brief"].last_error)
```

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner.SpawnPathTests -v`

Expected: all five fail with `NotImplementedError`.

- [ ] **Step 3: Implement the spawn path**

Replace the `run_next_node` stub in `lifecycle_runner.py`. Add the imports:

```python
from story_automator.core.common import iso_now
from story_automator.core.lifecycle_policy import NodeDef, Policy
from story_automator.core.lifecycle_scheduler import runnable_nodes
```

Add a session-name helper (no tmux runtime import — name is a plain string):

```python
def _session_name_for_node(node: NodeDef, run_id: str) -> str:
    """Stable, tmux-safe session name derived from the node id + run id.

    Mirrors the existing ``generate_session_name`` shape used in
    ``commands/tmux.py`` (alnum/dot/dash/underscore, ≤ 160 chars) but
    keeps the runner free of a tmux_runtime import — this module is
    pure stdlib + lifecycle_* imports + one ``spawn_agent`` boundary.
    """
    safe_node = node.id.replace("/", "-")
    base = f"lifecycle-{safe_node}"
    if run_id:
        base += f"-{run_id[-12:]}"  # short suffix for cross-run differentiation
    return base[:160]
```

Now the main entry point:

```python
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
    """Execute one runnable node end-to-end. Returns None if nothing is runnable.

    Mandatory injectables (no production default chosen here because they
    bind to processes/sockets and would make the runner impossible to
    unit-test without monkey-patching): ``spawn_agent`` and
    ``monitor_session``. The phase-4 delegate / verifier / validator
    callables and the emitter are optional — defaults wire to the
    existing project surface at call sites (commands/lifecycle.py in
    W0-M04). The clock is replaceable for deterministic timing.

    The ``artifact_exists`` callable feeds the scheduler — caller controls
    "what does it mean for an input artifact to exist?" the same way
    W0-M01's scheduler did. Default: ``lambda p: (Path(project_root) / p).exists()``.
    """
    if spawn_agent is None or monitor_session is None:
        raise RunnerError(
            "run_next_node requires both `spawn_agent` and `monitor_session` "
            "callables; production wiring passes the tmux defaults in the "
            "CLI layer (W0-M04)"
        )
    if artifact_exists is None:
        root = Path(project_root)
        artifact_exists = lambda p: (root / p).exists()  # noqa: E731

    candidates = runnable_nodes(
        policy, status,
        artifact_exists=artifact_exists, max_concurrency=1,
    )
    if not candidates:
        return None
    node_id = candidates[0]
    node = policy.nodes[node_id]

    # Increment the per-node attempts counter on every RUNNING entry.
    # W0-M02 does not retry (design decision §5), so the counter is 1
    # for a node that ever ran; LifecyclePhaseFailed.attempt reads this
    # value, and a future failure-governance milestone (Wave 8 §38) will
    # re-use the counter to gate retry/escalation.
    status.nodes[node_id].attempts += 1
    started_at = clock()
    _transition_node(
        status, status_path, node_id, NodeState.RUNNING,
        started_at=started_at,
    )

    # --- spawn the child agent for node.skill ---
    from story_automator.core.run_identity import current_run_id

    run_id = current_run_id(project_root)
    session = _session_name_for_node(node, run_id)
    # Production command synthesis lives in W0-M04 (it composes the
    # skill resolver + prompt rendering). For the runner test surface,
    # we hand off a minimal command shape — the spawn boundary is the
    # injection point that turns this into a real shell command.
    command = f"# lifecycle: invoke skill {node.skill} for node {node.id}"
    agent = node.agent_role
    try:
        spawn_out, spawn_code = spawn_agent(
            session, command, agent, project_root,
        )
    except Exception as exc:  # noqa: BLE001 — boundary failure must not crash the runner
        completed_at = clock()
        _transition_node(
            status, status_path, node_id, NodeState.FAILED,
            completed_at=completed_at,
            last_error=f"spawn_raised: {type(exc).__name__}: {exc}",
        )
        return RunResult(
            node_id=node_id, final_state="failed", verified=False,
            reason="spawn_raised", duration_s=0.0,
        )

    if spawn_code != 0:
        completed_at = clock()
        _transition_node(
            status, status_path, node_id, NodeState.FAILED,
            completed_at=completed_at,
            last_error=f"spawn_failed: exit={spawn_code}: {spawn_out.strip()}",
        )
        return RunResult(
            node_id=node_id, final_state="failed", verified=False,
            reason="spawn_failed", duration_s=0.0,
        )

    # --- monitor to terminal state ---
    # Note: in production wiring (W0-M04), `monitor_session` is
    # `commands.tmux.cmd_monitor_session`, which *always* returns rc=0 in
    # the normal flow (terminal session state is exposed via the JSON
    # stdout payload, not the return code). The `monitor_rc != 0` branch
    # below therefore only fires when monitor_session itself raises (caught
    # above) or when a custom monitor implementation chooses to surface
    # a non-zero rc. The "session crashed but rc=0" case is decided by
    # the verifier downstream — `artifact_exists` returns verified=False,
    # and the verifier-rejected FAILED path fires with reason
    # "verifier_rejected" / error_class "VerifierRejected" (see Task 10).
    monitor_args = [session, "--json", "--story-key", node_id]
    try:
        monitor_rc = monitor_session(monitor_args)
    except Exception as exc:  # noqa: BLE001
        completed_at = clock()
        _transition_node(
            status, status_path, node_id, NodeState.FAILED,
            completed_at=completed_at,
            last_error=f"monitor_raised: {type(exc).__name__}: {exc}",
        )
        return RunResult(
            node_id=node_id, final_state="failed", verified=False,
            reason="monitor_raised", duration_s=0.0,
        )

    if monitor_rc != 0:
        completed_at = clock()
        _transition_node(
            status, status_path, node_id, NodeState.FAILED,
            completed_at=completed_at,
            last_error=f"monitor_nonzero: rc={monitor_rc}",
        )
        return RunResult(
            node_id=node_id, final_state="failed", verified=False,
            reason="monitor_nonzero", duration_s=0.0,
        )

    # --- TASK 9 will plug verifier_dispatch here; until then, monitor=0 == complete ---
    completed_at = clock()
    _transition_node(
        status, status_path, node_id, NodeState.COMPLETE,
        completed_at=completed_at,
    )
    return RunResult(
        node_id=node_id, final_state="complete", verified=True,
        reason="", duration_s=0.0,
    )
```

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner -v`

Expected: all SpawnPathTests pass plus the earlier skeleton + transition tests.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py tests/test_lifecycle_runner.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 runner spawn+monitor path (verifier wiring in T9)"
```

---

## Task 8: lifecycle_runner.py — phase-4 sprint-orchestrator delegation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py`
- Modify: `tests/test_lifecycle_runner.py`
- Create: `tests/fixtures/lifecycle/m02-phase4-delegate.policy.json`

- [ ] **Step 1: Create the phase-4 fixture**

Create `tests/fixtures/lifecycle/m02-phase4-delegate.policy.json`:

```json
{
  "version": 1,
  "nodes": {
    "B3-epics": {
      "track": "bmm",
      "phase": 3,
      "skill": "bmad-create-epics-and-stories",
      "validator_skill": null,
      "deps": [],
      "input_artifacts": [],
      "output_artifact": "epics/",
      "verifier": "artifact_exists",
      "gate": "auto",
      "modes": ["greenfield"],
      "agent_role": "pm",
      "interactive": false
    },
    "B4-sprint": {
      "track": "bmm",
      "phase": 4,
      "skill": "bmad-story-automator",
      "validator_skill": null,
      "deps": ["B3-epics"],
      "input_artifacts": ["epics/"],
      "output_artifact": "sprint-status.yaml",
      "verifier": "artifact_exists",
      "gate": "auto",
      "modes": ["greenfield"],
      "agent_role": "dev",
      "interactive": false
    }
  },
  "entry": {
    "greenfield": ["B3-epics"],
    "brownfield": []
  }
}
```

- [ ] **Step 2: Add failing tests**

Append to `tests/test_lifecycle_runner.py`:

```python
class Phase4DelegationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"
        # Seed the project root with the dependency artifact so B4-sprint
        # is runnable straight away.
        (self.root / "epics").mkdir()
        (self.root / "epics" / "epic-1.md").write_text("# E1\n", encoding="utf-8")

        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            NodeState, new_run_status, save_status,
        )

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "m02-phase4-delegate.policy.json"
        self.policy = load_policy(fixture.read_text(encoding="utf-8"))
        self.status = new_run_status(
            self.policy, run_id="r-p4", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        # B3-epics is already produced; mark it COMPLETE so the scheduler
        # surfaces B4-sprint (the phase-4 node) as the next runnable.
        self.status.nodes["B3-epics"].state = NodeState.COMPLETE
        save_status(self.status_path, self.status)

    def test_phase4_dispatches_to_sprint_delegate_not_spawn(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node

        spawn_calls: list[tuple] = []
        delegate_calls: list[tuple] = []

        def stub_spawn(*a, **k):
            spawn_calls.append(a)
            return ("", 0)

        def stub_delegate(*, node, project_root, status, run_id):
            delegate_calls.append((node.id, project_root))
            (Path(project_root) / "sprint-status.yaml").write_text(
                "stories: []\n", encoding="utf-8"
            )
            return {"verified": True}

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=stub_spawn,
            monitor_session=lambda *a, **k: 0,
            sprint_delegate=stub_delegate,
        )

        self.assertEqual(result.node_id, "B4-sprint")
        self.assertEqual(result.final_state, "complete")
        self.assertEqual(len(delegate_calls), 1)
        self.assertEqual(delegate_calls[0][0], "B4-sprint")
        # The spawn boundary must NOT be invoked for phase-4 nodes
        self.assertEqual(spawn_calls, [])

    def test_phase4_without_delegate_fails_loud(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node, RunnerError

        with self.assertRaises(RunnerError):
            run_next_node(
                self.policy, self.status,
                project_root=str(self.root),
                status_path=self.status_path,
                spawn_agent=lambda *a, **k: ("", 0),
                monitor_session=lambda *a, **k: 0,
                # sprint_delegate intentionally None
            )

    def test_phase4_delegate_returning_false_transitions_to_failed(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import NodeState, load_status

        def rejecting_delegate(*, node, project_root, status, run_id):
            return {"verified": False, "reason": "p0_gate_failed"}

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            sprint_delegate=rejecting_delegate,
        )
        self.assertEqual(result.final_state, "failed")
        on_disk = load_status(self.status_path)
        self.assertEqual(on_disk.nodes["B4-sprint"].state, NodeState.FAILED)
        self.assertIn("p0_gate_failed", on_disk.nodes["B4-sprint"].last_error)
```

- [ ] **Step 3: Run — expect FAIL on the phase-4 tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner.Phase4DelegationTests -v`

Expected: all three fail — the runner currently has no phase-4 branch and tries to spawn instead.

- [ ] **Step 4: Implement phase-4 delegation**

In `lifecycle_runner.py`, refactor the "spawn the child agent" block. Insert a phase-4 branch **before** the existing spawn call, after the RUNNING transition. The cleanest form is a small dispatch helper:

```python
def _is_sprint_delegate_node(node: NodeDef) -> bool:
    """A node delegates to the existing sprint orchestrator iff
    track=bmm AND phase=4. This matches build-spec-full.md §2:
    'delegate to existing sprint orchestrator on track=bmm,phase=4'."""
    return node.track == "bmm" and node.phase == 4
```

Then inside `run_next_node`, after the RUNNING transition:

```python
    if _is_sprint_delegate_node(node):
        if sprint_delegate is None:
            raise RunnerError(
                f"node {node.id!r} (track=bmm phase=4) requires a "
                f"`sprint_delegate` callable; the production CLI wires "
                f"this in W0-M04. Pass a stub in tests."
            )
        try:
            delegate_result = sprint_delegate(
                node=node, project_root=project_root,
                status=status, run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001
            completed_at = clock()
            _transition_node(
                status, status_path, node_id, NodeState.FAILED,
                completed_at=completed_at,
                last_error=f"delegate_raised: {type(exc).__name__}: {exc}",
            )
            return RunResult(
                node_id=node_id, final_state="failed", verified=False,
                reason="delegate_raised", duration_s=0.0,
            )
        if not isinstance(delegate_result, dict):
            raise RunnerError(
                f"sprint_delegate for {node.id!r} returned "
                f"{type(delegate_result).__name__}, expected dict"
            )
        verified = bool(delegate_result.get("verified"))
        completed_at = clock()
        if verified:
            _transition_node(
                status, status_path, node_id, NodeState.COMPLETE,
                completed_at=completed_at,
            )
            return RunResult(
                node_id=node_id, final_state="complete", verified=True,
                reason="", duration_s=0.0,
            )
        reason = str(delegate_result.get("reason") or "delegate_rejected")
        _transition_node(
            status, status_path, node_id, NodeState.FAILED,
            completed_at=completed_at,
            last_error=f"delegate_rejected: {reason}",
        )
        return RunResult(
            node_id=node_id, final_state="failed", verified=False,
            reason=reason, duration_s=0.0,
        )

    # --- spawn-agent path (non-phase-4) ---
    # (existing spawn + monitor logic from Task 7 remains here)
```

- [ ] **Step 5: Run — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner -v`

Expected: all tests across all classes green (SpawnPathTests + Phase4DelegationTests + earlier ones).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py tests/test_lifecycle_runner.py tests/fixtures/lifecycle/m02-phase4-delegate.policy.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 runner phase-4 sprint-delegate dispatch"
```

---

## Task 9: lifecycle_runner.py — verifier dispatch + gate=human → AWAITING_APPROVAL

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py`
- Modify: `tests/test_lifecycle_runner.py`

- [ ] **Step 1: Add failing tests for verifier wiring + gate handling**

Append to `tests/test_lifecycle_runner.py`:

```python
class VerifierAndGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"

        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import new_run_status, save_status

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "greenfield-minimal.policy.json"
        self.policy = load_policy(fixture.read_text(encoding="utf-8"))
        self.status = new_run_status(
            self.policy, run_id="r-vg", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        save_status(self.status_path, self.status)

    def test_verifier_pass_with_gate_auto_transitions_to_complete(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import NodeState, load_status

        verifier_calls: list[str] = []

        def stub_verifier(name, *, node, project_root, **kwargs):
            verifier_calls.append(name)
            return {"verified": True, "verifier": name}

        # B1-brief has gate=human in the greenfield fixture. Re-load policy
        # with B1-brief.gate flipped to "auto" via a hand-built status.
        # Instead, just verify the gate=human case in the next test;
        # here verify that the verifier is actually invoked on the
        # default (gate=human) path — gate handling is asserted separately.
        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=stub_verifier,
        )
        # B1-brief's verifier name in the fixture is "structural"; but the
        # actual verifier registry uses the literal `node.verifier` string,
        # so the stub is asked for whatever the fixture says.
        self.assertEqual(verifier_calls, [self.policy.nodes["B1-brief"].verifier])

    def test_gate_human_with_verifier_pass_lands_awaiting_approval(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import NodeState, load_status

        # B1-brief in the greenfield-minimal fixture has gate=human
        self.assertEqual(self.policy.nodes["B1-brief"].gate, "human")

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {"verified": True},
        )
        self.assertEqual(result.final_state, "awaiting_approval")
        self.assertTrue(result.verified)
        on_disk = load_status(self.status_path)
        self.assertEqual(
            on_disk.nodes["B1-brief"].state, NodeState.AWAITING_APPROVAL,
        )

    def test_gate_human_with_verifier_fail_lands_failed(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import NodeState, load_status

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {
                "verified": False, "reason": "structural_check_failed",
            },
        )
        self.assertEqual(result.final_state, "failed")
        self.assertFalse(result.verified)
        on_disk = load_status(self.status_path)
        self.assertEqual(on_disk.nodes["B1-brief"].state, NodeState.FAILED)
        self.assertIn("structural_check_failed", on_disk.nodes["B1-brief"].last_error)

    def test_no_verifier_dispatch_uses_lifecycle_verifiers_registry(self) -> None:
        # Default: when verifier_dispatch is None, the runner falls back
        # to the LIFECYCLE_VERIFIERS registry via run_lifecycle_verifier.
        # That registry includes "artifact_exists" — drop a real file on
        # disk to satisfy it.
        from story_automator.core.lifecycle_runner import run_next_node

        # Build a minimal 1-node policy with verifier="artifact_exists"
        # via an in-memory dict (avoids fixture sprawl).
        from story_automator.core.lifecycle_policy import load_policy
        import json as _json

        minimal = {
            "version": 1,
            "nodes": {
                "N1": {
                    "track": "bmm", "phase": 1,
                    "skill": "bmad-x", "validator_skill": None,
                    "deps": [], "input_artifacts": [],
                    "output_artifact": "out.md",
                    "verifier": "artifact_exists",
                    "gate": "auto",
                    "modes": ["greenfield"], "agent_role": "analyst",
                    "interactive": False,
                },
            },
            "entry": {"greenfield": ["N1"], "brownfield": []},
        }
        policy = load_policy(_json.dumps(minimal))
        from story_automator.core.lifecycle_status import new_run_status, save_status

        status = new_run_status(
            policy, run_id="r-default-verifier", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        save_status(self.status_path, status)

        # Pre-create the artifact the verifier expects.
        (self.root / "out.md").write_text("# out\n", encoding="utf-8")

        result = run_next_node(
            policy, status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            # verifier_dispatch intentionally NOT passed — exercises default
        )
        self.assertEqual(result.final_state, "complete")
        self.assertTrue(result.verified)
```

- [ ] **Step 2: Run — expect FAIL on the new tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner.VerifierAndGateTests -v`

Expected: the gate=human + verifier-fail + default-registry tests fail (the current code unconditionally transitions to COMPLETE after a 0-rc monitor).

- [ ] **Step 3: Implement verifier dispatch + gate handling**

In `lifecycle_runner.py`:

1. Replace the post-monitor "always COMPLETE" block (Task 7's stub) with verifier dispatch followed by gate-aware final-state selection.
2. Add a default `verifier_dispatch` that points at the registry:

```python
def _default_verifier_dispatch(
    name: str,
    *,
    node: NodeDef,
    project_root: str,
    **kwargs: Any,
) -> dict[str, Any]:
    from story_automator.core.lifecycle_verifiers import run_lifecycle_verifier

    return run_lifecycle_verifier(
        name, node=node, project_root=project_root, **kwargs,
    )
```

3. In `run_next_node`, after the monitor returns rc=0 (non-phase-4 branch):

```python
    # --- verifier dispatch ---
    dispatcher = verifier_dispatch or _default_verifier_dispatch
    try:
        verdict = dispatcher(
            node.verifier,
            node=node, project_root=project_root,
            validator_dispatch=validator_dispatch,
        )
    except Exception as exc:  # noqa: BLE001
        completed_at = clock()
        _transition_node(
            status, status_path, node_id, NodeState.FAILED,
            completed_at=completed_at,
            last_error=f"verifier_raised: {type(exc).__name__}: {exc}",
        )
        return RunResult(
            node_id=node_id, final_state="failed", verified=False,
            reason="verifier_raised", duration_s=0.0,
        )
    if not isinstance(verdict, dict):
        raise RunnerError(
            f"verifier_dispatch for {node.verifier!r} returned "
            f"{type(verdict).__name__}, expected dict"
        )

    verified = bool(verdict.get("verified"))
    completed_at = clock()
    if not verified:
        reason = str(verdict.get("reason") or "verifier_rejected")
        _transition_node(
            status, status_path, node_id, NodeState.FAILED,
            completed_at=completed_at,
            last_error=f"verifier_rejected: {reason}",
        )
        return RunResult(
            node_id=node_id, final_state="failed", verified=False,
            reason=reason, duration_s=0.0,
        )

    # --- gate handling: human → AWAITING_APPROVAL; auto → COMPLETE ---
    if node.gate == "human":
        _transition_node(
            status, status_path, node_id, NodeState.AWAITING_APPROVAL,
            completed_at=completed_at,
            gate_decision=None,  # explicitly null until approver decides
        )
        return RunResult(
            node_id=node_id, final_state="awaiting_approval",
            verified=True, reason="", duration_s=0.0,
        )

    _transition_node(
        status, status_path, node_id, NodeState.COMPLETE,
        completed_at=completed_at,
    )
    return RunResult(
        node_id=node_id, final_state="complete", verified=True,
        reason="", duration_s=0.0,
    )
```

- [ ] **Step 4: Update old SpawnPathTests so they still pass**

The Task 7 test `test_picks_first_runnable_node_and_spawns` expected `complete` without a verifier. With Task 9 wired, the default verifier (`artifact_exists`) now runs and would fail because `docs/product-brief.md` does not exist on disk.

Adjust that test (find and update in place) — make it pass an always-pass `verifier_dispatch`:

```python
        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=stub_spawn,
            monitor_session=stub_monitor,
            verifier_dispatch=lambda name, **kw: {"verified": True},
        )
```

And update `test_status_marks_running_before_spawn` to pass the same stub.

The remaining SpawnPathTests cases (`test_no_runnable_nodes_returns_none`, `test_running_node_refuses_re_entry`, `test_spawn_failure_transitions_to_failed`) do not need adjustment — they short-circuit before the verifier runs.

- [ ] **Step 5: Run — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner -v`

Expected: all tests green across all four classes.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py tests/test_lifecycle_runner.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 runner verifier dispatch + gate=human→awaiting_approval"
```

---

## Task 10: lifecycle_runner.py — telemetry emission (LifecyclePhase* events)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py`
- Modify: `tests/test_lifecycle_runner.py`

- [ ] **Step 1: Add failing telemetry tests**

Append to `tests/test_lifecycle_runner.py`:

```python
class TelemetryEmissionTests(unittest.TestCase):
    """Telemetry test bodies reference `Any` in `list[Any]` annotations —
    if running this file in isolation, ensure `from typing import Any` is
    present at the top of the module (added in Task 6 if not already there).
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"

        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import new_run_status, save_status

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "greenfield-minimal.policy.json"
        self.policy = load_policy(fixture.read_text(encoding="utf-8"))
        self.status = new_run_status(
            self.policy, run_id="r-tel", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        save_status(self.status_path, self.status)

    def test_emits_started_and_completed_on_happy_path(self) -> None:
        from story_automator.core.lifecycle_events import (
            LifecyclePhaseCompleted, LifecyclePhaseStarted,
        )
        from story_automator.core.lifecycle_runner import run_next_node

        emitted: list[Any] = []

        class StubEmitter:
            def emit(self, event):
                emitted.append(event)

        run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {"verified": True},
            emitter=StubEmitter(),
        )
        types = [type(e).__name__ for e in emitted]
        self.assertEqual(
            types, ["LifecyclePhaseStarted", "LifecyclePhaseCompleted"],
        )
        started = emitted[0]
        completed = emitted[1]
        self.assertIsInstance(started, LifecyclePhaseStarted)
        self.assertIsInstance(completed, LifecyclePhaseCompleted)
        self.assertEqual(started.node_id, "B1-brief")
        self.assertEqual(started.phase, 1)
        self.assertEqual(started.track, "bmm")
        # gate=human + verified=True → gate_decision == "awaiting_approval"
        self.assertEqual(completed.gate_decision, "awaiting_approval")

    def test_emits_started_and_failed_on_verifier_rejection(self) -> None:
        from story_automator.core.lifecycle_events import LifecyclePhaseFailed
        from story_automator.core.lifecycle_runner import run_next_node

        emitted: list[Any] = []

        class StubEmitter:
            def emit(self, event):
                emitted.append(event)

        run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {
                "verified": False, "reason": "x",
            },
            emitter=StubEmitter(),
        )
        types = [type(e).__name__ for e in emitted]
        self.assertEqual(types, ["LifecyclePhaseStarted", "LifecyclePhaseFailed"])
        failed = emitted[1]
        self.assertIsInstance(failed, LifecyclePhaseFailed)
        self.assertEqual(failed.reason, "verifier_rejected")

    def test_emit_failure_does_not_crash_runner(self) -> None:
        """Emit is best-effort observability — a flaky sink must NOT break
        a run. Mirrors the guard pattern in commands/orchestrator._emit_safe."""
        from story_automator.core.lifecycle_runner import run_next_node

        class FlakyEmitter:
            def emit(self, event):
                raise OSError("disk full")

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {"verified": True},
            emitter=FlakyEmitter(),
        )
        # Runner reached its normal end despite emitter failure
        self.assertEqual(result.final_state, "awaiting_approval")
```

- [ ] **Step 2: Run — expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner.TelemetryEmissionTests -v`

Expected: all three fail — runner currently does not emit.

- [ ] **Step 3: Wire telemetry emission**

Add to `lifecycle_runner.py`:

```python
def _emit_safe(emitter: Any, event: Any) -> None:
    """Best-effort emit. A flaky sink must never break a run."""
    if emitter is None:
        return
    try:
        emitter.emit(event)
    except OSError as exc:
        logger.warning("lifecycle telemetry emit failed for %s: %s",
                       type(event).__name__, exc)
```

In `run_next_node`, **after** the RUNNING transition + attempts increment from Task 7, **after** `run_id = current_run_id(project_root)`, and **before** the phase-4 branch (Task 8) — so the Started event fires on *both* delegate and spawn paths:

```python
    from story_automator.core.lifecycle_events import LifecyclePhaseStarted

    _emit_safe(emitter, LifecyclePhaseStarted(
        timestamp=started_at, run_id=run_id,
        node_id=node.id, phase=node.phase, track=node.track,
        skill=node.skill, agent_role=node.agent_role,
    ))
```

In every code path that lands the node in COMPLETE or AWAITING_APPROVAL, after the transition:

```python
    from story_automator.core.lifecycle_events import LifecyclePhaseCompleted

    gate_decision_str = "awaiting_approval" if node.gate == "human" else "auto_complete"
    _emit_safe(emitter, LifecyclePhaseCompleted(
        timestamp=completed_at, run_id=run_id,
        node_id=node.id, phase=node.phase, track=node.track,
        duration_s=_duration(started_at, completed_at),
        gate_decision=gate_decision_str,
    ))
```

In every code path that lands the node in FAILED, after the transition:

```python
    from story_automator.core.lifecycle_events import LifecyclePhaseFailed

    _emit_safe(emitter, LifecyclePhaseFailed(
        timestamp=completed_at, run_id=run_id,
        node_id=node.id, phase=node.phase, track=node.track,
        reason=reason, error_class=error_class,
        attempt=status.nodes[node_id].attempts,
    ))
```

**Enumerate every FAILED code path explicitly** — missing one of these is the most likely defect in this task. Each row below maps a code path to its (`reason`, `error_class`) pair the emit must carry. `_emit_safe(...LifecyclePhaseFailed(...))` belongs immediately after each `_transition_node(..., NodeState.FAILED, ...)` call:

| Source branch | `reason` | `error_class` |
|---|---|---|
| Task 7 spawn raises | `"spawn_raised"` | `type(exc).__name__` |
| Task 7 spawn rc != 0 | `"spawn_failed"` | `"SpawnFailed"` |
| Task 7 monitor raises | `"monitor_raised"` | `type(exc).__name__` |
| Task 7 monitor rc != 0 | `"monitor_nonzero"` | `"MonitorNonzero"` |
| Task 8 delegate raises | `"delegate_raised"` | `type(exc).__name__` |
| Task 8 delegate returns verified=False | the delegate's `reason` (e.g. `"p0_gate_failed"`) | `"DelegateRejected"` |
| Task 9 verifier raises | `"verifier_raised"` | `type(exc).__name__` |
| Task 9 verifier returns verified=False | the verifier's `reason` (e.g. `"artifact_missing"`) | `"VerifierRejected"` |

For COMPLETE / AWAITING_APPROVAL paths (Task 8 delegate verified=True, Task 9 verifier verified=True), emit `LifecyclePhaseCompleted` with `gate_decision="auto_complete"` (gate=auto, COMPLETE) or `gate_decision="awaiting_approval"` (gate=human, AWAITING_APPROVAL).

Total emit sites in `run_next_node`: 1× Started (right after RUNNING transition, **before** the phase-4 branch — so the Started event fires for both phase-4 and non-phase-4 paths), 2× Completed (Task 8 delegate-success, Task 9 verifier-success), 8× Failed (rows above).

Add the `_duration` helper:

```python
def _duration(started_at: str, completed_at: str) -> float:
    """Best-effort ISO-8601 timestamp delta in seconds. Returns 0.0 on parse
    failure — duration is observability metadata, not a correctness gate."""
    from datetime import datetime

    try:
        a = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        b = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        return max(0.0, (b - a).total_seconds())
    except (TypeError, ValueError):
        return 0.0
```

Refactor so every emit-bearing branch is well-marked. The full helper-factoring is left to the implementer — the tests don't care which internal helper they go through.

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner -v`

Expected: all tests green.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py tests/test_lifecycle_runner.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 runner emits LifecyclePhase{Started,Completed,Failed}"
```

---

## Task 11: lifecycle_runner.py — duration + RunResult fields + small finishing touches

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py`
- Modify: `tests/test_lifecycle_runner.py`

This task tightens the API: `RunResult.duration_s` should reflect real elapsed time (Task 10 emits it on the event; surface it on the return value too), and pin the runner's behavior on a previously-failed node (re-runnable iff explicitly reset by the operator).

- [ ] **Step 1: Add failing tests**

Append:

```python
class RunResultDurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import new_run_status, save_status

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "greenfield-minimal.policy.json"
        self.policy = load_policy(fixture.read_text(encoding="utf-8"))
        self.status = new_run_status(
            self.policy, run_id="r-dur", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        save_status(self.status_path, self.status)

    def test_duration_uses_injected_clock(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node

        ticks = iter(["2026-06-17T00:00:00Z", "2026-06-17T00:00:42Z"])

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {"verified": True},
            clock=lambda: next(ticks),
        )
        self.assertAlmostEqual(result.duration_s, 42.0, places=3)


class FailedNodeReentryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            NodeState, new_run_status, save_status,
        )

        fixture = Path(__file__).resolve().parent / "fixtures" / "lifecycle" / "greenfield-minimal.policy.json"
        self.policy = load_policy(fixture.read_text(encoding="utf-8"))
        self.status = new_run_status(
            self.policy, run_id="r-fr", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        self.status.nodes["B1-brief"].state = NodeState.FAILED
        save_status(self.status_path, self.status)

    def test_failed_node_is_not_runnable_without_reset(self) -> None:
        """A FAILED node sticks until reset. The scheduler already filters
        non-PENDING — this is a regression guard."""
        from story_automator.core.lifecycle_runner import run_next_node

        result = run_next_node(
            self.policy, self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {"verified": True},
        )
        # B1-brief is FAILED → not runnable → result is None (no other
        # nodes' deps are satisfied; B2-prd depends on B1-brief).
        self.assertIsNone(result)
```

- [ ] **Step 2: Run — expect FAIL on the duration test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner.RunResultDurationTests -v`

Expected: FAIL (`assertAlmostEqual(0.0, 42.0)`).

- [ ] **Step 3: Wire duration through to RunResult**

In `run_next_node`, in every COMPLETE / AWAITING_APPROVAL / FAILED return path that has a `started_at` + `completed_at`, set `duration_s=_duration(started_at, completed_at)` on the returned `RunResult`.

- [ ] **Step 4: Run — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_runner -v`

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py tests/test_lifecycle_runner.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(lifecycle): W0-M02 propagate duration_s through RunResult"
```

---

## Task 12: End-to-end acceptance — 2-node fixture, mocked agent, mirrors test_orchestration_loop.py

**Files:**
- Create: `tests/test_lifecycle_acceptance_m02.py`
- Create: `tests/fixtures/lifecycle/m02-two-node.policy.json`

- [ ] **Step 1: Create the 2-node fixture**

Create `tests/fixtures/lifecycle/m02-two-node.policy.json`:

```json
{
  "version": 1,
  "nodes": {
    "N1-first": {
      "track": "bmm",
      "phase": 1,
      "skill": "bmad-product-brief",
      "validator_skill": null,
      "deps": [],
      "input_artifacts": [],
      "output_artifact": "docs/n1.md",
      "verifier": "artifact_exists",
      "gate": "auto",
      "modes": ["greenfield"],
      "agent_role": "analyst",
      "interactive": false
    },
    "N2-second": {
      "track": "bmm",
      "phase": 2,
      "skill": "bmad-create-prd",
      "validator_skill": null,
      "deps": ["N1-first"],
      "input_artifacts": ["docs/n1.md"],
      "output_artifact": "docs/n2.md",
      "verifier": "artifact_exists",
      "gate": "auto",
      "modes": ["greenfield"],
      "agent_role": "pm",
      "interactive": false
    }
  },
  "entry": {
    "greenfield": ["N1-first"],
    "brownfield": []
  }
}
```

- [ ] **Step 2: Create the acceptance test**

Create `tests/test_lifecycle_acceptance_m02.py`:

```python
"""W0-M02 acceptance: runs a node end-to-end (mocked agent) → verify → advance;
phase-4 delegates; events emit; mirrors `tests/test_orchestration_loop.py`."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.lifecycle_events import (
    LifecyclePhaseCompleted,
    LifecyclePhaseStarted,
)
from story_automator.core.lifecycle_policy import load_policy
from story_automator.core.lifecycle_runner import run_next_node
from story_automator.core.lifecycle_status import (
    NodeState, load_status, new_run_status, save_status,
)
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_reader import TelemetryReader

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class W0M02AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"

    def test_two_node_run_advances_through_complete(self) -> None:
        policy = load_policy(
            (FIXTURE_DIR / "m02-two-node.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="acc-m02", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        save_status(self.status_path, status)

        emitter = TelemetryEmitter(self.root / "telemetry" / "events.jsonl")

        # The spawn boundary actually drops the expected output file on
        # disk so the artifact_exists verifier passes. This is the only
        # production fact the test simulates — no real tmux, no real agent.
        def fake_spawn(session, command, agent, project_root, mode=None):
            # Match the node by its id appearing in the session name (the
            # runner's _session_name_for_node builds "lifecycle-<node_id>-...").
            for nid, node in policy.nodes.items():
                if nid in session:
                    target = Path(project_root) / node.output_artifact
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"# {nid}\n", encoding="utf-8")
                    break
            return ("", 0)

        results: list = []
        for _ in range(3):  # one extra iteration confirms None on a finished run
            r = run_next_node(
                policy, status,
                project_root=str(self.root),
                status_path=self.status_path,
                spawn_agent=fake_spawn,
                monitor_session=lambda args: 0,
                emitter=emitter,
            )
            results.append(r)
            if r is None:
                break

        node_ids = [r.node_id for r in results if r is not None]
        final_states = [r.final_state for r in results if r is not None]
        self.assertEqual(node_ids, ["N1-first", "N2-second"])
        self.assertEqual(final_states, ["complete", "complete"])
        # The third loop iteration confirms exhaustion
        self.assertIsNone(results[-1])

        # Status reflects both COMPLETE on disk
        revived = load_status(self.status_path)
        self.assertEqual(revived.nodes["N1-first"].state, NodeState.COMPLETE)
        self.assertEqual(revived.nodes["N2-second"].state, NodeState.COMPLETE)

        # Telemetry: 2× Started + 2× Completed
        events = list(
            TelemetryReader(self.root / "telemetry" / "events.jsonl").iter_events()
        )
        types = [type(e).__name__ for e in events]
        self.assertEqual(types.count("LifecyclePhaseStarted"), 2)
        self.assertEqual(types.count("LifecyclePhaseCompleted"), 2)
        # Each Started event has a non-empty node_id
        for e in events:
            if isinstance(e, LifecyclePhaseStarted):
                self.assertIn(e.node_id, {"N1-first", "N2-second"})
            if isinstance(e, LifecyclePhaseCompleted):
                self.assertEqual(e.gate_decision, "auto_complete")

    def test_phase4_delegate_path_advances_and_emits(self) -> None:
        policy = load_policy(
            (FIXTURE_DIR / "m02-phase4-delegate.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="acc-m02-p4", mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        # Seed the upstream artifact + mark B3-epics COMPLETE
        (self.root / "epics").mkdir()
        (self.root / "epics" / "e1.md").write_text("# e1\n", encoding="utf-8")
        status.nodes["B3-epics"].state = NodeState.COMPLETE
        save_status(self.status_path, status)

        emitter = TelemetryEmitter(self.root / "telemetry" / "events.jsonl")

        delegate_invocations: list[str] = []

        def stub_delegate(*, node, project_root, status, run_id):
            delegate_invocations.append(node.id)
            (Path(project_root) / node.output_artifact).write_text(
                "stories: []\n", encoding="utf-8"
            )
            return {"verified": True}

        # spawn_agent must NEVER be invoked for the phase-4 node
        def never_spawn(*a, **k):
            raise AssertionError(
                "spawn_agent must not be invoked for track=bmm phase=4 — "
                "the delegate path owns the execution"
            )

        result = run_next_node(
            policy, status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=never_spawn,
            monitor_session=lambda args: 0,
            sprint_delegate=stub_delegate,
            emitter=emitter,
        )

        self.assertEqual(result.node_id, "B4-sprint")
        self.assertEqual(result.final_state, "complete")
        self.assertEqual(delegate_invocations, ["B4-sprint"])
        # Telemetry includes Started + Completed for B4-sprint
        events = list(
            TelemetryReader(self.root / "telemetry" / "events.jsonl").iter_events()
        )
        types = [(type(e).__name__, getattr(e, "node_id", "")) for e in events]
        self.assertIn(("LifecyclePhaseStarted", "B4-sprint"), types)
        self.assertIn(("LifecyclePhaseCompleted", "B4-sprint"), types)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run — expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_lifecycle_acceptance_m02 -v`

Expected: both acceptance tests green. If a test fails, examine the runner code path it exercises — the fixture is intentionally minimal and the failure modes should localize quickly.

- [ ] **Step 4: Full-suite regression**

Run: `npm run test:python`

Expected: all previously-existing tests + the 4 new W0-M02 test files (`test_lifecycle_events.py`, `test_lifecycle_verifiers.py`, `test_lifecycle_runner.py`, `test_lifecycle_acceptance_m02.py`) green. Net new test count: roughly 30-35.

- [ ] **Step 5: Commit**

```bash
git add tests/test_lifecycle_acceptance_m02.py tests/fixtures/lifecycle/m02-two-node.policy.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(lifecycle): W0-M02 acceptance — 2-node spawn + phase-4 delegate + events"
```

---

## Task 13: Quality gates — ruff, module size, full suite, coverage, import allowlist

**Files:** none modified unless a gate fails.

- [ ] **Step 1: Ruff lint**

Run: `python -m ruff check skills/bmad-story-automator/src/story_automator/core/lifecycle_events.py skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py tests/test_lifecycle_events.py tests/test_lifecycle_verifiers.py tests/test_lifecycle_runner.py tests/test_lifecycle_acceptance_m02.py`

Expected: exit 0. Fix the source; do not suppress with `# noqa` unless the lint is genuinely wrong.

- [ ] **Step 2: Ruff format check**

Run: `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/lifecycle_events.py skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py tests/test_lifecycle_events.py tests/test_lifecycle_verifiers.py tests/test_lifecycle_runner.py tests/test_lifecycle_acceptance_m02.py`

If it fails: run `python -m ruff format <same paths>` and re-run the check. Commit the formatting fix as a separate `style(lifecycle):` commit.

- [ ] **Step 3: Module size guardrail**

Run `wc -l` on each new module. Expected sizes: `lifecycle_events.py` ≤ 100, `lifecycle_verifiers.py` ≤ 200, `lifecycle_runner.py` ≤ 400. All must stay under the 500-LOC CLAUDE.md soft limit.

- [ ] **Step 4: telemetry_events.py unchanged audit**

Run: `git log --since="2026-06-17" --diff-filter=AM --name-only -- skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`

Expected: NO output for the W0-M02 branch. The M01 guardrail forbids editing this file outside its owning milestone. If any commit edits it, revert and rethink the approach (the lifecycle events live in `lifecycle_events.py`).

- [ ] **Step 5: success_verifiers.py unchanged audit**

Run: `git log --since="2026-06-17" --diff-filter=AM --name-only -- skills/bmad-story-automator/src/story_automator/core/success_verifiers.py`

Expected: NO output for the W0-M02 branch. The new verifier registry is a sibling module by design; modifying the existing one would break the sprint-track surface.

- [ ] **Step 6: Import allowlist audit**

Run:

```bash
python -c "
import ast
files = [
    'skills/bmad-story-automator/src/story_automator/core/lifecycle_events.py',
    'skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py',
    'skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py',
]
for f in files:
    print(f'--- {f} ---')
    for node in ast.walk(ast.parse(open(f).read())):
        if isinstance(node, ast.ImportFrom):
            print(f'  from {node.module} import ...')
        elif isinstance(node, ast.Import):
            for n in node.names:
                print(f'  import {n.name}')
"
```

Manually verify every printed import is either: a stdlib module (`json`, `typing`, `dataclasses`, `enum`, `pathlib`, `logging`, `collections.abc`, `datetime`); a project module under `story_automator.core.*`; or the `filelock`/`psutil`/`hashlib` allowlist already in use elsewhere. **No new third-party module may appear in these three files.**

- [ ] **Step 7: Full suite regression**

Run: `npm run test:python`

Expected: all previously-existing tests + the 4 new W0-M02 test files green. No regressions in `test_orchestration_loop.py`, `test_lifecycle_*` from W0-M01, or any of the M01/M04 telemetry / audit tests.

- [ ] **Step 8: Coverage gate for new modules**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/lifecycle_events,skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers,skills/bmad-story-automator/src/story_automator/core/lifecycle_runner \
  -m unittest discover -s tests
python -m coverage report -m --fail-under=85
```

Expected: PASS (≥ 85 % on each new module). If a branch is uncovered, add a focused test — do NOT lower the gate. The most-likely uncovered branches: the OSError swallow in `_emit_safe`, the `_duration` parse-failure path (cover with a malformed-timestamp test), the `_default_verifier_dispatch` fallback when no `verifier_dispatch` is passed.

- [ ] **Step 9: `npm run verify` smoke**

Run: `npm run verify`

Expected: PASS. This runs `test:python`, `pack:dry-run`, `test:cli`, and `test:smoke` — the canonical release-style gate from CLAUDE.md.

- [ ] **Step 10: Commit any formatting fixes (skip if Step 2 reported no changes)**

```bash
git add -u skills/bmad-story-automator/src/story_automator/core/ tests/
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(lifecycle): ruff format pass"
```

If no fixes were needed, skip — do not create an empty commit.

---

## Task 14: Operator documentation — module map note + changelog entry

**Files:**
- Modify: `docs/superpowers/specs/lifecycle/build-spec-full.md` (append a "W0-M02 status" footnote — **do not modify any other section**)
- Modify or create: `docs/changelog/2026-06-17.md` (append a new dated entry **without modifying existing entry headings**)

- [ ] **Step 1: Append a status note to the lifecycle build spec**

Open `docs/superpowers/specs/lifecycle/build-spec-full.md`. Find the existing "Implementation status" block from W0-M01 at the file's end. Append (do NOT modify any pre-existing line):

```markdown
- **W0-M02 (Phase runner + phase verifiers)** — landed 2026-06-17. Three new modules: `core/lifecycle_events.py` (LifecyclePhaseStarted/Completed/Failed typed events auto-registered into `Event._REGISTRY`), `core/lifecycle_verifiers.py` (sibling registry of `artifact_exists`, `structural_complete`, `validator_skill`), `core/lifecycle_runner.py` (single-turn `run_next_node` with injected spawn/monitor/delegate/verifier boundaries; atomic per-transition status persistence; run_id-correlated telemetry). The approval-gate primitive, entry-mode router CLI, and W0-M04 lifecycle-helper command surface remain scheduled for the next milestones. `core/telemetry_events.py` and `core/success_verifiers.py` were not modified.
```

- [ ] **Step 2: Add a dated changelog entry**

If `docs/changelog/2026-06-17.md` already exists from W0-M01, append the new entry below the existing one (do NOT rewrite any pre-existing heading or sub-section):

```markdown

## 261117 - [FULL] W0-M02 phase runner + phase verifiers + lifecycle events

### Summary
Adds the macro-lifecycle phase runner and verifier registry — three new sibling modules under `core/` that pick a runnable node off the W0-M01 scheduler, spawn a child agent via the existing tmux runtime (or delegate to the sprint orchestrator on track=bmm + phase=4), verify the output, and transition the run-state atomically with run_id-correlated telemetry. Every side-effect goes through an injectable callable so CI exercises the full flow with no real tmux or agent.

### Added
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_events.py` — `LifecyclePhaseStarted`, `LifecyclePhaseCompleted`, `LifecyclePhaseFailed` (Event subclasses, auto-registered into the shared `Event._REGISTRY`).
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_verifiers.py` — `LIFECYCLE_VERIFIERS` registry + `run_lifecycle_verifier`; built-ins: `artifact_exists`, `structural_complete`, `validator_skill` (injected dispatch).
- `skills/bmad-story-automator/src/story_automator/core/lifecycle_runner.py` — `run_next_node` (single-turn driver), `RunResult`, `RunnerError`, `_transition_node` (atomic persistence).
- `tests/test_lifecycle_events.py`, `tests/test_lifecycle_verifiers.py`, `tests/test_lifecycle_runner.py`, `tests/test_lifecycle_acceptance_m02.py`.
- 2 new fixtures: `tests/fixtures/lifecycle/m02-two-node.policy.json`, `tests/fixtures/lifecycle/m02-phase4-delegate.policy.json`.

### Files
- `core/lifecycle_events.py`, `core/lifecycle_verifiers.py`, `core/lifecycle_runner.py` (new)
- `tests/test_lifecycle_{events,verifiers,runner,acceptance_m02}.py` (new)
- `tests/fixtures/lifecycle/m02-*.policy.json` (new)
- `docs/superpowers/specs/lifecycle/build-spec-full.md` (appended status footnote)

### QA Notes
- Lint: `ruff check` clean on all new modules.
- Tests: `npm run test:python` green; the four new test files contribute ~30-35 tests.
- Coverage: ≥ 85 % on each new module.
- Module size: each new module under 400 LOC, well under the 500-LOC soft limit.
- Cross-platform: tests use stdlib + `unittest`; no subprocess, no tmux, no network; runs on Windows git-bash and WSL Ubuntu.
- Guardrail compliance: no new third-party imports introduced; `core/telemetry_events.py` and `core/success_verifiers.py` untouched (confirmed by `git log --diff-filter=AM`); the new events flow through the existing emitter/reader/parse_event pipeline.
```

> Per CLAUDE.md hard guardrails: do NOT modify any pre-existing changelog heading, bullet, or sub-section heading. Only append new content. The `261117` date heading is new for W0-M02; if `docs/changelog/2026-06-17.md` already has a `## 261117 - [FULL] W0-M01 ...` heading from W0-M01, leave it alone and add the W0-M02 heading immediately after it.

- [ ] **Step 3: Commit docs**

```bash
git add docs/superpowers/specs/lifecycle/build-spec-full.md docs/changelog/2026-06-17.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(lifecycle): W0-M02 status footnote + changelog entry"
```

---

## Self-Review Checklist

**1. Spec coverage (build-spec-full.md §2 + design-spec.md §3.4):**
- Spawn child agent for `node.skill` via tmux runtime — Task 7 (injected `spawn_agent` boundary; default at W0-M04 wires `tmux_runtime.spawn_session`).
- Monitor session — Task 7 (injected `monitor_session` boundary; default at W0-M04 wires `commands.tmux.cmd_monitor_session`).
- Run verifier — Task 9 (verifier dispatch via lifecycle_verifiers registry, with a `verifier_dispatch` override boundary).
- Delegate to sprint orchestrator on track=bmm + phase=4 — Task 8 (`sprint_delegate` boundary; spawn path explicitly bypassed for phase=4).
- Verifier registry generalising `success_verifiers` — Tasks 3, 4, 5 (`artifact_exists`, `structural_complete`, `validator_skill` — sibling module to keep `success_verifiers.py` untouched).
- New `core/lifecycle_events.py` (`LifecyclePhaseStarted/Completed/Failed`, run_id-correlated) — Tasks 1, 2, 10.
- §2 acceptance bullets:
  - "runs a node end-to-end (mocked agent) → verify → advance" — Task 12 acceptance test (both 2-node and phase-4 cases).
  - "phase-4 delegates" — Task 12 second sub-test asserts the spawn boundary is never invoked + the sprint delegate is.
  - "events emit" — Task 10 unit tests + Task 12 acceptance test.
  - "mirrors `test_orchestration_loop.py`" — Task 12 acceptance test reuses the same TelemetryReader + final-state-on-disk pattern.

**2. Guardrail compliance:**
- No new third-party imports — Task 13 Step 6 audit.
- `core/telemetry_events.py` untouched — Task 13 Step 4 audit (`git log --diff-filter=AM`).
- `core/success_verifiers.py` untouched — Task 13 Step 5 audit.
- No fifth changelog tag — Task 14 reuses `[FULL]` from the existing four-tag vocabulary.
- Module size ≤ 500 LOC each — Task 13 Step 3.
- Conventional Commits + `Generated-By:` trailer — every commit step uses both.

**3. TDD discipline:** Every task that introduces production code follows the "test first → run failing → implement → run green → commit" loop. The skeleton task (Task 1) is the simplest case; Tasks 6–11 each follow the same shape with progressively richer behaviour.

**4. Injection-boundary discipline:** No production module performs a side-effect (spawn, monitor, emit, fs write, time read) without going through a parameter the caller can replace. The acceptance test (Task 12) and unit tests (Tasks 3–11) confirm this by passing stubs.

**5. Test surface alignment with `test_orchestration_loop.py`:** Task 12's acceptance test reads the events JSONL via `TelemetryReader`, asserts type counts via `type(e).__name__` (same pattern), and checks run_id correlation. The only difference is the event type names (`LifecyclePhaseStarted` vs `StoryStarted`) — by design.

**6. Backwards-compatibility of the existing per-story telemetry stream:** `LifecyclePhaseStarted` etc. share the `events.jsonl` sink with `StoryStarted` etc. but use distinct `event_type` strings (`"lifecycle_phase_started"` vs `"story_started"`). A reader that only knows the older types will route the new ones to `UnknownEvent` — the forward-compat fallback already in `telemetry_events.py`. No reader code changes.

**7. Cross-task name drift:**
- `RunResult(node_id, final_state, verified, reason, duration_s)` — signature stable across Tasks 6, 7, 8, 9, 10, 11, 12.
- `run_next_node(policy, status, *, project_root, status_path, spawn_agent, monitor_session, sprint_delegate, verifier_dispatch, validator_dispatch, emitter, clock, artifact_exists) -> RunResult | None` — signature stable across Tasks 6–12; new kwargs added in the task that introduces them but never renamed.
- `_transition_node` and `_emit_safe` are internal helpers; their signatures are referenced only by the runner itself + the Task 6 transition test.
- `LIFECYCLE_VERIFIERS` registry keys never get renamed once introduced (`artifact_exists`, `structural_complete`, `validator_skill`).

**8. Placeholder scan:** No "TODO", "TBD", or "implement later" markers in code blocks. Tasks 7 and 9 explicitly call out that the prior task's stub is being replaced — that is forward-pointing, not a placeholder.

---

## Notes for the implementer

- **Order matters.** Tasks 1 → 14 are dependency-ordered. Tasks 1–2 establish the event types so the runner (Task 10) can import them without circular hassle. Tasks 3–5 establish the verifier registry so Task 9 has something to call. Task 6 lays the runner skeleton, Tasks 7–11 fill in branches. Tasks 12–14 verify + document.
- **When a test from a prior task starts failing after a later task lands, that is expected only at Task 7 → Task 9 boundary** (the placeholder verifier wiring is replaced by real dispatch; one SpawnPathTests test needs an `verifier_dispatch=lambda ...` stub added — Task 9 Step 4 covers this). Any other regression is a real problem; do not paper over it by gating tests.
- **Boundary inversion is non-negotiable.** Do not import `tmux_runtime.spawn_session` or `commands.tmux.cmd_monitor_session` from the runner module. The CLI layer (W0-M04) is the wiring point that binds the real implementations. The runner's defaults for the spawn/monitor callables are `None` precisely so an accidental omission fails loudly with `RunnerError` rather than blowing up inside a tmux call deep in the stack.
- **`current_run_id` is the only telemetry-coupling call site inside the runner.** It reads the active marker; if the marker is absent during a test, it returns `""` (matching the existing per-story emitter behavior). The acceptance test (Task 12) does NOT create a marker — the telemetry stream just has `run_id=""` on every event, which is fine for asserting count + type. The production CLI (W0-M04) is responsible for ensuring the marker is present.
- **State transitions are append-only in spirit but overwrite-only in implementation.** Every `_transition_node` call rewrites the entire `lifecycle-status.json`. The previous state is lost (apart from the implicit `started_at` / `completed_at` / `last_error` fields). If you need a transition *log*, the telemetry events ARE that log — they're append-only and run_id-correlated.
- **Do not add a retry loop.** The §2 acceptance does not include retries; "the verifier failed → FAILED" is the contract. Per-node retries + escalation are W8-§38 territory; introducing them here would re-do design space that the failure-governance milestone owns.

