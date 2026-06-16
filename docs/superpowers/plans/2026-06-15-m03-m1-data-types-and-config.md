# M03-M1 — Budget Ceilings: Data Types and Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the data-type substrate of the M03 budget-ceilings module — `CeilingDecision`, `BudgetCeiling`, and a tolerant `parse_ceilings_config` reader — so later sub-milestones can layer the evaluator, the bypass helper, and BMAD skill wiring on top without re-doing schema decisions.

**Architecture:** A single new module `core/budget_ceilings.py` exposes three public names: the `CeilingDecision` enum (REQ-02), the `BudgetCeiling` `@dataclass(kw_only=True)` (REQ-03), and `parse_ceilings_config()` (REQ-04, REQ-05). The reader is intentionally tolerant — missing file, missing JSON keys, and malformed ceiling entries all return an empty list or are silently skipped, with structured warnings collected in a module-level `_PARSE_WARNINGS` list that is cleared at the start of every call. The evaluator (`evaluate_ceilings`), bypass helper (`bypass_allowed`), and BMAD step wiring are explicitly **out of scope** for this sub-milestone and ship in M03-M2 / M03-M3.

**Tech Stack:** Python 3.11+, stdlib only (`json`, `enum`, `dataclasses`, `pathlib`), reuse of `core.common` for path handling. Tests use `unittest.TestCase` and `compact_json` from `core.common` (REQ-15) so the JSON fixtures match the wire format M02 writes. No third-party dependency is added or imported.

---

## File Structure

- **Create** `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` (~150 LOC ceiling)
  - `CeilingDecision` enum (3 members)
  - `BudgetCeiling` dataclass (5 fields, kw_only)
  - `_PARSE_WARNINGS: list[dict[str, str]]` module-level list
  - `_VALID_WINDOWS` constant set
  - `parse_ceilings_config(path) -> list[BudgetCeiling]`
  - `_validate_ceiling_dict(raw) -> BudgetCeiling | None` private helper
- **Create** `skills/bmad-story-automator/tests/test_budget_ceilings.py` (~250 LOC ceiling)
  - Module import smoke test
  - `CeilingDecision` enum shape tests
  - `BudgetCeiling` field/shape tests
  - `parse_ceilings_config` happy path
  - `parse_ceilings_config` missing-file / missing-keys / empty-JSON tests
  - `parse_ceilings_config` malformed-entry skipping tests with `_PARSE_WARNINGS` assertions
  - Cross-platform path handling test (str + Path both accepted)

No other files are modified in this sub-milestone. The BMAD step markdown insertion (REQ-13) and the `sw cli ceiling-check` dispatcher entry (mentioned in the spec's out-of-scope section as belonging to M03-M3) are not touched here.

---

## Task 1: Module scaffold and import smoke test

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_budget_ceilings.py
from __future__ import annotations

import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import budget_ceilings  # noqa: F401


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'story_automator.core.budget_ceilings'`.

- [ ] **Step 3: Create the minimal module**

```python
# skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py
"""Budget ceiling data types and config reader (M03 sub-milestone M1).

This module ships the data substrate for M03 budget enforcement: the
``CeilingDecision`` enum, the ``BudgetCeiling`` dataclass, and the
tolerant ``parse_ceilings_config`` reader. The evaluator, bypass
helper, and BMAD step wiring are scheduled for M03-M2 / M03-M3.
"""

from __future__ import annotations

__all__ = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (1 test, 0 failures).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): scaffold core module and test file (M03-M1)"
```

---

## Task 2: `CeilingDecision` enum shape

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

Spec reference: REQ-02 — exactly three members `ALLOW`, `WARN`, `BLOCK` in that declaration order, each with a string value equal to its name.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class CeilingDecisionTests(unittest.TestCase):
    def test_has_exactly_three_members(self) -> None:
        from story_automator.core.budget_ceilings import CeilingDecision

        self.assertEqual(len(list(CeilingDecision)), 3)

    def test_member_names_and_order(self) -> None:
        from story_automator.core.budget_ceilings import CeilingDecision

        names = [m.name for m in CeilingDecision]
        self.assertEqual(names, ["ALLOW", "WARN", "BLOCK"])

    def test_member_values_match_names(self) -> None:
        from story_automator.core.budget_ceilings import CeilingDecision

        self.assertEqual(CeilingDecision.ALLOW.value, "ALLOW")
        self.assertEqual(CeilingDecision.WARN.value, "WARN")
        self.assertEqual(CeilingDecision.BLOCK.value, "BLOCK")

    def test_is_enum_subclass(self) -> None:
        import enum

        from story_automator.core.budget_ceilings import CeilingDecision

        self.assertTrue(issubclass(CeilingDecision, enum.Enum))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 4 errors (`ImportError: cannot import name 'CeilingDecision'`).

- [ ] **Step 3: Add the enum**

Edit `budget_ceilings.py` — add the import and the enum block above `__all__`:

```python
import enum


class CeilingDecision(enum.Enum):
    """Tri-state verdict returned by ceiling evaluation.

    Declaration order is load-bearing: callers may compare verdicts by
    member index when merging multi-ceiling results (REQ-10), so the
    sequence ALLOW < WARN < BLOCK must never be reordered.
    """

    ALLOW = "ALLOW"
    WARN = "WARN"
    BLOCK = "BLOCK"
```

And update `__all__`:

```python
__all__ = ["CeilingDecision"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (5 tests, 0 failures).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): add CeilingDecision enum (M03 REQ-02)"
```

---

## Task 3: `BudgetCeiling` dataclass shape

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

Spec reference: REQ-03 — `@dataclass(kw_only=True)`, fields `name: str`, `window: str`, `limit_usd: float`, `warn_at: float`, `gate_names: tuple[str, ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class BudgetCeilingShapeTests(unittest.TestCase):
    def test_is_kw_only_dataclass(self) -> None:
        import dataclasses

        from story_automator.core.budget_ceilings import BudgetCeiling

        self.assertTrue(dataclasses.is_dataclass(BudgetCeiling))
        # Positional construction must fail because dataclass is kw_only.
        with self.assertRaises(TypeError):
            BudgetCeiling("c1", "per_run", 10.0, 0.8, ("init",))  # type: ignore[misc]

    def test_field_names_exact(self) -> None:
        import dataclasses

        from story_automator.core.budget_ceilings import BudgetCeiling

        names = [f.name for f in dataclasses.fields(BudgetCeiling)]
        self.assertEqual(
            names,
            ["name", "window", "limit_usd", "warn_at", "gate_names"],
        )

    def test_can_construct_with_keywords(self) -> None:
        from story_automator.core.budget_ceilings import BudgetCeiling

        ceiling = BudgetCeiling(
            name="per_run_cap",
            window="per_run",
            limit_usd=25.0,
            warn_at=0.8,
            gate_names=("init", "story_start"),
        )
        self.assertEqual(ceiling.name, "per_run_cap")
        self.assertEqual(ceiling.window, "per_run")
        self.assertEqual(ceiling.limit_usd, 25.0)
        self.assertEqual(ceiling.warn_at, 0.8)
        self.assertEqual(ceiling.gate_names, ("init", "story_start"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 3 errors (`ImportError: cannot import name 'BudgetCeiling'`).

- [ ] **Step 3: Add the dataclass**

Edit `budget_ceilings.py`. Add `from dataclasses import dataclass` to the imports and insert the dataclass after the enum:

```python
from dataclasses import dataclass


@dataclass(kw_only=True)
class BudgetCeiling:
    """Single configured spending ceiling read from ``workflow.json``.

    ``window`` is one of ``"per_run"``, ``"24h"``, ``"7d"``, ``"30d"``
    (REQ-03). ``warn_at`` is a fraction in ``(0.0, 1.0]`` multiplied
    against ``limit_usd`` to produce the WARN threshold. ``gate_names``
    enumerates which preflight gate names this ceiling applies to:
    elements are drawn from ``{"init", "story_start", "retry_start"}``
    per REQ-07, but this dataclass does not enforce that set — the
    evaluator (M03-M2) is the only consumer that filters on it.
    """

    name: str
    window: str
    limit_usd: float
    warn_at: float
    gate_names: tuple[str, ...]
```

Update `__all__`:

```python
__all__ = ["BudgetCeiling", "CeilingDecision"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (8 tests, 0 failures).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): add BudgetCeiling dataclass (M03 REQ-03)"
```

---

## Task 4: `_PARSE_WARNINGS` module-level list and clearing contract

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

Spec reference: REQ-05 — module-level `_PARSE_WARNINGS` list cleared on every call.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class ParseWarningsModuleStateTests(unittest.TestCase):
    def test_module_exposes_parse_warnings_list(self) -> None:
        from story_automator.core import budget_ceilings

        self.assertTrue(hasattr(budget_ceilings, "_PARSE_WARNINGS"))
        self.assertIsInstance(budget_ceilings._PARSE_WARNINGS, list)

    def test_parse_warnings_starts_empty(self) -> None:
        from story_automator.core import budget_ceilings

        # Snapshot at import time may be empty or hold prior-call detritus
        # depending on test order, but the list object identity must be
        # stable across calls (it is module-level, not function-local).
        first = budget_ceilings._PARSE_WARNINGS
        second = budget_ceilings._PARSE_WARNINGS
        self.assertIs(first, second)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 2 errors (`AttributeError: module ... has no attribute '_PARSE_WARNINGS'`).

- [ ] **Step 3: Add the module-level list**

Edit `budget_ceilings.py` — add the declaration after the dataclass:

```python
_PARSE_WARNINGS: list[dict[str, str]] = []
"""Structured parse warnings, cleared at the start of each
``parse_ceilings_config`` call (REQ-05). Each entry is a dict with
``index`` (str repr of the position in the array), ``reason``
(short slug), and ``detail`` (free-form message). Intentionally
module-level, not part of the function return, so callers that care
about warnings can opt in without complicating the happy-path
signature."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (10 tests, 0 failures).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): add _PARSE_WARNINGS module-level list (M03 REQ-05)"
```

---

## Task 5: `parse_ceilings_config` — missing file returns empty list

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

Spec reference: REQ-04 — missing file returns empty list rather than raise.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py` (after fixture import block — add the imports at the top of the file if not present):

```python
import tempfile
from pathlib import Path

from story_automator.core.common import compact_json, ensure_dir


class ParseCeilingsConfigMissingFileTests(unittest.TestCase):
    def test_missing_file_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist.json"
            result = parse_ceilings_config(missing)
            self.assertEqual(result, [])

    def test_missing_file_accepts_str_path(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "does-not-exist.json")
            result = parse_ceilings_config(missing)
            self.assertEqual(result, [])

    def test_missing_file_clears_parse_warnings(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        budget_ceilings._PARSE_WARNINGS.append(
            {"index": "0", "reason": "stale", "detail": "from prior test"}
        )
        with tempfile.TemporaryDirectory() as tmp:
            parse_ceilings_config(Path(tmp) / "missing.json")
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 3 errors (`ImportError: cannot import name 'parse_ceilings_config'`).

- [ ] **Step 3: Implement the missing-file path**

Edit `budget_ceilings.py`. Add the imports at the top:

```python
import json
from pathlib import Path
```

Add the function below `_PARSE_WARNINGS`:

```python
def parse_ceilings_config(workflow_json_path: str | Path) -> list[BudgetCeiling]:
    """Read ``policy.cost_ceilings`` from ``workflow.json`` (REQ-04, REQ-05).

    Tolerant by design: missing file, empty JSON, missing ``policy`` key,
    and missing ``cost_ceilings`` key all return an empty list. Malformed
    individual ceiling entries are skipped silently while a structured
    warning is appended to ``_PARSE_WARNINGS``; the warning list is
    cleared at the start of every call so callers can inspect just the
    warnings produced by the most recent invocation.
    """
    _PARSE_WARNINGS.clear()
    path = Path(workflow_json_path)
    if not path.is_file():
        return []
    return []
```

Update `__all__`:

```python
__all__ = ["BudgetCeiling", "CeilingDecision", "parse_ceilings_config"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (13 tests, 0 failures).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): parse_ceilings_config skeleton handles missing file (M03 REQ-04)"
```

---

## Task 6: `parse_ceilings_config` — missing-key tolerance (empty JSON, no `policy`, no `cost_ceilings`)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

Spec reference: REQ-04 — absence of `policy` or `cost_ceilings` returns empty list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class ParseCeilingsConfigMissingKeysTests(unittest.TestCase):
    def _write(self, tmp: str, payload: object) -> Path:
        path = Path(tmp) / "workflow.json"
        path.write_text(compact_json(payload), encoding="utf-8")
        return path

    def test_empty_object_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {})
            self.assertEqual(parse_ceilings_config(path), [])

    def test_no_policy_key_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"other": {"foo": "bar"}})
            self.assertEqual(parse_ceilings_config(path), [])

    def test_no_cost_ceilings_key_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"policy": {"unrelated": 1}})
            self.assertEqual(parse_ceilings_config(path), [])

    def test_cost_ceilings_not_a_list_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {"policy": {"cost_ceilings": {"not": "a list"}}})
            self.assertEqual(parse_ceilings_config(path), [])

    def test_top_level_not_object_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(compact_json([1, 2, 3]), encoding="utf-8")
            self.assertEqual(parse_ceilings_config(path), [])

    def test_invalid_json_returns_empty_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text("not json {", encoding="utf-8")
            self.assertEqual(parse_ceilings_config(path), [])
```

- [ ] **Step 2: Run tests to verify they pass against the skeleton**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (6 new tests). The skeleton trivially returns `[]` for every input, which matches each test's expectation — this set of tests is intentionally written first so the implementation in Step 3 cannot regress them. The implementation must continue to return `[]` for every malformed-shape input; it only adds the file-reading path and JSON traversal so well-formed input (Task 7) can later return ceilings.

- [ ] **Step 3: Implement file reading with broad tolerance**

Replace the body of `parse_ceilings_config` so it walks the JSON tree defensively. Edit `budget_ceilings.py`:

```python
def parse_ceilings_config(workflow_json_path: str | Path) -> list[BudgetCeiling]:
    """Read ``policy.cost_ceilings`` from ``workflow.json`` (REQ-04, REQ-05).

    Tolerant by design: missing file, empty JSON, malformed JSON, missing
    ``policy`` key, missing ``cost_ceilings`` key, and ``cost_ceilings``
    not being a list all return an empty list. Individual malformed
    ceiling entries are skipped while a structured warning is appended
    to ``_PARSE_WARNINGS`` (cleared at the start of every call).
    """
    _PARSE_WARNINGS.clear()
    path = Path(workflow_json_path)
    if not path.is_file():
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        return []
    raw_ceilings = policy.get("cost_ceilings")
    if not isinstance(raw_ceilings, list):
        return []
    return []
```

(Still returns `[]` even after a valid list — Task 7 adds the per-entry parser.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (19 tests, 0 failures).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): tolerate missing policy/cost_ceilings keys (M03 REQ-04)"
```

---

## Task 7: `parse_ceilings_config` — happy path with one well-formed ceiling

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- Test: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

Spec reference: REQ-04 — return `BudgetCeiling` instances in file order; REQ-03 — validate the field constraints.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class ParseCeilingsConfigHappyPathTests(unittest.TestCase):
    def _write(self, tmp: str, ceilings: list[dict[str, object]]) -> Path:
        ensure_dir(tmp)
        path = Path(tmp) / "workflow.json"
        path.write_text(
            compact_json({"policy": {"cost_ceilings": ceilings}}),
            encoding="utf-8",
        )
        return path

    def test_single_well_formed_ceiling_parses(self) -> None:
        from story_automator.core.budget_ceilings import (
            BudgetCeiling,
            parse_ceilings_config,
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "per_run_cap",
                        "window": "per_run",
                        "limit_usd": 25.0,
                        "warn_at": 0.8,
                        "gate_names": ["init", "story_start"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
            self.assertEqual(len(result), 1)
            self.assertIsInstance(result[0], BudgetCeiling)
            self.assertEqual(result[0].name, "per_run_cap")
            self.assertEqual(result[0].window, "per_run")
            self.assertEqual(result[0].limit_usd, 25.0)
            self.assertEqual(result[0].warn_at, 0.8)
            self.assertEqual(result[0].gate_names, ("init", "story_start"))

    def test_gate_names_become_tuple_not_list(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {
                        "name": "c1",
                        "window": "24h",
                        "limit_usd": 10.0,
                        "warn_at": 0.5,
                        "gate_names": ["init"],
                    }
                ],
            )
            result = parse_ceilings_config(path)
            self.assertIsInstance(result[0].gate_names, tuple)

    def test_multiple_ceilings_preserve_file_order(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "first", "window": "per_run", "limit_usd": 5.0,
                     "warn_at": 0.5, "gate_names": ["init"]},
                    {"name": "second", "window": "24h", "limit_usd": 10.0,
                     "warn_at": 0.6, "gate_names": ["story_start"]},
                    {"name": "third", "window": "7d", "limit_usd": 50.0,
                     "warn_at": 0.9, "gate_names": ["retry_start"]},
                ],
            )
            result = parse_ceilings_config(path)
            self.assertEqual([c.name for c in result], ["first", "second", "third"])

    def test_happy_path_leaves_parse_warnings_empty(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "c1", "window": "30d", "limit_usd": 100.0,
                     "warn_at": 0.75, "gate_names": ["init"]}
                ],
            )
            parse_ceilings_config(path)
        self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: 3 failures — `test_single_well_formed_ceiling_parses`, `test_gate_names_become_tuple_not_list`, and `test_multiple_ceilings_preserve_file_order` fail because `parse_ceilings_config` currently returns `[]` even on valid input. The fourth test (`test_happy_path_leaves_parse_warnings_empty`) passes trivially because the skeleton already calls `_PARSE_WARNINGS.clear()`.

- [ ] **Step 3: Implement the per-entry parser**

Edit `budget_ceilings.py`. Add the validation constants and the private validator:

```python
_VALID_WINDOWS: frozenset[str] = frozenset({"per_run", "24h", "7d", "30d"})
_REQUIRED_KEYS: tuple[str, ...] = (
    "name",
    "window",
    "limit_usd",
    "warn_at",
    "gate_names",
)


def _validate_ceiling_dict(index: int, raw: object) -> BudgetCeiling | None:
    """Validate one ceiling object; return ``None`` and record a warning
    if the entry is malformed (REQ-05).

    Validation covers: dict shape, presence of all five required keys,
    string type for ``name`` and ``window``, ``window`` membership in
    ``_VALID_WINDOWS``, numeric and strictly-positive ``limit_usd``,
    numeric ``warn_at`` in the half-open interval ``(0.0, 1.0]``, and
    ``gate_names`` being a list of strings.
    """
    if not isinstance(raw, dict):
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "not_object", "detail": type(raw).__name__}
        )
        return None
    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "missing_keys", "detail": ",".join(missing)}
        )
        return None
    name = raw["name"]
    window = raw["window"]
    limit_usd = raw["limit_usd"]
    warn_at = raw["warn_at"]
    gate_names = raw["gate_names"]
    if not isinstance(name, str) or not name:
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_name", "detail": repr(name)[:40]}
        )
        return None
    if not isinstance(window, str) or window not in _VALID_WINDOWS:
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_window", "detail": repr(window)[:40]}
        )
        return None
    if not isinstance(limit_usd, (int, float)) or isinstance(limit_usd, bool):
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_limit_usd_type",
             "detail": type(limit_usd).__name__}
        )
        return None
    if float(limit_usd) <= 0.0:
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_limit_usd_value",
             "detail": repr(limit_usd)[:40]}
        )
        return None
    if not isinstance(warn_at, (int, float)) or isinstance(warn_at, bool):
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_warn_at_type",
             "detail": type(warn_at).__name__}
        )
        return None
    warn_at_f = float(warn_at)
    if not (0.0 < warn_at_f <= 1.0):
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_warn_at_value",
             "detail": repr(warn_at)[:40]}
        )
        return None
    if not isinstance(gate_names, list) or not all(
        isinstance(g, str) for g in gate_names
    ):
        _PARSE_WARNINGS.append(
            {"index": str(index), "reason": "bad_gate_names",
             "detail": repr(gate_names)[:40]}
        )
        return None
    return BudgetCeiling(
        name=name,
        window=window,
        limit_usd=float(limit_usd),
        warn_at=warn_at_f,
        gate_names=tuple(gate_names),
    )
```

Replace the trailing `return []` in `parse_ceilings_config` with:

```python
    parsed: list[BudgetCeiling] = []
    for index, raw in enumerate(raw_ceilings):
        ceiling = _validate_ceiling_dict(index, raw)
        if ceiling is not None:
            parsed.append(ceiling)
    return parsed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (23 tests, 0 failures).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(budget-ceilings): parse well-formed ceilings preserving order (M03 REQ-03/04)"
```

---

## Task 8: `parse_ceilings_config` — malformed entries are skipped and warned

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` (no source change expected — should already pass)
- Test: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

Spec reference: REQ-05 / REQ-14 (config subset) — malformed entries are silently skipped while a structured warning is appended.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_budget_ceilings.py`:

```python
class ParseCeilingsConfigMalformedEntryTests(unittest.TestCase):
    def _write(self, tmp: str, ceilings: list[object]) -> Path:
        path = Path(tmp) / "workflow.json"
        path.write_text(
            compact_json({"policy": {"cost_ceilings": ceilings}}),
            encoding="utf-8",
        )
        return path

    def test_missing_required_key_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    # Missing 'warn_at'
                    {"name": "bad", "window": "per_run", "limit_usd": 10.0,
                     "gate_names": ["init"]},
                    # Good
                    {"name": "good", "window": "per_run", "limit_usd": 10.0,
                     "warn_at": 0.5, "gate_names": ["init"]},
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual([c.name for c in result], ["good"])
        self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 1)
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "missing_keys"
        )
        self.assertIn("warn_at", budget_ceilings._PARSE_WARNINGS[0]["detail"])

    def test_invalid_window_string_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "1h", "limit_usd": 10.0,
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_window")

    def test_negative_limit_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "per_run", "limit_usd": -1.0,
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_value"
        )

    def test_zero_limit_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "per_run", "limit_usd": 0.0,
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])

    def test_warn_at_out_of_range_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        cases = [0.0, -0.1, 1.5]
        for warn_at in cases:
            with self.subTest(warn_at=warn_at):
                with tempfile.TemporaryDirectory() as tmp:
                    path = self._write(
                        tmp,
                        [
                            {"name": "bad", "window": "per_run",
                             "limit_usd": 10.0, "warn_at": warn_at,
                             "gate_names": ["init"]}
                        ],
                    )
                    result = parse_ceilings_config(path)
                self.assertEqual(result, [])
                self.assertTrue(
                    budget_ceilings._PARSE_WARNINGS[0]["reason"].startswith(
                        "bad_warn_at"
                    )
                )

    def test_boundary_warn_at_one_is_allowed(self) -> None:
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "ok", "window": "per_run", "limit_usd": 10.0,
                     "warn_at": 1.0, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].warn_at, 1.0)

    def test_non_object_entry_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, ["not an object", 42, None])
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 3)
        for warning in budget_ceilings._PARSE_WARNINGS:
            self.assertEqual(warning["reason"], "not_object")

    def test_gate_names_must_be_list_of_strings(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "per_run", "limit_usd": 10.0,
                     "warn_at": 0.5, "gate_names": "init"},
                    {"name": "bad2", "window": "per_run", "limit_usd": 10.0,
                     "warn_at": 0.5, "gate_names": [1, 2]},
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        reasons = [w["reason"] for w in budget_ceilings._PARSE_WARNINGS]
        self.assertEqual(reasons, ["bad_gate_names", "bad_gate_names"])

    def test_warnings_cleared_on_each_call(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            bad_path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "nope", "limit_usd": 10.0,
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            parse_ceilings_config(bad_path)
            self.assertEqual(len(budget_ceilings._PARSE_WARNINGS), 1)

            good_path = Path(tmp) / "workflow2.json"
            good_path.write_text(
                compact_json(
                    {"policy": {"cost_ceilings": [
                        {"name": "ok", "window": "per_run", "limit_usd": 10.0,
                         "warn_at": 0.5, "gate_names": ["init"]}
                    ]}}
                ),
                encoding="utf-8",
            )
            parse_ceilings_config(good_path)
            self.assertEqual(budget_ceilings._PARSE_WARNINGS, [])

    def test_bool_is_not_accepted_as_limit_usd(self) -> None:
        """``True`` is an ``int`` in Python; the validator explicitly
        rejects bool to avoid silently coercing ``True`` to 1.0."""
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "per_run", "limit_usd": True,
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_type"
        )

    def test_string_limit_usd_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "per_run", "limit_usd": "10.0",
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_limit_usd_type"
        )

    def test_bool_is_not_accepted_as_warn_at(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "per_run", "limit_usd": 10.0,
                     "warn_at": True, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_warn_at_type"
        )

    def test_string_warn_at_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": "per_run", "limit_usd": 10.0,
                     "warn_at": "0.5", "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(
            budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_warn_at_type"
        )

    def test_non_string_name_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": 42, "window": "per_run", "limit_usd": 10.0,
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_name")

    def test_empty_string_name_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "", "window": "per_run", "limit_usd": 10.0,
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_name")

    def test_non_string_window_is_skipped(self) -> None:
        from story_automator.core import budget_ceilings
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "bad", "window": 42, "limit_usd": 10.0,
                     "warn_at": 0.5, "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(result, [])
        self.assertEqual(budget_ceilings._PARSE_WARNINGS[0]["reason"], "bad_window")

    def test_utf8_non_ascii_name_round_trips(self) -> None:
        """REQ-04 says UTF-8 reading; confirm non-ASCII names survive."""
        from story_automator.core.budget_ceilings import parse_ceilings_config

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                [
                    {"name": "ceiling-ünïcödé", "window": "per_run",
                     "limit_usd": 10.0, "warn_at": 0.5,
                     "gate_names": ["init"]}
                ],
            )
            result = parse_ceilings_config(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "ceiling-ünïcödé")
```

- [ ] **Step 2: Run tests to verify they pass**

The source already enforces every constraint (added in Task 7). Run to confirm.

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (33+ tests, 0 failures). If any test fails, fix the validator in Task 7's source until green.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): cover malformed entry skipping and warnings (M03 REQ-05/14)"
```

---

## Task 9: REQ-15 wire-format fidelity test — ledger fixture round-trips through `compact_json`

**Files:**
- Modify: `skills/bmad-story-automator/tests/test_budget_ceilings.py`

Spec reference: REQ-15 — test fixtures must compose concrete M01 event instances and serialize through `compact_json` so the wire format under test matches M02. The evaluator does not exist yet, but the spec requires the fixture-building **convention** to be established now so M03-M2 inherits a working pattern.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_budget_ceilings.py`:

```python
class LedgerFixturePatternTests(unittest.TestCase):
    """REQ-15: fixtures must be built by serializing M01 event instances
    through ``compact_json``. This sub-milestone has no evaluator yet,
    but the fixture-building utility is exercised here so M03-M2 can
    rely on it. The test asserts only that the fixture round-trips
    through ``parse_event`` — no ceiling evaluation runs."""

    def test_event_fixture_round_trips_via_compact_json(self) -> None:
        from story_automator.core.telemetry_events import (
            StoryCompleted,
            parse_event,
        )

        event = StoryCompleted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="r1",
            epic="E1",
            story_key="S1",
            duration_s=1.0,
            cost_usd=0.25,
            tokens_in=10,
            tokens_out=10,
            attempts=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            ensure_dir(tmp)
            ledger = Path(tmp) / "events.jsonl"
            line = compact_json(event.to_dict())
            ledger.write_text(line + "\n", encoding="utf-8")

            with ledger.open("r", encoding="utf-8") as handle:
                first = handle.readline().rstrip("\n")
            parsed = parse_event(first)
        self.assertEqual(parsed.run_id, "r1")
        self.assertEqual(getattr(parsed, "cost_usd"), 0.25)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_budget_ceilings -v`
Expected: PASS (34+ tests, 0 failures). This test depends only on M01 code that already exists.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(budget-ceilings): establish REQ-15 ledger-fixture pattern via compact_json"
```

---

## Task 10: Quality-gate sweep — lint, format, import-allowlist grep, line count, compile

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` (formatting only)
- Modify: `skills/bmad-story-automator/tests/test_budget_ceilings.py` (formatting only)

Spec reference: Quality-gates section — `ruff check`, `ruff format --check`, import-allowlist grep, `wc -l <= 500`, `python -m compileall`, determinism considerations.

- [ ] **Step 1: Run ruff lint**

Run: `python -m ruff check skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py skills/bmad-story-automator/tests/test_budget_ceilings.py`
Expected: exits 0 with no warnings. If anything fires, fix it directly (likely candidates: unused imports, missing blank lines).

- [ ] **Step 2: Run ruff format check**

Run: `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py skills/bmad-story-automator/tests/test_budget_ceilings.py`
Expected: exits 0. If it reports changes, run `python -m ruff format <paths>` and commit the formatting separately.

- [ ] **Step 3: Import-allowlist grep**

The allowlist forbids `requests`, `httpx`, `aiohttp`, `subprocess`, `os.system`, `filelock`, and `psutil` in `core/budget_ceilings.py`.

Use the Grep tool (or `python -m grep` if not available) to run pattern `requests|httpx|aiohttp|subprocess|os\.system|filelock|psutil` over the source file.

Expected: zero matches. If something fires, the source must be refactored to use stdlib only.

- [ ] **Step 4: Line count check**

Run (cross-platform via Python so it works on git-bash and PowerShell):

```bash
python -c "import sys; print(sum(1 for _ in open('skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py', encoding='utf-8')))"
python -c "import sys; print(sum(1 for _ in open('skills/bmad-story-automator/tests/test_budget_ceilings.py', encoding='utf-8')))"
```

Expected: both values <= 500. (Realistic targets: source ~140 LOC, tests ~400 LOC.)

- [ ] **Step 5: Compile gate**

Run: `python -m compileall skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
Expected: exits 0. (Syntax-warnings-as-errors gate.)

- [ ] **Step 6: Full test sweep + targeted coverage**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v`
Expected: PASS (entire suite, including pre-existing M01/M02 tests).

Run (single chained command, matching the spec's quality gate literally):

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run -m unittest tests.test_budget_ceilings && \
  python -m coverage report -m --fail-under=85 --include="*/core/budget_ceilings.py"
```

Expected: coverage >= 85% on `budget_ceilings.py`. Below 85% means a validator branch (one of `bad_name`, `bad_window`, `bad_limit_usd_type`, `bad_limit_usd_value`, `bad_warn_at_type`, `bad_warn_at_value`, `bad_gate_names`, `not_object`, `missing_keys`) lacks a test — add one and re-run.

- [ ] **Step 7: Commit (formatting only, if anything changed)**

If `ruff format` modified the files:

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py \
        skills/bmad-story-automator/tests/test_budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(budget-ceilings): apply ruff format"
```

Otherwise, skip the commit step.

---

## Task 11: Final review — `_PARSE_WARNINGS` is intentionally module-private; document the export contract

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`

This is a docstring-only tidy step to remind future readers (and the M03-M2 author) that `_PARSE_WARNINGS` is intentionally not in `__all__`, that `BudgetCeiling` is `kw_only=True` to prevent accidental positional construction, and that the evaluator lives in M03-M2.

- [ ] **Step 1: Final source review**

Open `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` and confirm:
- File begins with `from __future__ import annotations` as the first non-comment statement (REQ-01).
- `__all__` lists exactly `["BudgetCeiling", "CeilingDecision", "parse_ceilings_config"]`. `_PARSE_WARNINGS`, `_VALID_WINDOWS`, `_REQUIRED_KEYS`, and `_validate_ceiling_dict` are intentionally absent — they are inspection hooks and internal helpers, not stable exports.
- No imports from `filelock`, `psutil`, `subprocess`, `os.system`, `requests`, `httpx`, `aiohttp`.
- All union type hints use PEP 604 (`str | Path`, never `Optional[Path]`).
- Module docstring states out-of-scope items (evaluator, bypass helper, gate wiring).

Open `skills/bmad-story-automator/tests/test_budget_ceilings.py` and confirm:
- File begins with `from __future__ import annotations` as the first non-comment statement (REQ-01).
- Every test class subclasses `unittest.TestCase` (REQ-14 baseline).
- Imports of `compact_json` and `ensure_dir` come from `story_automator.core.common` (REQ-15), not duplicated.

Cement REQ-01 with an automated check that tolerates the existing
project convention of a module docstring preceding the future import
(see `telemetry_events.py` for the precedent). Append to the test file:

```python
class SpecReq01PreludeTests(unittest.TestCase):
    """REQ-01: both new files must declare
    ``from __future__ import annotations``. The existing project
    convention (see core/telemetry_events.py) places the module
    docstring before the future import; this test tolerates a
    docstring prelude but rejects any executable code between the
    docstring and the future import."""

    def _has_future_import_after_optional_docstring(self, src: str) -> bool:
        import ast

        tree = ast.parse(src)
        body = tree.body
        # Skip leading docstring (a single Expr node wrapping a Str
        # constant at index 0).
        first = body[0] if body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            body = body[1:]
        # The next statement must be the __future__ import.
        if not body:
            return False
        head = body[0]
        if not isinstance(head, ast.ImportFrom):
            return False
        return head.module == "__future__" and any(
            alias.name == "annotations" for alias in head.names
        )

    def test_source_file_has_future_annotations(self) -> None:
        src_path = (
            Path(__file__).resolve().parents[1]
            / "src" / "story_automator" / "core" / "budget_ceilings.py"
        )
        self.assertTrue(
            self._has_future_import_after_optional_docstring(
                src_path.read_text(encoding="utf-8")
            ),
            f"REQ-01 violated for {src_path}",
        )

    def test_test_file_has_future_annotations(self) -> None:
        test_path = Path(__file__).resolve()
        self.assertTrue(
            self._has_future_import_after_optional_docstring(
                test_path.read_text(encoding="utf-8")
            ),
            f"REQ-01 violated for {test_path}",
        )
```

Update the module docstring to its final form if anything drifted:

```python
"""Budget ceiling data types and config reader (M03 sub-milestone M1).

Ships the data substrate of M03 budget enforcement: the
``CeilingDecision`` enum (REQ-02), the ``BudgetCeiling`` dataclass
(REQ-03), and the tolerant ``parse_ceilings_config`` reader
(REQ-04 / REQ-05). The reader is intentionally forgiving — every
malformed shape (missing file, missing keys, malformed entry) returns
an empty list or skips the entry while appending a structured warning
to the module-private ``_PARSE_WARNINGS`` list (cleared on every
call). The list is not in ``__all__`` and is not part of the stable
public surface — it exists so test code and downstream callers can
inspect why ceilings were dropped.

Out of scope for this sub-milestone: ``evaluate_ceilings``,
``bypass_allowed``, the wire-up to ``sw cli ceiling-check``, the
ten-line BMAD step insertions, and the ledger-streaming summation.
Those land in M03-M2 (evaluator) and M03-M3 (BMAD wiring).
"""
```

- [ ] **Step 2: Run final quality gate sweep**

Run the full test suite plus ruff:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v
python -m ruff check skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py skills/bmad-story-automator/tests/test_budget_ceilings.py
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py skills/bmad-story-automator/tests/test_budget_ceilings.py
```

Expected: everything green.

- [ ] **Step 3: Commit the documentation refresh (if changed)**

```bash
git add skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(budget-ceilings): finalize module docstring and out-of-scope notes"
```

---

## Coverage map

| Requirement | Tasks |
|---|---|
| REQ-01 (file paths, `from __future__ import annotations`) | 1, 11 |
| REQ-02 (`CeilingDecision` enum) | 2 |
| REQ-03 (`BudgetCeiling` dataclass, kw_only, field set) | 3, 7 |
| REQ-04 (`parse_ceilings_config` happy + tolerant) | 5, 6, 7 |
| REQ-05 (malformed entries skipped + `_PARSE_WARNINGS`) | 4, 7, 8 |
| REQ-14 (config subset: malformed-entry tests) | 8 |
| REQ-15 (test fixtures via `compact_json` + M01 events) | 9 |
| Quality gates (ruff, line count, compile, coverage) | 10 |
| Module docstring / scope notes | 11 |

## Out-of-scope for this sub-milestone (deliberate)

- `evaluate_ceilings()` — M03-M2.
- `bypass_allowed()` — M03-M2.
- Ledger streaming + window summation — M03-M2.
- Severity-rank merging across multiple ceilings — M03-M2.
- `sw cli ceiling-check` subcommand + BMAD step markdown insertions — M03-M3.
- HMAC audit log integration — M04, owned by separate spec.
- Determinism gate (100-call byte-identical replay) — M03-M2 (no evaluator yet).
