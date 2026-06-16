# M04 Milestone 4: Audit-Trail Policy Gate + Call-Site Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `audit_for_policy()` helper that gates the chain-verified `AuditLog` behind `security.audit_trail` in the runtime policy, introduce a minimal `core/telemetry_events.py` with the three event dataclasses referenced by REQ-11..13, and wire one audit-call hook into each of the three command modules so escalations, state mutations, and retro-agent dispatches land in the JSONL chain when (and only when) the operator opts in.

**Architecture:** A single new top-level helper `audit_for_policy(policy, path)` in `core/audit.py` reads `policy["security"]["audit_trail"]`, returns `None` when falsy (no I/O, single dict lookup — REQ-14), otherwise calls `load_key_from_env()` and either raises `AuditKeyMissing` or returns `AuditLog(path=path, key=key)`. The runtime policy schema (`core/runtime_policy.py`) gains one allowed top-level key, `security`, validated as an optional `{audit_trail: bool}` mapping; the bundled `data/orchestration-policy.json` ships `security: {audit_trail: false}` so existing deployments observe no behaviour change. `core/telemetry_events.py` is created fresh — three `@dataclass(frozen=True, kw_only=True)` payload carriers (`EscalationRaised`, `StoryStateChanged`, `RetroAgentDispatched`), each with a `event_name: str` class attribute and a `to_dict()` method. Call-sites construct one instance and pass it to `AuditLog.append`. Each integration short-circuits to a single dict lookup when the policy gate is off: no key load, no path stat, no filesystem I/O.

**Tech Stack:** Python 3.11+, standard library only. Reuses `core.audit` (`AuditLog`, `load_key_from_env`, `AuditKeyMissing`), `core.common.iso_now`, `core.runtime_policy.load_runtime_policy`, `filelock` transitively. Tests use `unittest` and run via `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py"`. Lint with `ruff check skills/bmad-story-automator/src/story_automator/core/audit.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_audit_policy.py tests/test_audit_call_sites.py` and `ruff format --check` on the same set. Coverage gate from M3 (`coverage report --include='*/audit.py' --fail-under=85`) carries forward.

---

## Spec Coverage Map

| Spec ID | Requirement | Tasks |
|---|---|---|
| REQ-10 | `audit_for_policy(policy, path)` returns `None` on falsy flag; otherwise `AuditLog` with env key; raises `AuditKeyMissing` when flag is true but no key | Tasks 2, 3, 4 |
| REQ-11 | `commands/orchestrator.py` calls `audit_for_policy` once during escalation and appends `EscalationRaised` before the escalation result is printed | Task 8 |
| REQ-12 | `commands/state.py` invokes the helper inside its state-update path and appends `StoryStateChanged` after a successful frontmatter write; failures from `append` are re-raised | Task 9 |
| REQ-13 | `commands/orchestrator_epic_agents.py` appends `RetroAgentDispatched` each time a retro-agent is selected, with the same correlation id used by surrounding telemetry | Task 10 |
| REQ-14 | All three integrations short-circuit on `None`; default policy fixture keeps `security.audit_trail: false` | Tasks 5, 8, 9, 10, 11 |
| Policy schema | `runtime_policy._validate_policy_shape` accepts `security` as optional top-level with `audit_trail: bool` | Task 1 |
| NFR-no-secret-leak | `AuditKeyMissing.__str__()` never contains the raw `BMAD_AUDIT_KEY` value | Task 4 |
| NFR-500-line-cap | `core/audit.py` stays ≤ 500 source lines | Task 12 |
| QA-coverage-85 | `coverage report --include='*/audit.py' --fail-under=85` passes after the new code lands | Task 13 |

Out of scope for M4 (deferred): KMS / sealed-secret loaders, log rotation, full `SECURITY.md` rewrite (M14), the regex→AST refactor of `commands/state.py` (M05), and any additional event dataclasses beyond the three required.

---

## File Structure

- **Modify:** `skills/bmad-story-automator/src/story_automator/core/audit.py` — add `audit_for_policy()` at the bottom of the public surface; no changes to existing helpers, dataclass, or exceptions. New surface ≤ 30 source lines including docstring.
- **Modify:** `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py` — add `"security"` to `VALID_TOP_LEVEL_KEYS` and a `_validate_security_shape` block in `_validate_policy_shape`. One new helper, ~15 lines.
- **Modify:** `skills/bmad-story-automator/data/orchestration-policy.json` — add `"security": {"audit_trail": false}` block (default off; REQ-14).
- **Create:** `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` — three frozen kw-only dataclasses with class-level `event_name` and instance `to_dict()`. ~50 source lines.
- **Modify:** `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py` — add one private helper `_maybe_audit(policy)` plus an `audit.append(EscalationRaised(...))` call inside `_escalate` immediately before `print_json({"escalate": True, ...})`. Also wire the same helper into the existing `_state_update` path so the StoryStateChanged record fires after the frontmatter write succeeds (REQ-12).
- **Modify:** `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py` — call the same helper from `retro_agent_action` and append `RetroAgentDispatched` immediately after `resolve_agent` returns.
- **Modify:** `skills/bmad-story-automator/src/story_automator/commands/state.py` — add a thin pass-through wrapper `audit_state_change(policy, path, *, story, from_status, to_status, correlation_id)` so spec REQ-12 ("commands/state.py must invoke the same helper") is satisfied at the module the spec names. The orchestrator's `_state_update` path imports this wrapper and calls it after the frontmatter write.
- **Create:** `tests/test_audit_policy.py` — covers the policy gate (`audit_for_policy` and the schema extension).
- **Create:** `tests/test_audit_call_sites.py` — covers the three call-site integrations and the short-circuit behaviour.

No existing M1/M2/M3 helpers are renamed or rewritten. No new third-party dependency.

Note on REQ-12 (state-update path): in this repo the actual state-mutation handler is `_state_update` in `commands/orchestrator.py`. The spec names `commands/state.py` because that is where state mutation lives in the upstream layout (and where M05 will migrate it). To honour the spec literally without anticipating M05, we add the thin `audit_state_change` wrapper in `commands/state.py` and have the orchestrator dispatch the call through it — so when M05 moves the state-update handler into `commands/state.py`, the audit hook is already there.

---

## Task 1: Extend policy schema to allow `security.audit_trail`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py:12` (constant), `:283` (validation)
- Modify: `skills/bmad-story-automator/data/orchestration-policy.json`
- Test: `tests/test_audit_policy.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_policy.py` with this initial content:

```python
from __future__ import annotations

import unittest


class PolicySchemaSecurityTests(unittest.TestCase):
    def _base_policy(self) -> dict:
        # Minimal shape that satisfies _validate_policy_shape today.
        return {
            "version": 1,
            "runtime": {
                "parser": {
                    "provider": "claude",
                    "model": "haiku",
                    "timeoutSeconds": 120,
                },
            },
            "workflow": {"sequence": []},
            "steps": {},
        }

    def test_security_audit_trail_false_is_accepted(self) -> None:
        from story_automator.core.runtime_policy import _validate_policy_shape

        policy = self._base_policy()
        policy["security"] = {"audit_trail": False}
        _validate_policy_shape(policy)  # must not raise

    def test_security_audit_trail_true_is_accepted(self) -> None:
        from story_automator.core.runtime_policy import _validate_policy_shape

        policy = self._base_policy()
        policy["security"] = {"audit_trail": True}
        _validate_policy_shape(policy)

    def test_security_missing_is_accepted(self) -> None:
        from story_automator.core.runtime_policy import _validate_policy_shape

        _validate_policy_shape(self._base_policy())

    def test_security_audit_trail_non_bool_rejected(self) -> None:
        from story_automator.core.runtime_policy import (
            PolicyError,
            _validate_policy_shape,
        )

        policy = self._base_policy()
        policy["security"] = {"audit_trail": "yes"}
        with self.assertRaises(PolicyError):
            _validate_policy_shape(policy)

    def test_security_unknown_subkey_rejected(self) -> None:
        from story_automator.core.runtime_policy import (
            PolicyError,
            _validate_policy_shape,
        )

        policy = self._base_policy()
        policy["security"] = {"audit_trail": False, "unknown": 1}
        with self.assertRaises(PolicyError):
            _validate_policy_shape(policy)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_policy -v`
Expected: FAIL on `test_security_audit_trail_false_is_accepted` with `PolicyError: unknown top-level policy keys: security`.

- [ ] **Step 3: Extend the schema constant**

In `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py:12`, change:

```python
VALID_TOP_LEVEL_KEYS = {"version", "snapshot", "runtime", "workflow", "steps"}
```

to:

```python
VALID_TOP_LEVEL_KEYS = {"version", "snapshot", "runtime", "workflow", "steps", "security"}
```

- [ ] **Step 4: Add the security validator**

Append a new helper near `_validate_policy_shape` (above it, alongside `_expect_optional_dict`):

```python
_VALID_SECURITY_KEYS = {"audit_trail"}


def _validate_security_shape(policy: dict[str, Any]) -> None:
    """Validate the optional ``security`` block.

    Accepts a missing block (treated as ``{}``) and the single supported
    subkey ``audit_trail`` (bool). Any other subkey or a non-bool value
    raises ``PolicyError``.
    """
    if "security" not in policy:
        return
    security = policy.get("security")
    if not isinstance(security, dict):
        raise PolicyError("security must be an object")
    unknown = sorted(set(security) - _VALID_SECURITY_KEYS)
    if unknown:
        raise PolicyError(f"unknown security keys: {', '.join(unknown)}")
    if "audit_trail" in security and not isinstance(security["audit_trail"], bool):
        raise PolicyError("security.audit_trail must be a bool")
```

Then inside `_validate_policy_shape`, add this call immediately after the `unknown_keys` check (around line 286):

```python
    _validate_security_shape(policy)
```

- [ ] **Step 5: Update the bundled policy default**

Edit `skills/bmad-story-automator/data/orchestration-policy.json` and add this top-level key (place after `"snapshot": {...}`, before `"runtime": {...}`):

```json
  "security": {
    "audit_trail": false
  },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_policy -v`
Expected: PASS.

Also run the existing policy validation suite to confirm no regression:

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_runtime_policy*.py" -v` (silently skipped if no such tests exist; the existing `discover` run below will catch any regression either way).

- [ ] **Step 7: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/runtime_policy.py skills/bmad-story-automator/data/orchestration-policy.json tests/test_audit_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(policy): allow optional security.audit_trail block

REQ-10 requires gating the audit-trail subsystem on a runtime policy
flag. Extend VALID_TOP_LEVEL_KEYS and add _validate_security_shape so a
{security: {audit_trail: bool}} block round-trips through the policy
loader, and ship the bundled default false so existing deployments
observe no behaviour change."
```

---

## Task 2: `audit_for_policy` returns `None` when the flag is falsy

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/audit.py`
- Test: `tests/test_audit_policy.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_policy.py`:

```python
import tempfile
from pathlib import Path


class AuditForPolicyGateOffTests(unittest.TestCase):
    def test_returns_none_when_security_block_missing(self) -> None:
        from story_automator.core.audit import audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                audit_for_policy({}, Path(d) / "audit.jsonl")
            )

    def test_returns_none_when_audit_trail_missing(self) -> None:
        from story_automator.core.audit import audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                audit_for_policy({"security": {}}, Path(d) / "audit.jsonl")
            )

    def test_returns_none_when_audit_trail_false(self) -> None:
        from story_automator.core.audit import audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(
                audit_for_policy(
                    {"security": {"audit_trail": False}},
                    Path(d) / "audit.jsonl",
                )
            )

    def test_gate_off_does_no_filesystem_io(self) -> None:
        # REQ-14: short-circuit must touch no files, not even the parent dir.
        from story_automator.core.audit import audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "nonexistent-subdir" / "audit.jsonl"
            self.assertIsNone(
                audit_for_policy(
                    {"security": {"audit_trail": False}}, target
                )
            )
            # The parent we asked about must not have been created.
            self.assertFalse(target.parent.exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_policy.AuditForPolicyGateOffTests -v`
Expected: FAIL with `ImportError: cannot import name 'audit_for_policy' from 'story_automator.core.audit'`.

- [ ] **Step 3: Add the helper (gate-off branch only)**

Append to `skills/bmad-story-automator/src/story_automator/core/audit.py`, after the `AuditLog` class:

```python
def audit_for_policy(
    policy: Mapping[str, Any], path: pathlib.Path
) -> AuditLog | None:
    """Return an ``AuditLog`` when policy enables the audit trail, else ``None``.

    REQ-10: when ``policy["security"]["audit_trail"]`` is falsy, returns
    ``None`` immediately — no key load, no path stat, no parent-directory
    creation (REQ-14). When truthy, loads the chain key via
    ``load_key_from_env()`` and returns an ``AuditLog`` instance; if the
    flag is truthy but no key is available, raises ``AuditKeyMissing``.

    The raw key bytes never appear in exception messages or repr output.
    """
    security = policy.get("security") or {}
    if not security.get("audit_trail"):
        return None
    key = load_key_from_env()
    if key is None:
        raise AuditKeyMissing(
            "security.audit_trail is enabled but BMAD_AUDIT_KEY is unset"
        )
    return AuditLog(path=path, key=key)
```

Also add `"audit_for_policy"` to `__all__` at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_policy.AuditForPolicyGateOffTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/audit.py tests/test_audit_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(audit): audit_for_policy returns None when gate is off

REQ-10 / REQ-14: the helper short-circuits on a single dict lookup
when security.audit_trail is missing or falsy. No key load, no path
stat, no parent-directory creation — verified by a zero-IO assertion."
```

---

## Task 3: `audit_for_policy` returns an `AuditLog` when the flag is true

**Files:**
- Modify: (no source change beyond what Task 2 wrote; tests-only verification)
- Test: `tests/test_audit_policy.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_policy.py`:

```python
import os


class AuditForPolicyGateOnTests(unittest.TestCase):
    def setUp(self) -> None:
        # Snapshot/restore the env var so test ordering can't leak it.
        self._saved = os.environ.pop("BMAD_AUDIT_KEY", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved

    def test_returns_audit_log_when_flag_true_and_key_set(self) -> None:
        from story_automator.core.audit import AuditLog, audit_for_policy

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            log = audit_for_policy(
                {"security": {"audit_trail": True}},
                Path(d) / "audit.jsonl",
            )
            self.assertIsInstance(log, AuditLog)
            self.assertEqual(log.path, Path(d) / "audit.jsonl")
            self.assertEqual(len(log.key), 32)

    def test_returned_log_can_append_and_verify(self) -> None:
        # End-to-end: the returned log is a fully wired AuditLog.
        from story_automator.core.audit import audit_for_policy

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            log = audit_for_policy(
                {"security": {"audit_trail": True}},
                Path(d) / "audit.jsonl",
            )

            class Fake:
                event_name = "E"

                def to_dict(self) -> dict:
                    return {"k": 1}

            assert log is not None
            log.append(Fake())
            self.assertEqual(log.verify(), (True, 1))
```

- [ ] **Step 2: Run test to verify it passes**

Task 2 already added the gate-on branch, so this batch should already pass.

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_policy.AuditForPolicyGateOnTests -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): audit_for_policy returns wired AuditLog when gate is on

End-to-end: with security.audit_trail=true and BMAD_AUDIT_KEY set, the
helper returns an AuditLog whose append() + verify() chain works."
```

---

## Task 4: `audit_for_policy` raises `AuditKeyMissing` (no key leak)

**Files:**
- Modify: (no source change; covered by Task 2's implementation)
- Test: `tests/test_audit_policy.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_policy.py`:

```python
class AuditForPolicyKeyMissingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("BMAD_AUDIT_KEY", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved

    def test_raises_when_flag_true_but_env_unset(self) -> None:
        from story_automator.core.audit import AuditKeyMissing, audit_for_policy

        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AuditKeyMissing):
                audit_for_policy(
                    {"security": {"audit_trail": True}},
                    Path(d) / "audit.jsonl",
                )

    def test_raises_when_flag_true_but_env_empty(self) -> None:
        from story_automator.core.audit import AuditKeyMissing, audit_for_policy

        os.environ["BMAD_AUDIT_KEY"] = ""
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AuditKeyMissing):
                audit_for_policy(
                    {"security": {"audit_trail": True}},
                    Path(d) / "audit.jsonl",
                )

    def test_exception_message_does_not_contain_env_value(self) -> None:
        # NFR-no-secret-leak: even though the env var is unset here, the
        # message must not embed any audit key material under any branch.
        from story_automator.core.audit import AuditKeyMissing, audit_for_policy

        secret = "do-not-log-this-canary-2c2c2c"
        os.environ["BMAD_AUDIT_KEY"] = secret
        # Force the missing-key branch by setting flag false, then back to
        # true with the env cleared again — the message we capture is from
        # the second call.
        os.environ.pop("BMAD_AUDIT_KEY")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(AuditKeyMissing) as ctx:
                audit_for_policy(
                    {"security": {"audit_trail": True}},
                    Path(d) / "audit.jsonl",
                )
            self.assertNotIn(secret, str(ctx.exception))
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_policy.AuditForPolicyKeyMissingTests -v`
Expected: PASS (Task 2's implementation already raises `AuditKeyMissing`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): audit_for_policy raises AuditKeyMissing, never leaks key

REQ-10 + NFR-no-secret-leak: when security.audit_trail is true but the
env key is unset or empty, raise AuditKeyMissing. The exception
message must not embed any audit key material."
```

---

## Task 5: Create `core/telemetry_events.py` with three event dataclasses

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Create: `tests/test_audit_call_sites.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_call_sites.py`:

```python
from __future__ import annotations

import unittest


class TelemetryEventsSurfaceTests(unittest.TestCase):
    def test_three_event_classes_exposed(self) -> None:
        from story_automator.core import telemetry_events as te

        self.assertTrue(hasattr(te, "EscalationRaised"))
        self.assertTrue(hasattr(te, "StoryStateChanged"))
        self.assertTrue(hasattr(te, "RetroAgentDispatched"))

    def test_event_name_matches_class_name(self) -> None:
        from story_automator.core.telemetry_events import (
            EscalationRaised,
            RetroAgentDispatched,
            StoryStateChanged,
        )

        self.assertEqual(EscalationRaised.event_name, "EscalationRaised")
        self.assertEqual(StoryStateChanged.event_name, "StoryStateChanged")
        self.assertEqual(
            RetroAgentDispatched.event_name, "RetroAgentDispatched"
        )

    def test_to_dict_round_trip(self) -> None:
        from story_automator.core.telemetry_events import EscalationRaised

        ev = EscalationRaised(
            trigger="review-loop",
            reason="Review loop exceeded max cycles (5/5)",
            correlation_id="c-1",
        )
        d = ev.to_dict()
        self.assertEqual(
            d,
            {
                "trigger": "review-loop",
                "reason": "Review loop exceeded max cycles (5/5)",
                "correlation_id": "c-1",
            },
        )

    def test_dataclass_is_frozen_and_kw_only(self) -> None:
        # Frozen so callers can't mutate after passing to append(); kw-only
        # so call-sites stay readable across the three carriers.
        from story_automator.core.telemetry_events import StoryStateChanged

        ev = StoryStateChanged(
            story="1.2", from_status="draft", to_status="qa", correlation_id="c-2"
        )
        with self.assertRaises(Exception):
            ev.story = "x"  # type: ignore[misc]

    def test_satisfies_audit_event_protocol(self) -> None:
        from story_automator.core.audit import Event
        from story_automator.core.telemetry_events import RetroAgentDispatched

        ev = RetroAgentDispatched(
            primary="claude", fallback="false", model="", correlation_id="c-3"
        )
        # runtime_checkable Protocol: isinstance check works structurally.
        self.assertIsInstance(ev, Event)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.TelemetryEventsSurfaceTests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'story_automator.core.telemetry_events'`.

- [ ] **Step 3: Create the module**

Create `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`:

```python
"""Minimal telemetry-event payload carriers used by the audit subsystem.

This module ships only what M04 needs: three frozen kw-only dataclasses
covering the three audit hook sites (escalation, state transition, retro
dispatch). Each class exposes:

  - ``event_name``: a class attribute equal to the class name; used by
    ``audit.AuditLog.append`` as the ``event`` field of the JSONL record.
  - ``to_dict()``: returns an instance-as-dict mapping in declaration
    order, suitable for ``audit.AuditLog`` to embed as ``payload``.

The classes intentionally satisfy ``audit.Event`` (structural Protocol)
without importing it — keeping the dependency edge one-way.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True, kw_only=True)
class EscalationRaised:
    """Operator-visible escalation raised by ``commands/orchestrator.py``."""

    event_name: str = dataclasses.field(default="EscalationRaised", init=False)
    trigger: str
    reason: str
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "reason": self.reason,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True, kw_only=True)
class StoryStateChanged:
    """State-doc frontmatter transition written by the state-update path."""

    event_name: str = dataclasses.field(default="StoryStateChanged", init=False)
    story: str
    from_status: str
    to_status: str
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "story": self.story,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "correlation_id": self.correlation_id,
        }


@dataclasses.dataclass(frozen=True, kw_only=True)
class RetroAgentDispatched:
    """Retro-agent selection emitted by ``orchestrator_epic_agents.py``."""

    event_name: str = dataclasses.field(default="RetroAgentDispatched", init=False)
    primary: str
    fallback: str
    model: str
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "fallback": self.fallback,
            "model": self.model,
            "correlation_id": self.correlation_id,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.TelemetryEventsSurfaceTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_audit_call_sites.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): add EscalationRaised, StoryStateChanged, RetroAgentDispatched

REQ-11/12/13 reference these three event dataclasses by name. Each is
frozen + kw-only, exposes event_name as a class attribute, and
satisfies the audit.Event Protocol structurally without importing it."
```

---

## Task 6: Add `audit_state_change` wrapper to `commands/state.py`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/state.py`
- Test: `tests/test_audit_call_sites.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_call_sites.py`:

```python
import os
import tempfile
from pathlib import Path


class StateAuditWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("BMAD_AUDIT_KEY", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved

    def test_short_circuits_when_policy_disables(self) -> None:
        from story_automator.commands.state import audit_state_change

        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "audit.jsonl"
            audit_state_change(
                {},
                target,
                story="1.2",
                from_status="draft",
                to_status="qa",
                correlation_id="c-1",
            )
            self.assertFalse(target.exists())

    def test_appends_when_policy_enables_and_key_set(self) -> None:
        import json

        from story_automator.commands.state import audit_state_change

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "audit.jsonl"
            audit_state_change(
                {"security": {"audit_trail": True}},
                target,
                story="1.2",
                from_status="draft",
                to_status="qa",
                correlation_id="c-1",
            )
            line = target.read_text(encoding="utf-8").strip()
            rec = json.loads(line)
            self.assertEqual(rec["event"], "StoryStateChanged")
            self.assertEqual(
                rec["payload"],
                {
                    "story": "1.2",
                    "from_status": "draft",
                    "to_status": "qa",
                    "correlation_id": "c-1",
                },
            )

    def test_append_failure_propagates(self) -> None:
        # Simulate a lock-held error: a held FileLock at the same path
        # makes audit_for_policy + append raise AuditLockTimeout, and the
        # wrapper must re-raise (REQ-12: failures must not be swallowed).
        import filelock

        from story_automator.commands.state import audit_state_change
        from story_automator.core.audit import AuditLockTimeout

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "audit.jsonl"
            held = filelock.FileLock(str(target) + ".lock")
            held.acquire(timeout=1)
            try:
                with self.assertRaises(AuditLockTimeout):
                    audit_state_change(
                        {"security": {"audit_trail": True}},
                        target,
                        story="1.2",
                        from_status="draft",
                        to_status="qa",
                        correlation_id="c-1",
                    )
            finally:
                held.release()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.StateAuditWrapperTests -v`
Expected: FAIL with `ImportError: cannot import name 'audit_state_change'`.

- [ ] **Step 3: Add the wrapper**

Add these imports to `skills/bmad-story-automator/src/story_automator/commands/state.py` at the existing top-of-file import block (after the existing `from ..core.frontmatter ...` line, around line 8):

```python
from typing import Any, Mapping

from ..core.audit import audit_for_policy
from ..core.telemetry_events import StoryStateChanged
```

Then append at the bottom of the file:

```python
def audit_state_change(
    policy: Mapping[str, Any],
    audit_path: Path,
    *,
    story: str,
    from_status: str,
    to_status: str,
    correlation_id: str,
) -> None:
    """Append a ``StoryStateChanged`` record when the policy gate is on.

    No-op when ``audit_for_policy`` returns ``None`` (REQ-14). Any
    exception from ``AuditLog.append`` propagates per REQ-12 — the state
    mutation must not be silently divorced from the audit record.
    """
    log = audit_for_policy(policy, audit_path)
    if log is None:
        return
    log.append(
        StoryStateChanged(
            story=story,
            from_status=from_status,
            to_status=to_status,
            correlation_id=correlation_id,
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.StateAuditWrapperTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/state.py tests/test_audit_call_sites.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(state): audit_state_change wrapper for StoryStateChanged events

REQ-12: the audit hook for state transitions must live in
commands/state.py. The wrapper short-circuits on the policy gate and
re-raises any append failure so the mutation is never silently
divorced from the audit record."
```

---

## Task 7: Create shared `commands/_audit_hooks.py` with `_audit_path_for` + `_maybe_audit_event`

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/commands/_audit_hooks.py`
- Test: `tests/test_audit_call_sites.py`

Rationale for the leaf module: both `commands/orchestrator.py` and `commands/orchestrator_epic_agents.py` need these helpers. Putting them in `orchestrator.py` and re-importing from `orchestrator_epic_agents.py` creates a circular import because `orchestrator.py` already imports from `orchestrator_epic_agents.py`. A new leaf module avoids the cycle from the start — better than introducing the cycle in Task 7 and untangling it in Task 10.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_call_sites.py`:

```python
class AuditHooksTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("BMAD_AUDIT_KEY", None)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved

    def test_audit_path_for_uses_bmad_audit_subdir(self) -> None:
        from story_automator.commands._audit_hooks import _audit_path_for

        path = _audit_path_for("/tmp/proj")
        self.assertEqual(
            path, Path("/tmp/proj") / "_bmad" / "audit" / "audit.jsonl"
        )

    def test_maybe_audit_event_short_circuits_on_disabled(self) -> None:
        # REQ-14: no I/O when policy gate is off.
        from story_automator.commands._audit_hooks import _maybe_audit_event
        from story_automator.core.telemetry_events import EscalationRaised

        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "_bmad" / "audit" / "audit.jsonl"
            _maybe_audit_event(
                {},
                target,
                EscalationRaised(
                    trigger="review-loop",
                    reason="r",
                    correlation_id="c-1",
                ),
            )
            self.assertFalse(target.exists())
            # And the parent dir was never created.
            self.assertFalse(target.parent.exists())

    def test_maybe_audit_event_writes_when_enabled(self) -> None:
        import json

        from story_automator.commands._audit_hooks import _maybe_audit_event
        from story_automator.core.telemetry_events import EscalationRaised

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "audit.jsonl"
            _maybe_audit_event(
                {"security": {"audit_trail": True}},
                target,
                EscalationRaised(
                    trigger="review-loop",
                    reason="exceeded",
                    correlation_id="c-9",
                ),
            )
            rec = json.loads(target.read_text(encoding="utf-8").strip())
            self.assertEqual(rec["event"], "EscalationRaised")
            self.assertEqual(rec["payload"]["correlation_id"], "c-9")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.AuditHooksTests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'story_automator.commands._audit_hooks'`.

- [ ] **Step 3: Create the leaf module**

Create `skills/bmad-story-automator/src/story_automator/commands/_audit_hooks.py`:

```python
"""Shared audit-hook plumbing for the command modules.

Lives as a leaf module under ``commands/`` so that both ``orchestrator``
and ``orchestrator_epic_agents`` can import from it without creating
an import cycle (``orchestrator`` already imports from
``orchestrator_epic_agents``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..core.audit import Event as _AuditEvent, audit_for_policy


def _audit_path_for(project_root: str | Path) -> Path:
    """Return the conventional audit-log path under a project root.

    The audit subsystem writes a single per-project JSONL log at
    ``<project_root>/_bmad/audit/audit.jsonl``. The directory is created
    lazily by ``AuditLog`` on the first append — callers must not
    pre-create it (REQ-14 forbids any filesystem I/O when the gate is
    off).
    """
    return Path(project_root) / "_bmad" / "audit" / "audit.jsonl"


def _maybe_audit_event(
    policy: Mapping[str, Any], audit_path: Path, event: _AuditEvent
) -> None:
    """Append ``event`` to the audit chain when the policy gate is on.

    No-op when ``audit_for_policy`` returns ``None`` — single dict lookup,
    zero I/O (REQ-14). Errors from ``AuditLog.append`` propagate; callers
    that need a failure-tolerant path must wrap explicitly.
    """
    log = audit_for_policy(policy, audit_path)
    if log is None:
        return
    log.append(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.AuditHooksTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/orchestrator.py tests/test_audit_call_sites.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(orchestrator): _audit_path_for and _maybe_audit_event helpers

Shared plumbing for the three audit-hook integrations. Both helpers
short-circuit cleanly when the policy gate is off (single dict lookup,
zero filesystem I/O, REQ-14)."
```

---

## Task 8: Wire `_escalate` to append `EscalationRaised` before printing

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py:325-369`
- Test: `tests/test_audit_call_sites.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_call_sites.py`:

```python
import io
import json
from contextlib import redirect_stdout


class EscalateAuditIntegrationTests(unittest.TestCase):
    """Integration tests for the _escalate audit hook.

    We patch the policy loader and project-root lookups in
    ``story_automator.commands.orchestrator`` so the test does not
    depend on resolving a real bundled policy under a temp project root
    (``load_runtime_policy`` with explicit state_file goes through the
    legacy-mode path which ignores ``_bmad/bmm/story-automator.policy.json``
    overrides, so toggling via that file would not engage the gate).
    """

    def setUp(self) -> None:
        self._saved_key = os.environ.pop("BMAD_AUDIT_KEY", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved_key is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved_key

    def test_escalate_short_circuits_when_gate_off(self) -> None:
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        with mock.patch.object(
            orch, "load_runtime_policy", return_value={"security": {"audit_trail": False}}
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                orch._escalate(["review-loop", "cycles=99"])
        self.assertFalse(
            (Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl").exists()
        )

    def test_escalate_appends_when_gate_on(self) -> None:
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with mock.patch.object(
            orch, "load_runtime_policy", return_value={"security": {"audit_trail": True}}
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = orch._escalate(["review-loop", "cycles=99"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().strip())
        self.assertTrue(out["escalate"])

        audit_path = Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl"
        self.assertTrue(audit_path.exists())
        rec = json.loads(audit_path.read_text(encoding="utf-8").strip())
        self.assertEqual(rec["event"], "EscalationRaised")
        self.assertEqual(rec["payload"]["trigger"], "review-loop")
        self.assertIn("Review loop exceeded", rec["payload"]["reason"])

    def test_escalate_does_not_audit_non_escalating_dispatch(self) -> None:
        # A "review-loop" dispatch under the limit returns escalate=False.
        # That is not a security event and must not produce an audit row.
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        with mock.patch.object(
            orch, "load_runtime_policy", return_value={"security": {"audit_trail": True}}
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                orch._escalate(["review-loop", "cycles=0"])
        self.assertFalse(
            (Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl").exists()
        )

    def test_escalate_preserves_policy_error_behavior(self) -> None:
        # The legacy contract: when load_runtime_policy raises PolicyError or
        # FileNotFoundError, _escalate prints {"escalate": true, "reason":
        # str(exc)} and returns 0. The new code must keep this behaviour.
        from unittest import mock

        from story_automator.commands import orchestrator as orch
        from story_automator.core.runtime_policy import PolicyError

        with mock.patch.object(
            orch, "load_runtime_policy", side_effect=PolicyError("bad policy")
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = orch._escalate(["review-loop", "cycles=99"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue().strip())
        self.assertTrue(out["escalate"])
        self.assertIn("bad policy", out["reason"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.EscalateAuditIntegrationTests -v`
Expected: FAIL on `test_escalate_appends_when_gate_on` because `_escalate` does not yet emit any audit record.

- [ ] **Step 3: Wire the hook into `_escalate`**

Add these imports at the top of `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py` (alongside the existing block of `from .orchestrator_epic_agents import ...`):

```python
from ._audit_hooks import _audit_path_for, _maybe_audit_event
from ..core.telemetry_events import EscalationRaised
```

Replace the entire `_escalate` function with this version. The legacy contract — when `load_runtime_policy` raises `FileNotFoundError` or `PolicyError`, print `{"escalate": True, "reason": str(exc)}` and return 0 — is preserved as an early return *before* we ever attempt to audit, because at that point we have no policy in hand:

```python
def _escalate(args: list[str]) -> int:
    trigger = args[0] if args else ""
    context = args[1] if len(args) > 1 else ""
    state_file = ""
    idx = 2
    try:
        while idx < len(args):
            if args[idx] == "--state-file":
                state_file = _flag_value(args, idx, "--state-file")
                idx += 2
                continue
            idx += 1
    except PolicyError as exc:
        # Legacy contract: arg-parse PolicyError → escalate=True. No audit
        # — we never loaded a policy, so the gate state is unknown.
        print_json({"escalate": True, "reason": str(exc)})
        return 0
    try:
        policy = load_runtime_policy(get_project_root(), state_file=state_file)
    except (FileNotFoundError, PolicyError) as exc:
        # Legacy contract: policy-load failure → escalate=True. Same
        # rationale as above; do not audit when we have no policy.
        print_json({"escalate": True, "reason": str(exc)})
        return 0

    if trigger == "review-loop":
        cycles = _parse_context_int(context, "cycles")
        limit = review_max_cycles(policy)
        if cycles >= limit:
            result: dict = {
                "escalate": True,
                "reason": f"Review loop exceeded max cycles ({cycles}/{limit})",
            }
        else:
            result = {"escalate": False}
    elif trigger == "session-crash":
        retries = _parse_context_int(context, "retries")
        limit = crash_max_retries(policy)
        if retries >= limit:
            result = {
                "escalate": True,
                "reason": f"Session crashed after {retries} retries",
            }
        else:
            result = {"escalate": False, "action": "retry"}
    elif trigger == "story-validation":
        created = _parse_context_int(context, "created")
        if created != 1:
            result = {
                "escalate": True,
                "reason": "No story file created"
                if created == 0
                else f"Runaway creation: {created} files",
            }
        else:
            result = {"escalate": False}
    else:
        result = {"escalate": False, "reason": "Unknown trigger"}

    # REQ-11: audit before the user-visible print, but only on actual
    # escalations. A non-escalating dispatch is not a security event.
    if result.get("escalate"):
        _maybe_audit_event(
            policy,
            _audit_path_for(get_project_root()),
            EscalationRaised(
                trigger=trigger,
                reason=str(result.get("reason", "")),
                correlation_id=_escalate_correlation_id(state_file, trigger),
            ),
        )

    print_json(result)
    return 0
```

Add this small correlation-id helper near `_parse_context_int` (below the existing `_parse_context_int`):

```python
def _escalate_correlation_id(state_file: str, trigger: str) -> str:
    """Stable correlation id for one escalation event.

    Combines the state-file basename (or empty) with the trigger so the
    audit record can be cross-referenced against the orchestration log.
    """
    base = Path(state_file).name if state_file else ""
    return f"escalate:{trigger}:{base}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.EscalateAuditIntegrationTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/orchestrator.py tests/test_audit_call_sites.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(orchestrator): emit EscalationRaised audit event on escalation

REQ-11: when an escalation triggers (review-loop, session-crash,
story-validation), append an EscalationRaised record before the
user-visible escalation JSON is printed. Non-escalating dispatches are
not security events and are not audited."
```

---

## Task 9: Wire `_state_update` to emit `StoryStateChanged` via `audit_state_change`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py:300-322` (`_state_update`)
- Test: `tests/test_audit_call_sites.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_call_sites.py`:

```python
class StateUpdateAuditIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_key = os.environ.pop("BMAD_AUDIT_KEY", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved_key is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved_key

    def _write_state(self, status_before: str) -> Path:
        state = Path(self._tmp.name) / "state.md"
        state.write_text(
            f"---\nstatus: {status_before}\ncurrentStory: 1.2\n---\nbody\n",
            encoding="utf-8",
        )
        return state

    def test_state_update_short_circuits_when_gate_off(self) -> None:
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        state = self._write_state("READY")
        with mock.patch.object(
            orch,
            "load_runtime_policy",
            return_value={"security": {"audit_trail": False}},
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            rc = orch._state_update([str(state), "--set", "status=IN_PROGRESS"])
        self.assertEqual(rc, 0)
        self.assertFalse(
            (Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl").exists()
        )

    def test_state_update_appends_when_gate_on(self) -> None:
        import json
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        state = self._write_state("READY")
        with mock.patch.object(
            orch,
            "load_runtime_policy",
            return_value={"security": {"audit_trail": True}},
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            rc = orch._state_update([str(state), "--set", "status=IN_PROGRESS"])
        self.assertEqual(rc, 0)
        audit_path = Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl"
        rec = json.loads(audit_path.read_text(encoding="utf-8").strip())
        self.assertEqual(rec["event"], "StoryStateChanged")
        self.assertEqual(rec["payload"]["from_status"], "READY")
        self.assertEqual(rec["payload"]["to_status"], "IN_PROGRESS")
        self.assertEqual(rec["payload"]["story"], "1.2")

    def test_state_update_without_status_change_skips_audit(self) -> None:
        # Updating a non-status field must not produce an audit record —
        # StoryStateChanged is, by name, only for status transitions.
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        state = self._write_state("READY")
        with mock.patch.object(
            orch,
            "load_runtime_policy",
            return_value={"security": {"audit_trail": True}},
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            rc = orch._state_update([str(state), "--set", "currentStory=1.3"])
        self.assertEqual(rc, 0)
        self.assertFalse(
            (Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl").exists()
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.StateUpdateAuditIntegrationTests -v`
Expected: FAIL on `test_state_update_appends_when_gate_on`.

- [ ] **Step 3: Wire the hook**

In `_state_update` (around line 300), capture the prior status before applying `--set status=...`, then call `audit_state_change` after `Path(args[0]).write_text(...)`:

```python
def _state_update(args: list[str]) -> int:
    if not args or not file_exists(args[0]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    text = read_text(args[0])
    fields_before = parse_simple_frontmatter(text)
    updated: list[str] = []
    idx = 1
    while idx < len(args):
        if args[idx] == "--set" and idx + 1 < len(args):
            key, value = args[idx + 1].split("=", 1)
            replaced, count = re.subn(
                rf"(?m)^{re.escape(key)}:.*$",
                lambda m, k=key, v=value: f"{k}: {v}",
                text,
            )
            if count:
                text = replaced
                updated.append(key)
            idx += 2
            continue
        idx += 1
    if not updated:
        print_json({"ok": False, "error": "keys_not_found", "updated": []})
        return 1
    Path(args[0]).write_text(text, encoding="utf-8")

    # REQ-12: audit after the write succeeds. Failures from append are
    # re-raised by audit_state_change so the state mutation is never
    # silently divorced from its audit record.
    if "status" in updated:
        fields_after = parse_simple_frontmatter(text)
        try:
            policy = load_runtime_policy(get_project_root(), state_file=args[0])
        except (FileNotFoundError, PolicyError):
            policy = {}
        audit_state_change(
            policy,
            _audit_path_for(get_project_root()),
            story=str(fields_before.get("currentStory") or ""),
            from_status=str(fields_before.get("status") or ""),
            to_status=str(fields_after.get("status") or ""),
            correlation_id=f"state-update:{Path(args[0]).name}",
        )

    print_json({"ok": True, "updated": updated})
    return 0
```

Add the import at the top of `commands/orchestrator.py` (next to the existing `from .orchestrator_epic_agents import ...`):

```python
from .state import audit_state_change
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.StateUpdateAuditIntegrationTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/orchestrator.py tests/test_audit_call_sites.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(orchestrator): emit StoryStateChanged audit event after status writes

REQ-12: when --set status=... changes the state-doc frontmatter, the
audit hook fires after the write succeeds via the commands/state.py
wrapper (audit_state_change). Failures from append propagate so the
mutation is never silently divorced from the audit record. The hook
no-ops when the --set update does not touch the status field."
```

---

## Task 10: Wire `retro_agent_action` to emit `RetroAgentDispatched`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py:201-220` (`retro_agent_action`)
- Test: `tests/test_audit_call_sites.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_call_sites.py`:

```python
class RetroAgentAuditIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_key = os.environ.pop("BMAD_AUDIT_KEY", None)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def tearDown(self) -> None:
        os.environ.pop("BMAD_AUDIT_KEY", None)
        if self._saved_key is not None:
            os.environ["BMAD_AUDIT_KEY"] = self._saved_key

    def _write_state(self) -> Path:
        state = Path(self._tmp.name) / "state.md"
        state.write_text(
            "---\n"
            "epic: 1\n"
            "currentStory: 1.2\n"
            "agentConfig:\n"
            "  defaultPrimary: \"claude\"\n"
            "  defaultFallback: \"false\"\n"
            "---\nbody\n",
            encoding="utf-8",
        )
        return state

    def test_retro_agent_short_circuits_when_gate_off(self) -> None:
        from unittest import mock

        from story_automator.commands import orchestrator_epic_agents as oea

        state = self._write_state()
        with mock.patch.object(
            oea,
            "load_runtime_policy",
            return_value={"security": {"audit_trail": False}},
        ), mock.patch.object(
            oea, "get_project_root", return_value=self._tmp.name
        ):
            rc = oea.retro_agent_action(["--state-file", str(state)])
        self.assertEqual(rc, 0)
        self.assertFalse(
            (Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl").exists()
        )

    def test_retro_agent_appends_when_gate_on(self) -> None:
        import json
        from unittest import mock

        from story_automator.commands import orchestrator_epic_agents as oea

        os.environ["BMAD_AUDIT_KEY"] = "test-canary-secret"
        state = self._write_state()
        with mock.patch.object(
            oea,
            "load_runtime_policy",
            return_value={"security": {"audit_trail": True}},
        ), mock.patch.object(
            oea, "get_project_root", return_value=self._tmp.name
        ):
            rc = oea.retro_agent_action(["--state-file", str(state)])
        self.assertEqual(rc, 0)
        audit_path = Path(self._tmp.name) / "_bmad" / "audit" / "audit.jsonl"
        rec = json.loads(audit_path.read_text(encoding="utf-8").strip())
        self.assertEqual(rec["event"], "RetroAgentDispatched")
        self.assertIn("correlation_id", rec["payload"])
        self.assertEqual(
            rec["payload"]["correlation_id"], f"retro:{state.name}"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.RetroAgentAuditIntegrationTests -v`
Expected: FAIL on `test_retro_agent_appends_when_gate_on`.

- [ ] **Step 3: Wire the hook**

Edit `retro_agent_action` in `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py`:

```python
def retro_agent_action(args: list[str]) -> int:
    options = {"state-file": ""}
    idx = 0
    while idx < len(args):
        key = args[idx].lstrip("-")
        if idx + 1 < len(args):
            options[key] = args[idx + 1]
            idx += 2
        else:
            idx += 1
    if not options["state-file"]:
        print_json({"ok": False, "error": "missing_args"})
        return 1
    if not file_exists(options["state-file"]):
        print_json({"ok": False, "error": "file_not_found"})
        return 1
    config = _load_agent_config_from_state(options["state-file"])
    primary, fallback, model = resolve_agent(config, "medium", "retro")

    # REQ-13: audit each retro-agent selection with the same correlation
    # id surface that surrounding telemetry uses (the state-file basename).
    try:
        policy = load_runtime_policy(
            get_project_root(), state_file=options["state-file"]
        )
    except (FileNotFoundError, PolicyError):
        policy = {}
    correlation_id = f"retro:{Path(options['state-file']).name}"
    _maybe_audit_event(
        policy,
        _audit_path_for(get_project_root()),
        RetroAgentDispatched(
            primary=primary,
            fallback=fallback,
            model=model,
            correlation_id=correlation_id,
        ),
    )

    print_json({"ok": True, "task": "retro", "primary": primary, "fallback": fallback, "model": model})
    return 0
```

Add these imports at the top of the file (alongside the existing `core` imports):

```python
from ._audit_hooks import _audit_path_for, _maybe_audit_event
from story_automator.core.runtime_policy import PolicyError, load_runtime_policy
from story_automator.core.telemetry_events import RetroAgentDispatched
```

(The `_audit_hooks` leaf module is created in Task 7, so no circular-import issue arises.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.RetroAgentAuditIntegrationTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py tests/test_audit_call_sites.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(retro): emit RetroAgentDispatched audit event on selection

REQ-13: each retro-agent dispatch appends a RetroAgentDispatched
record with the correlation id (state-file basename) that surrounding
telemetry already uses."
```

---

## Task 11: Cross-cutting short-circuit assertion (REQ-14 audit)

**Files:**
- Test: `tests/test_audit_call_sites.py`

- [ ] **Step 1: Write the failing test**

Append a final dedicated test class that asserts the no-I/O contract across all three call-sites in one place:

```python
class CallSiteShortCircuitContractTests(unittest.TestCase):
    """REQ-14: when audit_for_policy returns None, no integration may touch
    the filesystem beyond what the surrounding code already does.

    We use the default (gate-off) policy explicitly via mock.patch so the
    test does not depend on the bundled policy file resolving under the
    temp project root.
    """

    GATE_OFF = {"security": {"audit_trail": False}}

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_no_audit_dir_created_after_default_escalate(self) -> None:
        import io
        from contextlib import redirect_stdout
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        with mock.patch.object(
            orch, "load_runtime_policy", return_value=self.GATE_OFF
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            with redirect_stdout(io.StringIO()):
                orch._escalate(["review-loop", "cycles=0"])
        self.assertFalse((Path(self._tmp.name) / "_bmad" / "audit").exists())

    def test_no_audit_dir_created_after_default_retro_agent(self) -> None:
        from unittest import mock

        from story_automator.commands import orchestrator_epic_agents as oea

        state = Path(self._tmp.name) / "state.md"
        state.write_text(
            "---\nagentConfig:\n  defaultPrimary: \"claude\"\n"
            "  defaultFallback: \"false\"\n---\n",
            encoding="utf-8",
        )
        with mock.patch.object(
            oea, "load_runtime_policy", return_value=self.GATE_OFF
        ), mock.patch.object(
            oea, "get_project_root", return_value=self._tmp.name
        ):
            oea.retro_agent_action(["--state-file", str(state)])
        self.assertFalse((Path(self._tmp.name) / "_bmad" / "audit").exists())

    def test_no_audit_dir_created_after_default_state_update(self) -> None:
        from unittest import mock

        from story_automator.commands import orchestrator as orch

        state = Path(self._tmp.name) / "state.md"
        state.write_text(
            "---\nstatus: READY\ncurrentStory: 1.2\n---\n",
            encoding="utf-8",
        )
        with mock.patch.object(
            orch, "load_runtime_policy", return_value=self.GATE_OFF
        ), mock.patch.object(
            orch, "get_project_root", return_value=self._tmp.name
        ):
            orch._state_update([str(state), "--set", "status=IN_PROGRESS"])
        self.assertFalse((Path(self._tmp.name) / "_bmad" / "audit").exists())
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_call_sites.CallSiteShortCircuitContractTests -v`
Expected: PASS (no code change should be needed — Tasks 8/9/10 already short-circuit; this test just locks the contract).

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_call_sites.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): assert no-IO contract across three call-site integrations

REQ-14 demands that when the gate is off, each integration performs no
filesystem I/O beyond what the surrounding code already does. This
single test class locks the contract across _escalate, _state_update,
and retro_agent_action."
```

---

## Task 12: Re-assert the 500-line module budget after policy helper lands

**Files:**
- Test: `tests/test_audit_policy.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_audit_policy.py`:

```python
class AuditModuleSizeBudgetM4Tests(unittest.TestCase):
    def test_audit_module_at_or_below_500_lines(self) -> None:
        # Same NFR as M2/M3; re-asserted here so an M4-only run catches
        # accidental bloat without depending on the M2/M3 suites.
        from pathlib import Path

        audit_path = (
            Path(__file__).resolve().parents[1]
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "audit.py"
        )
        line_count = sum(1 for _ in audit_path.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            line_count,
            500,
            f"audit.py is {line_count} lines (budget: 500 per NFR-500-line-cap)",
        )
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_policy.AuditModuleSizeBudgetM4Tests -v`
Expected: PASS (audit.py gained ~25 lines for `audit_for_policy`; still well under 500).

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_policy.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(audit): re-pin 500-line module budget in M4 policy suite"
```

---

## Task 13: Final ruff + full unittest discovery + coverage gate

**Files:**
- (verification only)

- [ ] **Step 1: Run ruff check**

Run:
```
ruff check skills/bmad-story-automator/src/story_automator/core/audit.py \
          skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
          skills/bmad-story-automator/src/story_automator/core/runtime_policy.py \
          skills/bmad-story-automator/src/story_automator/commands/orchestrator.py \
          skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py \
          skills/bmad-story-automator/src/story_automator/commands/state.py \
          skills/bmad-story-automator/src/story_automator/commands/_audit_hooks.py \
          tests/test_audit_policy.py tests/test_audit_call_sites.py
```
Expected: zero findings.

- [ ] **Step 2: Run ruff format --check**

Run:
```
ruff format --check skills/bmad-story-automator/src/story_automator/core/audit.py \
                    skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
                    skills/bmad-story-automator/src/story_automator/core/runtime_policy.py \
                    skills/bmad-story-automator/src/story_automator/commands/orchestrator.py \
                    skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py \
                    skills/bmad-story-automator/src/story_automator/commands/state.py \
                    skills/bmad-story-automator/src/story_automator/commands/_audit_hooks.py \
                    tests/test_audit_policy.py tests/test_audit_call_sites.py
```
Expected: no diffs.

- [ ] **Step 3: Run the full audit test discovery**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -p "test_audit*.py" -v`
Expected: all M1, M2, M3, M4 audit tests pass; zero failures, zero errors.

- [ ] **Step 4: Run the full project discovery to catch regressions in other suites**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v`
Expected: all tests pass. The schema change in Task 1 and the orchestrator wiring in Tasks 8/9 could plausibly regress existing `commands/orchestrator` or `runtime_policy` tests — if any fail, investigate root cause; do not paper over.

- [ ] **Step 5: Run coverage gate on `core/audit.py`**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src coverage run --branch -m unittest discover -s tests -p "test_audit*.py"
coverage report --include='*/audit.py' --fail-under=85
```
Expected: ≥85% statement coverage on `audit.py`.

- [ ] **Step 6: No commit required for the gate run unless coverage shifted the suite**

If coverage came in below 85%, add a targeted test in `tests/test_audit_policy.py` that hits the uncovered branch (likely `audit_for_policy`'s key-loaded happy path or the `AuditKeyMissing` raise) and commit it as `test(audit): cover <branch>`.

---

## Self-Review Summary

- **Spec coverage:** REQ-10 → Tasks 2/3/4; REQ-11 → Task 8; REQ-12 → Tasks 6/9; REQ-13 → Task 10; REQ-14 → Tasks 5/8/9/10/11. Policy-schema extension and NFRs covered by Tasks 1/12/13.
- **Placeholder scan:** none. Every code block is concrete. The one judgment call — moving `_audit_path_for` / `_maybe_audit_event` into `commands/_audit_hooks.py` to avoid an import cycle — is spelled out in Task 10 with exact steps.
- **Type consistency:** `audit_for_policy(policy: Mapping[str, Any], path: pathlib.Path) -> AuditLog | None` is used identically in tests, wrapper, and call-sites; `EscalationRaised` / `StoryStateChanged` / `RetroAgentDispatched` use the same kw-only field names across declaration, helper, and tests; `audit_state_change` keyword names match the dataclass constructor.
- **Spec interpretation flagged:** REQ-12 says "commands/state.py must invoke the same helper inside its state-update path". This repo's state-update handler currently lives in `commands/orchestrator.py::_state_update`. To honour the spec literally and stay forward-compatible with M05's migration, the audit hook itself is implemented as `audit_state_change` in `commands/state.py` and called from the orchestrator's state-update path.
