# M06b c-m01 — Fixtures and Format Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the test wedge of M06b — two JSON fixtures plus one stdlib-only unittest file that pin down the shapes Layer 1/2/3 exchange and the section structure of the future SKILL.md / step-03ab markdown.

**Architecture:** This sub-milestone is the **red phase** of M06b's outer TDD wedge. The SKILL.md and step-03ab markdown files do **not** exist yet; they arrive in c-m02/c-m03. Tests that depend on those markdown artifacts must call `self.skipTest(...)` in their `setUp` when the artifact is absent, so this milestone's `unittest` run is clean (skipped is not failed). Fixture-shape tests pass immediately because the fixtures themselves land in this milestone. The test file is intentionally allergic to imports from `story_automator.core.*` — REQ-14 mandates stdlib + `unittest.TestCase` only, so we cannot cross-validate fixtures by calling `parse_gap_list`; we re-implement just the shape checks the future contract requires.

**Tech Stack:**
- Python 3.11+, stdlib only (`json`, `re`, `unittest`, `pathlib`)
- ruff for lint/format
- LF line endings (project convention; Windows git-bash with `core.autocrlf=input`)
- Conventional Commits with `Generated-By` trailer

**Spec:** `docs/superpowers/specs/2026-06-14-m06b-trust-verify-skill.md` — REQ-13 (fixtures), REQ-14 (test file), quality gates (ruff + unittest).

**Pre-flight note for the engineer:** `git status` may show `D .claude/.gap-report.json` from the prior phase. Do **not** `git add` that deletion as part of any task commit in this milestone — it is the orchestrator's transient state and is regenerated each phase. Use explicit per-file `git add` (already specified in every commit step below) to avoid sweeping it in.

**Out of scope (defer to c-m02+):**
- Creating `skills/trust-but-verify/SKILL.md`
- Creating `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md`
- Editing `step-03a-execute-review.md`
- Wiring `trust_verify` into `story_automator.cli`
- Any change to `core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`
- Adding new event types / emitter wiring

---

## File Structure

| Path | Role | Created/Modified |
|---|---|---|
| `tests/fixtures/trust_verify_sample_gaps.json` | Input fixture matching `parse_gap_list` contract | **Create** |
| `tests/fixtures/trust_verify_sample_result.json` | Output fixture matching the chain emit shape | **Create** |
| `tests/test_trust_verify_skill_format.py` | Format-test file (stdlib-only, validates REQ-01..05 + REQ-07..09) | **Create** |

No other files are touched. The plan ends with a verification task that runs ruff + unittest + the placeholder grep gate to confirm the milestone's quality gates pass.

---

## Conventions Reminder

- `from __future__ import annotations` at the top of every Python file.
- Imports grouped stdlib → third-party → local.
- PEP 604 union types (`str | None`).
- `unittest.TestCase` subclasses. Mixed `assert` and `self.assertEqual` is fine.
- Per-task commit. Conventional Commits. Add `Generated-By: claude-opus-4-7` trailer.
- Commit example: `git commit --trailer "Generated-By: claude-opus-4-7" -m "..."`.

---

## Task 1: Input fixture — `trust_verify_sample_gaps.json`

**Files:**
- Create: `tests/fixtures/trust_verify_sample_gaps.json`

**Why:** REQ-13 — the chain's Layer-1 input mirrors `core/gap_validator.py::parse_gap_list`, which expects a top-level `{"gaps": [...]}` with each gap carrying `file_path` (str), `line` (int), `symbol` (str), `description` (str), and `severity` (one of `blocker`/`major`/`minor`).

- [ ] **Step 1: Create the fixtures directory if absent**

```bash
mkdir -p tests/fixtures
```

- [ ] **Step 2: Write the fixture file**

Save the following to `tests/fixtures/trust_verify_sample_gaps.json` (UTF-8, LF line endings, trailing newline):

```json
{
  "gaps": [
    {
      "file_path": "skills/bmad-story-automator/src/story_automator/core/gap_validator.py",
      "line": 105,
      "symbol": "parse_gap_list",
      "description": "Sample Layer-1 input citing parse_gap_list as the entry point the chain consumes.",
      "severity": "major"
    },
    {
      "file_path": "skills/bmad-story-automator/src/story_automator/core/spec_compliance.py",
      "line": 241,
      "symbol": "check_compliance",
      "description": "Sample claim that the Layer-2 entry point is reachable from the chain runner.",
      "severity": "blocker"
    },
    {
      "file_path": "skills/bmad-story-automator/src/story_automator/core/feature_tester.py",
      "line": 209,
      "symbol": "plan_feature_tests",
      "description": "Sample claim that the Layer-3 planner is invoked after Layer 2 succeeds.",
      "severity": "minor"
    }
  ]
}
```

- [ ] **Step 3: Verify the fixture parses as JSON**

Run from the repo root (Windows git-bash):

```bash
python -c "import json,sys; json.loads(open('tests/fixtures/trust_verify_sample_gaps.json',encoding='utf-8').read()); print('ok')"
```

Expected: prints `ok` and exits 0.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/trust_verify_sample_gaps.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): add trust-verify input sample fixture (REQ-13)"
```

---

## Task 2: Output fixture — `trust_verify_sample_result.json`

**Files:**
- Create: `tests/fixtures/trust_verify_sample_result.json`

**Why:** REQ-13 + REQ-05 — the chain writes a single JSON file with exact top-level keys `layer1`, `layer2`, `layer3`, `decision`, `verified_at`. Each inner layer mirrors the corresponding M06a dataclass (`ValidationReport`, `ComplianceReport`, `list[TestPlanEntry]`).

- [ ] **Step 1: Write the fixture file**

Save the following to `tests/fixtures/trust_verify_sample_result.json` (UTF-8, LF, trailing newline):

```json
{
  "layer1": {
    "statuses": [
      {
        "gap": {
          "file_path": "skills/bmad-story-automator/src/story_automator/core/gap_validator.py",
          "line": 105,
          "symbol": "parse_gap_list",
          "description": "Sample Layer-1 input citing parse_gap_list as the entry point the chain consumes.",
          "severity": "major"
        },
        "path_exists": true,
        "line_in_range": true,
        "symbol_present": true,
        "confidence": 0.95,
        "notes": []
      }
    ],
    "overall_confidence": 0.95,
    "validated_at": "2026-06-15T12:00:00Z"
  },
  "layer2": {
    "verdicts": [
      {
        "req_id": "REQ-01",
        "status": "implemented",
        "evidence": "SKILL.md present at skills/trust-but-verify/SKILL.md and names the three layer module paths.",
        "confidence": 0.9
      },
      {
        "req_id": "REQ-07",
        "status": "implemented",
        "evidence": "step-03ab includes a When to run section referencing step-03a-execute-review.md.",
        "confidence": 0.85
      }
    ],
    "spec_path": "docs/superpowers/specs/2026-06-14-m06b-trust-verify-skill.md",
    "diff_sha": "0000000000000000000000000000000000000000000000000000000000000000",
    "model_invocation_ms": 1234
  },
  "layer3": [
    {
      "req_id": "REQ-01",
      "existing_test_path": null,
      "created_test_path": "tests/test_compliance_req_01.py",
      "action": "created"
    }
  ],
  "decision": "pass",
  "verified_at": "2026-06-15T12:00:01Z"
}
```

- [ ] **Step 2: Verify the fixture parses as JSON**

```bash
python -c "import json; d=json.loads(open('tests/fixtures/trust_verify_sample_result.json',encoding='utf-8').read()); assert set(d)=={'layer1','layer2','layer3','decision','verified_at'}; print('ok')"
```

Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/trust_verify_sample_result.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): add trust-verify output sample fixture (REQ-13)"
```

---

## Task 3: Test file scaffold — module imports, constants, helper

**Files:**
- Create: `tests/test_trust_verify_skill_format.py`

**Why:** Pull module imports, repo-root resolution, and the shared "skip-if-missing" helper into a small scaffold before adding test classes. Keeping this in its own commit makes later tasks pure additions.

- [ ] **Step 1: Write the file**

```python
"""Format tests for the M06b trust-but-verify SKILL bundle and step-03ab.

This file enforces the shape contracts declared in
docs/superpowers/specs/2026-06-14-m06b-trust-verify-skill.md REQ-01..REQ-05,
REQ-07..REQ-09, and REQ-13.

Tests are stdlib-only (REQ-14). When the SKILL.md or step-03ab markdown
file is not yet present (sub-milestones c-m02/c-m03), the dependent
tests call ``self.skipTest`` so this file's unittest run stays clean.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "trust-but-verify"
SKILL_MD = SKILL_DIR / "SKILL.md"
STEP_03AB = (
    REPO_ROOT
    / "skills"
    / "bmad-story-automator"
    / "steps-c"
    / "step-03ab-spec-compliance.md"
)
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
INPUT_FIXTURE = FIXTURES_DIR / "trust_verify_sample_gaps.json"
OUTPUT_FIXTURE = FIXTURES_DIR / "trust_verify_sample_result.json"


def _require_markdown(test_case: unittest.TestCase, path: Path) -> str:
    """Return the UTF-8 text of ``path`` or skip the test if it does not exist.

    The SKILL.md and step-03ab files are created in later M06b sub-milestones
    (c-m02 / c-m03). Tests that depend on them must skip cleanly here so the
    c-m01 unittest gate reports zero failures.
    """
    if not path.exists():
        test_case.skipTest(f"{path.relative_to(REPO_ROOT)} not yet present (c-m02+)")
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run ruff check**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
```

Expected: `All checks passed!` (or no output, exit 0).

- [ ] **Step 3: Run ruff format check**

```bash
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

Expected: `1 file already formatted` (exit 0). If it reports the file would be reformatted, run `python -m ruff format tests/test_trust_verify_skill_format.py` and re-check.

- [ ] **Step 4: Run the (empty) test module to confirm it imports cleanly**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format -v
```

Expected: `Ran 0 tests in 0.000s` followed by `NO TESTS RAN` or `OK`, exit code 0. Import errors here mean the scaffold is broken — fix before continuing. (`unittest -v` with no discovered tests in the module is normal and not a failure.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): scaffold trust-verify format test module (REQ-14)"
```

---

## Task 4: Input fixture shape tests (REQ-13)

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** Lock the input fixture to the `parse_gap_list` contract: top-level `{"gaps": [...]}`, each gap carries the five required keys with the right types, `severity` ∈ `{blocker, major, minor}`, `line` is `int` and rejects `bool`.

- [ ] **Step 1: Append the test class above the `if __name__` guard**

Insert this class **before** the `if __name__ == "__main__":` line:

```python
_ALLOWED_SEVERITIES = {"blocker", "major", "minor"}
_GAP_REQUIRED_KEYS = ("file_path", "line", "symbol", "description", "severity")


class InputFixtureShapeTests(unittest.TestCase):
    """REQ-13: sample input fixture matches parse_gap_list's contract."""

    def setUp(self) -> None:
        self.data = json.loads(INPUT_FIXTURE.read_text(encoding="utf-8"))

    def test_top_level_is_object_with_gaps_key(self) -> None:
        self.assertIsInstance(self.data, dict)
        self.assertIn("gaps", self.data)
        self.assertIsInstance(self.data["gaps"], list)

    def test_fixture_is_non_empty(self) -> None:
        self.assertGreater(
            len(self.data["gaps"]),
            0,
            "fixture must contain at least one sample gap",
        )

    def test_each_gap_has_required_keys(self) -> None:
        for index, gap in enumerate(self.data["gaps"]):
            self.assertIsInstance(gap, dict, msg=f"gaps[{index}] not an object")
            for key in _GAP_REQUIRED_KEYS:
                self.assertIn(key, gap, msg=f"gaps[{index}] missing {key!r}")

    def test_each_gap_field_has_correct_type(self) -> None:
        for index, gap in enumerate(self.data["gaps"]):
            self.assertIsInstance(gap["file_path"], str, msg=f"gaps[{index}].file_path")
            # bool is a subclass of int; reject explicitly to match parse_gap_list.
            self.assertFalse(
                isinstance(gap["line"], bool),
                msg=f"gaps[{index}].line must not be a bool",
            )
            self.assertIsInstance(gap["line"], int, msg=f"gaps[{index}].line")
            self.assertIsInstance(gap["symbol"], str, msg=f"gaps[{index}].symbol")
            self.assertIsInstance(
                gap["description"], str, msg=f"gaps[{index}].description"
            )

    def test_each_gap_severity_is_allowed(self) -> None:
        for index, gap in enumerate(self.data["gaps"]):
            self.assertIn(
                gap["severity"],
                _ALLOWED_SEVERITIES,
                msg=f"gaps[{index}].severity {gap['severity']!r} outside allowed set",
            )
```

- [ ] **Step 2: Run the new tests**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.InputFixtureShapeTests -v
```

Expected: 5 tests, all PASS.

- [ ] **Step 3: Ruff check + format check**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

Both must exit 0.

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert input fixture shape matches parse_gap_list (REQ-13)"
```

---

## Task 5: Output fixture shape tests (REQ-13 + REQ-05)

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** Lock the chain emit envelope: exactly five top-level keys `layer1`, `layer2`, `layer3`, `decision`, `verified_at`; `decision` must be one of `pass`/`warn`/`block`; the inner layer payloads must carry the dataclass fields M06a's layers emit.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
_DECISION_VALUES = {"pass", "warn", "block"}
_OUTPUT_REQUIRED_KEYS = {"layer1", "layer2", "layer3", "decision", "verified_at"}
_LAYER1_KEYS = {"statuses", "overall_confidence", "validated_at"}
_LAYER2_KEYS = {"verdicts", "spec_path", "diff_sha", "model_invocation_ms"}
_LAYER3_ENTRY_KEYS = {
    "req_id",
    "existing_test_path",
    "created_test_path",
    "action",
}
_LAYER3_ACTIONS = {"found", "created", "skipped"}


class OutputFixtureShapeTests(unittest.TestCase):
    """REQ-13 + REQ-05: sample output fixture matches the chain emit shape."""

    def setUp(self) -> None:
        self.data = json.loads(OUTPUT_FIXTURE.read_text(encoding="utf-8"))

    def test_top_level_has_exactly_required_keys(self) -> None:
        self.assertEqual(set(self.data), _OUTPUT_REQUIRED_KEYS)

    def test_decision_is_allowed_literal(self) -> None:
        self.assertIn(self.data["decision"], _DECISION_VALUES)

    def test_verified_at_is_iso8601_z_string(self) -> None:
        verified_at = self.data["verified_at"]
        self.assertIsInstance(verified_at, str)
        self.assertRegex(
            verified_at,
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$",
        )

    def test_layer1_has_validation_report_keys(self) -> None:
        layer1 = self.data["layer1"]
        self.assertIsInstance(layer1, dict)
        self.assertEqual(set(layer1), _LAYER1_KEYS)
        self.assertIsInstance(layer1["statuses"], list)
        self.assertIsInstance(layer1["overall_confidence"], (int, float))
        self.assertGreaterEqual(layer1["overall_confidence"], 0.0)
        self.assertLessEqual(layer1["overall_confidence"], 1.0)

    def test_layer2_has_compliance_report_keys(self) -> None:
        layer2 = self.data["layer2"]
        self.assertIsInstance(layer2, dict)
        self.assertEqual(set(layer2), _LAYER2_KEYS)
        self.assertIsInstance(layer2["verdicts"], list)
        self.assertFalse(isinstance(layer2["model_invocation_ms"], bool))
        self.assertIsInstance(layer2["model_invocation_ms"], int)
        self.assertGreaterEqual(layer2["model_invocation_ms"], 0)

    def test_layer3_is_list_of_plan_entries(self) -> None:
        layer3 = self.data["layer3"]
        self.assertIsInstance(layer3, list)
        for index, entry in enumerate(layer3):
            self.assertIsInstance(entry, dict, msg=f"layer3[{index}] not object")
            self.assertEqual(
                set(entry), _LAYER3_ENTRY_KEYS, msg=f"layer3[{index}] key set"
            )
            self.assertIn(
                entry["action"], _LAYER3_ACTIONS, msg=f"layer3[{index}].action"
            )
```

- [ ] **Step 2: Run the new tests**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.OutputFixtureShapeTests -v
```

Expected: 6 tests, all PASS.

- [ ] **Step 3: Ruff check + format check**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

Both exit 0.

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert output fixture matches chain emit shape (REQ-13, REQ-05)"
```

---

## Task 6: SKILL.md REQ-01 tests — file presence, layer module paths, invocation order

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** REQ-01 — exactly one file (`SKILL.md`) under `skills/trust-but-verify/`; names each of the three M06a Python modules by their repo-relative path; declares the L1→L2→L3 invocation order with no short-circuit.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
class SkillMdReq01Tests(unittest.TestCase):
    """REQ-01: SKILL bundle at skills/trust-but-verify/ with single SKILL.md
    that names the three M06a modules and declares L1 -> L2 -> L3 order."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, SKILL_MD)

    def test_skill_dir_contains_only_skill_md(self) -> None:
        names = sorted(p.name for p in SKILL_DIR.iterdir() if not p.name.startswith("."))
        self.assertEqual(
            names,
            ["SKILL.md"],
            msg=f"skills/trust-but-verify/ must contain only SKILL.md, got {names}",
        )

    def test_skill_md_names_all_three_layer_module_paths(self) -> None:
        for module_path in (
            "core/gap_validator.py",
            "core/spec_compliance.py",
            "core/feature_tester.py",
        ):
            self.assertIn(
                module_path,
                self.text,
                msg=f"SKILL.md must name layer module path {module_path!r}",
            )

    def test_skill_md_declares_invocation_order(self) -> None:
        l1 = self.text.find("Layer 1")
        l2 = self.text.find("Layer 2")
        l3 = self.text.find("Layer 3")
        self.assertNotEqual(l1, -1, msg="SKILL.md missing 'Layer 1' marker")
        self.assertGreater(l2, l1, msg="'Layer 2' must appear after 'Layer 1'")
        self.assertGreater(l3, l2, msg="'Layer 3' must appear after 'Layer 2'")
```

- [ ] **Step 2: Run the new tests**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.SkillMdReq01Tests -v
```

Expected: 3 tests, all SKIPPED (`s` markers). SKILL.md does not yet exist; later c-m02 milestone will create it and these turn into asserts.

- [ ] **Step 3: Ruff check + format check (both exit 0)**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert SKILL.md presence, layer paths, order (REQ-01)"
```

---

## Task 7: SKILL.md REQ-02 tests — `## Trigger` section, four trigger conditions

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** REQ-02 — a level-2 `## Trigger` section that enumerates exactly four trigger conditions: `/sw-trust-verify`, review preflight of step-03a, completion of a Dev Story phase, operator request via the orchestrator menu.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
class SkillMdReq02Tests(unittest.TestCase):
    """REQ-02: ## Trigger section names the four documented triggers."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, SKILL_MD)

    def test_trigger_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## Trigger\s*$",
            msg="SKILL.md must include a level-2 '## Trigger' heading",
        )

    def test_all_four_triggers_named(self) -> None:
        needles = (
            "/sw-trust-verify",
            "step-03a",
            "Dev Story",
            "orchestrator menu",
        )
        missing = [n for n in needles if n not in self.text]
        self.assertEqual(
            missing,
            [],
            msg=f"SKILL.md ## Trigger section missing references: {missing}",
        )
```

- [ ] **Step 2: Run the new tests (expect 2 SKIPPED)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.SkillMdReq02Tests -v
```

- [ ] **Step 3: Ruff check + format check (both exit 0)**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert SKILL.md Trigger section names four triggers (REQ-02)"
```

---

## Task 8: SKILL.md REQ-03 tests — `## Pre-conditions` section, four items

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** REQ-03 — level-2 `## Pre-conditions` section enumerating exactly four pre-conditions: story file at BMAD root, structured gap list at `.claude/trust-verify-input/gaps.json`, spec referenced by the current story, clean working tree.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
class SkillMdReq03Tests(unittest.TestCase):
    """REQ-03: ## Pre-conditions section names the four documented prereqs."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, SKILL_MD)

    def test_preconditions_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## Pre-conditions\s*$",
            msg="SKILL.md must include a level-2 '## Pre-conditions' heading",
        )

    def test_all_four_preconditions_named(self) -> None:
        needles = (
            "story file",
            ".claude/trust-verify-input/gaps.json",
            "spec",
            "git working tree",
        )
        missing = [n for n in needles if n not in self.text]
        self.assertEqual(
            missing,
            [],
            msg=f"SKILL.md ## Pre-conditions missing references: {missing}",
        )
```

- [ ] **Step 2: Run the new tests (expect 2 SKIPPED)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.SkillMdReq03Tests -v
```

- [ ] **Step 3: Ruff check + format check (both exit 0)**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert SKILL.md Pre-conditions section (REQ-03)"
```

---

## Task 9: SKILL.md REQ-04 tests — `## Invocation contract` CLI pattern

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** REQ-04 — level-2 `## Invocation contract` section showing the exact CLI invocation pattern using `python -m story_automator.cli trust_verify --gaps .claude/trust-verify-input/gaps.json --spec <spec_path> --diff <diff_path>` with no additional flags.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
class SkillMdReq04Tests(unittest.TestCase):
    """REQ-04: ## Invocation contract section shows the exact CLI pattern."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, SKILL_MD)

    def test_invocation_contract_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## Invocation contract\s*$",
            msg="SKILL.md must include a level-2 '## Invocation contract' heading",
        )

    def test_cli_pattern_present(self) -> None:
        # The spec mandates this exact pattern; match the spine of the
        # command line plus each required flag.
        for needle in (
            "python -m story_automator.cli trust_verify",
            "--gaps .claude/trust-verify-input/gaps.json",
            "--spec",
            "--diff",
        ):
            self.assertIn(
                needle,
                self.text,
                msg=f"SKILL.md ## Invocation contract missing {needle!r}",
            )

    def test_no_unexpected_cli_flags(self) -> None:
        # Scope the flag-set check to lines that ARE the CLI invocation
        # (start with `python -m story_automator.cli trust_verify`), not
        # every prose mention of trust_verify. This avoids false positives
        # on sentences like "the trust_verify skill supports --verbose
        # logging upstream" where --verbose belongs to a different tool.
        allowed = {"--gaps", "--spec", "--diff"}
        invocation_re = re.compile(
            r"python -m story_automator\.cli trust_verify[^\n]*"
        )
        for match in invocation_re.finditer(self.text):
            flags = set(re.findall(r"--[a-z][a-z0-9_-]*", match.group(0)))
            extra = flags - allowed
            self.assertEqual(
                extra,
                set(),
                msg=f"Unexpected CLI flag(s) in invocation line: {extra}",
            )
```

- [ ] **Step 2: Run the new tests (expect 3 SKIPPED)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.SkillMdReq04Tests -v
```

- [ ] **Step 3: Ruff check + format check (both exit 0)**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert SKILL.md Invocation contract CLI pattern (REQ-04)"
```

---

## Task 10: SKILL.md REQ-05 tests — `## Output contract` keys and decision literals

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** REQ-05 — level-2 `## Output contract` section specifying the chain writes `.claude/trust-verify-output/result.json` with exact top-level keys `layer1`, `layer2`, `layer3`, `decision`, `verified_at`, and `decision` is one of `pass`/`warn`/`block`.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
class SkillMdReq05Tests(unittest.TestCase):
    """REQ-05: ## Output contract section names the five top-level keys
    and the three allowed decision literals."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, SKILL_MD)

    def test_output_contract_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## Output contract\s*$",
            msg="SKILL.md must include a level-2 '## Output contract' heading",
        )

    def test_output_path_named(self) -> None:
        self.assertIn(
            ".claude/trust-verify-output/result.json",
            self.text,
            msg="SKILL.md ## Output contract must name the result.json path",
        )

    def test_all_five_top_level_keys_named(self) -> None:
        for key in ("layer1", "layer2", "layer3", "decision", "verified_at"):
            self.assertIn(
                key,
                self.text,
                msg=f"SKILL.md ## Output contract missing key {key!r}",
            )

    def test_all_three_decision_literals_named(self) -> None:
        for literal in ("pass", "warn", "block"):
            # Match the literal bounded by non-word characters so 'pass'
            # does not match inside 'password'.
            self.assertRegex(
                self.text,
                rf"(?<!\w){re.escape(literal)}(?!\w)",
                msg=f"SKILL.md ## Output contract missing decision literal {literal!r}",
            )
```

- [ ] **Step 2: Run the new tests (expect 4 SKIPPED)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.SkillMdReq05Tests -v
```

- [ ] **Step 3: Ruff check + format check (both exit 0)**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert SKILL.md Output contract keys and decisions (REQ-05)"
```

---

## Task 11: step-03ab REQ-07 tests — `## When to run` placement

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** REQ-07 — step-03ab must include a level-2 `## When to run` section saying the step runs after Dev Story section B and before Code Review Loop section D, with explicit reference to `step-03a-execute-review.md`.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
class Step03abReq07Tests(unittest.TestCase):
    """REQ-07: ## When to run section names section B, section D, step-03a."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, STEP_03AB)

    def test_when_to_run_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## When to run\s*$",
            msg="step-03ab must include a level-2 '## When to run' heading",
        )

    def test_when_to_run_references_section_b_d_and_step_03a(self) -> None:
        for needle in (
            "section B",
            "section D",
            "step-03a-execute-review.md",
        ):
            self.assertIn(
                needle,
                self.text,
                msg=f"step-03ab ## When to run missing reference: {needle!r}",
            )
```

- [ ] **Step 2: Run the new tests (expect 2 SKIPPED)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.Step03abReq07Tests -v
```

- [ ] **Step 3: Ruff check + format check (both exit 0)**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert step-03ab When to run section (REQ-07)"
```

---

## Task 12: step-03ab REQ-08 tests — `## What it does` section

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** REQ-08 — step-03ab includes a level-2 `## What it does` section explaining the step invokes the trust-but-verify skill, reads `result.json`, and makes a pass/warn/block decision gating the transition to section D.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
class Step03abReq08Tests(unittest.TestCase):
    """REQ-08: ## What it does section explains invoke -> read -> decide."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, STEP_03AB)

    def test_what_it_does_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## What it does\s*$",
            msg="step-03ab must include a level-2 '## What it does' heading",
        )

    def test_what_it_does_mentions_skill_result_and_decision(self) -> None:
        for needle in (
            "trust-but-verify",
            "result.json",
            "pass",
            "warn",
            "block",
            "section D",
        ):
            self.assertIn(
                needle,
                self.text,
                msg=f"step-03ab ## What it does missing reference: {needle!r}",
            )
```

- [ ] **Step 2: Run the new tests (expect 2 SKIPPED)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.Step03abReq08Tests -v
```

- [ ] **Step 3: Ruff check + format check (both exit 0)**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert step-03ab What it does section (REQ-08)"
```

---

## Task 13: step-03ab REQ-09 tests — `## Failure modes` enumerates exactly five modes

**Files:**
- Modify: `tests/test_trust_verify_skill_format.py`

**Why:** REQ-09 — step-03ab includes a level-2 `## Failure modes` section enumerating exactly five failure modes: Layer 1 gaps with confidence < 0.6; Layer 2 `missing` verdict on any REQ; Layer 3 creates a test under `tests/test_compliance_*.py`; malformed chain JSON output; Layer 2 subprocess non-zero exit.

- [ ] **Step 1: Append the test class above `if __name__`**

```python
class Step03abReq09Tests(unittest.TestCase):
    """REQ-09: ## Failure modes section enumerates the five documented modes."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, STEP_03AB)

    def test_failure_modes_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## Failure modes\s*$",
            msg="step-03ab must include a level-2 '## Failure modes' heading",
        )

    def test_layer1_confidence_threshold_named(self) -> None:
        # The spec pins the threshold at 0.6.
        self.assertIn("Layer 1", self.text)
        self.assertIn("0.6", self.text)

    def test_layer2_missing_verdict_named(self) -> None:
        self.assertIn("Layer 2", self.text)
        self.assertIn("missing", self.text)

    def test_layer3_created_test_path_named(self) -> None:
        self.assertIn("Layer 3", self.text)
        self.assertIn("tests/test_compliance_", self.text)

    def test_malformed_json_failure_named(self) -> None:
        # Match either 'malformed' or 'malformed JSON' anywhere in the section.
        self.assertRegex(
            self.text,
            r"(?i)malformed",
            msg="step-03ab ## Failure modes must mention malformed JSON output",
        )

    def test_subprocess_nonzero_exit_named(self) -> None:
        self.assertRegex(
            self.text,
            r"(?i)non[- ]?zero",
            msg="step-03ab ## Failure modes must mention non-zero subprocess exit",
        )
```

- [ ] **Step 2: Run the new tests (expect 6 SKIPPED)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format.Step03abReq09Tests -v
```

- [ ] **Step 3: Ruff check + format check (both exit 0)**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_trust_verify_skill_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m06b): assert step-03ab Failure modes section (REQ-09)"
```

---

## Task 14: Final verification — quality gates, no regressions, time budget

**Files:**
- No new edits expected. This task is a verification pass.

**Why:** Confirm all c-m01 quality gates pass before declaring the milestone done. Specifically:
- ruff check + ruff format check clean on the new test file
- the new test module runs in under one second (REQ non-functional)
- M06a's existing tests still pass with zero regressions
- placeholder grep gate stays clean on the fixtures (no `{{XXXX}}` four-letter tokens)

- [ ] **Step 1: Ruff check the test file and fixtures directory**

```bash
python -m ruff check tests/test_trust_verify_skill_format.py
python -m ruff format --check tests/test_trust_verify_skill_format.py
```

Both exit 0.

- [ ] **Step 2: Run the full new test module and time it**

Windows git-bash:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format -v
```

Expected:
- 0 failures, 0 errors (the only quality gate)
- 11 PASSED (fixture shape tests: 5 input + 6 output)
- 24 SKIPPED (SkillMdReq01: 3, Req02: 2, Req03: 2, Req04: 3, Req05: 4, Step03abReq07: 2, Req08: 2, Req09: 6 = 24)
- Wall time well under 1 second

If the skipped count differs by 1–2 because a test was reorganised, that's fine — the gate is "failures + errors == 0", not exact skip count.

- [ ] **Step 3: Run the M06a test files to confirm no regression**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_gap_validator tests.test_spec_compliance tests.test_feature_tester -v
```

Expected: all pass, zero failures, zero errors. The M06b c-m01 diff only adds files; it must not regress M06a.

- [ ] **Step 4: Placeholder grep gate over the new artifacts**

```bash
grep -nE '\{\{[A-Z]{4}\}\}' \
  tests/fixtures/trust_verify_sample_gaps.json \
  tests/fixtures/trust_verify_sample_result.json \
  tests/test_trust_verify_skill_format.py \
  && echo "FAIL: placeholder tokens found" \
  || echo "ok: no placeholder tokens"
```

Expected: prints `ok: no placeholder tokens`. (The `&&`/`||` invert exit code so grep's "no match" exit-1 becomes a success signal.)

- [ ] **Step 5: Git status sanity check**

```bash
git status --short
git log --oneline -n 14
```

Expected: working tree clean (all 13 prior task commits landed). The log shows 13 conventional commits with `test(m06b):` scope plus this milestone's history. No uncommitted changes.

- [ ] **Step 6: No commit needed — verification only**

This task is a quality gate. If any step above fails, return to the failing task and fix before declaring c-m01 complete.

---

## Self-Review Checklist (run after writing this plan, before execution)

- [x] Every REQ-13 obligation (input fixture + output fixture present, parse-list-compatible, chain-emit shape) covered by Tasks 1, 2, 4, 5.
- [x] Every REQ-14 obligation (test file at `tests/test_trust_verify_skill_format.py`, stdlib-only, `unittest.TestCase`, validates REQ-01..05 + REQ-07..09) covered by Tasks 3, 6–13.
- [x] Quality gates (ruff check, ruff format check, unittest) exercised in every per-test-class task and again in Task 14.
- [x] No new Python dependencies introduced (stdlib only).
- [x] No subprocess, no network, no tmux inside test methods (REQ-14 + project guardrail).
- [x] Cross-platform: tests use `pathlib`, no shell calls, no platform-specific paths.
- [x] All file paths spelled out exactly. No `TBD`/`TODO`/placeholder steps.
- [x] Conventional Commits with `Generated-By` trailer specified on every commit step.
- [x] Type identifiers consistent across tasks (`_GAP_REQUIRED_KEYS`, `_OUTPUT_REQUIRED_KEYS`, `_LAYER1_KEYS`, etc. defined once per module-level constant block and never renamed mid-plan).
