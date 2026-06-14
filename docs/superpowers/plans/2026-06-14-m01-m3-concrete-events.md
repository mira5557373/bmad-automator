# M01-M3 — Concrete Event Classes (REQ-05 + REQ-06) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append the 13 concrete typed event `@dataclass` subclasses to `core/telemetry_events.py` covering the BMAD story lifecycle (REQ-05) and pin `Event._REGISTRY`'s exactly-13-entry shape with companion completeness tests (REQ-06). Per-class round-trip is verified via a shared `_round_trip` helper that exercises `to_json_line` → `parse_event` → type-identity + dataclass `__eq__` + byte-equal re-emission.

**Architecture:** Pure-data, additive. Each concrete class is a `@dataclass(kw_only=True)` subclass of `Event` declaring an `EVENT_TYPE` classvar (snake_case form of its class name) plus the additional fields documented in the M01 design doc's 13-row table. Auto-registration is inherited from m01-m1's `__init_subclass__` — no changes to the base. The 13 round-trip tests share a `_round_trip(self, event)` helper method that re-emits + parses + asserts type identity, dataclass equality, and byte-equal serialization. Three registry-completeness tests cement REQ-06: production-only filter (13 entries with no leading-underscore sentinels), `UnknownEvent`-not-registered, and each registered class's `EVENT_TYPE` classvar matches its registry key.

**Tech Stack:** Python 3.11+ (`requires-python` in `pyproject.toml`). Stdlib only — no new imports beyond what m01-m1 and m01-m2 already added (`json`, `asdict`, `dataclass`, `Any`, `ClassVar`, `compact_json`, `iso_now`). Tests use `unittest.TestCase` per project convention. The `kw_only=True` modifier on every concrete class is mandatory: `Event` has `timestamp` and `run_id` as required non-default fields, so any subclass adding more required fields without `kw_only` would hit Python's "non-default after default" inheritance ordering rule (`TypeError` at class creation time).

**Slice scope:** This plan covers **m01-m3-concrete-events ONLY**: REQ-05 + REQ-06. It does **NOT** add the broader REQ-08 sweep with parameterized variants or edge cases (unicode in story_key, int-vs-float strictness, bool strictness) — those land in m01-m4. It does **NOT** add the REQ-09 broader byte-equal sweep across arbitrary unrecognized event_types — m01-m4. It does **NOT** add the 85% coverage gate, the import-allowlist grep gate, or the module-size `wc -l` gate — m01-m4. It **DOES** land the 13 per-class round-trip tests because those tests are the natural verification that REQ-05's "each declaring an EVENT_TYPE classvar matching the snake_case form of its class name and the additional fields" holds end-to-end through the parsing protocol from m01-m2. Per-class round-trip is REQ-08 read narrowly; the broader REQ-08 sweep is m01-m4.

**Parent artifacts:**
- Spec: `docs/superpowers/specs/2026-06-14-m01-event-types.md` (focus on REQ-05, REQ-06)
- Design doc: `docs/superpowers/specs/2026-06-14-m01-event-types-design.md` (the 13-row class table + field signatures + EVENT_TYPE strings)
- Parent plan (full M01): `docs/superpowers/plans/2026-06-14-m01-event-types.md`
- Predecessor slices: `docs/superpowers/plans/2026-06-14-m01-m1-event-base.md`, `docs/superpowers/plans/2026-06-14-m01-m2-event-parsing.md`
- Workflow milestone: `.claude/workflow.json` → `m01-m3-concrete-events`

---

## Prior Work Handling (READ BEFORE TASK 1)

A prior commit may have bundled m01-m3's scope alongside m01-m2 work (e.g., `git log --oneline` may show `feat(telemetry): 13 concrete event classes + round-trip + registry tests` already merged). If so, the 13 concrete classes, the 13 round-trip tests, and the registry-completeness tests are **already present** in the codebase. Each task's literal TDD flow ("Step 2: expect FAIL") will not actually fail — the test will PASS on the first run because the class and test both already exist.

**Adaptation protocol for every task in this plan.** Each subagent dispatched for Tasks 2–15 must run this protocol at the start of the task:

1. **Probe for existing implementation.** Run the grep documented in Task 1 Step 3 — does the task's target class (`StoryStarted`, `BudgetAlert`, etc.) already exist in `core/telemetry_events.py`?
2. **Probe for existing test.** Grep `tests/test_telemetry_events.py` for the task's test method name (`test_story_started_round_trip`, etc.) — does it already exist?
3. **Branch:**
   - **Both absent (clean state):** follow the task's TDD flow literally. Step 2 should FAIL; Step 4 should PASS.
   - **Both present (pre-existing work):** skip Step 1 (test addition) and Step 3 (class implementation). At Step 2 run the test alone and expect **PASS** (this verifies the existing implementation is correct). At Step 4, re-run the full suite — still PASS. At Step 5, **do NOT commit** (the work is already committed in a prior bundle); record this in the executor log as `task-N: verified pre-existing implementation, no commit`. Skip to the next task.
   - **Class present, test absent (or vice versa):** treat the task's task as adding the missing piece only. Reconcile in the executor log.

**Why this matters:** under subagent-driven execution each task is dispatched to a fresh agent that does not see this orchestrator-level context. The adaptation protocol must be encoded **in the plan** so each subagent reads it before its own task. Inline execution (single session) preserves context naturally and can apply the protocol once at Task 1.

**Test-count math under both scenarios converges to 62:**
- Clean state: m01-m2 baseline 44 + (13 round-trip + 3 registry + 2 export-contract) = 62.
- Pre-existing state: 60 currently in file (44 m01-m2 + 16 from prior bundled commit) + 2 export-contract from Task 16 = 62.

Task 17 Step 4 expects 62 under both paths.

---

## File Structure

| Path | Kind | Responsibility (this slice) |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` | MODIFY | Append the 13 concrete `@dataclass(kw_only=True)` event classes after `UnknownEvent` and before `parse_event`. Update `__all__` to export the 13 new class names. |
| `tests/test_telemetry_events.py` | MODIFY | Append `ConcreteEventRoundTripTests` (13 round-trip tests + `_round_trip` helper) and `RegistryCompletenessTests` (3 tests). |

**Out of scope (DO NOT add in this slice):**
- Parameterized variants of round-trip per class (e.g., unicode payloads, ASCII boundary cases) — m01-m4 owns broader REQ-08.
- The full REQ-09 byte-equal sweep across arbitrary unrecognized event_types — m01-m4.
- The 85% coverage gate (`pytest --cov-fail-under=85`) — m01-m4.
- The import-allowlist grep gate — m01-m4.
- The module-size `wc -l` gate — m01-m4.
- Field-type strictness tests (`tokens_in=1.5` rejected, `blocking="yes"` rejected) — m01-m4 if added.

## Conventions

- `from __future__ import annotations` is already at the top of the module — do not duplicate.
- Every concrete subclass is `@dataclass(kw_only=True)` — see the **Why kw_only=True** note in Task 2 Step 3.
- All concrete-class instance fields are stdlib primitives (`str`, `int`, `float`, `bool`). No nested dataclasses (M01 design constraint). No defaults — every field is required.
- `EVENT_TYPE` classvar string is exactly the snake_case form of the class name: `StoryStarted` → `"story_started"`. The spec wording REQ-05 makes this an enforceable property.
- Field declaration order inside each class matches the order in the design doc's 13-row table. Order matters because `to_dict` → `asdict` preserves declaration order, and the byte-equal round-trip relies on stable key ordering.
- Each new test class is appended above the `if __name__ == "__main__":` line, after the last existing test class.
- Conventional Commits with `Generated-By: claude-opus-4-7` trailer. One commit per task (the commit message is provided verbatim in each task's final step).

## Test runner commands (cross-platform)

| Action | Command (Windows git-bash / WSL / Linux all OK) |
|---|---|
| Run this slice's tests only | `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v` |
| Run a single new test method | `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_story_started_round_trip -v` |
| Lint new+modified files | `python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` |
| Format check | `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` |
| Full suite still passes | `npm run test:python` |

The `python` command on Windows resolves to Python 3.14 at `/c/Python314/python`; on WSL/Linux it resolves to whatever `python3` is configured (3.11/3.12/3.13). REQ-01's multi-version import-cleanliness criterion remains satisfied — `kw_only=True` is a 3.10+ dataclass feature and the project requires 3.11+.

## BLOCKED protocol

If any step produces unexpected output:
1. Stop. Do NOT proceed to the next step.
2. Capture the exact command, full stdout, full stderr, exit code.
3. Report: `BLOCKED at Task N Step S: <one-line summary>. Command: ..., Expected: ..., Actual: ...`
4. Wait for guidance before resuming.

Common blockers anticipated for this slice:
- **Field-ordering error at class-creation time:** if `kw_only=True` is forgotten, Python raises `TypeError: non-default argument 'epic' follows default argument` (or similar) when the module is first imported. Fix: confirm every concrete class has `@dataclass(kw_only=True)`.
- **Duplicate `EVENT_TYPE`:** if a typo causes two classes to share an `EVENT_TYPE` string, `__init_subclass__` raises `RuntimeError` at import time with both qualnames embedded. Fix: re-read the design doc's 13-row table and correct the typo.
- **Registry leakage in the completeness test:** if an earlier test forgot `_RegistryIsolationMixin` and left a `_temp_*` key in `Event._REGISTRY`, the completeness test's count or membership assertion fails. Fix: audit the offending test class for the mixin; the completeness test filters out `_`-prefixed keys defensively but a leaked key without the underscore prefix would still trip it.

---

## Task 1: Site inventory — confirm prerequisites and identify the seam

**Files:** None modified — verification only.

- [ ] **Step 1: Confirm m01-m2's surface is in place**

Run:

```bash
grep -n "^def parse_event\|^class UnknownEvent\|^class Event\b" \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: three matches — `class Event(...)`, `class UnknownEvent(Event)`, `def parse_event(line: str) -> Event`. If any are missing, m01-m2 did not land cleanly and m01-m3 cannot proceed — BLOCKED.

- [ ] **Step 2: Confirm `_RegistryIsolationMixin` is available**

Run:

```bash
grep -n "_RegistryIsolationMixin" tests/test_telemetry_events.py
```

Expected: a class definition near the top of the file and multiple uses by existing m01-m1 / m01-m2 test classes. If absent, m01-m1 regressed — BLOCKED.

- [ ] **Step 3: Confirm no production concrete events exist yet**

Run:

```bash
grep -nE "^class (StoryStarted|StoryCompleted|StoryFailed|StoryDeferred|RetryAttempt|EscalationTriggered|ReviewCycle|RetroFired|TmuxSessionSpawned|TmuxSessionCompleted|TmuxSessionCrashed|CostCharged|BudgetAlert)\b" \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected (for a clean slice start): zero matches. **If matches are found, the work has already landed in a prior commit** (e.g., during a bundled m01-m2/m01-m3 effort). In that case, this slice's job is to verify the implementation against the spec, run the gates, and skip the test+impl steps where they would re-add existing content. Proceed to Task 2 and adapt: for each task whose test or class already exists, replace Step 3's "Implement..." action with a verification read.

- [ ] **Step 4: Identify the insertion point**

Run:

```bash
grep -nE "^def parse_event|^@dataclass$" \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: a line number for `def parse_event(...)`. The 13 concrete event classes will be appended **between** the end of `UnknownEvent` and the `def parse_event(...)` line. Record this line number locally (e.g., `parse_event` is at line ~291); each subsequent task's "append" step inserts immediately above that line.

No commit for this task — verification gate only. Proceed to Task 2.

---

## Task 2: `ConcreteEventRoundTripTests` skeleton + `StoryStarted` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write the failing test class with the shared helper + first round-trip**

Append the following to `tests/test_telemetry_events.py` (above the `if __name__ == "__main__":` line):

```python
class ConcreteEventRoundTripTests(unittest.TestCase):
    """REQ-05 + REQ-08 (narrow): per-class round-trip for every concrete event.

    For each of the 13 concrete event classes the round trip
    ``instance -> to_json_line -> parse_event`` must return an instance of
    the same class that compares equal via dataclass ``__eq__`` and whose
    own ``to_json_line`` output is byte-equal to the original line. This
    catches any drift in field declaration order, in the ``to_dict`` key
    insertion order, or in ``compact_json``'s separator policy.
    """

    def _round_trip(self, event: Event) -> None:
        from story_automator.core.telemetry_events import parse_event

        line = event.to_json_line()
        parsed = parse_event(line)
        self.assertIs(type(parsed), type(event))
        self.assertEqual(parsed, event)
        self.assertEqual(parsed.to_json_line(), line)

    def test_story_started_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryStarted

        self._round_trip(
            StoryStarted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                agent="claude",
                model="sonnet",
                complexity="medium",
            )
        )
```

The `_round_trip` helper's type annotation `event: Event` works because `Event` is imported at module top via the `TYPE_CHECKING` block in `tests/test_telemetry_events.py` (m01-m1 set this up). The helper is private — `_round_trip` rather than `roundTrip` or `assertRoundTrip` — because it is an internal driver, not a public assertion method that unittest's discovery should treat as test-bearing.

- [ ] **Step 2: Run the new test (expect FAIL)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests -v
```

Expected: FAIL with `ImportError: cannot import name 'StoryStarted' from 'story_automator.core.telemetry_events'`.

- [ ] **Step 3: Implement `StoryStarted`**

**Why `kw_only=True`:** Python's dataclass inheritance forces non-default fields to precede defaulted ones across the whole MRO. `Event` (m01-m1) declares `timestamp: str` and `run_id: str` as required non-default fields. Any concrete subclass that adds more required non-default fields (which is every M01 concrete class — REQ-05 has no field defaults) would, without `kw_only`, force Python to require those new fields to appear positionally **before** any defaulted ancestor field. Since `Event` has no defaulted fields the strict ordering passes, but the call site becomes positional and fragile. With `kw_only=True` the subclass's fields become keyword-only at construction, which (a) eliminates any ordering surprise during future maintenance if a defaulted field is ever added upstream, and (b) makes `parse_event`'s `cls(**payload)` invocation strictly keyword-driven, which is the same contract `parse_event` already relies on from m01-m2. **Strict construction is preserved end-to-end:** missing required fields raise `TypeError`; extra fields raise `TypeError`; positional-only confusion is impossible.

In `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`, insert the following **after** the `UnknownEvent` class definition (specifically after `UnknownEvent.to_dict`'s closing line) and **before** `def parse_event(...)`:

```python
@dataclass(kw_only=True)
class StoryStarted(Event):
    """Emitted when a tmux session spawns to begin work on a story."""

    EVENT_TYPE: ClassVar[str] = "story_started"

    epic: str
    story_key: str
    agent: str
    model: str
    complexity: str
```

- [ ] **Step 4: Run tests (expect PASS)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all previously-passing m01-m1 / m01-m2 tests still pass, plus the new `test_story_started_round_trip` case passes.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): StoryStarted concrete event + round-trip test"
```

---

## Task 3: `StoryCompleted` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append the following method **inside** the existing `ConcreteEventRoundTripTests` class in `tests/test_telemetry_events.py` (immediately after `test_story_started_round_trip`):

```python
    def test_story_completed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryCompleted

        self._round_trip(
            StoryCompleted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                duration_s=42.5,
                cost_usd=1.23,
                tokens_in=1000,
                tokens_out=500,
                attempts=2,
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_story_completed_round_trip -v
```

Expected: `ImportError: cannot import name 'StoryCompleted'`.

- [ ] **Step 3: Implement `StoryCompleted`**

Insert after `StoryStarted` and before `def parse_event(...)`:

```python
@dataclass(kw_only=True)
class StoryCompleted(Event):
    """Emitted when a story is verified commit-ready."""

    EVENT_TYPE: ClassVar[str] = "story_completed"

    epic: str
    story_key: str
    duration_s: float
    cost_usd: float
    tokens_in: int
    tokens_out: int
    attempts: int
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass, count increases by 1.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): StoryCompleted concrete event + round-trip test"
```

---

## Task 4: `StoryFailed` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_story_failed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryFailed

        self._round_trip(
            StoryFailed(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                error_class="CRASH",
                reason="exit code 1",
                attempts=5,
                final_session="sa-foo-abc123",
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_story_failed_round_trip -v
```

Expected: `ImportError: cannot import name 'StoryFailed'`.

- [ ] **Step 3: Implement `StoryFailed`**

Insert after `StoryCompleted` and before `def parse_event(...)`:

```python
@dataclass(kw_only=True)
class StoryFailed(Event):
    """Emitted when all retries on a story have been exhausted."""

    EVENT_TYPE: ClassVar[str] = "story_failed"

    epic: str
    story_key: str
    error_class: str
    reason: str
    attempts: int
    final_session: str
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): StoryFailed concrete event + round-trip test"
```

---

## Task 5: `StoryDeferred` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_story_deferred_round_trip(self) -> None:
        from story_automator.core.telemetry_events import StoryDeferred

        self._round_trip(
            StoryDeferred(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                reason="plateau",
                tasks_completed=4,
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_story_deferred_round_trip -v
```

Expected: `ImportError: cannot import name 'StoryDeferred'`.

- [ ] **Step 3: Implement `StoryDeferred`**

Insert after `StoryFailed`:

```python
@dataclass(kw_only=True)
class StoryDeferred(Event):
    """Emitted when plateau detection or a complexity cap defers a story."""

    EVENT_TYPE: ClassVar[str] = "story_deferred"

    epic: str
    story_key: str
    reason: str
    tasks_completed: int
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): StoryDeferred concrete event + round-trip test"
```

---

## Task 6: `RetryAttempt` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_retry_attempt_round_trip(self) -> None:
        from story_automator.core.telemetry_events import RetryAttempt

        self._round_trip(
            RetryAttempt(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                attempt_num=3,
                agent="claude",
                model="opus",
                prev_error_class="TIMEOUT",
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_retry_attempt_round_trip -v
```

Expected: `ImportError: cannot import name 'RetryAttempt'`.

- [ ] **Step 3: Implement `RetryAttempt`**

Insert after `StoryDeferred`:

```python
@dataclass(kw_only=True)
class RetryAttempt(Event):
    """Emitted when starting a retry attempt (attempts 2 through 5)."""

    EVENT_TYPE: ClassVar[str] = "retry_attempt"

    epic: str
    story_key: str
    attempt_num: int
    agent: str
    model: str
    prev_error_class: str
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): RetryAttempt concrete event + round-trip test"
```

---

## Task 7: `EscalationTriggered` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_escalation_triggered_round_trip(self) -> None:
        from story_automator.core.telemetry_events import EscalationTriggered

        self._round_trip(
            EscalationTriggered(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                trigger_id=4,
                severity="CRITICAL",
                message="story file missing",
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_escalation_triggered_round_trip -v
```

Expected: `ImportError: cannot import name 'EscalationTriggered'`.

- [ ] **Step 3: Implement `EscalationTriggered`**

Insert after `RetryAttempt`:

```python
@dataclass(kw_only=True)
class EscalationTriggered(Event):
    """Emitted when one of the escalation rules fires for a story."""

    EVENT_TYPE: ClassVar[str] = "escalation_triggered"

    epic: str
    story_key: str
    trigger_id: int
    severity: str
    message: str
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): EscalationTriggered concrete event + round-trip test"
```

---

## Task 8: `ReviewCycle` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_review_cycle_round_trip(self) -> None:
        from story_automator.core.telemetry_events import ReviewCycle

        self._round_trip(
            ReviewCycle(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                cycle_num=2,
                issues_found=3,
                blocking=True,
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_review_cycle_round_trip -v
```

Expected: `ImportError: cannot import name 'ReviewCycle'`.

- [ ] **Step 3: Implement `ReviewCycle`**

Insert after `EscalationTriggered`:

```python
@dataclass(kw_only=True)
class ReviewCycle(Event):
    """Emitted per code-review cycle (up to five per story)."""

    EVENT_TYPE: ClassVar[str] = "review_cycle"

    epic: str
    story_key: str
    cycle_num: int
    issues_found: int
    blocking: bool
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): ReviewCycle concrete event + round-trip test"
```

---

## Task 9: `RetroFired` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_retro_fired_round_trip(self) -> None:
        from story_automator.core.telemetry_events import RetroFired

        self._round_trip(
            RetroFired(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                stories_completed=5,
                total_cost_usd=12.34,
                duration_s=300.0,
            )
        )
```

Note: `RetroFired` deliberately has no `story_key` — retrospectives are emitted at epic granularity, not per-story (per the design doc).

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_retro_fired_round_trip -v
```

Expected: `ImportError: cannot import name 'RetroFired'`.

- [ ] **Step 3: Implement `RetroFired`**

Insert after `ReviewCycle`:

```python
@dataclass(kw_only=True)
class RetroFired(Event):
    """Emitted when an epic retrospective runs."""

    EVENT_TYPE: ClassVar[str] = "retro_fired"

    epic: str
    stories_completed: int
    total_cost_usd: float
    duration_s: float
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): RetroFired concrete event + round-trip test"
```

---

## Task 10: `TmuxSessionSpawned` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_tmux_session_spawned_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionSpawned

        self._round_trip(
            TmuxSessionSpawned(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                session_name="sa-foo-abc123",
                story_key="3.1",
                pid=12345,
                pane_geometry="200x50",
            )
        )
```

Note: `TmuxSessionSpawned` deliberately has no `epic` — tmux events are scoped by session_name + story_key, not by epic (per the design doc).

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_tmux_session_spawned_round_trip -v
```

Expected: `ImportError: cannot import name 'TmuxSessionSpawned'`.

- [ ] **Step 3: Implement `TmuxSessionSpawned`**

Insert after `RetroFired`:

```python
@dataclass(kw_only=True)
class TmuxSessionSpawned(Event):
    """Emitted when a tmux session is created for a story."""

    EVENT_TYPE: ClassVar[str] = "tmux_session_spawned"

    session_name: str
    story_key: str
    pid: int
    pane_geometry: str
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TmuxSessionSpawned concrete event + round-trip test"
```

---

## Task 11: `TmuxSessionCompleted` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_tmux_session_completed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionCompleted

        self._round_trip(
            TmuxSessionCompleted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                session_name="sa-foo-abc123",
                story_key="3.1",
                exit_code=0,
                duration_s=45.0,
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_tmux_session_completed_round_trip -v
```

Expected: `ImportError: cannot import name 'TmuxSessionCompleted'`.

- [ ] **Step 3: Implement `TmuxSessionCompleted`**

Insert after `TmuxSessionSpawned`:

```python
@dataclass(kw_only=True)
class TmuxSessionCompleted(Event):
    """Emitted when a tmux session exits normally."""

    EVENT_TYPE: ClassVar[str] = "tmux_session_completed"

    session_name: str
    story_key: str
    exit_code: int
    duration_s: float
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TmuxSessionCompleted concrete event + round-trip test"
```

---

## Task 12: `TmuxSessionCrashed` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_tmux_session_crashed_round_trip(self) -> None:
        from story_automator.core.telemetry_events import TmuxSessionCrashed

        self._round_trip(
            TmuxSessionCrashed(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                session_name="sa-foo-abc123",
                story_key="3.1",
                exit_code=137,
                last_capture_chars=4096,
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_tmux_session_crashed_round_trip -v
```

Expected: `ImportError: cannot import name 'TmuxSessionCrashed'`.

- [ ] **Step 3: Implement `TmuxSessionCrashed`**

Insert after `TmuxSessionCompleted`:

```python
@dataclass(kw_only=True)
class TmuxSessionCrashed(Event):
    """Emitted when a tmux session terminates abnormally."""

    EVENT_TYPE: ClassVar[str] = "tmux_session_crashed"

    session_name: str
    story_key: str
    exit_code: int
    last_capture_chars: int
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): TmuxSessionCrashed concrete event + round-trip test"
```

---

## Task 13: `CostCharged` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_cost_charged_round_trip(self) -> None:
        from story_automator.core.telemetry_events import CostCharged

        self._round_trip(
            CostCharged(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                phase="dev",
                cost_usd=0.45,
                tokens_in=2000,
                tokens_out=800,
                model="sonnet",
            )
        )
```

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_cost_charged_round_trip -v
```

Expected: `ImportError: cannot import name 'CostCharged'`.

- [ ] **Step 3: Implement `CostCharged`**

Insert after `TmuxSessionCrashed`:

```python
@dataclass(kw_only=True)
class CostCharged(Event):
    """Emitted when each ``claude -p`` invocation completes."""

    EVENT_TYPE: ClassVar[str] = "cost_charged"

    epic: str
    story_key: str
    phase: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    model: str
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): CostCharged concrete event + round-trip test"
```

---

## Task 14: `BudgetAlert` round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Append the failing round-trip test**

Append to `ConcreteEventRoundTripTests`:

```python
    def test_budget_alert_round_trip(self) -> None:
        from story_automator.core.telemetry_events import BudgetAlert

        self._round_trip(
            BudgetAlert(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                threshold_pct=75,
                total_cost_usd=15.0,
                max_budget_usd=20.0,
                epic="3",
                story_key="3.1",
            )
        )
```

Note: `BudgetAlert`'s field order places `threshold_pct` first per the design doc — budget-level fields lead, then the originating story scope.

- [ ] **Step 2: Run the new test (expect FAIL)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripTests.test_budget_alert_round_trip -v
```

Expected: `ImportError: cannot import name 'BudgetAlert'`.

- [ ] **Step 3: Implement `BudgetAlert`**

Insert after `CostCharged` (still before `def parse_event(...)`):

```python
@dataclass(kw_only=True)
class BudgetAlert(Event):
    """Emitted when crossing a 50/75/90/100 percent budget threshold."""

    EVENT_TYPE: ClassVar[str] = "budget_alert"

    threshold_pct: int
    total_cost_usd: float
    max_budget_usd: float
    epic: str
    story_key: str
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all 13 round-trip tests now pass. After this task, every entry in the design doc's 13-row table is implemented and verified.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): BudgetAlert concrete event + round-trip test"
```

---

## Task 15: `RegistryCompletenessTests` — pin REQ-06's exactly-13-entry contract

**Files:**
- Modify: `tests/test_telemetry_events.py`

(No source change — REQ-06 is a property of the module state after import. The 13 classes from Tasks 2–14 auto-registered into `Event._REGISTRY` via the inherited `__init_subclass__` hook. This task adds the three tests that cement that contract.)

- [ ] **Step 1: Append the registry-completeness test class**

Append the following new test class to `tests/test_telemetry_events.py`, above the `if __name__ == "__main__":` line:

```python
class RegistryCompletenessTests(unittest.TestCase):
    """REQ-06: after module import Event._REGISTRY contains exactly 13
    entries keyed by the concrete classes' EVENT_TYPE strings; UnknownEvent
    must NOT be present.

    Uses a module-level filter that excludes leading-underscore keys so a
    leaked ``_temp_*`` sentinel from a test that aborted before
    ``_RegistryIsolationMixin.tearDown`` cleared it cannot mask a missing
    production event_type.
    """

    EXPECTED_EVENT_TYPES = frozenset(
        {
            "story_started",
            "story_completed",
            "story_failed",
            "story_deferred",
            "retry_attempt",
            "escalation_triggered",
            "review_cycle",
            "retro_fired",
            "tmux_session_spawned",
            "tmux_session_completed",
            "tmux_session_crashed",
            "cost_charged",
            "budget_alert",
        }
    )

    def test_registry_contains_exactly_thirteen_production_entries(self) -> None:
        from story_automator.core.telemetry_events import Event

        production = {k for k in Event._REGISTRY if not k.startswith("_")}
        self.assertEqual(len(production), 13)
        self.assertEqual(production, self.EXPECTED_EVENT_TYPES)

    def test_unknown_event_is_not_a_registered_value(self) -> None:
        from story_automator.core.telemetry_events import Event, UnknownEvent

        for cls in Event._REGISTRY.values():
            self.assertIsNot(cls, UnknownEvent)

    def test_each_registered_class_event_type_matches_its_key(self) -> None:
        from story_automator.core.telemetry_events import Event

        # Guards against a future regression where the registry key drifts
        # from the class's own EVENT_TYPE classvar (e.g., a subclass that
        # overrides EVENT_TYPE after registration in an init hook).
        for key, cls in Event._REGISTRY.items():
            self.assertEqual(cls.EVENT_TYPE, key)
```

- [ ] **Step 2: Run the new tests (expect PASS without source change)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.RegistryCompletenessTests -v
```

Expected: all 3 tests PASS. The 13 classes from Tasks 2–14 auto-registered, `UnknownEvent` was skipped by the empty-`EVENT_TYPE` guard in `__init_subclass__`, and each class's `EVENT_TYPE` classvar matches the key it was registered under.

If `test_registry_contains_exactly_thirteen_production_entries` FAILS with a count other than 13:
- count > 13: a `_temp_*` leak from another test. Identify which test class defines a typed sentinel but forgets `_RegistryIsolationMixin`. Fix it. The completeness test's underscore filter handles `_`-prefixed keys, but a sentinel without the underscore (e.g., `temp_event` rather than `_temp_event`) would slip through.
- count < 13: a class is missing from `EXPECTED_EVENT_TYPES`, or one of Tasks 2–14 introduced a typo in its `EVENT_TYPE` classvar (e.g., `"story_starts"` instead of `"story_started"`). Compare against the design doc table.

- [ ] **Step 3: Run the full file to confirm no regressions**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: every test in the file passes — m01-m1 baseline + m01-m2 additions + 13 round-trip tests + 3 registry-completeness tests.

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): RegistryCompletenessTests for REQ-06 13-entry pin"
```

---

## Task 16: Update `__all__` to export the 13 concrete event classes

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Write the failing export-contract tests**

Append a new test class to `tests/test_telemetry_events.py`:

```python
class ConcreteEventExportContractTests(unittest.TestCase):
    """REQ-05 implication: the 13 concrete classes must be importable
    via the documented module path. ``__all__`` pins the surface so
    ``from story_automator.core.telemetry_events import *`` works as
    documented in the design doc, and so future renames are caught
    by this gate rather than at downstream call sites.
    """

    EXPECTED_NAMES = (
        "BudgetAlert",
        "CostCharged",
        "EscalationTriggered",
        "RetroFired",
        "RetryAttempt",
        "ReviewCycle",
        "StoryCompleted",
        "StoryDeferred",
        "StoryFailed",
        "StoryStarted",
        "TmuxSessionCompleted",
        "TmuxSessionCrashed",
        "TmuxSessionSpawned",
    )

    def test_all_thirteen_concrete_classes_are_in_dunder_all(self) -> None:
        from story_automator.core import telemetry_events

        for name in self.EXPECTED_NAMES:
            self.assertIn(
                name,
                telemetry_events.__all__,
                f"{name} missing from __all__",
            )

    def test_all_thirteen_concrete_classes_are_importable_top_level(self) -> None:
        # Smoke test: every name in EXPECTED_NAMES resolves to a class
        # attribute on the module (and is not None / not a function).
        from story_automator.core import telemetry_events

        for name in self.EXPECTED_NAMES:
            obj = getattr(telemetry_events, name, None)
            self.assertIsNotNone(obj, f"{name} is not defined")
            self.assertTrue(isinstance(obj, type), f"{name} is not a class")
```

- [ ] **Step 2: Run the new tests (expected behavior depends on prior-work state)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventExportContractTests -v
```

**Clean state expected output:** `test_all_thirteen_concrete_classes_are_in_dunder_all` FAILS for the 13 names (m01-m2's `__all__` only listed `Event`, `UnknownEvent`, `compact_json`, `iso_now`, `parse_event`). The companion `test_all_thirteen_concrete_classes_are_importable_top_level` test passes because the class names are already defined at module scope from Tasks 2–14 — they just aren't yet enumerated in `__all__`.

**Pre-existing-work state expected output:** both tests PASS on first run. The prior bundled commit (`feat(telemetry): 13 concrete event classes + round-trip + registry tests`) updated `__all__` alongside the class definitions, so the membership check is already satisfied. In this case **skip Step 3** (no `__all__` update needed) and proceed directly to Step 4 verification.

- [ ] **Step 3: Update `__all__`**

In `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`, find the `__all__` block near the bottom (left by m01-m2 Task 12):

```python
__all__ = [
    "Event",
    "UnknownEvent",
    "compact_json",
    "iso_now",
    "parse_event",
]
```

Replace it with the alphabetically-sorted merged list:

```python
__all__ = [
    "BudgetAlert",
    "CostCharged",
    "EscalationTriggered",
    "Event",
    "RetroFired",
    "RetryAttempt",
    "ReviewCycle",
    "StoryCompleted",
    "StoryDeferred",
    "StoryFailed",
    "StoryStarted",
    "TmuxSessionCompleted",
    "TmuxSessionCrashed",
    "TmuxSessionSpawned",
    "UnknownEvent",
    "compact_json",
    "iso_now",
    "parse_event",
]
```

Sort order: alphabetical within the entire list (the m01-m1 / m01-m2 entries also follow this convention). The 13 new class names slot in between `BudgetAlert` and `TmuxSessionSpawned` — note `Event` interleaves between `EscalationTriggered` and `RetroFired`, and `UnknownEvent` follows `TmuxSessionSpawned`.

- [ ] **Step 4: Run tests (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v
```

Expected: all tests pass, including both `ConcreteEventExportContractTests` cases.

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): export 13 concrete event classes in __all__"
```

---

## Task 17: Final quality gates (lint + format + full suite + test-count verification)

**Files:** None modified — verification only.

Note on deferred gates: the 85% coverage gate (`pytest --cov-fail-under=85`), the import-allowlist grep gate, and the module-size `wc -l` gate are all deferred to m01-m4 per the milestone definition. This task runs only the gates whose contract was established by m01-m1 / m01-m2 and continues through m01-m3: ruff lint, ruff format, and the full project unittest suite.

- [ ] **Step 1: Ruff lint**

Run:

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
```

Expected: `All checks passed!` with exit code 0.

If any violation is reported, fix it inline and commit with: `git commit --trailer "Generated-By: claude-opus-4-7" -m "refactor(telemetry): satisfy ruff lint for m01-m3 additions"`. Anticipated potential issues:
- Unused-import warnings — none expected; every name used in m01-m3 (`ClassVar`, `dataclass`, the 13 class names, `frozenset`, `Event`, `UnknownEvent`, `parse_event`) is referenced at least once.
- Line-length violations on a long class docstring — wrap in parentheses, not backslash continuations.

- [ ] **Step 2: Ruff format check**

Run:

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
```

Expected: `X files already formatted` with exit code 0.

If reformat is needed:

```bash
python -m ruff format \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py \
  tests/test_telemetry_events.py
git add -A
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(telemetry): ruff format for m01-m3 additions"
```

- [ ] **Step 3: Full project test suite**

Run:

```bash
npm run test:python
```

Expected: 0 failures across all existing test files plus `tests/test_telemetry_events.py`. The exit code from `npm` must be 0.

If a pre-existing unrelated test regresses, the most likely cause is registry leakage from a m01-m3 test (less likely than in m01-m2 because the m01-m3 tests use real production classes, not test-local sentinels). Re-audit any inner-class `@dataclass class _X(Event):` declarations introduced incidentally.

- [ ] **Step 4: Test-count verification**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events 2>&1 | tail -3
```

Expected: the final summary line reads `Ran 62 tests in <time> OK` regardless of starting state:
- **Clean-state path:** m01-m2 baseline 44 tests + 18 added by m01-m3 (13 round-trip + 3 registry + 2 export-contract) = 62.
- **Pre-existing-work path:** 60 tests already in file (44 m01-m2 + 16 from prior bundled commit `feat(telemetry): 13 concrete event classes + round-trip + registry tests`) + 2 added by Task 16 = 62.

Both paths converge on the same final count. If the actual count is **60**, Task 16 did not run (or its test addition was skipped) — re-check Task 16. If the actual count is **62 + N** for `N > 0`, an extra test class slipped in — audit recent diffs.

Per-task / per-class breakdown of the 18 tests added by m01-m3 (under the clean-state path; pre-existing-state path reuses the same 16 tests for Tasks 2–15 and adds only Task 16's 2):

| Task | New test method(s) | Test class | Tests added |
|---|---|---|---|
| 2 | `test_story_started_round_trip` + `_round_trip` helper | `ConcreteEventRoundTripTests` (new) | 1 |
| 3 | `test_story_completed_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 4 | `test_story_failed_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 5 | `test_story_deferred_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 6 | `test_retry_attempt_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 7 | `test_escalation_triggered_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 8 | `test_review_cycle_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 9 | `test_retro_fired_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 10 | `test_tmux_session_spawned_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 11 | `test_tmux_session_completed_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 12 | `test_tmux_session_crashed_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 13 | `test_cost_charged_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 14 | `test_budget_alert_round_trip` | `ConcreteEventRoundTripTests` | 1 |
| 15 | three completeness tests | `RegistryCompletenessTests` (new) | 3 |
| 16 | two export-contract tests | `ConcreteEventExportContractTests` (new) | 2 |
| **Total** | **3 new test classes** | | **18** |

If the actual `Ran N tests` count differs from 62, the most common cause is a misspelled method name (must start with `test_` for unittest's discovery to find it) or a method indented outside the class body. Inspect the file and reconcile against the table.

- [ ] **Step 5: Slice complete — no commit (verification only)**

The slice is complete when all four gates above pass. No new commit is needed for verification — the per-task commits already capture the full slice. Future slice m01-m4 layers the broader REQ-08 / REQ-09 sweep, the coverage gate, the import-allowlist gate, and the module-size gate on top of m01-m3's surface without re-touching it.

---

## Self-Review

**1. Spec coverage (REQ-05 and REQ-06 only — per `workflow.json` milestone `spec_sections`):**

| Spec REQ sub-clause | Task(s) that implement(s) it |
|---|---|
| REQ-05: `StoryStarted` with documented fields + EVENT_TYPE `story_started` | Task 2 |
| REQ-05: `StoryCompleted` with documented fields | Task 3 |
| REQ-05: `StoryFailed` with documented fields | Task 4 |
| REQ-05: `StoryDeferred` with documented fields | Task 5 |
| REQ-05: `RetryAttempt` with documented fields | Task 6 |
| REQ-05: `EscalationTriggered` with documented fields | Task 7 |
| REQ-05: `ReviewCycle` with documented fields | Task 8 |
| REQ-05: `RetroFired` with documented fields | Task 9 |
| REQ-05: `TmuxSessionSpawned` with documented fields | Task 10 |
| REQ-05: `TmuxSessionCompleted` with documented fields | Task 11 |
| REQ-05: `TmuxSessionCrashed` with documented fields | Task 12 |
| REQ-05: `CostCharged` with documented fields | Task 13 |
| REQ-05: `BudgetAlert` with documented fields | Task 14 |
| REQ-05: each EVENT_TYPE is snake_case form of class name | Tasks 2–14 (string-literal in each class declaration) + Task 15 (`test_each_registered_class_event_type_matches_its_key` cross-checks the registry key against the class's own classvar) |
| REQ-06: `Event._REGISTRY` contains exactly 13 entries after import | Task 15 (`test_registry_contains_exactly_thirteen_production_entries`) |
| REQ-06: `UnknownEvent` is NOT in `_REGISTRY` | Task 15 (`test_unknown_event_is_not_a_registered_value`) |
| REQ-05 (implied): `__all__` exports the 13 classes | Task 16 |

Every REQ-05 and REQ-06 sub-clause maps to a task. No coverage gap.

**2. Placeholder scan:** searched the plan for `TBD`, `TODO`, `fill in`, `similar to`, `XXX`. Zero matches. Every "implement..." step contains the complete code body to insert.

**3. Type consistency:**
- `EVENT_TYPE: ClassVar[str]` consistent across all 13 concrete classes (Tasks 2–14).
- Field types match the design doc table exactly: `int` for counts (`tokens_in`, `tokens_out`, `attempts`, `trigger_id`, `cycle_num`, `issues_found`, `tasks_completed`, `attempt_num`, `pid`, `exit_code`, `last_capture_chars`, `threshold_pct`, `stories_completed`), `float` for currency and durations (`duration_s`, `cost_usd`, `total_cost_usd`, `max_budget_usd`), `bool` for `blocking`, `str` for the rest. No nested dataclasses (M01 design constraint).
- The `_round_trip(self, event: Event) -> None` helper signature (Task 2) is consistent with how every subsequent test calls it (Tasks 3–14).
- `__all__` alphabetical ordering (Task 16) matches the convention from m01-m1 / m01-m2 (`compact_json` and `iso_now` and `parse_event` follow the class names because Python's sort places lowercase after uppercase).

**4. Test-count consistency:** the per-task table in Task 17 Step 4 reconciles the total (`44 + 18 = 62`). The 18 m01-m3 additions break down as 13 round-trip tests (Tasks 2–14) + 3 registry-completeness tests (Task 15) + 2 export-contract tests (Task 16) = 18. The breakdown is verified by the table at Task 17 Step 4.

**5. Cross-task dependencies:**
- Tasks 2–14 each append a single test method to the **same** `ConcreteEventRoundTripTests` class introduced in Task 2. The test class header + `_round_trip` helper appear only in Task 2; subsequent tasks only append a `def test_..._round_trip` method.
- Task 15 adds a new test class (`RegistryCompletenessTests`) that has no source-code dependency on Tasks 2–14 beyond the auto-registration that those tasks trigger via `__init_subclass__`. If Tasks 2–14 ran in any order the registry would still contain all 13 entries at Task 15's first run.
- Task 16 adds a third new test class (`ConcreteEventExportContractTests`) plus the `__all__` update. The class-name `EXPECTED_NAMES` tuple lists all 13 concrete classes by name; if Task 16 runs out of order before Tasks 2–14, the smoke test `test_all_thirteen_concrete_classes_are_importable_top_level` would FAIL because the names are not yet defined. The plan is designed for in-order execution; out-of-order execution is the executor's choice.
- Task 17 is purely verification — no source change. Its test-count assertion (62) presupposes all 16 preceding tasks landed.

**6. Out-of-scope clarity:** the slice does NOT add the broader REQ-08 sweep (parameterized variants, unicode, int-vs-float strictness), REQ-09 byte-equal sweep across arbitrary unknown event_types, the 85% coverage gate, the allowlist gate, or the module-size gate. This is stated in the header's "Slice scope" paragraph, in the File Structure table's "Out of scope" callout, and in Task 17's "Note on deferred gates" line. The `workflow.json` milestone for `m01-m3-concrete-events` corroborates this scope.

**7. Idempotency on re-run:** Tasks 2–14's `__init_subclass__` registration is idempotent under module re-import (m01-m1's identity check `existing is not cls` was tested explicitly in `EventIdempotencyTests`). Re-running the test suite (which re-imports the module via Python's caching) does not raise duplicate-EVENT_TYPE errors. The `_RegistryIsolationMixin` from m01-m1 protects every test that mutates the registry, but the 13 m01-m3 tests use the production classes directly without inner-class subclassing, so no mixin is needed in `ConcreteEventRoundTripTests` / `RegistryCompletenessTests` / `ConcreteEventExportContractTests`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-14-m01-m3-concrete-events.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Each task in this plan is self-contained (one new test, one new class, one verification, one commit) and matches the subagent-driven model well.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Per the port-guide hybrid-mode pattern, m01-m3 is **continuation of the M01 pattern** (m01-m1 established the conventions; m01-m2 wired the parsing protocol; m01-m3 is mechanical extension via the 13 concrete classes). Either execution mode works; subagent-driven preserves context isolation as the M01 plan grows.
