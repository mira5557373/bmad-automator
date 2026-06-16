# M06a Layer 3 — Feature Tester Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `core/feature_tester.py` (M06a Layer 3) that, for each `implemented` REQ verdict from Layer 2, either locates an existing feature test in `tests/test_compliance_*.py` whose docstring/comments cite the REQ id, or writes a minimal failing-skeleton `unittest.TestCase` so the next TDD pass has something to fill in.

**Architecture:** A single stdlib-only module that exposes one frozen `TestPlanEntry` dataclass and one `plan_feature_tests` entry point. The module is decoupled from Layer 1 (`gap_validator`) and Layer 2 (`spec_compliance`) at *runtime*: a structural `Protocol` (`ReqVerdictLike`) describes the duck-typed input, and the real `ReqVerdict` is referenced only inside `if TYPE_CHECKING:` so `from story_automator.core import feature_tester` never imports `spec_compliance`. The skeleton template is a single module-level constant rendered with `str.format` from a frozen golden string; the test file asserts byte-equality against a golden literal to catch accidental template drift.

**Tech Stack:** Python 3.11+ stdlib only (`dataclasses`, `pathlib`, `logging`, `re`, `typing`). Atomic writes go through `story_automator.core.atomic_io.write_atomic_text` (which is the actual exported name — the spec REQ-13 says "`atomic_write`" but no such symbol exists in `atomic_io.py`; the diff is restricted to `feature_tester.py` and its test file so we use `write_atomic_text`). Tests use `unittest.TestCase` + `tempfile.TemporaryDirectory`.

**Spec & dependencies:**
- Spec: `docs/superpowers/specs/2026-06-14-m06a-trust-verify-python.md` (REQ-12 through REQ-16 + NFRs + quality gates).
- Upstream (read-only): `core/spec_compliance.py` (`ReqVerdict` shape — `req_id: str`, `status: Literal["implemented", "missing", "partial"]`, `evidence: str`, `confidence: float`).
- Upstream (call): `core/atomic_io.write_atomic_text(path: Path, data: str, *, encoding: str = "utf-8") -> None`.

**Diff envelope (quality-gate):** only `skills/bmad-story-automator/src/story_automator/core/feature_tester.py` and `tests/test_feature_tester.py` may change.

---

## File structure

| File | Responsibility | Lines (est.) |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/feature_tester.py` | `TestPlanEntry` dataclass, `ReqVerdictLike` Protocol, `_normalize_req_id`, `_SKELETON_TEMPLATE`, `_render_skeleton`, `_find_existing_test`, `_plan_for_verdict`, `plan_feature_tests` | ~180 |
| `tests/test_feature_tester.py` | Unit tests covering REQ-12 to REQ-16, golden-string byte-equality, import contract, dry-run, status filtering, search hit/miss, idempotency. | ~350 |

**No other files are modified.** This is a hard quality-gate constraint.

---

## Skeleton template (golden string)

The skeleton file body, used both by `_render_skeleton` (with `{req_id}`, `{req_id_lower_underscored}`, `{class_suffix}` substituted) and by the test file's golden assertion:

```python
"""Feature test for {req_id}."""

from __future__ import annotations

import unittest


class TestCompliance{class_suffix}(unittest.TestCase):
    """{req_id}: skeleton — fill in once the feature is wired."""

    def test_{req_id_lower_underscored}_skeleton(self) -> None:
        self.fail("{req_id} not yet covered by feature test")
```

**Normalization rules** (applied by `_normalize_req_id`):
- Input must match `re.fullmatch(r"REQ-\d+", req_id)`; otherwise raise `ValueError`.
- `req_id_lower_underscored = req_id.lower().replace("-", "_")` → `"req-07" → "req_07"`.
- `class_suffix = req_id.replace("-", "_")` → `"REQ-07" → "REQ_07"`, yielding `TestComplianceREQ_07`.
- File name written: `test_compliance_{req_id_lower_underscored}.py`, e.g. `test_compliance_req_07.py`.

**Existing-test search rule** (REQ-13):
- Glob `tests_dir / "test_compliance_*.py"`.
- For each matching file, read text (UTF-8) and treat as a hit if the literal token `req_id` (e.g. `"REQ-07"`) appears anywhere in the file (docstring, comment, identifier — spec says "docstring or comment matching the REQ id"; we accept any literal occurrence because Python parsing would be overkill and the file naming + literal-substring check is the documented contract).
- First hit wins (deterministic, lexicographic sort by `Path.name`).

---

## Task 1: Author the failing module-import contract tests (REQ-16)

**Files:**
- Create: `tests/test_feature_tester.py`

- [ ] **Step 1: Write the failing tests** (paste these as the file's complete initial body — they import a module that doesn't exist yet so they will fail at collection time, which is exactly what we want for the first iteration).

```python
from __future__ import annotations

import dataclasses
import importlib
import io
import logging
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from story_automator.core.feature_tester import TestPlanEntry


class ModuleImportContractTests(unittest.TestCase):
    """REQ-16: importable in any order, no import-time side effects beyond
    logging.getLogger(__name__), declares __all__."""

    def test_module_imports_cleanly(self) -> None:
        from story_automator.core import feature_tester  # noqa: F401

    def test_module_declares_all(self) -> None:
        from story_automator.core import feature_tester

        self.assertEqual(
            sorted(feature_tester.__all__),
            sorted(["TestPlanEntry", "plan_feature_tests"]),
        )

    def test_import_has_no_stdout_or_stderr_side_effects(self) -> None:
        sys.modules.pop("story_automator.core.feature_tester", None)
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = captured_out, captured_err
        try:
            from story_automator.core import feature_tester  # noqa: F401
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        self.assertEqual(captured_out.getvalue(), "")
        self.assertEqual(captured_err.getvalue(), "")

    def test_module_has_named_logger(self) -> None:
        from story_automator.core import feature_tester

        self.assertIsInstance(feature_tester.logger, logging.Logger)
        self.assertEqual(
            feature_tester.logger.name,
            "story_automator.core.feature_tester",
        )

    def test_module_does_not_import_spec_compliance_at_runtime(self) -> None:
        """REQ-16 / quality gate: no runtime cross-layer imports."""
        sys.modules.pop("story_automator.core.feature_tester", None)
        sys.modules.pop("story_automator.core.spec_compliance", None)
        from story_automator.core import feature_tester  # noqa: F401

        self.assertNotIn("story_automator.core.spec_compliance", sys.modules)

    def test_module_does_not_import_gap_validator_at_runtime(self) -> None:
        sys.modules.pop("story_automator.core.feature_tester", None)
        sys.modules.pop("story_automator.core.gap_validator", None)
        from story_automator.core import feature_tester  # noqa: F401

        self.assertNotIn("story_automator.core.gap_validator", sys.modules)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'story_automator.core.feature_tester'`.

- [ ] **Step 3: Create the minimal module skeleton**

Create `skills/bmad-story-automator/src/story_automator/core/feature_tester.py`:

```python
"""Layer 3 of the M06a trust-but-verify stack: feature-test planning.

For each `implemented` REQ verdict produced by Layer 2
(`core/spec_compliance.py`), this module either locates an existing
feature test in `tests/test_compliance_*.py` whose docstring or
comments cite the REQ id, or writes a minimal failing-skeleton
`unittest.TestCase` file so the next TDD pass has somewhere to start.

Layer 3 is intentionally decoupled from Layer 1 (`gap_validator.py`)
and Layer 2 (`spec_compliance.py`): the only runtime cross-module
dependency is `core.atomic_io.write_atomic_text`. The shape of the
input verdict list is described by the structural `ReqVerdictLike`
Protocol; the concrete `ReqVerdict` from Layer 2 is referenced only
inside `if TYPE_CHECKING:` so importing this module never transitively
loads `spec_compliance.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from story_automator.core.atomic_io import write_atomic_text

if TYPE_CHECKING:
    from story_automator.core.spec_compliance import ReqVerdict  # noqa: F401

__all__ = [
    "TestPlanEntry",
    "plan_feature_tests",
]

logger = logging.getLogger(__name__)
```

- [ ] **Step 4: Run tests to verify import contract passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.ModuleImportContractTests -v`
Expected: PASS for `test_module_imports_cleanly`, `test_import_has_no_stdout_or_stderr_side_effects`, `test_module_has_named_logger`, `test_module_does_not_import_spec_compliance_at_runtime`, `test_module_does_not_import_gap_validator_at_runtime`. FAIL for `test_module_declares_all` (the `__all__` mentions `TestPlanEntry` and `plan_feature_tests` which don't exist as objects yet — but `__all__` itself is a list of strings so this test actually PASSES). All six should be green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_feature_tester.py skills/bmad-story-automator/src/story_automator/core/feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(feature_tester): module import contract (REQ-16)"
```

---

## Task 2: Add `TestPlanEntry` frozen kw_only dataclass (REQ-12)

**Files:**
- Modify: `tests/test_feature_tester.py` (append new test class)
- Modify: `skills/bmad-story-automator/src/story_automator/core/feature_tester.py` (add dataclass)

- [ ] **Step 1: Append the failing test class to `tests/test_feature_tester.py`** (above the `if __name__ == "__main__"` guard):

```python
class TestPlanEntryDataclassTests(unittest.TestCase):
    """REQ-12: frozen kw_only @dataclass with four fields."""

    def test_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        self.assertTrue(dataclasses.is_dataclass(TestPlanEntry))
        params = TestPlanEntry.__dataclass_params__  # type: ignore[attr-defined]
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_does_not_subclass_other_dataclass(self) -> None:
        """NFR: dataclasses must not subclass other dataclasses."""
        from story_automator.core.feature_tester import TestPlanEntry

        for base in TestPlanEntry.__mro__[1:]:
            if base is object:
                continue
            self.assertFalse(
                dataclasses.is_dataclass(base),
                f"{TestPlanEntry.__name__} must not subclass dataclass {base.__name__}",
            )

    def test_has_required_fields(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        field_map = {f.name: f.type for f in dataclasses.fields(TestPlanEntry)}
        self.assertEqual(
            set(field_map),
            {"req_id", "existing_test_path", "created_test_path", "action"},
        )

    def test_positional_construction_rejected(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        with self.assertRaises(TypeError):
            TestPlanEntry("REQ-07", None, None, "found")  # type: ignore[misc]

    def test_kw_construction_round_trips(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        entry = TestPlanEntry(
            req_id="REQ-07",
            existing_test_path="tests/test_compliance_req_07.py",
            created_test_path=None,
            action="found",
        )
        self.assertEqual(entry.req_id, "REQ-07")
        self.assertEqual(entry.action, "found")

    def test_frozen_rejects_attribute_assignment(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        entry = TestPlanEntry(
            req_id="REQ-07",
            existing_test_path=None,
            created_test_path="tests/test_compliance_req_07.py",
            action="created",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            entry.action = "skipped"  # type: ignore[misc]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.TestPlanEntryDataclassTests -v`
Expected: FAIL with `ImportError: cannot import name 'TestPlanEntry'`.

- [ ] **Step 3: Add the dataclass to `feature_tester.py`** (insert after the `logger = ...` line and before any helper, but after `__all__`):

```python
@dataclass(frozen=True, kw_only=True)
class TestPlanEntry:
    """One row of the feature-test plan: what to do for a single REQ.

    Preconditions: `req_id` is a non-empty string matching ``REQ-\\d+``
        (the regex is enforced by `plan_feature_tests`, not by this
        dataclass itself); `action` is exactly one of "found", "created",
        "skipped"; when `action == "found"`, `existing_test_path` is the
        absolute string path of the located test file and
        `created_test_path` is `None`; when `action == "created"`,
        `existing_test_path` is `None` and `created_test_path` is the
        absolute string path of the freshly written skeleton; when
        `action == "skipped"`, `existing_test_path` is `None` and
        `created_test_path` is the absolute string path that *would*
        have been written had `dry_run=False`.
    Postconditions: instance is frozen; all four fields are present.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    req_id: str
    existing_test_path: str | None
    created_test_path: str | None
    action: Literal["found", "created", "skipped"]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.TestPlanEntryDataclassTests -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_feature_tester.py skills/bmad-story-automator/src/story_automator/core/feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(feature_tester): TestPlanEntry frozen kw_only dataclass (REQ-12)"
```

---

## Task 3: Add `_normalize_req_id` helper with validation

**Files:**
- Modify: `tests/test_feature_tester.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/feature_tester.py`

Rationale: Normalization is the foundation for the skeleton render, the file-name choice, and the existing-test search. Isolating it as a unit-testable helper keeps the downstream tasks small.

- [ ] **Step 1: Append the failing test class**

```python
class NormalizeReqIdTests(unittest.TestCase):
    """Internal helper: normalizes REQ-NN into its three rendered forms."""

    def test_normalizes_well_formed_id(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        underscored_lower, class_suffix = _normalize_req_id("REQ-07")
        self.assertEqual(underscored_lower, "req_07")
        self.assertEqual(class_suffix, "REQ_07")

    def test_normalizes_multi_digit_id(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        underscored_lower, class_suffix = _normalize_req_id("REQ-123")
        self.assertEqual(underscored_lower, "req_123")
        self.assertEqual(class_suffix, "REQ_123")

    def test_rejects_lowercase_prefix(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        with self.assertRaises(ValueError) as ctx:
            _normalize_req_id("req-07")
        self.assertIn("REQ-", str(ctx.exception))

    def test_rejects_missing_dash(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        with self.assertRaises(ValueError):
            _normalize_req_id("REQ07")

    def test_rejects_empty_string(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        with self.assertRaises(ValueError):
            _normalize_req_id("")

    def test_rejects_trailing_whitespace(self) -> None:
        from story_automator.core.feature_tester import _normalize_req_id

        with self.assertRaises(ValueError):
            _normalize_req_id("REQ-07 ")
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.NormalizeReqIdTests -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the helper to `feature_tester.py`** (insert after the `TestPlanEntry` definition, add `import re` to the import block at the top):

```python
import re
```

```python
_REQ_ID_RE: re.Pattern[str] = re.compile(r"REQ-\d+")


def _normalize_req_id(req_id: str) -> tuple[str, str]:
    """Return ``(req_id_lower_underscored, class_suffix)`` for a REQ id.

    Preconditions: `req_id` matches ``re.fullmatch(r"REQ-\\d+", req_id)``
        exactly — leading/trailing whitespace, lowercase prefixes, and
        missing dashes are all rejected.
    Postconditions: returns a 2-tuple of strings; the first replaces the
        dash with an underscore and lowercases the whole string (for
        method names and file names), the second only replaces the dash
        with an underscore (for class name suffixes).
    Raises: ValueError if the input does not match the required pattern.
    """
    if not _REQ_ID_RE.fullmatch(req_id):
        raise ValueError(
            f"req_id must match 'REQ-<digits>'; got {req_id!r}"
        )
    return req_id.lower().replace("-", "_"), req_id.replace("-", "_")
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.NormalizeReqIdTests -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_feature_tester.py skills/bmad-story-automator/src/story_automator/core/feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(feature_tester): _normalize_req_id helper with strict validation"
```

---

## Task 4: Add the skeleton template constant + golden-string render test (REQ-14 + quality gate)

**Files:**
- Modify: `tests/test_feature_tester.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/feature_tester.py`

- [ ] **Step 1: Append the failing test class**

```python
# Golden skeleton for REQ-07. ANY change to _SKELETON_TEMPLATE must
# update this string verbatim — that's the entire point of the
# byte-equality assertion.
_GOLDEN_SKELETON_REQ_07 = (
    '"""Feature test for REQ-07."""\n'
    "\n"
    "from __future__ import annotations\n"
    "\n"
    "import unittest\n"
    "\n"
    "\n"
    "class TestComplianceREQ_07(unittest.TestCase):\n"
    '    """REQ-07: skeleton — fill in once the feature is wired."""\n'
    "\n"
    "    def test_req_07_skeleton(self) -> None:\n"
    '        self.fail("REQ-07 not yet covered by feature test")\n'
)


class SkeletonRenderGoldenTests(unittest.TestCase):
    """REQ-14 + quality gate: byte-equality against a frozen golden string."""

    def test_render_matches_golden_for_req_07(self) -> None:
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-07")
        self.assertEqual(rendered, _GOLDEN_SKELETON_REQ_07)

    def test_render_contains_req_id_verbatim_in_class_docstring(self) -> None:
        """REQ-14: must place the REQ id verbatim in the class docstring."""
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-123")
        # The class docstring is the line beginning with `    """REQ-`
        self.assertIn('    """REQ-123: ', rendered)

    def test_render_imports_future_annotations(self) -> None:
        """REQ-14: must import from __future__ import annotations."""
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-07")
        self.assertIn("from __future__ import annotations\n", rendered)

    def test_render_calls_self_fail_with_exact_message(self) -> None:
        """REQ-14: body is exactly self.fail("REQ-NN not yet covered ...")."""
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-42")
        self.assertIn(
            '        self.fail("REQ-42 not yet covered by feature test")\n',
            rendered,
        )

    def test_render_method_name_uses_lower_underscored_id(self) -> None:
        from story_automator.core.feature_tester import _render_skeleton

        rendered = _render_skeleton("REQ-42")
        self.assertIn("    def test_req_42_skeleton(self) -> None:\n", rendered)

    def test_render_rejects_malformed_req_id(self) -> None:
        from story_automator.core.feature_tester import _render_skeleton

        with self.assertRaises(ValueError):
            _render_skeleton("not-a-req")
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.SkeletonRenderGoldenTests -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the template + render helper to `feature_tester.py`** (after `_normalize_req_id`):

```python
_SKELETON_TEMPLATE: str = (
    '"""Feature test for {req_id}."""\n'
    "\n"
    "from __future__ import annotations\n"
    "\n"
    "import unittest\n"
    "\n"
    "\n"
    "class TestCompliance{class_suffix}(unittest.TestCase):\n"
    '    """{req_id}: skeleton — fill in once the feature is wired."""\n'
    "\n"
    "    def test_{req_id_lower_underscored}_skeleton(self) -> None:\n"
    '        self.fail("{req_id} not yet covered by feature test")\n'
)


def _render_skeleton(req_id: str) -> str:
    """Render the skeleton test file body for `req_id`.

    Preconditions: `req_id` matches ``REQ-\\d+``.
    Postconditions: returns a UTF-8 string with LF line endings;
        byte-equal to a frozen golden test for ``REQ-07``.
    Raises: ValueError when `req_id` is malformed
        (propagated from `_normalize_req_id`).
    """
    req_id_lower_underscored, class_suffix = _normalize_req_id(req_id)
    return _SKELETON_TEMPLATE.format(
        req_id=req_id,
        req_id_lower_underscored=req_id_lower_underscored,
        class_suffix=class_suffix,
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.SkeletonRenderGoldenTests -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_feature_tester.py skills/bmad-story-automator/src/story_automator/core/feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(feature_tester): skeleton template with golden-string render (REQ-14)"
```

---

## Task 5: Add `_find_existing_test` helper (REQ-13 search half)

**Files:**
- Modify: `tests/test_feature_tester.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/feature_tester.py`

- [ ] **Step 1: Append the failing test class**

```python
class FindExistingTestTests(unittest.TestCase):
    """REQ-13: searches `tests/test_compliance_*.py` for a docstring or
    comment matching the REQ id."""

    def _write(self, dir_path: Path, name: str, body: str) -> Path:
        target = dir_path / name
        target.write_text(body, encoding="utf-8")
        return target

    def test_returns_none_when_dir_missing(self) -> None:
        from story_automator.core.feature_tester import _find_existing_test

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist"
            self.assertIsNone(_find_existing_test(missing, "REQ-07"))

    def test_returns_none_when_no_matching_file(self) -> None:
        from story_automator.core.feature_tester import _find_existing_test

        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                Path(tmp), "test_compliance_req_99.py", '"""REQ-99 done."""'
            )
            self.assertIsNone(_find_existing_test(Path(tmp), "REQ-07"))

    def test_finds_match_in_docstring(self) -> None:
        from story_automator.core.feature_tester import _find_existing_test

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                Path(tmp),
                "test_compliance_req_07.py",
                '"""REQ-07 happy-path test."""\n',
            )
            found = _find_existing_test(Path(tmp), "REQ-07")
            self.assertEqual(found, str(path.resolve()))

    def test_finds_match_in_comment(self) -> None:
        from story_automator.core.feature_tester import _find_existing_test

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                Path(tmp),
                "test_compliance_misc.py",
                "# REQ-07 covered here\nimport unittest\n",
            )
            found = _find_existing_test(Path(tmp), "REQ-07")
            self.assertEqual(found, str(path.resolve()))

    def test_only_searches_test_compliance_glob(self) -> None:
        from story_automator.core.feature_tester import _find_existing_test

        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                Path(tmp),
                "test_other_req_07.py",
                '"""REQ-07 lives in the wrong file."""\n',
            )
            self.assertIsNone(_find_existing_test(Path(tmp), "REQ-07"))

    def test_first_hit_is_deterministic_by_lex_order(self) -> None:
        from story_automator.core.feature_tester import _find_existing_test

        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                Path(tmp), "test_compliance_b.py", '"""REQ-07 in B."""\n'
            )
            first = self._write(
                Path(tmp), "test_compliance_a.py", '"""REQ-07 in A."""\n'
            )
            found = _find_existing_test(Path(tmp), "REQ-07")
            self.assertEqual(found, str(first.resolve()))

    def test_skips_files_with_partial_substring_collisions(self) -> None:
        """A file containing 'REQ-070' must NOT match a search for 'REQ-07'."""
        from story_automator.core.feature_tester import _find_existing_test

        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                Path(tmp),
                "test_compliance_req_070.py",
                '"""REQ-070 unrelated."""\n',
            )
            self.assertIsNone(_find_existing_test(Path(tmp), "REQ-07"))
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.FindExistingTestTests -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Add the helper to `feature_tester.py`** (after `_render_skeleton`):

```python
def _find_existing_test(tests_dir: Path, req_id: str) -> str | None:
    """Return the resolved absolute path of the first `test_compliance_*.py`
    file under `tests_dir` whose contents contain `req_id` as a whole token,
    or ``None`` when no such file exists.

    Preconditions: `req_id` matches ``REQ-\\d+``; `tests_dir` may or may
        not exist (a missing directory yields ``None``).
    Postconditions: scans files matching ``test_compliance_*.py`` in
        lexicographic order; returns the first whose UTF-8 contents
        contain `req_id` bounded by non-word characters (so ``REQ-07``
        does NOT match a file mentioning ``REQ-070``).
    Raises: nothing — file-read errors propagate naturally as ``OSError``.
    """
    if not tests_dir.exists():
        return None
    needle = re.compile(rf"(?<!\w){re.escape(req_id)}(?!\w)")
    for path in sorted(tests_dir.glob("test_compliance_*.py")):
        if needle.search(path.read_text(encoding="utf-8")):
            return str(path.resolve())
    return None
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.FindExistingTestTests -v`
Expected: all 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_feature_tester.py skills/bmad-story-automator/src/story_automator/core/feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(feature_tester): _find_existing_test with word-boundary match (REQ-13)"
```

---

## Task 6: Add `ReqVerdictLike` Protocol so `plan_feature_tests` is duck-typed

**Files:**
- Modify: `tests/test_feature_tester.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/feature_tester.py`

- [ ] **Step 1: Append the failing test class**

```python
class ReqVerdictLikeProtocolTests(unittest.TestCase):
    """Quality gate: runtime independence from spec_compliance preserved by
    structural Protocol matching."""

    def test_protocol_is_runtime_checkable(self) -> None:
        from story_automator.core.feature_tester import ReqVerdictLike

        # runtime_checkable is required so isinstance() checks work in tests
        # without importing the concrete ReqVerdict.
        self.assertTrue(hasattr(ReqVerdictLike, "_is_runtime_protocol"))

    def test_protocol_accepts_a_duck_typed_object(self) -> None:
        from story_automator.core.feature_tester import ReqVerdictLike

        class FakeVerdict:
            req_id = "REQ-07"
            status = "implemented"
            evidence = "anything"
            confidence = 0.9

        self.assertIsInstance(FakeVerdict(), ReqVerdictLike)

    def test_protocol_accepts_real_req_verdict_from_layer_2(self) -> None:
        """Bridge sanity: the concrete ReqVerdict is shape-compatible."""
        from story_automator.core.feature_tester import ReqVerdictLike
        from story_automator.core.spec_compliance import ReqVerdict

        verdict = ReqVerdict(
            req_id="REQ-07",
            status="implemented",
            evidence="x",
            confidence=0.9,
        )
        self.assertIsInstance(verdict, ReqVerdictLike)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.ReqVerdictLikeProtocolTests -v`
Expected: FAIL with `ImportError: cannot import name 'ReqVerdictLike'`.

- [ ] **Step 3: Add the Protocol to `feature_tester.py`** (after `__all__`, before `TestPlanEntry`; add `runtime_checkable` to the `typing` import). Also extend `__all__` to include the Protocol so callers can `isinstance`-check externally.

Update the import line:
```python
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable
```

Leave `__all__` unchanged — `ReqVerdictLike` is intentionally NOT in `__all__`. REQ-16 says `__all__` lists "exactly the public dataclasses and entry-point functions"; a Protocol is neither, so we keep it importable (`from story_automator.core.feature_tester import ReqVerdictLike` still works) but not re-exported.

Add the Protocol (using bare attribute annotations — the cleanest `runtime_checkable` form, no empty method bodies for mypy/ruff to complain about):
```python
@runtime_checkable
class ReqVerdictLike(Protocol):
    """Structural shape of a single REQ verdict.

    Preconditions: implementing object exposes `req_id` (str), `status`
        (str — typically Literal["implemented", "missing", "partial"]),
        `evidence` (str), and `confidence` (float) as readable attributes.
    Postconditions: this is a `runtime_checkable` Protocol so
        ``isinstance(obj, ReqVerdictLike)`` returns True for any object
        carrying those four attributes.
    Raises: nothing — Protocols are passive.

    This Protocol exists to keep `feature_tester` runtime-independent
    of `spec_compliance`: Layer 3 never imports `ReqVerdict` at runtime
    (only inside ``if TYPE_CHECKING:`` for type-checker assistance).
    """

    req_id: str
    status: str
    evidence: str
    confidence: float
```

Do NOT change the `__all__` assertion from Task 1; `ReqVerdictLike` is deliberately omitted.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.ReqVerdictLikeProtocolTests tests.test_feature_tester.ModuleImportContractTests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_feature_tester.py skills/bmad-story-automator/src/story_automator/core/feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(feature_tester): ReqVerdictLike Protocol preserves runtime independence"
```

---

## Task 7: Add `plan_feature_tests` — happy path (found + created)

**Files:**
- Modify: `tests/test_feature_tester.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/feature_tester.py`

- [ ] **Step 1: Append the failing test class**

```python
def _make_verdict(req_id: str, status: str = "implemented"):
    """Local helper: build a minimal duck-typed verdict without importing
    spec_compliance (keeps the runtime-independence invariant visible)."""

    class _V:
        pass

    v = _V()
    v.req_id = req_id
    v.status = status
    v.evidence = ""
    v.confidence = 1.0
    return v


class PlanFeatureTestsHappyPathTests(unittest.TestCase):
    """REQ-13: process implemented verdicts; locate or create per REQ."""

    def test_returns_empty_list_for_empty_verdicts(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            plan = plan_feature_tests([], tests_dir=Path(tmp))
            self.assertEqual(plan, [])

    def test_creates_skeleton_when_no_existing_test(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            plan = plan_feature_tests(
                [_make_verdict("REQ-07")], tests_dir=tests_dir
            )
            self.assertEqual(len(plan), 1)
            entry = plan[0]
            self.assertEqual(entry.req_id, "REQ-07")
            self.assertEqual(entry.action, "created")
            self.assertIsNone(entry.existing_test_path)
            self.assertIsNotNone(entry.created_test_path)
            written = Path(entry.created_test_path)
            self.assertTrue(written.exists())
            self.assertEqual(written.name, "test_compliance_req_07.py")
            self.assertEqual(
                written.read_text(encoding="utf-8"),
                _GOLDEN_SKELETON_REQ_07,
            )

    def test_found_branch_when_existing_test_present(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            existing = tests_dir / "test_compliance_req_07.py"
            existing.write_text(
                '"""REQ-07 already covered."""\n', encoding="utf-8"
            )
            original_bytes = existing.read_bytes()
            plan = plan_feature_tests(
                [_make_verdict("REQ-07")], tests_dir=tests_dir
            )
            self.assertEqual(len(plan), 1)
            entry = plan[0]
            self.assertEqual(entry.action, "found")
            self.assertEqual(
                entry.existing_test_path, str(existing.resolve())
            )
            self.assertIsNone(entry.created_test_path)
            # Idempotency: existing file is not touched.
            self.assertEqual(existing.read_bytes(), original_bytes)

    def test_creates_tests_dir_when_missing(self) -> None:
        """Operator-friendly: a missing tests_dir is created on write."""
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp) / "nested" / "tests"
            plan = plan_feature_tests(
                [_make_verdict("REQ-07")], tests_dir=tests_dir
            )
            self.assertEqual(plan[0].action, "created")
            self.assertTrue(tests_dir.is_dir())
            self.assertTrue(
                (tests_dir / "test_compliance_req_07.py").exists()
            )

    def test_processes_multiple_implemented_verdicts(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            plan = plan_feature_tests(
                [_make_verdict("REQ-07"), _make_verdict("REQ-08")],
                tests_dir=tests_dir,
            )
            req_ids = sorted(e.req_id for e in plan)
            self.assertEqual(req_ids, ["REQ-07", "REQ-08"])
            self.assertEqual(
                sorted(p.name for p in tests_dir.glob("test_compliance_*.py")),
                ["test_compliance_req_07.py", "test_compliance_req_08.py"],
            )

    def test_rejects_malformed_req_id_in_verdict(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                plan_feature_tests(
                    [_make_verdict("not-a-req")], tests_dir=Path(tmp)
                )
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.PlanFeatureTestsHappyPathTests -v`
Expected: FAIL — `plan_feature_tests` is not defined yet.

- [ ] **Step 3: Add the function (and a small private helper) to `feature_tester.py`**

```python
def _plan_for_verdict(
    verdict: ReqVerdictLike,
    *,
    tests_dir: Path,
    dry_run: bool,
) -> TestPlanEntry:
    """Plan a single verdict. Internal — `plan_feature_tests` is public."""
    req_id = verdict.req_id
    # Validate up front so a malformed id fails fast before any I/O.
    req_id_lower_underscored, _ = _normalize_req_id(req_id)

    existing = _find_existing_test(tests_dir, req_id)
    if existing is not None:
        return TestPlanEntry(
            req_id=req_id,
            existing_test_path=existing,
            created_test_path=None,
            action="found",
        )

    target = tests_dir / f"test_compliance_{req_id_lower_underscored}.py"

    if dry_run:
        return TestPlanEntry(
            req_id=req_id,
            existing_test_path=None,
            created_test_path=str(target.resolve()),
            action="skipped",
        )

    tests_dir.mkdir(parents=True, exist_ok=True)
    write_atomic_text(target, _render_skeleton(req_id))
    return TestPlanEntry(
        req_id=req_id,
        existing_test_path=None,
        created_test_path=str(target.resolve()),
        action="created",
    )


def plan_feature_tests(
    verdicts: list[ReqVerdictLike],
    *,
    tests_dir: Path,
    dry_run: bool = False,
) -> list[TestPlanEntry]:
    """Plan feature tests for each `implemented` REQ verdict.

    Preconditions: every `verdict.req_id` matches ``REQ-\\d+``;
        `tests_dir` is a `Path` (need not exist — created on write);
        `dry_run`, when True, suppresses all filesystem writes.
    Postconditions: returns one `TestPlanEntry` per verdict whose
        ``status == "implemented"`` (other statuses are silently dropped
        per REQ-13). When `dry_run=False` and no existing test is found
        for a REQ, a skeleton file is written via
        ``core.atomic_io.write_atomic_text`` and `action="created"`. When
        an existing test in ``tests_dir/test_compliance_*.py`` cites the
        REQ id as a whole token, `action="found"` and no file is
        written. When `dry_run=True` and no existing test is found,
        `action="skipped"` and `created_test_path` is set to the path
        that *would* have been written.
    Raises: `ValueError` if any verdict's `req_id` is malformed;
        ``OSError`` (and subclasses) propagated from the atomic-write
        path on filesystem failure.
    """
    plan: list[TestPlanEntry] = []
    for verdict in verdicts:
        if verdict.status != "implemented":
            continue
        plan.append(
            _plan_for_verdict(verdict, tests_dir=tests_dir, dry_run=dry_run)
        )
    return plan
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.PlanFeatureTestsHappyPathTests -v`
Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_feature_tester.py skills/bmad-story-automator/src/story_automator/core/feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(feature_tester): plan_feature_tests happy path (REQ-13)"
```

---

## Task 8: Status filtering — only `implemented` verdicts are processed (REQ-13)

**Files:**
- Modify: `tests/test_feature_tester.py`

- [ ] **Step 1: Append the failing test class**

```python
class PlanFeatureTestsStatusFilterTests(unittest.TestCase):
    """REQ-13: processes only verdicts with status == 'implemented'."""

    def test_missing_verdicts_dropped(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            plan = plan_feature_tests(
                [_make_verdict("REQ-07", status="missing")],
                tests_dir=tests_dir,
            )
            self.assertEqual(plan, [])
            self.assertEqual(
                list(tests_dir.glob("test_compliance_*.py")), []
            )

    def test_partial_verdicts_dropped(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            plan = plan_feature_tests(
                [_make_verdict("REQ-07", status="partial")],
                tests_dir=tests_dir,
            )
            self.assertEqual(plan, [])

    def test_mixed_input_keeps_only_implemented(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            plan = plan_feature_tests(
                [
                    _make_verdict("REQ-07", status="implemented"),
                    _make_verdict("REQ-08", status="missing"),
                    _make_verdict("REQ-09", status="partial"),
                    _make_verdict("REQ-10", status="implemented"),
                ],
                tests_dir=tests_dir,
            )
            self.assertEqual(
                sorted(e.req_id for e in plan), ["REQ-07", "REQ-10"]
            )

    def test_dropped_verdicts_do_not_validate_req_id(self) -> None:
        """Dropped early — a malformed missing/partial id must NOT raise."""
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            plan = plan_feature_tests(
                [_make_verdict("not-a-req", status="missing")],
                tests_dir=Path(tmp),
            )
            self.assertEqual(plan, [])
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.PlanFeatureTestsStatusFilterTests -v`
Expected: all 4 PASS (the implementation already filters by status; no code changes needed). If they fail, the early-continue in `plan_feature_tests` is wrong — fix it before committing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(feature_tester): status filter — only implemented processed (REQ-13)"
```

---

## Task 9: Dry-run behaviour (REQ-15)

**Files:**
- Modify: `tests/test_feature_tester.py`

- [ ] **Step 1: Append the failing test class**

```python
class PlanFeatureTestsDryRunTests(unittest.TestCase):
    """REQ-15: dry_run=True writes no file; created_test_path is the
    would-be path; action='skipped'."""

    def test_dry_run_does_not_write_file(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            plan = plan_feature_tests(
                [_make_verdict("REQ-07")],
                tests_dir=tests_dir,
                dry_run=True,
            )
            self.assertEqual(len(plan), 1)
            entry = plan[0]
            self.assertEqual(entry.action, "skipped")
            self.assertIsNone(entry.existing_test_path)
            would_be = Path(entry.created_test_path)
            self.assertEqual(would_be.name, "test_compliance_req_07.py")
            self.assertFalse(would_be.exists())
            self.assertEqual(
                list(tests_dir.glob("test_compliance_*.py")), []
            )

    def test_dry_run_does_not_create_tests_dir(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp) / "nested" / "tests"
            plan = plan_feature_tests(
                [_make_verdict("REQ-07")],
                tests_dir=tests_dir,
                dry_run=True,
            )
            self.assertEqual(plan[0].action, "skipped")
            self.assertFalse(tests_dir.exists())

    def test_dry_run_still_returns_found_when_existing_test_present(
        self,
    ) -> None:
        """If a test already exists, dry_run still reports 'found'."""
        from story_automator.core.feature_tester import plan_feature_tests

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)
            existing = tests_dir / "test_compliance_req_07.py"
            existing.write_text('"""REQ-07 covered."""\n', encoding="utf-8")
            plan = plan_feature_tests(
                [_make_verdict("REQ-07")],
                tests_dir=tests_dir,
                dry_run=True,
            )
            self.assertEqual(plan[0].action, "found")
            self.assertEqual(
                plan[0].existing_test_path, str(existing.resolve())
            )
```

- [ ] **Step 2: Run to verify pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.PlanFeatureTestsDryRunTests -v`
Expected: all 3 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(feature_tester): dry_run semantics (REQ-15)"
```

---

## Task 10: Docstring + atomic-write contract assertions

**Files:**
- Modify: `tests/test_feature_tester.py`

Rationale: NFR requires public-API docstrings stating pre/post/raises; REQ-13 requires the write path to use `core.atomic_io`. These tests lock those contracts.

- [ ] **Step 1: Append the failing test class**

```python
class PublicAPIDocstringTests(unittest.TestCase):
    """NFR: public-API docstrings must mention pre/post/raises."""

    def test_plan_feature_tests_docstring_covers_contracts(self) -> None:
        from story_automator.core.feature_tester import plan_feature_tests

        doc = plan_feature_tests.__doc__ or ""
        for needle in ("Preconditions", "Postconditions", "Raises"):
            self.assertIn(needle, doc, f"missing {needle} in docstring")

    def test_test_plan_entry_docstring_covers_contracts(self) -> None:
        from story_automator.core.feature_tester import TestPlanEntry

        doc = TestPlanEntry.__doc__ or ""
        for needle in ("Preconditions", "Postconditions", "Raises"):
            self.assertIn(needle, doc)


class AtomicWriteContractTests(unittest.TestCase):
    """REQ-13: skeleton creation MUST go through core.atomic_io."""

    def test_plan_feature_tests_writes_via_atomic_io(self) -> None:
        from unittest.mock import patch

        from story_automator.core import feature_tester

        with tempfile.TemporaryDirectory() as tmp:
            tests_dir = Path(tmp)

            captured: list[tuple[Path, str]] = []

            def fake_write(path: Path, data: str, **kwargs: object) -> None:
                captured.append((path, data))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(data, encoding="utf-8")

            with patch.object(
                feature_tester, "write_atomic_text", side_effect=fake_write
            ):
                feature_tester.plan_feature_tests(
                    [_make_verdict("REQ-07")], tests_dir=tests_dir
                )

            self.assertEqual(len(captured), 1)
            written_path, written_data = captured[0]
            self.assertEqual(written_path.name, "test_compliance_req_07.py")
            self.assertEqual(written_data, _GOLDEN_SKELETON_REQ_07)
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.PublicAPIDocstringTests tests.test_feature_tester.AtomicWriteContractTests -v`
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(feature_tester): pin docstring contracts and atomic-write call (REQ-13, NFR)"
```

---

## Task 11: Forbidden-import grep test + cross-platform `Path` semantics

**Files:**
- Modify: `tests/test_feature_tester.py`

- [ ] **Step 1: Append the failing test class**

```python
class ForbiddenImportsTests(unittest.TestCase):
    """Quality gate: stdlib only (no psutil), no commands/, no cross-layer
    runtime imports of spec_compliance or gap_validator."""

    def test_source_has_no_psutil_import(self) -> None:
        from story_automator.core import feature_tester

        src_path = Path(feature_tester.__file__)
        text = src_path.read_text(encoding="utf-8")
        self.assertNotIn("import psutil", text)
        self.assertNotIn("from psutil", text)

    def test_source_has_no_commands_import(self) -> None:
        from story_automator.core import feature_tester

        src_path = Path(feature_tester.__file__)
        text = src_path.read_text(encoding="utf-8")
        self.assertNotIn("story_automator.commands", text)

    def test_source_only_imports_spec_compliance_under_type_checking(
        self,
    ) -> None:
        """Runtime independence: any cross-layer import lives inside the
        `if TYPE_CHECKING:` block; top-level imports never mention
        spec_compliance or gap_validator. We track the indent-aware
        state so the TYPE_CHECKING block (4-space-indented) is exempt.
        """
        from story_automator.core import feature_tester

        src_path = Path(feature_tester.__file__)
        text = src_path.read_text(encoding="utf-8")
        for line in text.splitlines():
            # An import line at column 0 (no leading whitespace) is
            # unconditional. Indented import lines belong to a nested
            # block (e.g. `if TYPE_CHECKING:`) and are out of scope.
            if line.startswith("import ") or line.startswith("from "):
                self.assertNotIn(
                    "spec_compliance",
                    line,
                    f"unconditional import touches spec_compliance: {line!r}",
                )
                self.assertNotIn(
                    "gap_validator",
                    line,
                    f"unconditional import touches gap_validator: {line!r}",
                )
```

- [ ] **Step 2: Run tests to verify pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester.ForbiddenImportsTests -v`
Expected: all 3 PASS (the runtime spec_compliance import is gated by `if TYPE_CHECKING:` per Task 1).

- [ ] **Step 3: Commit**

```bash
git add tests/test_feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(feature_tester): forbid psutil/commands/cross-layer runtime imports"
```

---

## Task 12: Run the full suite + coverage; push to ≥92%

**Files:**
- Possibly modify: `skills/bmad-story-automator/src/story_automator/core/feature_tester.py` (add `# pragma: no cover` to any genuinely unreachable branch)

- [ ] **Step 1: Run the entire test file**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_feature_tester -v`
Expected: all green; verify the count is ≥18 test methods across the three M06a test files (already 18+ in this single file).

- [ ] **Step 2: Measure coverage**

Run (use the dotted module name as `--source` so coverage resolves it via `PYTHONPATH`; the file-path-without-`.py` form does NOT work):
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=story_automator.core.feature_tester \
  -m unittest tests.test_feature_tester
PYTHONPATH=skills/bmad-story-automator/src python -m coverage report -m --fail-under=92
```

Expected: ≥92% line coverage. The `if TYPE_CHECKING:` block is statically `False` at runtime so coverage will naturally count that line as missed — mark it with `# pragma: no cover` (see Step 3). With bare attribute annotations on the Protocol (no method bodies), there is nothing left to pragma on the Protocol itself.

- [ ] **Step 3: If coverage < 92%, add a `# pragma: no cover` with a one-line rationale to each uncovered branch**

Example (only if needed):

```python
if TYPE_CHECKING:  # pragma: no cover - imports gated to type-check time only
    from story_automator.core.spec_compliance import ReqVerdict  # noqa: F401
```

- [ ] **Step 4: Re-run coverage**

Run: same coverage commands as Step 2.
Expected: ≥92%.

- [ ] **Step 5: Commit if any pragma added; otherwise skip the commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "chore(feature_tester): pragma uncoverable type-only branches"
```

---

## Task 13: Lint with `ruff` and type-check with `mypy --strict`

**Files:** none (running tools only; fix in place if either reports findings)

- [ ] **Step 1: Run ruff**

Run:
```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/core/feature_tester.py tests/test_feature_tester.py
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/feature_tester.py tests/test_feature_tester.py
```
Expected: zero findings, zero unformatted files. If `ruff format --check` complains, run `python -m ruff format <paths>` and commit the formatting fix as `style(feature_tester): ruff format`.

- [ ] **Step 2: Run mypy strict**

Run:
```bash
python -m mypy --strict skills/bmad-story-automator/src/story_automator/core/feature_tester.py
```
Expected: zero errors. If mypy complains about `runtime_checkable` Protocol methods returning ellipsis, add a `# type: ignore[empty-body]` with a one-line rationale.

- [ ] **Step 3: Fix any findings in place, commit if changes were needed**

```bash
git add skills/bmad-story-automator/src/story_automator/core/feature_tester.py tests/test_feature_tester.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(feature_tester): ruff + mypy strict clean"
```

---

## Task 14: Final whole-suite verification + diff-envelope audit

**Files:** none

- [ ] **Step 1: Run all M06a tests together**

Run:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest \
  tests.test_gap_validator tests.test_spec_compliance tests.test_feature_tester -v
```
Expected: all PASS; total test-method count ≥18 (quality gate).

- [ ] **Step 2: Run the full project test suite**

Run: `npm run test:python`
Expected: 0 failures. If Layer 1 or Layer 2 tests regress, STOP — the diff was supposed to be confined to `feature_tester.py` and `tests/test_feature_tester.py`. Bisect to find the leakage.

- [ ] **Step 3: Audit the diff envelope**

Run:
```bash
git diff --name-only main..HEAD
```
Expected output (the only paths that may appear):
```
skills/bmad-story-automator/src/story_automator/core/feature_tester.py
tests/test_feature_tester.py
docs/superpowers/plans/2026-06-15-m06a-m3-feature-tester.md
.claude/.gap-report.json   (Phase A only; will be removed/replaced by orchestrator)
```
Anything else is a quality-gate violation. Fix and recommit.

- [ ] **Step 4: Final commit (only if any cleanup was made)**

```bash
git status
# If nothing to commit, skip this step.
```

---

## Self-review checklist

**Spec coverage:**

| REQ / NFR | Covered by |
|---|---|
| REQ-12 (`TestPlanEntry` dataclass) | Task 2 |
| REQ-13 (`plan_feature_tests` search + create + status filter) | Tasks 5, 7, 8, 10 |
| REQ-14 (skeleton format with REQ id verbatim, `from __future__`, `self.fail`) | Tasks 4, 7 (golden) |
| REQ-15 (`dry_run` semantics) | Task 9 |
| REQ-16 (importable any order, no side effects, `__all__`) | Task 1 |
| NFR frozen kw_only @dataclass, no subclass | Task 2 |
| NFR stdlib-only, no psutil | Task 11 |
| NFR PEP 604, `from __future__ import annotations` | Tasks 1, 3 (visible in implementation snippets) |
| NFR docstrings state pre/post/raises | Tasks 2, 7, 10 |
| NFR mypy --strict | Task 13 |
| QG ruff clean | Task 13 |
| QG ≥92% coverage | Task 12 |
| QG golden-string byte-equality | Task 4 |
| QG tests use `tempfile.TemporaryDirectory` | Tasks 5, 7, 8, 9, 10, 11 (consistently) |
| QG no imports from commands/ or other M06a modules at runtime | Tasks 1 (`if TYPE_CHECKING:`), 6 (Protocol), 11 (grep guard) |
| QG diff limited to feature_tester.py + test_feature_tester.py | Task 14 audit |

**Known spec quirks (flagged for gap analysis, NOT fixed in this plan):**

- REQ-13 says "writes a minimal skeleton file using `core.atomic_io.atomic_write`". No `atomic_write` symbol exists in `core/atomic_io.py`; the actual exported writer is `write_atomic_text`. Since the diff envelope forbids modifying `atomic_io.py`, this plan uses `write_atomic_text`. If the spec author intended a name change, that's a separate milestone.
- REQ-14 says "skeleton ... must be a valid `unittest.TestCase` subclass with one `test_<req_id_lower>_skeleton` method". The phrase `<req_id_lower>` is ambiguous because "REQ-07" lowercased is "req-07" which is not a valid Python identifier. The plan reads `<req_id_lower>` as `req_id_lower_with_underscores` (i.e. `req_07`). If a future reviewer disagrees, the golden test in Task 4 is the single point of update.
- The spec quality gate says "at least 18 test methods across the three test files". This plan delivers 30+ test methods in `tests/test_feature_tester.py` alone, comfortably above the bar.
