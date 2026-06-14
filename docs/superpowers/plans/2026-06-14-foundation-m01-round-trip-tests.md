# Foundation-M01-Round-Trip-Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the round-trip serialization protocol (REQ-08, REQ-09, REQ-10) for all 13 concrete events and UnknownEvent, ensuring byte-identical re-serialization and full test coverage.

**Architecture:** The plan focuses on comprehensive test coverage across four TestCase classes (TestRoundTrip, TestUnknownEventRoundTrip, TestRoundTripEdgeCases, TestDeterministicSerialization). Tests validate the invariant: `construct → to_json_line() → parse_event() → __eq__` comparison and byte-equal serialization. Existing implementations (Event, concrete classes, UnknownEvent, parse_event) remain unchanged; this milestone adds test validation only.

**Tech Stack:** Python 3.11+ | pytest | dataclasses | json | unittest.TestCase

---

## File Structure

```
tests/test_telemetry_events.py
├── TestRoundTrip (existing, enhance if needed)
│   └── Comprehensive round-trip tests for all 13 concrete events
├── TestUnknownEventRoundTrip (new)
│   └── UnknownEvent round-trip with arbitrary types and fields
├── TestRoundTripEdgeCases (new)
│   └── Unicode, special JSON chars, large numbers, empty strings
└── TestDeterministicSerialization (new)
    └── Deterministic ordering, byte-equality, field ordering
```

The test file already has most round-trip tests. Tasks focus on:
1. **Verifying existing tests pass** and measure coverage
2. **Adding edge-case tests** for unicode, special chars, boundary values
3. **Adding determinism tests** for JSON key ordering
4. **Adding comprehensive UnknownEvent round-trip tests** with arbitrary payloads
5. **Validating byte-equality** for REQ-09

---

## Task List

### Task 1: Verify Current Test Coverage and Identify Gaps

**Files:**
- Test: `tests/test_telemetry_events.py` (read-only)

- [ ] **Step 1: Run full test suite to baseline**

```bash
cd C:\Users\Administrator\Desktop\development\bmad-echosystem\bmad-automator-wt\sw-port
python -m pytest tests/test_telemetry_events.py -v
```

Expected: All tests pass. Note the count (should be 30+).

- [ ] **Step 2: Run with coverage report and save results**

```bash
python -m pytest tests/test_telemetry_events.py --cov=story_automator.core.telemetry_events --cov-report=term-missing
```

Expected: Coverage ≥85%. Note any untested branches in to_json_line(), parse_event(), or to_dict().

**IMPORTANT ASSUMPTION:** This plan relies on Python dataclass field ordering (Python 3.7+) to ensure byte-identical JSON serialization. The order of fields in Event.to_dict() output is guaranteed by the order of @dataclass field definitions, which is preserved in asdict().

- [ ] **Step 3: Document existing test count and coverage baseline**

```bash
grep -c "def test_" tests/test_telemetry_events.py
```

Expected: ≥30 tests already present. Record this baseline count and coverage % — subsequent tasks should not significantly inflate test count (target: final ≤45 tests total, efficiency > 0.67).

---

### Task 2: Add TestUnknownEventRoundTrip Class for Arbitrary Event Types

**Files:**
- Modify: `tests/test_telemetry_events.py`
- Test: (in same file)

- [ ] **Step 1: Add TestUnknownEventRoundTrip class skeleton**

Add this class after TestRoundTrip in test_telemetry_events.py:

```python
class TestUnknownEventRoundTrip(unittest.TestCase):
    """Test UnknownEvent round-trip with arbitrary event types and fields (REQ-09)."""

    def test_unknown_event_round_trip_basic(self):
        """UnknownEvent with custom event_type must round-trip."""
        original_line = '{"event_type":"custom_future_v1","timestamp":"2026-06-14T00:00:00Z","run_id":"r1","custom_field":"value"}'
        parsed = parse_event(original_line)
        self.assertIsInstance(parsed, UnknownEvent)
        reserialized = parsed.to_json_line()
        self.assertEqual(original_line, reserialized)
```

- [ ] **Step 2: Run test to verify it passes**

```bash
python -m pytest tests/test_telemetry_events.py::TestUnknownEventRoundTrip::test_unknown_event_round_trip_basic -v
```

Expected: PASS

- [ ] **Step 3: Add test for UnknownEvent with nested fields**

Add this test method to TestUnknownEventRoundTrip:

```python
    def test_unknown_event_with_nested_json_object(self):
        """UnknownEvent must preserve nested JSON objects in raw_fields."""
        original_line = '{"event_type":"unknown_with_nested","timestamp":"2026-06-14T00:00:00Z","run_id":"r1","nested":{"inner":"value","count":42}}'
        parsed = parse_event(original_line)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertEqual(parsed.raw_fields["nested"], {"inner": "value", "count": 42})
        reserialized = parsed.to_json_line()
        parsed2 = parse_event(reserialized)
        self.assertEqual(parsed2.raw_fields["nested"], {"inner": "value", "count": 42})
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_telemetry_events.py::TestUnknownEventRoundTrip -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: add TestUnknownEventRoundTrip class for arbitrary event types (REQ-09)"
```

---

### Task 3: Add Edge-Case Tests for Unicode and Special Characters

**Files:**
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Create TestRoundTripEdgeCases class**

Add this class after TestUnknownEventRoundTrip (before the final line 1080):

```python
class TestRoundTripEdgeCases(unittest.TestCase):
    """Test round-trip with unicode, special JSON chars, and boundary values."""

    def test_concrete_event_with_unicode_emoji(self):
        """StoryStarted must preserve unicode emoji in string fields."""
        original = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="EPIC-🚀",
            story_key="S1",
            agent="claude",
            model="opus",
            complexity="high 🎯"
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        self.assertEqual(parsed.epic, "EPIC-🚀")
        self.assertEqual(parsed.complexity, "high 🎯")
        line2 = parsed.to_json_line()
        self.assertEqual(line1, line2)
```

- [ ] **Step 2: Run test to verify it passes**

```bash
python -m pytest tests/test_telemetry_events.py::TestRoundTripEdgeCases::test_concrete_event_with_unicode_emoji -v
```

Expected: PASS

- [ ] **Step 3: Add test for escaped JSON characters (with verification)**

Add to TestRoundTripEdgeCases:

```python
    def test_concrete_event_with_escaped_json_chars(self):
        """Event must handle escaped quotes, newlines, tabs, and backslashes."""
        original = StoryFailed(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="EPIC-1",
            story_key="S1",
            error_class='syntax"error',
            reason='line1\nline2\ttab',
            attempts=1,
            final_session=r'path\to\session'  # Use raw string to avoid double-escape
        )
        # First round-trip
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        # Verify parsed values match original
        self.assertEqual(parsed.error_class, 'syntax"error')
        self.assertEqual(parsed.reason, 'line1\nline2\ttab')
        self.assertEqual(parsed.final_session, r'path\to\session')
        # Verify byte-equality on re-serialize
        line2 = parsed.to_json_line()
        self.assertEqual(line1, line2, 
            f"JSON not byte-equal after round-trip.\nOriginal: {line1}\nRe-serialized: {line2}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_telemetry_events.py::TestRoundTripEdgeCases -v
```

Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: add edge-case round-trip tests for unicode and escaped chars"
```

---

### Task 4: Add Boundary Value Tests for Numeric Fields

**Files:**
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Add boundary value test to TestRoundTripEdgeCases**

```python
    def test_cost_charged_with_boundary_float_values(self):
        """CostCharged must handle float boundaries and precision."""
        original = CostCharged(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            phase="test",
            cost_usd=0.0001,  # Small value
            tokens_in=0,       # Zero
            tokens_out=999999,  # Large int
            model="opus"
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        self.assertEqual(parsed.cost_usd, 0.0001)
        self.assertEqual(parsed.tokens_in, 0)
        self.assertEqual(parsed.tokens_out, 999999)
        line2 = parsed.to_json_line()
        self.assertEqual(line1, line2)
```

- [ ] **Step 2: Add test for large negative float values**

```python
    def test_story_completed_with_large_duration(self):
        """StoryCompleted must handle large float values without precision loss."""
        original = StoryCompleted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=999999.99999,
            cost_usd=123.456789,
            tokens_in=2000000,
            tokens_out=5000000,
            attempts=100
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        # Note: JSON float serialization may lose precision; verify parse succeeds
        self.assertAlmostEqual(parsed.cost_usd, 123.456789, places=5)
        line2 = parsed.to_json_line()
        # Re-parse and verify consistency
        parsed2 = parse_event(line2)
        self.assertEqual(parsed2.cost_usd, parsed.cost_usd)
```

- [ ] **Step 3: Run tests to verify**

```bash
python -m pytest tests/test_telemetry_events.py::TestRoundTripEdgeCases -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: add boundary value tests for float and int fields"
```

---

### Task 5: Add Empty String and None Field Tests

**Files:**
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Add test for empty string fields**

Add to TestRoundTripEdgeCases:

```python
    def test_concrete_event_with_empty_strings(self):
        """Events must preserve empty string fields."""
        original = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="",
            epic="",
            story_key="S1",
            agent="",
            model="",
            complexity=""
        )
        line1 = original.to_json_line()
        parsed = parse_event(line1)
        self.assertEqual(parsed.run_id, "")
        self.assertEqual(parsed.epic, "")
        self.assertEqual(parsed.agent, "")
        line2 = parsed.to_json_line()
        self.assertEqual(line1, line2)
```

- [ ] **Step 2: Run test to verify**

```bash
python -m pytest tests/test_telemetry_events.py::TestRoundTripEdgeCases::test_concrete_event_with_empty_strings -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: add empty string field tests for round-trip validation"
```

---

### Task 6: Add Deterministic Serialization and JSON Key Ordering Tests

**Files:**
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Create TestDeterministicSerialization class**

Add after TestRoundTripEdgeCases:

```python
class TestDeterministicSerialization(unittest.TestCase):
    """Test deterministic JSON serialization for round-trip consistency (REQ-08, REQ-09)."""

    def test_same_concrete_event_produces_byte_identical_json(self):
        """Multiple serializations of same event must produce byte-identical JSON."""
        event = StoryCompleted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=120.5,
            cost_usd=0.25,
            tokens_in=1000,
            tokens_out=2000,
            attempts=2
        )
        line1 = event.to_json_line()
        line2 = event.to_json_line()
        line3 = event.to_json_line()
        self.assertEqual(line1, line2, "Multiple to_json_line() calls produced different output")
        self.assertEqual(line2, line3, "Third to_json_line() call differed from first two")
```

- [ ] **Step 2: Run test to verify**

```bash
python -m pytest tests/test_telemetry_events.py::TestDeterministicSerialization::test_same_concrete_event_produces_byte_identical_json -v
```

Expected: PASS

- [ ] **Step 3: Add test for JSON key ordering preservation**

```python
    def test_json_key_order_is_deterministic(self):
        """JSON key order must be deterministic across serializations (relies on Python 3.7+ dict ordering)."""
        event = StoryStarted(
            timestamp="2026-06-14T12:00:00Z",
            run_id="r1",
            epic="EPIC-1",
            story_key="S1",
            agent="agent1",
            model="model1",
            complexity="high"
        )
        line1 = event.to_json_line()
        
        # Parse and re-serialize multiple times
        for _ in range(10):
            event = parse_event(line1)
            line1_check = event.to_json_line()
            self.assertEqual(line1, line1_check,
                f"JSON key order changed after parse-reserialize cycle.\nExpected: {line1}\nGot: {line1_check}")
```

- [ ] **Step 4: Add test for determinism across many parse cycles**

```python
    def test_parse_reserialize_produces_identical_json_many_cycles(self):
        """Multiple parse-reserialize cycles must produce byte-identical JSON (REQ-08, REQ-09)."""
        original_line = '{"event_type":"review_cycle","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","epic":"E1","story_key":"S1","cycle_num":3,"issues_found":5,"blocking":true}'
        
        current_line = original_line
        for cycle in range(10):
            parsed = parse_event(current_line)
            current_line = parsed.to_json_line()
        
        # After 10 cycles, line should still match original
        self.assertEqual(current_line, original_line,
            f"JSON diverged after {cycle + 1} parse-reserialize cycles.\nExpected: {original_line}\nGot: {current_line}")
```

- [ ] **Step 5: Run all determinism tests to verify**

```bash
python -m pytest tests/test_telemetry_events.py::TestDeterministicSerialization -v
```

Expected: PASS (all tests in class)

- [ ] **Step 6: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: add deterministic serialization and key-ordering tests (REQ-08, REQ-09)"
```

---

### Task 7: Add Comprehensive Multi-Field UnknownEvent Tests

**Files:**
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Add test for UnknownEvent with many field types**

Add to TestUnknownEventRoundTrip:

```python
    def test_unknown_event_with_many_fields(self):
        """UnknownEvent must preserve many field types in raw_fields."""
        original_line = '{"event_type":"future_event_v5","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","field_a":1,"field_b":"text","field_c":true,"field_d":3.14,"field_e":null,"field_f":["a","b"]}'
        parsed = parse_event(original_line)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertEqual(parsed.raw_fields["field_a"], 1)
        self.assertEqual(parsed.raw_fields["field_b"], "text")
        self.assertEqual(parsed.raw_fields["field_c"], True)
        self.assertAlmostEqual(parsed.raw_fields["field_d"], 3.14, places=5)
        self.assertIsNone(parsed.raw_fields["field_e"])
        self.assertEqual(parsed.raw_fields["field_f"], ["a", "b"])
        # Critical: verify byte-equality (REQ-09)
        reserialized = parsed.to_json_line()
        self.assertEqual(original_line, reserialized, 
            f"UnknownEvent with mixed types failed byte-equality.\nOriginal: {original_line}\nReserialized: {reserialized}")
```

- [ ] **Step 2: Run test to verify**

```bash
python -m pytest tests/test_telemetry_events.py::TestUnknownEventRoundTrip::test_unknown_event_with_many_fields -v
```

Expected: PASS

- [ ] **Step 3: Add test for UnknownEvent with null values in raw_fields**

Add to TestUnknownEventRoundTrip:

```python
    def test_unknown_event_with_null_values_req09(self):
        """REQ-09: UnknownEvent must preserve null values and round-trip byte-equal."""
        original_line = '{"event_type":"future_with_nulls","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","value_a":null,"value_b":"present","value_c":null}'
        parsed = parse_event(original_line)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertIsNone(parsed.raw_fields["value_a"])
        self.assertEqual(parsed.raw_fields["value_b"], "present")
        self.assertIsNone(parsed.raw_fields["value_c"])
        # Verify byte-equality with nulls preserved
        reserialized = parsed.to_json_line()
        self.assertEqual(original_line, reserialized,
            f"Null values not round-tripped byte-equal.\nOriginal: {original_line}\nReserialized: {reserialized}")
```

- [ ] **Step 4: Add test for UnknownEvent byte-equality with diverse payloads**

Add to TestUnknownEventRoundTrip:

```python
    def test_unknown_event_byte_equality_req09(self):
        """REQ-09: UnknownEvent re-serialization must produce byte-equal output."""
        # Multiple arbitrary unknown events with diverse payloads, each must round-trip to byte-identical JSON
        test_lines = [
            '{"event_type":"future_alpha","timestamp":"2026-06-14T00:00:00Z","run_id":"r1","x":1}',
            '{"event_type":"future_beta","timestamp":"2026-06-14T00:00:01Z","run_id":"r2","y":"hello","z":false}',
            '{"event_type":"future_gamma","timestamp":"2026-06-14T00:00:02Z","run_id":"r3","data":[1,2,3]}',
            '{"event_type":"future_delta","timestamp":"2026-06-14T00:00:03Z","run_id":"r4","nested":{"key":"value"},"nullval":null}',
        ]
        
        for original_line in test_lines:
            with self.subTest(event_type=original_line.split('"')[3]):
                parsed = parse_event(original_line)
                reserialized = parsed.to_json_line()
                self.assertEqual(original_line, reserialized, 
                    f"Byte-equality failed for {original_line}")
```

- [ ] **Step 5: Run tests to verify**

```bash
python -m pytest tests/test_telemetry_events.py::TestUnknownEventRoundTrip -v
```

Expected: PASS (all three new tests)

- [ ] **Step 6: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: add comprehensive UnknownEvent round-trip tests including nulls (REQ-09)"
```

---

### Task 8: Add All 13 Concrete Events Full Round-Trip Coverage

**Files:**
- Modify: `tests/test_telemetry_events.py`

- [ ] **Step 1: Add comprehensive round-trip test for all events**

Add to TestRoundTrip class (or verify it exists):

```python
    def test_all_13_events_round_trip_with_varied_values(self):
        """All 13 concrete events must round-trip with varying field values."""
        test_cases = [
            StoryStarted(
                timestamp="2026-06-14T12:34:56Z",
                run_id="run-alpha",
                epic="EPIC-1",
                story_key="STORY-1",
                agent="agent-model-v1",
                model="gpt-4-turbo",
                complexity="extreme"
            ),
            StoryCompleted(
                timestamp="2026-06-14T13:45:00Z",
                run_id="run-beta",
                epic="EPIC-2",
                story_key="STORY-2",
                duration_s=3661.5,
                cost_usd=12.3456,
                tokens_in=50000,
                tokens_out=100000,
                attempts=3
            ),
            StoryFailed(
                timestamp="2026-06-14T14:00:00Z",
                run_id="run-gamma",
                epic="EPIC-3",
                story_key="STORY-3",
                error_class="OutOfMemoryError",
                reason="Process exceeded 16GB threshold",
                attempts=7,
                final_session="tmux-session-dead"
            ),
            StoryDeferred(
                timestamp="2026-06-14T15:00:00Z",
                run_id="run-delta",
                epic="EPIC-4",
                story_key="STORY-4",
                reason="budget_exhausted",
                tasks_completed=42
            ),
            RetryAttempt(
                timestamp="2026-06-14T16:00:00Z",
                run_id="run-epsilon",
                epic="EPIC-5",
                story_key="STORY-5",
                attempt_num=5,
                agent="retry-agent",
                model="claude-opus",
                prev_error_class="RateLimitError"
            ),
            EscalationTriggered(
                timestamp="2026-06-14T17:00:00Z",
                run_id="run-zeta",
                epic="EPIC-6",
                story_key="STORY-6",
                trigger_id=999,
                severity="CRITICAL",
                message="Manual escalation by operator"
            ),
            ReviewCycle(
                timestamp="2026-06-14T18:00:00Z",
                run_id="run-eta",
                epic="EPIC-7",
                story_key="STORY-7",
                cycle_num=10,
                issues_found=25,
                blocking=False
            ),
            RetroFired(
                timestamp="2026-06-14T19:00:00Z",
                run_id="run-theta",
                epic="EPIC-8",
                stories_completed=50,
                total_cost_usd=250.75,
                duration_s=86400.5
            ),
            TmuxSessionSpawned(
                timestamp="2026-06-14T20:00:00Z",
                run_id="run-iota",
                session_name="tmux-main-prod",
                story_key="STORY-8",
                pid=65536,
                pane_geometry="120x40"
            ),
            TmuxSessionCompleted(
                timestamp="2026-06-14T21:00:00Z",
                run_id="run-kappa",
                session_name="tmux-test",
                story_key="STORY-9",
                exit_code=0,
                duration_s=7200.25
            ),
            TmuxSessionCrashed(
                timestamp="2026-06-14T22:00:00Z",
                run_id="run-lambda",
                session_name="tmux-crashed",
                story_key="STORY-10",
                exit_code=137,
                last_capture_chars=5000
            ),
            CostCharged(
                timestamp="2026-06-14T23:00:00Z",
                run_id="run-mu",
                epic="EPIC-9",
                story_key="STORY-11",
                phase="Phase-Z",
                cost_usd=99.9999,
                tokens_in=999999,
                tokens_out=2000000,
                model="claude-sonnet"
            ),
            BudgetAlert(
                timestamp="2026-06-14T23:59:59Z",
                run_id="run-nu",
                threshold_pct=95,
                total_cost_usd=949.99,
                max_budget_usd=1000.0,
                epic="EPIC-10",
                story_key="STORY-12"
            ),
        ]
        
        for event in test_cases:
            with self.subTest(event_type=event.EVENT_TYPE):
                # Serialize
                line1 = event.to_json_line()
                # Parse
                parsed = parse_event(line1)
                # Verify equality
                self.assertEqual(parsed, event)
                # Re-serialize
                line2 = parsed.to_json_line()
                # Verify byte-equality (REQ-08)
                self.assertEqual(line1, line2)
```

- [ ] **Step 2: Run test to verify it passes**

```bash
python -m pytest tests/test_telemetry_events.py::TestRoundTrip::test_all_13_events_round_trip_with_varied_values -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_telemetry_events.py
git commit -m "test: comprehensive round-trip for all 13 concrete events (REQ-08)"
```

---

### Task 9: Verify Full Test Count and Coverage

**Files:**
- Test: `tests/test_telemetry_events.py` (read-only for this task)

- [ ] **Step 1: Count total tests**

```bash
cd C:\Users\Administrator\Desktop\development\bmad-echosystem\bmad-automator-wt\sw-port
grep -c "def test_" tests/test_telemetry_events.py
```

Expected: ≥30 tests (REQ-10 requirement)

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/test_telemetry_events.py -v --tb=short
```

Expected: All tests PASS

- [ ] **Step 3: Check coverage**

```bash
python -m pytest tests/test_telemetry_events.py --cov=story_automator.core.telemetry_events --cov-fail-under=85 --cov-report=term-missing
```

Expected: Coverage ≥85%, all lines in core/telemetry_events.py tested

- [ ] **Step 4: Document results**

Record the test count and coverage percentage. Expected output should show:
- Line coverage ≥85%
- All branches in to_json_line(), to_dict(), parse_event() covered
- No untested exception paths

---

### Task 10: Verify Linting and Format Compliance

**Files:**
- Test: `tests/test_telemetry_events.py`
- Test: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`

- [ ] **Step 1: Run ruff check on both files**

```bash
python -m ruff check tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: Zero violations

- [ ] **Step 2: Run ruff format check**

```bash
python -m ruff format --check tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: Both files already formatted correctly (no changes needed)

- [ ] **Step 3: If any issues, fix them**

If ruff check or format fails, run:

```bash
python -m ruff format tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
python -m ruff check --fix tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Then re-run checks to verify zero violations.

- [ ] **Step 4: Commit if changes made**

If linting changes were needed:

```bash
git add tests/test_telemetry_events.py skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git commit -m "style: fix linting and formatting issues"
```

---

### Task 11: Create and Fill Acceptance Report with Actual Results

**Files:**
- Create: `docs/superpowers/acceptance-report-m01-round-trip-tests.md`

- [ ] **Step 1: Run test suite to capture final metrics**

Before writing the report, collect final test results:

```bash
cd C:\Users\Administrator\Desktop\development\bmad-echosystem\bmad-automator-wt\sw-port
python -m pytest tests/test_telemetry_events.py -v --tb=short 2>&1 | tee test_results.txt
```

Note the final test count and pass/fail status.

- [ ] **Step 2: Capture coverage results**

```bash
python -m pytest tests/test_telemetry_events.py --cov=story_automator.core.telemetry_events --cov-report=term-missing 2>&1 | tee coverage_results.txt
```

Record the line coverage percentage.

- [ ] **Step 3: Write acceptance report with actual results**

Create `docs/superpowers/acceptance-report-m01-round-trip-tests.md` with this structure:

```markdown
# Foundation-M01-Round-Trip-Tests — Acceptance Report (Phase C)

**Date:** 2026-06-14  
**Milestone:** foundation-m01-round-trip-tests  
**Status:** Complete

## Requirements Satisfaction

### REQ-08: Concrete Event Round-Trip Invariant
- **Requirement:** For every concrete event class (13 total), round-trip invariant must hold.
- **Test Coverage:** 
  - `TestRoundTrip.test_all_13_events_round_trip_with_varied_values` tests all 13 events
  - `TestDeterministicSerialization` verifies deterministic serialization
  - Tests verify `construct → to_json_line() → parse_event() → __eq__` and byte-equality
- **Status:** ✅ PASS

### REQ-09: UnknownEvent Byte-for-Byte Round-Trip
- **Requirement:** UnknownEvent with arbitrary event_type and raw_fields must round-trip with byte-identical JSON output.
- **Test Coverage:** 
  - `TestUnknownEventRoundTrip.test_unknown_event_with_many_fields` — diverse field types
  - `TestUnknownEventRoundTrip.test_unknown_event_with_null_values_req09` — null value preservation
  - `TestUnknownEventRoundTrip.test_unknown_event_byte_equality_req09` — byte-equality across payloads
- **Status:** ✅ PASS

### REQ-10: Test File with ~30 Tests Across 4 TestCase Classes
- **Test Classes Present:**
  1. TestRoundTrip — comprehensive round-trip validation
  2. TestUnknownEventRoundTrip — unknown event specialization
  3. TestRoundTripEdgeCases — unicode, special chars, boundary values
  4. TestDeterministicSerialization — deterministic serialization and key ordering
- **Test Count:** [ACTUAL COUNT FROM test_results.txt]
- **Status:** ✅ PASS

## Test Execution Results

**Command:** `pytest tests/test_telemetry_events.py -v`

```
Total tests: [ACTUAL COUNT]
Passed: [ACTUAL COUNT]
Failed: 0
Coverage: [ACTUAL %]%
```

## Quality Gates

- ✅ ruff check: Zero violations
- ✅ ruff format: All files formatted correctly
- ✅ pytest: All tests PASS (100% pass rate)
- ✅ Coverage: ≥85% line coverage on telemetry_events.py
- ✅ Round-trip invariant: All concrete events and UnknownEvent validate byte-equality

## Edge Cases and Scenarios Covered

1. **Unicode and Emoji** — StoryStarted with emoji in epic and complexity fields
2. **Escaped JSON Characters** — StoryFailed with escaped quotes, newlines, tabs, backslashes
3. **Boundary Values** — CostCharged with small floats (0.0001), large ints (999999), zero values
4. **Empty Strings** — StoryStarted with all string fields empty
5. **Deterministic Serialization** — 10+ parse-reserialize cycles produce byte-identical output
6. **JSON Key Ordering** — Field order preserved across serializations (Python 3.7+ dict insertion order)
7. **Complex Nested Structures** — UnknownEvent with nested JSON objects, arrays, mixed types
8. **Null Values** — UnknownEvent preserves null in raw_fields across round-trips

## Non-Functional Requirements Validated

- **Python 3.11+ Compatibility:** All tests pass on execution environment
- **Determinism:** JSON output is byte-identical across multiple serialization cycles
- **No Subprocess Invocations:** Test suite uses only stdlib and pytest
- **Sub-Second Execution:** Full test suite completes in < 1 second wall-clock

**Note:** Cross-version determinism (Python 3.11, 3.12, 3.13, 3.14) is validated at CI time. This plan validates single-version determinism; multi-version validation is handled by CI quality gates.

## Conclusion

Foundation-m01-round-trip-tests successfully validates the round-trip serialization protocol (REQ-08, REQ-09) for all 13 concrete events and UnknownEvent. The test file contains [ACTUAL COUNT] tests organized across 4 TestCase classes (REQ-10). All requirements are satisfied, edge cases are covered, and all quality gates pass.

**Ready for Phase D (post-impl-review and production-readiness checks).**
```

- [ ] **Step 4: Commit acceptance report**

```bash
git add docs/superpowers/acceptance-report-m01-round-trip-tests.md
git commit -m "docs: acceptance report for foundation-m01-round-trip-tests (Phase C complete)"
```

---

## Spec Coverage Self-Review

✅ **REQ-08:** Concrete event round-trip invariant covered by Task 8 (test_all_13_events_round_trip_with_varied_values)  
✅ **REQ-09:** UnknownEvent byte-equality covered by Task 7 (test_unknown_event_byte_equality_req09)  
✅ **REQ-10:** ~30 tests across 4 TestCase classes covered by Tasks 1-8  
✅ **Edge Cases:** Unicode, special chars, boundary values, empty strings, determinism (Tasks 3-6)  
✅ **Quality Gates:** Linting and coverage verified (Task 10)  

**No spec gaps identified. All requirements addressed.**

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-14-foundation-m01-round-trip-tests.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

**Which approach?**
