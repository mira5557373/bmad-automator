# M06a-M2: Spec Compliance (Layer 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the stdlib-only `core/spec_compliance.py` module — two frozen dataclasses (`ReqVerdict`, `ComplianceReport`), one `ComplianceError` exception, and one entry-point function (`check_compliance`) that spawns `claude -p` via `subprocess.run`, injects the spec/diff as fenced code blocks, and returns a per-REQ classification — as the second wedge atom of M06a.

**Architecture:** A single new module `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py` exposing exactly these public symbols: `ReqVerdict`, `ComplianceReport`, `ComplianceError`, `check_compliance` (plus the module logger). Layer 1 (`gap_validator.py`) and Layer 3 (`feature_tester.py`) are NOT imported — the spec quality gate forbids cross-layer imports. The subprocess invocation passes arguments as a list (never `shell=True`), sets `cwd` to a caller-supplied path defaulting to `Path.cwd()`, and injects `LANG=C.UTF-8` into the child environment. Spec text and diff text are wrapped in fenced code blocks before insertion into the prompt; any unresolved four-letter placeholder tokens (`{{XXXX}}` shape) in the spec are escaped so the subprocess never receives a template directive. The subprocess output is parsed as a strict JSON envelope of shape `{"verdicts": [{"req_id": ..., "status": ..., "evidence": ..., "confidence": ...}], "model_invocation_ms": ...}`; any parse failure or non-zero exit or timeout raises `ComplianceError` — never silently downgrades to `missing`. The `diff_sha` field is computed locally as the SHA-256 hex digest of `diff_text` so the report can be cross-referenced without re-hashing.

**Tech Stack:** Python 3.11+ stdlib only (`dataclasses`, `hashlib`, `json`, `logging`, `os`, `pathlib`, `re`, `subprocess`, `typing`). Tests use `unittest.TestCase` with `unittest.mock.patch("subprocess.run")` — every test that touches the subprocess boundary stubs it; any test that would shell out to a real `claude` binary is marked `@unittest.skip` with a recorded reason. No `filelock`, no `psutil`, no third-party imports. No imports from `commands/`, from `core/gap_validator`, or from `core/feature_tester` — Layer 2 must be independently importable per the spec quality gate.

---

## Scope for this sub-milestone

**In scope (from the spec):**
- REQ-07: `ReqVerdict` frozen kw_only dataclass with `req_id`, `status` (Literal `"implemented" | "missing" | "partial"`), `evidence`, `confidence`
- REQ-08: `ComplianceReport` frozen kw_only dataclass with `verdicts`, `spec_path`, `diff_sha`, `model_invocation_ms`
- REQ-09: `check_compliance(*, spec_path: Path, diff_text: str, timeout_s: int = 120, claude_binary: str = "claude") -> ComplianceReport` invoking `subprocess.run` with `check=False`, `text=True`, `capture_output=True`, `timeout=timeout_s`
- REQ-10: `ComplianceError` module-level `Exception` subclass; raised on non-zero exit, timeout, or unparseable output; never silently downgrades a parse failure into a `missing` verdict
- REQ-11: spec text and diff text injected as fenced code blocks; unresolved four-letter placeholder tokens escaped to prevent the subprocess from receiving template directives
- REQ-16: importable in any order, no import-time side effects beyond `logging.getLogger(__name__)`, declare `__all__`
- Non-functional: subprocess list args never `shell=True`, caller-supplied `cwd` defaulting to `Path.cwd()`, `LANG=C.UTF-8` propagated in child env, frozen kw_only dataclasses not subclassing other dataclasses, stdlib-only with no psutil, PEP 604, `from __future__ import annotations`, public-API docstrings stating pre/post/raises, mypy `--strict`
- Quality gates: ruff clean, mypy `--strict` clean, ≥92% line coverage, tests must stub `subprocess.run` via `unittest.mock.patch("subprocess.run")` and never invoke a real model, any subprocess-touching test marked `@unittest.skip` with recorded reason, no imports from `commands/` or other M06a layer modules, diff limited to `core/spec_compliance.py` and `tests/test_spec_compliance.py`

**Out of scope (deferred to later M06a wedges or future milestones):**
- Layer 1 `core/gap_validator.py` (REQ-01..06) — already shipped in M06a-M1.
- Layer 3 `core/feature_tester.py` (REQ-12..15) — M06a-M3.
- The M06b BMAD orchestrator skill markdown.
- HTTP/MCP/API client wrappers — only the single `claude -p` subprocess invocation is allowed.
- Persisting `ComplianceReport` to disk (callers use `core/atomic_io.py` from M05).
- Real-model integration tests (any test that would shell out is `@unittest.skip`-ped with a recorded reason).

---

## File Structure

| File | New / Modified | Responsibility |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py` | Create | `ReqVerdict`, `ComplianceReport`, `ComplianceError`, `check_compliance`, prompt-rendering helper, JSON-envelope parser, module logger, `__all__` |
| `tests/test_spec_compliance.py` | Create | Unit tests: import contract, two dataclass shapes, exception type, prompt rendering (fenced blocks, placeholder escape), `check_compliance` happy path (stubbed `subprocess.run`), error matrix (non-zero exit, timeout, unparseable JSON, missing fields), subprocess argument shape (list args, no shell, cwd, LANG=C.UTF-8 env), `diff_sha` computation, `model_invocation_ms` propagation |

No other files are modified by this sub-milestone — neither `common.py`, nor `gap_validator.py`, nor any existing test file. The spec's "diff limited to" quality gate is enforced in Task 14.

---

## JSON envelope contract (single source of truth — reused across tasks)

`check_compliance` expects the subprocess stdout to deserialize to a JSON object of exactly this shape:

```json
{
  "verdicts": [
    {
      "req_id": "REQ-01",
      "status": "implemented",
      "evidence": "core/gap_validator.py:39 — frozen dataclass with five fields",
      "confidence": 0.9
    }
  ],
  "model_invocation_ms": 4231
}
```

Rules (enforced by the parser):

- The top-level value must be a JSON object containing both `verdicts` (list) and `model_invocation_ms` (int).
- Each verdict must contain all four keys: `req_id` (str), `status` (one of `"implemented"`, `"missing"`, `"partial"`), `evidence` (str), `confidence` (float or int — coerced to float).
- `model_invocation_ms` must be a non-negative integer.
- Any missing field, wrong type, or out-of-set status value raises `ComplianceError` with a field-locating message. The parser never silently substitutes a `"missing"` verdict — REQ-10 forbids that.

`ComplianceReport.spec_path` is the string form of the resolved spec path; `ComplianceReport.diff_sha` is `hashlib.sha256(diff_text.encode("utf-8")).hexdigest()`.

---

## Prompt-rendering contract (single source of truth)

`_render_prompt(spec_text: str, diff_text: str) -> str` returns:

```
You are verifying spec compliance. Compare the diff against the listed REQ-NN
requirements in the spec. Respond with a single JSON object of shape:
{"verdicts": [{"req_id": "...", "status": "implemented|missing|partial",
"evidence": "...", "confidence": 0.0-1.0}], "model_invocation_ms": <int>}.

## Spec

```text
<escaped spec_text>
```

## Diff

```text
<diff_text>
```
```

Placeholder escape rule (REQ-11): any token matching the regex `\{\{[A-Z]{4}\}\}` in `spec_text` is replaced with `{{ESC:<token-body>}}` before the spec is embedded — for example `{{NAME}}` (4-letter body) becomes `{{ESC:NAME}}`. Tokens with non-letter bodies, lowercase bodies, or non-4-letter bodies are left untouched (the spec language explicitly says "four-letter placeholder tokens"). The diff text is NOT escaped — REQ-11 limits the escape to the spec.

---

## Task 1: Module skeleton, `__all__`, import-side-effect test (REQ-16)

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
- Create: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_spec_compliance.py`:

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
        from story_automator.core import spec_compliance  # noqa: F401

    def test_module_declares_all(self) -> None:
        from story_automator.core import spec_compliance

        self.assertEqual(
            sorted(spec_compliance.__all__),
            sorted([
                "ComplianceError",
                "ComplianceReport",
                "ReqVerdict",
                "check_compliance",
            ]),
        )

    def test_import_has_no_stdout_or_stderr_side_effects(self) -> None:
        sys.modules.pop("story_automator.core.spec_compliance", None)
        captured_out = io.StringIO()
        captured_err = io.StringIO()
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = captured_out, captured_err
        try:
            from story_automator.core import spec_compliance  # noqa: F401
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        self.assertEqual(captured_out.getvalue(), "")
        self.assertEqual(captured_err.getvalue(), "")

    def test_module_has_named_logger(self) -> None:
        from story_automator.core import spec_compliance

        self.assertIsInstance(spec_compliance.logger, logging.Logger)
        self.assertEqual(
            spec_compliance.logger.name,
            "story_automator.core.spec_compliance",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'story_automator.core.spec_compliance'`.

- [ ] **Step 3: Create the module skeleton**

Create `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`:

```python
"""Layer 2 of the M06a trust-but-verify stack: spec compliance via `claude -p`.

This module exposes two frozen dataclasses (`ReqVerdict`,
`ComplianceReport`), one exception (`ComplianceError`), and one
entry-point function (`check_compliance`). `check_compliance` spawns
`claude -p` via `subprocess.run` (list args, never `shell=True`),
injects the spec text and diff text into the prompt as fenced code
blocks, and returns a `ComplianceReport` whose per-REQ verdict
classifies each requirement as `"implemented"`, `"missing"`, or
`"partial"`.

Layer 2 is intentionally decoupled from Layer 1 (`gap_validator.py`) and
Layer 3 (`feature_tester.py`): no cross-layer imports, no shared state,
no HTTP/MCP/API clients. The only external boundary is the single
subprocess invocation. The child process inherits a clean environment
overlay that pins `LANG=C.UTF-8` for deterministic locale.
"""

from __future__ import annotations

import logging

__all__ = [
    "ComplianceError",
    "ComplianceReport",
    "ReqVerdict",
    "check_compliance",
]

logger = logging.getLogger(__name__)
```

> NOTE: At this point `ComplianceError`, `ComplianceReport`, `ReqVerdict`, and `check_compliance` are referenced in `__all__` but not yet defined. That is intentional — `__all__` is only consulted by `from module import *`, never on plain `import module`, so the import-contract tests pass. Subsequent tasks add the symbols; Task 12 below adds an explicit symbol-existence assertion that closes the `__all__`-vs-reality gap.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(spec_compliance): add module skeleton, __all__, and import-contract tests"
```

---

## Task 2: `ComplianceError` exception (REQ-10)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec_compliance.py`:

```python
class ComplianceErrorTests(unittest.TestCase):
    """REQ-10: module-level Exception subclass."""

    def test_compliance_error_is_exception_subclass(self) -> None:
        from story_automator.core.spec_compliance import ComplianceError

        self.assertTrue(issubclass(ComplianceError, Exception))

    def test_compliance_error_carries_message(self) -> None:
        from story_automator.core.spec_compliance import ComplianceError

        err = ComplianceError("subprocess exited 2")
        self.assertEqual(str(err), "subprocess exited 2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: FAIL — `ImportError: cannot import name 'ComplianceError'`.

- [ ] **Step 3: Add `ComplianceError`**

Append to `spec_compliance.py`:

```python
class ComplianceError(Exception):
    """Raised when `check_compliance` cannot return a meaningful report.

    Preconditions: caller supplies a single human-readable message.
    Postconditions: instance is a plain `Exception` carrying the message.
    Raises: nothing — this is the exception type itself.

    Raised by `check_compliance` when:
      - the `claude -p` subprocess exits non-zero
      - the subprocess times out (TimeoutExpired)
      - the subprocess stdout cannot be parsed as the expected JSON envelope

    The function MUST NOT silently downgrade a parse failure into a
    `"missing"` verdict — REQ-10 forbids that.
    """
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(spec_compliance): add ComplianceError exception (REQ-10)"
```

---

## Task 3: `ReqVerdict` dataclass (REQ-07)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec_compliance.py`:

```python
import dataclasses


class ReqVerdictDataclassTests(unittest.TestCase):
    """REQ-07: frozen kw_only @dataclass with four fields."""

    def test_req_verdict_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.spec_compliance import ReqVerdict

        self.assertTrue(dataclasses.is_dataclass(ReqVerdict))
        params = ReqVerdict.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_req_verdict_field_names(self) -> None:
        from story_automator.core.spec_compliance import ReqVerdict

        names = sorted(f.name for f in dataclasses.fields(ReqVerdict))
        self.assertEqual(
            names, ["confidence", "evidence", "req_id", "status"],
        )

    def test_req_verdict_construction_requires_keyword_args(self) -> None:
        from story_automator.core.spec_compliance import ReqVerdict

        with self.assertRaises(TypeError):
            ReqVerdict("REQ-01", "implemented", "", 0.9)  # type: ignore[misc]

    def test_req_verdict_instances_are_immutable(self) -> None:
        from story_automator.core.spec_compliance import ReqVerdict

        v = ReqVerdict(
            req_id="REQ-01", status="implemented",
            evidence="seen", confidence=0.9,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            v.status = "missing"  # type: ignore[misc]

    def test_req_verdict_does_not_subclass_other_dataclasses(self) -> None:
        # NFR: dataclasses must not subclass other dataclasses.
        from story_automator.core.spec_compliance import ReqVerdict

        ancestors = [
            base for base in ReqVerdict.__mro__
            if base is not ReqVerdict and base is not object
        ]
        for base in ancestors:
            self.assertFalse(
                dataclasses.is_dataclass(base),
                f"ReqVerdict unexpectedly inherits from dataclass {base!r}",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: FAIL — `ImportError: cannot import name 'ReqVerdict'`.

- [ ] **Step 3: Add the `ReqVerdict` dataclass**

Add the import and the dataclass to `spec_compliance.py`. The final import block becomes:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
```

Append below `logger`:

```python
@dataclass(frozen=True, kw_only=True)
class ReqVerdict:
    """Verdict for one REQ from the spec compared against the diff.

    Preconditions: `req_id` is a non-empty string (e.g. "REQ-07");
        `status` is exactly one of "implemented", "missing", "partial";
        `evidence` is a human-readable string (may be empty);
        `confidence` lies in `[0.0, 1.0]`. The dataclass itself does not
        enforce these constraints — `_parse_envelope` (Task 7) does so
        before constructing instances.
    Postconditions: instance is frozen; all four fields are present.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    req_id: str
    status: Literal["implemented", "missing", "partial"]
    evidence: str
    confidence: float
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(spec_compliance): add frozen kw_only ReqVerdict dataclass (REQ-07)"
```

---

## Task 4: `ComplianceReport` dataclass (REQ-08)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec_compliance.py`:

```python
class ComplianceReportDataclassTests(unittest.TestCase):
    """REQ-08: frozen kw_only @dataclass with four fields."""

    def test_compliance_report_is_frozen_kw_only_dataclass(self) -> None:
        from story_automator.core.spec_compliance import ComplianceReport

        self.assertTrue(dataclasses.is_dataclass(ComplianceReport))
        params = ComplianceReport.__dataclass_params__
        self.assertTrue(params.frozen)
        self.assertTrue(params.kw_only)

    def test_compliance_report_field_names(self) -> None:
        from story_automator.core.spec_compliance import ComplianceReport

        names = sorted(f.name for f in dataclasses.fields(ComplianceReport))
        self.assertEqual(
            names,
            ["diff_sha", "model_invocation_ms", "spec_path", "verdicts"],
        )

    def test_compliance_report_construction(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceReport,
            ReqVerdict,
        )

        v = ReqVerdict(
            req_id="REQ-01", status="implemented",
            evidence="seen", confidence=0.9,
        )
        r = ComplianceReport(
            verdicts=[v],
            spec_path="docs/foo.md",
            diff_sha="deadbeef",
            model_invocation_ms=4231,
        )
        self.assertEqual(r.verdicts, [v])
        self.assertEqual(r.spec_path, "docs/foo.md")
        self.assertEqual(r.diff_sha, "deadbeef")
        self.assertEqual(r.model_invocation_ms, 4231)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: FAIL — `ImportError: cannot import name 'ComplianceReport'`.

- [ ] **Step 3: Add the `ComplianceReport` dataclass**

Append to `spec_compliance.py`:

```python
@dataclass(frozen=True, kw_only=True)
class ComplianceReport:
    """Aggregate report from `check_compliance`.

    Preconditions: `verdicts` is a list (possibly empty); `spec_path` is
        the string form of the spec file path (typically the resolved
        absolute path); `diff_sha` is the SHA-256 hex digest of the diff
        text passed to `check_compliance`; `model_invocation_ms` is a
        non-negative integer reported by the subprocess.
    Postconditions: instance is frozen. Note: `frozen=True` does not
        deep-freeze `verdicts` — callers must treat it as read-only.
    Raises: TypeError if constructed with positional args (kw_only).
    """

    verdicts: list[ReqVerdict]
    spec_path: str
    diff_sha: str
    model_invocation_ms: int
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(spec_compliance): add frozen kw_only ComplianceReport dataclass (REQ-08)"
```

---

## Task 5: Prompt rendering — fenced blocks + four-letter placeholder escape (REQ-11)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spec_compliance.py`:

```python
class PromptRenderingTests(unittest.TestCase):
    """REQ-11: spec/diff embedded as fenced code blocks, four-letter
    placeholder tokens escaped in the spec only."""

    def test_render_prompt_wraps_spec_in_fenced_block(self) -> None:
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="hello", diff_text="world")
        self.assertIn("## Spec\n\n```text\nhello\n```", out)

    def test_render_prompt_wraps_diff_in_fenced_block(self) -> None:
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="spec body", diff_text="diff body")
        self.assertIn("## Diff\n\n```text\ndiff body\n```", out)

    def test_render_prompt_escapes_four_letter_uppercase_placeholder(self) -> None:
        # REQ-11: {{NAME}} (4-letter uppercase body) must be escaped.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="Hello {{NAME}}!", diff_text="d")
        self.assertIn("{{ESC:NAME}}", out)
        self.assertNotIn("{{NAME}}", out)

    def test_render_prompt_does_not_escape_three_letter_token(self) -> None:
        # "four-letter" means exactly four — leave others alone.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="Hello {{HI}}", diff_text="d")
        self.assertIn("{{HI}}", out)
        self.assertNotIn("ESC:HI", out)

    def test_render_prompt_does_not_escape_lowercase_token(self) -> None:
        # Spec says "four-letter" — interpret as uppercase letters
        # (the BMAD template convention). Lowercase identifiers are
        # human prose, not template directives.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="Hello {{name}}", diff_text="d")
        self.assertIn("{{name}}", out)
        self.assertNotIn("ESC:name", out)

    def test_render_prompt_does_not_escape_diff_tokens(self) -> None:
        # REQ-11 scopes the escape to the spec; diff is verbatim.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="clean", diff_text="diff has {{NAME}}")
        self.assertIn("{{NAME}}", out)
        self.assertNotIn("ESC:NAME", out)

    def test_render_prompt_states_expected_json_shape(self) -> None:
        # The model must be told which JSON envelope to return.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="s", diff_text="d")
        self.assertIn("verdicts", out)
        self.assertIn("model_invocation_ms", out)

    def test_render_prompt_forbids_markdown_fences_in_response(self) -> None:
        # Real claude -p often wraps JSON in ```json fences by default.
        # The prompt must instruct otherwise, else `_parse_envelope`
        # raises ComplianceError on the fenced output. This test pins
        # the contract so a future header edit can't quietly drop the
        # instruction.
        from story_automator.core.spec_compliance import _render_prompt

        out = _render_prompt(spec_text="s", diff_text="d")
        self.assertRegex(out, r"no markdown fences")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: FAIL — `ImportError: cannot import name '_render_prompt'`. (Tests reach into a private helper because REQ-11 names a behavior that has to be verified deterministically without invoking `check_compliance`.)

- [ ] **Step 3: Implement `_render_prompt` and the escape helper**

Add `import re` to the import block. The final import block becomes:

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal
```

Append below `ComplianceReport`:

```python
_PLACEHOLDER_RE: re.Pattern[str] = re.compile(r"\{\{([A-Z]{4})\}\}")


def _escape_placeholders(spec_text: str) -> str:
    """Replace four-letter uppercase `{{XXXX}}` tokens with `{{ESC:XXXX}}`.

    REQ-11: unresolved four-letter placeholder tokens in the spec must
    be escaped so the subprocess does not treat them as template
    directives intended for human authoring.
    """
    return _PLACEHOLDER_RE.sub(r"{{ESC:\1}}", spec_text)


_PROMPT_HEADER: str = (
    "You are verifying spec compliance. Compare the diff against the listed "
    "REQ-NN requirements in the spec. Output ONLY a single raw JSON object — "
    "no markdown fences, no preamble, no trailing prose — of shape: "
    '{"verdicts": [{"req_id": "...", "status": "implemented|missing|partial", '
    '"evidence": "...", "confidence": 0.0-1.0}], "model_invocation_ms": <int>}.'
)


def _render_prompt(*, spec_text: str, diff_text: str) -> str:
    """Render the `claude -p` prompt with fenced code blocks.

    Preconditions: `spec_text` and `diff_text` are strings (may be empty).
    Postconditions: returned string contains the prompt header, a fenced
        `## Spec` block holding `_escape_placeholders(spec_text)`, and a
        fenced `## Diff` block holding `diff_text` verbatim.
    Raises: nothing.
    """
    safe_spec = _escape_placeholders(spec_text)
    return (
        f"{_PROMPT_HEADER}\n\n"
        f"## Spec\n\n```text\n{safe_spec}\n```\n\n"
        f"## Diff\n\n```text\n{diff_text}\n```\n"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (22 tests). Subsequent task expected-counts shift up by one accordingly.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(spec_compliance): render prompt with fenced blocks and placeholder escape (REQ-11)"
```

---

## Task 6: JSON envelope parser (REQ-09 partial + REQ-10)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spec_compliance.py`:

```python
class EnvelopeParserHappyPathTests(unittest.TestCase):
    """REQ-09: parse the model's JSON envelope into ReqVerdict list."""

    def test_parses_single_verdict(self) -> None:
        from story_automator.core.spec_compliance import _parse_envelope

        payload = (
            '{"verdicts": ['
            '{"req_id": "REQ-01", "status": "implemented", '
            '"evidence": "seen at core/a.py:1", "confidence": 0.9}'
            '], "model_invocation_ms": 4231}'
        )
        verdicts, ms = _parse_envelope(payload)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].req_id, "REQ-01")
        self.assertEqual(verdicts[0].status, "implemented")
        self.assertEqual(verdicts[0].evidence, "seen at core/a.py:1")
        self.assertAlmostEqual(verdicts[0].confidence, 0.9)
        self.assertEqual(ms, 4231)

    def test_coerces_integer_confidence_to_float(self) -> None:
        from story_automator.core.spec_compliance import _parse_envelope

        payload = (
            '{"verdicts": ['
            '{"req_id": "REQ-02", "status": "partial", '
            '"evidence": "", "confidence": 1}'
            '], "model_invocation_ms": 0}'
        )
        verdicts, ms = _parse_envelope(payload)
        self.assertIsInstance(verdicts[0].confidence, float)
        self.assertEqual(verdicts[0].confidence, 1.0)
        self.assertEqual(ms, 0)


class EnvelopeParserErrorTests(unittest.TestCase):
    """REQ-10: parse failure raises ComplianceError, never downgrades."""

    def test_malformed_json_raises_compliance_error(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "not valid JSON"):
            _parse_envelope("{not json")

    def test_non_object_top_level_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "top-level JSON object"):
            _parse_envelope("[]")

    def test_missing_verdicts_key_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "'verdicts'"):
            _parse_envelope('{"model_invocation_ms": 0}')

    def test_missing_model_invocation_ms_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "model_invocation_ms"):
            _parse_envelope('{"verdicts": []}')

    def test_non_list_verdicts_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "'verdicts' must be a"):
            _parse_envelope('{"verdicts": {}, "model_invocation_ms": 0}')

    def test_missing_verdict_field_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        payload = (
            '{"verdicts": [{"req_id": "REQ-01", "status": "implemented", '
            '"evidence": "x"}], "model_invocation_ms": 0}'
        )
        with self.assertRaisesRegex(ComplianceError, "'confidence'"):
            _parse_envelope(payload)

    def test_unknown_status_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        payload = (
            '{"verdicts": [{"req_id": "REQ-01", "status": "maybe", '
            '"evidence": "", "confidence": 0.5}], "model_invocation_ms": 0}'
        )
        with self.assertRaisesRegex(ComplianceError, "status must be one of"):
            _parse_envelope(payload)

    def test_negative_model_invocation_ms_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "non-negative"):
            _parse_envelope('{"verdicts": [], "model_invocation_ms": -1}')

    def test_non_integer_model_invocation_ms_raises(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        with self.assertRaisesRegex(ComplianceError, "model_invocation_ms"):
            _parse_envelope(
                '{"verdicts": [], "model_invocation_ms": "fast"}'
            )

    def test_parser_never_silently_downgrades_to_missing(self) -> None:
        # REQ-10 explicit guarantee: a malformed envelope must NOT be
        # converted into a "missing" verdict. Assert by checking that
        # the parser raises rather than returning a list.
        from story_automator.core.spec_compliance import (
            ComplianceError,
            _parse_envelope,
        )

        try:
            _parse_envelope("not json at all")
        except ComplianceError:
            return
        self.fail(
            "parser silently produced a verdict instead of raising "
            "ComplianceError on unparseable input — REQ-10 forbids that"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: FAIL — `ImportError: cannot import name '_parse_envelope'`.

- [ ] **Step 3: Implement `_parse_envelope`**

Add `import json` to the import block. The final import block becomes:

```python
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal
```

Append below `_render_prompt`:

```python
_ALLOWED_STATUSES: frozenset[str] = frozenset(
    {"implemented", "missing", "partial"},
)
_REQUIRED_VERDICT_KEYS: tuple[str, ...] = (
    "req_id", "status", "evidence", "confidence",
)


def _parse_envelope(payload: str) -> tuple[list[ReqVerdict], int]:
    """Parse the subprocess stdout into `(verdicts, model_invocation_ms)`.

    Preconditions: `payload` is the raw stdout from the subprocess.
    Postconditions: returns a tuple of `(list[ReqVerdict], int)` whose
        verdicts preserve the input order and whose integer is the
        non-negative `model_invocation_ms` field.
    Raises: `ComplianceError` (REQ-10) when the payload is not valid
        JSON, when the top-level value is not an object, when a required
        key is missing or wrongly typed, when `status` is outside the
        allowed set, or when `model_invocation_ms` is negative or
        non-integer. The function NEVER silently substitutes a
        "missing" verdict on a parse failure.
    """
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ComplianceError(
            f"subprocess output is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ComplianceError(
            "subprocess output must be a top-level JSON object"
        )
    if "verdicts" not in data:
        raise ComplianceError("envelope missing required key 'verdicts'")
    if "model_invocation_ms" not in data:
        raise ComplianceError(
            "envelope missing required key 'model_invocation_ms'"
        )
    raw_verdicts = data["verdicts"]
    if not isinstance(raw_verdicts, list):
        raise ComplianceError("'verdicts' must be a JSON array")
    ms = data["model_invocation_ms"]
    # `bool` is a subclass of `int`; reject explicitly so `true` does
    # not silently parse as `1`.
    if isinstance(ms, bool) or not isinstance(ms, int):
        raise ComplianceError(
            f"model_invocation_ms must be an integer, got "
            f"{type(ms).__name__}"
        )
    if ms < 0:
        raise ComplianceError(
            f"model_invocation_ms must be non-negative, got {ms}"
        )

    verdicts: list[ReqVerdict] = []
    for index, raw in enumerate(raw_verdicts):
        if not isinstance(raw, dict):
            raise ComplianceError(
                f"verdicts[{index}] must be a JSON object"
            )
        for key in _REQUIRED_VERDICT_KEYS:
            if key not in raw:
                raise ComplianceError(
                    f"verdicts[{index}] missing required key {key!r}"
                )
        status = raw["status"]
        if status not in _ALLOWED_STATUSES:
            raise ComplianceError(
                f"verdicts[{index}].status must be one of "
                f"{sorted(_ALLOWED_STATUSES)!r}, got {status!r}"
            )
        confidence_raw = raw["confidence"]
        if isinstance(confidence_raw, bool) or not isinstance(
            confidence_raw, (int, float),
        ):
            raise ComplianceError(
                f"verdicts[{index}].confidence must be a number, got "
                f"{type(confidence_raw).__name__}"
            )
        verdicts.append(
            ReqVerdict(
                req_id=str(raw["req_id"]),
                status=status,
                evidence=str(raw["evidence"]),
                confidence=float(confidence_raw),
            )
        )
    return verdicts, ms
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (33 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(spec_compliance): implement strict JSON envelope parser (REQ-09, REQ-10)"
```

---

## Task 7: `check_compliance` happy path with stubbed subprocess (REQ-09)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spec_compliance.py`:

```python
import hashlib
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch


def _ok_completed_process(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["claude", "-p", "..."], returncode=0, stdout=stdout, stderr="",
    )


_SAMPLE_ENVELOPE = (
    '{"verdicts": ['
    '{"req_id": "REQ-01", "status": "implemented", '
    '"evidence": "core/a.py:1", "confidence": 0.9}'
    '], "model_invocation_ms": 4231}'
)


class CheckComplianceHappyPathTests(unittest.TestCase):
    """REQ-09: subprocess.run is invoked, stdout is parsed, report is built."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.spec = self.root / "spec.md"
        self.spec.write_text("# REQ-01 do thing\n", encoding="utf-8")

    def test_returns_compliance_report_with_parsed_verdicts(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceReport,
            check_compliance,
        )

        with patch(
            "subprocess.run",
            return_value=_ok_completed_process(_SAMPLE_ENVELOPE),
        ):
            report = check_compliance(
                spec_path=self.spec, diff_text="--- a/x\n+++ b/x\n",
            )

        self.assertIsInstance(report, ComplianceReport)
        self.assertEqual(len(report.verdicts), 1)
        self.assertEqual(report.verdicts[0].req_id, "REQ-01")
        self.assertEqual(report.verdicts[0].status, "implemented")
        self.assertEqual(report.model_invocation_ms, 4231)

    def test_spec_path_is_string_form_of_resolved_path(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch(
            "subprocess.run",
            return_value=_ok_completed_process(_SAMPLE_ENVELOPE),
        ):
            report = check_compliance(spec_path=self.spec, diff_text="d")
        self.assertEqual(report.spec_path, str(self.spec.resolve()))

    def test_diff_sha_is_sha256_of_diff_text(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
        expected_sha = hashlib.sha256(diff.encode("utf-8")).hexdigest()
        with patch(
            "subprocess.run",
            return_value=_ok_completed_process(_SAMPLE_ENVELOPE),
        ):
            report = check_compliance(spec_path=self.spec, diff_text=diff)
        self.assertEqual(report.diff_sha, expected_sha)

    def test_spec_text_is_read_from_disk_and_embedded_in_prompt(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        self.spec.write_text(
            "# Spec body unique-marker-xyz\n", encoding="utf-8",
        )
        captured: dict[str, object] = {}

        def fake_run(*args: object, **kwargs: object) -> object:
            captured["args"] = args
            captured["kwargs"] = kwargs
            captured["input"] = kwargs.get("input")
            return _ok_completed_process(_SAMPLE_ENVELOPE)

        with patch("subprocess.run", side_effect=fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")

        prompt = captured["input"]
        assert isinstance(prompt, str)
        self.assertIn("unique-marker-xyz", prompt)
        self.assertIn("```text\n", prompt)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: FAIL — `ImportError: cannot import name 'check_compliance'`.

- [ ] **Step 3: Implement `check_compliance` happy path**

Add the necessary imports — the final import block becomes:

```python
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
```

Append below `_parse_envelope`:

```python
_DEFAULT_TIMEOUT_S: int = 120


def check_compliance(
    *,
    spec_path: Path,
    diff_text: str,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
    claude_binary: str = "claude",
    cwd: Path | None = None,
) -> ComplianceReport:
    """Verify a candidate diff against the REQs declared in `spec_path`.

    Preconditions: `spec_path` must point to a readable UTF-8 file
        (typically a Markdown spec containing REQ-NN sections);
        `diff_text` is the candidate diff as a string; `timeout_s` is a
        positive integer; `claude_binary` is the executable name (or
        path) of the `claude` CLI; `cwd`, when provided, is an existing
        directory used as the subprocess working directory — otherwise
        the current working directory is used.
    Postconditions: returns a `ComplianceReport` whose `verdicts` reflect
        the model's classification of each REQ; `spec_path` is the
        resolved absolute path as a string; `diff_sha` is the SHA-256
        hex digest of `diff_text` encoded as UTF-8; `model_invocation_ms`
        is propagated verbatim from the subprocess envelope.
    Raises: `ComplianceError` (REQ-10) when the subprocess exits
        non-zero, when it times out, or when its stdout cannot be parsed
        as the JSON envelope `_parse_envelope` expects. This function
        NEVER silently downgrades a parse failure into a "missing"
        verdict — REQ-10 forbids that.
    """
    resolved_spec = spec_path.resolve()
    spec_text = resolved_spec.read_text(encoding="utf-8")
    prompt = _render_prompt(spec_text=spec_text, diff_text=diff_text)

    effective_cwd = cwd if cwd is not None else Path.cwd()
    child_env = {**os.environ, "LANG": "C.UTF-8"}

    try:
        completed = subprocess.run(
            [claude_binary, "-p"],
            input=prompt,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            cwd=str(effective_cwd),
            env=child_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ComplianceError(
            f"`{claude_binary} -p` timed out after {timeout_s}s"
        ) from exc

    if completed.returncode != 0:
        raise ComplianceError(
            f"`{claude_binary} -p` exited {completed.returncode}: "
            f"{(completed.stderr or '').strip()[:500]}"
        )

    verdicts, ms = _parse_envelope(completed.stdout)
    diff_sha = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
    return ComplianceReport(
        verdicts=verdicts,
        spec_path=str(resolved_spec),
        diff_sha=diff_sha,
        model_invocation_ms=ms,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (37 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(spec_compliance): implement check_compliance happy path with stubbed subprocess (REQ-09)"
```

---

## Task 8: `check_compliance` error matrix — non-zero exit, timeout, parse failure (REQ-10)

**Files:**
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spec_compliance.py`:

```python
class CheckComplianceErrorMatrixTests(unittest.TestCase):
    """REQ-10: non-zero exit, timeout, and parse failure raise
    ComplianceError. Never silently downgrade."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.spec = self.root / "spec.md"
        self.spec.write_text("# REQ-01\n", encoding="utf-8")

    def test_non_zero_exit_raises_compliance_error(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        failed = subprocess.CompletedProcess(
            args=["claude", "-p"], returncode=2,
            stdout="", stderr="boom",
        )
        with (
            patch("subprocess.run", return_value=failed),
            self.assertRaisesRegex(ComplianceError, "exited 2"),
        ):
            check_compliance(spec_path=self.spec, diff_text="d")

    def test_non_zero_exit_includes_stderr_excerpt(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        failed = subprocess.CompletedProcess(
            args=["claude", "-p"], returncode=1,
            stdout="", stderr="auth failed: please login",
        )
        with patch("subprocess.run", return_value=failed):
            try:
                check_compliance(spec_path=self.spec, diff_text="d")
            except ComplianceError as exc:
                self.assertIn("auth failed", str(exc))
            else:
                self.fail("expected ComplianceError")

    def test_timeout_raises_compliance_error(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        def fake_run(*args: object, **kwargs: object) -> object:
            raise subprocess.TimeoutExpired(
                cmd=["claude", "-p"], timeout=120,
            )

        with (
            patch("subprocess.run", side_effect=fake_run),
            self.assertRaisesRegex(ComplianceError, "timed out"),
        ):
            check_compliance(spec_path=self.spec, diff_text="d")

    def test_unparseable_stdout_raises_compliance_error(self) -> None:
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        ok_but_bad = subprocess.CompletedProcess(
            args=["claude", "-p"], returncode=0,
            stdout="not json at all", stderr="",
        )
        with (
            patch("subprocess.run", return_value=ok_but_bad),
            self.assertRaisesRegex(ComplianceError, "not valid JSON"),
        ):
            check_compliance(spec_path=self.spec, diff_text="d")

    def test_parse_failure_never_downgrades_to_missing_verdict(self) -> None:
        # REQ-10 explicit guarantee. We verified _parse_envelope in
        # Task 6; here we verify the public surface honours the same.
        from story_automator.core.spec_compliance import (
            ComplianceError,
            check_compliance,
        )

        ok_but_bad = subprocess.CompletedProcess(
            args=["claude", "-p"], returncode=0,
            stdout='{"unrelated": "shape"}', stderr="",
        )
        with patch("subprocess.run", return_value=ok_but_bad):
            try:
                check_compliance(spec_path=self.spec, diff_text="d")
            except ComplianceError:
                return
        self.fail(
            "check_compliance silently produced a report instead of "
            "raising on unparseable envelope — REQ-10 forbids that"
        )

    def test_timeout_propagates_configured_timeout_seconds(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        captured: dict[str, object] = {}

        def fake_run(*args: object, **kwargs: object) -> object:
            captured.update(kwargs)
            return _ok_completed_process(_SAMPLE_ENVELOPE)

        with patch("subprocess.run", side_effect=fake_run):
            check_compliance(
                spec_path=self.spec, diff_text="d", timeout_s=7,
            )
        self.assertEqual(captured.get("timeout"), 7)
```

- [ ] **Step 2: Run tests to verify they pass (Task 7 already implements the error paths)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (43 tests). If any test fails, fix the corresponding branch in `check_compliance` — do not loosen the assertion. (The most likely fix: ensure the `stderr` excerpt is included verbatim in the non-zero-exit message; the parse-failure path re-raises the `ComplianceError` from `_parse_envelope` unchanged.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(spec_compliance): cover error matrix for non-zero exit, timeout, parse failure (REQ-10)"
```

---

## Task 9: Subprocess invocation shape — list args, no shell, cwd, LANG=C.UTF-8 (NFR)

**Files:**
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spec_compliance.py`:

```python
class SubprocessInvocationShapeTests(unittest.TestCase):
    """NFR: list args, never shell=True, caller-supplied cwd defaulting
    to Path.cwd(), LANG=C.UTF-8 propagated in child env."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.spec = self.root / "spec.md"
        self.spec.write_text("# REQ-01\n", encoding="utf-8")
        self.captured: dict[str, object] = {}

        def fake_run(*args: object, **kwargs: object) -> object:
            self.captured["args"] = args
            self.captured.update(kwargs)
            return _ok_completed_process(_SAMPLE_ENVELOPE)

        self._fake_run = fake_run

    def test_subprocess_args_are_list_not_string(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        positional = self.captured["args"]
        assert isinstance(positional, tuple)
        self.assertIsInstance(positional[0], list)
        self.assertEqual(positional[0][0], "claude")
        self.assertIn("-p", positional[0])

    def test_subprocess_never_uses_shell(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        # `shell` MUST NOT be set to True; we accept absent or False.
        self.assertNotEqual(self.captured.get("shell"), True)

    def test_subprocess_uses_check_false_and_captures_text_output(self) -> None:
        # REQ-09 explicit: check=False, text=True, capture_output=True.
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        self.assertEqual(self.captured.get("check"), False)
        self.assertEqual(self.captured.get("text"), True)
        self.assertEqual(self.captured.get("capture_output"), True)

    def test_cwd_defaults_to_current_working_directory(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        self.assertEqual(self.captured.get("cwd"), str(Path.cwd()))

    def test_cwd_can_be_overridden_by_caller(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(
                spec_path=self.spec, diff_text="d", cwd=self.root,
            )
        self.assertEqual(self.captured.get("cwd"), str(self.root))

    def test_env_propagates_lang_c_utf8(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(spec_path=self.spec, diff_text="d")
        env = self.captured.get("env")
        self.assertIsInstance(env, dict)
        assert isinstance(env, dict)
        self.assertEqual(env.get("LANG"), "C.UTF-8")
        # PATH must still be present so the child can locate `claude`.
        self.assertIn("PATH", env)

    def test_claude_binary_argument_overrides_executable(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with patch("subprocess.run", side_effect=self._fake_run):
            check_compliance(
                spec_path=self.spec, diff_text="d",
                claude_binary="/usr/local/bin/claude",
            )
        positional = self.captured["args"]
        assert isinstance(positional, tuple)
        self.assertEqual(positional[0][0], "/usr/local/bin/claude")
```

- [ ] **Step 2: Run tests to verify they pass (Task 7 already implements the shape)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (50 tests). If `test_env_propagates_lang_c_utf8` fails because `PATH` is missing, the implementation built `env` from scratch instead of overlaying `os.environ` — fix by merging `os.environ` first, then setting `LANG=C.UTF-8`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(spec_compliance): assert subprocess argument shape, cwd, and LANG=C.UTF-8 (NFR)"
```

---

## Task 10: Real-model integration test — skipped with recorded reason

**Files:**
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Add the skipped test as documentation of the gate**

The spec quality gate says: *"any subprocess-touching test marked `@unittest.skip` with a recorded reason"*. We add exactly one such test as documentation of the boundary — every real-model invocation lives here, behind the skip, so a future operator wanting to run it end-to-end can do so locally.

Append to `tests/test_spec_compliance.py`:

```python
class RealModelIntegrationTests(unittest.TestCase):
    """Boundary tests that WOULD shell out to a real `claude` binary.

    Quality gate: every test that would actually invoke the model is
    marked `@unittest.skip` with a recorded reason so CI never spends
    real credits and never depends on developer login state.
    """

    @unittest.skip(
        "REASON: invokes real `claude -p` binary — costs credits and "
        "requires developer login. Run manually with `unittest "
        "--no-skip` for end-to-end smoke."
    )
    def test_real_claude_subprocess_round_trip(self) -> None:  # pragma: no cover
        # If you remove the skip, this test will actually call the model.
        # Do NOT remove the skip in CI. The test body is intentionally
        # minimal — its purpose is to document the boundary, not to
        # provide functional coverage (that's the stubbed tests above).
        from story_automator.core.spec_compliance import check_compliance

        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "spec.md"
            spec.write_text(
                "## Functional requirements\n- REQ-01 do thing\n",
                encoding="utf-8",
            )
            report = check_compliance(
                spec_path=spec,
                diff_text="--- a/x\n+++ b/x\n",
                timeout_s=30,
            )
            self.assertGreaterEqual(len(report.verdicts), 0)
```

- [ ] **Step 2: Run the suite and confirm the test is skipped**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS with one skipped test (`test_real_claude_subprocess_round_trip ... skipped 'REASON: invokes real ...'`). Total: 51 entries, 50 passing + 1 skipped.

- [ ] **Step 3: Commit**

```bash
git add tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(spec_compliance): document real-model boundary as skipped test (quality gate)"
```

---

## Task 11: Spec file missing → IO error surfaces cleanly

**Files:**
- Modify: `tests/test_spec_compliance.py`

The spec is silent on what happens when `spec_path` does not exist. The natural Python answer is `FileNotFoundError` from `read_text` — we let that surface to the caller (it is not a *compliance* error, it is a *bad input* error). This task pins that contract with a test so future refactors do not silently swallow the IO error.

- [ ] **Step 1: Write the test**

Append to `tests/test_spec_compliance.py`:

```python
class SpecPathErrorTests(unittest.TestCase):
    """Bad input (missing spec) raises FileNotFoundError — NOT
    ComplianceError. Compliance errors are reserved for subprocess
    boundary failures (REQ-10)."""

    def test_missing_spec_path_raises_file_not_found(self) -> None:
        from story_automator.core.spec_compliance import check_compliance

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.md"
            with self.assertRaises(FileNotFoundError):
                check_compliance(spec_path=missing, diff_text="d")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (52 entries, 51 passing + 1 skipped).

- [ ] **Step 3: Commit**

```bash
git add tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(spec_compliance): pin FileNotFoundError contract for missing spec_path"
```

---

## Task 12: Symbol existence assertion + forbidden-import audit (REQ-16, quality)

**Files:**
- Modify: `tests/test_spec_compliance.py`

- [ ] **Step 1: Write the tests**

Append to `tests/test_spec_compliance.py`:

```python
class AllSymbolsActuallyDefinedTests(unittest.TestCase):
    """REQ-16: every name in `__all__` must actually be defined.

    The Task 1 import-contract test only checks `__all__` membership;
    this test closes the gap by asserting each declared name resolves
    to a real attribute on the module.
    """

    def test_each_all_symbol_resolves(self) -> None:
        from story_automator.core import spec_compliance

        for name in spec_compliance.__all__:
            self.assertTrue(
                hasattr(spec_compliance, name),
                f"__all__ advertises {name!r} but the module has no "
                f"such attribute",
            )

    def test_no_unrelated_layer_imports(self) -> None:
        """Quality gate: no import from other M06a layers or from commands/."""
        import inspect

        from story_automator.core import spec_compliance

        source = inspect.getsource(spec_compliance)
        for forbidden in (
            "from .gap_validator",
            "from .feature_tester",
            "from story_automator.commands",
            "from ..commands",
        ):
            self.assertNotIn(forbidden, source)

    def test_no_psutil_import(self) -> None:
        # NFR: stdlib-only with no psutil.
        import inspect

        from story_automator.core import spec_compliance

        source = inspect.getsource(spec_compliance)
        self.assertNotIn("import psutil", source)
        self.assertNotIn("from psutil", source)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v`
Expected: PASS (55 entries, 54 passing + 1 skipped).

- [ ] **Step 3: Commit**

```bash
git add tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(spec_compliance): assert __all__ resolves and forbidden imports absent (REQ-16, NFR)"
```

---

## Task 13: `mypy --strict`, ruff, and module-size gates

**Files:**
- Inspect (no edits unless gates fail): `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`, `tests/test_spec_compliance.py`

- [ ] **Step 1: Ruff check**

Run: `python -m ruff check skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py`
Expected: exit 0. Fix source — do not add `# noqa` without an inline rationale.

- [ ] **Step 2: Ruff format check**

Run: `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py`
If it fails: `python -m ruff format skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py` then re-run the check.

- [ ] **Step 3: mypy --strict**

Bash / git-bash:

```bash
MYPYPATH=skills/bmad-story-automator/src python -m mypy --strict --explicit-package-bases \
  skills/bmad-story-automator/src/story_automator/core/spec_compliance.py
```

PowerShell:

```powershell
$env:MYPYPATH = "skills/bmad-story-automator/src"
python -m mypy --strict --explicit-package-bases `
  skills/bmad-story-automator/src/story_automator/core/spec_compliance.py
Remove-Item Env:MYPYPATH
```

Expected: `Success: no issues found`.

Common fixes if mypy fails:
- Missing return annotation on a private helper → add `-> str`, `-> tuple[list[ReqVerdict], int]`, etc.
- `subprocess.CompletedProcess[str]` parameterization on Python 3.11 — Python 3.11 supports the generic form; do NOT add `# type: ignore`.
- `# type: ignore` may only be introduced with an adjacent justification comment (NFR).

- [ ] **Step 4: Module size guardrail**

PowerShell: `(Get-Content skills/bmad-story-automator/src/story_automator/core/spec_compliance.py | Measure-Object -Line).Lines`
Bash: `wc -l skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
Expected: ≤ 500 source lines (target: well under 350).

- [ ] **Step 5: Import allowlist audit**

PowerShell: `Select-String -Path skills/bmad-story-automator/src/story_automator/core/spec_compliance.py -Pattern '^(import|from) '`
Bash: `grep -E "^(import|from) " skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`

Expected — exactly these imports, all stdlib:
- `from __future__ import annotations`
- `import hashlib`
- `import json`
- `import logging`
- `import os`
- `import re`
- `import subprocess`
- `from dataclasses import dataclass`
- `from pathlib import Path`
- `from typing import Literal`

No `psutil`, no `filelock`, no `from .gap_validator`, no `from .feature_tester`, no `from ..commands`, no `from .common` (Layer 2 must be independently importable — it does not need `iso_now` because the spec does not require a `validated_at` field).

- [ ] **Step 6: Commit any formatting/typing fixes**

If Steps 1–5 produced edits:

```bash
git add skills/bmad-story-automator/src/story_automator/core/spec_compliance.py tests/test_spec_compliance.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(spec_compliance): ruff format + mypy --strict pass"
```

If no fixes were needed, skip — do not create an empty commit.

---

## Task 14: Coverage gate (≥92%) and final diff-scope audit

**Files:** none modified.

- [ ] **Step 1: Coverage run**

Run from the repo root:

Bash:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/spec_compliance \
  -m unittest tests.test_spec_compliance
python -m coverage report -m --fail-under=92
```

PowerShell:

```powershell
$env:PYTHONPATH = "skills/bmad-story-automator/src"
python -m coverage run `
  --source=skills/bmad-story-automator/src/story_automator/core/spec_compliance `
  -m unittest tests.test_spec_compliance
python -m coverage report -m --fail-under=92
Remove-Item Env:PYTHONPATH
```

Expected: PASS with line coverage ≥ 92%.

If a branch is uncovered, add a focused negative-path test rather than lowering the gate. Only mark an irrelevant line with `# pragma: no cover` if there is no reasonable test for it (e.g. the body of the skipped real-model test, which already carries the pragma) — and any new pragma MUST carry a same-line `# rationale: <one-line explanation>` comment.

- [ ] **Step 2: Full Python suite regression check**

Run: `npm run test:python`
Expected: PASS — every pre-existing test (Layer 1 from M06a-M1 plus shipped suites) plus `tests/test_spec_compliance.py` discovers and passes.

- [ ] **Step 3: Diff-scope audit (quality gate: diff limited to two files)**

PowerShell:
```powershell
git diff --name-only main...HEAD
```
Bash:
```bash
git diff --name-only main...HEAD
```

Expected — among the diff, the only NEW source paths introduced by M06a-M2 are:
- `skills/bmad-story-automator/src/story_automator/core/spec_compliance.py`
- `tests/test_spec_compliance.py`

The diff will also include M06a-M1 files (`core/gap_validator.py`, `tests/test_gap_validator.py`, `docs/superpowers/plans/2026-06-15-m06a-m1-gap-validator.md`) plus this plan file — those are the deliverables of earlier sub-milestones already merged into the worktree branch. If any *other* core/* or tests/* file is touched by M06a-M2 commits, revert it (`git checkout main -- <path>`).

- [ ] **Step 4: Cross-platform sanity (Windows git-bash)**

Run from a Windows git-bash prompt:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_spec_compliance -v
```

Expected: PASS. Pay attention to:
- `subprocess.TimeoutExpired` import path — same on Windows and POSIX.
- `Path.cwd()` and `str(Path.cwd())` — Windows returns backslash-form (e.g. `C:\Users\...`); the test asserts equality with `str(Path.cwd())`, so the comparison stays correct regardless of slash flavor.
- `os.environ` overlay — Windows tends to have `PATH` (capitalized as `Path` on some boxes); the assertion uses `env.get("PATH")` which, because `os.environ` is case-insensitive on Windows, will resolve correctly.

- [ ] **Step 5: Final sign-off (no commit)**

Print one line confirming "M06a-M2 gates green on Windows git-bash and Linux CI" in the conversation. Do not amend prior commits — leave the history as a clean stack of feat/test/style commits, one per task.

---

## Self-Review Checklist

**Spec coverage:**
- REQ-07 (`ReqVerdict` frozen kw_only with `req_id`, `status` Literal, `evidence`, `confidence`): Task 3 (dataclass), Task 6 (`status` Literal validation in parser).
- REQ-08 (`ComplianceReport` frozen kw_only with `verdicts`, `spec_path`, `diff_sha`, `model_invocation_ms`): Task 4 (dataclass), Task 7 (population in `check_compliance`).
- REQ-09 (`check_compliance` invokes `claude -p` via `subprocess.run` with `check=False`, `text=True`, `capture_output=True`, `timeout=timeout_s`): Task 7 (implementation), Task 9 (assertion on subprocess shape).
- REQ-10 (`ComplianceError` raised on non-zero exit, timeout, parse failure; never downgrades): Task 2 (exception), Task 6 (parser raise), Task 7 (subprocess raise), Task 8 (error-matrix assertions including the explicit "never downgrades" guarantee).
- REQ-11 (fenced blocks + four-letter placeholder escape on spec only): Task 5 (rendering + escape regex + scope-to-spec test).
- REQ-16 (importable in any order, no import-time side effects beyond `logging.getLogger(__name__)`, `__all__` declared): Task 1 (skeleton + import contract), Task 12 (symbol existence + forbidden-import audit).
- NFR — subprocess list args never `shell=True`: Task 9. Caller-supplied `cwd` defaulting to `Path.cwd()`: Task 9. `LANG=C.UTF-8` in child env: Task 9. Frozen kw_only dataclasses not subclassing other dataclasses: Tasks 3/4 (assertion in Task 3). Stdlib-only no psutil: Task 12 (assertion) + Task 13 (import allowlist audit). PEP 604 (`X | None`): visible in `cwd: Path | None = None` signature; mypy `--strict` catches violations (Task 13). `from __future__ import annotations`: Task 1. Public-API docstrings with pre/post/raises: every public symbol's docstring (Tasks 2, 3, 4, 5, 7). mypy `--strict`: Task 13.
- Quality gates — ruff clean (Task 13), mypy strict clean (Task 13), ≥92% coverage (Task 14), tests stub `subprocess.run` via `unittest.mock.patch("subprocess.run")` (Tasks 7, 8, 9) and never invoke real model (Task 10 documents the boundary with `@unittest.skip` + recorded reason), no imports from `commands/` or other M06a layer modules (Tasks 12, 13), diff scoped to two files (Task 14).

**Test count and negative-coverage check:**
- Final test count: ~55 entries (54 passing + 1 skipped real-model boundary) across 12 `TestCase` classes — comfortably above any reasonable floor.
- `check_compliance` negative tests: non-zero exit (Task 8), timeout (Task 8), unparseable stdout (Task 8), parse failure does not downgrade (Task 8), missing spec file (Task 11).
- `_parse_envelope` negative tests: malformed JSON, non-object top-level, missing `verdicts`, missing `model_invocation_ms`, non-list `verdicts`, missing verdict field, unknown status, negative `model_invocation_ms`, non-integer `model_invocation_ms`, never-downgrades guarantee (Task 6).
- `_render_prompt` negative tests: three-letter token NOT escaped, lowercase token NOT escaped, diff token NOT escaped (Task 5).

**Placeholder scan:** No "TODO", "TBD", "fill in details". The Task 1 module skeleton declares `__all__` ahead of definitions — intentional and explicitly justified in the note (matches M06a-M1's approach). Task 12 closes the symbol-existence gap.

**Type consistency:**
- `check_compliance(*, spec_path: Path, diff_text: str, timeout_s: int = 120, claude_binary: str = "claude", cwd: Path | None = None) -> ComplianceReport` — used identically across Tasks 7–11.
- `_parse_envelope(payload: str) -> tuple[list[ReqVerdict], int]` — used identically across Tasks 6–7.
- `_render_prompt(*, spec_text: str, diff_text: str) -> str` — used identically across Tasks 5, 7.
- `_escape_placeholders(spec_text: str) -> str` — Task 5.
- `ReqVerdict(req_id=..., status=..., evidence=..., confidence=...)` — used identically across Tasks 3, 6.
- `ComplianceReport(verdicts=..., spec_path=..., diff_sha=..., model_invocation_ms=...)` — used identically across Tasks 4, 7.

**Test names match implementation:** `_render_prompt`, `_escape_placeholders`, and `_parse_envelope` are intentionally tested through their private names because REQ-11 (placeholder escape) and REQ-10 (never-downgrade guarantee) require deterministic verification that can't go through the subprocess boundary. Keeping the private-name tests is a deliberate trade-off: the underscore signals "module-internal" to humans, but the spec quality gates compel us to assert behaviour that no public function exposes verbatim.

---

## Notes for the implementer

1. **Why pass the prompt via `input=` rather than as a CLI arg?** `claude -p` reads the prompt from stdin when invoked with `-p` and no positional prompt argument. Stuffing a multi-kilobyte prompt onto the command line would risk ARG_MAX on some platforms; stdin is unbounded and avoids quoting headaches.

2. **Why `subprocess.CompletedProcess[str]` typing in tests?** `subprocess.run` is generic over the encoding mode (`bytes` vs `str`). With `text=True` (REQ-09), the result is parameterized as `CompletedProcess[str]`. Constructing the stub with the same generic parameter keeps mypy happy without `# type: ignore`.

3. **Why `os.environ` overlay rather than a fresh `{"LANG": "C.UTF-8"}` dict?** A fresh dict would drop `PATH`, making the child unable to locate `claude`. The overlay preserves everything the parent has, then pins the locale.

4. **Why coerce `confidence` to `float` even when it parses as `int`?** JSON does not distinguish `1` from `1.0`; the model may emit either. The `ReqVerdict.confidence` field is typed `float`, and downstream consumers (Layer 3, M06b orchestrator) expect a uniform `float`. The coercion is a one-line guarantee.

5. **Why escape only four-letter uppercase placeholders?** The spec REQ-11 says "four-letter placeholder tokens". The BMAD template convention uses `{{NAME}}`-shape uppercase ALL-CAPS tokens of varying length; "four-letter" is interpreted as exactly-four-letter-uppercase as the narrowest reading of the spec. Lowercase identifiers (`{{name}}`) appear in human prose and are not template directives — leaving them untouched avoids mangling regular text. If the operator later wants broader escaping, the regex is one line to widen.

6. **Why compute `diff_sha` locally rather than asking the model for it?** Trust boundary: the model is untrusted in the "trust-but-verify" pattern. Computing the SHA locally pins the diff identity to what we actually sent, not what the model claims to have received.

7. **Why `Path | None` for `cwd` instead of `Path = Path.cwd()`?** Default argument values are evaluated once at function definition time. `Path.cwd()` as a default would freeze the directory to wherever the module was imported. Defaulting to `None` and resolving inside the function picks up the *current* `Path.cwd()` at invocation time, which is the spec-mandated behaviour.

8. **What's deferred to M06a-M3 and M06b?**
   - Layer 3 (`core/feature_tester.py`) — `TestPlanEntry`, `plan_feature_tests`, skeleton test generation. REQ-12..15.
   - The M06b orchestrator skill markdown that chains Layers 1+2+3.
   - Real-model integration: the skipped test in Task 10 documents the boundary so a future operator can run it manually.
