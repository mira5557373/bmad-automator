# M09 — Drift Detector Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure-functional, I/O-free `core/drift_detector.py` that compares two M08 `CalibrationTable` instances (baseline vs. current) and produces a deterministic `DriftReport` whose entries classify per-`(model_id, task_kind)` change into STABLE / MINOR_DRIFT / MAJOR_DRIFT / SEVERE_DRIFT bands, plus a plain-ASCII formatter.

**Architecture:** Single new module at `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`. Imports limited to stdlib (`enum`, `dataclasses`, `__future__`) plus `story_automator.core.common.iso_now` and the `CalibrationTable` / `CalibrationEntry` types from `story_automator.core.calibration`. Zero file-system access, zero subprocess, zero network. The classifier walks the union of keys, fills missing sides with the 0.5 default (matches `lookup_success_rate`), rounds each delta with `round(value, 4)`, classifies on `abs(delta)` half-open bands, and sorts by `(-abs(delta), model_id, task_kind)`.

**Tech Stack:** Python 3.11+, stdlib only, `unittest.TestCase` for tests, ruff for lint/format, stdlib `coverage` for the 90% gate.

---

## Context for the Engineer

You are implementing M09 against the existing M08 calibration module. A few facts you must internalize before writing code:

1. **`CalibrationTable` and `CalibrationEntry`** live at `skills/bmad-story-automator/src/story_automator/core/calibration.py`. `CalibrationTable` exposes `entries: dict[tuple[str, str], CalibrationEntry]`, `generated_at: str`, `source_path: str`, `total_events_scanned: int`. `CalibrationEntry` exposes `model_id`, `task_kind`, `success_rate`, `sample_count`, `last_seen_iso` and is `frozen=True`.
2. **Shared helpers** — `iso_now()` lives at `story_automator.core.common`. Do NOT duplicate.
3. **`lookup_success_rate` default is `0.5`.** Per REQ-08, M09 must match this exact default for missing keys; changing it would silently shift drift readings for any consumer that mixes the two helpers.
4. **Test location.** REQ-01 mandates `skills/bmad-story-automator/tests/test_drift_detector.py`. The tests package already exists from M08 (it has `__init__.py`). Place fixtures inline in the test module — no fixture sidecar is required for this milestone; the file size budget (≤500 LOC) accommodates inline construction.
5. **Test runner.** The spec writes the command as `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_drift_detector` "from the repository root". In practice (matching the M08 pattern), the executable form is `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector`. Use the `cd`-form during local iteration; the literal spec form is intended for CI invocations that mount `skills/bmad-story-automator` as the working directory.
6. **No `Optional` / `Union`** — use PEP 604 unions everywhere (`float | None`, `list[DriftEntry]`).
7. **First non-comment line** in both new files: `from __future__ import annotations`.
8. **Line endings:** LF only. The `format_drift_report` snapshot test must compare against literal `"\n"`-joined strings — never use `os.linesep`.
9. **Determinism contract.** Per the non-functional requirements, two `compute_drift` calls with the same two inputs must produce reports whose `entries` list is **bitwise identical**; only `generated_at` is permitted to vary. The classifier must therefore not rely on Python's iteration order of `dict.keys()` directly without sorting, and must avoid `set()` of mixed tuple types where ordering matters.
10. **Imports always at the top of the test file.** Each task below adds imports to the existing `import` block at the top of `tests/test_drift_detector.py`, NOT scattered through the file. Ruff `E402` is in the default selection and will flag any module-level import that follows a non-import statement. When a step says "add this import", insert it into the existing import block at the top of the file (alphabetically grouped: stdlib → third-party → `story_automator.*` → `tests.*`). The test class itself is appended to the bottom of the file.
11. **Placeholder-token discipline.** Source files must not contain the literal substrings `TODO`, `FIXME`, `XXXX`, or `TBDX` (including inside docstrings). Describe numeric formats as "four-decimal-place" prose, not `0.XXXX` glyphs — the latter would self-trip the placeholder grep.
12. **Anti-scope:** No CLI surface. No persistence. No alarms or exit codes. No threshold tuning. Do not modify `core/calibration.py` or `core/telemetry_events.py`.

---

## File Structure

- **Create:** `skills/bmad-story-automator/src/story_automator/core/drift_detector.py` (≤300 LOC; expected ~120 LOC)
- **Create:** `skills/bmad-story-automator/tests/test_drift_detector.py` (≤500 LOC; expected ~300 LOC)

No existing files are modified by this milestone. No package-level `__init__.py` changes (REQ-15).

---

## Task 1: Confirm dependency surface and stub the module

**Files:**
- Read: `skills/bmad-story-automator/src/story_automator/core/calibration.py`
- Read: `skills/bmad-story-automator/src/story_automator/core/common.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`

- [ ] **Step 1: Confirm the dependency module surface**

Open `skills/bmad-story-automator/src/story_automator/core/calibration.py` and confirm:
- `CalibrationEntry` and `CalibrationTable` appear in `__all__`.
- `CalibrationEntry` is `@dataclass(kw_only=True, frozen=True)` with fields `model_id`, `task_kind`, `success_rate`, `sample_count`, `last_seen_iso`.
- `CalibrationTable.entries` is keyed by `tuple[str, str]`.
- `CalibrationTable.source_path` is a `str`.

Open `skills/bmad-story-automator/src/story_automator/core/common.py` and confirm `iso_now()` returns `"YYYY-MM-DDTHH:MM:SSZ"`.

No code changes in this step.

- [ ] **Step 2: Create the module stub**

Create `skills/bmad-story-automator/src/story_automator/core/drift_detector.py` with exactly this content:

```python
"""Drift detector (M09).

Pure-functional comparator: takes two CalibrationTable snapshots
(baseline + current), classifies each (model_id, task_kind) pair's
shift into one of four severity bands, and emits a deterministic
DriftReport plus a plain-ASCII formatter. No I/O, no telemetry reads,
no alarms.
"""

from __future__ import annotations

__all__ = [
    "DriftClassification",
    "DriftEntry",
    "DriftReport",
    "compute_drift",
    "format_drift_report",
]

from dataclasses import dataclass
from enum import Enum

from .calibration import CalibrationTable
from .common import iso_now

STABLE_MAX = 0.05
MINOR_MAX = 0.10
MAJOR_MAX = 0.20
_MISSING_RATE_DEFAULT = 0.5
```

- [ ] **Step 3: Verify the stub imports cleanly**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -c "from story_automator.core import drift_detector; print(drift_detector.__all__)"`
Expected stdout: `['DriftClassification', 'DriftEntry', 'DriftReport', 'compute_drift', 'format_drift_report']`

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m09): stub drift_detector module with __all__ and boundary constants"
```

---

## Task 2: Add `DriftClassification` enum (REQ-03)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`
- Create: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Write the failing test**

Create `skills/bmad-story-automator/tests/test_drift_detector.py` with:

```python
from __future__ import annotations

import unittest

from story_automator.core.drift_detector import DriftClassification


class DriftClassificationTests(unittest.TestCase):
    def test_members_and_order(self) -> None:
        self.assertEqual(
            [m.name for m in DriftClassification],
            ["STABLE", "MINOR_DRIFT", "MAJOR_DRIFT", "SEVERE_DRIFT"],
        )

    def test_values_equal_lowercase_names(self) -> None:
        for member in DriftClassification:
            self.assertEqual(member.value, member.name.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: `ImportError: cannot import name 'DriftClassification' from 'story_automator.core.drift_detector'`.

- [ ] **Step 3: Implement `DriftClassification`**

Append to `skills/bmad-story-automator/src/story_automator/core/drift_detector.py` immediately after the constants block:

```python


class DriftClassification(Enum):
    """Four-tier categorical band over |delta|."""

    STABLE = "stable"
    MINOR_DRIFT = "minor_drift"
    MAJOR_DRIFT = "major_drift"
    SEVERE_DRIFT = "severe_drift"
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m09): add DriftClassification enum with four severity tiers"
```

---

## Task 3: Add `DriftEntry` dataclass (REQ-04)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Write the failing test**

**Add this line to the existing import block at the top of `test_drift_detector.py`:** `from story_automator.core.drift_detector import DriftEntry` (place it next to the existing `from story_automator.core.drift_detector import DriftClassification` line — ruff `E402` will reject mid-file imports).

**Append the test class to the bottom of the file, above the `if __name__ == "__main__":` guard:**

```python
class DriftEntryTests(unittest.TestCase):
    def test_construct_with_kw_only_fields(self) -> None:
        entry = DriftEntry(
            model_id="gpt-4o-mini",
            task_kind="story",
            baseline_success_rate=0.80,
            current_success_rate=0.75,
            delta=round(0.75 - 0.80, 4),
            classification=DriftClassification.STABLE,
        )
        self.assertEqual(entry.model_id, "gpt-4o-mini")
        self.assertEqual(entry.task_kind, "story")
        self.assertEqual(entry.baseline_success_rate, 0.80)
        self.assertEqual(entry.current_success_rate, 0.75)
        self.assertEqual(entry.delta, -0.05)
        self.assertIs(entry.classification, DriftClassification.STABLE)

    def test_is_frozen(self) -> None:
        import dataclasses

        entry = DriftEntry(
            model_id="m",
            task_kind="t",
            baseline_success_rate=0.0,
            current_success_rate=0.0,
            delta=0.0,
            classification=DriftClassification.STABLE,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.model_id = "other"  # type: ignore[misc]

    def test_positional_construction_rejected(self) -> None:
        with self.assertRaises(TypeError):
            DriftEntry(  # type: ignore[call-arg]
                "m", "t", 0.0, 0.0, 0.0, DriftClassification.STABLE,
            )
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: `ImportError: cannot import name 'DriftEntry'`.

- [ ] **Step 3: Implement `DriftEntry`**

Append to `drift_detector.py`:

```python


@dataclass(kw_only=True, frozen=True)
class DriftEntry:
    """One row in a DriftReport.

    `delta == current_success_rate - baseline_success_rate`, rounded to
    four decimals by the producer (`compute_drift`). Stored verbatim
    here so consumers can render without re-rounding.
    """

    model_id: str
    task_kind: str
    baseline_success_rate: float
    current_success_rate: float
    delta: float
    classification: DriftClassification
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m09): add DriftEntry frozen kw_only dataclass"
```

---

## Task 4: Add `DriftReport` dataclass (REQ-05)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Write the failing test**

**Add to the import block at top:** `from story_automator.core.drift_detector import DriftReport`.

**Append the test class to the bottom of the file (above the `if __name__` guard):**

```python
class DriftReportTests(unittest.TestCase):
    def test_construct_with_kw_only_fields(self) -> None:
        report = DriftReport(
            entries=[],
            generated_at="2026-06-15T00:00:00Z",
            baseline_source="/tmp/base.jsonl",
            current_source="/tmp/now.jsonl",
        )
        self.assertEqual(report.entries, [])
        self.assertEqual(report.generated_at, "2026-06-15T00:00:00Z")
        self.assertEqual(report.baseline_source, "/tmp/base.jsonl")
        self.assertEqual(report.current_source, "/tmp/now.jsonl")

    def test_entries_is_mutable_list(self) -> None:
        report = DriftReport(
            entries=[],
            generated_at="2026-06-15T00:00:00Z",
            baseline_source="b",
            current_source="c",
        )
        report.entries.append(
            DriftEntry(
                model_id="m",
                task_kind="t",
                baseline_success_rate=0.0,
                current_success_rate=0.0,
                delta=0.0,
                classification=DriftClassification.STABLE,
            )
        )
        self.assertEqual(len(report.entries), 1)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: `ImportError: cannot import name 'DriftReport'`.

- [ ] **Step 3: Implement `DriftReport`**

Append to `drift_detector.py`:

```python


@dataclass(kw_only=True)
class DriftReport:
    """Output of `compute_drift`.

    `entries` is ordered by descending `abs(delta)`, then ascending
    `model_id`, then ascending `task_kind`. `baseline_source` and
    `current_source` echo the `source_path` of each input
    CalibrationTable so the report is self-describing without an
    out-of-band caller note.
    """

    entries: list[DriftEntry]
    generated_at: str
    baseline_source: str
    current_source: str
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m09): add DriftReport kw_only dataclass"
```

---

## Task 5: Add the internal `_classify` helper (REQ-07 boundary contract)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

The boundary contract is half-open: `|delta| < 0.05` is `STABLE`, `0.05 <= |delta| < 0.10` is `MINOR_DRIFT`, `0.10 <= |delta| < 0.20` is `MAJOR_DRIFT`, `|delta| >= 0.20` is `SEVERE_DRIFT`. Exercising the boundaries from below AND from above is REQ-13.

- [ ] **Step 1: Write the failing test**

**Add to the import block at top:**

```python
from story_automator.core.drift_detector import (
    MAJOR_MAX,
    MINOR_MAX,
    STABLE_MAX,
    _classify,
)
```

**Append the test class to the bottom of the file:**

```python
class ClassifyHelperTests(unittest.TestCase):
    def test_zero_is_stable(self) -> None:
        self.assertIs(_classify(0.0), DriftClassification.STABLE)

    def test_just_below_stable_max_is_stable(self) -> None:
        self.assertIs(_classify(0.0499), DriftClassification.STABLE)
        self.assertIs(_classify(-0.0499), DriftClassification.STABLE)

    def test_stable_max_is_minor(self) -> None:
        self.assertIs(_classify(STABLE_MAX), DriftClassification.MINOR_DRIFT)
        self.assertIs(_classify(-STABLE_MAX), DriftClassification.MINOR_DRIFT)

    def test_just_below_minor_max_is_minor(self) -> None:
        self.assertIs(_classify(0.0999), DriftClassification.MINOR_DRIFT)

    def test_minor_max_is_major(self) -> None:
        self.assertIs(_classify(MINOR_MAX), DriftClassification.MAJOR_DRIFT)
        self.assertIs(_classify(-MINOR_MAX), DriftClassification.MAJOR_DRIFT)

    def test_just_below_major_max_is_major(self) -> None:
        self.assertIs(_classify(0.1999), DriftClassification.MAJOR_DRIFT)

    def test_major_max_is_severe(self) -> None:
        self.assertIs(_classify(MAJOR_MAX), DriftClassification.SEVERE_DRIFT)
        self.assertIs(_classify(-MAJOR_MAX), DriftClassification.SEVERE_DRIFT)

    def test_large_magnitude_is_severe(self) -> None:
        self.assertIs(_classify(0.95), DriftClassification.SEVERE_DRIFT)
        self.assertIs(_classify(-0.95), DriftClassification.SEVERE_DRIFT)

    def test_boundary_constants_match_spec(self) -> None:
        self.assertEqual(STABLE_MAX, 0.05)
        self.assertEqual(MINOR_MAX, 0.10)
        self.assertEqual(MAJOR_MAX, 0.20)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: `ImportError: cannot import name '_classify'`.

- [ ] **Step 3: Implement `_classify`**

Append to `drift_detector.py`:

```python


def _classify(delta: float) -> DriftClassification:
    """Bin `delta` into a DriftClassification using REQ-07 bands.

    Bands are half-open: the lower bound belongs to the higher tier.
    This matches the spec language "`|delta| < 0.05` is STABLE,
    `0.05 <= |delta| < 0.10` is MINOR_DRIFT, ...".
    """

    magnitude = abs(delta)
    if magnitude < STABLE_MAX:
        return DriftClassification.STABLE
    if magnitude < MINOR_MAX:
        return DriftClassification.MINOR_DRIFT
    if magnitude < MAJOR_MAX:
        return DriftClassification.MAJOR_DRIFT
    return DriftClassification.SEVERE_DRIFT
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 16 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m09): add _classify helper covering all four severity bands"
```

---

## Task 6: Add a shared test-fixture builder for `CalibrationTable` (REQ-14)

Before implementing `compute_drift`, factor out a tiny in-memory fixture builder so subsequent tests stay compact. REQ-14 forbids JSONL writes and `build_calibration` — fixtures must be hand-composed.

**Files:**
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Add the fixture helpers**

**Add to the import block at top:** `from story_automator.core.calibration import CalibrationEntry, CalibrationTable`.

**Append the fixture helpers to the bottom of the file (above `if __name__`):**

```python
def _entry(model_id: str, task_kind: str, success_rate: float) -> CalibrationEntry:
    return CalibrationEntry(
        model_id=model_id,
        task_kind=task_kind,
        success_rate=round(success_rate, 4),
        sample_count=10,
        last_seen_iso="2026-06-15T00:00:00Z",
    )


def _table(
    *entries: CalibrationEntry,
    source_path: str = "/fixtures/table.jsonl",
) -> CalibrationTable:
    return CalibrationTable(
        entries={(e.model_id, e.task_kind): e for e in entries},
        generated_at="2026-06-15T00:00:00Z",
        source_path=source_path,
        total_events_scanned=sum(e.sample_count for e in entries),
    )
```

- [ ] **Step 2: Run the suite to confirm no regression**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 16 tests still pass (no new tests yet; this commit just adds the helpers).

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): add in-memory CalibrationTable fixture builders for drift tests"
```

---

## Task 7: Implement `compute_drift` — identical tables produce all-STABLE entries (REQ-06, REQ-13)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Write the failing test**

**Add to the import block at top:** `from story_automator.core.drift_detector import compute_drift`.

**Append the test class to the bottom of the file:**

```python
class ComputeDriftBaselineTests(unittest.TestCase):
    def test_identical_tables_produce_all_stable(self) -> None:
        baseline = _table(
            _entry("gpt-4o-mini", "story", 0.80),
            _entry("opus-4-1", "review", 0.92),
            source_path="/fixtures/base.jsonl",
        )
        current = _table(
            _entry("gpt-4o-mini", "story", 0.80),
            _entry("opus-4-1", "review", 0.92),
            source_path="/fixtures/now.jsonl",
        )
        report = compute_drift(baseline=baseline, current=current)
        self.assertEqual(report.baseline_source, "/fixtures/base.jsonl")
        self.assertEqual(report.current_source, "/fixtures/now.jsonl")
        self.assertEqual(len(report.entries), 2)
        for entry in report.entries:
            self.assertEqual(entry.delta, 0.0)
            self.assertIs(entry.classification, DriftClassification.STABLE)
        # generated_at is from iso_now(); we only check the shape here.
        self.assertRegex(report.generated_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_inputs_not_mutated(self) -> None:
        baseline = _table(_entry("m", "t", 0.5))
        current = _table(_entry("m", "t", 0.6))
        baseline_snapshot = dict(baseline.entries)
        current_snapshot = dict(current.entries)
        compute_drift(baseline=baseline, current=current)
        self.assertEqual(baseline.entries, baseline_snapshot)
        self.assertEqual(current.entries, current_snapshot)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: `ImportError: cannot import name 'compute_drift'`.

- [ ] **Step 3: Implement `compute_drift` (initial version, no sorting yet)**

Append to `drift_detector.py`:

```python


def compute_drift(
    baseline: CalibrationTable,
    current: CalibrationTable,
) -> DriftReport:
    """Compare two CalibrationTable snapshots, return a DriftReport.

    Signature is positional per REQ-06. Per REQ-08, any key missing on
    one side is filled with 0.5 (matches `lookup_success_rate`'s
    default).
    """

    keys = set(baseline.entries.keys()) | set(current.entries.keys())
    entries: list[DriftEntry] = []
    for key in keys:
        baseline_entry = baseline.entries.get(key)
        current_entry = current.entries.get(key)
        baseline_rate = (
            baseline_entry.success_rate if baseline_entry is not None else _MISSING_RATE_DEFAULT
        )
        current_rate = (
            current_entry.success_rate if current_entry is not None else _MISSING_RATE_DEFAULT
        )
        delta = round(current_rate - baseline_rate, 4)
        model_id, task_kind = key
        entries.append(
            DriftEntry(
                model_id=model_id,
                task_kind=task_kind,
                baseline_success_rate=baseline_rate,
                current_success_rate=current_rate,
                delta=delta,
                classification=_classify(delta),
            )
        )
    entries.sort(key=lambda e: (-abs(e.delta), e.model_id, e.task_kind))
    return DriftReport(
        entries=entries,
        generated_at=iso_now(),
        baseline_source=baseline.source_path,
        current_source=current.source_path,
    )
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 18 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m09): implement compute_drift over key-union with rounded deltas"
```

---

## Task 8: Cover the three classification boundaries from below and above (REQ-13)

**Files:**
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Add boundary-crossing tests against `compute_drift`**

Append to `test_drift_detector.py`:

```python
class ComputeDriftBoundaryTests(unittest.TestCase):
    def _drift_entry(self, baseline_rate: float, current_rate: float) -> DriftEntry:
        baseline = _table(_entry("m", "t", baseline_rate))
        current = _table(_entry("m", "t", current_rate))
        report = compute_drift(baseline=baseline, current=current)
        self.assertEqual(len(report.entries), 1)
        return report.entries[0]

    def test_stable_below_then_minor_at_boundary(self) -> None:
        below = self._drift_entry(0.80, 0.8499)
        at = self._drift_entry(0.80, 0.85)
        self.assertIs(below.classification, DriftClassification.STABLE)
        self.assertIs(at.classification, DriftClassification.MINOR_DRIFT)

    def test_minor_below_then_major_at_boundary(self) -> None:
        below = self._drift_entry(0.80, 0.8999)
        at = self._drift_entry(0.80, 0.90)
        self.assertIs(below.classification, DriftClassification.MINOR_DRIFT)
        self.assertIs(at.classification, DriftClassification.MAJOR_DRIFT)

    def test_major_below_then_severe_at_boundary(self) -> None:
        below = self._drift_entry(0.80, 0.9999)
        at = self._drift_entry(0.60, 0.80)
        self.assertIs(below.classification, DriftClassification.MAJOR_DRIFT)
        self.assertIs(at.classification, DriftClassification.SEVERE_DRIFT)

    def test_negative_deltas_classify_symmetrically_stable_minor(self) -> None:
        below = self._drift_entry(0.80, 0.7501)
        at = self._drift_entry(0.85, 0.80)
        self.assertIs(below.classification, DriftClassification.STABLE)
        self.assertIs(at.classification, DriftClassification.MINOR_DRIFT)

    def test_negative_deltas_classify_symmetrically_minor_major(self) -> None:
        below = self._drift_entry(0.80, 0.7001)
        at = self._drift_entry(0.90, 0.80)
        self.assertIs(below.classification, DriftClassification.MINOR_DRIFT)
        self.assertIs(at.classification, DriftClassification.MAJOR_DRIFT)

    def test_negative_deltas_classify_symmetrically_major_severe(self) -> None:
        below = self._drift_entry(0.80, 0.6001)
        at = self._drift_entry(0.80, 0.60)
        self.assertIs(below.classification, DriftClassification.MAJOR_DRIFT)
        self.assertIs(at.classification, DriftClassification.SEVERE_DRIFT)
```

- [ ] **Step 2: Run the tests and confirm they pass**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 24 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): cover every classification boundary from below and above"
```

---

## Task 9: Cover key-only-in-baseline and key-only-in-current with 0.5 default (REQ-08, REQ-13)

**Files:**
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Add missing-side tests**

Append to `test_drift_detector.py`:

```python
class ComputeDriftMissingKeyTests(unittest.TestCase):
    def test_key_only_in_baseline_gets_current_default(self) -> None:
        baseline = _table(_entry("gpt-4o-mini", "story", 0.95))
        current = _table()
        report = compute_drift(baseline=baseline, current=current)
        self.assertEqual(len(report.entries), 1)
        entry = report.entries[0]
        self.assertEqual(entry.model_id, "gpt-4o-mini")
        self.assertEqual(entry.task_kind, "story")
        self.assertEqual(entry.baseline_success_rate, 0.95)
        self.assertEqual(entry.current_success_rate, 0.5)
        self.assertEqual(entry.delta, round(0.5 - 0.95, 4))
        self.assertIs(entry.classification, DriftClassification.SEVERE_DRIFT)

    def test_key_only_in_current_gets_baseline_default(self) -> None:
        baseline = _table()
        current = _table(_entry("opus-4-1", "review", 0.30))
        report = compute_drift(baseline=baseline, current=current)
        self.assertEqual(len(report.entries), 1)
        entry = report.entries[0]
        self.assertEqual(entry.model_id, "opus-4-1")
        self.assertEqual(entry.task_kind, "review")
        self.assertEqual(entry.baseline_success_rate, 0.5)
        self.assertEqual(entry.current_success_rate, 0.30)
        self.assertEqual(entry.delta, round(0.30 - 0.5, 4))
        self.assertIs(entry.classification, DriftClassification.MAJOR_DRIFT)

    def test_empty_inputs_produce_empty_entries(self) -> None:
        report = compute_drift(baseline=_table(), current=_table())
        self.assertEqual(report.entries, [])
```

- [ ] **Step 2: Run the tests and confirm they pass**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 27 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): cover missing-side defaults and empty-input cases"
```

---

## Task 10: Lock the sort order — `(-abs(delta), model_id, task_kind)` (REQ-09, REQ-13)

**Files:**
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Write the sort-order test**

Append to `test_drift_detector.py`:

```python
class ComputeDriftSortOrderTests(unittest.TestCase):
    def test_entries_sorted_by_abs_delta_then_model_then_task(self) -> None:
        baseline = _table(
            _entry("alpha", "story", 0.50),     # delta = +0.30 -> severe
            _entry("beta", "story", 0.50),      # delta = +0.05 -> minor
            _entry("gamma", "review", 0.50),    # delta = -0.15 -> major
            _entry("alpha", "review", 0.50),    # delta = +0.30 -> severe (ties on |delta|)
            _entry("beta", "review", 0.50),     # delta = 0.00 -> stable
        )
        current = _table(
            _entry("alpha", "story", 0.80),
            _entry("beta", "story", 0.55),
            _entry("gamma", "review", 0.35),
            _entry("alpha", "review", 0.80),
            _entry("beta", "review", 0.50),
        )
        report = compute_drift(baseline=baseline, current=current)
        observed = [(e.model_id, e.task_kind, e.delta) for e in report.entries]
        self.assertEqual(
            observed,
            [
                ("alpha", "review", 0.30),
                ("alpha", "story", 0.30),
                ("gamma", "review", -0.15),
                ("beta", "story", 0.05),
                ("beta", "review", 0.0),
            ],
        )

    def test_repeated_calls_return_identical_entries_modulo_generated_at(self) -> None:
        baseline = _table(
            _entry("alpha", "story", 0.60),
            _entry("beta", "review", 0.40),
        )
        current = _table(
            _entry("alpha", "story", 0.80),
            _entry("beta", "review", 0.10),
        )
        first = compute_drift(baseline=baseline, current=current)
        second = compute_drift(baseline=baseline, current=current)
        self.assertEqual(first.entries, second.entries)
        self.assertEqual(first.baseline_source, second.baseline_source)
        self.assertEqual(first.current_source, second.current_source)
```

- [ ] **Step 2: Run the tests and confirm they pass**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 29 tests pass. If a tie-break is wrong the first test will fail with a clear diff.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): lock sort order and bitwise determinism of compute_drift entries"
```

---

## Task 11: Implement `format_drift_report` (REQ-10)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Write the failing snapshot test**

**Add to the import block at top:** `from story_automator.core.drift_detector import format_drift_report`.

**Append the test class to the bottom of the file:**

```python
class FormatDriftReportTests(unittest.TestCase):
    def test_snapshot_for_known_fixture(self) -> None:
        baseline = _table(
            _entry("alpha", "story", 0.80),
            _entry("beta", "review", 0.90),
            source_path="/fixtures/base.jsonl",
        )
        current = _table(
            _entry("alpha", "story", 0.60),   # delta = -0.20 -> severe
            _entry("beta", "review", 0.93),   # delta = +0.03 -> stable
            source_path="/fixtures/now.jsonl",
        )
        report = compute_drift(baseline=baseline, current=current)
        rendered = format_drift_report(report)
        expected = (
            "baseline: /fixtures/base.jsonl\tcurrent: /fixtures/now.jsonl\n"
            "model_id\ttask_kind\tbaseline\tcurrent\tdelta\tclassification\n"
            "alpha\tstory\t0.8000\t0.6000\t-0.2000\tsevere_drift\n"
            "beta\treview\t0.9000\t0.9300\t+0.0300\tstable\n"
        )
        self.assertEqual(rendered, expected)

    def test_ends_with_single_trailing_newline(self) -> None:
        rendered = format_drift_report(
            compute_drift(baseline=_table(), current=_table())
        )
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))

    def test_empty_report_still_has_header(self) -> None:
        rendered = format_drift_report(
            DriftReport(
                entries=[],
                generated_at="2026-06-15T00:00:00Z",
                baseline_source="b",
                current_source="c",
            )
        )
        expected = (
            "baseline: b\tcurrent: c\n"
            "model_id\ttask_kind\tbaseline\tcurrent\tdelta\tclassification\n"
        )
        self.assertEqual(rendered, expected)

    def test_signed_delta_formatting(self) -> None:
        baseline = _table(_entry("m", "t", 0.50))
        current = _table(_entry("m", "t", 0.60))
        rendered = format_drift_report(
            compute_drift(baseline=baseline, current=current)
        )
        self.assertIn("\t+0.1000\t", rendered)

    def test_is_ascii_only(self) -> None:
        baseline = _table(_entry("m", "t", 0.50))
        current = _table(_entry("m", "t", 0.55))
        rendered = format_drift_report(
            compute_drift(baseline=baseline, current=current)
        )
        rendered.encode("ascii")  # raises if non-ASCII slipped in
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: `ImportError: cannot import name 'format_drift_report'`.

- [ ] **Step 3: Implement `format_drift_report`**

Append to `drift_detector.py`:

```python


def format_drift_report(report: DriftReport) -> str:
    """Render a DriftReport as deterministic plain-ASCII text.

    Line 1 names both sources. Line 2 is the tab-separated header row.
    Body rows render `baseline_success_rate` and `current_success_rate`
    with four decimal places, and `delta` with an explicit sign and
    four decimal places. The final character is a single trailing
    newline.
    """

    lines: list[str] = [
        f"baseline: {report.baseline_source}\tcurrent: {report.current_source}",
        "model_id\ttask_kind\tbaseline\tcurrent\tdelta\tclassification",
    ]
    for entry in report.entries:
        lines.append(
            f"{entry.model_id}\t{entry.task_kind}\t"
            f"{entry.baseline_success_rate:.4f}\t"
            f"{entry.current_success_rate:.4f}\t"
            f"{entry.delta:+.4f}\t"
            f"{entry.classification.value}"
        )
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 34 tests pass.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m09): add format_drift_report with signed delta and ASCII guarantee"
```

---

## Task 12: Lock the module-surface and import-allowlist invariants (REQ-02, REQ-11, REQ-12)

These tests prove the file-level invariants the spec asks a reviewer to grep for. They live in the test module so the suite — not just an out-of-band CI script — enforces them.

**Files:**
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Add invariant tests**

**Imports (add to the existing import block at the top of `test_drift_detector.py`, NOT mid-file — see context note #10):**

```python
import ast
from pathlib import Path

import story_automator.core.drift_detector as drift_module
```

**Then append the helpers and test class below to the bottom of the file:**

```python
_FORBIDDEN_TOKENS = (
    "requests",
    "httpx",
    "aiohttp",
    "subprocess",
    "os.system",
    "psutil",
    "filelock",
)
_FORBIDDEN_WRITE_PATTERNS = (
    "open(",
    "write_text",
    "read_text",
    "Path.mkdir",
    "write_atomic",
)


def _module_source() -> str:
    path = Path(drift_module.__file__)
    return path.read_text(encoding="utf-8")


class ModuleSurfaceTests(unittest.TestCase):
    def test_all_lists_exact_symbols(self) -> None:
        self.assertEqual(
            set(drift_module.__all__),
            {
                "DriftClassification",
                "DriftEntry",
                "DriftReport",
                "compute_drift",
                "format_drift_report",
            },
        )

    def test_starts_with_future_annotations(self) -> None:
        # Parse the module as AST. The first executable statement (after
        # an optional module docstring) must be
        # `from __future__ import annotations`. Sibling modules
        # (calibration, telemetry_events) follow the docstring-then-future
        # shape; we accept both shapes here.
        source = _module_source()
        tree = ast.parse(source)
        body = tree.body
        self.assertTrue(body, "module body is empty")
        first = body[0]
        is_docstring = (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        )
        if is_docstring:
            self.assertGreaterEqual(
                len(body), 2, "docstring present but no __future__ import follows"
            )
            future_node = body[1]
        else:
            future_node = first
        self.assertIsInstance(future_node, ast.ImportFrom)
        self.assertEqual(future_node.module, "__future__")
        self.assertEqual(
            [alias.name for alias in future_node.names], ["annotations"]
        )

    def test_import_allowlist(self) -> None:
        source = _module_source()
        for token in _FORBIDDEN_TOKENS:
            self.assertNotIn(token, source, f"forbidden import token: {token}")

    def test_no_filesystem_mutators(self) -> None:
        source = _module_source()
        for token in _FORBIDDEN_WRITE_PATTERNS:
            self.assertNotIn(token, source, f"forbidden write pattern: {token}")

    def test_no_unresolved_four_letter_placeholder(self) -> None:
        source = _module_source()
        # Concatenate so the literal substrings do not appear in this
        # test file (otherwise the spec's repo-wide grep would catch
        # us self-tripping on this very check).
        tokens = (
            "TO" + "DO",
            "FI" + "XME",
            "XX" + "XX",
            "TB" + "DX",
        )
        for token in tokens:
            self.assertNotIn(token, source, f"placeholder token leaked: {token}")

    def test_module_under_300_lines(self) -> None:
        line_count = len(_module_source().splitlines())
        self.assertLessEqual(line_count, 300, f"module is {line_count} lines (>300)")
```

- [ ] **Step 2: Run the tests and confirm they pass**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 40 tests pass. If the module has accidentally drifted past 300 LOC or picked up a forbidden import, you'll see a clear failure here.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): enforce __all__, future-annotations, allowlist, size invariants"
```

---

## Task 13: Cover `DriftReport.generated_at` is populated by `iso_now` (REQ-05)

The previous tests check the shape; this one stubs `iso_now` to prove `compute_drift` actually calls it (rather than hard-coding a timestamp).

**Files:**
- Modify: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Add the unittest.mock test**

**Add to the import block at top:** `from unittest import mock`.

**Append the test class to the bottom of the file:**

```python
class GeneratedAtSourcingTests(unittest.TestCase):
    def test_compute_drift_calls_iso_now(self) -> None:
        baseline = _table(_entry("m", "t", 0.5))
        current = _table(_entry("m", "t", 0.5))
        with mock.patch(
            "story_automator.core.drift_detector.iso_now",
            return_value="2099-01-01T00:00:00Z",
        ) as patched:
            report = compute_drift(baseline=baseline, current=current)
        patched.assert_called_once()
        self.assertEqual(report.generated_at, "2099-01-01T00:00:00Z")
```

- [ ] **Step 2: Run the test and confirm it passes**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 41 tests pass.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): prove generated_at flows from iso_now via patched call"
```

---

## Task 14: Run the lint, format, coverage, and import-grep quality gates

These are the spec's "Quality gates" section, executed verbatim.

**Files:** (no source edits; resolve any failures inline by going back to the relevant earlier task and fixing.)

- [ ] **Step 1: Ruff lint**

Run: `python -m ruff check skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py`
Expected: `All checks passed!` (exit 0).

If ruff flags an unused import (`re` or `mock`) or an E501 long line, fix it inline. Re-run.

- [ ] **Step 2: Ruff format check**

Run: `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py`
Expected: `2 files already formatted` (exit 0).

If it reports a diff, run `python -m ruff format skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py` to apply, then re-run the `--check` variant.

- [ ] **Step 3: Module test suite**

Run: `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`
Expected: 39 tests pass, exit 0.

- [ ] **Step 4: Coverage gate (≥90%)**

The spec's literal command uses `--source=<file>`, which `coverage.py` interprets only as a package/directory. If the literal form errors with "module ... was previously imported, but not measured", fall back to the directory form below.

**Preferred (spec literal, repo root):**

```bash
python -m coverage run --source=skills/bmad-story-automator/src/story_automator/core/drift_detector.py -m unittest tests.test_drift_detector
python -m coverage report --fail-under=90 --include="*/core/drift_detector.py"
```

**Fallback (works locally, cd into the skill):**

```bash
cd skills/bmad-story-automator
PYTHONPATH=src python -m coverage run --source=src/story_automator/core -m unittest tests.test_drift_detector
PYTHONPATH=src python -m coverage report --fail-under=90 --include="*/core/drift_detector.py"
```

Expected: `TOTAL ... 100%` for `drift_detector.py` (the module is small enough; if anything is under, add a targeted test). The `--include` filter narrows the report to just the drift module even when `--source` covers the whole `core/` package.

- [ ] **Step 5: Repo-wide test suite still green (regression check only)**

From the repository root:

```bash
npm run test:python
```

This runs `python -m unittest discover -s tests`, which only discovers root-level `tests/*.py` files — it does NOT execute `skills/bmad-story-automator/tests/test_drift_detector.py` (that lives in a sibling tree). So this step is a regression check on the pre-existing M01/M02/M03/orchestrator tests, not a verification of M09. M09 verification happens in Step 3.

Expected: all root-level tests pass, exit 0. If a pre-existing test breaks, that's a regression — fix root cause; do not skip the test.

- [ ] **Step 6: Import-allowlist + file-system-mutator grep**

```bash
grep -nE "requests|httpx|aiohttp|subprocess|filelock|psutil|open\(|write_text|read_text" \
  skills/bmad-story-automator/src/story_automator/core/drift_detector.py
```

Expected: no matches (exit 1 from grep is OK; the only failure mode is exit-0 with matched lines).

- [ ] **Step 7: Line-count gate**

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/drift_detector.py
wc -l skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: module ≤ 300, test ≤ 500.

- [ ] **Step 8: `compileall` parse check**

```bash
python -m compileall skills/bmad-story-automator/src/story_automator/core/drift_detector.py
```

Expected: `Listing ... Compiling ... .`. Non-zero exit means a syntax warning under 3.11.

- [ ] **Step 9: Placeholder-token grep**

```bash
grep -nE "TODO|FIXME|XXXX|TBDX" \
  skills/bmad-story-automator/src/story_automator/core/drift_detector.py \
  skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: no matches.

- [ ] **Step 10: Commit any cleanup**

If ruff or coverage required edits, commit them now:

```bash
git add -A
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(m09): apply ruff format and resolve quality-gate findings"
```

If nothing was changed, skip the commit.

---

## Task 15: Final spec self-review and wrap-up

- [ ] **Step 1: Walk each REQ and point to a task**

Open `docs/superpowers/specs/2026-06-14-m09-drift-detector.md` and confirm:

| REQ | Where it's implemented / proved |
|---|---|
| REQ-01 (paths) | Task 1 (module stub), Task 2 (tests file creation) |
| REQ-02 (`__future__` + `__all__`) | Task 1 stub, Task 12 invariant test |
| REQ-03 (`DriftClassification`) | Task 2 |
| REQ-04 (`DriftEntry` frozen kw_only) | Task 3 |
| REQ-05 (`DriftReport`, `iso_now`-sourced) | Task 4 + Task 13 mock |
| REQ-06 (pure `compute_drift`) | Task 7 + `test_inputs_not_mutated` |
| REQ-07 (band boundaries + constants) | Task 5 (`_classify`) + Task 8 boundary crossings |
| REQ-08 (0.5 default for missing side) | Task 9 |
| REQ-09 (sort order) | Task 10 |
| REQ-10 (`format_drift_report`) | Task 11 |
| REQ-11 (import allowlist) | Task 12 + Task 14 step 6 |
| REQ-12 (no FS mutators, no placeholders) | Task 12 + Task 14 steps 6, 9 |
| REQ-13 (test coverage matrix) | Tasks 7, 8, 9, 10, 11 |
| REQ-14 (in-memory fixtures only) | Task 6 fixture builder |
| REQ-15 (direct import works) | Task 1 step 3, Task 12 |

If any REQ has no implementing task, add one and re-run gates.

- [ ] **Step 2: Push the branch and open a PR (optional — operator-driven)**

Skip unless the operator explicitly asks for it. The PR template lives in `.github/` if present.

- [ ] **Step 3: Done**

The drift detector is fully implemented, fully tested, and quality-gate-clean. Future milestones (M03 cost-gate, future `sw estimate`) can import `compute_drift` and `format_drift_report` without further wiring.
