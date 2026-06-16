# M01-M4 — Tests and Quality Gates (REQ-08, REQ-09, REQ-10, REQ-11, NFR, Quality Gates) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the M01 wedge atom's final slice: (a) broaden the REQ-08 round-trip sweep beyond the m01-m3 per-class happy-path fixtures to cover unicode, JSON-special characters, and numeric/boolean edge cases; (b) broaden the REQ-09 `UnknownEvent` byte-equal sweep beyond the single m01-m3 fixture to cover arbitrary unrecognized `event_type` strings and arbitrary JSON-primitive `raw_fields` shapes; (c) codify the four quality gates that have no in-suite representation today — import-allowlist (REQ-11), module-size (NFR), PEP 604 union-type policy (NFR), and a documenting `FieldTypeTests` class (REQ-10's fourth design class); (d) verify the operator-runnable gates (`ruff check`, `ruff format --check`, `pytest --cov-fail-under=85`, `python -m unittest tests.test_telemetry_events`) all pass on the assembled module + test file.

**Architecture:** Pure-test additions plus four new in-suite gate test classes. No source change to `core/telemetry_events.py` — the 13 concrete classes, the registry, the parser, and the helper imports are all complete from m01-m1/m01-m2/m01-m3. The new test sweeps reuse `ConcreteEventRoundTripTests._round_trip` (already private on that class) via a thin module-level helper or by re-importing it; this plan duplicates the round-trip logic into each new test class to keep each class self-contained (no cross-class state coupling). The gate tests use **only stdlib `ast`, `inspect`, `pathlib`** to introspect the module — no subprocess, no network, no third-party libs.

**Tech Stack:** Python 3.11+ (`requires-python` in `pyproject.toml`). Stdlib only — `ast`, `inspect`, `json`, `pathlib`, `unittest` — no new third-party deps. Tests use `unittest.TestCase` per project convention. Mixed `assert` and `self.assertEqual` are both acceptable (matches existing style). Total wall-clock budget: under one additional second (REQ-NFR).

**Slice scope:** This plan covers **m01-m4-tests-and-quality-gates ONLY**: REQ-08 broader sweep + REQ-09 broader sweep + REQ-10 fourth-class addition + REQ-11 allowlist gate + NFR module-size + NFR PEP 604 + the operator-gate verification (ruff, coverage, multi-Python sanity). It does **NOT** add `TelemetryEmitter` (M02), `TelemetryReader` (M02), cost-capture wiring (M03), HMAC chaining (M04), or typed enums (M07). It does **NOT** modify the M01 source module — every change in this slice lives in `tests/test_telemetry_events.py` plus one optional ruff-config touch on `pyproject.toml` (see Task 11 / gap-analysis note). It does **NOT** add an external CI script; the gates are codified as in-suite tests where natural and as documented operator-runnable commands where in-suite testing is infeasible (ruff, coverage).

**Parent artifacts:**
- Spec: `docs/superpowers/specs/2026-06-14-m01-event-types.md` (focus on REQ-08, REQ-09, REQ-10, REQ-11, NFR, Quality gates)
- Design doc: `docs/superpowers/specs/2026-06-14-m01-event-types-design.md` (the test plan section names `EventBaseTests`, `ConcreteEventRoundTripTests`, `ParseEventTests`, `FieldTypeTests` — only `FieldTypeTests` is missing today)
- Parent plan (full M01): `docs/superpowers/plans/2026-06-14-m01-event-types.md`
- Predecessor slices:
  - `docs/superpowers/plans/2026-06-14-m01-m1-event-base.md`
  - `docs/superpowers/plans/2026-06-14-m01-m2-event-parsing.md`
  - `docs/superpowers/plans/2026-06-14-m01-m3-concrete-events.md`
- Workflow milestone: `.claude/workflow.json` → `m01-m4-tests-and-quality-gates`

---

## Prior Work Handling (READ BEFORE TASK 1)

The baseline at the start of this slice (verified by Task 1's site inventory grep) is:

- `tests/test_telemetry_events.py` contains **66 tests across 17 `TestCase` classes**, all passing under `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v`.
- `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` is **347 lines** (well under the 500-line NFR).
- `python -m ruff check` and `python -m ruff format --check` on both files report zero violations.
- `Event._REGISTRY` contains exactly 13 production entries after import; `UnknownEvent` is excluded.

A prior commit may have bundled some of m01-m4's content. Each subagent dispatched for Tasks 2–13 must run a **2-line existence probe** at task start:

1. **Probe for the new TestCase class name** in `tests/test_telemetry_events.py` (use `grep -n "^class <ClassName>" tests/test_telemetry_events.py`).
2. **Branch:**
   - **Class absent (clean state):** follow the task's TDD-style flow literally. Step 2 should FAIL (or PASS-on-empty for verification-style tests — see each task's "Step 2 expected" line). Step 4 should PASS.
   - **Class already present (pre-existing work):** at Step 2 run the test class alone and expect **PASS** (this verifies the existing implementation is correct). Skip Step 3 (no test addition needed). At Step 4 re-run the full suite — still PASS. At Step 5, **do NOT commit** (the work is already committed in a prior bundle); record this in the executor log as `task-N: verified pre-existing implementation, no commit`. Skip to the next task.

**Why this matters:** under subagent-driven execution each task is dispatched to a fresh agent that does not see this orchestrator-level context. The adaptation protocol must be encoded **in the plan** so each subagent reads it before its own task. Inline execution (single session) preserves context naturally and can apply the protocol once at Task 1.

**Test-count math at the end of this slice (clean path):** 66 (baseline) + 4 (REQ-08 sweep) + 3 (REQ-09 sweep) + 4 (FieldTypeTests) + 2 (ImportAllowlistTests) + 2 (ModuleSizeTests) + 2 (PEP604UnionTypesTests) = **83 tests**. Tasks 11–13 are operator-verification gates with no in-suite delta.

---

## File Structure

| Path | Kind | Responsibility (this slice) |
|---|---|---|
| `tests/test_telemetry_events.py` | MODIFY | Append six new `TestCase` classes: `ConcreteEventRoundTripExtendedTests`, `UnknownEventExtendedRoundTripTests`, `FieldTypeTests`, `ImportAllowlistTests`, `ModuleSizeTests`, `PEP604UnionTypesTests`. All append above the `if __name__ == "__main__":` line. |
| `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` | NO CHANGE | The module is feature-complete from m01-m1/m01-m2/m01-m3. This slice is test-only. |
| `pyproject.toml` (optional, Task 11 / gap analysis) | NO CHANGE in baseline | The spec REQ-11 wording assumes a `dependencies` declaration in pyproject.toml; in fact the allowlist is documented in CLAUDE.md only. This plan does NOT alter pyproject.toml — the gap analysis flags the spec/reality mismatch; the in-suite import-allowlist gate enforces the contract regardless. |

**Out of scope (DO NOT add in this slice):**
- `TelemetryEmitter` (locked JSONL writer) — M02.
- `TelemetryReader` aggregations — M02.
- Wiring existing log sites — M02.
- Cost-capture path on Haiku parser output — M03.
- HMAC chaining — M04 (separate substrate).
- Typed enums (`severity`, `error_class`, `reason`, `phase`) — M07.
- Timestamp-format validation at parse time — M02 or later.
- A new ruff configuration in `pyproject.toml` — current ruff defaults pass cleanly; adding one is scope creep (gap analysis flags but defers).
- An external CI script — out of scope per the spec's quality-gates section, which lists operator-runnable commands not pipeline files.

## Conventions

- Every new test class lives in `tests/test_telemetry_events.py`, **above** the `if __name__ == "__main__":` line (line ~1006 currently, will drift downward as classes append).
- Class-level docstrings begin with the requirement they verify (e.g., `"""REQ-08 broader sweep: ..."""`).
- Inside each test class, imports of `Event` / `StoryStarted` / etc. happen **inside** each test method to match the existing pattern (lazy import is the project's convention for this file — see m01-m1 `EventBaseTests` and m01-m3 `ConcreteEventRoundTripTests`).
- `from __future__ import annotations` is already at the top of `tests/test_telemetry_events.py` — do not duplicate.
- Tests must NOT mutate `Event._REGISTRY`. If a test requires a temporary subclass, it inherits `_RegistryIsolationMixin` (defined at the top of the test file by m01-m1). None of the m01-m4 tests planned below need to mutate the registry — they exercise the production 13 classes and `UnknownEvent` only.
- Conventional Commits with `Generated-By: claude-opus-4-7` trailer. One commit per task where a commit is performed (the commit message is provided verbatim in each task's final step).

## Test runner commands (cross-platform)

| Action | Command (Windows git-bash / WSL / Linux all OK) |
|---|---|
| Run this slice's tests only | `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v` |
| Run a single new test class | `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ImportAllowlistTests -v` |
| Lint new+modified files | `python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` |
| Format check | `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py` |
| Coverage (Task 10) | `PYTHONPATH=skills/bmad-story-automator/src python -m coverage run --source=story_automator.core.telemetry_events -m unittest tests.test_telemetry_events && python -m coverage report -m --include="*/telemetry_events.py" --fail-under=85` |
| Full Python suite still passes | `npm run test:python` |

The `python` command on Windows resolves to Python 3.14 at `/c/Python314/python`; on WSL/Linux it resolves to whatever `python3` is configured (3.11/3.12/3.13). REQ-01's multi-version import-cleanliness criterion remains satisfied — all new code is stdlib-only and uses no version-gated features beyond what m01-m1/m01-m2/m01-m3 already require.

**Coverage runner note (Task 12):** the spec lists `pytest --cov` as the canonical command but pytest+coverage may not be installed on the operator's Windows machine; CLAUDE.md lists "stdlib `coverage` package (operator-installed, not a project dep)" as the coverage tool. The plan uses `python -m coverage` directly (no pytest dependency) so the same command runs on every supported environment. The acceptance criterion is identical: ≥85% line coverage on `core/telemetry_events.py`.

## BLOCKED protocol

If any step produces unexpected output:
1. Stop. Do NOT proceed to the next step.
2. Capture the exact command, full stdout, full stderr, exit code.
3. Report: `BLOCKED at Task N Step S: <one-line summary>. Command: ..., Expected: ..., Actual: ...`
4. Wait for guidance before resuming.

Common blockers anticipated for this slice:
- **Import-allowlist false positive:** if a future refactor adds a new `from .something import ...` and the allowlist test naively rejects all relative imports, the test must be updated to allow relative imports from `story_automator.core.*` (Task 8 implements this allowance correctly — see code).
- **Module-size off-by-one:** `Path.read_text().splitlines()` counts logical lines (no trailing-newline artifact); if a future change uses `Path.read_text().count("\n")` instead, the count may differ by one for files ending with no final newline. Task 9 uses `splitlines()` to match the canonical NFR phrasing of "source lines."
- **Coverage shortfall:** if a future change adds an unreached branch to `core/telemetry_events.py`, Task 12 will report < 85%. This is a real failure, not a tooling issue — fix the underlying gap (add a test) before declaring the slice complete.
- **Ruff version drift:** if `ruff` is upgraded mid-slice and a new default rule fires, the lint gate fails. Fix by addressing the rule (or, if it's a false positive in this codebase, document the suppression in `pyproject.toml` under `[tool.ruff.lint.per-file-ignores]`). Adding a ruff config is **scope creep** for m01-m4 — flag and ask the operator before proceeding.

---

## Task 1: Site inventory — confirm prerequisites and baseline state

**Files:** None modified — verification only.

- [ ] **Step 1: Confirm m01-m3's surface is in place**

Run:

```bash
grep -nE "^class (StoryStarted|StoryCompleted|StoryFailed|StoryDeferred|RetryAttempt|EscalationTriggered|ReviewCycle|RetroFired|TmuxSessionSpawned|TmuxSessionCompleted|TmuxSessionCrashed|CostCharged|BudgetAlert)\b" \
  skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: exactly 13 matches, one per concrete event class. If fewer than 13 or any are missing, m01-m3 did not land cleanly — **BLOCKED**.

- [ ] **Step 2: Confirm baseline test suite is green (count in resumable range)**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events 2>&1 | tail -3
```

Expected: `Ran N tests in 0.0XXs` with `N` **in the inclusive range [66, 83]**, followed by `OK`.

The range exists because m01-m4 may have been partially executed in a prior bundle:
- `N == 66` — clean m01-m3-finish baseline (no m01-m4 tasks landed yet).
- `66 < N < 83` — some m01-m4 tasks already committed; apply the **Prior Work Handling protocol** (see top of plan) per task in Tasks 2–7.
- `N == 83` — all in-suite m01-m4 tasks already landed; Tasks 2–7 will short-circuit via the protocol and the slice continues with operator-runnable verification gates (Tasks 8–13).

If `N < 66`, m01-m3 did not land cleanly — **BLOCKED**.
If `N > 83`, work outside this slice's scope has been added — **BLOCKED**, investigate.
If any test fails (status not `OK`) — **BLOCKED** regardless of count.

- [ ] **Step 3: Confirm baseline module LOC under 500**

Run:

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected: a count ≤ 500 (current baseline: 347). If > 500, the module has grown past the NFR — **BLOCKED**, must investigate before adding more tests.

- [ ] **Step 4: Confirm ruff lint and format both currently pass**

Run (in parallel if your shell supports it; sequential is fine):

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
```

Expected for each: `All checks passed!` and `2 files already formatted`. If either fails, the baseline is unclean — **BLOCKED**.

- [ ] **Step 5: Confirm the six new test class names are NOT yet present**

Run:

```bash
grep -nE "^class (ConcreteEventRoundTripExtendedTests|UnknownEventExtendedRoundTripTests|FieldTypeTests|ImportAllowlistTests|ModuleSizeTests|PEP604UnionTypesTests)\b" \
  tests/test_telemetry_events.py
```

Expected (clean state): zero matches. **If any are present**, a prior commit has bundled some m01-m4 work; apply the Prior Work Handling protocol at the top of this plan for each present class as Tasks 2–10 are dispatched.

No commit for this task — verification gate only. Proceed to Task 2.

---

## Task 2: REQ-08 broader sweep — `ConcreteEventRoundTripExtendedTests` class with unicode in string fields

**Files:**
- Modify: `tests/test_telemetry_events.py`

REQ-08 says the round-trip invariant must hold "for every concrete event class." m01-m3 verified the happy path with ASCII fixtures (13 tests). m01-m4 broadens to confirm that unicode and special characters preserve byte-equal through `compact_json` (which uses `ensure_ascii=False`) and back through `json.loads`.

- [ ] **Step 1: Append the test class skeleton with the first test method**

Append the following to `tests/test_telemetry_events.py`, immediately above the `if __name__ == "__main__":` line:

```python
class ConcreteEventRoundTripExtendedTests(unittest.TestCase):
    """REQ-08 broader sweep: round-trip holds under unicode, JSON-special
    characters, and numeric / boolean edge cases.

    m01-m3 verified the per-class happy path with ASCII fixtures. This
    class broadens the verification to confirm that `compact_json`'s
    `ensure_ascii=False` policy preserves unicode in string fields
    byte-equal, that JSON-special characters in strings are escaped and
    parsed back identically, and that integer / float / boolean
    boundary values survive the serialization round-trip without drift.
    """

    def _round_trip(self, event: Event) -> None:
        from story_automator.core.telemetry_events import parse_event

        line = event.to_json_line()
        parsed = parse_event(line)
        self.assertIs(type(parsed), type(event))
        self.assertEqual(parsed, event)
        self.assertEqual(parsed.to_json_line(), line)

    def test_round_trip_preserves_unicode_in_string_fields(self) -> None:
        """REQ-08 + NFR: `compact_json(ensure_ascii=False)` must emit
        non-ASCII codepoints natively (not as `\\uXXXX` escapes), and
        parse_event must round-trip them byte-equal. Covers the operator's
        real-world case of unicode in story titles or epic names.
        """
        from story_automator.core.telemetry_events import StoryStarted

        self._round_trip(
            StoryStarted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="エピック-3",
                story_key="3.1-héllo-世界",
                agent="クロード",
                model="sonnet",
                complexity="medium",
            )
        )
```

The `_round_trip` helper is duplicated from `ConcreteEventRoundTripTests` (m01-m3) intentionally — this keeps the new class self-contained and uncoupled from the m01-m3 class's private interface. The helper is short (5 lines) and the duplication clarifies the slice boundary.

- [ ] **Step 2: Run the new test class (expect PASS on first run)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripExtendedTests -v
```

Expected: 1 test runs, passes. The implementation in `core/telemetry_events.py` already supports this through `compact_json`'s `ensure_ascii=False` — m01-m4 verifies the contract, doesn't add new code.

If FAIL: investigate `compact_json` in `core/common.py`; the `ensure_ascii=False` flag may have regressed.

- [ ] **Step 3: Append the JSON-special-characters test**

Append to the same `ConcreteEventRoundTripExtendedTests` class:

```python
    def test_round_trip_preserves_json_special_characters_in_strings(self) -> None:
        """REQ-08 + NFR: JSON-special characters (`"`, `\\`, control
        characters) must be escaped on emission and parsed back byte-
        identically. The strict-byte-equal round-trip is the contract
        that lets the JSONL stream be transported through any utf-8 pipe
        without corruption.
        """
        from story_automator.core.telemetry_events import StoryFailed

        self._round_trip(
            StoryFailed(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                error_class="CRASH",
                # Embedded double-quote, backslash, tab, and newline must all
                # round-trip exactly. json.dumps escapes them; json.loads un-
                # escapes them; the assertion is that the second emission of
                # to_json_line yields the same escape sequences.
                reason='exit code 1: "fatal" \\ stderr=foo\tbar\nline2',
                attempts=5,
                final_session="sa-foo-abc123",
            )
        )
```

- [ ] **Step 4: Append the numeric edge cases test**

Append:

```python
    def test_round_trip_preserves_numeric_edge_cases(self) -> None:
        """REQ-08 + NFR: integer / float boundary values (zero, negative,
        large, fractional) must survive the round-trip. ``json.dumps``
        emits ``0`` for int zero and ``0.0`` for float zero — distinct
        wire forms — so the round-trip preserves both type identity and
        byte representation.
        """
        from story_automator.core.telemetry_events import StoryCompleted

        self._round_trip(
            StoryCompleted(
                timestamp="2026-06-14T05:12:34Z",
                run_id="20260614-051234",
                epic="3",
                story_key="3.1",
                duration_s=0.0,
                cost_usd=999_999.123456,
                tokens_in=0,
                tokens_out=2_147_483_648,
                attempts=1,
            )
        )
```

- [ ] **Step 5: Append the boolean both-values test**

Append:

```python
    def test_round_trip_preserves_boolean_both_values(self) -> None:
        """REQ-08 + NFR: ``ReviewCycle.blocking`` is the only bool field
        in the M01 type set. Both ``True`` and ``False`` must round-trip,
        and the wire form must use lowercase JSON booleans (``true`` /
        ``false``), not the Python repr (``True`` / ``False``). This is
        guaranteed by ``json.dumps``; the test pins the behavior.
        """
        from story_automator.core.telemetry_events import ReviewCycle

        for blocking_value in (True, False):
            with self.subTest(blocking=blocking_value):
                self._round_trip(
                    ReviewCycle(
                        timestamp="2026-06-14T05:12:34Z",
                        run_id="20260614-051234",
                        epic="3",
                        story_key="3.1",
                        cycle_num=2,
                        issues_found=3,
                        blocking=blocking_value,
                    )
                )
```

- [ ] **Step 6: Run the full new class (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ConcreteEventRoundTripExtendedTests -v
```

Expected: 4 tests, all PASS. Total file count rises from 66 to 70.

- [ ] **Step 7: Run the full file (expect PASS, no regressions)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v 2>&1 | tail -3
```

Expected: `Ran 70 tests in 0.0XXs`, `OK`.

- [ ] **Step 8: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): broaden REQ-08 round-trip sweep with unicode, special chars, numeric and boolean edge cases"
```

---

## Task 3: REQ-09 broader sweep — `UnknownEventExtendedRoundTripTests` class

**Files:**
- Modify: `tests/test_telemetry_events.py`

REQ-09 says `UnknownEvent` round-trip must hold "for arbitrary unrecognized `event_type` strings and arbitrary JSON-primitive `raw_fields`." m01-m3 verified one canonical fixture (`UnknownEventByteEqualPreservationTests`). m01-m4 broadens to multiple `event_type` shapes and `raw_fields` structures.

- [ ] **Step 1: Append the test class with multiple-`event_type` parametric test**

Append above the `if __name__ == "__main__":` line:

```python
class UnknownEventExtendedRoundTripTests(unittest.TestCase):
    """REQ-09 broader sweep: byte-equal round-trip for arbitrary
    unrecognized event_type strings and arbitrary JSON-primitive
    raw_fields shapes.

    m01-m3 verified one canonical fixture; m01-m4 broadens to multiple
    event_type shapes (numeric-like, mixed-case, special chars) and
    multiple raw_fields structures (nested, empty, JSON-primitive
    leaves only).
    """

    def test_round_trip_preserves_byte_equal_across_event_type_shapes(self) -> None:
        """REQ-09: arbitrary unrecognized event_type strings must round-
        trip byte-equal. The pop-and-restore path in parse_event reads
        the event_type string opaquely — no character class is privileged
        — so any non-empty string the registry doesn't recognize routes
        to UnknownEvent and is preserved verbatim.
        """
        from story_automator.core.telemetry_events import (
            UnknownEvent,
            compact_json,
            parse_event,
        )

        candidate_event_types = (
            "future_thing_M99",
            "v2.story_started",
            "MixedCase_Event",
            "with-dashes-and_underscores",
            "with.dots.in.the.name",
            "numeric_like_42",
            "trailing_whitespace_chars",
        )
        for raw_event_type in candidate_event_types:
            with self.subTest(event_type=raw_event_type):
                original = compact_json(
                    {
                        "event_type": raw_event_type,
                        "timestamp": "2026-06-14T05:12:34Z",
                        "run_id": "20260614-051234",
                        "alpha": 1,
                    }
                )
                parsed = parse_event(original)
                self.assertIsInstance(parsed, UnknownEvent)
                self.assertEqual(parsed.raw_event_type, raw_event_type)
                self.assertEqual(parsed.to_json_line(), original)
```

- [ ] **Step 2: Append the nested-raw_fields test**

Append to the same class:

```python
    def test_round_trip_preserves_byte_equal_for_nested_raw_fields(self) -> None:
        """REQ-09: nested JSON primitives (list-of-dicts, dict-of-lists,
        bools, nulls) inside raw_fields must round-trip byte-equal. The
        UnknownEvent.to_dict implementation merges raw_fields via
        dict.update — which preserves insertion order, which `compact_json`
        re-emits in the same order — making byte-equality hold for any
        canonically-ordered input.
        """
        from story_automator.core.telemetry_events import (
            UnknownEvent,
            compact_json,
            parse_event,
        )

        original = compact_json(
            {
                "event_type": "future_thing_M99",
                "timestamp": "2026-06-14T05:12:34Z",
                "run_id": "20260614-051234",
                "nested_list_of_dicts": [
                    {"key": "value-1", "num": 1},
                    {"key": "value-2", "num": 2},
                ],
                "nested_dict_of_lists": {"odds": [1, 3, 5], "evens": [2, 4]},
                "primitive_bool": True,
                "primitive_null": None,
                "primitive_zero_int": 0,
                "primitive_zero_float": 0.0,
            }
        )
        parsed = parse_event(original)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertEqual(parsed.to_json_line(), original)
```

- [ ] **Step 3: Append the empty-raw_fields test**

Append:

```python
    def test_round_trip_preserves_byte_equal_for_empty_raw_fields(self) -> None:
        """REQ-09: UnknownEvent with empty raw_fields (only envelope +
        event_type, no payload) must round-trip byte-equal. The dict.update
        of an empty dict is a no-op; the output equals the envelope alone.
        Pins the boundary where the parser receives an unknown event_type
        without any unrecognized payload — a real possibility when an
        older codebase consumes a stream emitted by a newer one whose new
        event has no payload yet.
        """
        from story_automator.core.telemetry_events import (
            UnknownEvent,
            compact_json,
            parse_event,
        )

        original = compact_json(
            {
                "event_type": "future_thing_no_payload",
                "timestamp": "2026-06-14T05:12:34Z",
                "run_id": "20260614-051234",
            }
        )
        parsed = parse_event(original)
        self.assertIsInstance(parsed, UnknownEvent)
        self.assertEqual(parsed.raw_fields, {})
        self.assertEqual(parsed.to_json_line(), original)
```

- [ ] **Step 4: Run the new class (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.UnknownEventExtendedRoundTripTests -v
```

Expected: 3 tests, all PASS. Implementation from m01-m2 already supports the contract; m01-m4 verifies it.

- [ ] **Step 5: Run the full file (expect PASS, count 73)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v 2>&1 | tail -3
```

Expected: `Ran 73 tests in 0.0XXs`, `OK`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): broaden REQ-09 UnknownEvent byte-equal sweep across event_type shapes and raw_fields structures"
```

---

## Task 4: `FieldTypeTests` — document M01's intentional no-type-validation stance

**Files:**
- Modify: `tests/test_telemetry_events.py`

REQ-10's design doc lists `FieldTypeTests` as one of the four canonical test classes. It does not exist yet. The DESIGN-doc draft framed these as "rejects wrong type at construction" tests, but Python's `@dataclass` does NOT validate types at `__init__` — it assigns whatever is passed. M01 intentionally defers type validation to M07 (failure_triage taxonomy). The correct M01 implementation of `FieldTypeTests` is therefore to **document the no-validation stance**: each test demonstrates that "wrong" types pass through construction and round-trip without coercion, with a docstring explaining why this is intentional in M01.

This is the spec-faithful interpretation: REQ-10 says "the four `TestCase` classes documented in the companion design doc" but the design doc's draft assumed Python would validate types when in fact it does not. M01-m4 lands the test class with the actually-correct behavior described, not the speculative draft. See `gap-analysis` notes.

- [ ] **Step 1: Append the FieldTypeTests class with four documenting tests**

Append above the `if __name__ == "__main__":` line:

```python
class FieldTypeTests(unittest.TestCase):
    """REQ-10 (4th design class): document M01's intentional no-type-
    validation stance.

    Python's ``@dataclass`` decorator does NOT validate field types at
    ``__init__`` — it assigns whatever is passed. M01 intentionally
    defers runtime type validation to M07 (failure_triage taxonomy)
    where typed enums for ``severity`` / ``error_class`` / ``reason`` /
    ``phase`` will be introduced alongside ``__post_init__`` validators.

    These tests pin the M01 contract: types are documented (REQ-05
    table) but not enforced. Round-trip still holds because JSON
    serialization preserves whatever Python type was assigned. A future
    contributor reading this class should understand that adding
    ``__post_init__`` validation here is a SCOPE CHANGE — it belongs in
    M07, not M01.
    """

    def test_int_field_accepts_float_silently_in_m01(self) -> None:
        """M01 documents int fields (e.g., ``tokens_in``) without
        enforcing the type. Passing 1.5 is silently accepted. The wire
        form will serialize as ``1.5`` (JSON number) and parse back as
        ``1.5`` (Python float). This is the M01 baseline; M07 may tighten.
        """
        from story_automator.core.telemetry_events import (
            StoryCompleted,
            parse_event,
        )

        event = StoryCompleted(
            timestamp="2026-06-14T05:12:34Z",
            run_id="20260614-051234",
            epic="3",
            story_key="3.1",
            duration_s=42.5,
            cost_usd=1.23,
            tokens_in=1.5,  # documented as int; passed as float; not rejected
            tokens_out=500,
            attempts=2,
        )
        self.assertEqual(event.tokens_in, 1.5)
        # Round-trip survives — the float is serialized as a JSON number
        # and parsed back as a Python float. Equality holds.
        parsed = parse_event(event.to_json_line())
        self.assertEqual(parsed, event)

    def test_float_field_accepts_int_silently_in_m01(self) -> None:
        """M01 documents float fields (e.g., ``cost_usd``) without
        enforcing the type. Passing the integer ``0`` is silently
        accepted and stored as an int (NOT coerced to ``0.0`` because
        @dataclass doesn't run converters). The wire form serializes as
        ``0`` (JSON integer), not ``0.0`` — which is JSON-valid but a
        type-strict downstream consumer might object. M07 may tighten.
        """
        from story_automator.core.telemetry_events import (
            StoryCompleted,
            parse_event,
        )

        event = StoryCompleted(
            timestamp="2026-06-14T05:12:34Z",
            run_id="20260614-051234",
            epic="3",
            story_key="3.1",
            duration_s=42.5,
            cost_usd=0,  # documented as float; passed as int; stored as int
            tokens_in=1000,
            tokens_out=500,
            attempts=2,
        )
        self.assertEqual(event.cost_usd, 0)
        self.assertIs(type(event.cost_usd), int)  # NOT coerced to float
        # Round-trip still holds even though the wire form is 0 (int).
        parsed = parse_event(event.to_json_line())
        self.assertEqual(parsed, event)

    def test_string_field_accepts_int_silently_in_m01(self) -> None:
        """M01 documents string fields (e.g., ``epic``) without
        enforcing the type. Passing ``42`` (int) is silently accepted.
        The wire form serializes as ``42`` (JSON integer), and the
        parsed value is an int — NOT a string. Equality holds at the
        Python level, but downstream consumers expecting str will
        fail. M07 may tighten.
        """
        from story_automator.core.telemetry_events import (
            StoryStarted,
            parse_event,
        )

        event = StoryStarted(
            timestamp="2026-06-14T05:12:34Z",
            run_id="20260614-051234",
            epic=42,  # documented as str; passed as int; not rejected
            story_key="3.1",
            agent="claude",
            model="sonnet",
            complexity="medium",
        )
        self.assertEqual(event.epic, 42)
        self.assertIs(type(event.epic), int)
        # Round-trip equality holds because both instances have epic=42 (int).
        parsed = parse_event(event.to_json_line())
        self.assertEqual(parsed, event)

    def test_bool_field_accepts_string_silently_in_m01(self) -> None:
        """M01 documents bool fields (``ReviewCycle.blocking``) without
        enforcing the type. Passing ``"yes"`` is silently accepted and
        stored as a string. The wire form serializes as ``"yes"`` (JSON
        string), not ``true`` — round-trip equality still holds because
        parsed value is also the string "yes". M07 may tighten via a
        ``__post_init__`` validator.
        """
        from story_automator.core.telemetry_events import (
            ReviewCycle,
            parse_event,
        )

        event = ReviewCycle(
            timestamp="2026-06-14T05:12:34Z",
            run_id="20260614-051234",
            epic="3",
            story_key="3.1",
            cycle_num=2,
            issues_found=3,
            blocking="yes",  # documented as bool; passed as str; not rejected
        )
        self.assertEqual(event.blocking, "yes")
        self.assertIs(type(event.blocking), str)
        parsed = parse_event(event.to_json_line())
        self.assertEqual(parsed, event)
```

- [ ] **Step 2: Run the new class (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.FieldTypeTests -v
```

Expected: 4 tests, all PASS. The tests assert the documented M01 behavior — types are not enforced.

- [ ] **Step 3: Run the full file (expect PASS, count 77)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v 2>&1 | tail -3
```

Expected: `Ran 77 tests in 0.0XXs`, `OK`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): FieldTypeTests document M01 no-type-validation stance (deferred to M07)"
```

---

## Task 5: `ImportAllowlistTests` — codify REQ-11 as an in-suite gate

**Files:**
- Modify: `tests/test_telemetry_events.py`

REQ-11 says the new module must use only stdlib + `filelock` + `psutil`. The current implementation uses only stdlib + a relative import from `.common`. m01-m4 codifies this as an in-suite test that parses the module via the `ast` module and inspects every import statement, so any future contributor adding a forbidden third-party dep will fail this test before merge.

- [ ] **Step 1: Append the ImportAllowlistTests class**

Append above the `if __name__ == "__main__":` line:

```python
class ImportAllowlistTests(unittest.TestCase):
    """REQ-11: ``core/telemetry_events.py`` must import only the Python
    standard library plus ``filelock`` and ``psutil`` (and project-local
    relative imports from ``story_automator.core``). Codified via AST
    inspection so a future ``import some_third_party_pkg`` fails fast
    here rather than waiting for a downstream environment to reveal it.

    The allowlist intentionally mirrors the CLAUDE.md guardrail. Note:
    pyproject.toml does NOT currently declare a ``[project.dependencies]``
    list (the spec REQ-11 wording was aspirational); this in-suite gate
    is the authoritative enforcement until that section exists.
    """

    # The set of top-level package names whose import is permitted in the
    # M01 telemetry module. Stdlib roots are enumerated explicitly so the
    # check stays portable across Python versions (sys.stdlib_module_names
    # is 3.10+ and would be cleaner — see the alternate impl below).
    ALLOWED_THIRD_PARTY = frozenset({"filelock", "psutil"})

    # First-party root: a relative import (level >= 1) or an absolute
    # import beginning with this string is always allowed.
    FIRST_PARTY_ROOT = "story_automator"

    def _module_imports(self) -> tuple[list[str], list[str]]:
        """Return (top_level_absolute_imports, relative_module_names)
        parsed from the telemetry_events module via AST. Avoids
        importing the module twice — we read the source directly.

        Anchors the source path on ``__file__`` rather than cwd so the
        test runs identically under ``unittest discover`` from the
        project root, under ``pytest`` from a subdirectory, and under
        any IDE test runner with an arbitrary cwd.
        """
        import ast
        from pathlib import Path

        project_root = Path(__file__).resolve().parent.parent
        source_path = (
            project_root
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "telemetry_events.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))

        absolute: list[str] = []
        relative: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    absolute.append(alias.name.split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    # Relative import — module may be None for "from . import X"
                    relative.append(node.module or "")
                else:
                    if node.module:
                        absolute.append(node.module.split(".", 1)[0])
        return absolute, relative

    def test_only_allowlisted_third_party_imports_in_telemetry_module(self) -> None:
        """Every absolute import's top-level name must be either a
        stdlib module OR in ALLOWED_THIRD_PARTY OR a first-party
        ``story_automator.*`` import. This is the canonical REQ-11 gate.
        """
        import sys

        absolute, _ = self._module_imports()
        stdlib_names = (
            sys.stdlib_module_names if hasattr(sys, "stdlib_module_names") else frozenset()
        )
        # Defensive fallback for Python < 3.10 (project requires 3.11+ so
        # this branch never executes in practice; the fallback exists so
        # the test is readable as a standalone gate).
        if not stdlib_names:  # pragma: no cover
            self.fail("sys.stdlib_module_names unavailable; Python 3.10+ required")

        for top in absolute:
            with self.subTest(import_name=top):
                allowed = (
                    top in stdlib_names
                    or top in self.ALLOWED_THIRD_PARTY
                    or top == self.FIRST_PARTY_ROOT
                )
                self.assertTrue(
                    allowed,
                    f"forbidden import {top!r} — not in stdlib, not in "
                    f"{set(self.ALLOWED_THIRD_PARTY)!r}, not the first-party "
                    f"root {self.FIRST_PARTY_ROOT!r}",
                )

    def test_relative_imports_stay_within_story_automator_core(self) -> None:
        """Relative imports (``from .common import ...``) are allowed
        only when they resolve within ``story_automator.core``. Pins the
        module's seam — a future ``from ..adapters.something import X``
        would broaden the module's coupling beyond core/ and fail here.
        """
        _, relative = self._module_imports()
        for module_suffix in relative:
            with self.subTest(module=module_suffix):
                # Empty (``from . import X``) is OK — same package.
                # ``common`` is the canonical sibling import.
                # Anything else is suspect.
                self.assertIn(
                    module_suffix,
                    ("", "common"),
                    f"unexpected relative import target {module_suffix!r}; "
                    f"core/telemetry_events.py is permitted to reach into "
                    f"core/common.py only (M01 seam)",
                )
```

- [ ] **Step 2: Run the new class (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ImportAllowlistTests -v
```

Expected: 2 tests, all PASS. The module currently imports `json`, `dataclasses`, `typing` (all stdlib) and `from .common import compact_json, iso_now` (first-party relative to `common`).

If FAIL: identify the forbidden import and decide whether to (a) remove it (preferred — restores REQ-11), or (b) add it to the allowlist (scope change — flag and ask the operator).

- [ ] **Step 3: Run the full file (expect PASS, count 79)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v 2>&1 | tail -3
```

Expected: `Ran 79 tests in 0.0XXs`, `OK`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): ImportAllowlistTests codify REQ-11 stdlib+filelock+psutil gate via AST inspection"
```

---

## Task 6: `ModuleSizeTests` — codify the 500-line NFR as an in-suite gate

**Files:**
- Modify: `tests/test_telemetry_events.py`

The NFR says "the module file size is no more than 500 source lines of code excluding tests and docstrings." The current module is 347 lines including docstrings. m01-m4 codifies the 500-line ceiling as an in-suite test so a future contributor exceeding it fails CI before merge.

The NFR phrasing "excluding tests and docstrings" is interpreted as: tests are in a separate file (`tests/test_telemetry_events.py`) and are automatically excluded; docstring stripping is NOT performed because (a) the current count INCLUDING docstrings is 347, comfortably under 500; (b) stripping docstrings would require AST parsing and add brittle complexity. The strict NFR is "file ≤ 500 lines including docstrings"; if docstring-stripping is ever needed the gate can be tightened then.

- [ ] **Step 1: Append the ModuleSizeTests class**

Append above the `if __name__ == "__main__":` line:

```python
class ModuleSizeTests(unittest.TestCase):
    """NFR: ``core/telemetry_events.py`` must be ≤ 500 source lines per
    the CONTRIBUTING.md guideline. Codified here as an in-suite gate
    so a future contributor exceeding the budget fails fast.

    Counts logical lines via ``splitlines()`` (which omits the trailing-
    newline artifact). Docstring stripping is NOT performed — the
    baseline at the end of m01 (347 lines including docstrings) is far
    enough under 500 that the simple count is the right gate. If a
    future milestone genuinely needs more than 500 lines of code (sans
    docstrings) the gate must be tightened to AST-strip docstrings;
    that's a deliberate decision, not a quiet workaround.
    """

    MAX_SOURCE_LINES = 500

    def _module_source_path(self):
        """Anchor on ``__file__`` so the test is cwd-independent."""
        from pathlib import Path

        project_root = Path(__file__).resolve().parent.parent
        return (
            project_root
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "telemetry_events.py"
        )

    def test_module_is_under_five_hundred_lines(self) -> None:
        source_path = self._module_source_path()
        source_lines = source_path.read_text(encoding="utf-8").splitlines()
        self.assertLessEqual(
            len(source_lines),
            self.MAX_SOURCE_LINES,
            f"{source_path} is {len(source_lines)} lines; "
            f"NFR ceiling is {self.MAX_SOURCE_LINES}. Split the module "
            f"or move helpers to a new file in core/.",
        )

    def test_module_size_baseline_documented(self) -> None:
        """The baseline at end-of-M01 should be well under the ceiling.
        If this test fails with a count near 500, the module has grown
        unexpectedly during M01 and should be reviewed before the next
        milestone adds more content.
        """
        source_path = self._module_source_path()
        source_lines = source_path.read_text(encoding="utf-8").splitlines()
        # Soft baseline: at end of m01 we expect ~347 lines. A spread of
        # ±50 absorbs minor edits without becoming a churn test, while
        # still flagging a >100-line surprise growth that should warrant
        # a review before merging.
        self.assertLess(
            len(source_lines),
            450,
            f"{source_path} is {len(source_lines)} lines; the M01 "
            f"baseline is ~347. If the module is approaching 450 there "
            f"is likely a refactor opportunity worth surfacing.",
        )
```

- [ ] **Step 2: Run the new class (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.ModuleSizeTests -v
```

Expected: 2 tests, all PASS (the file is 347 lines, comfortably under both gates).

- [ ] **Step 3: Run the full file (expect PASS, count 81)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v 2>&1 | tail -3
```

Expected: `Ran 81 tests in 0.0XXs`, `OK`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): ModuleSizeTests codify 500-line NFR ceiling and baseline drift gate"
```

---

## Task 7: `PEP604UnionTypesTests` — codify the PEP 604 union policy as an in-suite gate

**Files:**
- Modify: `tests/test_telemetry_events.py`

The NFR says "all public functions, methods, and dataclass field types carry PEP 604 union-typed annotations." Today the module has zero `Optional[...]` or `Union[...]` usages — every annotation either is unconditional or uses `|`. m01-m4 codifies this as an in-suite test so a future contributor reintroducing `Optional` or `Union` fails the gate.

- [ ] **Step 1: Append the PEP604UnionTypesTests class**

Append above the `if __name__ == "__main__":` line:

```python
class PEP604UnionTypesTests(unittest.TestCase):
    """NFR: the M01 module must use PEP 604 union syntax (``str | None``)
    rather than ``typing.Optional[str]`` or ``typing.Union[str, None]``.
    Codified here as a textual gate against the module's source.

    The source scan is intentionally textual (not AST) because PEP 604
    annotations are syntactic — they appear in annotations and string-
    quoted via ``from __future__ import annotations``. A textual grep
    is the right granularity: any literal occurrence of ``Optional[`` or
    ``Union[`` in the module source fails the gate.
    """

    def _module_source_path(self):
        """Anchor on ``__file__`` so the test is cwd-independent."""
        from pathlib import Path

        project_root = Path(__file__).resolve().parent.parent
        return (
            project_root
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "telemetry_events.py"
        )

    def test_module_does_not_use_legacy_optional(self) -> None:
        source_path = self._module_source_path()
        source = source_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "Optional[",
            source,
            f"{source_path} contains legacy ``Optional[...]`` syntax; "
            f"NFR requires PEP 604 ``T | None``. Replace with the modern form.",
        )

    def test_module_does_not_use_legacy_union(self) -> None:
        source_path = self._module_source_path()
        source = source_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "Union[",
            source,
            f"{source_path} contains legacy ``Union[A, B]`` syntax; "
            f"NFR requires PEP 604 ``A | B``. Replace with the modern form.",
        )
```

- [ ] **Step 2: Run the new class (expect PASS)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.PEP604UnionTypesTests -v
```

Expected: 2 tests, all PASS. The module currently uses no `Optional` or `Union`.

- [ ] **Step 3: Run the full file (expect PASS, count 83)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v 2>&1 | tail -3
```

Expected: `Ran 83 tests in 0.0XXs`, `OK`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_telemetry_events.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): PEP604UnionTypesTests codify ``T | None`` NFR via textual source scan"
```

---

## Task 8: Verify ruff lint and format gates pass

**Files:** None modified — operator-runnable gate verification only.

The quality gates section of the spec lists ruff `check` and `format --check` as the canonical lint/format gates. Task 1 Step 4 already confirmed these pass at the slice baseline; this task re-runs them after Tasks 2–7 have appended 17 new tests. The new tests are stdlib-only and follow the project's existing style, but the verification is mandatory.

- [ ] **Step 1: Run ruff check on both files**

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
```

Expected: `All checks passed!`

If FAIL: address each violation. The most common cause after appending tests is an unused import — remove it. Do NOT add a `# noqa` suppression to silence a real violation; the only acceptable `noqa` in this codebase is for declarations that intentionally trigger `__init_subclass__` and need an `F841` suppression (see `_RegistryIsolationMixin` users in the existing m01-m1 tests).

- [ ] **Step 2: Run ruff format --check on both files**

```bash
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
```

Expected: `2 files already formatted`.

If FAIL: run `python -m ruff format <file>` to apply the formatter, then re-run `--check` to confirm. Commit the format fix as a separate commit if it cannot be folded into the previous task's commit (it usually can be — fix the upstream task and amend that commit before this one).

No commit for this task — verification gate only. Proceed to Task 9.

---

## Task 9: Verify the full suite passes under stdlib unittest

**Files:** None modified — operator-runnable gate verification only.

The spec's test gate lists `python -m pytest tests/test_telemetry_events.py -q` as canonical; CLAUDE.md and `npm run test:python` both use `python -m unittest discover`. Both runners discover `unittest.TestCase` natively; both must report green.

- [ ] **Step 1: Run unittest (canonical for this project)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events 2>&1 | tail -3
```

Expected: `Ran 83 tests in 0.0XXs`, `OK`.

- [ ] **Step 2: Run pytest in compatibility mode (if installed)**

If `pytest` is available on the operator's machine:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m pytest tests/test_telemetry_events.py -q 2>&1 | tail -3
```

Expected: `83 passed in 0.0XXs`. If pytest is not installed, skip — the unittest run in Step 1 is the authoritative gate; pytest discovery is a portability check, not a different verification.

- [ ] **Step 3: Run the full project test suite via npm**

```bash
npm run test:python
```

Expected: all project tests pass, the m01-m4 additions composing cleanly with the rest of the suite.

No commit for this task — verification gate only. Proceed to Task 10.

---

## Task 10: Verify the coverage gate

**Files:** None modified — operator-runnable gate verification only.

The spec lists `pytest --cov=story_automator.core.telemetry_events --cov-fail-under=85 tests/test_telemetry_events.py` as the canonical coverage gate. The project's CLAUDE.md notes coverage uses the stdlib `coverage` package (operator-installed). Both approaches measure the same thing; this task uses `python -m coverage` because pytest+cov may not be installed everywhere.

- [ ] **Step 1: Run coverage under the M01 test module**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run --source=story_automator.core.telemetry_events -m unittest tests.test_telemetry_events
python -m coverage report -m --include="*/telemetry_events.py"
```

Note: `PYTHONPATH` is required so `unittest` can resolve `tests.test_telemetry_events` (which itself imports `story_automator.core.telemetry_events`). `--source=story_automator.core.telemetry_events` (the importable module name, matching the spec's pytest-style `--cov=story_automator.core.telemetry_events`) tells coverage which file to track; supplying a filesystem directory instead would still work but couples to the on-disk path and breaks if the package is installed via wheel.

Expected output (the file row + a TOTAL summary):

```
Name                                                                       Stmts   Miss  Cover   Missing
--------------------------------------------------------------------------------------------------------
skills/bmad-story-automator/src/story_automator/core/telemetry_events.py     XX      Y    ZZ%    ...
--------------------------------------------------------------------------------------------------------
TOTAL                                                                        XX      Y    ZZ%
```

The `Cover` column must be ≥ **85%** on the telemetry_events.py row. (Pre-m01-m4 baseline measured at 100%; the gate has substantial headroom.)

If coverage < 85%: identify the missing branches from the `Missing` column. Likely candidates:
- A defensive ``raise`` path no test exercises (e.g., an error-message branch). Add a test that triggers it.
- A docstring-only conditional (unlikely — Python doesn't track docstrings as branches).
- An ``__init_subclass__`` short-circuit (e.g., the `if not cls.EVENT_TYPE: return` line). Already covered by the unregistered-subclass test in m01-m1.

Do NOT add `# pragma: no cover` to silence real uncovered code. That's only acceptable for defensive branches that genuinely cannot be exercised from tests (e.g., Python-version-specific fallbacks like the `sys.stdlib_module_names` check in Task 5 above).

- [ ] **Step 2: Enforce the gate as a single command**

```bash
python -m coverage report --include="*/telemetry_events.py" --fail-under=85
```

Expected: zero exit code (the report rerun confirms ≥85% as a CI-style gate).

If FAIL: address per Step 1 guidance.

No commit for this task — verification gate only. Proceed to Task 11.

---

## Task 11: Verify multi-Python sanity (REQ-01)

**Files:** None modified — operator-runnable gate verification only.

REQ-01 says the module must import cleanly under Python 3.11, 3.12, 3.13, **and 3.14**. The orchestrator's `python` resolves to whichever the operator has installed; CI runs 3.11/3.12/3.13 (Ubuntu + macOS) per the project's CI matrix. Full multi-version testing is a CI concern; this task is the local-developer sanity check.

- [ ] **Step 1: Verify the operator's Python is in scope**

```bash
python --version
```

Expected: a `Python 3.1{1,2,3,4}.X` line. If 3.10 or lower, M01 cannot run here — install a supported Python.

- [ ] **Step 2: Verify the module imports cleanly**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -c "from story_automator.core.telemetry_events import Event, UnknownEvent, parse_event, StoryStarted, BudgetAlert; print('import OK', len(Event._REGISTRY))"
```

Expected: `import OK 13`. Any other output (import error, wrong registry count) is a regression — **BLOCKED**.

- [ ] **Step 3: Note the CI matrix for the operator**

The project's CI runs the suite on Python 3.11, 3.12, and 3.13 (Ubuntu + macOS) per the existing CI configuration. The spec REQ-01 also lists 3.14; this slice does not modify CI to add 3.14 — that's a CI-config change with its own approval gate and is **out of scope for m01-m4**. Flag in the gap analysis if 3.14 is mandated for shipping M01.

No commit for this task — verification gate only. Proceed to Task 12.

---

## Task 12: Verify the cross-platform determinism NFR

**Files:** None modified — operator-runnable gate verification only.

The NFR says "the round-trip serialization is deterministic: identical input fields produce byte-identical JSON output across Python 3.11, 3.12, 3.13, and 3.14 runtimes." Determinism is testable locally because `dict.update` ordering + `json.dumps`(separators) + `asdict` ordering are all defined to be deterministic. The test exists implicitly in `EventToJsonLineTests.test_to_json_line_byte_output_is_deterministic` (m01-m1) and `ConcreteEventRoundTripTests` (m01-m3). This task adds no new test; it documents the verification path.

- [ ] **Step 1: Re-run the existing byte-determinism test alone**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events.EventToJsonLineTests.test_to_json_line_byte_output_is_deterministic -v
```

Expected: `OK`. The test asserts the exact wire form of a minimal event; passing it confirms the deterministic-output NFR holds on this Python.

- [ ] **Step 2: Document the cross-version assurance path**

The cross-version determinism guarantee rests on three CPython invariants:
1. `dict` preserves insertion order (PEP 468 / 3.7+).
2. `json.dumps` with explicit `separators=(",", ":")` emits no platform-dependent whitespace.
3. `dataclasses.asdict` preserves field declaration order across all 3.11+ versions.

No test in this slice exercises 3.11/3.12/3.13/3.14 simultaneously — that's a CI-matrix concern. The local sanity is Step 1.

No commit for this task — verification gate only. Proceed to Task 13.

---

## Task 13: Final integration verification

**Files:** None modified — operator-runnable final gate.

This task is the slice-completion checkpoint. All quality gates must report green simultaneously.

- [ ] **Step 1: Run all gates in sequence**

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/telemetry_events.py tests/test_telemetry_events.py
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events 2>&1 | tail -3
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run --source=story_automator.core.telemetry_events -m unittest tests.test_telemetry_events
python -m coverage report --include="*/telemetry_events.py" --fail-under=85
wc -l skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
```

Expected (all gates):
- Ruff check: `All checks passed!`
- Ruff format: `2 files already formatted`
- Unittest: `Ran 83 tests in 0.0XXs` and `OK`
- Coverage: ≥ 85% on telemetry_events.py
- Module size: ≤ 500 lines (currently 347)

- [ ] **Step 2: Run the full project suite as a final sanity check**

```bash
npm run test:python
```

Expected: full project test suite passes.

- [ ] **Step 3: Confirm git status is clean (or only intended changes)**

```bash
git status
```

Expected: clean working tree if all Tasks 2–7 committed correctly. If there are stray modifications, investigate and either commit (as a follow-up fix to the relevant earlier task) or revert.

No commit for this task — the slice is complete after Step 3 reports clean. The M01 wedge atom is now feature-complete and ready for the M02 milestone (TelemetryEmitter + reader + wiring).

---

## Self-Review Notes

After writing this plan, the following checks were run:

**1. Spec coverage:**
- REQ-08 (round-trip invariant for typed events) — covered by Task 2 (broader sweep with unicode, special chars, numeric, boolean edge cases) on top of m01-m3's 13 per-class happy-path tests. **Covered.**
- REQ-09 (round-trip invariant for UnknownEvent across arbitrary inputs) — covered by Task 3 (multiple event_type shapes, nested raw_fields, empty raw_fields) on top of m01-m3's single byte-equal test. **Covered.**
- REQ-10 (test file with ~30 tests across 4 TestCase classes) — the design doc's 4 classes are now represented: `EventBaseTests` (via m01-m1's seven sub-classes), `ConcreteEventRoundTripTests` (m01-m3) + `ConcreteEventRoundTripExtendedTests` (Task 2), `ParseEventTests` (via m01-m2's six sub-classes), and `FieldTypeTests` (Task 4 — the missing fourth class). Test count is 83 (≥ "approximately 30"). **Covered with finer-grained class split than the spec literally describes; flagged in gap analysis.**
- REQ-11 (allowlist enforcement) — covered by Task 5 (`ImportAllowlistTests` codifies the gate via AST). **Covered.**
- NFR 500-line ceiling — covered by Task 6 (`ModuleSizeTests`). **Covered.**
- NFR PEP 604 unions — covered by Task 7 (`PEP604UnionTypesTests`). **Covered.**
- NFR ruff check/format — covered by Task 8 (operator-runnable verification). **Covered.**
- NFR coverage ≥ 85% — covered by Task 10. **Covered.**
- NFR multi-platform (Windows / WSL / Linux) — every test uses only stdlib + project core/common; no tmux, no subprocess, no network. **Covered by construction.**
- NFR deterministic byte-output across 3.11/3.12/3.13/3.14 — Task 12 documents the local sanity path; full cross-version verification is a CI matrix concern, not in m01-m4 scope. **Documented; flagged in gap analysis.**
- Quality gates (lint, format, test, coverage, allowlist, module-size, cross-platform) — all addressed. **Covered.**

**2. Placeholder scan:**
- No "TBD", "TODO", "implement later", "fill in details".
- No "add appropriate error handling" / "add validation".
- No "Write tests for the above" without actual test code.
- No "Similar to Task N" — every task repeats the relevant code.
- Every step that changes code shows the code.

**3. Type consistency:**
- `_round_trip(event: Event)` signature matches m01-m3's `ConcreteEventRoundTripTests._round_trip`. The duplication is intentional (slice independence).
- `Event._REGISTRY` is read-only in all m01-m4 tests; no mutation via subclassing without `_RegistryIsolationMixin`.
- `compact_json` and `parse_event` are used as imported from `story_automator.core.telemetry_events`, consistent with m01-m1/m01-m2 conventions.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-14-m01-m4-tests-and-quality-gates.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task + two-stage review between tasks. Best for an orchestrated `superpowers:subagent-driven-development` flow.

**2. Inline Execution** — execute tasks in the current session via `superpowers:executing-plans`. Best for an operator who wants to checkpoint between tasks manually.

Operator chooses; both produce identical end state.
