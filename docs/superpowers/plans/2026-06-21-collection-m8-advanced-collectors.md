# Advanced Collectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 10 evidence collectors across 3 new categories (test_quality, mutation, agentic) plus an invariant registry YAML loader (§6.4), completing the spec §6.2 advanced quality categories that depend on the M4 collector framework.

**Architecture:** Each new category becomes a Python module under `core/collectors/` following the frozen `CollectorConfig` + `build_cmd` pattern from M4–M7. Seven new check scripts under `core/checks/` handle multi-step validations. A new `core/invariant_registry.py` module loads and validates invariant entries from the profile-referenced YAML file (§6.4). All collectors register via `register_core_collectors()`. M5–M7 have 39 collectors across 15 categories; M8 brings the total to 49 collectors across 18 categories.

**Tech Stack:** Python 3.11+ stdlib only (no new deps), `CollectorConfig` from M4 framework, profile `rules` dict for per-category configuration, simple YAML subset parser (stdlib only) for invariant registry files.

## Global Constraints

- No Python imports beyond stdlib + `filelock` + `psutil` (CLAUDE.md hard rule)
- 500 LOC soft limit per module
- Check scripts are standalone (no `story_automator` imports, stdlib only)
- Collectors use the same `CollectorConfig` frozen dataclass from `collector_config.py`
- All collectors are `deterministic=True` (subprocess tools produce repeatable output)
- Profile rules are opaque dicts consumed by `build_cmd`/check scripts
- Conventional Commits, `Generated-By:` trailer on every commit
- Test runner: `python -m pytest tests/ -v`
- Lint: `ruff check .`

## File Structure

**New files (3 collector modules):**
- `skills/bmad-story-automator/src/story_automator/core/collectors/test_quality.py` — 3 collectors: test-review, burn-in, hard-wait
- `skills/bmad-story-automator/src/story_automator/core/collectors/mutation.py` — 2 collectors: mutmut, stryker
- `skills/bmad-story-automator/src/story_automator/core/collectors/agentic.py` — 5 collectors: pack-schema, aibom-diff, opa, evals, guardrail

**New files (7 check scripts):**
- `skills/bmad-story-automator/src/story_automator/core/checks/test_review_check.py` — TEA test-review JSON reader + score threshold
- `skills/bmad-story-automator/src/story_automator/core/checks/burn_in_check.py` — run tests N×, detect flaky
- `skills/bmad-story-automator/src/story_automator/core/checks/hard_wait_check.py` — scan for sleep/setTimeout patterns
- `skills/bmad-story-automator/src/story_automator/core/checks/mutation_check.py` — run mutmut/stryker, check threshold
- `skills/bmad-story-automator/src/story_automator/core/checks/pack_schema_check.py` — validate agent tool pack-schema v1.2 fields
- `skills/bmad-story-automator/src/story_automator/core/checks/aibom_check.py` — validate AIBOM entries for changed tools
- `skills/bmad-story-automator/src/story_automator/core/checks/opa_check.py` — run opa compile + opa test

**New files (1 infrastructure module):**
- `skills/bmad-story-automator/src/story_automator/core/invariant_registry.py` — YAML subset loader + validation

**New files (11 test files):**
- `tests/test_invariant_registry.py`
- `tests/test_check_test_review.py`
- `tests/test_check_burn_in.py`
- `tests/test_check_hard_wait.py`
- `tests/test_check_mutation.py`
- `tests/test_check_pack_schema.py`
- `tests/test_check_aibom.py`
- `tests/test_check_opa.py`
- `tests/test_collectors_test_quality.py`
- `tests/test_collectors_mutation.py`
- `tests/test_collectors_agentic.py`

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py` — import + register 3 new categories
- `skills/bmad-story-automator/src/story_automator/core/diff_scope.py` — add test_quality, mutation, agentic to DEFAULT_FILE_CATEGORY_MAP
- `skills/bmad-story-automator/src/story_automator/core/profile_bridge.py` — wire invariant registry loader
- `tests/test_core_collectors.py` — update expected IDs (49), expected categories (18)
- `tests/test_collector_integration.py` — add advanced category pipeline tests
- `CLAUDE.md` — update module map

---

### Task 1: Invariant registry YAML loader

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/invariant_registry.py`
- Create: `tests/test_invariant_registry.py`

**Interfaces:**
- Consumes: YAML file path from `profile.invariants.registry_file`; `gate_schema.validate_invariant_entry()` for validation
- Produces: `load_yaml_registry(path) -> list[dict]`, `validate_registry(entries) -> tuple[bool, list[str]]`, `load_invariant_registry(profile, base_dir) -> list[dict]`

- [ ] **Step 1: Write failing tests for invariant registry loader**

```python
# tests/test_invariant_registry.py
from __future__ import annotations

import os
import tempfile
import unittest


class LoadYamlRegistryTests(unittest.TestCase):
    def test_loads_simple_entries(self) -> None:
        from story_automator.core.invariant_registry import load_yaml_registry

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
            "\n"
            "- id: DG-13\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg13.yml\n"
            "  severity: FAIL\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(content)
            path = f.name
        try:
            entries = load_yaml_registry(path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["id"], "DG-12")
            self.assertEqual(entries[0]["check_type"], "semgrep")
            self.assertEqual(entries[1]["id"], "DG-13")
        finally:
            os.unlink(path)

    def test_skips_comments_and_blanks(self) -> None:
        from story_automator.core.invariant_registry import load_yaml_registry

        content = (
            "# This is a comment\n"
            "\n"
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(content)
            path = f.name
        try:
            entries = load_yaml_registry(path)
            self.assertEqual(len(entries), 1)
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self) -> None:
        from story_automator.core.invariant_registry import load_yaml_registry

        entries = load_yaml_registry("/nonexistent/path.yaml")
        self.assertEqual(entries, [])

    def test_loads_real_msme_registry(self) -> None:
        from story_automator.core.invariant_registry import load_yaml_registry
        from pathlib import Path

        registry_path = (
            Path(__file__).resolve().parent.parent
            / "skills" / "bmad-story-automator" / "data"
            / "profiles" / "msme-erp.invariants.yaml"
        )
        if not registry_path.exists():
            self.skipTest("msme-erp.invariants.yaml not found")
        entries = load_yaml_registry(str(registry_path))
        self.assertGreaterEqual(len(entries), 6)
        ids = [e["id"] for e in entries]
        self.assertIn("DG-12", ids)
        self.assertIn("DG-25", ids)


class ValidateRegistryTests(unittest.TestCase):
    def test_valid_entries_pass(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        entries = [
            {"id": "DG-12", "checkable": "yes", "check_type": "semgrep",
             "rule_file": "semgrep/dg12.yml", "severity": "FAIL"},
        ]
        ok, errors = validate_registry(entries)
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_invalid_severity_fails(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        entries = [
            {"id": "DG-12", "checkable": "yes", "check_type": "semgrep",
             "rule_file": "semgrep/dg12.yml", "severity": "BAD"},
        ]
        ok, errors = validate_registry(entries)
        self.assertFalse(ok)
        self.assertTrue(any("severity" in e.lower() for e in errors))

    def test_invalid_check_type_fails(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        entries = [
            {"id": "DG-12", "checkable": "yes", "check_type": "unknown",
             "rule_file": "f.yml", "severity": "FAIL"},
        ]
        ok, errors = validate_registry(entries)
        self.assertFalse(ok)

    def test_non_checkable_skips_type_validation(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        entries = [
            {"id": "DG-99", "checkable": "no", "severity": "CONCERNS"},
        ]
        ok, errors = validate_registry(entries)
        self.assertTrue(ok)

    def test_empty_list_passes(self) -> None:
        from story_automator.core.invariant_registry import validate_registry

        ok, errors = validate_registry([])
        self.assertTrue(ok)
        self.assertEqual(errors, [])


class LoadInvariantRegistryTests(unittest.TestCase):
    def test_loads_from_profile_registry_file(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
        )
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "invariants.yaml")
            with open(path, "w") as f:
                f.write(content)
            profile = {
                "invariants": {"registry_file": "invariants.yaml"},
            }
            entries = load_invariant_registry(profile, tmpdir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "DG-12")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_registry_file_returns_empty(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        profile = {"invariants": {}}
        entries = load_invariant_registry(profile, "/tmp")
        self.assertEqual(entries, [])

    def test_no_invariants_key_returns_empty(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        entries = load_invariant_registry({}, "/tmp")
        self.assertEqual(entries, [])

    def test_filters_out_invalid_entries(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
            "\n"
            "- id: BAD-ENTRY\n"
            "  checkable: yes\n"
            "  check_type: unknown\n"
            "  rule_file: bad.yml\n"
            "  severity: FAIL\n"
        )
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "invariants.yaml")
            with open(path, "w") as f:
                f.write(content)
            profile = {
                "invariants": {"registry_file": "invariants.yaml"},
            }
            entries = load_invariant_registry(profile, tmpdir)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["id"], "DG-12")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_absolute_path_used_directly(self) -> None:
        from story_automator.core.invariant_registry import load_invariant_registry

        content = (
            "- id: DG-34\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg34.yml\n"
            "  severity: FAIL\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write(content)
            abs_path = f.name
        try:
            profile = {
                "invariants": {"registry_file": abs_path},
            }
            entries = load_invariant_registry(profile, "/nonexistent")
            self.assertEqual(len(entries), 1)
        finally:
            os.unlink(abs_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_invariant_registry.py -v`
Expected: `ModuleNotFoundError` — `invariant_registry` module does not exist yet.

- [ ] **Step 3: Implement invariant registry loader**

```python
# skills/bmad-story-automator/src/story_automator/core/invariant_registry.py
"""Invariant registry loader and validator (§6.4).

Loads DG/ADR invariant entries from YAML files referenced by
profile.invariants.registry_file. Uses a minimal YAML subset
parser (stdlib only) for the flat list-of-dicts format.
Validates entries against gate_schema.validate_invariant_entry().
"""
from __future__ import annotations

import os
from typing import Any

from .gate_schema import GateSchemaError, validate_invariant_entry

__all__ = [
    "load_yaml_registry",
    "validate_registry",
    "load_invariant_registry",
]


def load_yaml_registry(path: str) -> list[dict[str, str]]:
    """Parse a simple YAML invariant registry file.

    Supports: flat list of key-value dicts, comments, blank lines.
    Each entry starts with ``- key: value`` and continues with
    ``  key: value`` lines. Does NOT handle nested structures,
    multi-line strings, anchors, or other advanced YAML features.
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in lines:
        stripped = raw.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        if stripped.startswith("- "):
            if current is not None:
                entries.append(current)
            key, _, value = stripped[2:].partition(":")
            current = {key.strip(): value.strip()}
        elif stripped.startswith("  ") and current is not None:
            key, _, value = stripped.strip().partition(":")
            current[key.strip()] = value.strip()
    if current is not None:
        entries.append(current)
    return entries


def validate_registry(
    entries: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Validate each registry entry against gate_schema rules."""
    errors: list[str] = []
    for i, entry in enumerate(entries):
        try:
            validate_invariant_entry(entry)
        except GateSchemaError as exc:
            entry_id = entry.get("id", f"entry[{i}]")
            errors.append(f"{entry_id}: {exc}")
    return len(errors) == 0, errors


def load_invariant_registry(
    profile: dict[str, Any],
    base_dir: str,
) -> list[dict[str, str]]:
    """Load invariant registry from profile-referenced file.

    Resolves profile.invariants.registry_file relative to base_dir
    (unless it's an absolute path). Returns empty list if no file
    is configured or if the file cannot be read.
    """
    invariants = profile.get("invariants") or {}
    registry_file = invariants.get("registry_file")
    if not registry_file:
        return []
    if not os.path.isabs(registry_file):
        registry_file = os.path.join(base_dir, registry_file)
    entries = load_yaml_registry(registry_file)
    ok, errors = validate_registry(entries)
    if not ok:
        for err in errors:
            print(f"invariant registry validation: {err}")
        valid: list[dict[str, str]] = []
        for entry in entries:
            try:
                validate_invariant_entry(entry)
                valid.append(entry)
            except GateSchemaError:
                pass
        return valid
    return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_invariant_registry.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_invariant_registry.py skills/bmad-story-automator/src/story_automator/core/invariant_registry.py
git commit -m "feat(collector): add invariant registry YAML loader and validator (§6.4)" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Wire invariant registry into profile bridge

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/profile_bridge.py`
- Create: `tests/test_profile_bridge_registry.py`

**Interfaces:**
- Consumes: `invariant_registry.load_invariant_registry(profile, base_dir)`
- Produces: `enrich_profile_invariants(profile, base_dir) -> dict` — returns profile with `rules.invariants.registry` populated from the YAML file

- [ ] **Step 1: Write failing tests for profile bridge registry wiring**

```python
# tests/test_profile_bridge_registry.py
from __future__ import annotations

import os
import tempfile
import unittest


class EnrichProfileInvariantsTests(unittest.TestCase):
    def test_populates_registry_from_file(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
        )
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "invariants.yaml")
            with open(path, "w") as f:
                f.write(content)
            profile = {
                "invariants": {"registry_file": "invariants.yaml"},
                "rules": {},
            }
            enriched = enrich_profile_invariants(profile, tmpdir)
            registry = enriched["rules"]["invariants"]["registry"]
            self.assertEqual(len(registry), 1)
            self.assertEqual(registry[0]["id"], "DG-12")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_preserves_existing_rules(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

        profile = {
            "invariants": {},
            "rules": {"security": {"sast_max_high": 0}},
        }
        enriched = enrich_profile_invariants(profile, "/tmp")
        self.assertEqual(enriched["rules"]["security"]["sast_max_high"], 0)

    def test_no_registry_file_leaves_empty(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

        profile = {"invariants": {}, "rules": {}}
        enriched = enrich_profile_invariants(profile, "/tmp")
        registry = (enriched.get("rules") or {}).get("invariants", {}).get("registry", [])
        self.assertEqual(registry, [])

    def test_does_not_mutate_original(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
        )
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "invariants.yaml")
            with open(path, "w") as f:
                f.write(content)
            profile = {
                "invariants": {"registry_file": "invariants.yaml"},
                "rules": {},
            }
            enriched = enrich_profile_invariants(profile, tmpdir)
            self.assertNotIn("invariants", profile["rules"])
            self.assertIn("invariants", enriched["rules"])
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_merges_with_existing_invariant_rules(self) -> None:
        from story_automator.core.profile_bridge import enrich_profile_invariants

        content = (
            "- id: DG-12\n"
            "  checkable: yes\n"
            "  check_type: semgrep\n"
            "  rule_file: semgrep/dg12.yml\n"
            "  severity: FAIL\n"
        )
        tmpdir = tempfile.mkdtemp()
        try:
            path = os.path.join(tmpdir, "invariants.yaml")
            with open(path, "w") as f:
                f.write(content)
            profile = {
                "invariants": {"registry_file": "invariants.yaml"},
                "rules": {"invariants": {"some_key": "some_value"}},
            }
            enriched = enrich_profile_invariants(profile, tmpdir)
            inv_rules = enriched["rules"]["invariants"]
            self.assertEqual(inv_rules["some_key"], "some_value")
            self.assertEqual(len(inv_rules["registry"]), 1)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_profile_bridge_registry.py -v`
Expected: `ImportError` — `enrich_profile_invariants` does not exist yet.

- [ ] **Step 3: Implement enrich_profile_invariants in profile_bridge.py**

Add to `skills/bmad-story-automator/src/story_automator/core/profile_bridge.py`:

```python
import copy
from .invariant_registry import load_invariant_registry


def enrich_profile_invariants(
    profile: dict[str, Any],
    base_dir: str,
) -> dict[str, Any]:
    """Enrich profile with invariant registry entries from YAML file.

    Loads entries from profile.invariants.registry_file and injects
    them into profile.rules.invariants.registry. Returns a shallow
    copy — does not mutate the original profile.
    """
    enriched = copy.deepcopy(profile)
    entries = load_invariant_registry(profile, base_dir)
    if entries:
        rules = enriched.setdefault("rules", {})
        inv_rules = rules.setdefault("invariants", {})
        inv_rules["registry"] = entries
    return enriched
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_profile_bridge_registry.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_profile_bridge_registry.py skills/bmad-story-automator/src/story_automator/core/profile_bridge.py
git commit -m "feat(collector): wire invariant registry loader into profile bridge" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: Test review check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/test_review_check.py`
- Create: `tests/test_check_test_review.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `test_review_check.py <checkout> <min_score>`. Exit 0 = score met, 1 = below threshold, 2 = usage error. Also exports `read_tea_review(path) -> dict`, `check_score(review, min_score) -> tuple[bool, list[str]]` for unit testing.

- [ ] **Step 1: Write failing tests for test review check script**

```python
# tests/test_check_test_review.py
from __future__ import annotations

import json
import os
import tempfile
import unittest


class TestReviewUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.test_review_check import main

        self.assertEqual(main([]), 2)

    def test_one_arg_returns_2(self) -> None:
        from story_automator.core.checks.test_review_check import main

        self.assertEqual(main(["/tmp"]), 2)

    def test_non_numeric_score_returns_2(self) -> None:
        from story_automator.core.checks.test_review_check import main

        self.assertEqual(main(["/tmp", "abc"]), 2)


class ReadTeaReviewTests(unittest.TestCase):
    def test_reads_valid_review(self) -> None:
        from story_automator.core.checks.test_review_check import read_tea_review

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump({
                "overall_score": 85,
                "dimensions": {
                    "assertion_quality": 90,
                    "isolation": 80,
                    "coverage_depth": 85,
                },
            }, f)
            path = f.name
        try:
            review = read_tea_review(path)
            self.assertEqual(review["overall_score"], 85)
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self) -> None:
        from story_automator.core.checks.test_review_check import read_tea_review

        review = read_tea_review("/nonexistent/path.json")
        self.assertEqual(review, {})

    def test_invalid_json_returns_empty(self) -> None:
        from story_automator.core.checks.test_review_check import read_tea_review

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            f.write("not json")
            path = f.name
        try:
            review = read_tea_review(path)
            self.assertEqual(review, {})
        finally:
            os.unlink(path)


class CheckScoreTests(unittest.TestCase):
    def test_above_threshold_passes(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        review = {"overall_score": 85}
        ok, issues = check_score(review, 70)
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_below_threshold_fails(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        review = {"overall_score": 50}
        ok, issues = check_score(review, 70)
        self.assertFalse(ok)
        self.assertTrue(any("50" in i for i in issues))

    def test_equal_threshold_passes(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        review = {"overall_score": 70}
        ok, issues = check_score(review, 70)
        self.assertTrue(ok)

    def test_missing_score_fails(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        review = {}
        ok, issues = check_score(review, 70)
        self.assertFalse(ok)

    def test_empty_review_fails(self) -> None:
        from story_automator.core.checks.test_review_check import check_score

        ok, issues = check_score({}, 70)
        self.assertFalse(ok)


class MainIntegrationTests(unittest.TestCase):
    def test_review_above_threshold_exits_0(self) -> None:
        from story_automator.core.checks.test_review_check import main

        checkout = tempfile.mkdtemp()
        try:
            tea_dir = os.path.join(checkout, "_bmad", "gate", "tea")
            os.makedirs(tea_dir)
            with open(os.path.join(tea_dir, "test-review.json"), "w") as f:
                json.dump({"overall_score": 85}, f)
            self.assertEqual(main([checkout, "70"]), 0)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_review_file_exits_0(self) -> None:
        from story_automator.core.checks.test_review_check import main

        checkout = tempfile.mkdtemp()
        try:
            self.assertEqual(main([checkout, "70"]), 0)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_test_review.py -v`
Expected: `ModuleNotFoundError` — `test_review_check` module does not exist yet.

- [ ] **Step 3: Implement test review check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/test_review_check.py
"""Check TEA test-review score against threshold.

Standalone script invoked by the test-review-test_quality collector.
Reads TEA test-review.json from the checkout, compares overall_score
against min_score. Gracefully degrades if TEA output is absent.
Exit 0 = score met (or no review), exit 1 = below threshold, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_TEA_REVIEW_PATH = os.path.join("_bmad", "gate", "tea", "test-review.json")


def read_tea_review(path: str) -> dict:
    """Read TEA test-review JSON. Returns {} on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def check_score(
    review: dict, min_score: int,
) -> tuple[bool, list[str]]:
    """Check overall_score against min_score threshold."""
    if not review:
        return False, ["no test-review data available"]
    score = review.get("overall_score")
    if score is None:
        return False, ["test-review missing overall_score"]
    if not isinstance(score, (int, float)):
        return False, [f"test-review overall_score not numeric: {score!r}"]
    if score < min_score:
        return False, [
            f"test-review score {score} below threshold {min_score}"
        ]
    return True, []


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: test_review_check.py <checkout> <min_score>")
        return 2
    checkout = args[0]
    try:
        min_score = int(args[1])
    except ValueError:
        print(f"invalid min_score: {args[1]}")
        return 2
    review_path = os.path.join(checkout, _TEA_REVIEW_PATH)
    review = read_tea_review(review_path)
    if not review:
        print("TEA test-review not found — graceful pass")
        return 0
    ok, issues = check_score(review, min_score)
    for issue in issues:
        print(issue)
    if not ok:
        return 1
    print(f"test-review score {review.get('overall_score')} >= {min_score}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_test_review.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_test_review.py skills/bmad-story-automator/src/story_automator/core/checks/test_review_check.py
git commit -m "feat(collector): add test review check script for test_quality" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Burn-in check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/burn_in_check.py`
- Create: `tests/test_check_burn_in.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `burn_in_check.py <checkout> <runs> <max_flaky> <test_cmd_json>`. Exit 0 = 0 flaky, 1 = flaky found, 2 = usage error. Also exports `run_burn_in(checkout, test_cmd, runs) -> dict[str, list[bool]]`, `detect_flaky(results) -> list[str]` for unit testing.

- [ ] **Step 1: Write failing tests for burn-in check script**

```python
# tests/test_check_burn_in.py
from __future__ import annotations

import unittest


class BurnInUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.burn_in_check import main

        self.assertEqual(main([]), 2)

    def test_too_few_args_returns_2(self) -> None:
        from story_automator.core.checks.burn_in_check import main

        self.assertEqual(main(["/tmp", "5", "0"]), 2)

    def test_non_numeric_runs_returns_2(self) -> None:
        from story_automator.core.checks.burn_in_check import main

        self.assertEqual(main(["/tmp", "abc", "0", '["pytest"]']), 2)


class DetectFlakyTests(unittest.TestCase):
    def test_consistent_pass_not_flaky(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {
            "test_a": [True, True, True],
            "test_b": [True, True, True],
        }
        flaky = detect_flaky(results)
        self.assertEqual(flaky, [])

    def test_consistent_fail_not_flaky(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {
            "test_a": [False, False, False],
        }
        flaky = detect_flaky(results)
        self.assertEqual(flaky, [])

    def test_mixed_results_is_flaky(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {
            "test_a": [True, False, True],
            "test_b": [True, True, True],
        }
        flaky = detect_flaky(results)
        self.assertEqual(flaky, ["test_a"])

    def test_single_run_not_flaky(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {"test_a": [True]}
        flaky = detect_flaky(results)
        self.assertEqual(flaky, [])

    def test_empty_results(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        flaky = detect_flaky({})
        self.assertEqual(flaky, [])

    def test_multiple_flaky_sorted(self) -> None:
        from story_automator.core.checks.burn_in_check import detect_flaky

        results = {
            "test_c": [True, False],
            "test_a": [False, True],
            "test_b": [True, True],
        }
        flaky = detect_flaky(results)
        self.assertEqual(flaky, ["test_a", "test_c"])


class ParseTestOutputTests(unittest.TestCase):
    def test_parses_pytest_output(self) -> None:
        from story_automator.core.checks.burn_in_check import parse_test_names

        output = (
            "tests/test_a.py::test_one PASSED\n"
            "tests/test_a.py::test_two FAILED\n"
            "tests/test_b.py::test_three PASSED\n"
        )
        results = parse_test_names(output)
        self.assertIn("tests/test_a.py::test_one", results)
        self.assertTrue(results["tests/test_a.py::test_one"])
        self.assertIn("tests/test_a.py::test_two", results)
        self.assertFalse(results["tests/test_a.py::test_two"])

    def test_empty_output(self) -> None:
        from story_automator.core.checks.burn_in_check import parse_test_names

        results = parse_test_names("")
        self.assertEqual(results, {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_burn_in.py -v`
Expected: `ModuleNotFoundError` — `burn_in_check` module does not exist yet.

- [ ] **Step 3: Implement burn-in check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/burn_in_check.py
"""Run test suite N times and detect flaky tests.

Standalone script invoked by the burn-in-test_quality collector.
Runs the test command multiple times, tracks per-test pass/fail,
and reports tests that flip. Exit 0 = no flaky, 1 = flaky found,
2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

# v1: pytest format only (name::test PASSED|FAILED). Non-pytest runners
# degrade gracefully (no tests parsed → 0 flaky → pass).
_TEST_RESULT_RE = re.compile(
    r"^(\S+::\S+)\s+(PASSED|FAILED|ERROR)", re.MULTILINE,
)


def parse_test_names(output: str) -> dict[str, bool]:
    """Parse test names and pass/fail status from test runner output."""
    results: dict[str, bool] = {}
    for match in _TEST_RESULT_RE.finditer(output):
        name = match.group(1)
        passed = match.group(2) == "PASSED"
        results[name] = passed
    return results


def run_burn_in(
    checkout: str,
    test_cmd: list[str],
    runs: int,
) -> dict[str, list[bool]]:
    """Run test command N times, collect per-test results."""
    all_results: dict[str, list[bool]] = {}
    for _ in range(runs):
        try:
            proc = subprocess.run(
                test_cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=checkout,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        run_results = parse_test_names(combined)
        for name, passed in run_results.items():
            all_results.setdefault(name, []).append(passed)
    return all_results


def detect_flaky(results: dict[str, list[bool]]) -> list[str]:
    """Return sorted list of test names that flipped between runs."""
    flaky: list[str] = []
    for name, outcomes in results.items():
        if len(outcomes) < 2:
            continue
        if len(set(outcomes)) > 1:
            flaky.append(name)
    return sorted(flaky)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 4:
        print("usage: burn_in_check.py <checkout> <runs> <max_flaky> <test_cmd_json>")
        return 2
    checkout = args[0]
    try:
        runs = int(args[1])
        max_flaky = int(args[2])
    except ValueError:
        print(f"runs and max_flaky must be integers")
        return 2
    try:
        test_cmd: list[str] = json.loads(args[3])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid test command: {args[3]}")
        return 2
    if not isinstance(test_cmd, list) or not test_cmd:
        print("test_cmd must be a non-empty JSON array")
        return 2
    results = run_burn_in(checkout, test_cmd, runs)
    flaky = detect_flaky(results)
    for name in flaky:
        outcomes = results[name]
        pass_rate = sum(outcomes) / len(outcomes) * 100
        print(f"FLAKY: {name} ({pass_rate:.0f}% pass rate over {len(outcomes)} runs)")
    if len(flaky) > max_flaky:
        print(f"{len(flaky)} flaky test(s) found, max allowed {max_flaky}")
        return 1
    total = len(results)
    print(f"{total} test(s) across {runs} run(s), {len(flaky)} flaky (max {max_flaky})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_burn_in.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_burn_in.py skills/bmad-story-automator/src/story_automator/core/checks/burn_in_check.py
git commit -m "feat(collector): add burn-in check script for test_quality" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Hard-wait detector check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/hard_wait_check.py`
- Create: `tests/test_check_hard_wait.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `hard_wait_check.py <checkout> [extensions_json]`. Exit 0 = no hard waits, 1 = hard waits found, 2 = usage error. Also exports `scan_for_hard_waits(content, filename) -> list[str]`, `scan_test_files(checkout, extensions) -> list[str]` for unit testing.

- [ ] **Step 1: Write failing tests for hard-wait check script**

```python
# tests/test_check_hard_wait.py
from __future__ import annotations

import os
import tempfile
import unittest


class HardWaitUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.hard_wait_check import main

        self.assertEqual(main([]), 2)


class ScanForHardWaitsTests(unittest.TestCase):
    def test_time_sleep_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "import time\ntime.sleep(5)\n"
        findings = scan_for_hard_waits(content, "test_app.py")
        self.assertEqual(len(findings), 1)
        self.assertIn("time.sleep", findings[0])

    def test_set_timeout_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "await new Promise(r => setTimeout(r, 5000));\n"
        findings = scan_for_hard_waits(content, "test_app.ts")
        self.assertEqual(len(findings), 1)
        self.assertIn("setTimeout", findings[0])

    def test_cy_wait_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "cy.wait(3000)\n"
        findings = scan_for_hard_waits(content, "test_app.cy.ts")
        self.assertEqual(len(findings), 1)
        self.assertIn("cy.wait", findings[0])

    def test_asyncio_sleep_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "await asyncio.sleep(10)\n"
        findings = scan_for_hard_waits(content, "test_async.py")
        self.assertEqual(len(findings), 1)

    def test_thread_sleep_detected(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "Thread.sleep(1000)\n"
        findings = scan_for_hard_waits(content, "Test.java")
        self.assertEqual(len(findings), 1)

    def test_clean_code_passes(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "def test_something():\n    assert True\n"
        findings = scan_for_hard_waits(content, "test_app.py")
        self.assertEqual(findings, [])

    def test_page_wait_for_selector_ok(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_for_hard_waits

        content = "await page.waitForSelector('.ready')\n"
        findings = scan_for_hard_waits(content, "test_app.ts")
        self.assertEqual(findings, [])


class ScanTestFilesTests(unittest.TestCase):
    def test_scans_test_directories(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_test_files

        checkout = tempfile.mkdtemp()
        try:
            tests_dir = os.path.join(checkout, "tests")
            os.makedirs(tests_dir)
            with open(os.path.join(tests_dir, "test_slow.py"), "w") as f:
                f.write("import time\ntime.sleep(30)\n")
            findings = scan_test_files(checkout, [".py"])
            self.assertTrue(len(findings) >= 1)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_skips_non_test_files(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_test_files

        checkout = tempfile.mkdtemp()
        try:
            src_dir = os.path.join(checkout, "src")
            os.makedirs(src_dir)
            with open(os.path.join(src_dir, "app.py"), "w") as f:
                f.write("import time\ntime.sleep(1)\n")
            findings = scan_test_files(checkout, [".py"])
            self.assertEqual(findings, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_test_dir_returns_empty(self) -> None:
        from story_automator.core.checks.hard_wait_check import scan_test_files

        checkout = tempfile.mkdtemp()
        try:
            findings = scan_test_files(checkout, [".py"])
            self.assertEqual(findings, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_hard_wait.py -v`
Expected: `ModuleNotFoundError` — `hard_wait_check` module does not exist yet.

- [ ] **Step 3: Implement hard-wait detector check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/hard_wait_check.py
"""Detect hard waits in test files (time.sleep, setTimeout, etc.).

Standalone script invoked by the hard-wait-test_quality collector.
Scans test files for hard-coded wait patterns that indicate
non-deterministic timing dependencies.
Exit 0 = no hard waits, exit 1 = hard waits found, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_HARD_WAIT_PATTERNS = [
    (re.compile(r"\btime\.sleep\s*\("), "time.sleep"),
    (re.compile(r"\basyncio\.sleep\s*\("), "asyncio.sleep"),
    (re.compile(r"\bsetTimeout\s*\("), "setTimeout"),
    (re.compile(r"\bcy\.wait\s*\(\s*\d"), "cy.wait"),
    (re.compile(r"\bThread\.sleep\s*\("), "Thread.sleep"),
    (re.compile(r"\bpage\.waitForTimeout\s*\("), "page.waitForTimeout"),
]

_TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "e2e"}
_DEFAULT_EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx"]


def scan_for_hard_waits(content: str, filename: str) -> list[str]:
    """Scan content for hard-wait patterns. Returns findings."""
    findings: list[str] = []
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        for pattern, label in _HARD_WAIT_PATTERNS:
            if pattern.search(line):
                findings.append(
                    f"HARD_WAIT: {filename}:{i}: {label}: {line.strip()}"
                )
    return findings


def scan_test_files(
    checkout: str, extensions: list[str],
) -> list[str]:
    """Walk checkout for test directories, scan matching files."""
    all_findings: list[str] = []
    for root, dirs, files in os.walk(checkout):
        rel_root = os.path.relpath(root, checkout)
        parts = set(rel_root.replace("\\", "/").split("/"))
        if not parts & _TEST_DIR_NAMES:
            continue
        for fname in sorted(files):
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            path = os.path.join(root, fname)
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            rel = os.path.relpath(path, checkout)
            all_findings.extend(scan_for_hard_waits(content, rel))
    return all_findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: hard_wait_check.py <checkout> [extensions_json]")
        return 2
    checkout = args[0]
    if len(args) > 1:
        try:
            extensions: list[str] = json.loads(args[1])
        except (json.JSONDecodeError, TypeError):
            print(f"invalid extensions: {args[1]}")
            return 2
    else:
        extensions = _DEFAULT_EXTENSIONS
    findings = scan_test_files(checkout, extensions)
    for f in findings:
        print(f)
    if findings:
        print(f"{len(findings)} hard wait(s) found in test files")
        return 1
    print("no hard waits found in test files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_hard_wait.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_hard_wait.py skills/bmad-story-automator/src/story_automator/core/checks/hard_wait_check.py
git commit -m "feat(collector): add hard-wait detector check script for test_quality" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: test_quality collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/test_quality.py`
- Create: `tests/test_collectors_test_quality.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; 3 check scripts from `core/checks/`
- Produces: `TEST_REVIEW: CollectorConfig`, `BURN_IN: CollectorConfig`, `HARD_WAIT: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (3 items)

- [ ] **Step 1: Write failing tests for test_quality collectors**

```python
# tests/test_collectors_test_quality.py
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class TestReviewCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.test_quality import TEST_REVIEW

        self.assertEqual(TEST_REVIEW.collector_id, "test-review-test_quality")
        self.assertEqual(TEST_REVIEW.tool, "python3")
        self.assertEqual(TEST_REVIEW.category, "test_quality")
        self.assertTrue(TEST_REVIEW.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.test_quality import TEST_REVIEW

        cmd = TEST_REVIEW.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("test_review_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "70")

    def test_build_cmd_custom_score(self) -> None:
        from story_automator.core.collectors.test_quality import TEST_REVIEW

        profile = {"rules": {"test_quality": {"min_score": 85}}}
        cmd = TEST_REVIEW.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "85")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.test_quality import TEST_REVIEW

        cmd = TEST_REVIEW.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class BurnInCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.test_quality import BURN_IN

        self.assertEqual(BURN_IN.collector_id, "burn-in-test_quality")
        self.assertEqual(BURN_IN.tool, "python3")
        self.assertEqual(BURN_IN.category, "test_quality")
        self.assertTrue(BURN_IN.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.test_quality import BURN_IN

        cmd = BURN_IN.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("burn_in_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "5")
        self.assertEqual(cmd[4], "0")
        test_cmd = json.loads(cmd[5])
        self.assertEqual(test_cmd, ["pytest", "-v", "--tb=line"])

    def test_build_cmd_custom_config(self) -> None:
        from story_automator.core.collectors.test_quality import BURN_IN

        profile = {
            "rules": {
                "test_quality": {
                    "burn_in_runs": 10,
                    "max_flaky": 2,
                    "burn_in_cmd": ["npx", "vitest", "run"],
                },
            },
        }
        cmd = BURN_IN.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "10")
        self.assertEqual(cmd[4], "2")
        test_cmd = json.loads(cmd[5])
        self.assertEqual(test_cmd, ["npx", "vitest", "run"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.test_quality import BURN_IN

        cmd = BURN_IN.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class HardWaitCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.test_quality import HARD_WAIT

        self.assertEqual(HARD_WAIT.collector_id, "hard-wait-test_quality")
        self.assertEqual(HARD_WAIT.tool, "python3")
        self.assertEqual(HARD_WAIT.category, "test_quality")
        self.assertTrue(HARD_WAIT.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.test_quality import HARD_WAIT

        cmd = HARD_WAIT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("hard_wait_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.test_quality import HARD_WAIT

        cmd = HARD_WAIT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class TestQualityCollectorListTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.test_quality import COLLECTORS

        self.assertEqual(len(COLLECTORS), 3)

    def test_all_test_quality_category(self) -> None:
        from story_automator.core.collectors.test_quality import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "test_quality")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.test_quality import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "test-review-test_quality",
            "burn-in-test_quality",
            "hard-wait-test_quality",
        })

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.test_quality import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_test_quality.py -v`
Expected: `ModuleNotFoundError` — `test_quality` module does not exist yet.

- [ ] **Step 3: Implement test_quality collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/test_quality.py
"""Test-quality-category evidence collectors (§6.2).

PASS rule: TEA test-review >= band; 0 flaky over burn-in N×; no hard-waits.
Collectors: test-review-test_quality, burn-in-test_quality, hard-wait-test_quality.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_MIN_SCORE = 70
_DEFAULT_BURN_IN_RUNS = 5
_DEFAULT_MAX_FLAKY = 0
_DEFAULT_BURN_IN_CMD = ["pytest", "-v", "--tb=line"]


def _test_review_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("test_quality") or {}
    min_score = rules.get("min_score", _DEFAULT_MIN_SCORE)
    return [
        sys.executable,
        str(_CHECKS_DIR / "test_review_check.py"),
        checkout,
        str(int(min_score)),
    ]


def _burn_in_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("test_quality") or {}
    runs = rules.get("burn_in_runs", _DEFAULT_BURN_IN_RUNS)
    max_flaky = rules.get("max_flaky", _DEFAULT_MAX_FLAKY)
    test_cmd = rules.get("burn_in_cmd", _DEFAULT_BURN_IN_CMD)
    return [
        sys.executable,
        str(_CHECKS_DIR / "burn_in_check.py"),
        checkout,
        str(int(runs)),
        str(int(max_flaky)),
        json.dumps(test_cmd),
    ]


def _hard_wait_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "hard_wait_check.py"),
        checkout,
    ]


TEST_REVIEW = CollectorConfig(
    collector_id="test-review-test_quality",
    tool="python3",
    category="test_quality",
    build_cmd=_test_review_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

BURN_IN = CollectorConfig(
    collector_id="burn-in-test_quality",
    tool="python3",
    category="test_quality",
    build_cmd=_burn_in_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
    deterministic=True,
)

HARD_WAIT = CollectorConfig(
    collector_id="hard-wait-test_quality",
    tool="python3",
    category="test_quality",
    build_cmd=_hard_wait_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [TEST_REVIEW, BURN_IN, HARD_WAIT]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_test_quality.py -v`
Expected: All 15 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_test_quality.py skills/bmad-story-automator/src/story_automator/core/collectors/test_quality.py
git commit -m "feat(collector): add test_quality collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Mutation check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/mutation_check.py`
- Create: `tests/test_check_mutation.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `mutation_check.py <checkout> <tool> <threshold>`. Exit 0 = threshold met, 1 = below threshold, 2 = usage error. Also exports `parse_mutmut_results(output) -> dict`, `parse_stryker_results(output) -> dict`, `check_threshold(score, threshold) -> tuple[bool, list[str]]` for unit testing.

- [ ] **Step 1: Write failing tests for mutation check script**

```python
# tests/test_check_mutation.py
from __future__ import annotations

import unittest


class MutationCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.mutation_check import main

        self.assertEqual(main([]), 2)

    def test_two_args_returns_2(self) -> None:
        from story_automator.core.checks.mutation_check import main

        self.assertEqual(main(["/tmp", "mutmut"]), 2)

    def test_unsupported_tool_returns_2(self) -> None:
        from story_automator.core.checks.mutation_check import main

        self.assertEqual(main(["/tmp", "unknown", "80"]), 2)

    def test_non_numeric_threshold_returns_2(self) -> None:
        from story_automator.core.checks.mutation_check import main

        self.assertEqual(main(["/tmp", "mutmut", "abc"]), 2)


class ParseMutmutResultsTests(unittest.TestCase):
    def test_parses_summary_line(self) -> None:
        from story_automator.core.checks.mutation_check import parse_mutmut_results

        output = (
            "Legend for output:\n"
            "Killed 85 out of 100 mutants\n"
            "Survived: 15\n"
        )
        result = parse_mutmut_results(output)
        self.assertEqual(result["killed"], 85)
        self.assertEqual(result["total"], 100)
        self.assertAlmostEqual(result["score"], 85.0)

    def test_zero_mutants(self) -> None:
        from story_automator.core.checks.mutation_check import parse_mutmut_results

        output = "No mutants generated\n"
        result = parse_mutmut_results(output)
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["score"], 100.0)

    def test_empty_output(self) -> None:
        from story_automator.core.checks.mutation_check import parse_mutmut_results

        result = parse_mutmut_results("")
        self.assertEqual(result["score"], -1)


class ParseStrykerResultsTests(unittest.TestCase):
    def test_parses_summary(self) -> None:
        from story_automator.core.checks.mutation_check import parse_stryker_results

        output = (
            "All tests\n"
            "Mutation score: 92.50\n"
            "Killed: 37, Survived: 3, Timeout: 0, No coverage: 0\n"
        )
        result = parse_stryker_results(output)
        self.assertAlmostEqual(result["score"], 92.5)

    def test_empty_output(self) -> None:
        from story_automator.core.checks.mutation_check import parse_stryker_results

        result = parse_stryker_results("")
        self.assertEqual(result["score"], -1)


class CheckThresholdTests(unittest.TestCase):
    def test_above_threshold_passes(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(85.0, 80)
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_below_threshold_fails(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(60.0, 80)
        self.assertFalse(ok)
        self.assertTrue(any("60" in i for i in issues))

    def test_equal_threshold_passes(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(80.0, 80)
        self.assertTrue(ok)

    def test_negative_score_fails(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(-1, 80)
        self.assertFalse(ok)

    def test_zero_total_passes(self) -> None:
        from story_automator.core.checks.mutation_check import check_threshold

        ok, issues = check_threshold(100.0, 80)
        self.assertTrue(ok)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_mutation.py -v`
Expected: `ModuleNotFoundError` — `mutation_check` module does not exist yet.

- [ ] **Step 3: Implement mutation check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/mutation_check.py
"""Run mutation testing tool and check score against threshold.

Standalone script invoked by mutation collectors.
Runs mutmut (Python) or stryker (TypeScript), parses output for
mutation score, and compares against threshold.
Exit 0 = threshold met, exit 1 = below threshold, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import re
import subprocess
import sys

_MUTMUT_KILLED_RE = re.compile(
    r"Killed\s+(\d+)\s+out\s+of\s+(\d+)", re.IGNORECASE,
)
_STRYKER_SCORE_RE = re.compile(
    r"Mutation\s+score:\s+([\d.]+)", re.IGNORECASE,
)
_SUPPORTED_TOOLS = ("mutmut", "stryker")


def parse_mutmut_results(output: str) -> dict:
    """Parse mutmut output for killed/total counts."""
    match = _MUTMUT_KILLED_RE.search(output)
    if match:
        killed = int(match.group(1))
        total = int(match.group(2))
        score = (killed / total * 100) if total > 0 else 100.0
        return {"killed": killed, "total": total, "score": score}
    if "no mutants" in output.lower() or not output.strip():
        if "no mutants" in output.lower():
            return {"killed": 0, "total": 0, "score": 100.0}
        return {"killed": 0, "total": 0, "score": -1}
    return {"killed": 0, "total": 0, "score": -1}


def parse_stryker_results(output: str) -> dict:
    """Parse Stryker output for mutation score."""
    match = _STRYKER_SCORE_RE.search(output)
    if match:
        score = float(match.group(1))
        return {"score": score}
    return {"score": -1}


def check_threshold(
    score: float, threshold: int,
) -> tuple[bool, list[str]]:
    """Check mutation score against threshold."""
    if score < 0:
        return False, ["mutation testing produced no score"]
    if score < threshold:
        return False, [
            f"mutation score {score:.1f}% below threshold {threshold}%"
        ]
    return True, []


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 3:
        print("usage: mutation_check.py <checkout> <tool> <threshold>")
        return 2
    checkout = args[0]
    tool = args[1]
    if tool not in _SUPPORTED_TOOLS:
        print(f"unsupported mutation tool: {tool}")
        return 2
    try:
        threshold = int(args[2])
    except ValueError:
        print(f"invalid threshold: {args[2]}")
        return 2
    if tool == "mutmut":
        cmd = ["mutmut", "run", "--CI"]
    else:
        cmd = ["npx", "stryker", "run"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=1800, cwd=checkout,
        )
    except FileNotFoundError:
        print(f"{tool} not found")
        return 1
    except subprocess.TimeoutExpired:
        print(f"{tool} timed out")
        return 1
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if tool == "mutmut":
        result = parse_mutmut_results(output)
    else:
        result = parse_stryker_results(output)
    ok, issues = check_threshold(result["score"], threshold)
    for issue in issues:
        print(issue)
    if not ok:
        return 1
    print(f"mutation score {result['score']:.1f}% >= {threshold}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_mutation.py -v`
Expected: All 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_mutation.py skills/bmad-story-automator/src/story_automator/core/checks/mutation_check.py
git commit -m "feat(collector): add mutation check script" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: mutation collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/mutation.py`
- Create: `tests/test_collectors_mutation.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; `mutation_check.py` from `core/checks/`
- Produces: `MUTMUT: CollectorConfig`, `STRYKER: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (2 items)

- [ ] **Step 1: Write failing tests for mutation collectors**

```python
# tests/test_collectors_mutation.py
from __future__ import annotations

import sys
import unittest
from pathlib import Path


class MutmutCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.mutation import MUTMUT

        self.assertEqual(MUTMUT.collector_id, "mutmut-mutation")
        self.assertEqual(MUTMUT.tool, "python3")
        self.assertEqual(MUTMUT.category, "mutation")
        self.assertTrue(MUTMUT.deterministic)
        self.assertIn("*.py", MUTMUT.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.mutation import MUTMUT

        cmd = MUTMUT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("mutation_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "mutmut")
        self.assertEqual(cmd[4], "80")

    def test_build_cmd_custom_threshold(self) -> None:
        from story_automator.core.collectors.mutation import MUTMUT

        profile = {"rules": {"mutation": {"threshold": 90}}}
        cmd = MUTMUT.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[4], "90")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.mutation import MUTMUT

        cmd = MUTMUT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class StrykerCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.mutation import STRYKER

        self.assertEqual(STRYKER.collector_id, "stryker-mutation")
        self.assertEqual(STRYKER.tool, "python3")
        self.assertEqual(STRYKER.category, "mutation")
        self.assertTrue(STRYKER.deterministic)
        self.assertIn("*.ts", STRYKER.file_patterns)
        self.assertIn("*.tsx", STRYKER.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.mutation import STRYKER

        cmd = STRYKER.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("mutation_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "stryker")
        self.assertEqual(cmd[4], "80")

    def test_build_cmd_custom_threshold(self) -> None:
        from story_automator.core.collectors.mutation import STRYKER

        profile = {"rules": {"mutation": {"threshold": 95}}}
        cmd = STRYKER.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[4], "95")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.mutation import STRYKER

        cmd = STRYKER.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class MutationCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.mutation import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_mutation_category(self) -> None:
        from story_automator.core.collectors.mutation import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "mutation")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.mutation import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"mutmut-mutation", "stryker-mutation"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.mutation import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_mutation.py -v`
Expected: `ModuleNotFoundError` — `mutation` module does not exist yet.

- [ ] **Step 3: Implement mutation collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/mutation.py
"""Mutation-category evidence collectors (§6.2).

PASS rule: mutation score >= threshold on changed code (sampled/budgeted).
Collectors: mutmut-mutation (Python), stryker-mutation (TypeScript).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_THRESHOLD = 80


def _mutmut_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("mutation") or {}
    threshold = rules.get("threshold", _DEFAULT_THRESHOLD)
    return [
        sys.executable,
        str(_CHECKS_DIR / "mutation_check.py"),
        checkout,
        "mutmut",
        str(int(threshold)),
    ]


def _stryker_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("mutation") or {}
    threshold = rules.get("threshold", _DEFAULT_THRESHOLD)
    return [
        sys.executable,
        str(_CHECKS_DIR / "mutation_check.py"),
        checkout,
        "stryker",
        str(int(threshold)),
    ]


MUTMUT = CollectorConfig(
    collector_id="mutmut-mutation",
    tool="python3",
    category="mutation",
    build_cmd=_mutmut_cmd,
    file_patterns=frozenset({"*.py"}),
)

STRYKER = CollectorConfig(
    collector_id="stryker-mutation",
    tool="python3",
    category="mutation",
    build_cmd=_stryker_cmd,
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [MUTMUT, STRYKER]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_mutation.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_mutation.py skills/bmad-story-automator/src/story_automator/core/collectors/mutation.py
git commit -m "feat(collector): add mutation collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: Pack-schema check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/pack_schema_check.py`
- Create: `tests/test_check_pack_schema.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `pack_schema_check.py <checkout> [tools_dir]`. Exit 0 = valid, 1 = missing fields, 2 = usage error. Also exports `find_tool_definitions(checkout, tools_dir) -> list[dict]`, `validate_pack_schema(tool_def) -> list[str]` for unit testing.

- [ ] **Step 1: Write failing tests for pack-schema check script**

```python
# tests/test_check_pack_schema.py
from __future__ import annotations

import json
import os
import tempfile
import unittest


class PackSchemaUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.pack_schema_check import main

        self.assertEqual(main([]), 2)


class ValidatePackSchemaTests(unittest.TestCase):
    def test_valid_tool_passes(self) -> None:
        from story_automator.core.checks.pack_schema_check import validate_pack_schema

        tool_def = {
            "name": "search_tool",
            "risk_tier": "low",
            "reversibility_class": "reversible",
            "time_lock": "none",
            "autonomy": "supervised",
        }
        issues = validate_pack_schema(tool_def)
        self.assertEqual(issues, [])

    def test_missing_risk_tier_fails(self) -> None:
        from story_automator.core.checks.pack_schema_check import validate_pack_schema

        tool_def = {
            "name": "search_tool",
            "reversibility_class": "reversible",
            "time_lock": "none",
            "autonomy": "supervised",
        }
        issues = validate_pack_schema(tool_def)
        self.assertEqual(len(issues), 1)
        self.assertIn("risk_tier", issues[0])

    def test_missing_multiple_fields_reports_all(self) -> None:
        from story_automator.core.checks.pack_schema_check import validate_pack_schema

        tool_def = {"name": "tool"}
        issues = validate_pack_schema(tool_def)
        self.assertEqual(len(issues), 4)

    def test_empty_field_fails(self) -> None:
        from story_automator.core.checks.pack_schema_check import validate_pack_schema

        tool_def = {
            "name": "tool",
            "risk_tier": "",
            "reversibility_class": "reversible",
            "time_lock": "none",
            "autonomy": "supervised",
        }
        issues = validate_pack_schema(tool_def)
        self.assertEqual(len(issues), 1)
        self.assertIn("risk_tier", issues[0])


class FindToolDefinitionsTests(unittest.TestCase):
    def test_finds_json_tool_files(self) -> None:
        from story_automator.core.checks.pack_schema_check import find_tool_definitions

        checkout = tempfile.mkdtemp()
        try:
            tools_dir = os.path.join(checkout, "tools")
            os.makedirs(tools_dir)
            tool = {
                "name": "search",
                "risk_tier": "low",
                "reversibility_class": "reversible",
                "time_lock": "none",
                "autonomy": "supervised",
            }
            with open(os.path.join(tools_dir, "search.tool.json"), "w") as f:
                json.dump(tool, f)
            defs = find_tool_definitions(checkout, "tools")
            self.assertEqual(len(defs), 1)
            self.assertEqual(defs[0]["name"], "search")
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_tools_dir_returns_empty(self) -> None:
        from story_automator.core.checks.pack_schema_check import find_tool_definitions

        checkout = tempfile.mkdtemp()
        try:
            defs = find_tool_definitions(checkout, "tools")
            self.assertEqual(defs, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_invalid_json_skipped(self) -> None:
        from story_automator.core.checks.pack_schema_check import find_tool_definitions

        checkout = tempfile.mkdtemp()
        try:
            tools_dir = os.path.join(checkout, "tools")
            os.makedirs(tools_dir)
            with open(os.path.join(tools_dir, "bad.tool.json"), "w") as f:
                f.write("not json")
            defs = find_tool_definitions(checkout, "tools")
            self.assertEqual(defs, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_pack_schema.py -v`
Expected: `ModuleNotFoundError` — `pack_schema_check` module does not exist yet.

- [ ] **Step 3: Implement pack-schema check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/pack_schema_check.py
"""Validate agent tool pack-schema v1.2 envelope fields.

Standalone script invoked by the pack-schema-agentic collector.
Finds tool definition files, validates required pack-schema v1.2
fields: {risk_tier, reversibility_class, time_lock, autonomy}.
Exit 0 = all valid, exit 1 = missing/invalid fields, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_REQUIRED_FIELDS = ("risk_tier", "reversibility_class", "time_lock", "autonomy")
_TOOL_SUFFIX = ".tool.json"


def find_tool_definitions(
    checkout: str, tools_dir: str,
) -> list[dict]:
    """Find and load tool definition files."""
    path = os.path.join(checkout, tools_dir)
    if not os.path.isdir(path):
        return []
    defs: list[dict] = []
    for root, _dirs, files in os.walk(path):
        for fname in sorted(files):
            if not fname.endswith(_TOOL_SUFFIX):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data["_source_file"] = os.path.relpath(fpath, checkout)
                    defs.append(data)
            except (OSError, json.JSONDecodeError):
                continue
    return defs


def validate_pack_schema(tool_def: dict) -> list[str]:
    """Validate a tool definition has required pack-schema v1.2 fields."""
    issues: list[str] = []
    name = tool_def.get("name", tool_def.get("_source_file", "unknown"))
    for field in _REQUIRED_FIELDS:
        value = tool_def.get(field)
        if not value or not isinstance(value, str) or not value.strip():
            issues.append(f"{name}: missing or empty field '{field}'")
    return issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: pack_schema_check.py <checkout> [tools_dir]")
        return 2
    checkout = args[0]
    tools_dir = args[1] if len(args) > 1 else "tools"
    defs = find_tool_definitions(checkout, tools_dir)
    if not defs:
        print("no tool definitions found — pack-schema N/A")
        return 0
    all_issues: list[str] = []
    for tool_def in defs:
        all_issues.extend(validate_pack_schema(tool_def))
    for issue in all_issues:
        print(issue)
    if all_issues:
        print(f"{len(all_issues)} pack-schema violation(s)")
        return 1
    print(f"{len(defs)} tool definition(s) validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_pack_schema.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_pack_schema.py skills/bmad-story-automator/src/story_automator/core/checks/pack_schema_check.py
git commit -m "feat(collector): add pack-schema check script for agentic" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: AIBOM check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/aibom_check.py`
- Create: `tests/test_check_aibom.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `aibom_check.py <checkout> [aibom_path]`. Exit 0 = all tools covered, 1 = missing entries, 2 = usage error. Also exports `load_aibom(path) -> dict`, `find_tool_names(checkout) -> set[str]`, `check_aibom_coverage(tools, aibom) -> list[str]` for unit testing.

- [ ] **Step 1: Write failing tests for AIBOM check script**

```python
# tests/test_check_aibom.py
from __future__ import annotations

import json
import os
import tempfile
import unittest


class AibomUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.aibom_check import main

        self.assertEqual(main([]), 2)


class LoadAibomTests(unittest.TestCase):
    def test_loads_valid_aibom(self) -> None:
        from story_automator.core.checks.aibom_check import load_aibom

        aibom = {
            "components": [
                {"name": "search_tool", "type": "machine-learning-model"},
                {"name": "classify_tool", "type": "machine-learning-model"},
            ],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(aibom, f)
            path = f.name
        try:
            data = load_aibom(path)
            self.assertEqual(len(data.get("components", [])), 2)
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self) -> None:
        from story_automator.core.checks.aibom_check import load_aibom

        data = load_aibom("/nonexistent/path.json")
        self.assertEqual(data, {})


class FindToolNamesTests(unittest.TestCase):
    def test_finds_tool_json_files(self) -> None:
        from story_automator.core.checks.aibom_check import find_tool_names

        checkout = tempfile.mkdtemp()
        try:
            tools_dir = os.path.join(checkout, "tools")
            os.makedirs(tools_dir)
            with open(os.path.join(tools_dir, "search.tool.json"), "w") as f:
                json.dump({"name": "search_tool"}, f)
            names = find_tool_names(checkout)
            self.assertIn("search_tool", names)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_tools_returns_empty(self) -> None:
        from story_automator.core.checks.aibom_check import find_tool_names

        checkout = tempfile.mkdtemp()
        try:
            names = find_tool_names(checkout)
            self.assertEqual(names, set())
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)


class CheckAibomCoverageTests(unittest.TestCase):
    def test_all_covered_passes(self) -> None:
        from story_automator.core.checks.aibom_check import check_aibom_coverage

        tools = {"search_tool", "classify_tool"}
        aibom = {
            "components": [
                {"name": "search_tool"},
                {"name": "classify_tool"},
            ],
        }
        issues = check_aibom_coverage(tools, aibom)
        self.assertEqual(issues, [])

    def test_missing_tool_fails(self) -> None:
        from story_automator.core.checks.aibom_check import check_aibom_coverage

        tools = {"search_tool", "classify_tool"}
        aibom = {"components": [{"name": "search_tool"}]}
        issues = check_aibom_coverage(tools, aibom)
        self.assertEqual(len(issues), 1)
        self.assertIn("classify_tool", issues[0])

    def test_empty_tools_passes(self) -> None:
        from story_automator.core.checks.aibom_check import check_aibom_coverage

        issues = check_aibom_coverage(set(), {})
        self.assertEqual(issues, [])

    def test_empty_aibom_with_tools_fails(self) -> None:
        from story_automator.core.checks.aibom_check import check_aibom_coverage

        issues = check_aibom_coverage({"tool_a"}, {})
        self.assertEqual(len(issues), 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_aibom.py -v`
Expected: `ModuleNotFoundError` — `aibom_check` module does not exist yet.

- [ ] **Step 3: Implement AIBOM check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/aibom_check.py
"""Validate AIBOM entries for agent tools.

Standalone script invoked by the aibom-diff-agentic collector.
Checks that every tool definition has a corresponding entry in the
AIBOM (CycloneDX-1.6 / SPDX-AI-3.0 format). FAIL if missing.
Exit 0 = all covered, exit 1 = missing entries, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_AIBOM_DEFAULT = os.path.join("aibom", "aibom.json")
_TOOL_SUFFIX = ".tool.json"


def load_aibom(path: str) -> dict:
    """Load AIBOM JSON. Returns {} on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def find_tool_names(checkout: str) -> set[str]:
    """Find tool names from *.tool.json files."""
    tools_dir = os.path.join(checkout, "tools")
    if not os.path.isdir(tools_dir):
        return set()
    names: set[str] = set()
    for root, _dirs, files in os.walk(tools_dir):
        for fname in files:
            if not fname.endswith(_TOOL_SUFFIX):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("name"):
                    names.add(data["name"])
            except (OSError, json.JSONDecodeError):
                continue
    return names


def check_aibom_coverage(
    tools: set[str], aibom: dict,
) -> list[str]:
    """Check that all tool names have AIBOM entries."""
    if not tools:
        return []
    components = aibom.get("components") or []
    covered = {
        c.get("name") for c in components
        if isinstance(c, dict) and c.get("name")
    }
    issues: list[str] = []
    for tool_name in sorted(tools):
        if tool_name not in covered:
            issues.append(f"MISSING AIBOM entry: {tool_name}")
    return issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: aibom_check.py <checkout> [aibom_path]")
        return 2
    checkout = args[0]
    aibom_path = args[1] if len(args) > 1 else os.path.join(checkout, _AIBOM_DEFAULT)
    tools = find_tool_names(checkout)
    if not tools:
        print("no tool definitions found — AIBOM check N/A")
        return 0
    aibom = load_aibom(aibom_path)
    issues = check_aibom_coverage(tools, aibom)
    for issue in issues:
        print(issue)
    if issues:
        print(f"{len(issues)} tool(s) missing AIBOM entries")
        return 1
    print(f"all {len(tools)} tool(s) have AIBOM entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_aibom.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_aibom.py skills/bmad-story-automator/src/story_automator/core/checks/aibom_check.py
git commit -m "feat(collector): add AIBOM check script for agentic" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: OPA constitution check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/opa_check.py`
- Create: `tests/test_check_opa.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `opa_check.py <checkout> [policy_dir]`. Exit 0 = compile + test green, 1 = failures, 2 = usage error. Also exports `run_opa_compile(checkout, policy_dir) -> tuple[bool, str]`, `run_opa_test(checkout, policy_dir) -> tuple[bool, str]` for unit testing.

- [ ] **Step 1: Write failing tests for OPA check script**

```python
# tests/test_check_opa.py
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock


class OpaCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.opa_check import main

        self.assertEqual(main([]), 2)


class RunOpaCompileTests(unittest.TestCase):
    def test_no_policy_dir_returns_pass(self) -> None:
        from story_automator.core.checks.opa_check import run_opa_compile

        checkout = tempfile.mkdtemp()
        try:
            ok, msg = run_opa_compile(checkout, "policy")
            self.assertTrue(ok)
            self.assertIn("no policy", msg.lower())
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    @patch("subprocess.run")
    def test_compile_success(self, mock_run: MagicMock) -> None:
        from story_automator.core.checks.opa_check import run_opa_compile

        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        checkout = tempfile.mkdtemp()
        try:
            policy_dir = os.path.join(checkout, "policy")
            os.makedirs(policy_dir)
            with open(os.path.join(policy_dir, "main.rego"), "w") as f:
                f.write("package main\n")
            ok, msg = run_opa_compile(checkout, "policy")
            self.assertTrue(ok)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    @patch("subprocess.run")
    def test_compile_failure(self, mock_run: MagicMock) -> None:
        from story_automator.core.checks.opa_check import run_opa_compile

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error: parse error",
        )
        checkout = tempfile.mkdtemp()
        try:
            policy_dir = os.path.join(checkout, "policy")
            os.makedirs(policy_dir)
            with open(os.path.join(policy_dir, "main.rego"), "w") as f:
                f.write("package main\n")
            ok, msg = run_opa_compile(checkout, "policy")
            self.assertFalse(ok)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)


class RunOpaTestTests(unittest.TestCase):
    def test_no_test_files_returns_pass(self) -> None:
        from story_automator.core.checks.opa_check import run_opa_test

        checkout = tempfile.mkdtemp()
        try:
            policy_dir = os.path.join(checkout, "policy")
            os.makedirs(policy_dir)
            with open(os.path.join(policy_dir, "main.rego"), "w") as f:
                f.write("package main\n")
            ok, msg = run_opa_test(checkout, "policy")
            self.assertTrue(ok)
            self.assertIn("no test", msg.lower())
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    @patch("subprocess.run")
    def test_test_success(self, mock_run: MagicMock) -> None:
        from story_automator.core.checks.opa_check import run_opa_test

        mock_run.return_value = MagicMock(returncode=0, stdout="PASS: 5/5", stderr="")
        checkout = tempfile.mkdtemp()
        try:
            policy_dir = os.path.join(checkout, "policy")
            os.makedirs(policy_dir)
            with open(os.path.join(policy_dir, "main_test.rego"), "w") as f:
                f.write("package main\ntest_allow { allow }\n")
            ok, msg = run_opa_test(checkout, "policy")
            self.assertTrue(ok)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_opa.py -v`
Expected: `ModuleNotFoundError` — `opa_check` module does not exist yet.

- [ ] **Step 3: Implement OPA check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/opa_check.py
"""Run OPA constitution compile and test.

Standalone script invoked by the opa-agentic collector.
Runs `opa compile` (must exit 0) and `opa test` (when test rules exist).
Exit 0 = both pass, exit 1 = failures, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import subprocess
import sys

_OPA_TIMEOUT = 120


def _has_rego_files(policy_path: str) -> bool:
    """Check if any .rego files exist in the policy directory."""
    if not os.path.isdir(policy_path):
        return False
    for root, _dirs, files in os.walk(policy_path):
        for f in files:
            if f.endswith(".rego"):
                return True
    return False


def _has_test_files(policy_path: str) -> bool:
    """Check if any *_test.rego files exist."""
    if not os.path.isdir(policy_path):
        return False
    for root, _dirs, files in os.walk(policy_path):
        for f in files:
            if f.endswith("_test.rego"):
                return True
    return False


def run_opa_compile(
    checkout: str, policy_dir: str,
) -> tuple[bool, str]:
    """Run opa compile on the policy directory."""
    policy_path = os.path.join(checkout, policy_dir)
    if not _has_rego_files(policy_path):
        return True, "no policy directory or rego files found — N/A"
    try:
        result = subprocess.run(
            ["opa", "compile", policy_path],
            capture_output=True, text=True,
            timeout=_OPA_TIMEOUT, cwd=checkout,
        )
    except FileNotFoundError:
        return False, "opa not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "opa compile timed out"
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()[:200]
        return False, f"opa compile failed: {msg}"
    return True, "opa compile passed"


def run_opa_test(
    checkout: str, policy_dir: str,
) -> tuple[bool, str]:
    """Run opa test on the policy directory (if test rules exist)."""
    policy_path = os.path.join(checkout, policy_dir)
    if not _has_test_files(policy_path):
        return True, "no test rules found — skipping opa test"
    try:
        result = subprocess.run(
            ["opa", "test", policy_path, "-v"],
            capture_output=True, text=True,
            timeout=_OPA_TIMEOUT, cwd=checkout,
        )
    except FileNotFoundError:
        return False, "opa not found in PATH"
    except subprocess.TimeoutExpired:
        return False, "opa test timed out"
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip()[:200]
        return False, f"opa test failed: {msg}"
    return True, f"opa test passed: {(result.stdout or '').strip()[:100]}"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: opa_check.py <checkout> [policy_dir]")
        return 2
    checkout = args[0]
    policy_dir = args[1] if len(args) > 1 else "policy"
    compile_ok, compile_msg = run_opa_compile(checkout, policy_dir)
    print(compile_msg)
    if not compile_ok:
        return 1
    test_ok, test_msg = run_opa_test(checkout, policy_dir)
    print(test_msg)
    if not test_ok:
        return 1
    print("OPA constitution checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_opa.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_opa.py skills/bmad-story-automator/src/story_automator/core/checks/opa_check.py
git commit -m "feat(collector): add OPA constitution check script for agentic" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: agentic collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/agentic.py`
- Create: `tests/test_collectors_agentic.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; 3 check scripts from `core/checks/`; `presence_check.py` for guardrail
- Produces: `PACK_SCHEMA: CollectorConfig`, `AIBOM_DIFF: CollectorConfig`, `OPA: CollectorConfig`, `EVALS: CollectorConfig`, `GUARDRAIL: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (5 items)

- [ ] **Step 1: Write failing tests for agentic collectors**

```python
# tests/test_collectors_agentic.py
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class PackSchemaCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import PACK_SCHEMA

        self.assertEqual(PACK_SCHEMA.collector_id, "pack-schema-agentic")
        self.assertEqual(PACK_SCHEMA.tool, "python3")
        self.assertEqual(PACK_SCHEMA.category, "agentic")
        self.assertTrue(PACK_SCHEMA.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import PACK_SCHEMA

        cmd = PACK_SCHEMA.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("pack_schema_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_tools_dir(self) -> None:
        from story_automator.core.collectors.agentic import PACK_SCHEMA

        profile = {"rules": {"agentic": {"tools_dir": "agent_tools"}}}
        cmd = PACK_SCHEMA.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "agent_tools")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.agentic import PACK_SCHEMA

        cmd = PACK_SCHEMA.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class AibomDiffCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import AIBOM_DIFF

        self.assertEqual(AIBOM_DIFF.collector_id, "aibom-diff-agentic")
        self.assertEqual(AIBOM_DIFF.tool, "python3")
        self.assertEqual(AIBOM_DIFF.category, "agentic")
        self.assertTrue(AIBOM_DIFF.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import AIBOM_DIFF

        cmd = AIBOM_DIFF.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("aibom_check.py", cmd[1])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.agentic import AIBOM_DIFF

        cmd = AIBOM_DIFF.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class OpaCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import OPA

        self.assertEqual(OPA.collector_id, "opa-agentic")
        self.assertEqual(OPA.tool, "python3")
        self.assertEqual(OPA.category, "agentic")
        self.assertTrue(OPA.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import OPA

        cmd = OPA.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("opa_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_policy_dir(self) -> None:
        from story_automator.core.collectors.agentic import OPA

        profile = {"rules": {"agentic": {"policy_dir": "opa_policies"}}}
        cmd = OPA.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "opa_policies")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.agentic import OPA

        cmd = OPA.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class EvalsCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import EVALS

        self.assertEqual(EVALS.collector_id, "evals-agentic")
        self.assertEqual(EVALS.tool, "deepeval")
        self.assertEqual(EVALS.category, "agentic")
        self.assertFalse(EVALS.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import EVALS

        cmd = EVALS.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "deepeval")
        self.assertIn("test", cmd)
        self.assertIn("run", cmd)

    def test_build_cmd_custom_tool(self) -> None:
        from story_automator.core.collectors.agentic import EVALS

        profile = {
            "rules": {"agentic": {
                "eval_tool": "promptfoo",
                "eval_cmd": ["npx", "promptfoo", "eval"],
            }},
        }
        cmd = EVALS.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd, ["npx", "promptfoo", "eval"])


class GuardrailCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.agentic import GUARDRAIL

        self.assertEqual(GUARDRAIL.collector_id, "guardrail-agentic")
        self.assertEqual(GUARDRAIL.tool, "python3")
        self.assertEqual(GUARDRAIL.category, "agentic")
        self.assertTrue(GUARDRAIL.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.agentic import GUARDRAIL

        cmd = GUARDRAIL.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("presence_check.py", cmd[1])
        files = json.loads(cmd[3])
        self.assertIn("guardrails.yaml", files)

    def test_build_cmd_custom_files(self) -> None:
        from story_automator.core.collectors.agentic import GUARDRAIL

        profile = {
            "rules": {"agentic": {
                "guardrail_files": ["config/guardrails.json", "config/safety.yaml"],
            }},
        }
        cmd = GUARDRAIL.build_cmd("/tmp/checkout", profile)
        files = json.loads(cmd[3])
        self.assertEqual(files, ["config/guardrails.json", "config/safety.yaml"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.agentic import GUARDRAIL

        cmd = GUARDRAIL.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class AgenticCollectorListTests(unittest.TestCase):
    def test_five_collectors(self) -> None:
        from story_automator.core.collectors.agentic import COLLECTORS

        self.assertEqual(len(COLLECTORS), 5)

    def test_all_agentic_category(self) -> None:
        from story_automator.core.collectors.agentic import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "agentic")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.agentic import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "pack-schema-agentic",
            "aibom-diff-agentic",
            "opa-agentic",
            "evals-agentic",
            "guardrail-agentic",
        })

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.agentic import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_agentic.py -v`
Expected: `ModuleNotFoundError` — `agentic` module does not exist yet.

- [ ] **Step 3: Implement agentic collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/agentic.py
"""Agentic-category evidence collectors (§6.2).

PASS rule (if touched): (a) pack-schema v1.2 valid, (b) AIBOM entries present,
(c) OPA constitution compiles + tests pass, (d) evals >= threshold,
(e) guardrail configuration present.
Collectors: pack-schema, aibom-diff, opa, evals, guardrail.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_GUARDRAIL_FILES = ["guardrails.yaml", "guardrails.json"]


def _pack_schema_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    cmd = [
        sys.executable,
        str(_CHECKS_DIR / "pack_schema_check.py"),
        checkout,
    ]
    tools_dir = rules.get("tools_dir")
    if tools_dir:
        cmd.append(tools_dir)
    return cmd


def _aibom_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    cmd = [
        sys.executable,
        str(_CHECKS_DIR / "aibom_check.py"),
        checkout,
    ]
    aibom_path = rules.get("aibom_path")
    if aibom_path:
        cmd.append(aibom_path)
    return cmd


def _opa_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    policy_dir = rules.get("policy_dir", "policy")
    return [
        sys.executable,
        str(_CHECKS_DIR / "opa_check.py"),
        checkout,
        policy_dir,
    ]


def _evals_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    custom_cmd = rules.get("eval_cmd")
    if custom_cmd and isinstance(custom_cmd, list):
        return custom_cmd
    return ["deepeval", "test", "run"]


def _guardrail_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("agentic") or {}
    files = rules.get("guardrail_files", _DEFAULT_GUARDRAIL_FILES)
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(files),
    ]


PACK_SCHEMA = CollectorConfig(
    collector_id="pack-schema-agentic",
    tool="python3",
    category="agentic",
    build_cmd=_pack_schema_cmd,
    file_patterns=frozenset({"*.json", "*.yaml", "*.yml"}),
)

AIBOM_DIFF = CollectorConfig(
    collector_id="aibom-diff-agentic",
    tool="python3",
    category="agentic",
    build_cmd=_aibom_cmd,
    file_patterns=frozenset({"*.json", "*.yaml", "*.yml"}),
)

OPA = CollectorConfig(
    collector_id="opa-agentic",
    tool="python3",
    category="agentic",
    build_cmd=_opa_cmd,
    file_patterns=frozenset({"*.rego"}),
)

EVALS = CollectorConfig(
    collector_id="evals-agentic",
    tool="deepeval",
    category="agentic",
    build_cmd=_evals_cmd,
    tool_version_cmd=("deepeval", "--version"),
    file_patterns=frozenset({"*.py", "*.ts", "*.yaml"}),
    deterministic=False,
)

GUARDRAIL = CollectorConfig(
    collector_id="guardrail-agentic",
    tool="python3",
    category="agentic",
    build_cmd=_guardrail_cmd,
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json"}),
)

COLLECTORS: list[CollectorConfig] = [
    PACK_SCHEMA, AIBOM_DIFF, OPA, EVALS, GUARDRAIL,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_agentic.py -v`
Expected: All 22 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_agentic.py skills/bmad-story-automator/src/story_automator/core/collectors/agentic.py
git commit -m "feat(collector): add agentic collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 13: Register new collectors in __init__.py

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`

**Interfaces:**
- Consumes: `COLLECTORS` from `test_quality.py`, `mutation.py`, `agentic.py`
- Produces: Updated `register_core_collectors()`, `CORE_COLLECTOR_IDS`, `_ALL` with all 49 collectors

- [ ] **Step 1: Modify __init__.py to import and register new categories**

Update `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`:

Add imports after existing imports:
```python
from .agentic import COLLECTORS as _AGENTIC
from .mutation import COLLECTORS as _MUTATION
from .test_quality import COLLECTORS as _TEST_QUALITY
```

Update `_ALL` aggregation:
```python
_ALL = (
    _ACCESSIBILITY + _AGENTIC + _API_COMPAT + _COMPLIANCE + _CORRECTNESS
    + _DOCS + _INVARIANTS + _LICENSE + _MIGRATIONS + _MUTATION
    + _OBSERVABILITY + _PERFORMANCE + _PROCESS + _SECURITY + _STATIC
    + _SUPPLY_CHAIN + _TEST_QUALITY + _TRACEABILITY
)
```

Update module docstring to include new categories.

- [ ] **Step 2: Verify import works**

Run: `python -c "from story_automator.core.collectors import register_core_collectors; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py
git commit -m "feat(collector): register test_quality, mutation, agentic collectors" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 14: Update diff_scope file-category map

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/diff_scope.py`

**Interfaces:**
- Modifies: `DEFAULT_FILE_CATEGORY_MAP` to include `test_quality`, `mutation`, and `agentic` categories

- [ ] **Step 1: Add new category mappings to DEFAULT_FILE_CATEGORY_MAP**

Add `test_quality` and `mutation` to existing Python/TS patterns since tests and mutations apply to source files. Add `agentic` mappings for JSON/YAML/rego files.

Update the map entries:
- `"*.py"` → add `"test_quality"`, `"mutation"`
- `"*.ts"` → add `"test_quality"`, `"mutation"`
- `"*.tsx"` → add `"test_quality"`, `"mutation"`
- `"*.js"` → add `"test_quality"`, `"mutation"`
- `"*.jsx"` → add `"test_quality"`, `"mutation"`
- Add `"*.rego": frozenset({"agentic"})` — OPA policy files
- Add `"*.tool.json": frozenset({"agentic"})` — tool definitions
- `"*.yaml"` → add `"agentic"` (already has invariants, compliance)
- `"*.yml"` → add `"agentic"` (already has invariants, compliance)

- [ ] **Step 2: Verify diff_scope still works**

Run: `python -m pytest tests/test_diff_scope.py -v`
Expected: All existing tests PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/diff_scope.py
git commit -m "feat(collector): update diff_scope map for test_quality, mutation, agentic" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 15: Update registry test expectations

**Files:**
- Modify: `tests/test_core_collectors.py`

**Interfaces:**
- Updates `_EXPECTED_IDS` to include all 49 collector IDs
- Updates `_EXPECTED_CATEGORIES` to include all 18 categories
- Updates count assertion from 39 to 49

- [ ] **Step 1: Update expected IDs and categories**

Add to `_EXPECTED_IDS`:
```python
# test_quality (3)
"test-review-test_quality",
"burn-in-test_quality",
"hard-wait-test_quality",
# mutation (2)
"mutmut-mutation",
"stryker-mutation",
# agentic (5)
"pack-schema-agentic",
"aibom-diff-agentic",
"opa-agentic",
"evals-agentic",
"guardrail-agentic",
```

Add to `_EXPECTED_CATEGORIES`:
```python
"test_quality",
"mutation",
"agentic",
```

Update `test_collector_count`: `self.assertEqual(len(reg.all_collectors()), 49)`

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_core_collectors.py -v`
Expected: All tests PASS with updated expectations.

- [ ] **Step 3: Commit**

```bash
git add tests/test_core_collectors.py
git commit -m "test(collector): update registry expectations for 49 collectors, 18 categories" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 16: Integration pipeline tests for advanced categories

**Files:**
- Modify: `tests/test_collector_integration.py`

**Interfaces:**
- Adds `AdvancedCategoryPipelineTests` class with tests for test_quality, mutation, agentic categories through the full pipeline

- [ ] **Step 1: Add advanced category integration tests**

Add new test class at end of `tests/test_collector_integration.py`:

```python
class AdvancedCategoryPipelineTests(unittest.TestCase):
    """Pipeline tests with test_quality, mutation, agentic categories."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-adv-integration-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.base_sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _advanced_profile(self) -> dict[str, Any]:
        return {
            "categories": {
                "code": ["test_quality", "mutation", "agentic"],
                "system": [],
            },
            "categories_na": [],
            "rules": {
                "test_quality": {"min_score": 70, "burn_in_runs": 5, "max_flaky": 0},
                "mutation": {"threshold": 80},
                "agentic": {},
            },
            "timeouts": {"test_quality": 900},
        }

    def _advanced_registry(self) -> CollectorRegistry:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="test-review-test_quality",
            tool="python3", category="test_quality", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="burn-in-test_quality",
            tool="python3", category="test_quality", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="hard-wait-test_quality",
            tool="python3", category="test_quality", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="mutmut-mutation",
            tool="python3", category="mutation", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="stryker-mutation",
            tool="python3", category="mutation", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="pack-schema-agentic",
            tool="python3", category="agentic", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="opa-agentic",
            tool="python3", category="agentic", build_cmd=_ok_cmd,
        ))
        return reg

    def test_all_advanced_categories_pass(self) -> None:
        profile = self._advanced_profile()
        reg = self._advanced_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-adv-pass", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 7)
        for outcome in outcomes:
            self.assertEqual(outcome.evidence["status"], "ok")
        records = load_evidence_bundle(self.project_root, "gate-adv-pass")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(aggregate_verdicts(verdicts), "PASS")

    def test_mutation_fail_propagates(self) -> None:
        profile = self._advanced_profile()
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="mutmut-mutation",
            tool="python3", category="mutation", build_cmd=_fail_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="test-review-test_quality",
            tool="python3", category="test_quality", build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-adv-fail", self.base_sha,
                profile, reg,
            )
        records = load_evidence_bundle(self.project_root, "gate-adv-fail")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(verdicts["mutation"], "FAIL")
        self.assertEqual(verdicts["test_quality"], "PASS")
        self.assertEqual(aggregate_verdicts(verdicts), "FAIL")

    def test_kill_switch_advanced_tool(self) -> None:
        profile = self._advanced_profile()
        profile["rules"]["mutation"]["disabled_tools"] = ["python3"]
        reg = self._advanced_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-adv-kill", self.base_sha,
                profile, reg,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertNotIn("mutation", run_cats)
        self.assertIn("test_quality", run_cats)

    def test_categories_na_excludes_agentic(self) -> None:
        profile = self._advanced_profile()
        profile["categories_na"] = ["agentic"]
        reg = self._advanced_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-adv-na", self.base_sha,
                profile, reg,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertNotIn("agentic", run_cats)
        self.assertIn("test_quality", run_cats)
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_collector_integration.py::AdvancedCategoryPipelineTests -v`
Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_collector_integration.py
git commit -m "test(collector): add integration pipeline tests for advanced categories" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 17: Update default profile rules

**Files:**
- Modify: `skills/bmad-story-automator/data/profiles/default.json`

**Interfaces:**
- Adds default rules for `mutation` and `agentic` categories (test_quality rules already exist)

- [ ] **Step 1: Add default rules for new categories**

Add to `rules` in `default.json`:
```json
"mutation": {"threshold": 80},
"agentic": {}
```

Note: Categories are NOT added to `categories.code` in the default profile — the default profile is intentionally minimal. Product-specific profiles (like msme-erp) activate these categories.

- [ ] **Step 2: Verify profile still loads**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: All existing tests PASS.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/data/profiles/default.json
git commit -m "feat(collector): add default rules for mutation and agentic categories" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 18: Update CLAUDE.md module map

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Updates module map with new M8 modules

- [ ] **Step 1: Update CLAUDE.md**

Add under the "Collectors (m5–m7)" bullet in the Gate subsystem section:
```
- **Collectors (m8)** `core/collectors/{test_quality,mutation,agentic}.py`, `core/invariant_registry.py`. Check scripts in `core/checks/{test_review_check,burn_in_check,hard_wait_check,mutation_check,pack_schema_check,aibom_check,opa_check}.py`. Invariant registry YAML loader (§6.4).
```

- [ ] **Step 2: Verify no trailing whitespace**

Run: `grep -n ' $' CLAUDE.md | head -5`
Expected: No output (no trailing whitespace).

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS including new M8 tests.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): update module map for m8 advanced collectors" --trailer "Generated-By: claude-opus-4-6"
```
