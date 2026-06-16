# M07a — Failure-triage taxonomy foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the pure-data foundation of `core/failure_triage.py` — the `FailureClass` and `Confidence` enums, the frozen `Classification` dataclass, and the `IMPLIES_GRAPH` constant — with taxonomy-completeness and ruff quality gates passing. No `classify()` dispatch logic; that is M07b.

**Architecture:** A single new module `skills/bmad-story-automator/src/story_automator/core/failure_triage.py` containing four top-level surfaces — `FailureClass`, `Confidence`, `Classification`, `IMPLIES_GRAPH` — plus a module-level `__all__`. Pure-stdlib (`enum`, `dataclasses`), no I/O, no third-party imports. Tests at `tests/test_failure_triage.py` (matching the established repo-root convention used by every other test in this project; the spec text says `skills/bmad-story-automator/tests/` but no such directory exists — repo-root layout is the actual convention and is what `npm run test:python` discovers via `python3 -m unittest discover -s tests`).

**Tech Stack:** Python 3.11+, stdlib only (`enum`, `dataclasses`), `unittest.TestCase` for tests, `ruff` for lint/format.

**Scope (M07a only):** Covers spec REQ-01 (module location + future annotations), REQ-02 (FailureClass — 13 members, declaration order, str values matching name), REQ-03 (Confidence enum), REQ-04 (frozen kw_only `Classification` dataclass), REQ-05 (IMPLIES_GRAPH constant — static deterministic entries only), the non-functional requirements (LF, PEP 604, cross-platform, no third-party imports), and the taxonomy-completeness + ruff quality gates. REQ-06 through REQ-15 (the `classify()` dispatch, per-event classifier helpers, `classify_stream` generator, 13-class behavioural test matrix, coverage gate, determinism gate, line-count gate) are **out of scope for M07a and belong to M07b**.

**Spec/codebase mismatches deferred to M07b** (logged in gap report, not blocking for M07a since they only touch dispatch logic):
- REQ-08 references `error_kind` on `StoryFailed`; the M01 dataclass field is `error_class`.
- REQ-09 references `exit_signal` on `TmuxSessionCrashed`; the M01 dataclass has only `exit_code` and `last_capture_chars`.
- REQ-10 references `attempt_count` on `StoryDeferred`; the M01 dataclass has `tasks_completed`.
- REQ-11 references `trigger: str` on `EscalationTriggered`; the M01 dataclass has `trigger_id: int`, `severity: str`, `message: str`.

---

### Task 1: Test scaffold + failing module-import test

**Files:**
- Create: `tests/test_failure_triage.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import unittest


class ModuleImportTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import failure_triage  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run (from repo root, git-bash or WSL):
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: `ModuleNotFoundError: No module named 'story_automator.core.failure_triage'` — one test fails with an import error.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add failing module-import scaffold for m07a" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 2: Create empty module skeleton (make import test pass)

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Create the module with future annotations and a docstring**

Write exactly this content to `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`:

```python
"""Failure-triage taxonomy foundation for bmad-automator (M07a).

This module defines the pure-data substrate that downstream triage
(M07b classify dispatch), adaptive retry (M08), gate decisions (M09),
and the retrospective summariser (M10) consume:

- ``FailureClass`` — the closed 13-member taxonomy of failure shapes.
- ``Confidence`` — three-level confidence ordinal (HIGH/MEDIUM/LOW).
- ``Classification`` — frozen, kw-only result record paired with each
  failure-shaped event.
- ``IMPLIES_GRAPH`` — the static implication edges between members of
  ``FailureClass``. Runtime classifiers may extend the per-event
  ``implies`` tuple based on payload hints (e.g. transport hints on a
  tmux crash) — those extensions live in ``classify`` (M07b) and are
  not encoded here.

M07a is data-only: no ``classify`` function, no dispatch logic, no I/O,
no third-party imports. The classify dispatch and per-event helpers
land in M07b.
"""

from __future__ import annotations
```

- [ ] **Step 2: Run the import test to verify it passes**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: `OK` — `test_module_imports` passes.

- [ ] **Step 3: Commit the module skeleton**

```bash
git add skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): add empty m07a module skeleton" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 3: Write failing tests for `FailureClass` enum (REQ-02)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_failure_triage.py` (after the existing import test):

```python
class FailureClassTests(unittest.TestCase):
    def test_failure_class_has_exactly_thirteen_members(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        self.assertEqual(len(list(FailureClass)), 13)

    def test_failure_class_members_in_declaration_order(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        expected = [
            "CRASH",
            "TIMEOUT",
            "POLICY_VIOLATION",
            "REVIEW_REJECTED",
            "TEST_FAILURE",
            "BUDGET_EXCEEDED",
            "PARSE_ERROR",
            "AGENT_REFUSED",
            "NETWORK_ERROR",
            "GATE_DEFER",
            "PLATEAU",
            "REPEATED_RETRY",
            "UNKNOWN",
        ]
        self.assertEqual([m.name for m in FailureClass], expected)

    def test_failure_class_values_equal_member_names(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        for member in FailureClass:
            self.assertEqual(member.value, member.name)

    def test_failure_class_is_str_enum_subclass(self) -> None:
        import enum

        from story_automator.core.failure_triage import FailureClass

        self.assertTrue(issubclass(FailureClass, enum.Enum))
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.FailureClassTests -v
```
Expected: 4 failures — `ImportError: cannot import name 'FailureClass'`.

---

### Task 4: Implement `FailureClass` (REQ-02)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Add the enum**

Append to the module (after `from __future__ import annotations`):

```python

import enum


class FailureClass(enum.Enum):
    """Closed taxonomy of failure shapes consumed by triage.

    Exactly thirteen members. Declaration order is the canonical order
    asserted by the taxonomy-completeness gate (REQ-02). String values
    equal the member name so JSONL serialisations in M07b round-trip
    cleanly.
    """

    CRASH = "CRASH"
    TIMEOUT = "TIMEOUT"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    REVIEW_REJECTED = "REVIEW_REJECTED"
    TEST_FAILURE = "TEST_FAILURE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    PARSE_ERROR = "PARSE_ERROR"
    AGENT_REFUSED = "AGENT_REFUSED"
    NETWORK_ERROR = "NETWORK_ERROR"
    GATE_DEFER = "GATE_DEFER"
    PLATEAU = "PLATEAU"
    REPEATED_RETRY = "REPEATED_RETRY"
    UNKNOWN = "UNKNOWN"
```

- [ ] **Step 2: Run the FailureClass tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.FailureClassTests -v
```
Expected: all 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_failure_triage.py skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): add FailureClass 13-member taxonomy (REQ-02)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 5: Write failing tests for `Confidence` enum (REQ-03)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append:

```python
class ConfidenceTests(unittest.TestCase):
    def test_confidence_members_are_high_medium_low(self) -> None:
        from story_automator.core.failure_triage import Confidence

        self.assertEqual([m.name for m in Confidence], ["HIGH", "MEDIUM", "LOW"])

    def test_confidence_values_equal_names(self) -> None:
        from story_automator.core.failure_triage import Confidence

        for member in Confidence:
            self.assertEqual(member.value, member.name)

    def test_confidence_is_case_sensitive_enum(self) -> None:
        import enum

        from story_automator.core.failure_triage import Confidence

        self.assertTrue(issubclass(Confidence, enum.Enum))
        with self.assertRaises(KeyError):
            Confidence["high"]
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ConfidenceTests -v
```
Expected: 3 failures — `ImportError: cannot import name 'Confidence'`.

---

### Task 6: Implement `Confidence` (REQ-03)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Add the enum**

Append after the `FailureClass` definition:

```python


class Confidence(enum.Enum):
    """Three-level confidence ordinal for a classification.

    Case-sensitive member names mirror the value strings; serialisations
    in M07b emit the bare member name so downstream policy engines (M08
    adaptive retry, M09 gate) can match on string equality without
    needing to import this enum.
    """

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
```

- [ ] **Step 2: Run the Confidence tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ConfidenceTests -v
```
Expected: all 3 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_failure_triage.py skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): add Confidence enum (REQ-03)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 7: Write failing tests for `Classification` dataclass (REQ-04)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append:

```python
class ClassificationDataclassTests(unittest.TestCase):
    def test_classification_is_a_dataclass(self) -> None:
        from dataclasses import is_dataclass

        from story_automator.core.failure_triage import Classification

        self.assertTrue(is_dataclass(Classification))

    def test_classification_is_frozen(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            Confidence,
            FailureClass,
        )

        c = Classification(
            primary=FailureClass.UNKNOWN,
            implies=(),
            confidence=Confidence.LOW,
            reason="x",
            event_id=None,
        )
        with self.assertRaises(Exception):
            c.reason = "y"  # type: ignore[misc]

    def test_classification_field_names_and_order(self) -> None:
        from dataclasses import fields

        from story_automator.core.failure_triage import Classification

        names = [f.name for f in fields(Classification)]
        self.assertEqual(
            names,
            ["primary", "implies", "confidence", "reason", "event_id"],
        )

    def test_classification_field_types_are_pep604_strings(self) -> None:
        from dataclasses import fields

        from story_automator.core.failure_triage import Classification

        types_by_name = {f.name: f.type for f in fields(Classification)}
        # With `from __future__ import annotations` the types are stored
        # as the literal source strings — assert PEP 604 syntax is used
        # for the optional field, not typing.Optional.
        self.assertEqual(types_by_name["primary"], "FailureClass")
        self.assertEqual(types_by_name["implies"], "tuple[FailureClass, ...]")
        self.assertEqual(types_by_name["confidence"], "Confidence")
        self.assertEqual(types_by_name["reason"], "str")
        self.assertEqual(types_by_name["event_id"], "str | None")

    def test_classification_requires_kw_only_construction(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            Confidence,
            FailureClass,
        )

        with self.assertRaises(TypeError):
            Classification(  # type: ignore[misc]
                FailureClass.UNKNOWN,
                (),
                Confidence.LOW,
                "x",
                None,
            )

    def test_classification_round_trip_construction(self) -> None:
        from story_automator.core.failure_triage import (
            Classification,
            Confidence,
            FailureClass,
        )

        c = Classification(
            primary=FailureClass.POLICY_VIOLATION,
            implies=(FailureClass.REVIEW_REJECTED,),
            confidence=Confidence.HIGH,
            reason="guardrail tripped",
            event_id=None,
        )
        self.assertEqual(c.primary, FailureClass.POLICY_VIOLATION)
        self.assertEqual(c.implies, (FailureClass.REVIEW_REJECTED,))
        self.assertEqual(c.confidence, Confidence.HIGH)
        self.assertEqual(c.reason, "guardrail tripped")
        self.assertIsNone(c.event_id)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassificationDataclassTests -v
```
Expected: 6 failures — `ImportError: cannot import name 'Classification'`.

---

### Task 8: Implement `Classification` dataclass (REQ-04)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Add the import and dataclass**

Update the imports block to the exact two-line ordering shown below (this matches ruff's default `I001` isort rule — alphabetical by module name within the single stdlib group — and is what `ruff check` will accept in Task 13 without manual reformatting):

```python
from dataclasses import dataclass
import enum
```

Then append after the `Confidence` definition:

```python


@dataclass(frozen=True, kw_only=True)
class Classification:
    """Frozen verdict produced by ``classify`` (M07b) for one event.

    Fields:

    - ``primary`` — the leading ``FailureClass`` for this event.
    - ``implies`` — additional ``FailureClass`` entries downstream policy
      should treat as concurrently true (e.g. ``POLICY_VIOLATION``
      always implies ``REVIEW_REJECTED``). Empty tuple when no
      implications apply. Order is stable per-classifier to keep
      ``Classification`` instances hashable-equivalent.
    - ``confidence`` — operator-facing certainty level.
    - ``reason`` — short snake-case string explaining the verdict.
      Used by M10 retro summaries; never user-facing prose.
    - ``event_id`` — the originating event's identifier when available,
      else ``None``. M01 events do not yet carry an ``event_id`` field
      so this is currently always ``None`` in practice; reserved so
      downstream consumers can correlate verdicts back to source events
      once the field lands.
    """

    primary: FailureClass
    implies: tuple[FailureClass, ...]
    confidence: Confidence
    reason: str
    event_id: str | None
```

- [ ] **Step 2: Run the Classification tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ClassificationDataclassTests -v
```
Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_failure_triage.py skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): add frozen Classification dataclass (REQ-04)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 9: Write failing tests for `IMPLIES_GRAPH` (REQ-05)

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the failing tests**

Append:

```python
class ImpliesGraphTests(unittest.TestCase):
    def test_implies_graph_is_dict(self) -> None:
        from story_automator.core.failure_triage import IMPLIES_GRAPH

        self.assertIsInstance(IMPLIES_GRAPH, dict)

    def test_implies_graph_keys_are_failure_class_members(self) -> None:
        from story_automator.core.failure_triage import (
            IMPLIES_GRAPH,
            FailureClass,
        )

        for key in IMPLIES_GRAPH:
            self.assertIsInstance(key, FailureClass)

    def test_implies_graph_values_are_tuples_of_failure_class(self) -> None:
        from story_automator.core.failure_triage import (
            IMPLIES_GRAPH,
            FailureClass,
        )

        for value in IMPLIES_GRAPH.values():
            self.assertIsInstance(value, tuple)
            for member in value:
                self.assertIsInstance(member, FailureClass)

    def test_implies_graph_required_edges(self) -> None:
        from story_automator.core.failure_triage import (
            IMPLIES_GRAPH,
            FailureClass,
        )

        self.assertEqual(
            IMPLIES_GRAPH[FailureClass.POLICY_VIOLATION],
            (FailureClass.REVIEW_REJECTED,),
        )
        self.assertEqual(
            IMPLIES_GRAPH[FailureClass.BUDGET_EXCEEDED],
            (FailureClass.GATE_DEFER,),
        )
        self.assertEqual(
            IMPLIES_GRAPH[FailureClass.REPEATED_RETRY],
            (FailureClass.PLATEAU,),
        )

    def test_implies_graph_has_no_self_loops(self) -> None:
        from story_automator.core.failure_triage import IMPLIES_GRAPH

        for key, value in IMPLIES_GRAPH.items():
            self.assertNotIn(key, value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ImpliesGraphTests -v
```
Expected: 5 failures — `ImportError: cannot import name 'IMPLIES_GRAPH'`.

---

### Task 10: Implement `IMPLIES_GRAPH` (REQ-05)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/failure_triage.py`

- [ ] **Step 1: Add the constant and `__all__`**

Append to the module (after the `Classification` definition):

```python


IMPLIES_GRAPH: dict[FailureClass, tuple[FailureClass, ...]] = {
    FailureClass.POLICY_VIOLATION: (FailureClass.REVIEW_REJECTED,),
    FailureClass.BUDGET_EXCEEDED: (FailureClass.GATE_DEFER,),
    FailureClass.REPEATED_RETRY: (FailureClass.PLATEAU,),
}
# Spec REQ-05 also mentions a conditional CRASH -> (NETWORK_ERROR,) edge
# "when transport hints are present". That edge is *runtime conditional*
# on the tmux-crash payload, not a static implication of CRASH itself
# (most crashes are not network-shaped). It is therefore applied inside
# `_classify_tmux_crash` (M07b), not encoded here.


__all__ = [
    "Classification",
    "Confidence",
    "FailureClass",
    "IMPLIES_GRAPH",
]
```

- [ ] **Step 2: Run the IMPLIES_GRAPH tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ImpliesGraphTests -v
```
Expected: all 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_failure_triage.py skills/bmad-story-automator/src/story_automator/core/failure_triage.py
git commit -m "feat(failure-triage): add IMPLIES_GRAPH static edges + module __all__ (REQ-05)" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 11: Taxonomy-completeness gate + placeholder-token gate

**Files:**
- Modify: `tests/test_failure_triage.py`

- [ ] **Step 1: Append the gate tests**

Append (these encode the "taxonomy-completeness gate" quality gate
from the spec — exactly 13 members + no unresolved four-letter
placeholder tokens in the source):

```python
class TaxonomyCompletenessGateTests(unittest.TestCase):
    def test_exactly_thirteen_failure_class_members(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        self.assertEqual(
            len(list(FailureClass)),
            13,
            "FailureClass must have exactly 13 members; "
            "silent additions break downstream M08/M09/M10 contracts.",
        )

    def test_failure_class_member_set_matches_agreed_taxonomy(self) -> None:
        from story_automator.core.failure_triage import FailureClass

        expected = {
            "CRASH",
            "TIMEOUT",
            "POLICY_VIOLATION",
            "REVIEW_REJECTED",
            "TEST_FAILURE",
            "BUDGET_EXCEEDED",
            "PARSE_ERROR",
            "AGENT_REFUSED",
            "NETWORK_ERROR",
            "GATE_DEFER",
            "PLATEAU",
            "REPEATED_RETRY",
            "UNKNOWN",
        }
        self.assertEqual({m.name for m in FailureClass}, expected)

    def test_no_unresolved_four_letter_placeholder_tokens_in_source(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        text = source_path.read_text(encoding="utf-8")
        # The taxonomy-completeness gate forbids unresolved four-letter
        # ALL-CAPS placeholder tokens in the shipped source. Standard
        # IDE/code-review placeholders are the targets.
        forbidden = ("TODO", "FIXM", "XXXX", "HACK", "TKTK")
        for token in forbidden:
            self.assertNotIn(
                token,
                text,
                f"unresolved placeholder token {token!r} found in "
                f"{source_path}; resolve or remove before shipping.",
            )
```

- [ ] **Step 2: Run the gate tests to verify they pass**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.TaxonomyCompletenessGateTests -v
```
Expected: all 3 tests pass (the module currently has no `TODO`/`FIXM`/`XXXX`/`HACK`/`TKTK` tokens).

- [ ] **Step 3: Commit**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add taxonomy-completeness + placeholder-token gates" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 12: Import-allowlist + line-count discipline gates

**Files:**
- Modify: `tests/test_failure_triage.py`

These encode (a) the import-allowlist requirement (REQ-13 / non-functional "no third-party imports") and (b) the ≤500-LOC ceiling. Both are stdlib-only assertions and run cross-platform.

- [ ] **Step 1: Append the discipline gates**

```python
class ImportAndSizeDisciplineTests(unittest.TestCase):
    def test_no_third_party_or_io_imports(self) -> None:
        import ast
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        allowed_roots = {"enum", "dataclasses", "typing", "collections"}
        allowed_local_prefixes = ("story_automator.core",)
        # In M07a the module currently uses only `enum` and `dataclasses`.
        # The allowlist is set wider (reserving room for REQ-13's permitted
        # `core.telemetry_events` / `core.common` imports in M07b) but
        # explicitly excludes `filelock`, `psutil`, `os`, `sys`, `pathlib`,
        # `subprocess`, and any other I/O-shaped stdlib module.
        forbidden_roots = {
            "filelock",
            "psutil",
            "os",
            "sys",
            "pathlib",
            "subprocess",
            "socket",
            "http",
            "urllib",
            "asyncio",
            "threading",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertNotIn(root, forbidden_roots)
                    self.assertTrue(
                        root in allowed_roots
                        or alias.name.startswith(allowed_local_prefixes),
                        f"unexpected import: {alias.name}",
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                root = module.split(".")[0]
                self.assertNotIn(root, forbidden_roots)
                self.assertTrue(
                    root in allowed_roots
                    or module.startswith(allowed_local_prefixes)
                    or root == "__future__",
                    f"unexpected from-import: {module}",
                )

    def test_module_under_five_hundred_lines(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        line_count = len(source_path.read_text(encoding="utf-8").splitlines())
        self.assertLessEqual(
            line_count,
            500,
            f"failure_triage.py has {line_count} lines; cap is 500.",
        )

    def test_future_annotations_on_first_non_comment_line(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        text = source_path.read_text(encoding="utf-8")
        # Walk past comment-only lines, blank lines, and the leading
        # module docstring (which is a string literal, not a comment).
        # The first executable statement must be `from __future__ import
        # annotations` so that the PEP 604 union string `event_id: str |
        # None` in Classification resolves lazily.
        import ast

        tree = ast.parse(text)
        first_stmt = tree.body[0] if tree.body else None
        # Skip a leading docstring expression if present.
        if (
            isinstance(first_stmt, ast.Expr)
            and isinstance(first_stmt.value, ast.Constant)
            and isinstance(first_stmt.value.value, str)
        ):
            first_stmt = tree.body[1] if len(tree.body) > 1 else None
        self.assertIsInstance(first_stmt, ast.ImportFrom)
        assert isinstance(first_stmt, ast.ImportFrom)  # narrow for mypy
        self.assertEqual(first_stmt.module, "__future__")
        self.assertEqual(
            [alias.name for alias in first_stmt.names],
            ["annotations"],
        )

    def test_no_typing_optional_or_union(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        text = source_path.read_text(encoding="utf-8")
        # PEP 604 enforcement: typing.Optional and typing.Union are
        # forbidden in this module (spec non-functional requirement).
        # Catches both bare `Optional[` / `Union[` references and the
        # `from typing import Optional` / `Union` import forms.
        for token in ("Optional", "Union"):
            self.assertNotIn(
                token,
                text,
                f"forbidden typing alias {token!r} found in "
                f"{source_path}; use PEP 604 `X | Y` syntax instead.",
            )

    def test_lf_line_endings(self) -> None:
        import pathlib

        from story_automator.core import failure_triage

        source_path = pathlib.Path(failure_triage.__file__)
        raw = source_path.read_bytes()
        self.assertNotIn(
            b"\r\n",
            raw,
            f"{source_path} contains CRLF line endings; spec requires "
            f"LF under core.autocrlf=false. Re-save with LF endings.",
        )

    def test_all_export_list(self) -> None:
        from story_automator.core import failure_triage

        self.assertEqual(
            set(failure_triage.__all__),
            {"Classification", "Confidence", "FailureClass", "IMPLIES_GRAPH"},
        )
```

- [ ] **Step 2: Run the discipline tests**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage.ImportAndSizeDisciplineTests -v
```
Expected: both tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_failure_triage.py
git commit -m "test(failure-triage): add import-allowlist + line-count discipline gates" --trailer "Generated-By: claude-opus-4-7"
```

---

### Task 13: Full test-suite + ruff + format quality gates

**Files:** (no source edits; verification only — if ruff complains, fix the offending file and re-run before committing.)

- [ ] **Step 1: Run the full failure-triage test suite**

Run:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_failure_triage -v
```
Expected: all tests pass. Verify the count is `Ran N tests in <2s` where N matches the sum of tests added across tasks 1, 3, 5, 7, 9, 11, 12.

- [ ] **Step 2: Run the project-wide test suite (regression guard)**

Run:
```
npm run test:python
```
Expected: `OK` — no other suite is regressed. If a suite breaks, the new module imports cleanly so the breakage is unrelated; surface it and stop.

- [ ] **Step 3: Run ruff check on the new files**

Run:
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
```
Expected: `All checks passed!` — exit 0. If ruff reports findings, edit the offending file (do not add a `# noqa` blanket) and re-run before continuing.

- [ ] **Step 4: Run ruff format --check**

Run:
```
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
```
Expected: `2 files already formatted` (or equivalent zero-diff output). If a diff is reported, run `python -m ruff format <path>` to apply formatting, then re-run `--check`, then add and commit the formatting change as a separate `style(failure-triage):` commit.

- [ ] **Step 5: Run wc -l to confirm the size budget**

Run (git-bash or WSL):
```
wc -l skills/bmad-story-automator/src/story_automator/core/failure_triage.py
```
Expected: a value well under 500 (likely ≤ 110 for M07a).

- [ ] **Step 6: No new commit required if gates pass cleanly**

The earlier per-task commits already cover the source + tests. Only commit here if step 4 produced formatting fixes:

```bash
git add skills/bmad-story-automator/src/story_automator/core/failure_triage.py tests/test_failure_triage.py
git commit -m "style(failure-triage): apply ruff format" --trailer "Generated-By: claude-opus-4-7"
```

---

## Self-review checklist (run after the plan is implemented end-to-end)

- [ ] REQ-01 covered: module exists at the exact spec path and starts with `from __future__ import annotations` on the first non-comment line. (Task 2.)
- [ ] REQ-02 covered: FailureClass has the 13 named members in declaration order with `name == value`. (Tasks 3–4, regression-locked by Task 11.)
- [ ] REQ-03 covered: Confidence enum HIGH/MEDIUM/LOW, case-sensitive. (Tasks 5–6.)
- [ ] REQ-04 covered: Classification is `@dataclass(frozen=True, kw_only=True)` with the five fields in spec order, types stored as PEP 604 strings under `from __future__ import annotations`. (Tasks 7–8.)
- [ ] REQ-05 covered: IMPLIES_GRAPH contains the three required static edges; the conditional CRASH -> NETWORK_ERROR edge is documented as M07b runtime logic. (Tasks 9–10.)
- [ ] Non-functional — `from __future__ import annotations` on first non-comment line (Task 12 `test_future_annotations_on_first_non_comment_line`), PEP 604 / no `typing.Optional` / no `typing.Union` (Task 12 `test_no_typing_optional_or_union` + Task 7 PEP 604 string-type assertion), LF line endings (Task 12 `test_lf_line_endings`), no third-party imports (Task 12 `test_no_third_party_or_io_imports`), ≤500 LOC (Task 12 `test_module_under_five_hundred_lines`), `__all__` export set (Task 12 `test_all_export_list`).
- [ ] Quality gate — taxonomy completeness + 4-letter placeholder ban — Task 11.
- [ ] Quality gate — ruff check + ruff format --check — Task 13 steps 3–4.
- [ ] No placeholders in the plan: every step has either complete code or a complete shell command with expected output.
- [ ] No type drift between tasks: the same field names (`primary`, `implies`, `confidence`, `reason`, `event_id`) are used in tests (Task 7) and implementation (Task 8) and dataclass-fields assertions (Task 11).
