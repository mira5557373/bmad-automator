# M08 — Per-Model Calibration Tracker (m2-aggregation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the calibration aggregation against REQ-05/06/07/08/14: cover the malformed-JSON-line tolerance path (currently 2 missed statements), add a multi-key aggregation test, refactor `build_calibration` into small private helpers for clarity and testability, and bring `test_calibration.py` back under the 500-line non-functional cap.

**Architecture:** Keep the public surface identical (`CalibrationEntry`, `CalibrationTable`, `build_calibration`, `lookup_success_rate`, `format_calibration_report`). Split `build_calibration` into three private helpers — `_iter_event_lines(path)`, `_accumulate_buckets(events_iter)`, `_materialize_entries(buckets)` — that the public function orchestrates. Push shared fixture factories (`_make_entry`, `_make_table`) into the existing sibling module `tests/_calibration_fixtures.py` to reduce duplication and trim test LOC.

**Tech Stack:** Python 3.11+, stdlib only (`pathlib`, `dataclasses`, `json`, `typing`), `unittest.TestCase` for tests, ruff lint/format, stdlib `coverage` at `--fail-under=85`.

---

## Context for the Engineer

You are extending the existing M08 calibration module. **Most of the M08 surface already exists** because the m1-types milestone over-delivered. Before writing any code, internalize these facts:

1. **Current state (verified 2026-06-15):**
   - `skills/bmad-story-automator/src/story_automator/core/calibration.py` — 167 LOC, exports all five symbols, implements `build_calibration` with streaming + aggregation.
   - `skills/bmad-story-automator/tests/test_calibration.py` — **518 LOC** (FAILS the ≤500 non-functional cap; you MUST trim it as part of this milestone).
   - `skills/bmad-story-automator/tests/_calibration_fixtures.py` — 143 LOC, holds `_fixture_dir`, `_write_jsonl`, `_completed_line`, `_failed_line`, and the `_ExtendedEventShim` that widens `StoryCompleted` / `StoryFailed` with `model_id` / `task_kind`.
   - Test suite: 23 tests, all green.
   - Coverage on `core/calibration.py`: 97%. The 2 uncovered statements are the `except (ValueError, json.JSONDecodeError, TypeError): continue` branch inside the streaming loop (the malformed-JSON-line tolerance path).

2. **What this milestone changes:**
   - Adds a malformed-JSON-line tolerance test (closes the coverage gap and asserts REQ-05's "tolerates" semantics for non-JSON lines).
   - Adds a multi-key aggregation test (REQ-07 — multiple `(model_id, task_kind)` pairs in the same ledger).
   - Refactors `build_calibration` into three private helpers without changing observable behavior.
   - Extracts `_make_entry` / `_make_table` factories into `_calibration_fixtures.py` and rewrites duplicated fixture construction in the four call sites so the test file drops below 500 LOC.

3. **What this milestone MUST NOT touch:**
   - Public API of `core/calibration.py` (`CalibrationEntry`, `CalibrationTable`, the three top-level functions, `__all__`).
   - `core/telemetry_events.py` — the M01 gap (no `model_id` / `task_kind` on `StoryCompleted` / `StoryFailed`) is a deferred M01 follow-up, not an M08 fix. The `_ExtendedEventShim` stays.
   - `core/common.py` — no new helpers; reuse `iso_now`, `compact_json`, `ensure_dir`.
   - `pyproject.toml` dependency allowlist (`stdlib + filelock + psutil`).

4. **Quality gates (re-stated from the spec):**
   - `ruff check` and `ruff format --check` both exit zero on the two M08 files.
   - `python -m unittest tests.test_calibration` from `skills/bmad-story-automator/` exits zero.
   - `coverage report --fail-under=85 --include="*/core/calibration.py"` exits zero.
   - `wc -l skills/bmad-story-automator/src/story_automator/core/calibration.py` ≤ 500.
   - `wc -l skills/bmad-story-automator/tests/test_calibration.py` ≤ 500.
   - Import-allowlist grep finds no `requests`, `httpx`, `aiohttp`, `subprocess`, `os.system`, `psutil`, `filelock` in `core/calibration.py`.
   - Four-letter placeholder-token grep (`\b(TODO|FIXME|XXXX|TBD|TKTK)\b`) returns zero matches in both files.
   - `python -m compileall core/calibration.py` exits zero.

5. **Discovery boundary.** The new tests live under `skills/bmad-story-automator/tests/`, NOT the repo-root `tests/`. The repo-root `npm run test:python` does not discover M08 tests by design (this was documented in m1-types Task 14); the M08 quality gates run with cwd = `skills/bmad-story-automator/`.

6. **Working directory for unittest / coverage commands.** All `python -m unittest tests.test_calibration` invocations below assume `cd skills/bmad-story-automator` first. The Bash session resets the cwd between tool calls in some environments — explicitly `cd` at the top of each shell snippet.

7. **No `Optional` / `Union`.** PEP 604 unions only (`str | Path`, `Iterator[Event]`).

8. **First non-comment line in every new/edited file:** `from __future__ import annotations` (already present in all three M08 files).

---

## File Structure

- **Modify:** `skills/bmad-story-automator/src/story_automator/core/calibration.py` (currently 167 LOC; refactor target ~180 LOC; HARD cap 500)
- **Modify:** `skills/bmad-story-automator/tests/test_calibration.py` (currently 518 LOC — OVER cap; target ≤ 480 LOC for headroom)
- **Modify:** `skills/bmad-story-automator/tests/_calibration_fixtures.py` (currently 143 LOC; add `_make_entry` / `_make_table` helpers; expected ~175 LOC; HARD cap 500)

No new files. No deletions.

---

## Task 1: Baseline — confirm current state before any edit

**Files:**
- Read: `skills/bmad-story-automator/src/story_automator/core/calibration.py`
- Read: `skills/bmad-story-automator/tests/test_calibration.py`
- Read: `skills/bmad-story-automator/tests/_calibration_fixtures.py`

- [ ] **Step 1: Confirm the existing M08 module surface**

Open each of the three files above. Confirm:
- `calibration.py` exports exactly `["CalibrationEntry", "CalibrationTable", "build_calibration", "format_calibration_report", "lookup_success_rate"]` in `__all__`.
- `test_calibration.py` imports fixtures from `tests._calibration_fixtures`.
- `_calibration_fixtures.py` defines `_fixture_dir`, `_write_jsonl`, `_completed_line`, `_failed_line`, `_ExtendedEventShim`.

No code change in this step.

- [ ] **Step 2: Run the existing test suite and capture the baseline**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_calibration -v 2>&1 | tail -5
```

Expected: `Ran 23 tests` and `OK`.

- [ ] **Step 3: Capture baseline coverage**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m coverage run --source=src/story_automator/core -m unittest tests.test_calibration && python -m coverage report --include="*/core/calibration.py" -m
```

Expected output: total coverage 97%, with the two uncovered statements being inside the `except (ValueError, json.JSONDecodeError, TypeError): continue` branch in `build_calibration`. Note the exact line numbers — Task 2 targets them.

- [ ] **Step 4: Confirm the file-size gate failure**

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/calibration.py skills/bmad-story-automator/tests/test_calibration.py skills/bmad-story-automator/tests/_calibration_fixtures.py
```

Expected: `test_calibration.py` reports a value > 500 (currently 518). This is the size constraint the plan must bring back under 500 by Task 9.

- [ ] **Step 5: No commit (audit only)**

Proceed to Task 2.

---

## Task 2: Add a failing test for malformed-JSON-line tolerance

**Files:**
- Test: `skills/bmad-story-automator/tests/test_calibration.py`

REQ-05 says `build_calibration` "tolerates trailing blank lines as well as `\r\n` line endings". The existing implementation extends this tolerance to malformed JSON via `except (ValueError, json.JSONDecodeError, TypeError): continue`. There is no test asserting that behavior; that is the 2-statement coverage gap. We assert the behavior so the gap closes and the contract is documented.

- [ ] **Step 1: Add the failing test**

Insert the following class into `tests/test_calibration.py` **immediately before** the `class LookupSuccessRateTests(unittest.TestCase):` block. (The placement matters because the shim install/uninstall runs once per class; we group the shim-using classes near each other.)

```python
class BuildCalibrationMalformedLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _ExtendedEventShim.install()

    @classmethod
    def tearDownClass(cls) -> None:
        _ExtendedEventShim.uninstall()

    def test_malformed_json_line_is_skipped_without_counting(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            good = _completed_line(
                "2026-06-14T10:00:00Z", "r1", "S-1", "claude-opus-4", "code"
            )
            ledger.write_text(
                "\n".join(["{not json", good, "[1, 2, 3]"]) + "\n",
                encoding="utf-8",
            )
            table = build_calibration(ledger)

        self.assertEqual(set(table.entries.keys()), {("claude-opus-4", "code")})
        self.assertEqual(table.entries[("claude-opus-4", "code")].sample_count, 1)
        self.assertEqual(table.total_events_scanned, 1)

    def test_json_object_missing_event_type_is_skipped(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            good = _completed_line(
                "2026-06-14T10:00:00Z", "r1", "S-1", "m", "t"
            )
            from story_automator.core.common import compact_json as _cj

            no_type = _cj({"timestamp": "2026-06-14T11:00:00Z", "run_id": "r2"})
            _write_jsonl(ledger, [no_type, good])
            table = build_calibration(ledger)

        self.assertEqual(set(table.entries.keys()), {("m", "t")})
        self.assertEqual(table.total_events_scanned, 1)
```

> **Engineer note on `total_events_scanned`.** The current implementation increments `total_events_scanned` AFTER the parse succeeds. So skipped malformed lines do NOT count toward the scanned total — they neither parse nor count. The `[1, 2, 3]` line and the `no_type` line both raise `ValueError` from `parse_event` (`"missing event_type"` and `"top-level JSON must be an object"`), which the `except` swallows. Both tests assert this exact behavior.

- [ ] **Step 2: Run the test — expect it to PASS already (coverage gap, not behavior gap)**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_calibration.BuildCalibrationMalformedLineTests -v
```

Expected: 2 tests pass. The behavior is already correct; we are closing the **coverage** gap and locking in the contract.

- [ ] **Step 3: Confirm coverage now hits 100% on the previously-uncovered branch**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m coverage run --source=src/story_automator/core -m unittest tests.test_calibration && python -m coverage report --include="*/core/calibration.py" -m
```

Expected: `Cover` increases to 100% (68/68 statements) or at least covers the previously-missed lines. If still <100%, the missed statements are now visible in the `Missing` column — investigate them before continuing.

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/tests/test_calibration.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m08): cover malformed-JSON-line tolerance in build_calibration"
```

---

## Task 3: Add a failing test for multi-key aggregation

**Files:**
- Test: `skills/bmad-story-automator/tests/test_calibration.py`

REQ-07 requires aggregation per `(model_id, task_kind)` key. Every existing aggregation test uses exactly one key per ledger. A test with two distinct `(model_id, task_kind)` pairs in the same ledger asserts that the bucket dict actually partitions correctly.

- [ ] **Step 1: Add the failing test**

Append to `BuildCalibrationMixedAggregationTests` (existing class — append a method; do NOT create a new class):

```python
    def test_two_distinct_keys_aggregate_independently(self) -> None:
        from story_automator.core.calibration import build_calibration

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "telemetry.jsonl"
            lines = [
                _completed_line(
                    "2026-06-14T10:00:00Z", "r1", "S-1", "claude-opus-4", "code"
                ),
                _failed_line(
                    "2026-06-14T10:01:00Z", "r2", "S-2", "claude-opus-4", "code"
                ),
                _completed_line(
                    "2026-06-14T10:02:00Z", "r3", "S-3", "gpt-5-codex", "review"
                ),
                _completed_line(
                    "2026-06-14T10:03:00Z", "r4", "S-4", "gpt-5-codex", "review"
                ),
            ]
            _write_jsonl(ledger, lines)
            table = build_calibration(ledger)

        self.assertEqual(
            set(table.entries.keys()),
            {("claude-opus-4", "code"), ("gpt-5-codex", "review")},
        )
        opus = table.entries[("claude-opus-4", "code")]
        gpt = table.entries[("gpt-5-codex", "review")]
        self.assertEqual(opus.success_rate, 0.5)
        self.assertEqual(opus.sample_count, 2)
        self.assertEqual(opus.last_seen_iso, "2026-06-14T10:01:00Z")
        self.assertEqual(gpt.success_rate, 1.0)
        self.assertEqual(gpt.sample_count, 2)
        self.assertEqual(gpt.last_seen_iso, "2026-06-14T10:03:00Z")
        self.assertEqual(table.total_events_scanned, 4)
```

- [ ] **Step 2: Run and verify it passes**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_calibration.BuildCalibrationMixedAggregationTests -v
```

Expected: 3 tests pass (the two existing plus the new multi-key one).

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_calibration.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m08): aggregate two distinct (model_id, task_kind) keys independently"
```

---

## Task 4: Add `_make_entry` and `_make_table` factories to the fixtures module

**Files:**
- Modify: `skills/bmad-story-automator/tests/_calibration_fixtures.py`

Four call sites in `test_calibration.py` build `CalibrationEntry` + `CalibrationTable` inline (the `LookupSuccessRateTests._make_table`, two `FormatCalibrationReportTests` methods, and the `CalibrationTableShapeTests.test_construction`). Pushing this into the fixtures module shaves ~30+ LOC across the call sites and centralizes the canonical entry/table shape.

- [ ] **Step 1: Append the two factories to `_calibration_fixtures.py`**

Open `skills/bmad-story-automator/tests/_calibration_fixtures.py`. First, extend the existing module-level imports — find the line `from story_automator.core.telemetry_events import StoryCompleted, StoryFailed` and add immediately below it:

```python
from story_automator.core.calibration import CalibrationEntry, CalibrationTable
```

Then append (after the existing helpers, before any `if __name__` guard if one is present — currently none):

```python
def _make_entry(
    *,
    model_id: str = "claude-opus-4",
    task_kind: str = "code",
    success_rate: float = 0.8750,
    sample_count: int = 8,
    last_seen_iso: str = "2026-06-14T12:00:00Z",
) -> CalibrationEntry:
    """Build a CalibrationEntry for tests. Defaults are the canonical
    opus/code/0.875/8 fixture used by lookup and report tests.
    """

    return CalibrationEntry(
        model_id=model_id,
        task_kind=task_kind,
        success_rate=success_rate,
        sample_count=sample_count,
        last_seen_iso=last_seen_iso,
    )


def _make_table(
    entries=None,
    *,
    generated_at: str = "2026-06-14T13:00:00Z",
    source_path: str = "/tmp/t.jsonl",
    total_events_scanned: int | None = None,
) -> CalibrationTable:
    """Build a CalibrationTable for tests.

    `entries` may be an iterable of CalibrationEntry (keyed by
    (model_id, task_kind)) or a pre-built dict. `total_events_scanned`
    defaults to `sum(e.sample_count for e in entries)` when omitted.
    """

    if entries is None:
        entries_dict: dict[tuple[str, str], CalibrationEntry] = {}
    elif isinstance(entries, dict):
        entries_dict = entries
    else:
        entries_dict = {(e.model_id, e.task_kind): e for e in entries}
    scanned: int = (
        total_events_scanned
        if total_events_scanned is not None
        else sum(e.sample_count for e in entries_dict.values())
    )
    return CalibrationTable(
        entries=entries_dict,
        generated_at=generated_at,
        source_path=source_path,
        total_events_scanned=scanned,
    )
```

- [ ] **Step 2: Confirm `_calibration_fixtures.py` still parses and existing tests still pass**

```bash
cd skills/bmad-story-automator && python -m compileall tests/_calibration_fixtures.py && PYTHONPATH=src python -m unittest tests.test_calibration -v 2>&1 | tail -3
```

Expected: compileall succeeds; all 26 tests (23 + 2 from Task 2 + 1 from Task 3) still pass. The new factories are additive — no test uses them yet.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/_calibration_fixtures.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m08): add _make_entry/_make_table factories to fixtures module"
```

---

## Task 5: Rewrite duplicated entry/table construction sites in `test_calibration.py`

**Files:**
- Modify: `skills/bmad-story-automator/tests/test_calibration.py`

Replace four call sites with the new factories. This step is mechanical — the test assertions stay identical; only the construction lines change. The goal is to drop the file under 500 LOC.

- [ ] **Step 1: Extend the fixtures import**

At the top of `test_calibration.py`, replace the fixtures import block:

```python
from tests._calibration_fixtures import (
    _ExtendedEventShim,
    _completed_line,
    _failed_line,
    _fixture_dir,
    _write_jsonl,
)
```

with:

```python
from tests._calibration_fixtures import (
    _ExtendedEventShim,
    _completed_line,
    _failed_line,
    _fixture_dir,
    _make_entry,
    _make_table,
    _write_jsonl,
)
```

- [ ] **Step 2: Replace `LookupSuccessRateTests._make_table`**

Find the `class LookupSuccessRateTests(unittest.TestCase):` block. Replace its `_make_table` method body with:

```python
    def _make_table(self):
        return _make_table([_make_entry()])
```

(Delete the old in-class CalibrationEntry/CalibrationTable inline constructions inside this method.)

- [ ] **Step 3: Replace `CalibrationTableShapeTests.test_construction`'s table build**

Find `class CalibrationTableShapeTests(unittest.TestCase):`. In `test_construction`, change:

```python
        entry = CalibrationEntry(
            model_id="m",
            task_kind="t",
            success_rate=0.5,
            sample_count=2,
            last_seen_iso="2026-06-14T12:00:00Z",
        )
        table = CalibrationTable(
            entries={("m", "t"): entry},
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/telemetry.jsonl",
            total_events_scanned=2,
        )
```

to:

```python
        entry = _make_entry(
            model_id="m", task_kind="t", success_rate=0.5, sample_count=2,
        )
        table = _make_table(
            [entry], source_path="/tmp/telemetry.jsonl", total_events_scanned=2,
        )
```

The `from story_automator.core.calibration import CalibrationEntry, CalibrationTable` import inside this method becomes unused once both classes are no longer referenced — DELETE that import line from the method body. (`CalibrationEntry` IS still referenced via the assertion `self.assertEqual(table.entries[("m", "t")], entry)` — no, it's referenced via `entry` which is now a `_make_entry()` return; the import is unused. Delete it.)

The assertions in the rest of the method (`self.assertEqual(table.entries[("m", "t")], entry)`, etc.) remain unchanged.

- [ ] **Step 4: Replace `FormatCalibrationReportTests.test_empty_table_emits_header_and_trailing_newline`**

Replace its body's table construction:

```python
        table = CalibrationTable(
            entries={},
            generated_at="2026-06-14T13:00:00Z",
            source_path="/tmp/telemetry.jsonl",
            total_events_scanned=0,
        )
```

with:

```python
        table = _make_table(source_path="/tmp/telemetry.jsonl")
```

Delete the now-unused `CalibrationTable` import line at the top of the method body. Keep `format_calibration_report` in the import. (Ruff `F401` will flag any leftover unused import; if you are unsure whether the symbol is still referenced, search the method body — if the name `CalibrationTable` appears only inside the `import` statement, delete it.)

- [ ] **Step 5: Replace `FormatCalibrationReportTests.test_rows_sorted_by_model_id_then_task_kind`**

Replace the `entries = { … }` dict + `table = CalibrationTable(…)` block with:

```python
        table = _make_table(
            [
                _make_entry(
                    model_id="claude-sonnet-4-5", task_kind="review",
                    success_rate=0.5000, sample_count=4,
                    last_seen_iso="2026-06-14T10:00:00Z",
                ),
                _make_entry(
                    model_id="claude-opus-4", task_kind="code",
                    success_rate=0.8750, sample_count=8,
                    last_seen_iso="2026-06-14T11:00:00Z",
                ),
                _make_entry(
                    model_id="claude-opus-4", task_kind="docs",
                    success_rate=1.0000, sample_count=2,
                    last_seen_iso="2026-06-14T12:00:00Z",
                ),
            ],
            source_path="/tmp/telemetry.jsonl",
        )
```

Delete the method's `CalibrationEntry, CalibrationTable` imports.

- [ ] **Step 6: Replace `FormatCalibrationReportTests.test_report_is_plain_ascii`**

Replace its `entries = { ... }` + `table = CalibrationTable(...)` with:

```python
        table = _make_table(
            [
                _make_entry(
                    model_id="m", task_kind="t",
                    success_rate=0.6667, sample_count=3,
                ),
            ],
            source_path="/tmp/t.jsonl",
        )
```

Delete its `CalibrationEntry, CalibrationTable` imports.

- [ ] **Step 7: Run the full suite — verify nothing regressed**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_calibration -v 2>&1 | tail -5
```

Expected: all 26 tests pass.

- [ ] **Step 8: Confirm the LOC budget is met**

```bash
wc -l skills/bmad-story-automator/tests/test_calibration.py skills/bmad-story-automator/tests/_calibration_fixtures.py skills/bmad-story-automator/src/story_automator/core/calibration.py
```

Expected: `test_calibration.py` ≤ 500. If still over, audit for additional duplication you may have missed (e.g., the `BuildCalibrationParsingTolerationTests.test_non_string_model_id_or_task_kind_is_skipped` builds an inline `StoryCompleted().to_dict()` — that one is logically a one-off, leave it). If you cannot trim under 500 with mechanical replacements, return to this step and split one of the largest test classes (e.g., `FormatCalibrationReportTests`) into a sibling file `test_calibration_report.py` — but flag this in the commit message because it splits the M08 surface across two files.

- [ ] **Step 9: Commit**

```bash
git add skills/bmad-story-automator/tests/test_calibration.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m08): collapse duplicate entry/table construction via shared factories"
```

---

## Task 6: Refactor `build_calibration` into three private helpers

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/calibration.py`

Currently `build_calibration` interleaves I/O, parsing, type filtering, key extraction, bucket accumulation, and entry materialization in a single 65-line function. Split into:
- `_iter_event_lines(path)` — generator over decoded JSONL lines (handles CRLF + blanks).
- `_accumulate_buckets(events)` — pure aggregation over an iterable of `Event` instances.
- `_materialize_entries(buckets)` — pure conversion of bucket dict to `dict[key, CalibrationEntry]`.

The public `build_calibration` becomes a thin orchestrator. No observable behavior changes; all 26 tests must still pass.

- [ ] **Step 1: Open the current `build_calibration` body for reference**

Run:

```bash
sed -n '59,124p' skills/bmad-story-automator/src/story_automator/core/calibration.py
```

The body you are about to replace spans roughly lines 59–124.

- [ ] **Step 2: Replace `build_calibration` and add the three private helpers**

First, add the `Iterator` / `Iterable` imports at the top of the module. Find the existing import block (`import json`, `from dataclasses import dataclass`, `from pathlib import Path`) and add immediately above the `from .common import iso_now` line:

```python
from collections.abc import Iterable, Iterator
```

Then replace the entire `build_calibration` function (everything from the `def build_calibration(jsonl_path: str | Path) -> CalibrationTable:` line through its closing `)` of the final `return CalibrationTable(...)`) — anchor on the function boundaries rather than line numbers, since prior tasks may have shifted line numbers — with:

```python
def _iter_event_lines(path: Path) -> Iterator[str]:
    """Yield non-blank decoded JSONL lines, tolerating CRLF and blanks.

    The caller is responsible for parsing; this helper is pure I/O.
    """

    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\r\n")
            if not line.strip():
                continue
            yield line


def _accumulate_buckets(
    lines: Iterable[str],
) -> tuple[int, dict[tuple[str, str], list]]:
    """Aggregate decoded JSONL lines into per-key buckets.

    Returns `(total_scanned, buckets)` where `buckets[key]` is a
    `[completed_count, failed_count, last_seen_iso]` triple. Lines that
    fail `parse_event` (malformed JSON, missing event_type, unknown
    typed fields) are silently dropped and do NOT increment
    `total_scanned`. Unknown event types parse successfully (they
    become `UnknownEvent`) and DO increment `total_scanned` but do not
    contribute to any bucket.
    """

    total_scanned = 0
    buckets: dict[tuple[str, str], list] = {}
    for line in lines:
        try:
            event = parse_event(line)
        except (ValueError, json.JSONDecodeError, TypeError):
            continue
        total_scanned += 1
        if not isinstance(event, (StoryCompleted, StoryFailed)):
            continue
        model_id = getattr(event, "model_id", None)
        task_kind = getattr(event, "task_kind", None)
        if not isinstance(model_id, str) or not isinstance(task_kind, str):
            continue
        key = (model_id, task_kind)
        bucket = buckets.setdefault(key, [0, 0, ""])
        if isinstance(event, StoryCompleted):
            bucket[0] += 1
        else:
            bucket[1] += 1
        if event.timestamp > bucket[2]:
            bucket[2] = event.timestamp
    return total_scanned, buckets


def _materialize_entries(
    buckets: dict[tuple[str, str], list],
) -> dict[tuple[str, str], CalibrationEntry]:
    """Convert raw bucket triples into immutable CalibrationEntry rows.

    Rounds success_rate to four decimal places per REQ-07.
    """

    entries: dict[tuple[str, str], CalibrationEntry] = {}
    for (model_id, task_kind), (completed, failed, last_seen) in buckets.items():
        sample_count = completed + failed
        success_rate = round(completed / sample_count, 4)
        entries[(model_id, task_kind)] = CalibrationEntry(
            model_id=model_id,
            task_kind=task_kind,
            success_rate=success_rate,
            sample_count=sample_count,
            last_seen_iso=last_seen,
        )
    return entries


def build_calibration(jsonl_path: str | Path) -> CalibrationTable:
    """Build a CalibrationTable by streaming a JSONL telemetry ledger.

    Missing paths return an empty table (not an exception). Each
    successfully parsed line increments `total_events_scanned`;
    only StoryCompleted / StoryFailed records with both `model_id`
    and `task_kind` attributes contribute to `entries`.
    """

    path = Path(jsonl_path)
    source_path = str(path)
    if not path.is_file():
        return CalibrationTable(
            entries={},
            generated_at=iso_now(),
            source_path=source_path,
            total_events_scanned=0,
        )
    total_scanned, buckets = _accumulate_buckets(_iter_event_lines(path))
    return CalibrationTable(
        entries=_materialize_entries(buckets),
        generated_at=iso_now(),
        source_path=source_path,
        total_events_scanned=total_scanned,
    )
```

- [ ] **Step 3: Run the full test suite — confirm zero behavioral regressions**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_calibration -v 2>&1 | tail -5
```

Expected: all 26 tests pass. If any fail, the refactor introduced a regression — revert and bisect by re-applying helpers one at a time.

- [ ] **Step 4: Confirm coverage remains at the previous level**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m coverage run --source=src/story_automator/core -m unittest tests.test_calibration && python -m coverage report --include="*/core/calibration.py" -m
```

Expected: ≥ the post-Task-2 coverage (target 100%, gate 85%).

- [ ] **Step 5: Confirm file size is still within budget**

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/calibration.py
```

Expected: ≤ 500. Refactor target was ~180; actual should be in the 180–220 range.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/calibration.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "refactor(m08): split build_calibration into iter/accumulate/materialize helpers"
```

---

## Task 7: Lock the new helper contracts with direct unit tests

**Files:**
- Test: `skills/bmad-story-automator/tests/test_calibration.py`

The Task 6 refactor introduced three private helpers. Lock their contracts directly so a future change to either helper that breaks `build_calibration` fails fast at the helper test, not the integration test.

- [ ] **Step 1: Add the helper unit tests**

Append to `tests/test_calibration.py` immediately before the `if __name__ == "__main__":` guard:

```python
class IterEventLinesTests(unittest.TestCase):
    def test_blank_lines_and_crlf_are_stripped(self) -> None:
        from story_automator.core.calibration import _iter_event_lines

        with _fixture_dir() as tmpdir:
            ledger = Path(tmpdir) / "raw.jsonl"
            ledger.write_bytes(b'a\r\n\r\nb\n   \nc\r\n')
            lines = list(_iter_event_lines(ledger))

        self.assertEqual(lines, ["a", "b", "c"])


class MaterializeEntriesTests(unittest.TestCase):
    def test_buckets_round_to_four_decimals_and_aggregate(self) -> None:
        from story_automator.core.calibration import _materialize_entries

        buckets = {
            ("m", "t"): [2, 1, "2026-06-14T12:00:00Z"],
            ("m", "u"): [0, 4, "2026-06-14T11:00:00Z"],
        }
        entries = _materialize_entries(buckets)

        self.assertEqual(entries[("m", "t")].success_rate, 0.6667)
        self.assertEqual(entries[("m", "t")].sample_count, 3)
        self.assertEqual(entries[("m", "u")].success_rate, 0.0)
        self.assertEqual(entries[("m", "u")].sample_count, 4)
```

> **Engineer note.** The shim is NOT needed here: `_iter_event_lines` is pure file I/O, and `_materialize_entries` operates on a pre-built bucket dict with no `Event` instances involved. Do NOT add `setUpClass`/`tearDownClass` to these two classes.
>
> **Ruff note.** Importing private (`_`-prefixed) names from a module is allowed under the project's ruff profile — these are internal helpers exposed solely for testing, and the test module is the only consumer. If ruff `PLC2701` (private-name import) fires, prefix the import with `# noqa: PLC2701` ONLY on the helper-import line (do NOT broaden the suppression).

- [ ] **Step 2: Run and verify the new helper tests pass**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_calibration.IterEventLinesTests tests.test_calibration.MaterializeEntriesTests -v
```

Expected: 2 tests pass.

- [ ] **Step 3: Re-confirm LOC budget**

```bash
wc -l skills/bmad-story-automator/tests/test_calibration.py
```

Expected: ≤ 500. The two new test classes add ~30 LOC; this is fine as long as the Task 5 trims gave you headroom. If you are now over 500, return to Task 5 step 8 and split out one more redundancy (a common one: collapse `test_miss_returns_default_0_5` and `test_miss_returns_custom_default` in `LookupSuccessRateTests` into a single parameterized loop).

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/tests/test_calibration.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m08): unit-test _iter_event_lines and _materialize_entries helpers"
```

---

## Task 8: Quality gate — ruff lint and format

**Files:**
- Modify (only if ruff complains): `skills/bmad-story-automator/src/story_automator/core/calibration.py`
- Modify (only if ruff complains): `skills/bmad-story-automator/tests/test_calibration.py`
- Modify (only if ruff complains): `skills/bmad-story-automator/tests/_calibration_fixtures.py`

- [ ] **Step 1: Run `ruff check` on all three M08 files**

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/calibration.py \
  skills/bmad-story-automator/tests/test_calibration.py \
  skills/bmad-story-automator/tests/_calibration_fixtures.py
```

Expected: zero output, exit code 0. The most likely findings if any: unused import (`CalibrationEntry`/`CalibrationTable` left over from Task 5), or line length on the new helper signatures. Fix in place — do NOT add `# noqa`. Re-run until clean.

- [ ] **Step 2: Run `ruff format --check`**

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/calibration.py \
  skills/bmad-story-automator/tests/test_calibration.py \
  skills/bmad-story-automator/tests/_calibration_fixtures.py
```

If diffs are reported, apply them:

```bash
python -m ruff format \
  skills/bmad-story-automator/src/story_automator/core/calibration.py \
  skills/bmad-story-automator/tests/test_calibration.py \
  skills/bmad-story-automator/tests/_calibration_fixtures.py
```

Then re-run `--check` until exit 0.

- [ ] **Step 3: Re-run tests in case the format pass shifted multi-line structures**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_calibration 2>&1 | tail -3
```

Expected: `OK`.

- [ ] **Step 4: Commit (only if any edits were made)**

```bash
git add skills/bmad-story-automator/src/story_automator/core/calibration.py skills/bmad-story-automator/tests/test_calibration.py skills/bmad-story-automator/tests/_calibration_fixtures.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(m08): satisfy ruff lint and format for m2-aggregation"
```

If no edits were needed, skip the commit and proceed to Task 9.

---

## Task 9: Quality gate — file-size, import allowlist, placeholder tokens, compileall

**Files:**
- (no expected edits)

- [ ] **Step 1: Confirm `wc -l` budget on every M08 file**

```bash
wc -l \
  skills/bmad-story-automator/src/story_automator/core/calibration.py \
  skills/bmad-story-automator/tests/test_calibration.py \
  skills/bmad-story-automator/tests/_calibration_fixtures.py
```

Expected: `core/calibration.py` ≤ 500, `tests/test_calibration.py` ≤ 500, `tests/_calibration_fixtures.py` ≤ 500. If any value exceeds 500, return to the relevant earlier task and trim further before continuing.

- [ ] **Step 2: Import-allowlist grep on `core/calibration.py`**

```bash
grep -nE "(^|[^_a-z])(requests|httpx|aiohttp|subprocess|os\.system|psutil|filelock)([^_a-z]|$)" \
  skills/bmad-story-automator/src/story_automator/core/calibration.py
```

Expected: zero matches (exit code 1 from grep, but no output lines).

- [ ] **Step 3: Four-letter placeholder-token grep on both new files**

```bash
grep -nE "\b(TODO|FIXME|XXXX|TBD|TKTK)\b" \
  skills/bmad-story-automator/src/story_automator/core/calibration.py \
  skills/bmad-story-automator/tests/test_calibration.py \
  skills/bmad-story-automator/tests/_calibration_fixtures.py
```

Expected: zero matches. If matches appear, replace each with an actionable comment that names the responsible milestone, or remove it.

- [ ] **Step 4: `compileall` parses `core/calibration.py` under Python 3.11+**

```bash
python -m compileall skills/bmad-story-automator/src/story_automator/core/calibration.py
```

Expected: `Compiling ...` line followed by exit code 0, no `SyntaxWarning` output.

- [ ] **Step 5: Coverage gate at `--fail-under=85`**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m coverage run --source=src/story_automator/core -m unittest tests.test_calibration && python -m coverage report --include="*/core/calibration.py" --fail-under=85
```

Expected: report shows `Cover` ≥ 85% (target 100% post-Task 2) and the command exits 0.

- [ ] **Step 6: No commit required (verification only)**

If any of the steps prompted an edit (e.g., a stray `TODO` was found), commit it:

```bash
git add <touched files>
git commit --trailer "Generated-By: claude-opus-4-7" -m "chore(m08): satisfy quality-gate grep and size budgets"
```

Otherwise proceed to Task 10.

---

## Task 10: Cross-platform sanity — repo-root tests still pass

**Files:**
- (no edits expected)

The M08 tests live under `skills/bmad-story-automator/tests/` and are NOT discovered by the repo-root `npm run test:python` script — that contract was set in m1-types and is documented in the spec. We still verify the repo-root suite stays green so M08 has not regressed any sibling module.

- [ ] **Step 1: Run the repo-root suite**

```bash
npm run test:python
```

Expected: zero failures, zero errors.

- [ ] **Step 2: Final end-to-end gate sweep**

Run the full sequence the spec lists as quality gates:

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/calibration.py \
  skills/bmad-story-automator/tests/test_calibration.py && \
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/calibration.py \
  skills/bmad-story-automator/tests/test_calibration.py && \
wc -l skills/bmad-story-automator/src/story_automator/core/calibration.py \
      skills/bmad-story-automator/tests/test_calibration.py && \
python -m compileall skills/bmad-story-automator/src/story_automator/core/calibration.py
```

Then from `skills/bmad-story-automator/`:

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_calibration && \
  PYTHONPATH=src python -m coverage run --source=src/story_automator/core -m unittest tests.test_calibration && \
  python -m coverage report --include="*/core/calibration.py" --fail-under=85
```

Expected: every command exits 0; both `wc -l` values ≤ 500.

- [ ] **Step 3: No commit required**

If the sweep prompted no edits, the milestone is complete with the prior commits as-is. If a final touch-up was needed:

```bash
git add <touched files>
git commit --trailer "Generated-By: claude-opus-4-7" -m "chore(m08): final quality-gate sweep before m2-aggregation close"
```

---

## Self-review notes

- **Spec coverage check.** The five spec sections this milestone is scoped to are all addressed:
  - REQ-05 (streaming UTF-8, CRLF / blank tolerance) — locked by `IterEventLinesTests` (Task 7) and pre-existing `BuildCalibrationParsingTolerationTests`. The malformed-line tolerance (which REQ-05's "tolerates" wording implies for the parse step) is now explicitly tested (Task 2).
  - REQ-06 (delegate to `parse_event`, filter to StoryCompleted/Failed) — exercised by every aggregation test and the new multi-key test (Task 3).
  - REQ-07 (success-rate formula, four-decimal rounding, `last_seen_iso` max) — locked by `MaterializeEntriesTests` (Task 7) plus pre-existing `BuildCalibrationMixedAggregationTests` and the new multi-key test (Task 3).
  - REQ-08 (missing path → empty table, no raise) — pre-existing `BuildCalibrationMissingPathTests`. The Task 6 refactor preserves this branch verbatim.
  - REQ-14 (fixtures via `compact_json` + `ensure_dir`-rooted temp dir) — `_fixture_dir` and `_write_jsonl` in `_calibration_fixtures.py`. The Task 4 / Task 5 trim shrinks the public test surface but does NOT relocate fixtures outside that helper module.
- **Non-functional coverage.** The 500-LOC cap on `test_calibration.py` is the load-bearing constraint this plan is built around — Tasks 4 and 5 are mandatory because the file currently violates it. Task 6 keeps `core/calibration.py` well under 500.
- **Behavior preservation.** Task 6's refactor changes structure, not behavior. The full 26+ test suite (with the 2 new from Task 2, 1 new from Task 3, 2 new from Task 7) is the regression net. Coverage rises from 97% → 100% on `core/calibration.py`.
- **Placeholder scan.** No `TBD` / `TODO` / `FIXME` / `XXXX` / `TKTK` appears in any task body — checked manually.
- **Type and name consistency.** Public symbols (`CalibrationEntry`, `CalibrationTable`, `build_calibration`, `lookup_success_rate`, `format_calibration_report`) are referenced identically across every task. New private helpers (`_iter_event_lines`, `_accumulate_buckets`, `_materialize_entries`) are introduced in Task 6 and exercised in Task 7 with the same names.
- **M01 gap status.** The `_ExtendedEventShim` remains. M01 still has not added `model_id` / `task_kind` to `StoryCompleted` / `StoryFailed`. Removing the shim is an M01 follow-up, NOT an M08 m2-aggregation deliverable.
