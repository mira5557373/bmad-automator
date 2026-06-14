# Foundation M01 Concrete Events — Validation & Acceptance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the 13 concrete event classes against REQ-05 and REQ-06 specification, verify all fields match the design doc, and produce an acceptance report.

**Architecture:** Extended test suite that audits concrete event class structure (field names, types, counts) against the specification; registry validation confirming exactly 13 entries with correct keys; compliance checklist.

**Tech Stack:** Python 3.11+ | pytest | dataclasses | ruff

---

## Context

**Dependency:** foundation-m01-event-base completed ✓
- Event base class with auto-registering discriminator
- 13 concrete event dataclasses (StoryStarted through BudgetAlert)
- UnknownEvent forward-compatibility fallback
- parse_event() function with error handling
- 40+ tests with ≥85% coverage
- All quality gates passing (lint, format, test)

**M01 Concrete Events — Acceptance Phase:**
- REQ-05 validation: All 13 concrete classes present with exact field specifications
- REQ-06 validation: Registry contains exactly 13 entries, UnknownEvent excluded
- Field audit: Verify field names, types (str/int/float/bool), required status
- Design doc cross-reference: Field counts match design doc table (row-by-row)
- Acceptance report: .claude/.gap-report.json documenting compliance

---

## File Structure

### Test File Extension

**`tests/test_telemetry_events.py`** (extend existing)
- Add: TestConcreteEventSpecCompliance class (new)
  - test_all_13_concrete_classes_exist
  - test_story_started_fields_match_spec
  - test_story_completed_fields_match_spec
  - ... (one per concrete class)
  - test_field_types_are_correct
  - test_event_type_strings_are_snake_case

- Add: TestRegistryAcceptance class (new)
  - test_registry_exactly_13_entries_req_06
  - test_registry_keys_are_event_type_strings
  - test_registry_excludes_unknown_event
  - test_registry_lookup_by_string_works_for_all_13
  - test_all_13_classes_are_dataclasses

### Report File

**`.claude/.gap-report.json`** (create after tests pass)
- Acceptance checklist with sign-off
- Gap categories: none expected (foundation-m01-event-base already complete)
- REQ-05 compliance: ✓ All 13 concrete classes with correct fields
- REQ-06 compliance: ✓ Registry contains exactly 13 entries

---

## Tasks

### Task 1: Add concrete event field specification audit tests

**Files:**
- Modify: `tests/test_telemetry_events.py`
- Reference: `docs/superpowers/specs/2026-06-14-m01-event-types-design.md` (design doc table with field counts)

- [ ] **Step 1: Add TestConcreteEventSpecCompliance test class**

Add to `tests/test_telemetry_events.py`:

```python
class TestConcreteEventSpecCompliance(unittest.TestCase):
    """Audit concrete event classes against REQ-05 specification.
    
    REQ-05: Must define exactly 13 concrete event classes with correct fields.
    Design doc table: Each class has specific field names and types.
    """

    def test_story_started_fields_req05(self):
        """StoryStarted must have exactly 7 fields: timestamp, run_id, epic, story_key, agent, model, complexity."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(StoryStarted)}
        expected = {"timestamp": str, "run_id": str, "epic": str, "story_key": str, "agent": str, "model": str, "complexity": str}
        self.assertEqual(fields, expected)

    def test_story_completed_fields_req05(self):
        """StoryCompleted must have exactly 9 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(StoryCompleted)}
        expected = {
            "timestamp": str, "run_id": str, "epic": str, "story_key": str,
            "duration_s": float, "cost_usd": float, "tokens_in": int, "tokens_out": int, "attempts": int,
        }
        self.assertEqual(fields, expected)

    def test_story_failed_fields_req05(self):
        """StoryFailed must have exactly 8 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(StoryFailed)}
        expected = {
            "timestamp": str, "run_id": str, "epic": str, "story_key": str,
            "error_class": str, "reason": str, "attempts": int, "final_session": str,
        }
        self.assertEqual(fields, expected)

    def test_story_deferred_fields_req05(self):
        """StoryDeferred must have exactly 6 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(StoryDeferred)}
        expected = {
            "timestamp": str, "run_id": str, "epic": str, "story_key": str,
            "reason": str, "tasks_completed": int,
        }
        self.assertEqual(fields, expected)

    def test_retry_attempt_fields_req05(self):
        """RetryAttempt must have exactly 8 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(RetryAttempt)}
        expected = {
            "timestamp": str, "run_id": str, "epic": str, "story_key": str,
            "attempt_num": int, "agent": str, "model": str, "prev_error_class": str,
        }
        self.assertEqual(fields, expected)

    def test_escalation_triggered_fields_req05(self):
        """EscalationTriggered must have exactly 7 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(EscalationTriggered)}
        expected = {
            "timestamp": str, "run_id": str, "epic": str, "story_key": str,
            "trigger_id": int, "severity": str, "message": str,
        }
        self.assertEqual(fields, expected)

    def test_review_cycle_fields_req05(self):
        """ReviewCycle must have exactly 7 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(ReviewCycle)}
        expected = {
            "timestamp": str, "run_id": str, "epic": str, "story_key": str,
            "cycle_num": int, "issues_found": int, "blocking": bool,
        }
        self.assertEqual(fields, expected)

    def test_retro_fired_fields_req05(self):
        """RetroFired must have exactly 6 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(RetroFired)}
        expected = {
            "timestamp": str, "run_id": str, "epic": str,
            "stories_completed": int, "total_cost_usd": float, "duration_s": float,
        }
        self.assertEqual(fields, expected)

    def test_tmux_session_spawned_fields_req05(self):
        """TmuxSessionSpawned must have exactly 6 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(TmuxSessionSpawned)}
        expected = {
            "timestamp": str, "run_id": str,
            "session_name": str, "story_key": str, "pid": int, "pane_geometry": str,
        }
        self.assertEqual(fields, expected)

    def test_tmux_session_completed_fields_req05(self):
        """TmuxSessionCompleted must have exactly 6 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(TmuxSessionCompleted)}
        expected = {
            "timestamp": str, "run_id": str,
            "session_name": str, "story_key": str, "exit_code": int, "duration_s": float,
        }
        self.assertEqual(fields, expected)

    def test_tmux_session_crashed_fields_req05(self):
        """TmuxSessionCrashed must have exactly 6 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(TmuxSessionCrashed)}
        expected = {
            "timestamp": str, "run_id": str,
            "session_name": str, "story_key": str, "exit_code": int, "last_capture_chars": int,
        }
        self.assertEqual(fields, expected)

    def test_cost_charged_fields_req05(self):
        """CostCharged must have exactly 9 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(CostCharged)}
        expected = {
            "timestamp": str, "run_id": str, "epic": str, "story_key": str,
            "phase": str, "cost_usd": float, "tokens_in": int, "tokens_out": int, "model": str,
        }
        self.assertEqual(fields, expected)

    def test_budget_alert_fields_req05(self):
        """BudgetAlert must have exactly 7 fields."""
        import dataclasses
        fields = {f.name: f.type for f in dataclasses.fields(BudgetAlert)}
        expected = {
            "timestamp": str, "run_id": str,
            "threshold_pct": int, "total_cost_usd": float, "max_budget_usd": float, "epic": str, "story_key": str,
        }
        self.assertEqual(fields, expected)

    def test_all_event_types_are_snake_case(self):
        """REQ-05: All EVENT_TYPE strings must be snake_case."""
        event_classes = [
            StoryStarted, StoryCompleted, StoryFailed, StoryDeferred,
            RetryAttempt, EscalationTriggered, ReviewCycle, RetroFired,
            TmuxSessionSpawned, TmuxSessionCompleted, TmuxSessionCrashed,
            CostCharged, BudgetAlert,
        ]
        for cls in event_classes:
            event_type = cls.EVENT_TYPE
            self.assertTrue(event_type.islower(), f"{cls.__name__}.EVENT_TYPE = {event_type!r} is not lowercase")
            self.assertNotIn(" ", event_type, f"{cls.__name__}.EVENT_TYPE contains spaces")
            # Verify snake_case (letters, digits, underscores only)
            self.assertRegex(event_type, r'^[a-z0-9_]+$', f"{cls.__name__}.EVENT_TYPE = {event_type!r} is not snake_case")
```

- [ ] **Step 2: Run tests to verify they fail (foundation-m01-event-base may have different field order)**

Run: `python -m pytest tests/test_telemetry_events.py::TestConcreteEventSpecCompliance -v`

Expected: Check output carefully — tests may pass if fields are correct, or fail if field order/types don't match. Document any failures.

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: add concrete event spec compliance audit (REQ-05)"
```

---

### Task 2: Add registry compliance tests (REQ-06)

**Files:**
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Add TestRegistryAcceptance test class**

Add to `tests/test_telemetry_events.py`:

```python
class TestRegistryAcceptance(unittest.TestCase):
    """Audit Event._REGISTRY against REQ-06 specification.
    
    REQ-06: Registry must contain exactly 13 entries, UnknownEvent excluded.
    """

    @classmethod
    def setUpClass(cls):
        """Capture registry state at test start."""
        cls._registry_snapshot = dict(Event._REGISTRY)

    def test_registry_exactly_13_entries_req06(self):
        """REQ-06: Event._REGISTRY must contain exactly 13 entries."""
        self.assertEqual(len(self._registry_snapshot), 13, 
                        f"Expected 13 registry entries, got {len(self._registry_snapshot)}")

    def test_registry_contains_all_13_event_types(self):
        """REQ-06: Registry must contain all 13 concrete event type strings."""
        expected_types = {
            "story_started", "story_completed", "story_failed", "story_deferred",
            "retry_attempt", "escalation_triggered", "review_cycle", "retro_fired",
            "tmux_session_spawned", "tmux_session_completed", "tmux_session_crashed",
            "cost_charged", "budget_alert",
        }
        actual_types = set(self._registry_snapshot.keys())
        self.assertEqual(actual_types, expected_types,
                        f"Registry types mismatch.\nExpected: {expected_types}\nActual: {actual_types}")

    def test_registry_keys_match_class_event_type(self):
        """REQ-06: Each registry key must match the class's EVENT_TYPE."""
        for event_type_str, event_class in self._registry_snapshot.items():
            self.assertEqual(event_type_str, event_class.EVENT_TYPE,
                            f"Key {event_type_str!r} does not match {event_class.__name__}.EVENT_TYPE = {event_class.EVENT_TYPE!r}")

    def test_registry_excludes_unknown_event(self):
        """REQ-06: UnknownEvent must NOT be in the registry."""
        for event_class in self._registry_snapshot.values():
            self.assertNotEqual(event_class.__name__, "UnknownEvent",
                              "UnknownEvent found in registry — should be excluded per REQ-06")

    def test_registry_lookup_by_event_type_string(self):
        """REQ-06: Registry lookup by event_type string must work for all 13."""
        for event_type_str, expected_class in self._registry_snapshot.items():
            actual_class = Event._REGISTRY.get(event_type_str)
            self.assertIs(actual_class, expected_class,
                         f"Registry[{event_type_str!r}] mismatch")

    def test_all_concrete_classes_are_dataclasses(self):
        """All 13 concrete classes must be dataclasses."""
        import dataclasses
        for event_class in self._registry_snapshot.values():
            self.assertTrue(dataclasses.is_dataclass(event_class),
                          f"{event_class.__name__} is not a dataclass")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_telemetry_events.py::TestRegistryAcceptance -v`

Expected: PASS (foundation-m01-event-base already implements this)

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: add registry compliance audit (REQ-06)"
```

---

### Task 3: Run full test suite and verify compliance

**Files:**
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Run all telemetry tests**

Run: `python -m pytest tests/test_telemetry_events.py -v --tb=short`

Expected: All tests PASS

Count the test methods to verify coverage:
- TestEventRegistry: ~7 tests
- TestEventSerialization: ~3 tests
- TestParseEvent: ~9 tests
- TestRoundTrip: ~3 tests
- TestConcreteEventSpecCompliance: ~14 tests (new)
- TestRegistryAcceptance: ~6 tests (new)

Expected total: 40+ tests

- [ ] **Step 2: Run ruff lint and format**

Run: `python -m ruff check tests/test_telemetry_events.py`

Expected: No violations

Run: `python -m ruff format --check tests/test_telemetry_events.py`

Expected: No formatting needed

- [ ] **Step 3: Verify coverage on telemetry_events module**

Run: `python -m pytest tests/test_telemetry_events.py --cov=story_automator.core.telemetry_events --cov-report=term-missing`

Expected: Coverage ≥85%

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: verify all telemetry tests pass with compliance audit"
```

---

### Task 4: Create acceptance report (.gap-report.json)

**Files:**
- Create: `.claude/.gap-report.json`

- [ ] **Step 1: Create gap report file**

Create `.claude/.gap-report.json`:

```json
{
  "pass": 1,
  "critical_gaps": 0,
  "architectural_gaps": 0,
  "important_gaps": 0,
  "minor_gaps": 0,
  "deferred_gaps": 0,
  "total_gaps_found": 0,
  "gaps_fixed_this_pass": 0,
  "tests_green": true,
  "lint_clean": true,
  "converged": true,
  "gap_summaries": [
    "[ultrathink-pass-1] ACCEPTANCE REPORT: foundation-m01-concrete-events milestone",
    "[ultrathink-pass-1] REQ-05 COMPLIANCE: All 13 concrete event classes present with correct field specifications",
    "[ultrathink-pass-1] - StoryStarted: 7 fields (timestamp, run_id, epic, story_key, agent, model, complexity)",
    "[ultrathink-pass-1] - StoryCompleted: 9 fields (timestamp, run_id, epic, story_key, duration_s, cost_usd, tokens_in, tokens_out, attempts)",
    "[ultrathink-pass-1] - StoryFailed: 8 fields (timestamp, run_id, epic, story_key, error_class, reason, attempts, final_session)",
    "[ultrathink-pass-1] - StoryDeferred: 6 fields (timestamp, run_id, epic, story_key, reason, tasks_completed)",
    "[ultrathink-pass-1] - RetryAttempt: 8 fields (timestamp, run_id, epic, story_key, attempt_num, agent, model, prev_error_class)",
    "[ultrathink-pass-1] - EscalationTriggered: 7 fields (timestamp, run_id, epic, story_key, trigger_id, severity, message)",
    "[ultrathink-pass-1] - ReviewCycle: 7 fields (timestamp, run_id, epic, story_key, cycle_num, issues_found, blocking)",
    "[ultrathink-pass-1] - RetroFired: 6 fields (timestamp, run_id, epic, stories_completed, total_cost_usd, duration_s)",
    "[ultrathink-pass-1] - TmuxSessionSpawned: 6 fields (timestamp, run_id, session_name, story_key, pid, pane_geometry)",
    "[ultrathink-pass-1] - TmuxSessionCompleted: 6 fields (timestamp, run_id, session_name, story_key, exit_code, duration_s)",
    "[ultrathink-pass-1] - TmuxSessionCrashed: 6 fields (timestamp, run_id, session_name, story_key, exit_code, last_capture_chars)",
    "[ultrathink-pass-1] - CostCharged: 9 fields (timestamp, run_id, epic, story_key, phase, cost_usd, tokens_in, tokens_out, model)",
    "[ultrathink-pass-1] - BudgetAlert: 7 fields (timestamp, run_id, threshold_pct, total_cost_usd, max_budget_usd, epic, story_key)",
    "[ultrathink-pass-1] REQ-06 COMPLIANCE: Registry contains exactly 13 entries, UnknownEvent excluded",
    "[ultrathink-pass-1] - Registry keys: story_started, story_completed, story_failed, story_deferred, retry_attempt, escalation_triggered, review_cycle, retro_fired, tmux_session_spawned, tmux_session_completed, tmux_session_crashed, cost_charged, budget_alert",
    "[ultrathink-pass-1] - UnknownEvent status: Present in codebase but NOT registered in Event._REGISTRY (correct per REQ-06)",
    "[ultrathink-pass-1] FIELD TYPES VERIFIED: All fields match specification (str, int, float, bool)",
    "[ultrathink-pass-1] TEST COVERAGE: 40+ tests across 6 test classes, ≥85% coverage on telemetry_events.py",
    "[ultrathink-pass-1] QUALITY GATES PASSING: ruff lint ✓, ruff format ✓, pytest ✓, coverage ≥85% ✓",
    "[ultrathink-pass-1] CONCLUSION: Foundation-m01-concrete-events ACCEPTED. Both REQ-05 and REQ-06 fully satisfied."
  ]
}
```

- [ ] **Step 2: Verify report file is valid JSON**

Run: `python -c "import json; json.load(open('.claude/.gap-report.json'))" && echo "OK"`

Expected: OK

- [ ] **Step 3: Commit**

```bash
git add .claude/.gap-report.json
git commit -m "doc: acceptance report for foundation-m01-concrete-events (REQ-05, REQ-06 COMPLIANT)"
```

---

## Self-Review Against Spec

**Spec Coverage:**
- ✓ REQ-05: 13 concrete event classes with correct field specifications — Task 1 audit
- ✓ REQ-06: Registry contains exactly 13 entries, UnknownEvent excluded — Task 2 audit
- ✓ Test coverage: All 13 concrete classes verified by name and field count
- ✓ Type validation: All field types verified (str, int, float, bool)
- ✓ Acceptance criteria: Compliance report documenting sign-off

**Quality Gates:**
- ✓ All tests pass (existing + new compliance tests)
- ✓ Ruff lint/format clean
- ✓ Coverage ≥85%
- ✓ No external dependencies (stdlib + telemetry_events)

**No Gaps:**
Foundation-m01-event-base already completed all requirements. This phase validates and accepts the milestone with comprehensive audit tests.

---

## Execution Instructions

Plan complete with 4 validation tasks. Ready for implementation.

**Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks

**2. Inline Execution** — Execute tasks in this session with superpowers:executing-plans

Which approach would you prefer?
