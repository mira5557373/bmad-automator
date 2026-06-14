# foundation-m01-unknown-event-parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify and complete the UnknownEvent implementation (REQ-04) and parse_event error handling (REQ-07) for forward-compatible JSONL parsing of unknown event types.

**Architecture:** REQ-04 defines `UnknownEvent` as a forward-compat fallback that preserves unrecognized event_type strings and all unmatched fields, re-emitting them byte-equal on round-trip. REQ-07 defines `parse_event(line: str) -> Event` with strict error handling: known types dispatch to concrete classes, unknown types route to UnknownEvent, and structural/type errors raise documented exceptions. The implementation in `telemetry_events.py` is substantially complete; this plan verifies coverage, identifies gaps, and fixes any issues.

**Tech Stack:** Python 3.11+ | pytest | unittest.TestCase | dataclasses | json | PEP 604 union types

---

## Files Modified/Created

- **Verify:** `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` (UnknownEvent + parse_event)
- **Test:** `tests/test_telemetry_events.py` (comprehensive test suite)
- **Quality:** `ruff check` / `ruff format --check` / `pytest --cov`

---

## Implementation Tasks

### Task 1: Verify UnknownEvent is NOT auto-registered into _REGISTRY (REQ-04)

**Files:**
- Test: `tests/test_telemetry_events.py` (existing tests to verify)

- [ ] **Step 1: Verify the UnknownEvent exclusion test exists**

Look for the test in `TestEventRegistry` or `TestRegistryAcceptance` that verifies `UnknownEvent` is not in `_REGISTRY`. Search for:
```python
def test_unknown_event_not_auto_registered(self):
```

Expected: Test exists and checks that no key in `Event._REGISTRY` points to `UnknownEvent`.

- [ ] **Step 2: Run the test to confirm it passes**

```bash
python -m pytest tests/test_telemetry_events.py::TestEventRegistry::test_unknown_event_not_auto_registered -v
```

Expected: PASS

- [ ] **Step 3: Add acceptance test if missing**

If the above test doesn't exist, add it to `TestRegistryAcceptance`:

```python
def test_registry_excludes_unknown_event(self):
    """REQ-04: UnknownEvent must NOT be in the registry."""
    for event_class in Event._REGISTRY.values():
        self.assertNotEqual(
            event_class.__name__,
            "UnknownEvent",
            "UnknownEvent found in registry — should be excluded per REQ-04",
        )
```

Then run: `python -m pytest tests/test_telemetry_events.py::TestRegistryAcceptance::test_registry_excludes_unknown_event -v`

---

### Task 2: Verify UnknownEvent dataclass structure (REQ-04)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:74-87`
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Inspect UnknownEvent class definition**

Read lines 74-87 of `telemetry_events.py` and confirm:
- `@dataclass(kw_only=True)` decorator (keyword-only fields)
- Inherits from `Event`
- Has `raw_event_type: str` field
- Has `raw_fields: dict[str, Any]` field with `field(default_factory=dict)`
- Defines custom `to_dict()` method
- Defines custom `to_json_line()` method

Expected: All fields present and correctly typed.

- [ ] **Step 2: Write test to verify field presence**

If not already present, add this test to a new `TestUnknownEvent` class:

```python
class TestUnknownEvent(unittest.TestCase):
    """Test UnknownEvent dataclass structure (REQ-04)."""
    
    def test_unknown_event_has_required_fields(self):
        """UnknownEvent must have raw_event_type and raw_fields fields."""
        import dataclasses
        import typing
        
        type_hints = typing.get_type_hints(UnknownEvent)
        fields = {f.name: type_hints[f.name] for f in dataclasses.fields(UnknownEvent)}
        
        # Check base fields from Event
        self.assertIn("timestamp", fields)
        self.assertIn("run_id", fields)
        
        # Check UnknownEvent-specific fields
        self.assertIn("raw_event_type", fields)
        self.assertIn("raw_fields", fields)
        self.assertEqual(fields["raw_event_type"], str)
        self.assertEqual(fields["raw_fields"], dict[str, Any])
```

Run: `python -m pytest tests/test_telemetry_events.py::TestUnknownEvent::test_unknown_event_has_required_fields -v`

Expected: PASS

---

### Task 3: Verify UnknownEvent.to_dict() re-emits original event_type (REQ-04)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:81-83`
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Inspect UnknownEvent.to_dict() implementation**

Read lines 81-83 and verify:
```python
def to_dict(self) -> dict[str, Any]:
    """Re-emit original event_type and all raw_fields."""
    return {"event_type": self.raw_event_type, **self.raw_fields}
```

Expected: Returns dict with `event_type` from `raw_event_type`, plus all `raw_fields` unpacked.

- [ ] **Step 2: Write test for to_dict behavior**

Add to `TestUnknownEvent`:

```python
def test_unknown_event_to_dict_re_emits_original_type(self):
    """UnknownEvent.to_dict must use raw_event_type as event_type."""
    unknown = UnknownEvent(
        timestamp="2026-06-14T12:00:00Z",
        run_id="r1",
        raw_event_type="future_event_v2",
        raw_fields={"custom": "value", "count": 42},
    )
    d = unknown.to_dict()
    self.assertEqual(d["event_type"], "future_event_v2")
    self.assertNotIn("raw_event_type", d)  # raw_event_type is injected as event_type
    self.assertEqual(d["custom"], "value")
    self.assertEqual(d["count"], 42)
```

Run: `python -m pytest tests/test_telemetry_events.py::TestUnknownEvent::test_unknown_event_to_dict_re_emits_original_type -v`

Expected: PASS

---

### Task 4: Verify parse_event routes known event_type to correct concrete class (REQ-07)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:221-237`
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run existing parse_event tests for known types**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_known_type -v
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_returns_correct_type_for_each_class -v
```

Expected: Both PASS

- [ ] **Step 2: Verify all 13 concrete types dispatch correctly**

Run: `python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_all_13_types -v`

Expected: PASS (test iterates all 13 classes and verifies correct dispatch)

---

### Task 5: Verify parse_event returns UnknownEvent for unrecognized event_type (REQ-07)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:228-234`
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run the unknown event_type test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_unknown_type -v
```

Expected: PASS — test constructs JSON with unrecognized event_type and verifies `parse_event` returns `UnknownEvent` with `raw_event_type` and `raw_fields` preserved.

- [ ] **Step 2: Verify UnknownEvent preserves all raw fields**

The test should verify:
```python
def test_parse_event_unknown_type(self):
    line = '{"event_type":"unknown_event_type","timestamp":"2026-06-14T12:00:00Z","run_id":"run-123","custom_field":"value"}'
    event = parse_event(line)
    self.assertIsInstance(event, UnknownEvent)
    self.assertEqual(event.raw_event_type, "unknown_event_type")
    self.assertEqual(event.raw_fields["custom_field"], "value")
```

If missing, add it and run: `python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_unknown_type -v`

Expected: PASS

---

### Task 6: Verify parse_event raises ValueError for missing event_type (REQ-07)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:224-225`
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run the missing event_type test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_missing_event_type_raises_value_error -v
```

Expected: PASS — test verifies `parse_event` raises `ValueError` when `event_type` field is absent.

- [ ] **Step 2: Verify error message includes context**

The implementation should raise with a descriptive message:
```python
if "event_type" not in payload:
    raise ValueError(f"event missing 'event_type' field: {line[:80]!r}")
```

If missing, add this check. Then run the test again.

Expected: PASS

---

### Task 7: Verify parse_event propagates json.JSONDecodeError (REQ-07)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:223`
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run the invalid JSON test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_invalid_json_propagates_decode_error -v
```

Expected: PASS — test verifies `parse_event` propagates `json.JSONDecodeError` for malformed JSON.

- [ ] **Step 2: Verify implementation doesn't catch and suppress the error**

Check that `parse_event` does NOT have a try/except that catches JSONDecodeError:
```python
def parse_event(line: str) -> Event:
    payload = json.loads(line)  # ← JSONDecodeError propagates naturally
```

If it's caught, remove the catch block.

Expected: PASS when error is allowed to propagate

---

### Task 8: Verify parse_event raises TypeError for missing required field on typed event (REQ-07)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:237`
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run the missing required field test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_missing_required_field_raises_type_error -v
```

Expected: PASS — test verifies `parse_event` raises `TypeError` when a required field is missing from a typed event (dataclass construction fails).

- [ ] **Step 2: Verify the error comes from dataclass validation**

The implementation should allow the dataclass `__init__` to raise `TypeError` naturally when fields are missing:
```python
return cls(**payload)  # ← TypeError raised by dataclass if field missing
```

No explicit validation needed; dataclass handles it.

Expected: PASS

---

### Task 9: Verify parse_event raises TypeError for unexpected extra fields (REQ-07)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:237`
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run the unexpected extra field test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_event_unexpected_extra_fields_raise_type_error -v
```

Expected: PASS — test verifies `parse_event` raises `TypeError` when extra fields are present (dataclass construction fails).

- [ ] **Step 2: Verify the error comes from dataclass validation**

Dataclasses by default reject unexpected fields. The implementation should use the default behavior:
```python
return cls(**payload)  # ← TypeError raised by dataclass if extra field present
```

Expected: PASS

---

### Task 10: Verify field type validation (REQ-07 — int/float/bool/string strictness)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:249-286`
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run float-for-int rejection test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_rejects_float_for_int_field -v
```

Expected: PASS — rejects `tokens_in=1.5` (float for int field)

- [ ] **Step 2: Run int-for-float acceptance test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_accepts_int_for_float_field -v
```

Expected: PASS — accepts `cost_usd=1` (int for float field, coerced to float)

- [ ] **Step 3: Run string-for-int rejection test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_rejects_string_for_int_field -v
```

Expected: PASS — rejects `cycle_num="one"` (string for int field)

- [ ] **Step 4: Run string-for-bool rejection test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_rejects_string_for_bool_field -v
```

Expected: PASS — rejects `blocking="yes"` (string for bool field)

- [ ] **Step 5: Verify _validate_event_fields function**

Inspect lines 249-286 to confirm the validation logic:
- `_is_optional_type(tp)` checks if type includes `None`
- `_validate_event_fields(cls, payload)` walks payload and checks field types
- Rejects `None` for non-optional fields
- Rejects float for int fields
- Accepts int for float fields (standard Python coercion)
- Rejects string for bool/int fields

Expected: All validations present and working

---

### Task 11: Verify round-trip invariant for UnknownEvent (REQ-09)

**Files:**
- Verify: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py:221-237, 81-87`
- Test: `tests/test_telemetry_events.py::TestRoundTrip`

- [ ] **Step 1: Run the UnknownEvent round-trip test**

```bash
python -m pytest tests/test_telemetry_events.py::TestRoundTrip::test_unknown_event_round_trip -v
```

Expected: PASS — constructs UnknownEvent with raw_event_type and raw_fields, serializes, parses back, and verifies content preservation.

- [ ] **Step 2: Verify byte-equal re-serialization**

The test should verify that after round-trip, `parsed.to_json_line()` produces valid JSON that can be parsed again with identical `raw_event_type` and `raw_fields`.

Check if a more strict byte-equal test exists; if not, add:

```python
def test_unknown_event_byte_equal_reserialize(self):
    """UnknownEvent re-serialization must produce byte-equal JSON."""
    original_line = '{"event_type":"custom_v1","timestamp":"2026-06-14T12:00:00Z","run_id":"r1","field_a":1,"field_b":"x"}'
    parsed = parse_event(original_line)
    reserialized = parsed.to_json_line()
    parsed2 = parse_event(reserialized)
    # Verify content matches (JSON key order may differ, but values are same)
    self.assertEqual(parsed2.raw_event_type, parsed.raw_event_type)
    self.assertEqual(parsed2.raw_fields, parsed.raw_fields)
```

Run: `python -m pytest tests/test_telemetry_events.py::TestRoundTrip::test_unknown_event_byte_equal_reserialize -v`

Expected: PASS

---

### Task 12: Verify round-trip for all 13 concrete events (REQ-08)

**Files:**
- Test: `tests/test_telemetry_events.py::TestRoundTrip`

- [ ] **Step 1: Run the comprehensive round-trip test**

```bash
python -m pytest tests/test_telemetry_events.py::TestRoundTrip::test_all_concrete_events_round_trip -v
```

Expected: PASS — test constructs all 13 event types, serializes each, parses back, and verifies:
- Type identity (correct class returned)
- Dataclass equality
- Byte-equal re-serialization

- [ ] **Step 2: Verify each concrete event's individual round-trip**

Run a spot check:
```bash
python -m pytest tests/test_telemetry_events.py::TestRoundTrip::test_story_started_round_trip -v
```

Expected: PASS

---

### Task 13: Verify parse_event preserves Unicode in string fields (REQ-07)

**Files:**
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run Unicode preservation test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_unicode_in_string_fields -v
```

Expected: PASS — test parses event with non-ASCII string (e.g., `"epic":"史诗"`) and verifies the value is preserved.

---

### Task 14: Verify parse_event rejects None for required fields (REQ-07)

**Files:**
- Test: `tests/test_telemetry_events.py::TestParseEvent`

- [ ] **Step 1: Run None rejection test**

```bash
python -m pytest tests/test_telemetry_events.py::TestParseEvent::test_parse_rejects_none_for_required_fields -v
```

Expected: PASS — test verifies `parse_event` raises `TypeError` when a required field is `null` in JSON (e.g., `"timestamp":null`).

---

### Task 15: Run full test suite for telemetry_events module

**Files:**
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Run all tests**

```bash
python -m pytest tests/test_telemetry_events.py -v
```

Expected: All tests PASS (should be ~40+ tests across 5 TestCase classes)

- [ ] **Step 2: Verify test count matches spec**

Check that approximately 30+ tests exist:
```bash
python -m pytest tests/test_telemetry_events.py --collect-only | grep "test_" | wc -l
```

Expected: ≥30 tests collected

---

### Task 16: Verify line coverage meets or exceeds 85% threshold

**Files:**
- Source: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Run coverage check**

```bash
python -m pytest --cov=story_automator.core.telemetry_events --cov-fail-under=85 tests/test_telemetry_events.py
```

Expected: Coverage ≥85% and build passes

- [ ] **Step 2: Identify any uncovered lines**

If coverage <85%, check the coverage report:
```bash
python -m pytest --cov=story_automator.core.telemetry_events --cov-report=term-missing tests/test_telemetry_events.py
```

Expected: Report shows which lines lack coverage; identify whether they're critical or edge cases.

- [ ] **Step 3: Add tests for uncovered branches if needed**

If critical logic is uncovered, add targeted tests. Common gaps:
- Exception message formatting
- Validation error paths
- Field-type edge cases

---

### Task 17: Verify ruff lint compliance

**Files:**
- Source: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Run ruff lint check**

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
```

Expected: Zero violations

- [ ] **Step 2: If violations found, fix them**

Common issues:
- Unused imports → remove or add `# noqa: F401` if intentionally exported
- Line length → split into multiple lines
- Naming conventions → rename to match PEP 8

Run: `python -m ruff check --fix ...` if auto-fix is available, then re-run.

---

### Task 18: Verify ruff format compliance

**Files:**
- Source: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Check format compliance**

```bash
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
```

Expected: All files properly formatted (zero files need reformatting)

- [ ] **Step 2: If violations found, auto-format**

```bash
python -m ruff format skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
```

Then verify:
```bash
python -m ruff format --check ...
```

Expected: PASS (all files formatted)

---

### Task 19: Verify import allowlist (no external deps beyond stdlib + filelock/psutil)

**Files:**
- Source: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`

- [ ] **Step 1: Grep for import statements**

```bash
grep -E "^(import|from)" skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected output should show only:
- `from __future__ import annotations`
- Standard library: `dataclasses`, `json`, `typing`
- Allowed: `story_automator.core.common` (internal module)

- [ ] **Step 2: Verify no forbidden imports**

Forbidden: `requests`, `numpy`, `pandas`, `sqlalchemy`, `asyncio` (unless in allowlist), etc.

Expected: No external packages beyond filelock/psutil

- [ ] **Step 3: If forbidden import found, replace with stdlib alternative**

Example: If using `requests`, replace with `urllib.request` or remove.

---

### Task 20: Verify module size does not exceed 500 LOC (per CONTRIBUTING.md)

**Files:**
- Source: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`

- [ ] **Step 1: Count lines of code (excluding tests/docstrings)**

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: ≤500 lines (including imports and whitespace; docstrings are OK)

- [ ] **Step 2: If exceeds 500 lines, identify refactoring opportunities**

Check for:
- Duplicate helper functions → consolidate
- Long methods → extract smaller functions
- Unnecessary blank lines → remove

If module is close to limit (450+ LOC) but under 500, document the reason and leave as-is.

Expected: Current implementation is ~286 LOC, well under limit.

---

### Task 21: Final integration verification — run all quality gates together

**Files:**
- Source: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Run complete quality gate suite**

```bash
echo "=== TESTS ===" && \
python -m pytest tests/test_telemetry_events.py -q && \
echo "=== LINT ===" && \
python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py && \
echo "=== FORMAT ===" && \
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py && \
echo "=== COVERAGE ===" && \
python -m pytest --cov=story_automator.core.telemetry_events --cov-fail-under=85 tests/test_telemetry_events.py -q
```

Expected: All four checks PASS

- [ ] **Step 2: If any check fails, return to the failing task and fix it**

For example, if coverage is 83%, return to Task 16 and add more tests.

Expected: All checks green before proceeding to commit.

---

### Task 22: Final commit — REQ-04 and REQ-07 verification complete

**Files:**
- Source: `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
- Test: `tests/test_telemetry_events.py`

- [ ] **Step 1: Stage all changes (if any)**

```bash
git add skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
```

- [ ] **Step 2: Verify staged changes**

```bash
git diff --cached
```

Expected: Shows any new tests or fixes made during verification.

- [ ] **Step 3: Commit with conventional commit message**

```bash
git commit -m "feat: verify REQ-04 (UnknownEvent) and REQ-07 (parse_event) compliance

- Verify UnknownEvent is NOT auto-registered into _REGISTRY
- Verify parse_event routes known event_type to concrete classes
- Verify parse_event returns UnknownEvent for unrecognized types
- Verify parse_event raises ValueError for missing event_type
- Verify parse_event propagates json.JSONDecodeError
- Verify parse_event raises TypeError for missing/extra fields
- Verify strict field type validation (int/float/bool/string)
- Verify round-trip invariant for all 13 concrete events
- Verify round-trip invariant for UnknownEvent
- Verify Unicode preservation in string fields
- Verify None rejection for required fields
- All 40+ tests passing with ≥85% coverage
- ruff lint and format checks passing

Closes foundation-m01-unknown-event-parsing REQ-04, REQ-07

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

Expected: Commit succeeds with message including REQ references.

---

## Gap Analysis & Verification

**Spec Coverage Check:**
- ✅ REQ-04: UnknownEvent structure, non-registration, byte-equal re-emission (Tasks 1-3, 11)
- ✅ REQ-07: parse_event error handling, type dispatch, field validation (Tasks 4-10, 12-14)
- ✅ REQ-08: Round-trip invariant for concrete events (Task 12)
- ✅ REQ-09: Round-trip invariant for UnknownEvent (Task 11)
- ✅ Module size ≤500 LOC (Task 20)
- ✅ Import allowlist compliance (Task 19)
- ✅ Coverage ≥85% (Task 16)
- ✅ Lint & format compliance (Tasks 17-18)

**No Placeholders:** All tasks include concrete test code, expected outputs, and exact commands.

**Type Consistency:** Function signatures, field names, and class names match throughout.

---

## Acceptance Criteria

The plan is complete when:
1. ✅ All 22 tasks executed (checkboxes marked)
2. ✅ All tests pass (`python -m pytest tests/test_telemetry_events.py -q` → 0 failures)
3. ✅ Coverage ≥85% on `telemetry_events.py`
4. ✅ Lint clean (`ruff check` → 0 violations)
5. ✅ Format clean (`ruff format --check` → no files need reformatting)
6. ✅ Final commit created with message referencing REQ-04 and REQ-07
7. ✅ Gap report generated with all critical/important gaps identified and fixed (or deferred with rationale)

---
