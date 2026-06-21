# Integration Collectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 12 evidence collectors across 6 new categories (traceability, api_compat, migrations, performance, accessibility, observability) to the collector framework, completing spec §6.2 integration quality categories.

**Architecture:** Each category becomes a new Python module under `core/collectors/` following the exact pattern established by M5/M6 (frozen `CollectorConfig` dataclasses with `build_cmd` callables). Five new check scripts under `core/checks/` handle multi-step validations that need profile-rule interpretation. One collector (slo-observability) reuses the existing `presence_check.py`. All collectors register via `register_core_collectors()`. M5+M6 have 27 collectors across 9 categories; M7 brings the total to 39 collectors across 15 categories.

**Tech Stack:** Python 3.11+ stdlib only (no new deps), `CollectorConfig` from M4 framework, `presence_check.py` reuse for SLO presence, profile `rules` dict for per-category configuration.

## Global Constraints

- No Python imports beyond stdlib + `filelock` + `psutil` (CLAUDE.md hard rule)
- 500 LOC soft limit per module
- Check scripts are standalone (no `story_automator` imports, stdlib only)
- Collectors use the same `CollectorConfig` frozen dataclass from `collector_config.py`
- All collectors are `deterministic=True` (subprocess tools produce repeatable output)
- Profile rules are opaque dicts consumed by `build_cmd`/check scripts, not validated at the profile level
- Conventional Commits, `Generated-By:` trailer on every commit
- Test runner: `python -m pytest tests/ -v`
- Lint: `ruff check .`

## File Structure

**New files (6 collector modules):**
- `skills/bmad-story-automator/src/story_automator/core/collectors/traceability.py` — 1 collector: trace-traceability (check script)
- `skills/bmad-story-automator/src/story_automator/core/collectors/api_compat.py` — 2 collectors: openapi-diff, schema-diff (external tools)
- `skills/bmad-story-automator/src/story_automator/core/collectors/migrations.py` — 2 collectors: alembic, migration-lint (external tool + check script)
- `skills/bmad-story-automator/src/story_automator/core/collectors/performance.py` — 3 collectors: lighthouse, bundlesize, perf-lint (external tools + check script)
- `skills/bmad-story-automator/src/story_automator/core/collectors/accessibility.py` — 1 collector: axe (external tool)
- `skills/bmad-story-automator/src/story_automator/core/collectors/observability.py` — 3 collectors: otel-wiring, health-probe, slo (check scripts + presence check)

**New files (5 check scripts):**
- `skills/bmad-story-automator/src/story_automator/core/checks/traceability_check.py` — TEA trace JSON reader + GWT title-parse fallback + threshold validation
- `skills/bmad-story-automator/src/story_automator/core/checks/migration_check.py` — Alembic reversibility + advisory-lock pattern checks
- `skills/bmad-story-automator/src/story_automator/core/checks/perf_lint_check.py` — static N+1 / unbounded query pattern detection
- `skills/bmad-story-automator/src/story_automator/core/checks/otel_check.py` — OTel instrumentation presence verification
- `skills/bmad-story-automator/src/story_automator/core/checks/health_check.py` — /healthz + /readyz endpoint pattern detection

**New files (11 test files):**
- `tests/test_check_traceability.py`
- `tests/test_collectors_traceability.py`
- `tests/test_collectors_api_compat.py`
- `tests/test_check_migration.py`
- `tests/test_collectors_migrations.py`
- `tests/test_check_perf_lint.py`
- `tests/test_collectors_performance.py`
- `tests/test_collectors_accessibility.py`
- `tests/test_check_otel.py`
- `tests/test_check_health.py`
- `tests/test_collectors_observability.py`

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py` — import + register 6 new categories
- `tests/test_core_collectors.py` — update expected IDs (39), expected categories (15)
- `tests/test_collector_integration.py` — add integration category pipeline tests

---

### Task 1: Traceability check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/traceability_check.py`
- Create: `tests/test_check_traceability.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `traceability_check.py <checkout> <thresholds_json> [tea_trace_path]`. Exit 0 = coverage met, 1 = violations, 2 = usage error. Also exports `read_tea_trace(path) -> list[dict]`, `gwt_fallback(checkout) -> list[dict]`, `compute_coverage(traces, thresholds) -> tuple[bool, list[str]]` for unit testing.

- [ ] **Step 1: Write failing tests for traceability check script**

```python
# tests/test_check_traceability.py
from __future__ import annotations

import json
import os
import tempfile
import unittest


class TraceabilityCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.traceability_check import main

        self.assertEqual(main([]), 2)

    def test_one_arg_returns_2(self) -> None:
        from story_automator.core.checks.traceability_check import main

        self.assertEqual(main(["/tmp"]), 2)

    def test_invalid_thresholds_json_returns_2(self) -> None:
        from story_automator.core.checks.traceability_check import main

        self.assertEqual(main(["/tmp", "not-json"]), 2)


class ReadTeaTraceTests(unittest.TestCase):
    def test_reads_valid_trace(self) -> None:
        from story_automator.core.checks.traceability_check import read_tea_trace

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "traces": [
                    {"ac_id": "AC-1", "priority": "P0", "test_file": "test_a.py", "status": "mapped"},
                    {"ac_id": "AC-2", "priority": "P1", "test_file": "test_b.py", "status": "mapped"},
                    {"ac_id": "AC-3", "priority": "P1", "test_file": "", "status": "unmapped"},
                ],
            }, f)
            path = f.name
        try:
            traces = read_tea_trace(path)
            self.assertEqual(len(traces), 3)
            self.assertEqual(traces[0]["ac_id"], "AC-1")
        finally:
            os.unlink(path)

    def test_missing_file_returns_empty(self) -> None:
        from story_automator.core.checks.traceability_check import read_tea_trace

        traces = read_tea_trace("/nonexistent/path.json")
        self.assertEqual(traces, [])

    def test_invalid_json_returns_empty(self) -> None:
        from story_automator.core.checks.traceability_check import read_tea_trace

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            traces = read_tea_trace(path)
            self.assertEqual(traces, [])
        finally:
            os.unlink(path)


class GwtFallbackTests(unittest.TestCase):
    def test_maps_matching_acs_only(self) -> None:
        from story_automator.core.checks.traceability_check import gwt_fallback

        checkout = tempfile.mkdtemp()
        try:
            story_dir = os.path.join(checkout, "_bmad", "stories")
            os.makedirs(story_dir)
            with open(os.path.join(story_dir, "story-1.md"), "w") as f:
                f.write(
                    "# Story 1\n"
                    "## Acceptance Criteria\n"
                    "- AC-1 [P0]: User login authentication\n"
                    "- AC-2 [P1]: Admin dashboard display\n"
                )
            test_dir = os.path.join(checkout, "tests")
            os.makedirs(test_dir)
            with open(os.path.join(test_dir, "test_login.py"), "w") as f:
                f.write("def test_given_user_when_login_then_authenticated(): pass\n")
            traces = gwt_fallback(checkout)
            self.assertEqual(len(traces), 2)
            by_id = {t["ac_id"]: t for t in traces}
            self.assertEqual(by_id["AC-1"]["status"], "mapped")
            self.assertEqual(by_id["AC-2"]["status"], "unmapped")
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_story_dir_returns_empty(self) -> None:
        from story_automator.core.checks.traceability_check import gwt_fallback

        checkout = tempfile.mkdtemp()
        try:
            traces = gwt_fallback(checkout)
            self.assertEqual(traces, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)


class ComputeCoverageTests(unittest.TestCase):
    def test_full_coverage_passes(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        traces = [
            {"ac_id": "AC-1", "priority": "P0", "status": "mapped"},
            {"ac_id": "AC-2", "priority": "P1", "status": "mapped"},
        ]
        ok, issues = compute_coverage(traces, {"P0": 100, "P1": 90})
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_p0_below_threshold_fails(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        traces = [
            {"ac_id": "AC-1", "priority": "P0", "status": "mapped"},
            {"ac_id": "AC-2", "priority": "P0", "status": "unmapped"},
        ]
        ok, issues = compute_coverage(traces, {"P0": 100, "P1": 90})
        self.assertFalse(ok)
        self.assertTrue(any("P0" in i for i in issues))

    def test_p1_below_threshold_fails(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        traces = [
            {"ac_id": f"AC-{i}", "priority": "P1", "status": "unmapped"}
            for i in range(10)
        ]
        ok, issues = compute_coverage(traces, {"P0": 100, "P1": 90})
        self.assertFalse(ok)
        self.assertTrue(any("P1" in i for i in issues))

    def test_empty_traces_passes(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        ok, issues = compute_coverage([], {"P0": 100, "P1": 90})
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_unknown_priority_ignored(self) -> None:
        from story_automator.core.checks.traceability_check import compute_coverage

        traces = [
            {"ac_id": "AC-1", "priority": "P99", "status": "unmapped"},
        ]
        ok, issues = compute_coverage(traces, {"P0": 100, "P1": 90})
        self.assertTrue(ok)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_traceability.py -v`
Expected: `ModuleNotFoundError` — `traceability_check` module does not exist yet.

- [ ] **Step 3: Implement traceability check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/traceability_check.py
"""Check AC-to-test traceability coverage against thresholds.

Standalone script invoked by the trace-traceability collector.
Reads TEA e2e-trace-summary.json when present, falls back to
GWT title parse over story files. Validates per-priority coverage.
Exit 0 = thresholds met, exit 1 = violations, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_AC_RE = re.compile(
    r"^-\s+(\S+)\s+\[(\w+)\]:\s*(.*)", re.MULTILINE,
)
_GWT_RE = re.compile(
    r"def\s+test_given_\w+_when_\w+_then_\w+", re.MULTILINE,
)
_STORY_RELDIR = os.path.join("_bmad", "stories")
_TEA_DEFAULT = os.path.join("_bmad", "gate", "tea", "e2e-trace-summary.json")


def read_tea_trace(path: str) -> list[dict]:
    """Read TEA e2e-trace-summary.json. Returns [] on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    traces = data.get("traces")
    if not isinstance(traces, list):
        return []
    return [t for t in traces if isinstance(t, dict) and "ac_id" in t]


def gwt_fallback(checkout: str) -> list[dict]:
    """Parse stories for ACs, scan tests for GWT patterns, compute mapping."""
    story_dir = os.path.join(checkout, _STORY_RELDIR)
    if not os.path.isdir(story_dir):
        return []
    acs: list[dict] = []
    for fname in sorted(os.listdir(story_dir)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(story_dir, fname)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        for match in _AC_RE.finditer(content):
            acs.append({
                "ac_id": match.group(1),
                "priority": match.group(2),
                "description": match.group(3).strip(),
                "status": "unmapped",
                "source": fname,
            })
    if not acs:
        return []
    test_tokens: list[set[str]] = []
    tests_dir = os.path.join(checkout, "tests")
    if os.path.isdir(tests_dir):
        for root, _dirs, files in os.walk(tests_dir):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(root, fname)
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                for match in _GWT_RE.finditer(content):
                    tokens = set(match.group(0).lower().replace("_", " ").split())
                    test_tokens.append(tokens)
    for ac in acs:
        ac_words = set(ac.get("description", "").lower().split())
        for tokens in test_tokens:
            if len(ac_words & tokens) >= 2:
                ac["status"] = "mapped"
                break
    return acs


def compute_coverage(
    traces: list[dict],
    thresholds: dict[str, int],
) -> tuple[bool, list[str]]:
    """Compute per-priority coverage. Returns (ok, issues)."""
    if not traces:
        return True, []
    by_priority: dict[str, list[dict]] = {}
    for t in traces:
        pri = t.get("priority", "")
        by_priority.setdefault(pri, []).append(t)
    issues: list[str] = []
    for pri, threshold in thresholds.items():
        group = by_priority.get(pri, [])
        if not group:
            continue
        mapped = sum(1 for t in group if t.get("status") == "mapped")
        total = len(group)
        pct = (mapped * 100) // total if total > 0 else 100
        if pct < threshold:
            issues.append(
                f"{pri}: {mapped}/{total} ({pct}%) mapped, "
                f"required {threshold}%"
            )
    return len(issues) == 0, issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: traceability_check.py <checkout> <thresholds_json> [tea_trace_path]")
        return 2
    checkout = args[0]
    try:
        thresholds: dict[str, int] = json.loads(args[1])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid thresholds: {args[1]}")
        return 2
    tea_path = args[2] if len(args) > 2 else os.path.join(checkout, _TEA_DEFAULT)
    traces = read_tea_trace(tea_path)
    if not traces:
        print("TEA trace not found, using GWT fallback")
        traces = gwt_fallback(checkout)
    if not traces:
        print("no ACs found — traceability N/A")
        return 0
    ok, issues = compute_coverage(traces, thresholds)
    for issue in issues:
        print(issue)
    if not ok:
        print(f"{len(issues)} traceability threshold(s) not met")
        return 1
    mapped = sum(1 for t in traces if t.get("status") == "mapped")
    print(f"{mapped}/{len(traces)} ACs mapped — all thresholds met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_traceability.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_traceability.py skills/bmad-story-automator/src/story_automator/core/checks/traceability_check.py
git commit -m "feat(collector): add traceability check script with TEA + GWT fallback" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: Traceability collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/traceability.py`
- Create: `tests/test_collectors_traceability.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; `traceability_check.py` from `core/checks/`
- Produces: `TRACE: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (1 item)

- [ ] **Step 1: Write failing tests for traceability collector**

```python
# tests/test_collectors_traceability.py
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class TraceCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        self.assertEqual(TRACE.collector_id, "trace-traceability")
        self.assertEqual(TRACE.tool, "python3")
        self.assertEqual(TRACE.category, "traceability")
        self.assertTrue(TRACE.deterministic)
        self.assertIn("*.md", TRACE.file_patterns)
        self.assertIn("*.json", TRACE.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        cmd = TRACE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("traceability_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        thresholds = json.loads(cmd[3])
        self.assertEqual(thresholds["P0"], 100)
        self.assertEqual(thresholds["P1"], 90)

    def test_build_cmd_custom_thresholds(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        profile = {
            "matrix": {
                "P0": {"coverage_pct": 100},
                "P1": {"coverage_pct": 80},
            },
        }
        cmd = TRACE.build_cmd("/tmp/checkout", profile)
        thresholds = json.loads(cmd[3])
        self.assertEqual(thresholds["P0"], 100)
        self.assertEqual(thresholds["P1"], 80)

    def test_build_cmd_custom_tea_path(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        profile = {
            "rules": {"traceability": {"tea_trace_path": "custom/trace.json"}},
        }
        cmd = TRACE.build_cmd("/tmp/checkout", profile)
        self.assertIn("custom/trace.json", cmd)

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.traceability import TRACE

        cmd = TRACE.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class TraceabilityCollectorListTests(unittest.TestCase):
    def test_one_collector(self) -> None:
        from story_automator.core.collectors.traceability import COLLECTORS

        self.assertEqual(len(COLLECTORS), 1)

    def test_all_traceability_category(self) -> None:
        from story_automator.core.collectors.traceability import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "traceability")

    def test_expected_id(self) -> None:
        from story_automator.core.collectors.traceability import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"trace-traceability"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.traceability import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_traceability.py -v`
Expected: `ModuleNotFoundError` — `traceability` module does not exist yet.

- [ ] **Step 3: Implement traceability collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/traceability.py
"""Traceability-category evidence collectors (§6.2).

PASS rule: P0 ACs 100% / P1 >= 90% mapped to tests.
Evidence: TEA e2e-trace-summary.json (fallback: GWT title parse).
Collectors: trace-traceability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_THRESHOLDS = {"P0": 100, "P1": 90}


def _trace_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    matrix = profile.get("matrix") or {}
    thresholds: dict[str, int] = {}
    for pri, defaults in _DEFAULT_THRESHOLDS.items():
        pri_cfg = matrix.get(pri) or {}
        thresholds[pri] = pri_cfg.get("coverage_pct", defaults)
    cmd = [
        sys.executable,
        str(_CHECKS_DIR / "traceability_check.py"),
        checkout,
        json.dumps(thresholds),
    ]
    rules = (profile.get("rules") or {}).get("traceability") or {}
    tea_path = rules.get("tea_trace_path")
    if tea_path:
        cmd.append(tea_path)
    return cmd


TRACE = CollectorConfig(
    collector_id="trace-traceability",
    tool="python3",
    category="traceability",
    build_cmd=_trace_cmd,
    file_patterns=frozenset({"*.md", "*.json", "*.py"}),
)

COLLECTORS: list[CollectorConfig] = [TRACE]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_traceability.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_traceability.py skills/bmad-story-automator/src/story_automator/core/collectors/traceability.py
git commit -m "feat(collector): add traceability collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: API compat collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/api_compat.py`
- Create: `tests/test_collectors_api_compat.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`
- Produces: `OPENAPI_DIFF: CollectorConfig`, `SCHEMA_DIFF: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (2 items)

- [ ] **Step 1: Write failing tests for api_compat collectors**

```python
# tests/test_collectors_api_compat.py
from __future__ import annotations

import unittest


class OpenapiDiffCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.api_compat import OPENAPI_DIFF

        self.assertEqual(OPENAPI_DIFF.collector_id, "openapi-diff-api_compat")
        self.assertEqual(OPENAPI_DIFF.tool, "oasdiff")
        self.assertEqual(OPENAPI_DIFF.category, "api_compat")
        self.assertTrue(OPENAPI_DIFF.deterministic)
        self.assertIn("*.yaml", OPENAPI_DIFF.file_patterns)
        self.assertIn("*.json", OPENAPI_DIFF.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.api_compat import OPENAPI_DIFF

        cmd = OPENAPI_DIFF.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "oasdiff")
        self.assertIn("breaking", cmd)

    def test_build_cmd_custom_base_spec(self) -> None:
        from story_automator.core.collectors.api_compat import OPENAPI_DIFF

        profile = {
            "rules": {"api_compat": {
                "openapi_base": "api/v1/openapi-base.yaml",
                "openapi_revision": "api/v1/openapi.yaml",
            }},
        }
        cmd = OPENAPI_DIFF.build_cmd("/tmp/checkout", profile)
        self.assertIn("api/v1/openapi-base.yaml", cmd)
        self.assertIn("api/v1/openapi.yaml", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.api_compat import OPENAPI_DIFF

        self.assertIsNotNone(OPENAPI_DIFF.tool_version_cmd)
        self.assertIn("oasdiff", OPENAPI_DIFF.tool_version_cmd)


class SchemaDiffCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.api_compat import SCHEMA_DIFF

        self.assertEqual(SCHEMA_DIFF.collector_id, "schema-diff-api_compat")
        self.assertEqual(SCHEMA_DIFF.tool, "oasdiff")
        self.assertEqual(SCHEMA_DIFF.category, "api_compat")
        self.assertTrue(SCHEMA_DIFF.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.api_compat import SCHEMA_DIFF

        cmd = SCHEMA_DIFF.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "oasdiff")
        self.assertIn("diff", cmd)

    def test_build_cmd_custom_specs(self) -> None:
        from story_automator.core.collectors.api_compat import SCHEMA_DIFF

        profile = {
            "rules": {"api_compat": {
                "schema_base": "schemas/base.yaml",
                "schema_revision": "schemas/current.yaml",
            }},
        }
        cmd = SCHEMA_DIFF.build_cmd("/tmp/checkout", profile)
        self.assertIn("schemas/base.yaml", cmd)
        self.assertIn("schemas/current.yaml", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.api_compat import SCHEMA_DIFF

        self.assertIsNotNone(SCHEMA_DIFF.tool_version_cmd)
        self.assertIn("oasdiff", SCHEMA_DIFF.tool_version_cmd)


class ApiCompatCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.api_compat import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_api_compat_category(self) -> None:
        from story_automator.core.collectors.api_compat import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "api_compat")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.api_compat import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"openapi-diff-api_compat", "schema-diff-api_compat"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.api_compat import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_api_compat.py -v`
Expected: `ModuleNotFoundError` — `api_compat` module does not exist yet.

- [ ] **Step 3: Implement api_compat collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/api_compat.py
"""API-compatibility-category evidence collectors (§6.2).

PASS rule: no breaking REST/schema change; audit-log additive-only.
Collectors: openapi-diff-api_compat, schema-diff-api_compat.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _openapi_diff_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("api_compat") or {}
    base = rules.get("openapi_base", "openapi-base.yaml")
    revision = rules.get("openapi_revision", "openapi.yaml")
    return ["oasdiff", "breaking", base, revision]


def _schema_diff_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("api_compat") or {}
    base = rules.get("schema_base", "openapi-base.yaml")
    revision = rules.get("schema_revision", "openapi.yaml")
    return ["oasdiff", "diff", base, revision, "--fail-on", "ERR"]


OPENAPI_DIFF = CollectorConfig(
    collector_id="openapi-diff-api_compat",
    tool="oasdiff",
    category="api_compat",
    build_cmd=_openapi_diff_cmd,
    tool_version_cmd=("oasdiff", "version"),
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json"}),
)

SCHEMA_DIFF = CollectorConfig(
    collector_id="schema-diff-api_compat",
    tool="oasdiff",
    category="api_compat",
    build_cmd=_schema_diff_cmd,
    tool_version_cmd=("oasdiff", "version"),
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json"}),
)

COLLECTORS: list[CollectorConfig] = [OPENAPI_DIFF, SCHEMA_DIFF]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_api_compat.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_api_compat.py skills/bmad-story-automator/src/story_automator/core/collectors/api_compat.py
git commit -m "feat(collector): add api_compat collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: Migration check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/migration_check.py`
- Create: `tests/test_check_migration.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `migration_check.py <checkout> [migrations_dir]`. Exit 0 = clean, 1 = issues, 2 = usage error. Also exports `check_reversibility(content, filename) -> list[str]`, `check_advisory_lock(content, filename) -> list[str]` for unit testing.

- [ ] **Step 1: Write failing tests for migration check script**

```python
# tests/test_check_migration.py
from __future__ import annotations

import os
import tempfile
import unittest


class MigrationCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.migration_check import main

        self.assertEqual(main([]), 2)


class CheckReversibilityTests(unittest.TestCase):
    def test_has_downgrade_passes(self) -> None:
        from story_automator.core.checks.migration_check import check_reversibility

        content = (
            "def upgrade():\n"
            "    op.create_table('users')\n"
            "\n"
            "def downgrade():\n"
            "    op.drop_table('users')\n"
        )
        issues = check_reversibility(content, "001_create_users.py")
        self.assertEqual(issues, [])

    def test_missing_downgrade_fails(self) -> None:
        from story_automator.core.checks.migration_check import check_reversibility

        content = (
            "def upgrade():\n"
            "    op.create_table('users')\n"
        )
        issues = check_reversibility(content, "001_create_users.py")
        self.assertEqual(len(issues), 1)
        self.assertIn("downgrade", issues[0].lower())

    def test_empty_downgrade_fails(self) -> None:
        from story_automator.core.checks.migration_check import check_reversibility

        content = (
            "def upgrade():\n"
            "    op.create_table('users')\n"
            "\n"
            "def downgrade():\n"
            "    pass\n"
        )
        issues = check_reversibility(content, "001_create_users.py")
        self.assertEqual(len(issues), 1)
        self.assertIn("empty", issues[0].lower())


class CheckAdvisoryLockTests(unittest.TestCase):
    def test_data_migration_with_lock_passes(self) -> None:
        from story_automator.core.checks.migration_check import check_advisory_lock

        content = (
            "def upgrade():\n"
            "    op.execute('SELECT pg_advisory_lock(1234)')\n"
            "    op.execute('UPDATE users SET active = true')\n"
            "    op.execute('SELECT pg_advisory_unlock(1234)')\n"
        )
        issues = check_advisory_lock(content, "002_data_migration.py")
        self.assertEqual(issues, [])

    def test_data_migration_without_lock_fails(self) -> None:
        from story_automator.core.checks.migration_check import check_advisory_lock

        content = (
            "def upgrade():\n"
            "    op.execute('UPDATE users SET active = true')\n"
        )
        issues = check_advisory_lock(content, "002_data_migration.py")
        self.assertEqual(len(issues), 1)
        self.assertIn("advisory", issues[0].lower())

    def test_schema_only_migration_passes(self) -> None:
        from story_automator.core.checks.migration_check import check_advisory_lock

        content = (
            "def upgrade():\n"
            "    op.add_column('users', sa.Column('name', sa.String))\n"
        )
        issues = check_advisory_lock(content, "003_add_column.py")
        self.assertEqual(issues, [])


class ScanMigrationsTests(unittest.TestCase):
    def test_no_dir_returns_empty(self) -> None:
        from story_automator.core.checks.migration_check import scan_migrations

        issues = scan_migrations("/nonexistent", "alembic/versions")
        self.assertEqual(issues, [])

    def test_scans_migration_files(self) -> None:
        from story_automator.core.checks.migration_check import scan_migrations

        checkout = tempfile.mkdtemp()
        try:
            mig_dir = os.path.join(checkout, "alembic", "versions")
            os.makedirs(mig_dir)
            with open(os.path.join(mig_dir, "001_init.py"), "w") as f:
                f.write("def upgrade():\n    op.create_table('x')\n")
            issues = scan_migrations(checkout, "alembic/versions")
            self.assertTrue(len(issues) >= 1)
            self.assertTrue(any("downgrade" in i.lower() for i in issues))
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_migration.py -v`
Expected: `ModuleNotFoundError` — `migration_check` module does not exist yet.

- [ ] **Step 3: Implement migration check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/migration_check.py
"""Check Alembic migrations for reversibility and advisory-lock usage.

Standalone script invoked by the migration-lint collector.
Scans migration files for missing downgrade functions and
data migrations without advisory locks.
Exit 0 = clean, exit 1 = issues, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import re
import sys

_DOWNGRADE_RE = re.compile(r"^def\s+downgrade\s*\(", re.MULTILINE)
_DOWNGRADE_PASS_RE = re.compile(
    r"def\s+downgrade\s*\([^)]*\)\s*:\s*\n\s+pass\s*$", re.MULTILINE,
)
_DATA_DML_RE = re.compile(
    r"op\.execute\s*\(\s*['\"](?:UPDATE|DELETE|INSERT)\b",
    re.IGNORECASE | re.MULTILINE,
)
_ADVISORY_LOCK_RE = re.compile(r"pg_advisory_lock", re.IGNORECASE)


def check_reversibility(content: str, filename: str) -> list[str]:
    """Check a migration has a non-empty downgrade function."""
    issues: list[str] = []
    if not _DOWNGRADE_RE.search(content):
        issues.append(f"MISSING downgrade: {filename}")
    elif _DOWNGRADE_PASS_RE.search(content):
        issues.append(f"EMPTY downgrade (pass only): {filename}")
    return issues


def check_advisory_lock(content: str, filename: str) -> list[str]:
    """Check data migrations use advisory locks."""
    issues: list[str] = []
    if _DATA_DML_RE.search(content) and not _ADVISORY_LOCK_RE.search(content):
        issues.append(
            f"DATA migration without advisory lock: {filename}"
        )
    return issues


def scan_migrations(checkout: str, migrations_dir: str) -> list[str]:
    """Scan all migration files and return issues."""
    mig_path = os.path.join(checkout, migrations_dir)
    if not os.path.isdir(mig_path):
        return []
    all_issues: list[str] = []
    for fname in sorted(os.listdir(mig_path)):
        if not fname.endswith(".py") or fname.startswith("__"):
            continue
        path = os.path.join(mig_path, fname)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        all_issues.extend(check_reversibility(content, fname))
        all_issues.extend(check_advisory_lock(content, fname))
    return all_issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: migration_check.py <checkout> [migrations_dir]")
        return 2
    checkout = args[0]
    migrations_dir = args[1] if len(args) > 1 else "alembic/versions"
    issues = scan_migrations(checkout, migrations_dir)
    for issue in issues:
        print(issue)
    if issues:
        print(f"{len(issues)} migration issue(s) found")
        return 1
    print("all migrations pass lint checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_migration.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_migration.py skills/bmad-story-automator/src/story_automator/core/checks/migration_check.py
git commit -m "feat(collector): add migration check script" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: Migrations collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/migrations.py`
- Create: `tests/test_collectors_migrations.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; `migration_check.py` from `core/checks/`
- Produces: `ALEMBIC: CollectorConfig`, `MIGRATION_LINT: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (2 items)

- [ ] **Step 1: Write failing tests for migrations collectors**

```python
# tests/test_collectors_migrations.py
from __future__ import annotations

import sys
import unittest
from pathlib import Path


class AlembicCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.migrations import ALEMBIC

        self.assertEqual(ALEMBIC.collector_id, "alembic-migrations")
        self.assertEqual(ALEMBIC.tool, "alembic")
        self.assertEqual(ALEMBIC.category, "migrations")
        self.assertTrue(ALEMBIC.deterministic)
        self.assertIn("*.py", ALEMBIC.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.migrations import ALEMBIC

        cmd = ALEMBIC.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "alembic")
        self.assertIn("upgrade", cmd)
        self.assertIn("head", cmd)
        self.assertIn("--sql", cmd)

    def test_build_cmd_custom_revision(self) -> None:
        from story_automator.core.collectors.migrations import ALEMBIC

        profile = {"rules": {"migrations": {"alembic_revision": "abc123"}}}
        cmd = ALEMBIC.build_cmd("/tmp/checkout", profile)
        self.assertIn("abc123", cmd)
        self.assertNotIn("head", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.migrations import ALEMBIC

        self.assertIsNotNone(ALEMBIC.tool_version_cmd)
        self.assertIn("alembic", ALEMBIC.tool_version_cmd)


class MigrationLintCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.migrations import MIGRATION_LINT

        self.assertEqual(MIGRATION_LINT.collector_id, "migration-lint-migrations")
        self.assertEqual(MIGRATION_LINT.tool, "python3")
        self.assertEqual(MIGRATION_LINT.category, "migrations")
        self.assertTrue(MIGRATION_LINT.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.migrations import MIGRATION_LINT

        cmd = MIGRATION_LINT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("migration_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        self.assertEqual(cmd[3], "alembic/versions")

    def test_build_cmd_custom_dir(self) -> None:
        from story_automator.core.collectors.migrations import MIGRATION_LINT

        profile = {"rules": {"migrations": {"migrations_dir": "db/migrations"}}}
        cmd = MIGRATION_LINT.build_cmd("/tmp/checkout", profile)
        self.assertEqual(cmd[3], "db/migrations")

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.migrations import MIGRATION_LINT

        cmd = MIGRATION_LINT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class MigrationsCollectorListTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.migrations import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_migrations_category(self) -> None:
        from story_automator.core.collectors.migrations import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "migrations")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.migrations import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"alembic-migrations", "migration-lint-migrations"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.migrations import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_migrations.py -v`
Expected: `ModuleNotFoundError` — `migrations` module does not exist yet.

- [ ] **Step 3: Implement migrations collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/migrations.py
"""Migrations-category evidence collectors (§6.2).

PASS rule: Alembic/Marabunta dry-run clean + reversible + advisory-lock correct.
Collectors: alembic-migrations, migration-lint-migrations.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _alembic_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("migrations") or {}
    revision = rules.get("alembic_revision", "head")
    return ["alembic", "upgrade", revision, "--sql"]


def _migration_lint_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("migrations") or {}
    migrations_dir = rules.get("migrations_dir", "alembic/versions")
    return [
        sys.executable,
        str(_CHECKS_DIR / "migration_check.py"),
        checkout,
        migrations_dir,
    ]


ALEMBIC = CollectorConfig(
    collector_id="alembic-migrations",
    tool="alembic",
    category="migrations",
    build_cmd=_alembic_cmd,
    tool_version_cmd=("alembic", "--version"),
    file_patterns=frozenset({"*.py", "*.sql"}),
)

MIGRATION_LINT = CollectorConfig(
    collector_id="migration-lint-migrations",
    tool="python3",
    category="migrations",
    build_cmd=_migration_lint_cmd,
    file_patterns=frozenset({"*.py"}),
)

COLLECTORS: list[CollectorConfig] = [ALEMBIC, MIGRATION_LINT]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_migrations.py -v`
Expected: All 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_migrations.py skills/bmad-story-automator/src/story_automator/core/collectors/migrations.py
git commit -m "feat(collector): add migrations collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: Performance lint check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/perf_lint_check.py`
- Create: `tests/test_check_perf_lint.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `perf_lint_check.py <checkout> [extensions_json]`. Exit 0 = clean, 1 = findings, 2 = usage error. Also exports `scan_for_n_plus_one(content, filename) -> list[str]`, `scan_for_unbounded(content, filename) -> list[str]` for unit testing.

- [ ] **Step 1: Write failing tests for perf lint check script**

```python
# tests/test_check_perf_lint.py
from __future__ import annotations

import os
import tempfile
import unittest


class PerfLintUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.perf_lint_check import main

        self.assertEqual(main([]), 2)


class ScanNPlusOneTests(unittest.TestCase):
    def test_lazy_load_in_loop_detected(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_n_plus_one

        content = (
            "for user in users:\n"
            "    orders = user.orders.all()\n"
        )
        findings = scan_for_n_plus_one(content, "app.py")
        self.assertEqual(len(findings), 1)
        self.assertIn("N+1", findings[0])

    def test_no_lazy_load_passes(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_n_plus_one

        content = (
            "users = db.query(User).options(joinedload(User.orders)).all()\n"
        )
        findings = scan_for_n_plus_one(content, "app.py")
        self.assertEqual(findings, [])

    def test_selectin_outside_loop_passes(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_n_plus_one

        content = "result = item.children.all()\n"
        findings = scan_for_n_plus_one(content, "app.py")
        self.assertEqual(findings, [])


class ScanUnboundedTests(unittest.TestCase):
    def test_select_without_limit_detected(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_unbounded

        content = 'db.execute("SELECT * FROM users")\n'
        findings = scan_for_unbounded(content, "query.py")
        self.assertEqual(len(findings), 1)
        self.assertIn("unbounded", findings[0].lower())

    def test_select_with_limit_passes(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_unbounded

        content = 'db.execute("SELECT * FROM users LIMIT 100")\n'
        findings = scan_for_unbounded(content, "query.py")
        self.assertEqual(findings, [])

    def test_find_all_without_limit_detected(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_unbounded

        content = "results = repo.find_all()\n"
        findings = scan_for_unbounded(content, "service.py")
        self.assertEqual(len(findings), 1)

    def test_count_query_passes(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_for_unbounded

        content = 'db.execute("SELECT COUNT(*) FROM users")\n'
        findings = scan_for_unbounded(content, "query.py")
        self.assertEqual(findings, [])


class ScanDirectoryTests(unittest.TestCase):
    def test_scans_python_files(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_directory

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "bad.py"), "w") as f:
                f.write(
                    "for u in users:\n"
                    "    orders = u.orders.all()\n"
                )
            findings = scan_directory(checkout, [".py"])
            self.assertTrue(len(findings) >= 1)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_no_files_returns_empty(self) -> None:
        from story_automator.core.checks.perf_lint_check import scan_directory

        checkout = tempfile.mkdtemp()
        try:
            findings = scan_directory(checkout, [".py"])
            self.assertEqual(findings, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_perf_lint.py -v`
Expected: `ModuleNotFoundError` — `perf_lint_check` module does not exist yet.

- [ ] **Step 3: Implement perf lint check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/perf_lint_check.py
"""Detect static N+1 and unbounded query patterns.

Standalone script invoked by the perf-lint-performance collector.
Scans source files for common performance anti-patterns.
Exit 0 = clean, exit 1 = findings, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_FOR_LOOP_RE = re.compile(r"^\s*for\s+\w+\s+in\s+", re.MULTILINE)
_LAZY_LOAD_RE = re.compile(r"\.\w+\.(all|filter|get)\s*\(")
_SELECT_STAR_RE = re.compile(
    r"""(?:execute|text)\s*\(\s*['"]SELECT\s+(?!\s*COUNT)\S+.*?FROM""",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)
_FIND_ALL_RE = re.compile(r"\.find_all\s*\(\s*\)")

_DEFAULT_EXTENSIONS = [".py", ".ts", ".tsx"]


def scan_for_n_plus_one(content: str, filename: str) -> list[str]:
    """Detect lazy-load attribute access inside for loops."""
    findings: list[str] = []
    lines = content.splitlines()
    in_for_loop = False
    for i, line in enumerate(lines, 1):
        if _FOR_LOOP_RE.match(line):
            in_for_loop = True
            continue
        if in_for_loop and line and not line[0].isspace():
            in_for_loop = False
        if in_for_loop and _LAZY_LOAD_RE.search(line):
            findings.append(f"N+1: {filename}:{i}: {line.strip()}")
    return findings


def scan_for_unbounded(content: str, filename: str) -> list[str]:
    """Detect SELECT without LIMIT and find_all() calls."""
    findings: list[str] = []
    lines = content.splitlines()
    for i, line in enumerate(lines, 1):
        if _SELECT_STAR_RE.search(line) and not _LIMIT_RE.search(line):
            findings.append(f"UNBOUNDED query: {filename}:{i}: {line.strip()}")
        if _FIND_ALL_RE.search(line):
            findings.append(f"UNBOUNDED find_all(): {filename}:{i}: {line.strip()}")
    return findings


def scan_directory(checkout: str, extensions: list[str]) -> list[str]:
    """Walk checkout and scan files matching extensions."""
    all_findings: list[str] = []
    for root, _dirs, files in os.walk(checkout):
        for fname in sorted(files):
            if not any(fname.endswith(ext) for ext in extensions):
                continue
            path = os.path.join(root, fname)
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
            rel = os.path.relpath(path, checkout)
            all_findings.extend(scan_for_n_plus_one(content, rel))
            all_findings.extend(scan_for_unbounded(content, rel))
    return all_findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: perf_lint_check.py <checkout> [extensions_json]")
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
    findings = scan_directory(checkout, extensions)
    for f in findings:
        print(f)
    if findings:
        print(f"{len(findings)} performance issue(s) found")
        return 1
    print("no performance issues found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_perf_lint.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_perf_lint.py skills/bmad-story-automator/src/story_automator/core/checks/perf_lint_check.py
git commit -m "feat(collector): add perf lint check script" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: Performance collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/performance.py`
- Create: `tests/test_collectors_performance.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; `perf_lint_check.py` from `core/checks/`
- Produces: `LIGHTHOUSE: CollectorConfig`, `BUNDLESIZE: CollectorConfig`, `PERF_LINT: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (3 items)

- [ ] **Step 1: Write failing tests for performance collectors**

```python
# tests/test_collectors_performance.py
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class LighthouseCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.performance import LIGHTHOUSE

        self.assertEqual(LIGHTHOUSE.collector_id, "lighthouse-performance")
        self.assertEqual(LIGHTHOUSE.tool, "lhci")
        self.assertEqual(LIGHTHOUSE.category, "performance")
        self.assertTrue(LIGHTHOUSE.deterministic)
        self.assertIn("*.ts", LIGHTHOUSE.file_patterns)
        self.assertIn("*.css", LIGHTHOUSE.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.performance import LIGHTHOUSE

        cmd = LIGHTHOUSE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "lhci")
        self.assertIn("autorun", cmd)

    def test_build_cmd_custom_config(self) -> None:
        from story_automator.core.collectors.performance import LIGHTHOUSE

        profile = {"rules": {"performance": {"lhci_config": "lighthouserc.custom.json"}}}
        cmd = LIGHTHOUSE.build_cmd("/tmp/checkout", profile)
        self.assertIn("--config=lighthouserc.custom.json", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.performance import LIGHTHOUSE

        self.assertIsNotNone(LIGHTHOUSE.tool_version_cmd)
        self.assertIn("lhci", LIGHTHOUSE.tool_version_cmd)


class BundlesizeCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.performance import BUNDLESIZE

        self.assertEqual(BUNDLESIZE.collector_id, "bundlesize-performance")
        self.assertEqual(BUNDLESIZE.tool, "bundlesize")
        self.assertEqual(BUNDLESIZE.category, "performance")
        self.assertTrue(BUNDLESIZE.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.performance import BUNDLESIZE

        cmd = BUNDLESIZE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "npx")
        self.assertIn("bundlesize", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.performance import BUNDLESIZE

        self.assertIsNotNone(BUNDLESIZE.tool_version_cmd)


class PerfLintCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.performance import PERF_LINT

        self.assertEqual(PERF_LINT.collector_id, "perf-lint-performance")
        self.assertEqual(PERF_LINT.tool, "python3")
        self.assertEqual(PERF_LINT.category, "performance")
        self.assertTrue(PERF_LINT.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.performance import PERF_LINT

        cmd = PERF_LINT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("perf_lint_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")

    def test_build_cmd_custom_extensions(self) -> None:
        from story_automator.core.collectors.performance import PERF_LINT

        profile = {"rules": {"performance": {"lint_extensions": [".py", ".rs"]}}}
        cmd = PERF_LINT.build_cmd("/tmp/checkout", profile)
        extensions = json.loads(cmd[3])
        self.assertEqual(extensions, [".py", ".rs"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.performance import PERF_LINT

        cmd = PERF_LINT.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class PerformanceCollectorListTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.performance import COLLECTORS

        self.assertEqual(len(COLLECTORS), 3)

    def test_all_performance_category(self) -> None:
        from story_automator.core.collectors.performance import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "performance")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.performance import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "lighthouse-performance", "bundlesize-performance",
            "perf-lint-performance",
        })

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.performance import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_performance.py -v`
Expected: `ModuleNotFoundError` — `performance` module does not exist yet.

- [ ] **Step 3: Implement performance collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/performance.py
"""Performance-category evidence collectors (§6.2).

PASS rule: bundle/Lighthouse budgets met; no static N+1/unbounded.
Collectors: lighthouse-performance, bundlesize-performance, perf-lint-performance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _lighthouse_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("performance") or {}
    cmd = ["lhci", "autorun"]
    config = rules.get("lhci_config")
    if config:
        cmd.append(f"--config={config}")
    return cmd


def _bundlesize_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "bundlesize"]


def _perf_lint_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("performance") or {}
    cmd = [
        sys.executable,
        str(_CHECKS_DIR / "perf_lint_check.py"),
        checkout,
    ]
    extensions = rules.get("lint_extensions")
    if extensions:
        cmd.append(json.dumps(extensions))
    return cmd


LIGHTHOUSE = CollectorConfig(
    collector_id="lighthouse-performance",
    tool="lhci",
    category="performance",
    build_cmd=_lighthouse_cmd,
    tool_version_cmd=("lhci", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx", "*.css", "*.html"}),
)

BUNDLESIZE = CollectorConfig(
    collector_id="bundlesize-performance",
    tool="bundlesize",
    category="performance",
    build_cmd=_bundlesize_cmd,
    tool_version_cmd=("npx", "bundlesize", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx", "*.css"}),
)

PERF_LINT = CollectorConfig(
    collector_id="perf-lint-performance",
    tool="python3",
    category="performance",
    build_cmd=_perf_lint_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [LIGHTHOUSE, BUNDLESIZE, PERF_LINT]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_performance.py -v`
Expected: All 16 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_performance.py skills/bmad-story-automator/src/story_automator/core/collectors/performance.py
git commit -m "feat(collector): add performance collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: Accessibility collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/accessibility.py`
- Create: `tests/test_collectors_accessibility.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`
- Produces: `AXE: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (1 item)

- [ ] **Step 1: Write failing tests for accessibility collector**

```python
# tests/test_collectors_accessibility.py
from __future__ import annotations

import unittest


class AxeCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        self.assertEqual(AXE.collector_id, "axe-accessibility")
        self.assertEqual(AXE.tool, "playwright")
        self.assertEqual(AXE.category, "accessibility")
        self.assertTrue(AXE.deterministic)
        self.assertIn("*.ts", AXE.file_patterns)
        self.assertIn("*.tsx", AXE.file_patterns)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        cmd = AXE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "npx")
        self.assertIn("playwright", cmd)
        self.assertIn("test", cmd)
        self.assertIn("--grep", cmd)
        self.assertIn("@a11y", cmd)

    def test_build_cmd_custom_grep(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        profile = {"rules": {"accessibility": {"playwright_grep": "@axe"}}}
        cmd = AXE.build_cmd("/tmp/checkout", profile)
        self.assertIn("@axe", cmd)
        self.assertNotIn("@a11y", cmd)

    def test_build_cmd_custom_config(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        profile = {"rules": {"accessibility": {"playwright_config": "e2e.config.ts"}}}
        cmd = AXE.build_cmd("/tmp/checkout", profile)
        self.assertIn("--config=e2e.config.ts", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.accessibility import AXE

        self.assertIsNotNone(AXE.tool_version_cmd)
        self.assertIn("playwright", AXE.tool_version_cmd)


class AccessibilityCollectorListTests(unittest.TestCase):
    def test_one_collector(self) -> None:
        from story_automator.core.collectors.accessibility import COLLECTORS

        self.assertEqual(len(COLLECTORS), 1)

    def test_all_accessibility_category(self) -> None:
        from story_automator.core.collectors.accessibility import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "accessibility")

    def test_expected_id(self) -> None:
        from story_automator.core.collectors.accessibility import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"axe-accessibility"})

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.accessibility import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_accessibility.py -v`
Expected: `ModuleNotFoundError` — `accessibility` module does not exist yet.

- [ ] **Step 3: Implement accessibility collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/accessibility.py
"""Accessibility-category evidence collectors (§6.2).

PASS rule: axe 0 serious/critical on changed UI.
Collectors: axe-accessibility.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _axe_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("accessibility") or {}
    grep = rules.get("playwright_grep", "@a11y")
    cmd = ["npx", "playwright", "test", "--grep", grep]
    config = rules.get("playwright_config")
    if config:
        cmd.append(f"--config={config}")
    return cmd


AXE = CollectorConfig(
    collector_id="axe-accessibility",
    tool="playwright",
    category="accessibility",
    build_cmd=_axe_cmd,
    tool_version_cmd=("npx", "playwright", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [AXE]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_accessibility.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_accessibility.py skills/bmad-story-automator/src/story_automator/core/collectors/accessibility.py
git commit -m "feat(collector): add accessibility collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: OTel wiring check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/otel_check.py`
- Create: `tests/test_check_otel.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `otel_check.py <checkout> [required_signals_json]`. Exit 0 = all signals wired, 1 = missing, 2 = usage error. Also exports `check_otel_wiring(checkout, required_signals) -> list[str]` for unit testing.

- [ ] **Step 1: Write failing tests for OTel check script**

```python
# tests/test_check_otel.py
from __future__ import annotations

import os
import tempfile
import unittest


class OtelCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.otel_check import main

        self.assertEqual(main([]), 2)


class CheckOtelWiringTests(unittest.TestCase):
    def test_all_signals_present(self) -> None:
        from story_automator.core.checks.otel_check import check_otel_wiring

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "telemetry.py"), "w") as f:
                f.write(
                    "from opentelemetry import trace\n"
                    "from opentelemetry import metrics\n"
                    "import logging\n"
                    "tracer = trace.get_tracer(__name__)\n"
                    "meter = metrics.get_meter(__name__)\n"
                    "logger = logging.getLogger(__name__)\n"
                )
            missing = check_otel_wiring(checkout, ["traces", "metrics", "logs"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_missing_traces(self) -> None:
        from story_automator.core.checks.otel_check import check_otel_wiring

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "app.py"), "w") as f:
                f.write("import logging\nlogger = logging.getLogger(__name__)\n")
            missing = check_otel_wiring(checkout, ["traces", "metrics", "logs"])
            self.assertTrue(any("traces" in m for m in missing))
            self.assertTrue(any("metrics" in m for m in missing))
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_empty_checkout_reports_all_missing(self) -> None:
        from story_automator.core.checks.otel_check import check_otel_wiring

        checkout = tempfile.mkdtemp()
        try:
            missing = check_otel_wiring(checkout, ["traces", "metrics", "logs"])
            self.assertEqual(len(missing), 3)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_typescript_otel_detected(self) -> None:
        from story_automator.core.checks.otel_check import check_otel_wiring

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "tracing.ts"), "w") as f:
                f.write(
                    "import { trace } from '@opentelemetry/api';\n"
                    "import { metrics } from '@opentelemetry/api';\n"
                    "import { logs } from '@opentelemetry/api';\n"
                )
            missing = check_otel_wiring(checkout, ["traces", "metrics", "logs"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_otel.py -v`
Expected: `ModuleNotFoundError` — `otel_check` module does not exist yet.

- [ ] **Step 3: Implement OTel check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/otel_check.py
"""Check OTel instrumentation wiring in source code.

Standalone script invoked by the otel-wiring-observability collector.
Scans source files for OpenTelemetry SDK usage patterns.
Exit 0 = all required signals wired, exit 1 = missing, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_SIGNAL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "traces": [
        re.compile(r"(?:from\s+opentelemetry\s+import\s+trace|opentelemetry.*trace)", re.IGNORECASE),
        re.compile(r"@opentelemetry/.*trace", re.IGNORECASE),
        re.compile(r"get_tracer\s*\(", re.IGNORECASE),
    ],
    "metrics": [
        re.compile(r"(?:from\s+opentelemetry\s+import\s+metrics|opentelemetry.*metrics)", re.IGNORECASE),
        re.compile(r"@opentelemetry/.*metrics", re.IGNORECASE),
        re.compile(r"get_meter\s*\(", re.IGNORECASE),
    ],
    "logs": [
        re.compile(r"(?:import\s+logging|from\s+logging\s+import)", re.IGNORECASE),
        re.compile(r"@opentelemetry/.*logs", re.IGNORECASE),
        re.compile(r"getLogger|get_logger", re.IGNORECASE),
    ],
}

_SOURCE_EXTENSIONS = frozenset({".py", ".ts", ".tsx", ".js", ".jsx"})


def check_otel_wiring(
    checkout: str,
    required_signals: list[str],
) -> list[str]:
    """Check that required OTel signals are wired. Returns missing signals."""
    found: set[str] = set()
    for root, _dirs, files in os.walk(checkout):
        for fname in files:
            ext = os.path.splitext(fname)[1]
            if ext not in _SOURCE_EXTENSIONS:
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            for signal, patterns in _SIGNAL_PATTERNS.items():
                if signal in found:
                    continue
                for pat in patterns:
                    if pat.search(content):
                        found.add(signal)
                        break
    missing: list[str] = []
    for signal in required_signals:
        if signal not in found:
            missing.append(f"MISSING signal: {signal}")
    return missing


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: otel_check.py <checkout> [required_signals_json]")
        return 2
    checkout = args[0]
    if len(args) > 1:
        try:
            required: list[str] = json.loads(args[1])
        except (json.JSONDecodeError, TypeError):
            print(f"invalid signals list: {args[1]}")
            return 2
    else:
        required = ["traces", "metrics", "logs"]
    missing = check_otel_wiring(checkout, required)
    for m in missing:
        print(m)
    if missing:
        print(f"{len(missing)} OTel signal(s) not wired")
        return 1
    print(f"all {len(required)} OTel signal(s) wired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_otel.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_otel.py skills/bmad-story-automator/src/story_automator/core/checks/otel_check.py
git commit -m "feat(collector): add OTel wiring check script" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Health probe check script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/health_check.py`
- Create: `tests/test_check_health.py`

**Interfaces:**
- Consumes: nothing (standalone script, stdlib only)
- Produces: `main(argv) -> int` entry point. CLI: `health_check.py <checkout> [endpoints_json]`. Exit 0 = all endpoints found, 1 = missing, 2 = usage error. Also exports `check_health_endpoints(checkout, endpoints) -> list[str]` for unit testing.

- [ ] **Step 1: Write failing tests for health check script**

```python
# tests/test_check_health.py
from __future__ import annotations

import os
import tempfile
import unittest


class HealthCheckUsageTests(unittest.TestCase):
    def test_no_args_returns_2(self) -> None:
        from story_automator.core.checks.health_check import main

        self.assertEqual(main([]), 2)


class CheckHealthEndpointsTests(unittest.TestCase):
    def test_both_endpoints_present(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "app.py"), "w") as f:
                f.write(
                    '@app.get("/healthz")\n'
                    "def health(): return {'ok': True}\n"
                    '@app.get("/readyz")\n'
                    "def ready(): return {'ok': True}\n"
                )
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_missing_readyz(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "app.py"), "w") as f:
                f.write('@app.get("/healthz")\ndef health(): pass\n')
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(len(missing), 1)
            self.assertTrue(any("/readyz" in m for m in missing))
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_empty_checkout_reports_all_missing(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(len(missing), 2)
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_typescript_routes_detected(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            src = os.path.join(checkout, "src")
            os.makedirs(src)
            with open(os.path.join(src, "routes.ts"), "w") as f:
                f.write(
                    "app.get('/healthz', (req, res) => res.json({ok: true}));\n"
                    "app.get('/readyz', (req, res) => res.json({ok: true}));\n"
                )
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)

    def test_yaml_k8s_probe_detected(self) -> None:
        from story_automator.core.checks.health_check import check_health_endpoints

        checkout = tempfile.mkdtemp()
        try:
            k8s = os.path.join(checkout, "k8s")
            os.makedirs(k8s)
            with open(os.path.join(k8s, "deployment.yaml"), "w") as f:
                f.write(
                    "livenessProbe:\n"
                    "  httpGet:\n"
                    "    path: /healthz\n"
                    "readinessProbe:\n"
                    "  httpGet:\n"
                    "    path: /readyz\n"
                )
            missing = check_health_endpoints(checkout, ["/healthz", "/readyz"])
            self.assertEqual(missing, [])
        finally:
            import shutil
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_check_health.py -v`
Expected: `ModuleNotFoundError` — `health_check` module does not exist yet.

- [ ] **Step 3: Implement health check script**

```python
# skills/bmad-story-automator/src/story_automator/core/checks/health_check.py
"""Check /healthz and /readyz endpoint declarations.

Standalone script invoked by the health-probe-observability collector.
Scans source and config files for health/ready endpoint registrations.
Exit 0 = all endpoints found, exit 1 = missing, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import sys

_SOURCE_EXTENSIONS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml",
})


def _build_endpoint_re(endpoint: str) -> re.Pattern[str]:
    escaped = re.escape(endpoint)
    return re.compile(escaped)


def check_health_endpoints(
    checkout: str,
    endpoints: list[str],
) -> list[str]:
    """Check that all required endpoints are declared. Returns missing."""
    patterns = {ep: _build_endpoint_re(ep) for ep in endpoints}
    found: set[str] = set()
    for root, _dirs, files in os.walk(checkout):
        for fname in files:
            ext = os.path.splitext(fname)[1]
            if ext not in _SOURCE_EXTENSIONS:
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except OSError:
                continue
            for ep, pat in patterns.items():
                if ep in found:
                    continue
                if pat.search(content):
                    found.add(ep)
    missing: list[str] = []
    for ep in endpoints:
        if ep not in found:
            missing.append(f"MISSING endpoint: {ep}")
    return missing


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: health_check.py <checkout> [endpoints_json]")
        return 2
    checkout = args[0]
    if len(args) > 1:
        try:
            endpoints: list[str] = json.loads(args[1])
        except (json.JSONDecodeError, TypeError):
            print(f"invalid endpoints list: {args[1]}")
            return 2
    else:
        endpoints = ["/healthz", "/readyz"]
    missing = check_health_endpoints(checkout, endpoints)
    for m in missing:
        print(m)
    if missing:
        print(f"{len(missing)} health endpoint(s) not declared")
        return 1
    print(f"all {len(endpoints)} health endpoint(s) declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_check_health.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_check_health.py skills/bmad-story-automator/src/story_automator/core/checks/health_check.py
git commit -m "feat(collector): add health probe check script" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: Observability collector module

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/observability.py`
- Create: `tests/test_collectors_observability.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `story_automator.core.collector_config`; `otel_check.py`, `health_check.py`, `presence_check.py` from `core/checks/`
- Produces: `OTEL_WIRING: CollectorConfig`, `HEALTH_PROBE: CollectorConfig`, `SLO: CollectorConfig`, `COLLECTORS: list[CollectorConfig]` (3 items)

- [ ] **Step 1: Write failing tests for observability collectors**

```python
# tests/test_collectors_observability.py
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


class OtelWiringCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.observability import OTEL_WIRING

        self.assertEqual(OTEL_WIRING.collector_id, "otel-wiring-observability")
        self.assertEqual(OTEL_WIRING.tool, "python3")
        self.assertEqual(OTEL_WIRING.category, "observability")
        self.assertTrue(OTEL_WIRING.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.observability import OTEL_WIRING

        cmd = OTEL_WIRING.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("otel_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        signals = json.loads(cmd[3])
        self.assertEqual(signals, ["traces", "metrics", "logs"])

    def test_build_cmd_custom_signals(self) -> None:
        from story_automator.core.collectors.observability import OTEL_WIRING

        profile = {"rules": {"observability": {"required_signals": ["traces"]}}}
        cmd = OTEL_WIRING.build_cmd("/tmp/checkout", profile)
        signals = json.loads(cmd[3])
        self.assertEqual(signals, ["traces"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.observability import OTEL_WIRING

        cmd = OTEL_WIRING.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class HealthProbeCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.observability import HEALTH_PROBE

        self.assertEqual(HEALTH_PROBE.collector_id, "health-probe-observability")
        self.assertEqual(HEALTH_PROBE.tool, "python3")
        self.assertEqual(HEALTH_PROBE.category, "observability")
        self.assertTrue(HEALTH_PROBE.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.observability import HEALTH_PROBE

        cmd = HEALTH_PROBE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("health_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        endpoints = json.loads(cmd[3])
        self.assertEqual(endpoints, ["/healthz", "/readyz"])

    def test_build_cmd_custom_endpoints(self) -> None:
        from story_automator.core.collectors.observability import HEALTH_PROBE

        profile = {"rules": {"observability": {"health_endpoints": ["/health", "/ready"]}}}
        cmd = HEALTH_PROBE.build_cmd("/tmp/checkout", profile)
        endpoints = json.loads(cmd[3])
        self.assertEqual(endpoints, ["/health", "/ready"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.observability import HEALTH_PROBE

        cmd = HEALTH_PROBE.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class SloCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.observability import SLO

        self.assertEqual(SLO.collector_id, "slo-observability")
        self.assertEqual(SLO.tool, "python3")
        self.assertEqual(SLO.category, "observability")
        self.assertTrue(SLO.deterministic)

    def test_build_cmd_default(self) -> None:
        from story_automator.core.collectors.observability import SLO

        cmd = SLO.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("presence_check.py", cmd[1])
        self.assertEqual(cmd[2], "/tmp/checkout")
        files = json.loads(cmd[3])
        self.assertIsInstance(files, list)
        self.assertTrue(len(files) > 0)

    def test_build_cmd_custom_slo_files(self) -> None:
        from story_automator.core.collectors.observability import SLO

        profile = {"rules": {"observability": {"slo_files": ["slo/custom.yaml"]}}}
        cmd = SLO.build_cmd("/tmp/checkout", profile)
        files = json.loads(cmd[3])
        self.assertEqual(files, ["slo/custom.yaml"])

    def test_check_script_path_exists(self) -> None:
        from story_automator.core.collectors.observability import SLO

        cmd = SLO.build_cmd("/tmp/checkout", {})
        script_path = Path(cmd[1])
        self.assertTrue(script_path.exists(), f"check script missing: {script_path}")


class ObservabilityCollectorListTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.observability import COLLECTORS

        self.assertEqual(len(COLLECTORS), 3)

    def test_all_observability_category(self) -> None:
        from story_automator.core.collectors.observability import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "observability")

    def test_expected_ids(self) -> None:
        from story_automator.core.collectors.observability import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "otel-wiring-observability", "health-probe-observability",
            "slo-observability",
        })

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.observability import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_collectors_observability.py -v`
Expected: `ModuleNotFoundError` — `observability` module does not exist yet.

- [ ] **Step 3: Implement observability collector module**

```python
# skills/bmad-story-automator/src/story_automator/core/collectors/observability.py
"""Observability-category evidence collectors (§6.2).

PASS rule: OTel traces/metrics/logs wired; /healthz+/readyz; SLO declared.
Collectors: otel-wiring-observability, health-probe-observability, slo-observability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_SIGNALS = ["traces", "metrics", "logs"]
_DEFAULT_ENDPOINTS = ["/healthz", "/readyz"]
_DEFAULT_SLO_FILES = [
    "slo.yaml",
    "slo.yml",
    "monitoring/slo.yaml",
]


def _otel_wiring_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("observability") or {}
    signals = rules.get("required_signals", _DEFAULT_SIGNALS)
    return [
        sys.executable,
        str(_CHECKS_DIR / "otel_check.py"),
        checkout,
        json.dumps(signals),
    ]


def _health_probe_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("observability") or {}
    endpoints = rules.get("health_endpoints", _DEFAULT_ENDPOINTS)
    return [
        sys.executable,
        str(_CHECKS_DIR / "health_check.py"),
        checkout,
        json.dumps(endpoints),
    ]


def _slo_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("observability") or {}
    slo_files = rules.get("slo_files", _DEFAULT_SLO_FILES)
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(slo_files),
    ]


OTEL_WIRING = CollectorConfig(
    collector_id="otel-wiring-observability",
    tool="python3",
    category="observability",
    build_cmd=_otel_wiring_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.yaml", "*.yml"}),
)

HEALTH_PROBE = CollectorConfig(
    collector_id="health-probe-observability",
    tool="python3",
    category="observability",
    build_cmd=_health_probe_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.yaml", "*.yml"}),
)

SLO = CollectorConfig(
    collector_id="slo-observability",
    tool="python3",
    category="observability",
    build_cmd=_slo_cmd,
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json"}),
)

COLLECTORS: list[CollectorConfig] = [OTEL_WIRING, HEALTH_PROBE, SLO]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_collectors_observability.py -v`
Expected: All 16 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_collectors_observability.py skills/bmad-story-automator/src/story_automator/core/collectors/observability.py
git commit -m "feat(collector): add observability collector module" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 12: Registration wiring + whole-registry tests

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`
- Modify: `tests/test_core_collectors.py`

**Interfaces:**
- Consumes: `COLLECTORS` lists from traceability, api_compat, migrations, performance, accessibility, observability modules
- Produces: `register_core_collectors(registry)` now registers all 39 collectors (27 from M5+M6 + 12 from M7). `CORE_COLLECTOR_IDS` frozenset updated.

- [ ] **Step 1: Write failing test for expanded registry**

Update `tests/test_core_collectors.py` — replace `_EXPECTED_IDS` and `_EXPECTED_CATEGORIES` with the full 39-collector / 15-category sets:

```python
# tests/test_core_collectors.py
from __future__ import annotations

import unittest


_EXPECTED_IDS = frozenset(
    {
        # static (5)
        "ruff-static",
        "mypy-static",
        "tsc-static",
        "biome-static",
        "knip-static",
        # correctness (4)
        "pytest-correctness",
        "vitest-correctness",
        "playwright-correctness",
        "coverage-correctness",
        # docs (3)
        "doc-presence-docs",
        "api-docs-docs",
        "docusaurus-docs",
        # process (2)
        "adr-process",
        "trace-process",
        # security (4)
        "semgrep-security",
        "trivy-vuln-security",
        "osv-security",
        "gitleaks-security",
        # license (1)
        "license-check-license",
        # compliance (2)
        "compliance-rules-compliance",
        "conftest-compliance",
        # supply_chain (4)
        "sbom-supply_chain",
        "cosign-supply_chain",
        "provenance-supply_chain",
        "trivy-sbom-supply_chain",
        # invariants (2)
        "invariant-semgrep-invariants",
        "invariant-conftest-invariants",
        # traceability (1)
        "trace-traceability",
        # api_compat (2)
        "openapi-diff-api_compat",
        "schema-diff-api_compat",
        # migrations (2)
        "alembic-migrations",
        "migration-lint-migrations",
        # performance (3)
        "lighthouse-performance",
        "bundlesize-performance",
        "perf-lint-performance",
        # accessibility (1)
        "axe-accessibility",
        # observability (3)
        "otel-wiring-observability",
        "health-probe-observability",
        "slo-observability",
    }
)

_EXPECTED_CATEGORIES = frozenset(
    {
        "correctness",
        "static",
        "docs",
        "process",
        "security",
        "license",
        "compliance",
        "supply_chain",
        "invariants",
        "traceability",
        "api_compat",
        "migrations",
        "performance",
        "accessibility",
        "observability",
    }
)


class RegisterCoreCollectorsTests(unittest.TestCase):
    def test_registers_all_collectors(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        registered_ids = {c.collector_id for c in reg.all_collectors()}
        self.assertEqual(registered_ids, _EXPECTED_IDS)

    def test_covers_all_categories(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        self.assertEqual(reg.all_categories(), _EXPECTED_CATEGORIES)

    def test_no_duplicate_ids(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        ids = [c.collector_id for c in reg.all_collectors()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_double_register_raises(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        with self.assertRaises(ValueError):
            register_core_collectors(reg)

    def test_collector_count(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        self.assertEqual(len(reg.all_collectors()), 39)

    def test_exported_id_set(self) -> None:
        from story_automator.core.collectors import CORE_COLLECTOR_IDS

        self.assertEqual(CORE_COLLECTOR_IDS, _EXPECTED_IDS)


class ProfileFilteringTests(unittest.TestCase):
    def test_applicable_filters_by_profile_categories(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = {
            "categories": {"code": ["static"]},
            "categories_na": [],
        }
        applicable = reg.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertEqual(cats, {"static"})

    def test_categories_na_excludes(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = {
            "categories": {"code": ["static", "docs"]},
            "categories_na": ["docs"],
        }
        applicable = reg.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertEqual(cats, {"static"})

    def test_kill_switch_excludes_tool(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = {
            "categories": {"code": ["static"]},
            "categories_na": [],
            "rules": {"static": {"disabled_tools": ["knip"]}},
        }
        applicable = reg.applicable(profile)
        ids = {c.collector_id for c in applicable}
        self.assertNotIn("knip-static", ids)
        self.assertIn("ruff-static", ids)

    def test_integration_categories_filter(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = {
            "categories": {"code": [
                "traceability", "api_compat", "migrations",
                "performance", "accessibility", "observability",
            ]},
            "categories_na": [],
        }
        applicable = reg.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertEqual(cats, {
            "traceability", "api_compat", "migrations",
            "performance", "accessibility", "observability",
        })
        self.assertEqual(len(applicable), 12)
```

- [ ] **Step 2: Run tests to verify the new integration test fails**

Run: `python -m pytest tests/test_core_collectors.py::RegisterCoreCollectorsTests::test_collector_count -v`
Expected: FAIL — count is 27, not 39 (new modules not yet imported in `__init__.py`).

- [ ] **Step 3: Update __init__.py to register new categories**

Replace the contents of `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`:

```python
"""Core evidence collector registration (§6.2, §8 module 3).

Registers all built-in collectors for correctness, static, docs, process,
security, license, compliance, supply_chain, invariants, traceability,
api_compat, migrations, performance, accessibility, observability.
"""

from __future__ import annotations

from ..collector_registry import CollectorRegistry
from .accessibility import COLLECTORS as _ACCESSIBILITY
from .api_compat import COLLECTORS as _API_COMPAT
from .compliance import COLLECTORS as _COMPLIANCE
from .correctness import COLLECTORS as _CORRECTNESS
from .docs import COLLECTORS as _DOCS
from .invariants import COLLECTORS as _INVARIANTS
from .license import COLLECTORS as _LICENSE
from .migrations import COLLECTORS as _MIGRATIONS
from .observability import COLLECTORS as _OBSERVABILITY
from .performance import COLLECTORS as _PERFORMANCE
from .process import COLLECTORS as _PROCESS
from .security import COLLECTORS as _SECURITY
from .static import COLLECTORS as _STATIC
from .supply_chain import COLLECTORS as _SUPPLY_CHAIN
from .traceability import COLLECTORS as _TRACEABILITY

__all__ = ["register_core_collectors", "CORE_COLLECTOR_IDS"]

_ALL = (
    _ACCESSIBILITY + _API_COMPAT + _COMPLIANCE + _CORRECTNESS + _DOCS
    + _INVARIANTS + _LICENSE + _MIGRATIONS + _OBSERVABILITY
    + _PERFORMANCE + _PROCESS + _SECURITY + _STATIC + _SUPPLY_CHAIN
    + _TRACEABILITY
)

CORE_COLLECTOR_IDS: frozenset[str] = frozenset(c.collector_id for c in _ALL)


def register_core_collectors(registry: CollectorRegistry) -> None:
    """Register all built-in collectors into the given registry."""
    for config in _ALL:
        registry.register(config)
```

- [ ] **Step 4: Run all registry tests to verify they pass**

Run: `python -m pytest tests/test_core_collectors.py -v`
Expected: All tests PASS including the new `test_integration_categories_filter`.

- [ ] **Step 5: Verify no existing tests broke**

Run: `python -m pytest tests/test_collectors_correctness.py tests/test_collectors_static.py tests/test_collectors_docs.py tests/test_collectors_process.py tests/test_collectors_security.py tests/test_collectors_license.py tests/test_collectors_compliance.py tests/test_collectors_supply_chain.py tests/test_collectors_invariants.py -v`
Expected: All existing collector tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py tests/test_core_collectors.py
git commit -m "feat(collector): register integration collectors in core registry" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 13: Pipeline integration tests

**Files:**
- Modify: `tests/test_collector_integration.py`

**Interfaces:**
- Consumes: `CollectorRegistry`, `run_gate_collectors`, `register_core_collectors`, `verdict_for_collector_status`, `aggregate_verdicts`, `load_evidence_bundle` from existing modules
- Produces: Integration tests proving the 6 new categories work through the full gate pipeline (registry → run → evidence → verdict)

- [ ] **Step 1: Write integration tests for integration categories**

Append to `tests/test_collector_integration.py`:

```python
class IntegrationCategoryPipelineTests(unittest.TestCase):
    """Pipeline tests with traceability, api_compat, migrations,
    performance, accessibility, observability categories."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-integ-integration-")
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

    def _integration_profile(self) -> dict[str, Any]:
        return {
            "categories": {
                "code": [
                    "traceability", "api_compat", "migrations",
                    "performance", "accessibility", "observability",
                ],
                "system": [],
            },
            "categories_na": [],
            "rules": {
                "traceability": {},
                "api_compat": {},
                "migrations": {},
                "performance": {},
                "accessibility": {},
                "observability": {},
            },
            "timeouts": {},
        }

    def _integration_registry(self) -> CollectorRegistry:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="trace-traceability",
            tool="python3", category="traceability", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="openapi-diff-api_compat",
            tool="python3", category="api_compat", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="alembic-migrations",
            tool="python3", category="migrations", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="lighthouse-performance",
            tool="python3", category="performance", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="axe-accessibility",
            tool="python3", category="accessibility", build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="otel-wiring-observability",
            tool="python3", category="observability", build_cmd=_ok_cmd,
        ))
        return reg

    def test_all_integration_categories_pass(self) -> None:
        profile = self._integration_profile()
        reg = self._integration_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-integ-pass", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 6)
        for outcome in outcomes:
            self.assertEqual(outcome.evidence["status"], "ok")
        records = load_evidence_bundle(self.project_root, "gate-integ-pass")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(aggregate_verdicts(verdicts), "PASS")

    def test_performance_fail_propagates(self) -> None:
        profile = self._integration_profile()
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="lighthouse-performance",
            tool="python3", category="performance", build_cmd=_fail_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="axe-accessibility",
            tool="python3", category="accessibility", build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-integ-fail", self.base_sha,
                profile, reg,
            )
        records = load_evidence_bundle(self.project_root, "gate-integ-fail")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(verdicts["performance"], "FAIL")
        self.assertEqual(verdicts["accessibility"], "PASS")
        self.assertEqual(aggregate_verdicts(verdicts), "FAIL")

    def test_kill_switch_integration_tool(self) -> None:
        profile = self._integration_profile()
        profile["rules"]["performance"]["disabled_tools"] = ["python3"]
        reg = self._integration_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-integ-kill", self.base_sha,
                profile, reg,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertNotIn("performance", run_cats)
        self.assertIn("traceability", run_cats)

    def test_categories_na_excludes_accessibility(self) -> None:
        profile = self._integration_profile()
        profile["categories_na"] = ["accessibility"]
        reg = self._integration_registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-integ-na", self.base_sha,
                profile, reg,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertNotIn("accessibility", run_cats)
        self.assertIn("observability", run_cats)

    def test_mixed_categories_all_tiers(self) -> None:
        profile = {
            "categories": {
                "code": [
                    "correctness", "static", "security",
                    "traceability", "performance", "observability",
                ],
                "system": [],
            },
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }
        reg = CollectorRegistry()
        for cat in ["correctness", "static", "security",
                     "traceability", "performance", "observability"]:
            reg.register(CollectorConfig(
                collector_id=f"test-{cat}",
                tool="python3", category=cat, build_cmd=_ok_cmd,
            ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-mixed-tiers", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 6)
        records = load_evidence_bundle(self.project_root, "gate-mixed-tiers")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(aggregate_verdicts(verdicts), "PASS")
```

- [ ] **Step 2: Run integration tests to verify they pass**

Run: `python -m pytest tests/test_collector_integration.py -v`
Expected: All tests PASS (existing + new `IntegrationCategoryPipelineTests`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_collector_integration.py
git commit -m "test(collector): add integration category pipeline tests" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 14: Quality gates

**Files:** All files from Tasks 1-13

**Interfaces:** None (validation only)

- [ ] **Step 1: Run ruff on all new/modified files**

Run:

```bash
ruff check \
  skills/bmad-story-automator/src/story_automator/core/collectors/traceability.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/api_compat.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/migrations.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/performance.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/accessibility.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/observability.py \
  skills/bmad-story-automator/src/story_automator/core/checks/traceability_check.py \
  skills/bmad-story-automator/src/story_automator/core/checks/migration_check.py \
  skills/bmad-story-automator/src/story_automator/core/checks/perf_lint_check.py \
  skills/bmad-story-automator/src/story_automator/core/checks/otel_check.py \
  skills/bmad-story-automator/src/story_automator/core/checks/health_check.py
```

Expected: No errors.

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS (existing ~95 test files + 11 new test files).

- [ ] **Step 3: Verify LOC limits**

Run:

```bash
wc -l \
  skills/bmad-story-automator/src/story_automator/core/collectors/traceability.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/api_compat.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/migrations.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/performance.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/accessibility.py \
  skills/bmad-story-automator/src/story_automator/core/collectors/observability.py \
  skills/bmad-story-automator/src/story_automator/core/checks/traceability_check.py \
  skills/bmad-story-automator/src/story_automator/core/checks/migration_check.py \
  skills/bmad-story-automator/src/story_automator/core/checks/perf_lint_check.py \
  skills/bmad-story-automator/src/story_automator/core/checks/otel_check.py \
  skills/bmad-story-automator/src/story_automator/core/checks/health_check.py
```

Expected: All files under 500 LOC.

- [ ] **Step 4: Verify collector count**

Run: `python -c "from story_automator.core.collectors import CORE_COLLECTOR_IDS; print(f'{len(CORE_COLLECTOR_IDS)} collectors registered'); assert len(CORE_COLLECTOR_IDS) == 39"`
Expected: `39 collectors registered`

- [ ] **Step 5: Verify category count**

Run: `python -c "from story_automator.core.collector_registry import CollectorRegistry; from story_automator.core.collectors import register_core_collectors; r = CollectorRegistry(); register_core_collectors(r); print(f'{len(r.all_categories())} categories'); assert len(r.all_categories()) == 15"`
Expected: `15 categories`

- [ ] **Step 6: Fix any issues found, commit**

If ruff or tests flagged issues, fix them and commit:

```bash
git add -A
git commit -m "fix(collector): quality gate fixes for collection-m7-integration-collectors" --trailer "Generated-By: claude-opus-4-6"
```
