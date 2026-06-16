# M09 — Drift Detector Format & Quality Gates Implementation Plan (M2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Layer the plain-ASCII `format_drift_report` rendering and the full battery of surface-invariant / quality-gate tests onto the M1 drift-detector core, so M09 passes every spec quality gate (REQ-10, REQ-13 snapshot+ASCII coverage, Non-functional requirements, and the eight Quality gates) without changing the public semantics of `compute_drift`.

**Architecture:** Single source module `skills/bmad-story-automator/src/story_automator/core/drift_detector.py` (already created in M1) gains one new public function `format_drift_report` plus a private classification helper test surface. The test module `skills/bmad-story-automator/tests/test_drift_detector.py` (already created in M1) gains new TestCase classes covering the formatter snapshot, ASCII-only invariant, signed-delta formatting, trailing-newline guarantee, module surface (`__all__`, `__future__` import, import allowlist, fs-mutator allowlist, four-letter placeholder ban, ≤300 LOC), cross-module consistency with `lookup_success_rate`'s default, and a `mock.patch` test proving `generated_at` flows from `iso_now()`. All eight Quality gates are then executed and pinned via the test suite.

**Tech Stack:** Python 3.11+, stdlib only (`enum`, `dataclasses`, `__future__`, `ast`, `pathlib`, `unittest.mock`), `unittest.TestCase` for tests, `ruff` for lint+format, stdlib `coverage` for the 90% threshold gate, `compileall` for parse validation.

---

## Context for the Engineer

You are extending the M1 drift-detector core. Read these before touching code:

1. **M1 already shipped.** `compute_drift`, `DriftClassification`, `DriftEntry`, `DriftReport`, `_classify`, and the boundary constants `STABLE_MAX` / `MINOR_MAX` / `MAJOR_MAX` are already in `core/drift_detector.py`. Do NOT redefine them. M2 only adds `format_drift_report` and the surface-invariant test classes.
2. **`__all__` must change.** Per REQ-02, `__all__` must list exactly `["DriftClassification", "DriftEntry", "DriftReport", "compute_drift", "format_drift_report"]`. When you add `format_drift_report`, also extend `__all__`.
3. **Plain-ASCII guarantee (REQ-10).** The formatter renders a tab-separated table. Line 1 names both source paths in the form `baseline: <path>\tcurrent: <path>`. Line 2 is the literal header `model_id\ttask_kind\tbaseline\tcurrent\tdelta\tclassification`. Body rows render `baseline_success_rate` and `current_success_rate` with `:.4f`, `delta` with `:+.4f` (mandatory sign), and `classification` as `entry.classification.value` (already a lowercase string). The output ends with exactly one `"\n"`.
4. **No new imports for the formatter.** It needs nothing beyond what M1 already imports. Do not add `os`, `string`, or anything else.
5. **Snapshot fixtures live inline in the test file.** Build `CalibrationEntry` and `CalibrationTable` instances directly per REQ-14; do not call `build_calibration`, do not touch tmp dirs, do not write JSONL.
6. **No `Optional` / `Union`** — PEP 604 syntax only (`float | None`, `list[DriftEntry]`).
7. **First non-comment line** in both files: `from __future__ import annotations`. A module docstring before it is allowed; the `__future__` import must be the next statement.
8. **LF only.** The snapshot test must compare against literal `"\n"`-joined strings. Never `os.linesep`.
9. **Placeholder-token discipline.** Source files must not contain the literal substrings `TODO`, `FIXME`, `XXXX`, or `TBDX` (including inside docstrings). Describe formats as prose ("four decimal places, signed"), never `+0.XXXX` glyphs — the placeholder grep would catch the latter.
10. **Imports at the top of the test file.** Insert into the existing import block; ruff `E402` will flag mid-file imports. The new test classes are appended to the bottom of the file.
11. **Local test command** (matches the M08/M01 pattern): `cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v`. The spec writes the CI form as `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_drift_detector` from the repo root.
12. **Anti-scope:** No CLI surface, no persistence, no exit codes, no alarms, no threshold tuning. Do not modify `core/calibration.py` or `core/telemetry_events.py`. Do not add a third-party dependency.
13. **TDD discipline.** Each feature step in this plan follows red → minimal-green → commit. The quality gates at the end are pure verification; they do not require new code unless a gate exposes a regression.

---

## File Structure

- **Modify:** `skills/bmad-story-automator/src/story_automator/core/drift_detector.py` — add `format_drift_report`, extend `__all__`. Target ≤300 LOC (spec ceiling); expected final size ~170 LOC.
- **Modify:** `skills/bmad-story-automator/tests/test_drift_detector.py` — add `FormatDriftReportTests`, `ModuleSurfaceTests`, `CrossModuleConsistencyTests`, `GeneratedAtSourcingTests` classes plus formatter snapshot fixtures. Target ≤500 LOC; expected final size ~490 LOC.

No other files are touched by this milestone.

---

## Task 1: Verify M1 baseline is green before adding anything

**Files:**
- Inspect only.

- [ ] **Step 1: Confirm M1 source and tests exist and are green**

Run from the repo root:

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector -v
```

Expected: all M1 tests pass. If any fail, stop and surface the regression — do not start M2 on a red baseline.

- [ ] **Step 2: Confirm ruff is clean on the M1 surface**

Run:

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: both exit zero.

- [ ] **Step 3: Confirm `__all__` currently lists the four M1 symbols only**

Read `skills/bmad-story-automator/src/story_automator/core/drift_detector.py` and confirm `__all__` is `["DriftClassification", "DriftEntry", "DriftReport", "compute_drift"]`. If `format_drift_report` is already present, skip the formatter feature tasks (2–6).

- [ ] **Step 4: Per-task idempotency rule for the surface-invariant tasks**

For every task from Task 2 onward, before writing the test, search `tests/test_drift_detector.py` for the test method name (e.g., `test_snapshot_for_known_fixture`, `test_all_lists_exact_symbols`, `test_starts_with_future_annotations`, …). If the method already exists, skip the "add test" step but still run the test in isolation to confirm it currently passes. Skip the per-task commit. This makes the plan idempotent against a partially-implemented M2: re-running it on a clean tree of an already-shipped M2 produces zero new commits and zero regressions. Document any skipped tasks in the final commit message of the milestone (or omit if no work was done).

No commit at this task — verification only.

---

## Task 2: TDD `format_drift_report` — snapshot test for a known fixture (REQ-10, REQ-13)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Add a failing snapshot test**

At the bottom of `tests/test_drift_detector.py` (and update the imports block at the top to import `format_drift_report` from `story_automator.core.drift_detector` alongside the existing symbols), append:

```python
class FormatDriftReportTests(unittest.TestCase):
    def test_snapshot_for_known_fixture(self) -> None:
        baseline = _table(
            _entry("alpha", "story", 0.80),
            _entry("beta", "review", 0.90),
            source_path="/fixtures/base.jsonl",
        )
        current = _table(
            _entry("alpha", "story", 0.60),  # delta = -0.20 -> severe
            _entry("beta", "review", 0.93),  # delta = +0.03 -> stable
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
```

(The `_entry` and `_table` helpers were defined in M1 — re-use them; do not redefine.)

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.FormatDriftReportTests.test_snapshot_for_known_fixture -v
```

Expected: `ImportError: cannot import name 'format_drift_report'` (or `AttributeError`).

- [ ] **Step 3: Implement minimal `format_drift_report`**

In `skills/bmad-story-automator/src/story_automator/core/drift_detector.py`, extend `__all__` to include `"format_drift_report"` and append at the end of the file:

```python
def format_drift_report(report: DriftReport) -> str:
    """Render a DriftReport as deterministic plain-ASCII text.

    Line 1 names both sources. Line 2 is the tab-separated header row.
    Body rows render `baseline_success_rate` and `current_success_rate`
    with four decimal places, and `delta` with an explicit sign and
    four decimal places. The final character is a single trailing
    newline.

    Precondition: `model_id`, `task_kind`, `baseline_source`, and
    `current_source` must be ASCII strings free of literal tabs and
    newlines. Telemetry-emitted model identifiers from M02 already
    satisfy this; non-ASCII inputs would silently break the spec
    REQ-10 plain-ASCII guarantee and could corrupt TSV column
    alignment.
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

- [ ] **Step 4: Run the test and confirm it passes**

Run:

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.FormatDriftReportTests.test_snapshot_for_known_fixture -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m09): add format_drift_report with signed delta and ASCII guarantee"
```

---

## Task 3: Add the trailing-newline invariant test (REQ-10)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append the test to `FormatDriftReportTests`**

```python
    def test_ends_with_single_trailing_newline(self) -> None:
        rendered = format_drift_report(
            compute_drift(baseline=_table(), current=_table())
        )
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))
```

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.FormatDriftReportTests.test_ends_with_single_trailing_newline -v
```

Expected: PASS (already true by construction in Task 2).

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): pin single trailing newline on format_drift_report output"
```

---

## Task 4: Add the empty-report header test (REQ-10 edge case)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append the test**

```python
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
```

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.FormatDriftReportTests.test_empty_report_still_has_header -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): empty DriftReport renders source line + header only"
```

---

## Task 5: Add the signed-delta formatting test (REQ-10)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append the test**

```python
    def test_signed_delta_formatting(self) -> None:
        baseline = _table(_entry("m", "t", 0.50))
        current = _table(_entry("m", "t", 0.60))
        rendered = format_drift_report(
            compute_drift(baseline=baseline, current=current)
        )
        self.assertIn("\t+0.1000\t", rendered)
```

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.FormatDriftReportTests.test_signed_delta_formatting -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): pin signed delta '+0.XXXX' rendering"
```

---

## Task 6: Add the ASCII-only invariant test (REQ-10, NFR plain-ASCII)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append the test**

```python
    def test_is_ascii_only(self) -> None:
        baseline = _table(_entry("m", "t", 0.50))
        current = _table(_entry("m", "t", 0.55))
        rendered = format_drift_report(
            compute_drift(baseline=baseline, current=current)
        )
        rendered.encode("ascii")  # raises if non-ASCII slipped in
```

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.FormatDriftReportTests.test_is_ascii_only -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): pin plain-ASCII guarantee on format_drift_report"
```

---

## Task 7: Add `__all__` exact-symbol test (REQ-02)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Add module import alias and the forbidden-token constants**

At the top of `tests/test_drift_detector.py`, ensure these imports are present in the import block (add the missing ones):

```python
import ast
from pathlib import Path
from unittest import mock

import story_automator.core.drift_detector as drift_module
```

Append the forbidden-token constants at module scope (just above the new TestCase class added in this task — they live at module scope, not inside a class):

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
```

- [ ] **Step 2: Append `ModuleSurfaceTests` with the `__all__` test**

```python
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
```

- [ ] **Step 3: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.ModuleSurfaceTests.test_all_lists_exact_symbols -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): pin __all__ to exactly the five public symbols"
```

---

## Task 8: Pin `from __future__ import annotations` as first non-docstring statement (REQ-02, NFR)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append to `ModuleSurfaceTests`**

```python
    def test_starts_with_future_annotations(self) -> None:
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
        self.assertEqual([alias.name for alias in future_node.names], ["annotations"])
```

- [ ] **Step 2: Append a parallel test pinning `__future__` on the test module itself**

The NFR demands `from __future__ import annotations` as the first non-comment statement in **both** new files. Append:

```python
    def test_test_module_starts_with_future_annotations(self) -> None:
        test_path = Path(__file__)
        source = test_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        body = tree.body
        self.assertTrue(body, "test module body is empty")
        first = body[0]
        is_docstring = (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        )
        future_node = body[1] if is_docstring else first
        self.assertIsInstance(future_node, ast.ImportFrom)
        self.assertEqual(future_node.module, "__future__")
        self.assertEqual([alias.name for alias in future_node.names], ["annotations"])
```

- [ ] **Step 3: Run both `__future__` tests and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.ModuleSurfaceTests.test_starts_with_future_annotations tests.test_drift_detector.ModuleSurfaceTests.test_test_module_starts_with_future_annotations -v
```

Expected: PASS on both.

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): pin __future__ annotations as first statement in both new files"
```

---

## Task 9: Add the import-allowlist grep test (REQ-11)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append to `ModuleSurfaceTests`**

```python
    def test_import_allowlist(self) -> None:
        source = _module_source()
        for token in _FORBIDDEN_TOKENS:
            self.assertNotIn(token, source, f"forbidden import token: {token}")
```

Note on the substring-grep false-positive risk: `_FORBIDDEN_TOKENS` is matched as a plain substring. Any future docstring or comment that mentions one of these words (e.g., a docstring sentence like "no subprocess invocation") will trip the assertion. Keep prose neutral — use phrases like "no shell-outs" or "no networking call" rather than naming the forbidden library. If a legitimate use ever arises that requires the word (vanishingly unlikely on this purely-functional module), upgrade the check to an AST-import walk that inspects only `ast.Import` / `ast.ImportFrom` nodes.

- [ ] **Step 2: Append a parallel PEP 604 check banning `typing.Optional` / `typing.Union` in the source module**

The NFR requires PEP 604 union syntax exclusively. Append (the constants `_FORBIDDEN_TYPING_TOKENS` are added at module scope alongside `_FORBIDDEN_TOKENS`):

```python
# At module scope, alongside _FORBIDDEN_TOKENS / _FORBIDDEN_WRITE_PATTERNS:
_FORBIDDEN_TYPING_TOKENS = (
    "typing.Optional",
    "typing.Union",
    "from typing import Optional",
    "from typing import Union",
    "Optional[",
    "Union[",
)

# Inside ModuleSurfaceTests:
    def test_no_typing_optional_or_union(self) -> None:
        source = _module_source()
        for token in _FORBIDDEN_TYPING_TOKENS:
            self.assertNotIn(token, source, f"NFR forbids PEP 484 union form: {token}")
```

- [ ] **Step 3: Run both checks and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.ModuleSurfaceTests.test_import_allowlist tests.test_drift_detector.ModuleSurfaceTests.test_no_typing_optional_or_union -v
```

Expected: PASS on both. If the PEP 604 check fails because `Optional[...]` or `Union[...]` snuck into the source module, rewrite as `X | None` / `X | Y` — REQ-NFR blocks the older form.

- [ ] **Step 4: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): enforce import allowlist and PEP 604 unions in source"
```

---

## Task 10: Add the no-fs-mutators grep test (REQ-12)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append to `ModuleSurfaceTests`**

```python
    def test_no_filesystem_mutators(self) -> None:
        source = _module_source()
        for token in _FORBIDDEN_WRITE_PATTERNS:
            self.assertNotIn(token, source, f"forbidden write pattern: {token}")
```

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.ModuleSurfaceTests.test_no_filesystem_mutators -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): enforce REQ-12 no filesystem mutators via source grep"
```

---

## Task 11: Add the placeholder-token ban test (REQ-12 tail, quality gate)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append to `ModuleSurfaceTests`**

Use string concatenation to split forbidden tokens at write time, so the test source itself does not self-trip the grep:

```python
    def test_no_unresolved_four_letter_placeholder(self) -> None:
        source = _module_source()
        tokens = (
            "TO" + "DO",
            "FI" + "XME",
            "XX" + "XX",
            "TB" + "DX",
        )
        for token in tokens:
            self.assertNotIn(token, source, f"placeholder token leaked: {token}")
```

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.ModuleSurfaceTests.test_no_unresolved_four_letter_placeholder -v
```

Expected: PASS. If it fails, remove the offending placeholder from the source — describe the format as prose.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): ban unresolved four-letter placeholders in source"
```

---

## Task 12: Add the ≤300-line module-size test (NFR, quality gate)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append to `ModuleSurfaceTests`**

```python
    def test_module_under_300_lines(self) -> None:
        line_count = len(_module_source().splitlines())
        self.assertLessEqual(line_count, 300, f"module is {line_count} lines (>300)")
```

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.ModuleSurfaceTests.test_module_under_300_lines -v
```

Expected: PASS (expected size after M2 is ~170 LOC).

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): pin module size at or below 300 lines"
```

---

## Task 13: Cross-module consistency test — REQ-08 default tracks `lookup_success_rate`

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append a new TestCase class**

```python
class CrossModuleConsistencyTests(unittest.TestCase):
    def test_missing_rate_default_matches_lookup_success_rate(self) -> None:
        from story_automator.core.calibration import lookup_success_rate

        self.assertEqual(lookup_success_rate.__defaults__, (0.5,))
        self.assertEqual(drift_module._MISSING_RATE_DEFAULT, 0.5)
```

(`_MISSING_RATE_DEFAULT` was introduced in M1 to capture the 0.5 fallback per REQ-08. If a reviewer renames it, this test fails and forces the rename to be intentional — that's the point.)

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.CrossModuleConsistencyTests -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): pin _MISSING_RATE_DEFAULT to lookup_success_rate default"
```

---

## Task 14: Generated-at sourcing test — prove `generated_at` flows from `iso_now()` (REQ-05)

**Files:**
- Test: `skills/bmad-story-automator/tests/test_drift_detector.py`

- [ ] **Step 1: Append a new TestCase class**

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

- [ ] **Step 2: Run and confirm PASS**

```bash
cd skills/bmad-story-automator && PYTHONPATH=src python -m unittest tests.test_drift_detector.GeneratedAtSourcingTests -v
```

Expected: PASS. If `iso_now` is referenced via fully-qualified import (`from story_automator.core import common; common.iso_now()`) instead of `from .common import iso_now; iso_now()`, the patch target changes and the test fails — the test deliberately pins the import shape too.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_drift_detector.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m09): prove generated_at flows from iso_now via patched call"
```

---

## Task 15: Run the full Quality Gates suite

**Files:**
- No code changes (verification only).

- [ ] **Step 1: Quality gate 1 — `ruff check` on both files**

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: exit 0, no warnings.

- [ ] **Step 2: Quality gate 2 — `ruff format --check` on both files**

```bash
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: exit 0. If it reports re-formatting needed, run `python -m ruff format <paths>`, re-run the check, and commit the format fixup as `style(m09): apply ruff format`.

- [ ] **Step 3: Quality gate 3 — full unittest module green**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_drift_detector -v
```

Expected: exit 0; OK with N tests (count grows by ~12 over the M1 baseline).

- [ ] **Step 4: Quality gate 4 — coverage ≥90% on `drift_detector.py`**

```bash
python -m coverage run --source=skills/bmad-story-automator/src/story_automator/core/drift_detector.py -m unittest tests.test_drift_detector
python -m coverage report --fail-under=90 --include="*/core/drift_detector.py"
```

Both commands must exit 0. If `--fail-under=90` fails, add a targeted test for whichever uncovered line the report names — do not lower the threshold.

- [ ] **Step 5: Quality gate 5 — import allowlist grep**

```bash
grep -E "(^|[^A-Za-z_])(requests|httpx|aiohttp|subprocess|filelock|psutil|os\.system|open\(|write_text|read_text)([^A-Za-z_]|$)" skills/bmad-story-automator/src/story_automator/core/drift_detector.py
```

Expected: no matches (grep exit code 1). If grep exits 0 (a match found), revert the offending import — REQ-11/REQ-12 forbid it.

- [ ] **Step 6: Quality gate 6 — `wc -l` ceilings**

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/drift_detector.py
wc -l skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: source ≤ 300, tests ≤ 500.

- [ ] **Step 7: Quality gate 7 — repository-wide placeholder grep on the two files**

```bash
grep -nE "(TODO|FIXME|XXXX|TBDX)" skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: matches **only** the lines inside `test_no_unresolved_four_letter_placeholder` that build forbidden tokens via string concatenation (`"TO" + "DO"` etc.) — those are the test source, not the placeholder itself. The plain glyphs `TODO`, `FIXME`, `XXXX`, `TBDX` must not appear anywhere outside that one test.

- [ ] **Step 8: Quality gate 8 — `compileall` succeeds under Python 3.11**

```bash
python -m compileall skills/bmad-story-automator/src/story_automator/core/drift_detector.py
```

Expected: exit 0 and prints `Compiling 'skills/.../drift_detector.py'...`.

- [ ] **Step 9: Commit (only if any quality gate forced a fixup commit above; otherwise no-op)**

If steps 1–8 all passed clean, no commit is needed here. If a fixup was applied, ensure it landed as a separate commit during the relevant step.

---

## Task 16: Final cross-platform sanity check (NFR LF-only, no platform deps)

**Files:**
- No code changes (verification only).

- [ ] **Step 1: Confirm LF line endings on both files**

```bash
file skills/bmad-story-automator/src/story_automator/core/drift_detector.py
file skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: each output contains `ASCII text` (no `CRLF line terminators`). If `file` reports CRLF, run `git add --renormalize` after confirming `.gitattributes` is correct, then commit as `chore(m09): normalize line endings to LF`.

- [ ] **Step 2: Confirm the test file has no `os.linesep`, no `Optional`, no `Union`, no `tmp`-dir fixtures**

```bash
grep -nE "(os\.linesep|typing\.Optional|typing\.Union|from typing import Optional|from typing import Union|Optional\[|Union\[|tempfile|TemporaryDirectory|tmp_path|tmpdir)" skills/bmad-story-automator/tests/test_drift_detector.py
```

Expected: no matches. If any match appears, fix it (PEP 604 union, no temp dirs per REQ-14) and commit as `refactor(m09): drop platform-coupled or REQ-14-violating patterns`.

- [ ] **Step 3: Confirm full unittest suite still green at the repository level**

```bash
npm run test:python
```

Expected: exit 0 with the existing M01–M08 suite plus the new M09 tests.

- [ ] **Step 4: No commit at this task unless a sanity check forced a fixup; otherwise the milestone is done.**

---

## Self-Review (run before declaring complete)

- **Spec coverage:**
  - REQ-10 (`format_drift_report`) — Tasks 2–6.
  - REQ-13 (snapshot + ASCII coverage; the boundary/missing-key/sort tests were already pinned in M1) — Task 2 (snapshot), Task 6 (ASCII).
  - REQ-02 (`__all__` listing) — Task 7.
  - REQ-11 (import allowlist) — Tasks 9 (step 1) and 15-step-5; PEP 604 union ban — Task 9 (step 2) plus Task 16 step 2.
  - REQ-12 (no fs mutators + no four-letter placeholder) — Tasks 10, 11, and 15-step-7.
  - Non-functional (≤300 / ≤500 LOC, plain-ASCII, LF, future-annotations on **both** files) — Tasks 8 (steps 1+2), 12, 6, 16.
  - Quality gates 1–8 (ruff check, ruff format, unittest, coverage, allowlist grep, wc -l, placeholder grep, compileall) — Task 15.
  - REQ-05 `generated_at` from `iso_now` — Task 14.
  - REQ-08 default of 0.5 tracks `lookup_success_rate` — Task 13.

- **Placeholder scan:** the only literal four-letter forbidden tokens appearing in this plan are inside fenced `bash` code blocks for the placeholder-grep gate; they are not source code. No `TODO`/`FIXME` in the source or test specifications.

- **Type consistency:** `format_drift_report(report: DriftReport) -> str` is consistent across Task 2 (signature), Task 7 (`__all__`), and the test surface. `_MISSING_RATE_DEFAULT` is referenced consistently between Tasks 13 and the M1 implementation.
