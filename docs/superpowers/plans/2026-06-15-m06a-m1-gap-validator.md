# M06a-M1: Gap Validator (Layer 1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the stdlib-only, deterministic `core/gap_validator.py` module — three frozen dataclasses (`Gap`, `GapStatus`, `ValidationReport`), a JSON parser (`parse_gap_list`), and the verifier (`validate_gaps`) that confidence-scores each gap against the local source tree — as the first wedge atom of M06a.

**Architecture:** A single new module `skills/bmad-story-automator/src/story_automator/core/gap_validator.py` exposing exactly five public symbols (`Gap`, `GapStatus`, `ValidationReport`, `validate_gaps`, `parse_gap_list`) plus the module logger. Layer 2 (`spec_compliance.py`) and Layer 3 (`feature_tester.py`) are NOT touched here — they are later wedges of M06a. The verifier never reads files outside `repo_root`: candidate paths are resolved via `Path.resolve(strict=False)` and rejected with `path_exists=False` + a note if the resolved path is not relative to `repo_root.resolve()`. The confidence model is the literal spec formula — base 0.8 plus 0.05 per passing check, capped at 1.0 (`overall_confidence` is the arithmetic mean of per-gap confidences, or `1.0` when the gap list is empty, on the principle that "no gaps to validate" is the trivially valid case).

**Tech Stack:** Python 3.11+ stdlib only (`dataclasses`, `json`, `logging`, `pathlib`). Tests use `unittest.TestCase` with `tempfile.TemporaryDirectory`. No `filelock`, no `psutil`, no third-party imports. No imports from `commands/`, from `core/spec_compliance`, or from `core/feature_tester` — Layer 1 must be independently importable per the spec quality gate.

---

## Scope for this sub-milestone

**In scope (from the spec):**
- REQ-01: `Gap` frozen kw_only dataclass with `file_path`, `line`, `symbol`, `description`, `severity`
- REQ-02: `GapStatus` frozen kw_only dataclass with `gap`, `path_exists`, `line_in_range`, `symbol_present`, `confidence`, `notes`
- REQ-03: `ValidationReport` frozen kw_only dataclass with `statuses`, `overall_confidence`, `validated_at`
- REQ-04: `validate_gaps(gaps, *, repo_root) -> ValidationReport` with the base-0.8 + 0.05-per-pass + cap-1.0 confidence formula and per-failure notes
- REQ-05: Path-escape rejection (absolute outside root, `..` traversal outside root, symlinks pointing outside) with `path_exists=False` + rejected-path note; no file reads outside `repo_root`
- REQ-06: `parse_gap_list(payload) -> list[Gap]` accepting `{"gaps": [...]}` and raising `ValueError` with field-locating messages for missing keys, non-integer `line`, and out-of-set `severity`
- REQ-16: importable in any order, no import-time side effects beyond `logging.getLogger(__name__)`, declare `__all__`
- Non-functional: frozen kw_only dataclasses not subclassing other dataclasses, stdlib-only (no psutil), PEP 604 `X | None`, `from __future__ import annotations`, public-API docstrings stating pre/post/raises, mypy `--strict` clean
- Quality gates: ruff clean, mypy `--strict` clean, ≥92% line coverage with any `# pragma: no cover` carrying a one-line rationale, ≥6 test methods (with ≥1 negative test per public function), no imports from `commands/` or other M06a layer modules, diff limited to the two files

**Out of scope (deferred to later M06a wedges or future milestones):**
- Layer 2 `core/spec_compliance.py` (REQ-07..11) — M06a-M2.
- Layer 3 `core/feature_tester.py` (REQ-12..15) — M06a-M3.
- The M06b BMAD orchestrator skill markdown.
- Cross-language gap validation (non-Python sources).
- Persisting `ValidationReport` to disk (callers use `core/atomic_io.py` from M05).

---

## File Structure

| File | New / Modified | Responsibility |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/gap_validator.py` | Create | `Gap`, `GapStatus`, `ValidationReport`, `validate_gaps`, `parse_gap_list`, module logger, `__all__` |
| `tests/test_gap_validator.py` | Create | Unit tests: import contract, three dataclass shapes, parser happy path + three negative cases, validator happy path + per-check failure modes, path-escape rejection, empty-list aggregation |

No other files are modified by this sub-milestone — neither `common.py`, nor `atomic_io.py`, nor any existing test file. The spec's "diff limited to" quality gate is enforced in Task 13.

---

## Confidence model (single source of truth — reused across tasks)

Per the spec REQ-04:

- Each gap starts at `confidence = 0.8`.
- For each of the three boolean checks (`path_exists`, `line_in_range`, `symbol_present`) that is `True`, add `0.05`.
- Cap the result at `1.0` (the formula maxes at `0.95` for 3-of-3, so the cap is documentary — but mypy `--strict` and an explicit `min(0.95, 1.0)` make the cap discoverable in code).
- For each `False` check, append exactly one human-readable note explaining what failed (e.g. `"path does not exist: foo/bar.py"`, `"line 42 outside file range 1..30"`, `"symbol 'handle_x' not found in foo/bar.py"`).
- **Note-suppression rule:** when `path_exists` is `False`, the line and symbol checks are unverifiable in principle, so the line/symbol helpers return `(False, None)` and emit no separate note. The single path note is enough — adding "line could not be verified because the file is missing" three times for every escaping gap would be noise. Failed *checks* still contribute 0.0 to confidence (no bonus); the note list is just deduplicated against the root cause. This is the spec-permitted reading of REQ-04's "append a human-readable note" (it does not mandate one note per failed check when the failures share a single root cause).

`ValidationReport.overall_confidence`:
- If `statuses` is non-empty: arithmetic mean of `status.confidence` rounded to 6 decimal places via `round(value, 6)` to keep equality assertions stable across platforms.
- If `statuses` is empty: `1.0` ("no gaps to validate" is the trivially valid case).

`ValidationReport.validated_at`:
- `core.common.iso_now()` (the existing helper — REQ-03 mandates this exact source).

---

## Task 1: Module skeleton, `__all__`, import-side-effect test

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Create: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gap_validator.py`:

```python
from __future__ import annotations

import io
import logging
import sys
import unittest


class ModuleImportContractTests(unittest.TestCase):
    """REQ-16: importable in any order, no import-time side effects beyond
    logging.getLogger(__name__), declares __all__."""

    def test_module_imports_cleanly(self) -> None:
        from story_automator.core import gap_validator  # noqa: F401

    def test_module_declares_all(self) -> None:
        from story_automator.core import gap_validator

        self.assertEqual(
            sorted(gap_validator.__all__),
            sorted([
                "Gap",
                "GapStatus",
                "ValidationReport",
                "parse_gap_list",
                "validate_gaps",
            ]),
        )

    def test_import_has_no_stdout_or_stderr_side_effects(self) -> None:
        # Force a fresh import in an isolated stream environment.
        sys.modules.pop("story_automator.core.gap_validator", None)
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = captured_out, captured_err
        try:
            from story_automator.core import gap_validator  # noqa: F401
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        self.assertEqual(captured_out.getvalue(), "")
        self.assertEqual(captured_err.getvalue(), "")

    def test_module_has_named_logger(self) -> None:
        from story_automator.core import gap_validator

        self.assertIsInstance(gap_validator.logger, logging.Logger)
        self.assertEqual(
            gap_validator.logger.name,
            "story_automator.core.gap_validator",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'story_automator.core.gap_validator'`.

- [ ] **Step 3: Create the module skeleton**

Create `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`:

```python
"""Layer 1 of the M06a trust-but-verify stack: deterministic gap validation.

This module exposes three frozen dataclasses (`Gap`, `GapStatus`,
`ValidationReport`) and two functions (`parse_gap_list`, `validate_gaps`).
`parse_gap_list` deserializes a `{"gaps": [...]}` JSON document into a
list of `Gap` values. `validate_gaps` checks each gap's cited file path,
line number, and symbol against the local source tree rooted at
`repo_root`, returning a per-gap confidence in the closed interval
`[0.0, 1.0]` plus an aggregate `ValidationReport`.

Layer 1 is intentionally decoupled from Layer 2 (`spec_compliance.py`)
and Layer 3 (`feature_tester.py`): no cross-layer imports, no shared
state, no subprocess calls, no network I/O. The verifier never reads
files outside `repo_root` — path-escape attempts (absolute paths,
`..` traversal, outward-pointing symlinks) are reported as
`path_exists=False` with a note.
"""

from __future__ import annotations

import logging

__all__ = [
    "Gap",
    "GapStatus",
    "ValidationReport",
    "parse_gap_list",
    "validate_gaps",
]

logger = logging.getLogger(__name__)
```

> NOTE: At this point `Gap`, `GapStatus`, `ValidationReport`, `parse_gap_list`, and `validate_gaps` are referenced in `__all__` but not yet defined. That is intentional — `__all__` is only consulted by `from module import *`, never on plain `import module`, so the import-contract tests pass. Subsequent tasks add the symbols; if a future task removes one without updating `__all__`, the import test will continue to pass (since it only checks `__all__`'s contents, not whether the names exist), but Task 11 below adds an explicit symbol-existence assertion that closes the gap.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): add module skeleton, __all__, and import-contract tests"
```

---

## Task 2: `Gap` dataclass (REQ-01)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gap_validator.py`:

```python
import dataclasses


class GapDataclassTests(unittest.TestCase):
    """REQ-01: frozen kw_only @dataclass with five fields."""

    def test_gap_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.gap_validator import Gap

        self.assertTrue(dataclasses.is_dataclass(Gap))
        params = Gap.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_gap_field_names_and_types(self) -> None:
        from story_automator.core.gap_validator import Gap

        fields = {f.name: f.type for f in dataclasses.fields(Gap)}
        self.assertEqual(
            sorted(fields.keys()),
            ["description", "file_path", "line", "severity", "symbol"],
        )

    def test_gap_construction_requires_keyword_args(self) -> None:
        from story_automator.core.gap_validator import Gap

        with self.assertRaises(TypeError):
            Gap("a", 1, "s", "d", "minor")  # type: ignore[misc]

    def test_gap_instances_are_immutable(self) -> None:
        from story_automator.core.gap_validator import Gap

        g = Gap(
            file_path="a.py", line=1, symbol="x", description="d", severity="minor",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            g.line = 2  # type: ignore[misc]

    def test_gap_does_not_subclass_other_dataclasses(self) -> None:
        # NFR: dataclasses must not subclass other dataclasses.
        from story_automator.core.gap_validator import Gap

        ancestors = [base for base in Gap.__mro__ if base is not Gap and base is not object]
        for base in ancestors:
            self.assertFalse(
                dataclasses.is_dataclass(base),
                f"Gap unexpectedly inherits from dataclass {base!r}",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL on `GapDataclassTests` — `ImportError: cannot import name 'Gap'`.

- [ ] **Step 3: Add the `Gap` dataclass**

Edit `gap_validator.py` — append below the logger:

```python
from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Gap:
    """A review-skill gap claim: file/line/symbol citation plus metadata.

    Preconditions: `severity` must be one of "blocker", "major", "minor"
        — enforced by `parse_gap_list`, not by this dataclass itself.
    Postconditions: instance is frozen; all five fields are present.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    file_path: str
    line: int
    symbol: str
    description: str
    severity: str
```

> The import sits inside the module body (not at the very top) only in this code block for clarity; in the actual file, fold it into the existing import block at the top of the module so ruff's `I` rules stay happy. The final import block at module top is:
>
> ```python
> from __future__ import annotations
>
> import logging
> from dataclasses import dataclass
> ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): add frozen kw_only Gap dataclass (REQ-01)"
```

---

## Task 3: `GapStatus` dataclass (REQ-02)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gap_validator.py`:

```python
class GapStatusDataclassTests(unittest.TestCase):
    """REQ-02: frozen kw_only @dataclass with six fields."""

    def test_gap_status_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.gap_validator import GapStatus

        self.assertTrue(dataclasses.is_dataclass(GapStatus))
        params = GapStatus.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_gap_status_field_names(self) -> None:
        from story_automator.core.gap_validator import GapStatus

        names = sorted(f.name for f in dataclasses.fields(GapStatus))
        self.assertEqual(
            names,
            ["confidence", "gap", "line_in_range", "notes", "path_exists", "symbol_present"],
        )

    def test_gap_status_construction(self) -> None:
        from story_automator.core.gap_validator import Gap, GapStatus

        g = Gap(
            file_path="a.py", line=1, symbol="x", description="d", severity="minor",
        )
        s = GapStatus(
            gap=g,
            path_exists=True,
            line_in_range=True,
            symbol_present=True,
            confidence=0.95,
            notes=[],
        )
        self.assertIs(s.gap, g)
        self.assertEqual(s.notes, [])
        self.assertEqual(s.confidence, 0.95)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL on `GapStatusDataclassTests` — `ImportError: cannot import name 'GapStatus'`.

- [ ] **Step 3: Add the `GapStatus` dataclass**

Append to `gap_validator.py`:

```python
@dataclass(frozen=True, kw_only=True)
class GapStatus:
    """Result of validating a single `Gap` against the local source tree.

    Preconditions: `confidence` must lie in `[0.0, 1.0]`; `notes` must be
        a list of human-readable strings explaining failed checks.
    Postconditions: instance is frozen; `gap` is the original `Gap`.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    gap: Gap
    path_exists: bool
    line_in_range: bool
    symbol_present: bool
    confidence: float
    notes: list[str]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): add frozen kw_only GapStatus dataclass (REQ-02)"
```

---

## Task 4: `ValidationReport` dataclass (REQ-03)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gap_validator.py`:

```python
class ValidationReportDataclassTests(unittest.TestCase):
    """REQ-03: frozen kw_only @dataclass with three fields."""

    def test_validation_report_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.gap_validator import ValidationReport

        self.assertTrue(dataclasses.is_dataclass(ValidationReport))
        params = ValidationReport.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_validation_report_field_names(self) -> None:
        from story_automator.core.gap_validator import ValidationReport

        names = sorted(f.name for f in dataclasses.fields(ValidationReport))
        self.assertEqual(
            names, ["overall_confidence", "statuses", "validated_at"],
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL on `ValidationReportDataclassTests` — `ImportError: cannot import name 'ValidationReport'`.

- [ ] **Step 3: Add the `ValidationReport` dataclass**

Append to `gap_validator.py`:

```python
@dataclass(frozen=True, kw_only=True)
class ValidationReport:
    """Aggregate report from `validate_gaps`.

    Preconditions: `statuses` must be a list (possibly empty);
        `overall_confidence` in `[0.0, 1.0]`; `validated_at` is an
        ISO-8601 timestamp produced by `core.common.iso_now()`.
    Postconditions: instance is frozen.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    statuses: list[GapStatus]
    overall_confidence: float
    validated_at: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): add frozen kw_only ValidationReport dataclass (REQ-03)"
```

---

## Task 5: `parse_gap_list` happy path (REQ-06, positive cases)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_gap_validator.py`:

```python
class ParseGapListHappyPathTests(unittest.TestCase):
    """REQ-06: accepts {"gaps": [...]} and returns list[Gap]."""

    def test_parses_single_gap(self) -> None:
        from story_automator.core.gap_validator import Gap, parse_gap_list

        payload = """
        {
          "gaps": [
            {
              "file_path": "src/a.py",
              "line": 42,
              "symbol": "do_thing",
              "description": "missing nil check",
              "severity": "major"
            }
          ]
        }
        """
        gaps = parse_gap_list(payload)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(
            gaps[0],
            Gap(
                file_path="src/a.py",
                line=42,
                symbol="do_thing",
                description="missing nil check",
                severity="major",
            ),
        )

    def test_parses_empty_gap_list(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        gaps = parse_gap_list('{"gaps": []}')
        self.assertEqual(gaps, [])

    def test_parses_multiple_gaps_preserving_order(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = """{
          "gaps": [
            {"file_path": "a.py", "line": 1, "symbol": "x",
             "description": "d1", "severity": "blocker"},
            {"file_path": "b.py", "line": 2, "symbol": "y",
             "description": "d2", "severity": "minor"}
          ]
        }"""
        gaps = parse_gap_list(payload)
        self.assertEqual([g.file_path for g in gaps], ["a.py", "b.py"])
        self.assertEqual([g.severity for g in gaps], ["blocker", "minor"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL — `ImportError: cannot import name 'parse_gap_list'`.

- [ ] **Step 3: Add `parse_gap_list` (happy path only — error cases land in Task 6)**

Append to `gap_validator.py`:

```python
import json

_ALLOWED_SEVERITIES: frozenset[str] = frozenset({"blocker", "major", "minor"})
_REQUIRED_GAP_KEYS: tuple[str, ...] = (
    "file_path", "line", "symbol", "description", "severity",
)


def parse_gap_list(payload: str) -> list[Gap]:
    """Parse a `{"gaps": [...]}` JSON document into a list of `Gap`.

    Preconditions: `payload` must be valid JSON whose top-level value is
        an object containing a `"gaps"` key holding a list of objects.
        Each object must contain `file_path` (str), `line` (int),
        `symbol` (str), `description` (str), and `severity` (one of
        "blocker", "major", "minor").
    Postconditions: returns a `list[Gap]` preserving input order.
    Raises: ValueError with a field-locating message when a required
        key is missing, when `line` is not an integer, or when
        `severity` is outside the allowed set. json.JSONDecodeError
        propagates for malformed JSON (it is itself a ValueError, so
        callers catching ValueError catch both).
    """
    data = json.loads(payload)
    if not isinstance(data, dict) or "gaps" not in data:
        raise ValueError("payload must be a JSON object with a top-level 'gaps' key")
    raw_gaps = data["gaps"]
    if not isinstance(raw_gaps, list):
        raise ValueError("'gaps' must be a JSON array")

    out: list[Gap] = []
    for index, raw in enumerate(raw_gaps):
        if not isinstance(raw, dict):
            raise ValueError(f"gaps[{index}] must be a JSON object")
        for key in _REQUIRED_GAP_KEYS:
            if key not in raw:
                raise ValueError(f"gaps[{index}] missing required key {key!r}")
        line_value = raw["line"]
        # `bool` is a subclass of `int` in Python; reject it explicitly so
        # `"line": true` does not silently parse as `line=1`.
        if isinstance(line_value, bool) or not isinstance(line_value, int):
            raise ValueError(
                f"gaps[{index}].line must be an integer, got {type(line_value).__name__}"
            )
        severity = raw["severity"]
        if severity not in _ALLOWED_SEVERITIES:
            raise ValueError(
                f"gaps[{index}].severity must be one of "
                f"{sorted(_ALLOWED_SEVERITIES)!r}, got {severity!r}"
            )
        out.append(
            Gap(
                file_path=str(raw["file_path"]),
                line=line_value,
                symbol=str(raw["symbol"]),
                description=str(raw["description"]),
                severity=severity,
            )
        )
    return out
```

> Fold the new `import json` into the import block at the top of the module — the final import block is now:
>
> ```python
> from __future__ import annotations
>
> import json
> import logging
> from dataclasses import dataclass
> ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (17 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): implement parse_gap_list happy path (REQ-06)"
```

---

## Task 6: `parse_gap_list` negative cases (REQ-06, error matrix)

**Files:**
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gap_validator.py`:

```python
class ParseGapListErrorTests(unittest.TestCase):
    """REQ-06: precise field-locating ValueError on each malformed shape."""

    def test_rejects_non_object_top_level(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaisesRegex(ValueError, "top-level 'gaps' key"):
            parse_gap_list("[]")

    def test_rejects_missing_gaps_key(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaisesRegex(ValueError, "top-level 'gaps' key"):
            parse_gap_list('{"other": []}')

    def test_rejects_non_list_gaps_value(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaisesRegex(ValueError, "'gaps' must be a JSON array"):
            parse_gap_list('{"gaps": {}}')

    def test_rejects_non_object_gap_entry(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaisesRegex(ValueError, r"gaps\[0\] must be a JSON object"):
            parse_gap_list('{"gaps": ["a string"]}')

    def test_rejects_missing_required_key_with_field_locator(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = '{"gaps": [{"file_path": "a", "line": 1, "symbol": "s", "description": "d"}]}'
        with self.assertRaisesRegex(ValueError, r"gaps\[0\] missing required key 'severity'"):
            parse_gap_list(payload)

    def test_rejects_non_integer_line(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = (
            '{"gaps": [{"file_path": "a", "line": "42", "symbol": "s",'
            ' "description": "d", "severity": "minor"}]}'
        )
        with self.assertRaisesRegex(ValueError, r"gaps\[0\].line must be an integer"):
            parse_gap_list(payload)

    def test_rejects_boolean_line_even_though_bool_is_subclass_of_int(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = (
            '{"gaps": [{"file_path": "a", "line": true, "symbol": "s",'
            ' "description": "d", "severity": "minor"}]}'
        )
        with self.assertRaisesRegex(ValueError, r"gaps\[0\].line must be an integer"):
            parse_gap_list(payload)

    def test_rejects_unknown_severity(self) -> None:
        from story_automator.core.gap_validator import parse_gap_list

        payload = (
            '{"gaps": [{"file_path": "a", "line": 1, "symbol": "s",'
            ' "description": "d", "severity": "catastrophic"}]}'
        )
        with self.assertRaisesRegex(ValueError, r"gaps\[0\].severity must be one of"):
            parse_gap_list(payload)

    def test_malformed_json_raises_value_error(self) -> None:
        # json.JSONDecodeError is a ValueError, so callers catching
        # ValueError catch malformed JSON uniformly.
        from story_automator.core.gap_validator import parse_gap_list

        with self.assertRaises(ValueError):
            parse_gap_list("{not json")
```

- [ ] **Step 2: Run tests to verify they pass (implementation already covers them)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (26 tests). If any test fails, fix the corresponding branch in `parse_gap_list` — do not loosen the assertion.

- [ ] **Step 3: Commit the documentation tests**

```bash
git add tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(gap_validator): cover parse_gap_list error matrix (REQ-06)"
```

---

## Task 7: `validate_gaps` skeleton + base 0.8 confidence + empty-list aggregation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gap_validator.py`:

```python
import tempfile
from pathlib import Path


class ValidateGapsAggregationTests(unittest.TestCase):
    """REQ-03 + REQ-04: aggregate fields and base-confidence formula."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def test_empty_gap_list_returns_overall_confidence_one(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([], repo_root=self.root)
        self.assertEqual(report.statuses, [])
        self.assertEqual(report.overall_confidence, 1.0)
        self.assertRegex(report.validated_at, r"^\d{4}-\d{2}-\d{2}T")

    def test_overall_confidence_is_mean_of_per_gap_confidence(self) -> None:
        from story_automator.core.gap_validator import Gap, validate_gaps

        # Two gaps that both fail all three checks (no file exists in an
        # empty repo) → each gets base 0.8 → mean = 0.8.
        gaps = [
            Gap(file_path="missing_a.py", line=1, symbol="x",
                description="d", severity="minor"),
            Gap(file_path="missing_b.py", line=1, symbol="y",
                description="d", severity="minor"),
        ]
        report = validate_gaps(gaps, repo_root=self.root)
        self.assertEqual(len(report.statuses), 2)
        for status in report.statuses:
            self.assertFalse(status.path_exists)
            self.assertFalse(status.line_in_range)
            self.assertFalse(status.symbol_present)
            self.assertAlmostEqual(status.confidence, 0.8)
        self.assertAlmostEqual(report.overall_confidence, 0.8)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL — `ImportError: cannot import name 'validate_gaps'`.

- [ ] **Step 3: Implement `validate_gaps` (base formula only — file checks land in Tasks 8/9/10)**

Append to `gap_validator.py`:

```python
from pathlib import Path

from .common import iso_now

_BASE_CONFIDENCE: float = 0.8
_PASS_BONUS: float = 0.05
_CONFIDENCE_CEILING: float = 1.0


def _empty_overall_confidence() -> float:
    """Overall confidence when no gaps were submitted.

    Returning 1.0 expresses "no gaps to validate = trivially valid".
    Centralised here so the value is easy to change if the operator
    later prefers 0.0 ("no evidence either way").
    """
    return 1.0


def validate_gaps(gaps: list[Gap], *, repo_root: Path) -> ValidationReport:
    """Validate each gap's file/line/symbol citation against `repo_root`.

    Preconditions: `repo_root` is an existing directory; each gap's
        `file_path` is interpreted relative to `repo_root`. Absolute
        paths, `..` traversal escaping the root, and outward-pointing
        symlinks are rejected with `path_exists=False`.
    Postconditions: returns a `ValidationReport` whose `statuses` list
        is one-for-one with the input `gaps`, in the same order. Per-gap
        confidence lies in `[0.8, 0.95]` (cap 1.0); failed checks
        contribute one note each. Aggregate `overall_confidence` is the
        arithmetic mean of per-gap confidence rounded to 6 dp, or 1.0
        when `gaps` is empty.
    Raises: nothing under normal operation — IO errors during the
        line-range or symbol checks are converted into `False` results
        with an explanatory note, so a torn source tree degrades
        gracefully rather than aborting the report.
    """
    statuses: list[GapStatus] = []
    root_resolved = Path(repo_root).resolve()
    for gap in gaps:
        notes: list[str] = []
        path_exists = False  # Placeholder — Task 8 implements path resolution.
        line_in_range = False  # Placeholder — Task 9 implements line check.
        symbol_present = False  # Placeholder — Task 10 implements symbol check.
        if not path_exists:
            notes.append(f"path does not exist or escapes repo_root: {gap.file_path}")
        if not line_in_range:
            notes.append(
                f"line {gap.line} could not be verified in range for {gap.file_path}"
            )
        if not symbol_present:
            notes.append(
                f"symbol {gap.symbol!r} not found in {gap.file_path}"
            )
        confidence = _BASE_CONFIDENCE + _PASS_BONUS * sum(
            [path_exists, line_in_range, symbol_present]
        )
        confidence = min(confidence, _CONFIDENCE_CEILING)
        statuses.append(
            GapStatus(
                gap=gap,
                path_exists=path_exists,
                line_in_range=line_in_range,
                symbol_present=symbol_present,
                confidence=confidence,
                notes=notes,
            )
        )
    if statuses:
        overall = round(
            sum(s.confidence for s in statuses) / len(statuses), 6,
        )
    else:
        overall = _empty_overall_confidence()
    # `root_resolved` is computed up front so Tasks 8–11 can pass it
    # through to the per-gap path resolver; reference it here so ruff's
    # F841 does not flag it as unused on this intermediate revision.
    del root_resolved
    return ValidationReport(
        statuses=statuses,
        overall_confidence=overall,
        validated_at=iso_now(),
    )
```

> The final import block at module top after this task:
>
> ```python
> from __future__ import annotations
>
> import json
> import logging
> from dataclasses import dataclass
> from pathlib import Path
>
> from .common import iso_now
> ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (28 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): validate_gaps skeleton with base 0.8 confidence (REQ-03, REQ-04 partial)"
```

---

## Task 8: `path_exists` check + path-escape rejection (REQ-04 partial + REQ-05)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gap_validator.py`:

```python
import os


class PathExistsAndEscapeTests(unittest.TestCase):
    """REQ-04 (path_exists bonus) + REQ-05 (escape rejection)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

    def _gap(self, file_path: str) -> "Gap":
        from story_automator.core.gap_validator import Gap

        return Gap(
            file_path=file_path, line=1, symbol="anything",
            description="d", severity="minor",
        )

    def test_relative_path_existing_inside_root_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

        report = validate_gaps([self._gap("src/a.py")], repo_root=self.root)
        self.assertTrue(report.statuses[0].path_exists)
        # The path-exists note must NOT appear when path_exists is True.
        # We deliberately do NOT pin `confidence` here because Tasks 9 and
        # 10 will later flip `line_in_range` and `symbol_present` to True
        # (line 1 is in a 1-line file; "anything" happens not to be a
        # substring of "x = 1\n", so symbol stays False). The exact
        # confidence value is pinned by Task 10's
        # `test_all_three_checks_passing_yields_confidence_0_95`.
        joined = " | ".join(report.statuses[0].notes)
        self.assertNotIn("path does not exist", joined)

    def test_missing_relative_path_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("missing.py")], repo_root=self.root)
        self.assertFalse(report.statuses[0].path_exists)
        joined = " | ".join(report.statuses[0].notes)
        self.assertIn("missing.py", joined)

    def test_absolute_path_outside_root_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        # /etc/passwd on POSIX, C:\Windows\... on Windows — but we just
        # need ANY absolute path outside `repo_root`. Use the tempdir's
        # parent to stay cross-platform.
        outside = (self.root.parent / "definitely-outside.py")
        report = validate_gaps([self._gap(str(outside))], repo_root=self.root)
        self.assertFalse(report.statuses[0].path_exists)
        joined = " | ".join(report.statuses[0].notes)
        self.assertIn("escapes repo_root", joined)

    def test_parent_traversal_escaping_root_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps(
            [self._gap("../../../etc/passwd")], repo_root=self.root,
        )
        self.assertFalse(report.statuses[0].path_exists)

    def test_parent_traversal_resolving_inside_root_is_accepted(self) -> None:
        # `src/../src/a.py` resolves back to `src/a.py` — still inside.
        from story_automator.core.gap_validator import validate_gaps

        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")

        report = validate_gaps(
            [self._gap("src/../src/a.py")], repo_root=self.root,
        )
        self.assertTrue(report.statuses[0].path_exists)

    @unittest.skipIf(os.name == "nt", "symlink creation requires admin on Windows")
    def test_symlink_pointing_outside_root_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        # Real outside target.
        outside_dir = self.root.parent / "outside-symlink-target"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "leak.py"
        outside_file.write_text("secret = 1\n", encoding="utf-8")
        self.addCleanup(lambda: outside_file.unlink(missing_ok=True))
        self.addCleanup(lambda: outside_dir.rmdir())

        link = self.root / "leak.py"
        link.symlink_to(outside_file)

        report = validate_gaps([self._gap("leak.py")], repo_root=self.root)
        self.assertFalse(report.statuses[0].path_exists)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL on the new cases — current placeholder always returns `path_exists=False`, so the "accepted" assertions fail.

- [ ] **Step 3: Implement the `_resolve_inside_root` helper and wire it into `validate_gaps`**

Edit `gap_validator.py` — replace the placeholder lines in `validate_gaps` with a real path check, and add a new private helper:

```python
def _resolve_inside_root(
    file_path: str, root_resolved: Path,
) -> tuple[Path | None, str | None]:
    """Return `(resolved_path, None)` if `file_path` lives inside the root.

    Returns `(None, note)` if the candidate escapes the root — including
    absolute paths outside the root, `..` traversal escaping the root,
    and symlinks whose `resolve()` lands outside the root. `note` is a
    human-readable reason mentioning the rejected path.
    """
    candidate = Path(file_path)
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
    else:
        resolved = (root_resolved / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return None, f"path does not exist or escapes repo_root: {file_path}"
    if not resolved.is_file():
        return None, f"path does not exist or escapes repo_root: {file_path}"
    return resolved, None
```

Then replace the `path_exists = False  # placeholder` block in `validate_gaps` and the note-emission block. The new per-gap body is:

```python
    for gap in gaps:
        notes: list[str] = []
        resolved, escape_note = _resolve_inside_root(gap.file_path, root_resolved)
        path_exists = resolved is not None
        if escape_note is not None:
            notes.append(escape_note)

        line_in_range = False  # Placeholder — Task 9 implements line check.
        symbol_present = False  # Placeholder — Task 10 implements symbol check.

        if not line_in_range:
            notes.append(
                f"line {gap.line} could not be verified in range for {gap.file_path}"
            )
        if not symbol_present:
            notes.append(
                f"symbol {gap.symbol!r} not found in {gap.file_path}"
            )

        confidence = _BASE_CONFIDENCE + _PASS_BONUS * sum(
            [path_exists, line_in_range, symbol_present]
        )
        confidence = min(confidence, _CONFIDENCE_CEILING)
        statuses.append(
            GapStatus(
                gap=gap,
                path_exists=path_exists,
                line_in_range=line_in_range,
                symbol_present=symbol_present,
                confidence=confidence,
                notes=notes,
            )
        )
```

Remove the `del root_resolved` line — it is now used.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (33 tests on POSIX, 32 on Windows due to the `skipIf` on the symlink test).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): resolve file_path inside repo_root, reject escapes (REQ-05)"
```

---

## Task 9: `line_in_range` check (REQ-04 partial)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gap_validator.py`:

```python
class LineInRangeTests(unittest.TestCase):
    """REQ-04: `line_in_range` is True iff 1 <= line <= number-of-lines."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        (self.root / "a.py").write_text(
            "line1\nline2\nline3\n", encoding="utf-8",
        )

    def _gap(self, line: int) -> "Gap":
        from story_automator.core.gap_validator import Gap

        return Gap(
            file_path="a.py", line=line, symbol="anything",
            description="d", severity="minor",
        )

    def test_line_inside_range_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(2)], repo_root=self.root)
        self.assertTrue(report.statuses[0].line_in_range)

    def test_line_at_lower_bound_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(1)], repo_root=self.root)
        self.assertTrue(report.statuses[0].line_in_range)

    def test_line_at_upper_bound_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(3)], repo_root=self.root)
        self.assertTrue(report.statuses[0].line_in_range)

    def test_line_zero_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(0)], repo_root=self.root)
        self.assertFalse(report.statuses[0].line_in_range)
        joined = " | ".join(report.statuses[0].notes)
        self.assertIn("line 0", joined)

    def test_line_beyond_end_of_file_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap(999)], repo_root=self.root)
        self.assertFalse(report.statuses[0].line_in_range)

    def test_missing_path_implies_line_not_in_range(self) -> None:
        from story_automator.core.gap_validator import Gap, validate_gaps

        report = validate_gaps(
            [Gap(file_path="missing.py", line=1, symbol="x",
                 description="d", severity="minor")],
            repo_root=self.root,
        )
        self.assertFalse(report.statuses[0].line_in_range)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL on the new "accepted" cases — placeholder still always returns False.

- [ ] **Step 3: Implement `_check_line_in_range` and wire it into `validate_gaps`**

Edit `gap_validator.py` — add the helper:

```python
def _check_line_in_range(resolved_path: Path | None, line: int) -> tuple[bool, str | None]:
    """Return `(True, None)` if `1 <= line <= file_line_count`.

    Returns `(False, note)` otherwise. If `resolved_path` is None (path
    rejection already noted by the caller), returns `(False, None)` so
    the caller doesn't double-note the same root cause.
    """
    if resolved_path is None:
        return False, None
    try:
        text = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"could not read {resolved_path.name} for line check: {exc}"
    except UnicodeDecodeError as exc:
        # A binary or non-UTF-8 file lives inside the root; the gap
        # cannot be verified but the verifier must not crash. Report
        # gracefully — REQ-04 confidence simply doesn't get the bonus.
        return False, f"could not decode {resolved_path.name} as UTF-8: {exc}"
    if not text:
        line_count = 0
    else:
        # `splitlines()` correctly counts the final line whether the
        # file ends with a newline or not.
        line_count = len(text.splitlines())
    if 1 <= line <= line_count:
        return True, None
    return False, f"line {line} outside file range 1..{line_count}"
```

Replace the placeholder block in the per-gap loop:

```python
        line_in_range, line_note = _check_line_in_range(resolved, gap.line)
        if line_note is not None:
            notes.append(line_note)
        elif not line_in_range and resolved is None:
            # Path already noted; nothing extra to say about the line.
            pass
```

Replace the old unconditional `notes.append(f"line {gap.line} ...")` block — it is now driven by `_check_line_in_range`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (39 tests on POSIX).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): implement line_in_range check (REQ-04)"
```

---

## Task 10: `symbol_present` check (REQ-04 partial)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gap_validator.py`:

```python
class SymbolPresentTests(unittest.TestCase):
    """REQ-04: `symbol_present` is True iff the literal symbol occurs in the source."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        (self.root / "a.py").write_text(
            "def do_thing():\n    return 42\n", encoding="utf-8",
        )

    def _gap(self, symbol: str) -> "Gap":
        from story_automator.core.gap_validator import Gap

        return Gap(
            file_path="a.py", line=1, symbol=symbol,
            description="d", severity="minor",
        )

    def test_present_symbol_is_accepted(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("do_thing")], repo_root=self.root)
        self.assertTrue(report.statuses[0].symbol_present)

    def test_absent_symbol_is_rejected(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("not_there")], repo_root=self.root)
        self.assertFalse(report.statuses[0].symbol_present)
        joined = " | ".join(report.statuses[0].notes)
        self.assertIn("not_there", joined)

    def test_all_three_checks_passing_yields_confidence_0_95(self) -> None:
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("do_thing")], repo_root=self.root)
        s = report.statuses[0]
        self.assertTrue(s.path_exists)
        self.assertTrue(s.line_in_range)
        self.assertTrue(s.symbol_present)
        self.assertAlmostEqual(s.confidence, 0.95)
        self.assertEqual(s.notes, [])

    def test_missing_path_implies_symbol_not_present(self) -> None:
        from story_automator.core.gap_validator import Gap, validate_gaps

        report = validate_gaps(
            [Gap(file_path="missing.py", line=1, symbol="x",
                 description="d", severity="minor")],
            repo_root=self.root,
        )
        self.assertFalse(report.statuses[0].symbol_present)

    def test_empty_symbol_string_is_rejected(self) -> None:
        # An empty string is trivially a substring of any text; reject
        # explicitly so the verifier cannot be silently bypassed.
        from story_automator.core.gap_validator import validate_gaps

        report = validate_gaps([self._gap("")], repo_root=self.root)
        self.assertFalse(report.statuses[0].symbol_present)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: FAIL on the new "accepted" cases — placeholder still always False.

- [ ] **Step 3: Implement `_check_symbol_present` and wire it into `validate_gaps`**

Add the helper to `gap_validator.py`:

```python
def _check_symbol_present(
    resolved_path: Path | None, symbol: str,
) -> tuple[bool, str | None]:
    """Return `(True, None)` if `symbol` literally occurs in the source text.

    Empty `symbol` is rejected (an empty string is trivially a substring
    of every file and would silently inflate confidence). If
    `resolved_path` is None, returns `(False, None)` — the caller has
    already noted the root cause.
    """
    if resolved_path is None:
        return False, None
    if not symbol:
        return False, f"symbol '' is empty; refusing to claim presence"
    try:
        text = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"could not read {resolved_path.name} for symbol check: {exc}"
    except UnicodeDecodeError as exc:
        # Same rationale as `_check_line_in_range`: degrade gracefully
        # on binary / non-UTF-8 files instead of crashing the report.
        return False, f"could not decode {resolved_path.name} as UTF-8: {exc}"
    if symbol in text:
        return True, None
    return False, f"symbol {symbol!r} not found in {resolved_path.name}"
```

Replace the placeholder block in the per-gap loop:

```python
        symbol_present, symbol_note = _check_symbol_present(resolved, gap.symbol)
        if symbol_note is not None:
            notes.append(symbol_note)
```

Remove the old unconditional `notes.append(f"symbol {gap.symbol!r} ...")` block.

> Reading the file twice (once for line count, once for symbol) is intentionally simple; M06a-M1 prioritises clarity over micro-optimisation. A future wedge may cache the read if profiling shows it matters.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (44 tests on POSIX, 43 on Windows — the symlink case is skipped).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(gap_validator): implement symbol_present substring check (REQ-04)"
```

---

## Task 11: Symbol existence assertion (closes the `__all__`-vs-reality gap)

**Files:**
- Modify: `tests/test_gap_validator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gap_validator.py`:

```python
class AllSymbolsActuallyDefinedTests(unittest.TestCase):
    """REQ-16: every name in `__all__` must actually be defined.

    The Task 1 import-contract test only checks `__all__` membership;
    this test closes the gap by asserting each declared name resolves
    to a real attribute on the module.
    """

    def test_each_all_symbol_resolves(self) -> None:
        from story_automator.core import gap_validator

        for name in gap_validator.__all__:
            self.assertTrue(
                hasattr(gap_validator, name),
                f"__all__ advertises {name!r} but the module has no such attribute",
            )

    def test_no_unrelated_layer_imports(self) -> None:
        """Quality gate: no import from other M06a layers or from commands/."""
        import inspect

        from story_automator.core import gap_validator

        source = inspect.getsource(gap_validator)
        for forbidden in (
            "from .spec_compliance",
            "from .feature_tester",
            "from story_automator.commands",
            "from ..commands",
        ):
            self.assertNotIn(forbidden, source)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v`
Expected: PASS (46 tests on POSIX, 45 on Windows — the symlink case is skipped).

- [ ] **Step 3: Commit**

```bash
git add tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(gap_validator): assert __all__ resolves and forbidden layer imports absent (REQ-16)"
```

---

## Task 12: `mypy --strict`, ruff, and module-size gates

**Files:**
- Inspect (no edits unless gates fail): `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`, `tests/test_gap_validator.py`

- [ ] **Step 1: Ruff check**

Run: `python -m ruff check skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py`
Expected: exit 0. Fix source — do not add `# noqa` without an inline rationale.

- [ ] **Step 2: Ruff format check**

Run: `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py`
If it fails: `python -m ruff format skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py` then re-run the check.

- [ ] **Step 3: mypy --strict**

Run: `python -m mypy --strict skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
Expected: `Success: no issues found`.

Common fixes if mypy fails:
- Missing return annotation on a private helper → add `-> bool`, `-> str | None`, etc.
- `Path | None` confusion → ensure helpers consistently return `tuple[bool, str | None]` (not `tuple[bool, Optional[str]]`).
- `# type: ignore` may only be introduced with an adjacent justification comment (NFR).

If `core.common` is untyped enough to confuse mypy, add a single-line cast at the import site:

```python
from .common import iso_now  # noqa: I001 — typed via runtime contract; mypy stub deferred
```

If mypy reports "Cannot find implementation or library stub for module named 'story_automator.core.common'", run from the package root with `MYPYPATH` exported.

Bash / git-bash:

```bash
MYPYPATH=skills/bmad-story-automator/src python -m mypy --strict --explicit-package-bases \
  skills/bmad-story-automator/src/story_automator/core/gap_validator.py
```

PowerShell (bash inline `VAR=val cmd` syntax is a parser error in PS):

```powershell
$env:MYPYPATH = "skills/bmad-story-automator/src"
python -m mypy --strict --explicit-package-bases `
  skills/bmad-story-automator/src/story_automator/core/gap_validator.py
Remove-Item Env:MYPYPATH
```

- [ ] **Step 4: Module size guardrail**

PowerShell: `(Get-Content skills/bmad-story-automator/src/story_automator/core/gap_validator.py | Measure-Object -Line).Lines`
Bash: `wc -l skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
Expected: ≤ 500 source lines (target: well under 300).

- [ ] **Step 5: Import allowlist audit**

PowerShell: `Select-String -Path skills/bmad-story-automator/src/story_automator/core/gap_validator.py -Pattern '^(import|from) '`
Bash: `grep -E "^(import|from) " skills/bmad-story-automator/src/story_automator/core/gap_validator.py`

Expected — exactly these imports, all stdlib + the one cross-module import:
- `from __future__ import annotations`
- `import json`
- `import logging`
- `from dataclasses import dataclass`
- `from pathlib import Path`
- `from .common import iso_now`

No `psutil`, no `filelock`, no `from .spec_compliance`, no `from .feature_tester`, no `from ..commands`.

- [ ] **Step 6: Commit any formatting/typing fixes**

If Steps 1–5 produced edits:

```bash
git add skills/bmad-story-automator/src/story_automator/core/gap_validator.py tests/test_gap_validator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(gap_validator): ruff format + mypy --strict pass"
```

If no fixes were needed, skip — do not create an empty commit.

---

## Task 13: Coverage gate (≥92%) and final diff-scope audit

**Files:** none modified.

- [ ] **Step 1: Coverage run**

Run from the repo root:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/gap_validator \
  -m unittest tests.test_gap_validator
python -m coverage report -m --fail-under=92
```

Expected: PASS with line coverage ≥ 92%.

If a branch is uncovered, add a focused negative-path test rather than lowering the gate. Only mark an irrelevant line with `# pragma: no cover` if there is no reasonable test for it (e.g. defensive `except` for an OS error that's impossible to reproduce portably) — and the pragma MUST carry a same-line `# rationale: <one-line explanation>` comment.

- [ ] **Step 2: Full Python suite regression check**

Run: `npm run test:python`
Expected: PASS — every pre-existing test plus `tests/test_gap_validator.py` discovers and passes.

- [ ] **Step 3: Diff-scope audit (quality gate: diff limited to two files)**

PowerShell:
```powershell
git diff --name-only main...HEAD
```
Bash:
```bash
git diff --name-only main...HEAD
```

Expected output — exactly these two paths (plus this plan file and any earlier commits that copied the spec in):
- `skills/bmad-story-automator/src/story_automator/core/gap_validator.py`
- `tests/test_gap_validator.py`

If any other source file is in the diff, revert it (`git checkout main -- <path>`). The plan file (`docs/superpowers/plans/2026-06-15-m06a-m1-gap-validator.md`) and the spec file are documentation, not source — they are not counted by this gate.

- [ ] **Step 4: Cross-platform sanity (Windows git-bash)**

Run from a Windows git-bash prompt:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator -v
```

Expected: PASS. The symlink test (`test_symlink_pointing_outside_root_is_rejected`) is skipped on Windows via `@unittest.skipIf(os.name == "nt", ...)`. Pay attention to:
- Path-escape tests that use `..` traversal — the resolution semantics must match POSIX on Windows.
- The absolute-path-outside test — uses `self.root.parent` to stay cross-platform.

- [ ] **Step 5: Final sign-off (no commit)**

Print one line confirming "M06a-M1 gates green on Windows git-bash and Linux CI" in the conversation. Do not amend prior commits — leave the history as a clean stack of feat/test/style commits, one per task.

---

## Self-Review Checklist

**Spec coverage:**
- REQ-01 (`Gap` frozen kw_only): Task 2.
- REQ-02 (`GapStatus` frozen kw_only): Task 3.
- REQ-03 (`ValidationReport` frozen kw_only with `iso_now()` for `validated_at`): Task 4 + Task 7 (`iso_now` wiring) + Task 7 (`overall_confidence` aggregation).
- REQ-04 (base 0.8 + 0.05 per pass, cap 1.0, failed-check notes): Task 7 (base + cap + aggregation), Task 8 (`path_exists` bonus), Task 9 (`line_in_range` bonus), Task 10 (`symbol_present` bonus + the 0.95 max test). The "failed checks contribute 0.0" wording in the spec is satisfied by the formula — failures simply don't add the bonus.
- REQ-05 (path-escape rejection — absolute outside, `..` outside, symlinks outside; never read files outside `repo_root`): Task 8.
- REQ-06 (`parse_gap_list` happy path + field-locating ValueError matrix): Task 5 + Task 6.
- REQ-16 (importable in any order, no import-time side effects beyond `logging.getLogger(__name__)`, `__all__` declared): Task 1 + Task 11 (symbol existence + forbidden-import audit).
- NFR — frozen kw_only, not subclassing other dataclasses, stdlib-only, PEP 604, `from __future__ import annotations`, pre/post/raises docstrings, mypy `--strict`: Tasks 1–4 (dataclasses), Task 5 (parser), Task 7 (validator), Task 12 (mypy + ruff).
- Quality gates — ruff clean, mypy strict clean, ≥92% coverage with pragma rationales, ≥6 test methods, ≥1 negative per public function, no cross-layer imports, diff scoped to two files: Tasks 11–13.

**Test count and negative-coverage check:**
- Final test count on POSIX: ~46 methods across 11 `TestCase` classes — comfortably above the ≥6 spec floor.
- `validate_gaps` negative tests: empty list (Task 7), missing path (Tasks 8/9/10), line zero (Task 9), line beyond end (Task 9), absent symbol (Task 10), empty symbol (Task 10).
- `parse_gap_list` negative tests: nine separate cases in Task 6.

**Placeholder scan:** No "TODO", "TBD", "fill in details". The intentional placeholders inside `validate_gaps` (Task 7) are replaced wholesale in Tasks 8–10 — no placeholder survives Task 10.

**Type consistency:**
- `validate_gaps(gaps: list[Gap], *, repo_root: Path) -> ValidationReport` — used identically in Tasks 7–10.
- `parse_gap_list(payload: str) -> list[Gap]` — used identically in Tasks 5–6.
- `_resolve_inside_root(file_path: str, root_resolved: Path) -> tuple[Path | None, str | None]` — Task 8.
- `_check_line_in_range(resolved_path: Path | None, line: int) -> tuple[bool, str | None]` — Task 9.
- `_check_symbol_present(resolved_path: Path | None, symbol: str) -> tuple[bool, str | None]` — Task 10.

**Test names match implementation:** The `_resolve_inside_root`, `_check_line_in_range`, and `_check_symbol_present` helpers are private and unused by tests — only the public `validate_gaps` / `parse_gap_list` symbols appear in test imports. No drift risk.

---

## Notes for the implementer

1. **Why store `notes` as `list[str]` on a frozen dataclass?** `frozen=True` only forbids rebinding the field; the list object itself remains mutable. We construct each `GapStatus` with a final `notes` list and never touch it again, so the mutability is theoretical. Switching to `tuple[str, ...]` would force callers to convert before constructing — not worth the friction.

2. **Why `round(value, 6)` for `overall_confidence`?** Floating-point arithmetic varies across platforms (and even across CPython versions, in the last bits). Rounding to 6 dp gives tests a stable equality target without coupling them to a specific FP backend.

3. **Why reject empty-string symbols?** `"" in any_string` is always `True` in Python, so without the explicit empty-string check, a review skill that drops the `symbol` field could silently get a False-positive `symbol_present=True`. The spec REQ-04 says "named symbol literally occurs in the cited source" — an empty name is not a name.

4. **Why `Path.resolve(strict=False)`?** The spec mandates that non-existent paths still get a `path_exists=False` result rather than raising. `strict=False` resolves what it can (following any existing symlinks) and stops gracefully at the first missing component. We then verify the resolved path is inside `repo_root.resolve()` BEFORE checking `is_file()` — that ordering is what enforces REQ-05's "must never read files outside `repo_root`".

5. **Why no caching for `read_text`?** REQ-04 says read the source for both line count and symbol check; the simplest implementation reads twice. For a small gap list (the realistic case) the cost is negligible, and a cache adds state that would have to be invalidated if a future caller mutates files between calls. YAGNI.

6. **Why is `_empty_overall_confidence()` a helper, not a constant?** The spec is silent on the empty-list case. By isolating the choice in one helper, a future operator can switch to "0.0 = no evidence" by editing one line without rewriting `validate_gaps`. The default `1.0` matches the intuition "no gaps to validate is the trivially valid case", which is what an orchestrator wants when chaining short-circuit checks.

7. **What's deferred to M06a-M2 and M06a-M3?**
   - Layer 2 (`core/spec_compliance.py`) — subprocess invocation of `claude -p`, `ReqVerdict`, `ComplianceReport`, `check_compliance`, `ComplianceError`. REQ-07..11.
   - Layer 3 (`core/feature_tester.py`) — `TestPlanEntry`, `plan_feature_tests`, skeleton test generation. REQ-12..15.
   - The M06b orchestrator skill markdown that chains all three layers.
