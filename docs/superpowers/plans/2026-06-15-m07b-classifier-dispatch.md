# M07b — Failure-triage classifier dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the pure-functional `classify(event) -> Classification` dispatch and the `classify_stream` generator on top of the M07a taxonomy foundation, with the four concrete event handlers, the 13-class behavioural matrix, the determinism gate, and the coverage / ruff / line-count / import-allowlist quality gates all passing.

**Architecture:** Extend the existing `skills/bmad-story-automator/src/story_automator/core/failure_triage.py` module (already contains `FailureClass`, `Confidence`, `Classification`, `IMPLIES_GRAPH`, `__all__` from M07a) with a single public `classify` entry point that dispatches on the concrete `Event` subclass from `core.telemetry_events`, four private `_classify_*` helpers (one per failure-shaped event), and the `classify_stream` generator. Pure-functional, no I/O, no buffering, no `iso_now`. Imports limited to `enum`, `dataclasses`, `collections.abc`, and `core.telemetry_events`. Tests live at `tests/test_failure_triage.py` (extending the M07a file, since that is the actual repo-root layout discovered by `npm run test:python`).

**Tech Stack:** Python 3.11+, stdlib only (`enum`, `dataclasses`, `collections.abc`), `unittest.TestCase` for tests, `ruff` for lint/format, stdlib `coverage` for the coverage gate.

**Scope (M07b only):** Covers spec REQ-06 (`classify` entry point — pure, no I/O, no raise), REQ-07 (concrete-type dispatch + non-failure-event UNKNOWN return), REQ-08 (`_classify_story_failed` six substring rules + UNKNOWN), REQ-09 (`_classify_tmux_crash` CRASH + conditional NETWORK_ERROR), REQ-10 (`_classify_story_deferred` GATE_DEFER + REPEATED_RETRY/PLATEAU), REQ-11 (`_classify_escalation` REVIEW_REJECTED + POLICY_VIOLATION), REQ-12 (`classify_stream` generator), REQ-13 (import-allowlist), REQ-14 (≥13 behavioural tests + stream round-trip), REQ-15 (assert on primary/implies/confidence; no file I/O; <2s aggregate), and the **coverage --fail-under=85**, **determinism**, and **line-count ≤500** quality gates. The taxonomy / ruff / placeholder-token / future-annotations / PEP-604 / LF-line-ending gates already pass from M07a and must continue to pass.

**Spec-vs-codebase field-name reconciliation** (carried over from the M07a plan's gap log — these are M07b's responsibility to resolve):

| Spec requirement | Spec field name | Actual M01 dataclass field | Resolution |
|---|---|---|---|
| REQ-08 `_classify_story_failed` | `error_kind` on `StoryFailed` | `error_class` | Classifier inspects both `event.reason` and `event.error_class` via a lower-cased concatenation. `getattr(event, "error_kind", "")` is also concatenated so an injected attribute (test-only) still works. |
| REQ-09 `_classify_tmux_crash` | `exit_signal` on `TmuxSessionCrashed` | only `exit_code`, `last_capture_chars` | Classifier reads `getattr(event, "exit_signal", "")`. Field is absent on the canonical M01 dataclass, so default CRASH/HIGH with no NETWORK_ERROR implies. Tests use `setattr` to inject the spec field on the otherwise-mutable M01 dataclass (no `frozen=True`, no `slots=True`). |
| REQ-10 `_classify_story_deferred` | `attempt_count` on `StoryDeferred` | `tasks_completed` | Classifier reads `getattr(event, "attempt_count", 0)`. Tests `setattr` it when exercising the `>3` branch. The `reason` substring branch ("plateau") uses the real `reason` field. |
| REQ-11 `_classify_escalation` | `trigger: str` on `EscalationTriggered` | `trigger_id: int`, `severity`, `message` | Classifier reads `getattr(event, "trigger", "")`. Tests `setattr` the spec field. Default branch returns REVIEW_REJECTED/MEDIUM without needing the field. |

These mismatches are **runtime-defensive only** — the classifier degrades gracefully when the spec field is missing (returning the documented default rather than raising). This is the path of lowest behavioural drift: the M07b module faithfully implements the spec's named-field logic, and the M01 schema is left untouched. A future milestone may either add the missing fields to M01 or rewrite the spec to match the existing names; either change is mechanical against the current implementation.

**Acknowledged spec-level fuzziness — NOT fixed in M07b** (locked behind tests, surfaced for the operator):
- REQ-08 substring matching is non-word-bounded, so `"latest"` matches the `"test"` rule and would classify as `TEST_FAILURE`. This is the spec's chosen behaviour ("map substrings deterministically") and `re` is intentionally not added to the import allowlist by M07a, so word-boundary tightening would require an allowlist change. M07b ships substring matching verbatim and pins the behaviour with a regression test so future tightening is a deliberate, breaking change rather than a silent one.
- REQ-08 lists six substring rules in a fixed declaration order. The plan locks this order as the dispatch precedence (a test asserts `"timeout policy"` → `TIMEOUT`). This is an implementation choice the spec does not literally mandate but is the only deterministic reading; the test is named so a future spec amendment that re-orders the rules can find and update it.

---

### Task 1: Pre-flight — confirm green M07a baseline

**Files:** (verification only — no edits)

- [ ] **Step 1: Run the existing M07a test suite to confirm baseline**

Run (from repo root, git-bash or WSL):
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: `OK` — every M07a test (`ModuleImportTests`, `FailureClassTests`, `ConfidenceTests`, `ClassificationDataclassTests`, `ImpliesGraphTests`, `TaxonomyCompletenessGateTests`, `ImportAndSizeDisciplineTests`) passes. If any failure or error appears, stop and surface it before continuing — M07b builds on this surface.

- [ ] **Step 2: Confirm `wc -l` baseline on the module**

Run:
```
wc -l skills/bmad-story-automator/src/story_automator/core/failure_triage.py
```
Expected: `112 skills/bmad-story-automator/src/story_automator/core/failure_triage.py` (or close to it). Budget remaining to the 500-LOC cap: ~388 lines. The M07b additions (dispatch + 4 helpers + stream generator + 2 new imports) should consume roughly 100–130 lines of source — well under budget.

- [ ] **Step 3: Confirm ruff is clean on the M07a baseline**

Run:
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
```
Expected: both report `All checks passed!` / `2 files already formatted` (or equivalent zero-diff). If a diff appears, stop and fix the M07a baseline before adding M07b code — do not paper over baseline drift with new commits.

No commit at this task. Verification only.

---

### Task 2: Failing test for `classify` dispatch skeleton (REQ-06, REQ-07 non-failure branch)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing test class**

Append at the end of `tests/test_failure_triage.py` (after the existing `ImportAndSizeDisciplineTests`):

```python


class ClassifyDispatchSkeletonTests(unittest.TestCase):
    def test_classify_is_callable(self) -> None:
        from story_automator.core.failure_triage import classify

        self.assertTrue(callable(classify))

    def test_classify_returns_unknown_for_non_failure_event(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            Confidence,
            FailureClass,
            classify,
        )
        from story_automator.core.telemetry_events import StoryStarted

        event = StoryStarted(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            agent="dev",
            model="claude-opus-4-7",
            complexity="medium",
        )
        result = classify(event)
        self.assertIsInstance(result, Classification)
        self.assertEqual(result.primary, FailureClass.UNKNOWN)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.LOW)
        self.assertEqual(result.reason, "non_failure_event")
        self.assertIsNone(result.event_id)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyDispatchSkeletonTests -v
```
Expected: 2 failures — `ImportError: cannot import name 'classify' from 'story_automator.core.failure_triage'`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add failing classify dispatch skeleton tests (REQ-06)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 3: Implement `classify` skeleton — non-failure-event UNKNOWN branch (REQ-06, REQ-07 fallback)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Update the module imports**

Replace the existing import block (currently `from dataclasses import dataclass` + `import enum` after `from __future__ import annotations`) with the M07b import block. The final file must read, in order: future-import, stdlib imports grouped alphabetically by module name (ruff isort `I001` default), then the local import. Edit the file so the import region is exactly:

```python
from __future__ import annotations

from collections.abc import Iterable, Iterator  # noqa: F401  # used in stringified annotations only under `from __future__ import annotations`
from dataclasses import dataclass
import enum

from story_automator.core.telemetry_events import (
    EscalationTriggered,
    Event,
    StoryDeferred,
    StoryFailed,
    TmuxSessionCrashed,
)
```

(`Iterable`, `Iterator`, and the five `telemetry_events` names are imported up-front even though some are first used in later tasks — keeping imports together avoids re-formatting in later tasks. The import-allowlist gate from M07a already permits `collections.abc` via the `collections` allowlist root and the local `story_automator.core.*` allowlist prefix; no test change is required.

The narrowly-scoped `# noqa: F401` on the `collections.abc` line is load-bearing: under `from __future__ import annotations`, both `Iterable` and `Iterator` exist purely as stringified annotations on `classify_stream` (Task 13), so ruff's F401 may flag them as unused depending on ruff version / target-version detection. The `# noqa` makes the intent explicit — these names ARE used, just at type-check time rather than at runtime. Do not generalise the noqa or add it to other imports.)

- [ ] **Step 2: Append the dispatch skeleton at the end of the module**

Append to the module (after the existing `__all__` block — the `__all__` will be updated in Task 11 to include the new public names):

```python


def classify(event: Event) -> Classification:
    """Classify a single telemetry event into a ``Classification`` verdict.

    Pure-functional: no I/O, no clock reads, no allocations beyond the
    returned ``Classification`` and the implies tuple. Never raises on a
    well-formed concrete event subclass shipped in M01 — unknown shapes
    return the ``UNKNOWN`` sentinel with ``LOW`` confidence rather than
    propagating an exception (REQ-06).

    Dispatch order matches the spec REQ-07 list: ``StoryFailed`` →
    ``_classify_story_failed``, ``StoryDeferred`` →
    ``_classify_story_deferred``, ``TmuxSessionCrashed`` →
    ``_classify_tmux_crash``, ``EscalationTriggered`` →
    ``_classify_escalation``. Every other event subtype — including
    ``UnknownEvent`` and the success-shaped events — short-circuits to
    the ``non_failure_event`` UNKNOWN verdict.
    """
    event_id = getattr(event, "event_id", None)
    if isinstance(event, StoryFailed):
        return _classify_story_failed(event)
    if isinstance(event, StoryDeferred):
        return _classify_story_deferred(event)
    if isinstance(event, TmuxSessionCrashed):
        return _classify_tmux_crash(event)
    if isinstance(event, EscalationTriggered):
        return _classify_escalation(event)
    return Classification(
        primary=FailureClass.UNKNOWN,
        implies=(),
        confidence=Confidence.LOW,
        reason="non_failure_event",
        event_id=event_id,
    )


def _classify_story_failed(event: StoryFailed) -> Classification:
    raise NotImplementedError  # implemented in Task 5


def _classify_story_deferred(event: StoryDeferred) -> Classification:
    raise NotImplementedError  # implemented in Task 9


def _classify_tmux_crash(event: TmuxSessionCrashed) -> Classification:
    raise NotImplementedError  # implemented in Task 7


def _classify_escalation(event: EscalationTriggered) -> Classification:
    raise NotImplementedError  # implemented in Task 11
```

The four `_classify_*` helpers are introduced here as `NotImplementedError` stubs so the `classify` dispatch references resolve at module-import time. Each subsequent implementation task replaces one stub body. The skeleton ships with a working non-failure branch which is what the Task 2 tests assert.

(Note: the `NotImplementedError` stub bodies will be replaced in Tasks 5, 7, 9, 11 — they exist transiently. If you are running the M07b tasks back-to-back this is fine; if you pause between tasks, the stubs do not break any test until that helper is exercised, which only happens in the matching Task 4/6/8/10 failing-test step.)

- [ ] **Step 3: Run the Task 2 tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyDispatchSkeletonTests -v
```
Expected: both tests pass.

- [ ] **Step 4: Run the full M07a test surface to verify no regression**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: every previously-green M07a test continues to pass; the 2 new dispatch-skeleton tests also pass. Total green test count = (M07a tests) + 2.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): add classify dispatch skeleton + helper stubs (REQ-06)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 4: Failing tests for `_classify_story_failed` (REQ-08)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append at the end of `tests/test_failure_triage.py`:

```python


class ClassifyStoryFailedTests(unittest.TestCase):
    def _make_event(self, *, reason: str, error_class: str = "") -> object:
        from story_automator.core.telemetry_events import StoryFailed

        return StoryFailed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            error_class=error_class,
            reason=reason,
            attempts=1,
            final_session="sess",
        )

    def test_timeout_substring_returns_timeout_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="job timeout after 600s"))
        self.assertEqual(result.primary, FailureClass.TIMEOUT)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_policy_substring_returns_policy_violation_high_implies_review(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="policy refusal: PII"))
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_guardrail_substring_returns_policy_violation(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="guardrail tripped on output"))
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)

    def test_test_substring_returns_test_failure_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="unit test assertion failed"))
        self.assertEqual(result.primary, FailureClass.TEST_FAILURE)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_pytest_substring_returns_test_failure(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="pytest exit code 1"))
        self.assertEqual(result.primary, FailureClass.TEST_FAILURE)

    def test_parse_substring_returns_parse_error_medium(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="failed to parse model output"))
        self.assertEqual(result.primary, FailureClass.PARSE_ERROR)
        self.assertEqual(result.confidence, Confidence.MEDIUM)

    def test_json_substring_returns_parse_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="invalid json payload"))
        self.assertEqual(result.primary, FailureClass.PARSE_ERROR)

    def test_refused_substring_returns_agent_refused_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="agent refused to write code"))
        self.assertEqual(result.primary, FailureClass.AGENT_REFUSED)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_refusal_substring_returns_agent_refused(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="model refusal at turn 3"))
        self.assertEqual(result.primary, FailureClass.AGENT_REFUSED)

    def test_budget_substring_returns_budget_exceeded_implies_gate_defer(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="budget cap hit at 110%"))
        self.assertEqual(result.primary, FailureClass.BUDGET_EXCEEDED)
        self.assertIn(FailureClass.GATE_DEFER, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_cost_substring_returns_budget_exceeded(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        result = classify(self._make_event(reason="cost exceeded epic cap"))
        self.assertEqual(result.primary, FailureClass.BUDGET_EXCEEDED)
        self.assertIn(FailureClass.GATE_DEFER, result.implies)

    def test_unmatched_reason_returns_unknown_low(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="ambient disk pressure"))
        self.assertEqual(result.primary, FailureClass.UNKNOWN)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.LOW)

    def test_error_class_field_is_inspected(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        # `reason` is empty; the signal lives on the `error_class` M01
        # field (spec said `error_kind` but M01 names it `error_class`).
        result = classify(self._make_event(reason="", error_class="timeout"))
        self.assertEqual(result.primary, FailureClass.TIMEOUT)

    def test_implementation_chooses_timeout_when_both_substrings_present(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        # Spec REQ-08 LISTS its substring rules in declaration order but
        # does not literally mandate that order as runtime precedence
        # when multiple substrings co-occur. This test pins the M07b
        # implementation's choice (rules applied in REQ-08 declaration
        # order — timeout first) so a future spec amendment that
        # re-orders the rules has a known regression test to update.
        # Do not delete this test without updating the spec preamble.
        result = classify(self._make_event(reason="timeout policy"))
        self.assertEqual(result.primary, FailureClass.TIMEOUT)

    def test_error_kind_injected_attribute_is_inspected(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        # Spec REQ-08 names the second inspected field `error_kind`;
        # M01 ships `error_class`. The classifier defensively reads
        # BOTH names so the spec-named field still works when injected
        # by a downstream caller (or by a future M01 schema update).
        # This test locks in the `error_kind` injection path so it
        # cannot be silently removed and so the coverage gate sees it.
        event = self._make_event(reason="", error_class="")
        event.error_kind = "budget"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.BUDGET_EXCEEDED)

    def test_substring_match_is_not_word_bounded_pinned_behaviour(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        # Spec REQ-08 specifies *substring* matching, not word-boundary
        # matching. As a documented consequence, `"latest"` matches the
        # `"test"` rule and classifies as TEST_FAILURE. This is the
        # spec's chosen behaviour; tightening to word boundaries would
        # require adding `re` to the M07a import allowlist. This test
        # pins the substring behaviour so the spec change is deliberate.
        result = classify(self._make_event(reason="latest model build"))
        self.assertEqual(result.primary, FailureClass.TEST_FAILURE)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyStoryFailedTests -v
```
Expected: 16 errors — `NotImplementedError` raised from the `_classify_story_failed` stub introduced in Task 3. (Test count: timeout, policy, guardrail, test, pytest, parse, json, refused, refusal, budget, cost, unmatched, error_class_field, precedence-implementation-choice, error_kind-injection, substring-not-word-bounded = 16.)

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add failing _classify_story_failed cases (REQ-08)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 5: Implement `_classify_story_failed` (REQ-08)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Replace the `_classify_story_failed` stub**

Edit the module: replace the existing stub body

```python
def _classify_story_failed(event: StoryFailed) -> Classification:
    raise NotImplementedError  # implemented in Task 5
```

with the full implementation:

```python
def _classify_story_failed(event: StoryFailed) -> Classification:
    """Map a ``StoryFailed`` event onto a ``Classification`` by substring.

    Inspects the lowercase concatenation of ``reason`` + ``error_class``
    (spec REQ-08 names the second field ``error_kind``; M01 defines it
    as ``error_class``, so both names are honoured via a defensive
    ``getattr`` so injected test attributes also flow through). Rules
    are applied in spec-declaration order — ``timeout`` wins over
    ``policy``, ``policy`` wins over ``test``, etc. — to keep the
    dispatch deterministic when a reason contains multiple substrings.
    """
    event_id = getattr(event, "event_id", None)
    haystack = " ".join(
        (
            event.reason or "",
            getattr(event, "error_kind", "") or "",
            event.error_class or "",
        )
    ).lower()
    if "timeout" in haystack:
        return Classification(
            primary=FailureClass.TIMEOUT,
            implies=(),
            confidence=Confidence.HIGH,
            reason="timeout_substring",
            event_id=event_id,
        )
    if "policy" in haystack or "guardrail" in haystack:
        return Classification(
            primary=FailureClass.POLICY_VIOLATION,
            implies=(FailureClass.REVIEW_REJECTED,),
            confidence=Confidence.HIGH,
            reason="policy_or_guardrail_substring",
            event_id=event_id,
        )
    if "test" in haystack or "pytest" in haystack:
        return Classification(
            primary=FailureClass.TEST_FAILURE,
            implies=(),
            confidence=Confidence.HIGH,
            reason="test_substring",
            event_id=event_id,
        )
    if "parse" in haystack or "json" in haystack:
        return Classification(
            primary=FailureClass.PARSE_ERROR,
            implies=(),
            confidence=Confidence.MEDIUM,
            reason="parse_or_json_substring",
            event_id=event_id,
        )
    if "refused" in haystack or "refusal" in haystack:
        return Classification(
            primary=FailureClass.AGENT_REFUSED,
            implies=(),
            confidence=Confidence.HIGH,
            reason="refusal_substring",
            event_id=event_id,
        )
    if "budget" in haystack or "cost" in haystack:
        return Classification(
            primary=FailureClass.BUDGET_EXCEEDED,
            implies=(FailureClass.GATE_DEFER,),
            confidence=Confidence.HIGH,
            reason="budget_or_cost_substring",
            event_id=event_id,
        )
    return Classification(
        primary=FailureClass.UNKNOWN,
        implies=(),
        confidence=Confidence.LOW,
        reason="story_failed_unmatched",
        event_id=event_id,
    )
```

- [ ] **Step 2: Run the Task 4 tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyStoryFailedTests -v
```
Expected: all 16 tests pass.

- [ ] **Step 3: Run the full failure-triage suite to verify no regression**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: every test (M07a + Task 2 dispatch skeleton + Task 4 story-failed) passes.

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): implement _classify_story_failed substring rules (REQ-08)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 6: Failing tests for `_classify_tmux_crash` (REQ-09)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append at the end of `tests/test_failure_triage.py`:

```python


class ClassifyTmuxCrashTests(unittest.TestCase):
    def _make_event(self, *, exit_code: int = 137) -> object:
        from story_automator.core.telemetry_events import TmuxSessionCrashed

        return TmuxSessionCrashed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            session_name="sess",
            story_key="S1",
            exit_code=exit_code,
            last_capture_chars=0,
        )

    def test_plain_crash_returns_crash_high_no_implies(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event())
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_sigpipe_exit_signal_implies_network_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        # Spec REQ-09 references an ``exit_signal`` field; M01 does not
        # define one. The M01 dataclass is not frozen and not slotted,
        # so injecting the spec field via setattr is sound.
        event.exit_signal = "SIGPIPE"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertIn(FailureClass.NETWORK_ERROR, result.implies)

    def test_sighup_exit_signal_implies_network_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.exit_signal = "SIGHUP"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertIn(FailureClass.NETWORK_ERROR, result.implies)

    def test_network_substring_in_exit_signal_implies_network_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.exit_signal = "network-unreachable"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertIn(FailureClass.NETWORK_ERROR, result.implies)

    def test_unrelated_exit_signal_does_not_imply_network_error(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.exit_signal = "SIGTERM"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertNotIn(FailureClass.NETWORK_ERROR, result.implies)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyTmuxCrashTests -v
```
Expected: 5 errors — `NotImplementedError` from the stub.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add failing _classify_tmux_crash cases (REQ-09)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 7: Implement `_classify_tmux_crash` (REQ-09)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Replace the `_classify_tmux_crash` stub**

Replace

```python
def _classify_tmux_crash(event: TmuxSessionCrashed) -> Classification:
    raise NotImplementedError  # implemented in Task 7
```

with:

```python
def _classify_tmux_crash(event: TmuxSessionCrashed) -> Classification:
    """Map a ``TmuxSessionCrashed`` event onto a ``CRASH`` classification.

    Always returns ``CRASH`` / ``HIGH``. If the event carries an
    ``exit_signal`` hint that matches SIGPIPE, SIGHUP, or contains the
    substring ``network``, the result additionally implies
    ``NETWORK_ERROR``. The M01 dataclass does not define ``exit_signal``
    today (spec REQ-09 names it but M01 ships ``exit_code`` and
    ``last_capture_chars`` only), so ``getattr`` with an empty-string
    default ensures the default branch is taken on canonical M01 events.
    """
    event_id = getattr(event, "event_id", None)
    exit_signal = getattr(event, "exit_signal", "") or ""
    implies: tuple[FailureClass, ...] = ()
    if exit_signal in ("SIGPIPE", "SIGHUP") or "network" in exit_signal:
        implies = (FailureClass.NETWORK_ERROR,)
    return Classification(
        primary=FailureClass.CRASH,
        implies=implies,
        confidence=Confidence.HIGH,
        reason="tmux_crash",
        event_id=event_id,
    )
```

- [ ] **Step 2: Run the Task 6 tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyTmuxCrashTests -v
```
Expected: all 5 tests pass.

- [ ] **Step 3: Run the full failure-triage suite**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): implement _classify_tmux_crash with conditional NETWORK_ERROR (REQ-09)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 8: Failing tests for `_classify_story_deferred` (REQ-10)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append:

```python


class ClassifyStoryDeferredTests(unittest.TestCase):
    def _make_event(
        self, *, reason: str = "complexity cap", tasks_completed: int = 2
    ) -> object:
        from story_automator.core.telemetry_events import StoryDeferred

        return StoryDeferred(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            reason=reason,
            tasks_completed=tasks_completed,
        )

    def test_default_returns_gate_defer_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event())
        self.assertEqual(result.primary, FailureClass.GATE_DEFER)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_plateau_substring_returns_repeated_retry_implies_plateau(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event(reason="plateau detected after 3 cycles"))
        self.assertEqual(result.primary, FailureClass.REPEATED_RETRY)
        self.assertIn(FailureClass.PLATEAU, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_attempt_count_over_three_returns_repeated_retry_implies_plateau(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        # Spec REQ-10 names ``attempt_count`` but M01 ships
        # ``tasks_completed`` only. Inject the spec field via setattr.
        event.attempt_count = 4  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.REPEATED_RETRY)
        self.assertIn(FailureClass.PLATEAU, result.implies)

    def test_attempt_count_three_does_not_trip_plateau_branch(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.attempt_count = 3  # type: ignore[attr-defined]
        result = classify(event)
        # Spec REQ-10 says "exceeds 3" — 3 itself stays in the default branch.
        self.assertEqual(result.primary, FailureClass.GATE_DEFER)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyStoryDeferredTests -v
```
Expected: 4 errors — `NotImplementedError` from the stub.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add failing _classify_story_deferred cases (REQ-10)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 9: Implement `_classify_story_deferred` (REQ-10)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Replace the `_classify_story_deferred` stub**

Replace

```python
def _classify_story_deferred(event: StoryDeferred) -> Classification:
    raise NotImplementedError  # implemented in Task 7
```

(note: the Task 3 stub comment may say "Task 7"; that was the original ordering placeholder — the body replacement is the same regardless) with:

```python
def _classify_story_deferred(event: StoryDeferred) -> Classification:
    """Map a ``StoryDeferred`` event onto either GATE_DEFER or REPEATED_RETRY.

    Spec REQ-10 names an optional ``attempt_count`` field that M01 does
    not currently emit (M01 ships ``tasks_completed``); ``getattr`` with
    a 0 default keeps the canonical M01 event on the default branch.
    The plateau check on ``reason`` runs against the lowercased value.
    """
    event_id = getattr(event, "event_id", None)
    reason_lower = (event.reason or "").lower()
    attempt_count = getattr(event, "attempt_count", 0)
    if "plateau" in reason_lower or attempt_count > 3:
        return Classification(
            primary=FailureClass.REPEATED_RETRY,
            implies=(FailureClass.PLATEAU,),
            confidence=Confidence.HIGH,
            reason="plateau_or_high_attempts",
            event_id=event_id,
        )
    return Classification(
        primary=FailureClass.GATE_DEFER,
        implies=(),
        confidence=Confidence.HIGH,
        reason="story_deferred",
        event_id=event_id,
    )
```

- [ ] **Step 2: Run the Task 8 tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyStoryDeferredTests -v
```
Expected: all 4 tests pass.

- [ ] **Step 3: Run the full failure-triage suite**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): implement _classify_story_deferred plateau branch (REQ-10)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 10: Failing tests for `_classify_escalation` (REQ-11)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append:

```python


class ClassifyEscalationTests(unittest.TestCase):
    def _make_event(self) -> object:
        from story_automator.core.telemetry_events import EscalationTriggered

        return EscalationTriggered(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            trigger_id=1,
            severity="warn",
            message="manual review requested",
        )

    def test_default_returns_review_rejected_medium(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._make_event())
        self.assertEqual(result.primary, FailureClass.REVIEW_REJECTED)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.MEDIUM)

    def test_policy_trigger_prefix_upgrades_to_policy_violation_high(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        event = self._make_event()
        # Spec REQ-11 names a ``trigger`` field; M01 has ``trigger_id``
        # (int) and ``severity``/``message`` (strings) only. Inject the
        # spec field on the otherwise-mutable dataclass instance.
        event.trigger = "policy:pii_leak"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_non_policy_trigger_stays_review_rejected(self) -> None:
        from story_automator.core.failure_triage import FailureClass, classify

        event = self._make_event()
        event.trigger = "review:manual"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.REVIEW_REJECTED)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyEscalationTests -v
```
Expected: 3 errors — `NotImplementedError` from the stub.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add failing _classify_escalation cases (REQ-11)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 11: Implement `_classify_escalation` + update `__all__` (REQ-11)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Replace the `_classify_escalation` stub**

Replace

```python
def _classify_escalation(event: EscalationTriggered) -> Classification:
    raise NotImplementedError  # implemented in Task 11
```

with:

```python
def _classify_escalation(event: EscalationTriggered) -> Classification:
    """Map an ``EscalationTriggered`` event onto a classification.

    Default is ``REVIEW_REJECTED`` / ``MEDIUM`` — most escalations are
    routed to a human reviewer. When the ``trigger`` field (spec REQ-11
    names it; M01 ships ``trigger_id`` / ``severity`` / ``message`` only)
    begins with the ``policy:`` namespace prefix, upgrade the verdict to
    ``POLICY_VIOLATION`` / ``HIGH`` with ``REVIEW_REJECTED`` implied so
    downstream M08 retry policy can refuse to retry policy escalations.
    """
    event_id = getattr(event, "event_id", None)
    trigger = getattr(event, "trigger", "") or ""
    if trigger.startswith("policy:"):
        return Classification(
            primary=FailureClass.POLICY_VIOLATION,
            implies=(FailureClass.REVIEW_REJECTED,),
            confidence=Confidence.HIGH,
            reason="policy_trigger_prefix",
            event_id=event_id,
        )
    return Classification(
        primary=FailureClass.REVIEW_REJECTED,
        implies=(),
        confidence=Confidence.MEDIUM,
        reason="escalation_default",
        event_id=event_id,
    )
```

- [ ] **Step 2: Update `__all__` to expose `classify` (NOT `classify_stream` yet)**

Find the existing `__all__` block (added in M07a):

```python
__all__ = [
    "Classification",
    "Confidence",
    "FailureClass",
    "IMPLIES_GRAPH",
]
```

Replace it with the M07b-Task-11 export set (just `classify` added; `classify_stream` is deferred to Task 13 so `__all__` and the symbol always land in the same commit — strict TDD discipline):

```python
__all__ = [
    "Classification",
    "Confidence",
    "FailureClass",
    "IMPLIES_GRAPH",
    "classify",
]
```

- [ ] **Step 3: Update the M07a `test_all_export_list` to reflect the Task-11 export set**

Edit `tests/test_failure_triage.py` — locate the existing `test_all_export_list` inside `ImportAndSizeDisciplineTests`:

```python
    def test_all_export_list(self) -> None:
        from story_automator.core import failure_triage

        self.assertEqual(
            set(failure_triage.__all__),
            {"Classification", "Confidence", "FailureClass", "IMPLIES_GRAPH"},
        )
```

Replace the assertion's expected set so it matches the Task-11 (post-`classify`, pre-`classify_stream`) export contract:

```python
    def test_all_export_list(self) -> None:
        from story_automator.core import failure_triage

        self.assertEqual(
            set(failure_triage.__all__),
            {
                "Classification",
                "Confidence",
                "FailureClass",
                "IMPLIES_GRAPH",
                "classify",
            },
        )
```

(Task 13 will mutate both the `__all__` block AND this test in the same commit to add `classify_stream`. Splitting the mutation across the two tasks keeps every intermediate commit's `__all__` truthful — no promise-but-no-symbol gap.)

- [ ] **Step 4: Run the Task 10 tests + the export-list test**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyEscalationTests tests.test_failure_triage.ImportAndSizeDisciplineTests.test_all_export_list -v
```
Expected: all 4 tests pass.

- [ ] **Step 5: Run the full failure-triage suite to verify no regression**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: all tests pass except any test that exercises `classify_stream` (none yet — that's Task 12).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
git commit -m "feat(failure-triage): implement _classify_escalation + export classify (REQ-11)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 12: Failing test for `classify_stream` (REQ-12)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append at the end of the file:

```python


class ClassifyStreamTests(unittest.TestCase):
    def test_classify_stream_is_a_generator_function(self) -> None:
        import inspect

        from story_automator.core.failure_triage import classify_stream

        self.assertTrue(inspect.isgeneratorfunction(classify_stream))

    def test_classify_stream_yields_one_classification_per_event(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            FailureClass,
            classify_stream,
        )
        from story_automator.core.telemetry_events import (
            StoryDeferred,
            StoryFailed,
            StoryStarted,
            TmuxSessionCrashed,
        )

        events = [
            StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="run-1",
                epic="E1",
                story_key="S1",
                agent="dev",
                model="claude-opus-4-7",
                complexity="medium",
            ),
            StoryFailed(
                timestamp="2026-01-01T00:00:00Z",
                run_id="run-1",
                epic="E1",
                story_key="S2",
                error_class="",
                reason="timeout 600s",
                attempts=1,
                final_session="sess",
            ),
            StoryDeferred(
                timestamp="2026-01-01T00:00:00Z",
                run_id="run-1",
                epic="E1",
                story_key="S3",
                reason="plateau",
                tasks_completed=1,
            ),
            TmuxSessionCrashed(
                timestamp="2026-01-01T00:00:00Z",
                run_id="run-1",
                session_name="sess",
                story_key="S4",
                exit_code=137,
                last_capture_chars=0,
            ),
        ]
        results = list(classify_stream(events))
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertIsInstance(r, Classification)
        self.assertEqual(results[0].primary, FailureClass.UNKNOWN)
        self.assertEqual(results[1].primary, FailureClass.TIMEOUT)
        self.assertEqual(results[2].primary, FailureClass.REPEATED_RETRY)
        self.assertEqual(results[3].primary, FailureClass.CRASH)

    def test_classify_stream_does_not_buffer_lazy_iteration(self) -> None:
        from story_automator.core.failure_triage import classify_stream
        from story_automator.core.telemetry_events import StoryStarted

        consumed: list[int] = []

        def source() -> object:
            for i in range(3):
                consumed.append(i)
                yield StoryStarted(
                    timestamp="2026-01-01T00:00:00Z",
                    run_id="run-1",
                    epic="E1",
                    story_key=f"S{i}",
                    agent="dev",
                    model="claude-opus-4-7",
                    complexity="medium",
                )

        gen = classify_stream(source())
        # Nothing consumed yet.
        self.assertEqual(consumed, [])
        next(gen)
        self.assertEqual(consumed, [0])
        next(gen)
        self.assertEqual(consumed, [0, 1])

    def test_classify_stream_propagates_iterator_exception(self) -> None:
        from story_automator.core.failure_triage import classify_stream

        class Boom(RuntimeError):
            pass

        def source() -> object:
            yield from ()
            raise Boom("source exploded")

        gen = classify_stream(source())
        with self.assertRaises(Boom):
            list(gen)
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyStreamTests -v
```
Expected: 4 errors — `ImportError: cannot import name 'classify_stream' from 'story_automator.core.failure_triage'`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add failing classify_stream generator tests (REQ-12)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 13: Implement `classify_stream` generator (REQ-12)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Append the generator function**

Append in the module, immediately before the `__all__` block (so the symbol is defined before the export-list is read):

```python


def classify_stream(events: Iterable[Event]) -> Iterator[Classification]:
    """Stream-classify a sequence of events.

    Thin generator over ``classify`` — does not buffer, does not consult
    a clock, and does not catch the underlying iterator's exceptions
    (they propagate verbatim per REQ-12). Consumers compose this with
    ``TelemetryReader.iter_events`` (M02) to drive batch triage without
    materialising the entire stream.
    """
    for event in events:
        yield classify(event)
```

- [ ] **Step 2: Extend `__all__` with `classify_stream`**

Edit the `__all__` block at the end of the module to add `"classify_stream"`:

```python
__all__ = [
    "Classification",
    "Confidence",
    "FailureClass",
    "IMPLIES_GRAPH",
    "classify",
    "classify_stream",
]
```

- [ ] **Step 3: Update the M07a `test_all_export_list` to add `classify_stream`**

Edit `tests/test_failure_triage.py` — locate the M07b-Task-11 export-list test:

```python
    def test_all_export_list(self) -> None:
        from story_automator.core import failure_triage

        self.assertEqual(
            set(failure_triage.__all__),
            {
                "Classification",
                "Confidence",
                "FailureClass",
                "IMPLIES_GRAPH",
                "classify",
            },
        )
```

Replace the expected set to include `classify_stream`:

```python
    def test_all_export_list(self) -> None:
        from story_automator.core import failure_triage

        self.assertEqual(
            set(failure_triage.__all__),
            {
                "Classification",
                "Confidence",
                "FailureClass",
                "IMPLIES_GRAPH",
                "classify",
                "classify_stream",
            },
        )
```

- [ ] **Step 4: Run the Task 12 tests + the updated export-list test**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassifyStreamTests tests.test_failure_triage.ImportAndSizeDisciplineTests.test_all_export_list -v
```
Expected: all 5 tests pass (4 stream tests + 1 updated export-list test).

- [ ] **Step 5: Run the full failure-triage suite**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
git commit -m "feat(failure-triage): add classify_stream generator + export (REQ-12)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 14: 13-class behavioural matrix + determinism gate (REQ-14, REQ-15, determinism quality gate)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the 13-class matrix + determinism gate tests**

Append at the end of the file:

```python


class ThirteenClassBehaviouralMatrixTests(unittest.TestCase):
    """One test per ``FailureClass`` member — REQ-14 acceptance matrix.

    Each test asserts on ``primary``, on the membership of the expected
    entries in ``implies``, and on ``confidence`` (REQ-15). No I/O, no
    ``compact_json`` call, no clock read.
    """

    def _story_failed(self, *, reason: str) -> object:
        from story_automator.core.telemetry_events import StoryFailed

        return StoryFailed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            error_class="",
            reason=reason,
            attempts=1,
            final_session="sess",
        )

    def _story_deferred(self, *, reason: str = "complexity cap") -> object:
        from story_automator.core.telemetry_events import StoryDeferred

        return StoryDeferred(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            reason=reason,
            tasks_completed=1,
        )

    def _tmux_crashed(self) -> object:
        from story_automator.core.telemetry_events import TmuxSessionCrashed

        return TmuxSessionCrashed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            session_name="sess",
            story_key="S1",
            exit_code=137,
            last_capture_chars=0,
        )

    def _escalation(self) -> object:
        from story_automator.core.telemetry_events import EscalationTriggered

        return EscalationTriggered(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            trigger_id=1,
            severity="warn",
            message="m",
        )

    def test_crash_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._tmux_crashed())
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertEqual(result.implies, ())  # REQ-15: implies membership asserted
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_timeout_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="timeout 600s"))
        self.assertEqual(result.primary, FailureClass.TIMEOUT)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_policy_violation_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="policy refusal"))
        self.assertEqual(result.primary, FailureClass.POLICY_VIOLATION)
        self.assertIn(FailureClass.REVIEW_REJECTED, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_review_rejected_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._escalation())
        self.assertEqual(result.primary, FailureClass.REVIEW_REJECTED)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.MEDIUM)

    def test_test_failure_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="pytest failure"))
        self.assertEqual(result.primary, FailureClass.TEST_FAILURE)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_budget_exceeded_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="budget cap"))
        self.assertEqual(result.primary, FailureClass.BUDGET_EXCEEDED)
        self.assertIn(FailureClass.GATE_DEFER, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_parse_error_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="parse error"))
        self.assertEqual(result.primary, FailureClass.PARSE_ERROR)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.MEDIUM)

    def test_agent_refused_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_failed(reason="agent refused"))
        self.assertEqual(result.primary, FailureClass.AGENT_REFUSED)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_network_error_implied_on_tmux_crash(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        event = self._tmux_crashed()
        event.exit_signal = "SIGPIPE"  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.CRASH)
        self.assertIn(FailureClass.NETWORK_ERROR, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_gate_defer_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_deferred())
        self.assertEqual(result.primary, FailureClass.GATE_DEFER)
        self.assertEqual(result.implies, ())  # REQ-15
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_plateau_implied_on_story_deferred(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        result = classify(self._story_deferred(reason="plateau"))
        self.assertEqual(result.primary, FailureClass.REPEATED_RETRY)
        self.assertIn(FailureClass.PLATEAU, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_repeated_retry_primary(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )

        event = self._story_deferred()
        event.attempt_count = 7  # type: ignore[attr-defined]
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.REPEATED_RETRY)
        self.assertIn(FailureClass.PLATEAU, result.implies)
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_unknown_primary_on_non_failure_event(self) -> None:
        from story_automator.core.failure_triage import (
            Confidence,
            FailureClass,
            classify,
        )
        from story_automator.core.telemetry_events import StoryStarted

        event = StoryStarted(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            agent="dev",
            model="claude-opus-4-7",
            complexity="medium",
        )
        result = classify(event)
        self.assertEqual(result.primary, FailureClass.UNKNOWN)
        self.assertEqual(result.implies, ())
        self.assertEqual(result.confidence, Confidence.LOW)


class DeterminismGateTests(unittest.TestCase):
    def test_classify_is_byte_identical_over_100_runs(self) -> None:
        """Determinism quality gate — REQ-15-adjacent.

        Classify the same synthetic event 100 times and assert every
        result is structurally equal *and* produces a byte-identical
        ``repr()``. Guards against accidental nondeterminism from set
        iteration or dict ordering inside any future implies-aggregation
        logic.
        """
        from story_automator.core.failure_triage import classify
        from story_automator.core.telemetry_events import StoryFailed

        event = StoryFailed(
            timestamp="2026-01-01T00:00:00Z",
            run_id="run-1",
            epic="E1",
            story_key="S1",
            error_class="",
            reason="policy guardrail tripped on PII",
            attempts=3,
            final_session="sess",
        )
        first = classify(event)
        first_repr = repr(first)
        for _ in range(99):
            other = classify(event)
            self.assertEqual(other, first)
            self.assertEqual(repr(other), first_repr)

    def test_classify_stream_is_byte_identical_over_100_runs(self) -> None:
        """Same gate as above but for the stream path."""
        from story_automator.core.failure_triage import classify_stream
        from story_automator.core.telemetry_events import (
            StoryDeferred,
            TmuxSessionCrashed,
        )

        def make_events() -> list[object]:
            return [
                StoryDeferred(
                    timestamp="2026-01-01T00:00:00Z",
                    run_id="run-1",
                    epic="E1",
                    story_key="S1",
                    reason="plateau",
                    tasks_completed=1,
                ),
                TmuxSessionCrashed(
                    timestamp="2026-01-01T00:00:00Z",
                    run_id="run-1",
                    session_name="sess",
                    story_key="S1",
                    exit_code=137,
                    last_capture_chars=0,
                ),
            ]

        first = list(classify_stream(make_events()))
        first_repr = [repr(c) for c in first]
        for _ in range(99):
            other = list(classify_stream(make_events()))
            self.assertEqual(other, first)
            self.assertEqual([repr(c) for c in other], first_repr)
```

- [ ] **Step 2: Run the matrix + determinism tests**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ThirteenClassBehaviouralMatrixTests tests.test_failure_triage.DeterminismGateTests -v
```
Expected: 13 matrix tests + 2 determinism tests all pass.

- [ ] **Step 3: Run the full failure-triage suite + time it**

Run:
```
time PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage
```
Expected: `OK` with all tests, completing in `real` under 2 seconds (the spec's REQ-15 aggregate-runtime budget). The 100-run determinism loops are the dominant cost; each `classify` call is a handful of attribute reads and a `Classification(...)` construction so 2×100 iterations remain well under the budget. If the wall-clock exceeds 2s, profile before continuing — most likely a CI cold-import effect; re-run twice and use the warmer number.

- [ ] **Step 4: Commit**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add 13-class behavioural matrix + determinism gate (REQ-14/15)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 15: Coverage gate — `coverage --fail-under=85` (Quality gates)

**Files:** (verification only — no source edits unless coverage gap surfaces)

- [ ] **Step 1: Run coverage over the failure-triage module**

Run (from repo root):
```
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --include=skills/bmad-story-automator/src/story_automator/core/failure_triage.py \
  -m unittest tests.test_failure_triage
PYTHONPATH=skills/bmad-story-automator/src python -m coverage report -m --fail-under=85
```

Expected: `coverage report` exits 0 with `failure_triage.py` listed and coverage ≥ 85%. The 13-class matrix + per-event substring branches + determinism loops should land north of 95%.

The `--include=<path-to-file.py>` form is deliberate — `coverage`'s `--source` takes a directory or dotted-module name, and a file path without `.py` (the obvious-looking shape) silently instruments nothing and falsely reports 0% coverage. `--include` accepts a file glob and scopes the report exclusively to the M07b module. If your environment prefers dotted-module style, the equivalent is `--source=story_automator.core.failure_triage` (works with `PYTHONPATH` set as shown).

- [ ] **Step 2: If coverage falls under 85%, surface and fill the gap**

If the report shows uncovered lines, identify which branches are missed (usually edge-of-substring cases). Add a focused failing test → minimal implementation tweak (if any) → re-run coverage. Do NOT add `# pragma: no cover` to dodge the gate — every branch in this module is reachable from real event shapes and must be tested. Commit any added tests as `test(failure-triage): close coverage gap on <case>`.

- [ ] **Step 3: Snapshot the coverage number in the commit (optional but encouraged)**

If coverage was clean on the first run, no new commit is required at this task; the gate is a guard, not a code change. If you added a test in Step 2, commit it.

---

### Task 16: Final quality-gate sweep (ruff, format, wc -l, import-allowlist, project-wide regression)

**Files:** (verification only — no source edits unless a gate complains; if it does, edit the offending file and re-run before continuing.)

- [ ] **Step 1: Confirm the import-allowlist gate still passes with the new imports**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ImportAndSizeDisciplineTests -v
```
Expected: all 6 discipline tests pass. The new `from collections.abc import Iterable, Iterator` import is permitted by the `collections` root in the allowlist; the new `from story_automator.core.telemetry_events import …` is permitted by the `story_automator.core` local prefix. The `Optional`/`Union` ban continues to pass — the M07b module uses only PEP 604 `X | None` syntax. The future-annotations gate continues to pass — the M07a docstring + `from __future__` remain the first two top-level statements. The LF-line-endings gate continues to pass — never write CRLF.

- [ ] **Step 2: Confirm `wc -l` ≤ 500 on the module**

Run:
```
wc -l skills/bmad-story-automator/src/story_automator/core/failure_triage.py
```
Expected: a value at or below 500. Estimated landing size: ~230–270 lines. If `wc -l` is over 500, surface a gap report and stop — the cap is non-negotiable; tighten docstrings or factor a helper rather than relaxing the gate.

- [ ] **Step 3: Run `ruff check` on the changed files**

Run:
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
```
Expected: `All checks passed!` (exit 0). If ruff reports findings, edit the offending file (do NOT add a blanket `# noqa`) and re-run before continuing.

- [ ] **Step 4: Run `ruff format --check` on the changed files**

Run:
```
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
```
Expected: `2 files already formatted` (or equivalent zero-diff). If a diff is reported, run `python -m ruff format <path>`, re-run `--check`, then commit the formatting change as a separate `style(failure-triage): apply ruff format` commit.

- [ ] **Step 5: Run the project-wide test suite (regression guard)**

Run:
```
npm run test:python
```
Expected: `OK` — no other suite regresses. If a suite breaks, the new module imports cleanly so the breakage is likely unrelated; surface it as a separate issue and stop the M07b push.

- [ ] **Step 6: Verify the failure-triage suite aggregate runtime stays under 2s**

Run:
```
time PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage
```
Expected: `real` under 2 seconds (REQ-15). Cold-import variance can push this on the first run; the steady-state number after one warm-up should be comfortably under.

- [ ] **Step 7: No new commit required if all gates pass clean**

The per-task feature/test commits already cover source + tests. Only commit at this task if Step 4 produced formatting fixes (then commit those as `style(failure-triage): apply ruff format`).

---

## Self-review checklist (run after the plan is implemented end-to-end)

- [ ] REQ-06 covered: `classify(event: Event) -> Classification` exists, is pure (no I/O), never raises on any concrete M01 event subclass (Tasks 2–3 establish the contract; Tasks 5/7/9/11 fill each branch; Task 14's 13-class matrix is the acceptance test).
- [ ] REQ-07 covered: dispatch on `StoryFailed` / `StoryDeferred` / `TmuxSessionCrashed` / `EscalationTriggered`; non-failure events return the documented UNKNOWN/LOW/`non_failure_event` sentinel with `event_id` resolved via `getattr(event, "event_id", None)` (Task 3, asserted by Task 2 + Task 14 `test_unknown_primary_on_non_failure_event`).
- [ ] REQ-08 covered: `_classify_story_failed` honours timeout / policy or guardrail / test or pytest / parse or json / refused or refusal / budget or cost / unmatched in declaration order (Tasks 4–5, regression-locked by the matrix in Task 14).
- [ ] REQ-09 covered: `_classify_tmux_crash` returns CRASH/HIGH baseline; SIGPIPE / SIGHUP / "network" substring on `exit_signal` adds NETWORK_ERROR to `implies` (Tasks 6–7, matrix `test_network_error_implied_on_tmux_crash`).
- [ ] REQ-10 covered: `_classify_story_deferred` returns GATE_DEFER/HIGH default; `reason` containing "plateau" or `attempt_count > 3` returns REPEATED_RETRY/HIGH with PLATEAU implied (Tasks 8–9, matrix `test_plateau_implied_on_story_deferred` + `test_repeated_retry_primary`).
- [ ] REQ-11 covered: `_classify_escalation` returns REVIEW_REJECTED/MEDIUM default; `trigger` starting with "policy:" upgrades to POLICY_VIOLATION/HIGH with REVIEW_REJECTED implied (Tasks 10–11).
- [ ] REQ-12 covered: `classify_stream(events: Iterable[Event]) -> Iterator[Classification]` is a generator, does not buffer, does not call `iso_now`, propagates source exceptions verbatim (Tasks 12–13).
- [ ] REQ-13 covered: imports limited to `enum`, `dataclasses`, `collections.abc`, `core.telemetry_events`; no `core.common` symbols are actually consumed (the spec reserves them — none are needed for pure dispatch). The import-allowlist gate from M07a continues to enforce this (Task 16 step 1).
- [ ] REQ-14 covered: ≥13 behavioural tests (one per FailureClass member) + the mixed-event stream round-trip in `ClassifyStreamTests.test_classify_stream_yields_one_classification_per_event` (Tasks 12 + 14).
- [ ] REQ-15 covered: every behavioural test asserts on `.primary`, on `.implies` membership, and on `.confidence`; no test reads or writes files; no test invokes `compact_json`; aggregate runtime stays under 2 s (Task 14 step 3, Task 16 step 6).
- [ ] Non-functional: `from __future__ import annotations` first non-comment statement (M07a, unchanged); PEP 604 in module + tests (no `Optional`/`Union` introduced); LF line endings (never write CRLF — the existing M07a discipline test continues to enforce); no `os.sep` literals (none used).
- [ ] Quality gate — ruff check + ruff format --check — Task 16 steps 3–4.
- [ ] Quality gate — coverage `--fail-under=85` — Task 15.
- [ ] Quality gate — determinism (100× byte-identical) — Task 14 `DeterminismGateTests`.
- [ ] Quality gate — taxonomy completeness + 4-letter placeholder ban — continues to pass from M07a (Task 16 step 1).
- [ ] Quality gate — import-allowlist grep — covered by the AST-based `test_no_third_party_or_io_imports` in M07a's `ImportAndSizeDisciplineTests`; new M07b imports are pre-allowed by that test's allowlist.
- [ ] Quality gate — `wc -l ≤ 500` on module — Task 16 step 2.
- [ ] Quality gate — project-wide test regression — Task 16 step 5.
- [ ] No placeholders in the plan: every step has either complete code or a complete shell command with expected output.
- [ ] No type drift between tasks: the same field names (`primary`, `implies`, `confidence`, `reason`, `event_id`) are used consistently in dispatch, in every `_classify_*` helper, and in every test assertion.
- [ ] No name drift between tasks: the four private helpers are named exactly `_classify_story_failed`, `_classify_story_deferred`, `_classify_tmux_crash`, `_classify_escalation` (matching REQ-07 exactly) in the skeleton (Task 3), the implementations (Tasks 5, 7, 9, 11), and the docstring of `classify` itself.
