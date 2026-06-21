# Extension M13: Test Burn-in — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement test burn-in, hard-wait detection, and mutation testing as evidence collectors and category rules for the `test_quality` and `mutation` gate categories (spec §8 module 5, §6.2, §12). These categories are already declared in `VALID_CODE_CATEGORIES` and profiled in MSME-ERP but have no collectors or rules — M13 fills the gap.

**Architecture:** Three new checker scripts under `core/checks/` plus two new collector modules under `core/collectors/` plus two new category rules in `category_rules.py`. Follows the established M5–M7 pattern exactly: standalone stdlib-only check scripts → `CollectorConfig` wrappers → category-specific rule functions → registration in `__init__.py`.

- **`burn_in_check.py`** (~130 LOC): Re-runs a test command N× (from `profile.rules.test_quality.burn_in_runs`). Tracks per-run exit codes. Parses JUnit XML (stdlib `xml.etree.ElementTree`) when available for per-test flakiness detection. Falls back to exit-code-only analysis otherwise.
- **`hard_wait_check.py`** (~90 LOC): Regex scanner for hard-coded waits (`time.sleep`, `asyncio.sleep`, `setTimeout`, `page.waitForTimeout`, `cy.wait`) in test files. Parallel to `perf_lint_check.py` but targeting test anti-patterns.
- **`mutation_check.py`** (~100 LOC): Invokes mutmut (Python) or Stryker (JS/TS) on changed files, parses results from tool output files, reports mutation score vs threshold.
- **`collectors/test_quality.py`** (~90 LOC): Three `CollectorConfig`s: burn-in, hard-wait, TEA test-review reader. TEA reader degrades gracefully when TEA output absent (§11).
- **`collectors/mutation.py`** (~60 LOC): One `CollectorConfig` for mutation testing.
- **`category_rules.py` additions** (~80 LOC): `test_quality_rule` (composite: flaky count, hard-wait count, test-review score) and `mutation_rule` (threshold-based score check).

**Dependency graph:** Consumes M4 framework (`CollectorConfig`, `CollectorRegistry`, `CollectorOutcome`, `run_collector_with_timeout`) and M9 verdict engine (`category_rules.py`, `verdict_engine.py`). Does NOT modify any existing module except `category_rules.py` (add two rule functions + register in `CATEGORY_RULES`) and `collectors/__init__.py` (import + register).

**Key existing interfaces consumed:**
- `collector_config.py`: `CollectorConfig`, `CollectorOutcome`, `CmdBuilder`
- `collector_registry.py`: `CollectorRegistry.register`, `CollectorRegistry.applicable`
- `category_rules.py`: `_status_based_rule`, `_make_category_result`, `worst_evidence_status`, `_aggregate_metrics`, `CATEGORY_RULES`
- `product_profile.py`: `rule_for`, `required_for_priority`, `VALID_CODE_CATEGORIES`
- `gate_schema.py`: `make_evidence_record`

**Tech Stack:** Python 3.11+, stdlib + `filelock` + `psutil` only; `unittest`; check scripts use stdlib only (`os`, `sys`, `json`, `re`, `subprocess`, `xml.etree.ElementTree`).

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Gate telemetry events land in their own milestone.
- **Do NOT modify existing m1–m10 module logic** except: `category_rules.py` (add two rule functions + register), `collectors/__init__.py` (import + register new collectors).
- **500-LOC soft limit per Python module.** Targets: each checker script ≤ 130, each collector module ≤ 90, each test file ≤ 200.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/<test_file>.py -v --tb=short` to validate per-task.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform**: checker scripts use `sys.executable` (not bash constructs). Tool commands use binary names directly.
- **Checker scripts use stdlib only** — they run as standalone subprocesses and must NOT import from `story_automator`.
- **Encoding safety**: all checker scripts open files with `errors="replace"` to avoid crashes on non-UTF-8 content.
- **Profile thresholds are the authority**: all rule functions read thresholds from `profile.rules.<category>` via `rule_for(profile, category)`, with sensible defaults when keys are absent.
- **Graceful degradation** (§11): when TEA output is absent, the test-review collector produces status `"ok"` with null score; the rule function treats missing score as non-blocking.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/checks/burn_in_check.py` — burn-in rerun engine + flaky detector (~130 LOC)
- `skills/bmad-story-automator/src/story_automator/core/checks/hard_wait_check.py` — hard-wait pattern scanner (~90 LOC)
- `skills/bmad-story-automator/src/story_automator/core/checks/mutation_check.py` — mutation tool runner + score parser (~100 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/test_quality.py` — burn-in, hard-wait, test-review collectors (~90 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/mutation.py` — mutation collector (~60 LOC)
- `tests/test_check_burn_in.py` — burn-in check tests (~200 LOC)
- `tests/test_check_hard_wait.py` — hard-wait check tests (~130 LOC)
- `tests/test_check_mutation.py` — mutation check tests (~160 LOC)
- `tests/test_collectors_test_quality.py` — test_quality collector tests (~130 LOC)
- `tests/test_collectors_mutation.py` — mutation collector tests (~100 LOC)
- `tests/test_check_test_review.py` — TEA test-review check tests (~80 LOC)
- `tests/test_burn_in_rules.py` — test_quality + mutation category rule tests (~180 LOC)
- `tests/test_burn_in_integration.py` — end-to-end integration tests (~180 LOC)

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/category_rules.py` — add `test_quality_rule`, `mutation_rule`, register in `CATEGORY_RULES` (~+80 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py` — import + register test_quality and mutation collectors (~+10 LOC)

**Untouched (explicit):** `core/adjudicator.py`, `core/evidence_io.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/gate_audit.py`, `core/gate_orchestrator.py`, `core/gate_status.py`, `core/gate_remediation.py`, `core/trust_boundary.py`, `core/collector_checkout.py`, `core/collector_config.py`, `core/collector_registry.py`, `core/collector_runner.py`, `core/collector_doctor.py`, `core/diff_scope.py`, `core/product_profile.py`, `core/verdict_engine.py`, `core/telemetry_events.py`, `data/profiles/default.json`, `data/profiles/msme-erp.json`, all existing collector modules.

---

### Task 1: Burn-in Check — Core Rerun Engine

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/burn_in_check.py`
- Create: `tests/test_check_burn_in.py`

**Interfaces:**
- Consumes: stdlib only (`os`, `sys`, `json`, `subprocess`, `tempfile`, `xml.etree.ElementTree`)
- Produces: `burn_in_check.main(argv: list[str] | None = None) -> int` — standalone script and importable function. Exit 0 = no flaky tests. Exit 1 = flaky test(s) detected. Exit 2 = usage error. Prints JSON summary line `BURN_IN_RESULT: {...}` with keys: `total_runs`, `passed_runs`, `failed_runs`, `flaky`, `flaky_count`, `flaky_tests`.

**Burn-in algorithm:**
1. Parse args: `<checkout> <n_runs> [--timeout <per_run_seconds>] -- <test_command...>`
2. For each of N runs: run the test command from `checkout` via `subprocess.run(timeout=per_run_timeout)`, capture exit code and stdout. Default per-run timeout: 300s.
3. After each run, scan for JUnit XML files (`**/results*.xml`, `**/junit*.xml`) in checkout.
4. If JUnit XMLs found: parse via `xml.etree.ElementTree`, extract per-test pass/fail per run.
5. A test is "flaky" if it has ≥1 pass AND ≥1 fail across the N runs.
6. Suite-level flaky: if some runs exit 0 and some exit non-zero, even without JUnit data.
7. Print `BURN_IN_RESULT: <json>` summary to stdout.

**Design notes:**
- The per-run timeout should be passed from the collector, derived from `profile.timeouts.test_quality / burn_in_runs` (e.g., 900s / 5 runs = 180s per run).
- The burn-in collector's test command (`pytest --tb=short -q`) is a default; the profile's toolchain can override it in a future enhancement. For M13, the hardcoded default is acceptable.
- The collector passes the full test command after `--`, so the check script itself is tool-agnostic.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_check_burn_in.py`:

```python
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_CHECKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
    / "story_automator" / "core" / "checks"
)


def _run_check(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECKS_DIR / "burn_in_check.py")] + args,
        capture_output=True, text=True, timeout=30,
    )


def _parse_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("BURN_IN_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


def _make_script(tmp: str, name: str, content: str) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


class TestBurnInCheckUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)

    def test_missing_separator_exits_2(self):
        r = _run_check(["/tmp", "3"])
        self.assertEqual(r.returncode, 2)


class TestBurnInCheckAllPass(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.script = _make_script(
            self.tmp, "pass_test.py",
            "import sys; sys.exit(0)\n",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_pass_exits_0(self):
        r = _run_check([self.tmp, "3", "--", sys.executable, self.script])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertEqual(result["total_runs"], 3)
        self.assertEqual(result["passed_runs"], 3)
        self.assertEqual(result["failed_runs"], 0)
        self.assertFalse(result["flaky"])
        self.assertEqual(result["flaky_count"], 0)


class TestBurnInCheckAllFail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.script = _make_script(
            self.tmp, "fail_test.py",
            "import sys; sys.exit(1)\n",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_fail_exits_1_but_not_flaky(self):
        r = _run_check([self.tmp, "3", "--", sys.executable, self.script])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertEqual(result["total_runs"], 3)
        self.assertEqual(result["passed_runs"], 0)
        self.assertEqual(result["failed_runs"], 3)
        self.assertFalse(result["flaky"])


class TestBurnInCheckFlaky(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        counter_file = os.path.join(self.tmp, ".run_counter")
        self.script = _make_script(
            self.tmp, "flaky_test.py",
            textwrap.dedent(f"""\
                import sys, os
                counter = "{counter_file}"
                n = 0
                if os.path.exists(counter):
                    with open(counter) as f:
                        n = int(f.read().strip())
                n += 1
                with open(counter, "w") as f:
                    f.write(str(n))
                sys.exit(0 if n % 2 == 1 else 1)
            """),
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_flaky_detected(self):
        r = _run_check([self.tmp, "4", "--", sys.executable, self.script])
        self.assertEqual(r.returncode, 1)
        result = _parse_result(r.stdout)
        self.assertTrue(result["flaky"])
        self.assertGreater(result["passed_runs"], 0)
        self.assertGreater(result["failed_runs"], 0)


class TestBurnInCheckSingleRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.script = _make_script(
            self.tmp, "pass_test.py",
            "import sys; sys.exit(0)\n",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_single_run_no_flaky(self):
        r = _run_check([self.tmp, "1", "--", sys.executable, self.script])
        self.assertEqual(r.returncode, 0)
        result = _parse_result(r.stdout)
        self.assertEqual(result["total_runs"], 1)
        self.assertFalse(result["flaky"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement the burn-in check**

Create `skills/bmad-story-automator/src/story_automator/core/checks/burn_in_check.py`:

```python
"""Burn-in runner: re-execute a test command N times to detect flaky tests.

Standalone script invoked by the burn-in-test-quality collector.
Runs the supplied test command N times, tracks per-run exit codes,
and optionally parses JUnit XML for per-test flakiness.
Exit 0 = no flaky, exit 1 = flaky or all-fail, exit 2 = usage.

Stdout includes a BURN_IN_RESULT: JSON line with metrics.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET


def _parse_junit_tests(xml_path: str) -> dict[str, str]:
    """Parse JUnit XML, return {test_name: 'pass'|'fail'|'error'|'skip'}."""
    results: dict[str, str] = {}
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError):
        return results
    for tc in tree.iter("testcase"):
        name = tc.get("classname", "") + "." + tc.get("name", "")
        if tc.find("failure") is not None or tc.find("error") is not None:
            results[name] = "fail"
        elif tc.find("skipped") is not None:
            results[name] = "skip"
        else:
            results[name] = "pass"
    return results


def _find_junit_xmls(checkout: str) -> list[str]:
    """Find JUnit XML files in common locations."""
    patterns = [
        os.path.join(checkout, "**", "junit*.xml"),
        os.path.join(checkout, "**", "results*.xml"),
        os.path.join(checkout, "**", "TEST-*.xml"),
    ]
    found: list[str] = []
    for pat in patterns:
        found.extend(glob.glob(pat, recursive=True))
    return sorted(set(found))


def _detect_flaky_tests(
    per_run_tests: list[dict[str, str]],
) -> list[dict[str, int]]:
    """Identify tests with mixed pass/fail across runs."""
    all_tests: set[str] = set()
    for run in per_run_tests:
        all_tests.update(run.keys())
    flaky: list[dict[str, int]] = []
    for test in sorted(all_tests):
        pass_count = sum(1 for run in per_run_tests if run.get(test) == "pass")
        fail_count = sum(
            1 for run in per_run_tests
            if run.get(test) in ("fail", "error")
        )
        if pass_count > 0 and fail_count > 0:
            flaky.append({"name": test, "pass_count": pass_count, "fail_count": fail_count})
    return flaky


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 3 or "--" not in args:
        print("usage: burn_in_check.py <checkout> <n_runs> [--timeout <secs>] -- <test_command...>")
        return 2

    sep = args.index("--")
    positional = args[:sep]
    checkout = positional[0]
    try:
        n_runs = int(positional[1])
    except ValueError:
        print(f"invalid n_runs: {positional[1]}")
        return 2
    if n_runs < 1:
        print(f"n_runs must be >= 1; got {n_runs}")
        return 2

    per_run_timeout = 300
    if "--timeout" in positional:
        ti = positional.index("--timeout")
        if ti + 1 < len(positional):
            try:
                per_run_timeout = int(positional[ti + 1])
            except ValueError:
                print(f"invalid timeout: {positional[ti + 1]}")
                return 2

    test_cmd = args[sep + 1:]
    if not test_cmd:
        print("test command is empty")
        return 2

    passed_runs = 0
    failed_runs = 0
    per_run_tests: list[dict[str, str]] = []

    for run_idx in range(n_runs):
        try:
            proc = subprocess.run(
                test_cmd, cwd=checkout,
                capture_output=True, text=True, errors="replace",
                timeout=per_run_timeout,
            )
        except FileNotFoundError:
            print(f"test command not found: {test_cmd[0]}")
            return 2
        except subprocess.TimeoutExpired:
            failed_runs += 1
            per_run_tests.append({})
            print(f"run {run_idx + 1}/{n_runs}: TIMEOUT")
            continue

        if proc.returncode == 0:
            passed_runs += 1
            print(f"run {run_idx + 1}/{n_runs}: PASS")
        else:
            failed_runs += 1
            print(f"run {run_idx + 1}/{n_runs}: FAIL (exit {proc.returncode})")

        junit_files = _find_junit_xmls(checkout)
        run_tests: dict[str, str] = {}
        for jf in junit_files:
            run_tests.update(_parse_junit_tests(jf))
        per_run_tests.append(run_tests)

    has_junit_data = any(bool(run) for run in per_run_tests)
    flaky_tests: list[dict[str, int]] = []
    if has_junit_data:
        flaky_tests = _detect_flaky_tests(per_run_tests)

    suite_flaky = passed_runs > 0 and failed_runs > 0

    result = {
        "total_runs": n_runs,
        "passed_runs": passed_runs,
        "failed_runs": failed_runs,
        "flaky": bool(flaky_tests) or suite_flaky,
        "flaky_count": len(flaky_tests),
        "flaky_tests": flaky_tests,
    }
    print(f"BURN_IN_RESULT: {json.dumps(result)}")

    if result["flaky"] or failed_runs == n_runs:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_burn_in.py -v --tb=short
```

---

### Task 2: Burn-in Check — JUnit XML Per-test Flakiness

**Files:**
- Modify: `tests/test_check_burn_in.py`

**Interfaces:**
- Consumes: `burn_in_check._parse_junit_tests`, `burn_in_check._detect_flaky_tests`
- Tests: per-test flakiness via synthetic JUnit XML files

- [ ] **Step 1: Write additional tests for JUnit XML parsing**

Add to `tests/test_check_burn_in.py`:

```python
class TestJUnitParsing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_junit(self, name: str, content: str) -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_parse_passing_tests(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from burn_in_check import _parse_junit_tests
        finally:
            sys.path.pop(0)
        path = self._write_junit("junit.xml", textwrap.dedent("""\
            <?xml version="1.0" ?>
            <testsuite tests="2">
              <testcase classname="test_foo" name="test_one"/>
              <testcase classname="test_foo" name="test_two"/>
            </testsuite>
        """))
        result = _parse_junit_tests(path)
        self.assertEqual(result["test_foo.test_one"], "pass")
        self.assertEqual(result["test_foo.test_two"], "pass")

    def test_parse_failing_tests(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from burn_in_check import _parse_junit_tests
        finally:
            sys.path.pop(0)
        path = self._write_junit("junit.xml", textwrap.dedent("""\
            <?xml version="1.0" ?>
            <testsuite tests="2">
              <testcase classname="test_foo" name="test_one"/>
              <testcase classname="test_foo" name="test_two">
                <failure message="assert False"/>
              </testcase>
            </testsuite>
        """))
        result = _parse_junit_tests(path)
        self.assertEqual(result["test_foo.test_one"], "pass")
        self.assertEqual(result["test_foo.test_two"], "fail")

    def test_parse_malformed_xml_returns_empty(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from burn_in_check import _parse_junit_tests
        finally:
            sys.path.pop(0)
        path = self._write_junit("bad.xml", "not xml")
        result = _parse_junit_tests(path)
        self.assertEqual(result, {})


class TestFlakyDetection(unittest.TestCase):
    def test_no_flaky_all_pass(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from burn_in_check import _detect_flaky_tests
        finally:
            sys.path.pop(0)
        runs = [
            {"a.test_1": "pass", "a.test_2": "pass"},
            {"a.test_1": "pass", "a.test_2": "pass"},
        ]
        self.assertEqual(_detect_flaky_tests(runs), [])

    def test_flaky_detected(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from burn_in_check import _detect_flaky_tests
        finally:
            sys.path.pop(0)
        runs = [
            {"a.test_1": "pass", "a.test_2": "pass"},
            {"a.test_1": "pass", "a.test_2": "fail"},
        ]
        result = _detect_flaky_tests(runs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "a.test_2")

    def test_all_fail_not_flaky(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from burn_in_check import _detect_flaky_tests
        finally:
            sys.path.pop(0)
        runs = [
            {"a.test_1": "fail"},
            {"a.test_1": "fail"},
        ]
        self.assertEqual(_detect_flaky_tests(runs), [])
```

- [ ] **Step 2: Verify all burn-in tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_burn_in.py -v --tb=short
```

---

### Task 3: Hard-Wait Check — Pattern Detection

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/hard_wait_check.py`
- Create: `tests/test_check_hard_wait.py`

**Interfaces:**
- Consumes: stdlib only (`os`, `sys`, `json`, `re`)
- Produces: `hard_wait_check.main(argv: list[str] | None = None) -> int` — standalone script. Exit 0 = no hard-waits. Exit 1 = hard-wait(s) found. Exit 2 = usage error. Prints `HARD_WAIT: <file>:<line>: <pattern>` for each finding, then a summary line.

**Detected patterns:**
- Python: `time.sleep(`, `asyncio.sleep(`
- JavaScript/TypeScript: `setTimeout(` (in test files), `page.waitForTimeout(`, `cy.wait(`, `browser.pause(`, `await sleep(`
- Exclusion: lines containing `# noqa: burn-in` or `// noqa: burn-in` are ignored (opt-out marker)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_check_hard_wait.py`:

```python
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_CHECKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
    / "story_automator" / "core" / "checks"
)


def _run_check(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECKS_DIR / "hard_wait_check.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


class TestHardWaitUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)


class TestHardWaitPython(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_time_sleep(self):
        test_file = os.path.join(self.tmp, "test_example.py")
        with open(test_file, "w") as f:
            f.write("import time\ntime.sleep(5)\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        self.assertIn("HARD_WAIT:", r.stdout)
        self.assertIn("time.sleep", r.stdout)

    def test_detects_asyncio_sleep(self):
        test_file = os.path.join(self.tmp, "test_async.py")
        with open(test_file, "w") as f:
            f.write("import asyncio\nawait asyncio.sleep(2)\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        self.assertIn("asyncio.sleep", r.stdout)

    def test_clean_file_passes(self):
        test_file = os.path.join(self.tmp, "test_clean.py")
        with open(test_file, "w") as f:
            f.write("def test_ok():\n    assert True\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)

    def test_noqa_marker_suppresses(self):
        test_file = os.path.join(self.tmp, "test_noqa.py")
        with open(test_file, "w") as f:
            f.write("time.sleep(5)  # noqa: burn-in\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)

    def test_non_test_file_ignored(self):
        src_file = os.path.join(self.tmp, "main.py")
        with open(src_file, "w") as f:
            f.write("import time\ntime.sleep(5)\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 0)


class TestHardWaitJavaScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_wait_for_timeout(self):
        test_file = os.path.join(self.tmp, "test_e2e.spec.ts")
        with open(test_file, "w") as f:
            f.write("await page.waitForTimeout(5000);\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)
        self.assertIn("waitForTimeout", r.stdout)

    def test_detects_set_timeout(self):
        test_file = os.path.join(self.tmp, "test_timer.test.ts")
        with open(test_file, "w") as f:
            f.write("setTimeout(() => {}, 3000);\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)

    def test_detects_cy_wait(self):
        test_file = os.path.join(self.tmp, "test_cypress.spec.js")
        with open(test_file, "w") as f:
            f.write("cy.wait(5000);\n")
        r = _run_check([self.tmp])
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement the hard-wait check**

Create `skills/bmad-story-automator/src/story_automator/core/checks/hard_wait_check.py`:

```python
"""Detect hard-coded waits in test files.

Standalone script invoked by the hard-wait-test-quality collector.
Scans test files for sleep/wait anti-patterns across Python and JS/TS.
Exit 0 = clean, exit 1 = findings, exit 2 = usage error.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import re
import sys

_PYTHON_PATTERNS = [
    re.compile(r"time\.sleep\s*\("),
    re.compile(r"asyncio\.sleep\s*\("),
]

_JS_PATTERNS = [
    re.compile(r"setTimeout\s*\("),
    re.compile(r"\.waitForTimeout\s*\("),
    re.compile(r"cy\.wait\s*\("),
    re.compile(r"browser\.pause\s*\("),
    re.compile(r"await\s+sleep\s*\("),
]

_NOQA_RE = re.compile(r"#\s*noqa:\s*burn-in|//\s*noqa:\s*burn-in")

_TEST_FILE_PATTERNS = [
    re.compile(r"^test_.*\.py$"),
    re.compile(r".*_test\.py$"),
    re.compile(r".*\.test\.[jt]sx?$"),
    re.compile(r".*\.spec\.[jt]sx?$"),
    re.compile(r"^test_.*\.[jt]sx?$"),
]

_PY_EXT = frozenset({".py"})
_JS_EXT = frozenset({".js", ".jsx", ".ts", ".tsx"})


def _is_test_file(filename: str) -> bool:
    return any(pat.match(filename) for pat in _TEST_FILE_PATTERNS)


def _get_patterns(ext: str) -> list[re.Pattern[str]]:
    if ext in _PY_EXT:
        return _PYTHON_PATTERNS
    if ext in _JS_EXT:
        return _JS_PATTERNS
    return []


def scan_file(filepath: str, checkout: str) -> list[str]:
    """Scan a single file for hard-wait patterns."""
    _, ext = os.path.splitext(filepath)
    patterns = _get_patterns(ext)
    if not patterns:
        return []
    findings: list[str] = []
    with open(filepath, encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            if _NOQA_RE.search(line):
                continue
            for pat in patterns:
                if pat.search(line):
                    rel = os.path.relpath(filepath, checkout)
                    findings.append(
                        f"HARD_WAIT: {rel}:{lineno}: {line.strip()}"
                    )
                    break
    return findings


def scan_directory(checkout: str) -> list[str]:
    """Walk checkout and scan test files for hard-wait patterns."""
    all_findings: list[str] = []
    for root, _dirs, files in os.walk(checkout):
        for fname in sorted(files):
            if not _is_test_file(fname):
                continue
            path = os.path.join(root, fname)
            all_findings.extend(scan_file(path, checkout))
    return all_findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: hard_wait_check.py <checkout>")
        return 2
    checkout = args[0]
    findings = scan_directory(checkout)
    for f in findings:
        print(f)
    if findings:
        print(f"{len(findings)} hard-wait(s) found")
        return 1
    print("no hard-waits found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_hard_wait.py -v --tb=short
```

---

### Task 4: Mutation Check — Tool Invocation and Score Parsing

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/mutation_check.py`
- Create: `tests/test_check_mutation.py`

**Interfaces:**
- Consumes: stdlib only (`os`, `sys`, `json`, `subprocess`, `re`)
- Produces: `mutation_check.main(argv: list[str] | None = None) -> int` — standalone script. Exit 0 = score meets threshold. Exit 1 = below threshold or tool error. Exit 2 = usage error. Prints `MUTATION_RESULT: <json>` with keys: `tool`, `mutation_score`, `mutants_total`, `mutants_killed`, `mutants_survived`, `threshold`, `passed`.

**Supported tools:**
- `mutmut` (Python): runs `mutmut run --paths-to-mutate=<files>`, parses `.mutmut-cache/` results or `mutmut results` output.
- `stryker` (JS/TS): runs `npx stryker run`, parses `reports/mutation/mutation.json`.
- Falls back to exit-code-only if result files not found.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_check_mutation.py`:

```python
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_CHECKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
    / "story_automator" / "core" / "checks"
)


def _run_check(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECKS_DIR / "mutation_check.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


def _parse_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("MUTATION_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


class TestMutationCheckUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)

    def test_invalid_tool_exits_2(self):
        r = _run_check(["/tmp", "unknown_tool", "60"])
        self.assertEqual(r.returncode, 2)


class TestMutationScoreParsing(unittest.TestCase):
    def test_parse_mutmut_results(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from mutation_check import _parse_mutmut_score
        finally:
            sys.path.pop(0)
        output = textwrap.dedent("""\
            Killed: 8
            Survived: 2
            Timeout: 0
            Suspicious: 0
            Skipped: 0
        """)
        score, killed, survived, total = _parse_mutmut_score(output)
        self.assertAlmostEqual(score, 80.0)
        self.assertEqual(killed, 8)
        self.assertEqual(survived, 2)
        self.assertEqual(total, 10)

    def test_parse_stryker_json(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from mutation_check import _parse_stryker_score
        finally:
            sys.path.pop(0)
        report = {
            "schemaVersion": "1",
            "thresholds": {"high": 80, "low": 60},
            "files": {
                "src/foo.ts": {
                    "mutants": [
                        {"status": "Killed"},
                        {"status": "Killed"},
                        {"status": "Survived"},
                    ]
                }
            },
        }
        score, killed, survived, total = _parse_stryker_score(report)
        self.assertAlmostEqual(score, 66.67, places=1)
        self.assertEqual(killed, 2)
        self.assertEqual(survived, 1)
        self.assertEqual(total, 3)

    def test_empty_mutmut_output(self):
        sys.path.insert(0, str(_CHECKS_DIR))
        try:
            from mutation_check import _parse_mutmut_score
        finally:
            sys.path.pop(0)
        score, killed, survived, total = _parse_mutmut_score("")
        self.assertEqual(score, 0.0)
        self.assertEqual(total, 0)


class TestMutationThreshold(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tool_not_found_exits_1(self):
        r = _run_check([self.tmp, "mutmut", "60"])
        self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement the mutation check**

Create `skills/bmad-story-automator/src/story_automator/core/checks/mutation_check.py`:

```python
"""Run mutation testing and check score against threshold.

Standalone script invoked by the mutation collector.
Supports mutmut (Python) and Stryker (JS/TS).
Exit 0 = score >= threshold, exit 1 = below or error, exit 2 = usage.

Stdout includes a MUTATION_RESULT: JSON line with metrics.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

VALID_TOOLS = frozenset({"mutmut", "stryker"})

_KILLED_RE = re.compile(r"Killed:\s*(\d+)", re.IGNORECASE)
_SURVIVED_RE = re.compile(r"Survived:\s*(\d+)", re.IGNORECASE)
_TIMEOUT_RE = re.compile(r"Timeout:\s*(\d+)", re.IGNORECASE)


def _parse_mutmut_score(output: str) -> tuple[float, int, int, int]:
    """Parse mutmut results output for mutation score."""
    killed = 0
    survived = 0
    m = _KILLED_RE.search(output)
    if m:
        killed = int(m.group(1))
    m = _SURVIVED_RE.search(output)
    if m:
        survived = int(m.group(1))
    m = _TIMEOUT_RE.search(output)
    timeout_count = int(m.group(1)) if m else 0
    total = killed + survived + timeout_count
    score = (killed / total * 100) if total > 0 else 0.0
    return score, killed, survived, total


def _parse_stryker_score(report: dict) -> tuple[float, int, int, int]:
    """Parse Stryker JSON mutation report."""
    killed = 0
    survived = 0
    total = 0
    for file_data in (report.get("files") or {}).values():
        for mutant in file_data.get("mutants", []):
            total += 1
            status = mutant.get("status", "").lower()
            if status == "killed":
                killed += 1
            elif status == "survived":
                survived += 1
    score = (killed / total * 100) if total > 0 else 0.0
    return score, killed, survived, total


def _run_mutmut(checkout: str, changed_files: str) -> tuple[float, int, int, int]:
    """Run mutmut and parse results."""
    cmd = ["mutmut", "run"]
    if changed_files:
        cmd.extend(["--paths-to-mutate", changed_files])
    try:
        subprocess.run(
            cmd, cwd=checkout, capture_output=True, text=True,
            errors="replace", timeout=600,
        )
    except FileNotFoundError:
        raise
    except subprocess.TimeoutExpired:
        return 0.0, 0, 0, 0

    try:
        result = subprocess.run(
            ["mutmut", "results"], cwd=checkout,
            capture_output=True, text=True, errors="replace", timeout=30,
        )
        return _parse_mutmut_score(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0.0, 0, 0, 0


def _run_stryker(checkout: str) -> tuple[float, int, int, int]:
    """Run Stryker and parse results."""
    try:
        subprocess.run(
            ["npx", "stryker", "run"], cwd=checkout,
            capture_output=True, text=True, errors="replace", timeout=600,
        )
    except FileNotFoundError:
        raise
    except subprocess.TimeoutExpired:
        return 0.0, 0, 0, 0

    report_path = os.path.join(checkout, "reports", "mutation", "mutation.json")
    if not os.path.isfile(report_path):
        return 0.0, 0, 0, 0
    try:
        with open(report_path, encoding="utf-8", errors="replace") as f:
            report = json.load(f)
        return _parse_stryker_score(report)
    except (json.JSONDecodeError, OSError):
        return 0.0, 0, 0, 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 3:
        print("usage: mutation_check.py <checkout> <tool> <threshold> [changed_files]")
        return 2
    checkout = args[0]
    tool = args[1]
    if tool not in VALID_TOOLS:
        print(f"unsupported mutation tool: {tool}; valid: {sorted(VALID_TOOLS)}")
        return 2
    try:
        threshold = float(args[2])
    except ValueError:
        print(f"invalid threshold: {args[2]}")
        return 2
    changed_files = args[3] if len(args) > 3 else ""

    try:
        if tool == "mutmut":
            score, killed, survived, total = _run_mutmut(checkout, changed_files)
        else:
            score, killed, survived, total = _run_stryker(checkout)
    except FileNotFoundError:
        print(f"mutation tool not found: {tool}")
        result = {
            "tool": tool, "mutation_score": 0.0,
            "mutants_total": 0, "mutants_killed": 0, "mutants_survived": 0,
            "threshold": threshold, "passed": False,
        }
        print(f"MUTATION_RESULT: {json.dumps(result)}")
        return 1

    passed = score >= threshold
    result = {
        "tool": tool, "mutation_score": round(score, 2),
        "mutants_total": total, "mutants_killed": killed,
        "mutants_survived": survived,
        "threshold": threshold, "passed": passed,
    }
    print(f"mutation score: {score:.1f}% (threshold: {threshold}%)")
    print(f"MUTATION_RESULT: {json.dumps(result)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_mutation.py -v --tb=short
```

---

### Task 5: Test Quality Collectors — Burn-in and Hard-Wait

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/test_quality.py`
- Create: `tests/test_collectors_test_quality.py`

**Interfaces:**
- Consumes: `collector_config.CollectorConfig`, `product_profile.rule_for`
- Produces: `COLLECTORS: list[CollectorConfig]` — three configs: `burn-in-test-quality`, `hard-wait-test-quality`, `test-review-test-quality`. Each has `category="test_quality"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collectors_test_quality.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_SRC = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from story_automator.core.collectors.test_quality import (
    BURN_IN,
    HARD_WAIT,
    TEST_REVIEW,
    COLLECTORS,
)


class TestBurnInCollector(unittest.TestCase):
    def test_category_is_test_quality(self):
        self.assertEqual(BURN_IN.category, "test_quality")

    def test_collector_id(self):
        self.assertEqual(BURN_IN.collector_id, "burn-in-test-quality")

    def test_tool(self):
        self.assertEqual(BURN_IN.tool, "python3")

    def test_build_cmd_includes_burn_in_runs(self):
        profile = {"rules": {"test_quality": {"burn_in_runs": 3}}, "timeouts": {"test_quality": 900}}
        cmd = BURN_IN.build_cmd("/checkout", profile)
        self.assertIn("burn_in_check.py", cmd[1])
        self.assertIn("3", cmd)
        self.assertIn("--timeout", cmd)
        self.assertIn("--", cmd)

    def test_build_cmd_default_runs(self):
        profile = {"rules": {}}
        cmd = BURN_IN.build_cmd("/checkout", profile)
        self.assertIn("5", cmd)
        self.assertIn("--timeout", cmd)


class TestHardWaitCollector(unittest.TestCase):
    def test_category_is_test_quality(self):
        self.assertEqual(HARD_WAIT.category, "test_quality")

    def test_collector_id(self):
        self.assertEqual(HARD_WAIT.collector_id, "hard-wait-test-quality")

    def test_build_cmd(self):
        cmd = HARD_WAIT.build_cmd("/checkout", {})
        self.assertIn("hard_wait_check.py", cmd[1])
        self.assertEqual(cmd[2], "/checkout")


class TestTestReviewCollector(unittest.TestCase):
    def test_category_is_test_quality(self):
        self.assertEqual(TEST_REVIEW.category, "test_quality")

    def test_collector_id(self):
        self.assertEqual(TEST_REVIEW.collector_id, "test-review-test-quality")

    def test_deterministic_is_false(self):
        self.assertFalse(TEST_REVIEW.deterministic)

    def test_build_cmd(self):
        profile = {"rules": {"test_quality": {"min_score": 70}}}
        cmd = TEST_REVIEW.build_cmd("/checkout", profile)
        self.assertIn("test_review_check.py", cmd[1])


class TestCollectorsList(unittest.TestCase):
    def test_all_three_present(self):
        self.assertEqual(len(COLLECTORS), 3)
        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("burn-in-test-quality", ids)
        self.assertIn("hard-wait-test-quality", ids)
        self.assertIn("test-review-test-quality", ids)

    def test_all_category_test_quality(self):
        for c in COLLECTORS:
            self.assertEqual(c.category, "test_quality")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement the test quality collectors**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/test_quality.py`:

```python
"""Test-quality-category evidence collectors (§6.2, §8 module 5).

PASS rule: TEA test-review >= band; 0 flaky over burn-in N×; no hard-waits.
Collectors: burn-in, hard-wait scanner, TEA test-review reader.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"
_DEFAULT_BURN_IN_RUNS = 5
_DEFAULT_MIN_SCORE = 70


def _burn_in_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("test_quality") or {}
    n_runs = int(rules.get("burn_in_runs", _DEFAULT_BURN_IN_RUNS))
    timeouts = profile.get("timeouts") or {}
    total_timeout = int(timeouts.get("test_quality", 900))
    per_run = max(60, total_timeout // max(n_runs, 1))
    return [
        sys.executable, str(_CHECKS_DIR / "burn_in_check.py"),
        checkout, str(n_runs), "--timeout", str(per_run),
        "--", "pytest", "--tb=short", "-q",
    ]


def _hard_wait_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable, str(_CHECKS_DIR / "hard_wait_check.py"),
        checkout,
    ]


def _test_review_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("test_quality") or {}
    min_score = int(rules.get("min_score", _DEFAULT_MIN_SCORE))
    return [
        sys.executable, str(_CHECKS_DIR / "test_review_check.py"),
        checkout, str(min_score),
    ]


BURN_IN = CollectorConfig(
    collector_id="burn-in-test-quality",
    tool="python3",
    category="test_quality",
    build_cmd=_burn_in_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

HARD_WAIT = CollectorConfig(
    collector_id="hard-wait-test-quality",
    tool="python3",
    category="test_quality",
    build_cmd=_hard_wait_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

TEST_REVIEW = CollectorConfig(
    collector_id="test-review-test-quality",
    tool="python3",
    category="test_quality",
    build_cmd=_test_review_cmd,
    deterministic=False,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [BURN_IN, HARD_WAIT, TEST_REVIEW]
```

- [ ] **Step 3: Verify tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_test_quality.py -v --tb=short
```

---

### Task 6: TEA Test-Review Check Script

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/test_review_check.py`
- Modify: `tests/test_collectors_test_quality.py` — add test-review check tests

**Interfaces:**
- Consumes: stdlib only (`os`, `sys`, `json`)
- Produces: `test_review_check.main(argv: list[str] | None = None) -> int` — standalone script. Reads TEA test-review output from standard locations. Exit 0 = score meets threshold or TEA absent (graceful degradation). Exit 1 = score below threshold. Exit 2 = usage error. Prints `TEST_REVIEW_RESULT: <json>` with keys: `score`, `threshold`, `available`, `passed`.

**TEA output locations searched:**
- `.tea/test-review.json`
- `test-review-summary.json`
- `_bmad/gate/risk/test-review.json`

- [ ] **Step 1: Write the tests**

Add test-review check tests to `tests/test_collectors_test_quality.py` (or create a separate `tests/test_check_test_review.py`):

**NOTE:** This task creates `test_review_check.py`, which is referenced in Task 5's `_test_review_cmd`. Task 5's test-review collector test (`test_build_cmd`) will import-fail until this task is complete. Implementors should create `test_review_check.py` (this task) before running Task 5's test suite, or stub the file first.

Create `tests/test_check_test_review.py` (standalone test file, not appended to `test_collectors_test_quality.py`):

```python
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_CHECKS_DIR = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
    / "story_automator" / "core" / "checks"
)


def _run_check(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_CHECKS_DIR / "test_review_check.py")] + args,
        capture_output=True, text=True, timeout=15,
    )


def _parse_review_result(stdout: str) -> dict:
    for line in stdout.splitlines():
        if line.startswith("TEST_REVIEW_RESULT:"):
            return json.loads(line.split(":", 1)[1].strip())
    return {}


class TestTestReviewCheckUsage(unittest.TestCase):
    def test_no_args_exits_2(self):
        r = _run_check([])
        self.assertEqual(r.returncode, 2)


class TestTestReviewCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_tea_output_exits_0(self):
        """Graceful degradation: no TEA = still pass."""
        r = _run_check([self.tmp, "70"])
        self.assertEqual(r.returncode, 0)
        result = _parse_review_result(r.stdout)
        self.assertFalse(result["available"])

    def test_score_above_threshold(self):
        tea_dir = os.path.join(self.tmp, ".tea")
        os.makedirs(tea_dir)
        with open(os.path.join(tea_dir, "test-review.json"), "w") as f:
            json.dump({"score": 85, "details": []}, f)
        r = _run_check([self.tmp, "70"])
        self.assertEqual(r.returncode, 0)
        result = _parse_review_result(r.stdout)
        self.assertTrue(result["available"])
        self.assertTrue(result["passed"])

    def test_score_below_threshold(self):
        tea_dir = os.path.join(self.tmp, ".tea")
        os.makedirs(tea_dir)
        with open(os.path.join(tea_dir, "test-review.json"), "w") as f:
            json.dump({"score": 50, "details": []}, f)
        r = _run_check([self.tmp, "70"])
        self.assertEqual(r.returncode, 1)
        result = _parse_review_result(r.stdout)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement test_review_check.py**

Create `skills/bmad-story-automator/src/story_automator/core/checks/test_review_check.py`:

```python
"""Read TEA test-review output and check score against threshold.

Standalone script invoked by the test-review-test-quality collector.
Gracefully degrades when TEA output is absent (exits 0, available=false).
Exit 0 = score meets threshold or TEA absent, exit 1 = below, exit 2 = usage.

Stdout includes a TEST_REVIEW_RESULT: JSON line.
Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_CANDIDATES = [
    os.path.join(".tea", "test-review.json"),
    "test-review-summary.json",
    os.path.join("_bmad", "gate", "risk", "test-review.json"),
]


def _find_review_file(checkout: str) -> str | None:
    for candidate in _CANDIDATES:
        path = os.path.join(checkout, candidate)
        if os.path.isfile(path):
            return path
    return None


def _extract_score(data: dict) -> float | None:
    score = data.get("score")
    if isinstance(score, (int, float)):
        return float(score)
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: test_review_check.py <checkout> <min_score>")
        return 2
    checkout = args[0]
    try:
        min_score = float(args[1])
    except ValueError:
        print(f"invalid min_score: {args[1]}")
        return 2

    review_file = _find_review_file(checkout)
    if not review_file:
        result = {"score": None, "threshold": min_score,
                  "available": False, "passed": True}
        print("TEA test-review not available; skipping")
        print(f"TEST_REVIEW_RESULT: {json.dumps(result)}")
        return 0

    try:
        with open(review_file, encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"failed to read test-review data: {exc}")
        return 1

    score = _extract_score(data)
    if score is None:
        print(f"could not parse score from {os.path.basename(review_file)}")
        return 1

    passed = score >= min_score
    result = {"score": score, "threshold": min_score,
              "available": True, "passed": passed}
    print(f"test-review score: {score:.1f} (threshold: {min_score})")
    print(f"TEST_REVIEW_RESULT: {json.dumps(result)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Verify tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_test_review.py -v --tb=short
```

---

### Task 7: Mutation Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/mutation.py`
- Create: `tests/test_collectors_mutation.py`

**Interfaces:**
- Consumes: `collector_config.CollectorConfig`
- Produces: `COLLECTORS: list[CollectorConfig]` — one config: `mutmut-mutation`. Category `"mutation"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collectors_mutation.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from story_automator.core.collectors.mutation import (
    MUTMUT,
    COLLECTORS,
)


class TestMutmutCollector(unittest.TestCase):
    def test_category_is_mutation(self):
        self.assertEqual(MUTMUT.category, "mutation")

    def test_collector_id(self):
        self.assertEqual(MUTMUT.collector_id, "mutmut-mutation")

    def test_tool(self):
        self.assertEqual(MUTMUT.tool, "python3")

    def test_build_cmd_includes_threshold(self):
        profile = {"rules": {"mutation": {"min_score": 60}}}
        cmd = MUTMUT.build_cmd("/checkout", profile)
        self.assertIn("mutation_check.py", cmd[1])
        self.assertIn("mutmut", cmd)
        self.assertIn("60", cmd)

    def test_build_cmd_default_threshold(self):
        profile = {"rules": {}}
        cmd = MUTMUT.build_cmd("/checkout", profile)
        self.assertIn("60", cmd)


class TestCollectorsList(unittest.TestCase):
    def test_all_present(self):
        self.assertEqual(len(COLLECTORS), 1)
        self.assertEqual(COLLECTORS[0].collector_id, "mutmut-mutation")

    def test_all_category_mutation(self):
        for c in COLLECTORS:
            self.assertEqual(c.category, "mutation")

    def test_file_patterns(self):
        self.assertIn("*.py", MUTMUT.file_patterns)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement the mutation collector**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/mutation.py`:

```python
"""Mutation-category evidence collectors (§6.2, §8 module 5).

PASS rule: mutation score >= threshold on changed code (sampled/budgeted).
Collectors: mutmut (Python), stryker (JS/TS — future extension).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"
_DEFAULT_MUTATION_THRESHOLD = 60


def _mutmut_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("mutation") or {}
    threshold = int(rules.get("min_score", _DEFAULT_MUTATION_THRESHOLD))
    return [
        sys.executable, str(_CHECKS_DIR / "mutation_check.py"),
        checkout, "mutmut", str(threshold),
    ]


MUTMUT = CollectorConfig(
    collector_id="mutmut-mutation",
    tool="python3",
    category="mutation",
    build_cmd=_mutmut_cmd,
    file_patterns=frozenset({"*.py"}),
)

COLLECTORS: list[CollectorConfig] = [MUTMUT]
```

- [ ] **Step 3: Verify tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_mutation.py -v --tb=short
```

---

### Task 8: test_quality Category Rule

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Create: `tests/test_burn_in_rules.py`

**Interfaces:**
- Consumes: `_make_category_result`, `worst_evidence_status`, `_aggregate_metrics`, `rule_for`
- Produces: `test_quality_rule(evidence, profile, required) -> dict` registered in `CATEGORY_RULES`

**Rule logic (§6.2, §12):**
1. Fail-closed: if any collector status is error/timeout → FAIL.
2. If flaky_count > max_flaky (from `profile.rules.test_quality.max_flaky`, default 0) → FAIL.
3. If hard_wait_count > 0 → FAIL.
4. If test_review_score is present and < min_score (from `profile.rules.test_quality.min_score`, default 70) → FAIL. If score not available (TEA absent), treated as non-blocking.
5. Otherwise → PASS.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_burn_in_rules.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from story_automator.core.category_rules import (
    test_quality_rule,
    mutation_rule,
    CATEGORY_RULES,
)


def _make_evidence(status="ok", metrics=None, category="test_quality"):
    return {
        "schema_version": 1,
        "collector": "test-collector",
        "tool": "test-tool",
        "category": category,
        "status": status,
        "metrics": metrics or {},
        "findings": [],
        "deterministic": True,
    }


class TestTestQualityRule(unittest.TestCase):
    def _profile(self, **overrides):
        rules = {"min_score": 70, "burn_in_runs": 5, "max_flaky": 0}
        rules.update(overrides)
        return {"rules": {"test_quality": rules}}

    def test_all_pass(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 0}),
            _make_evidence(metrics={"hard_wait_count": 0}),
            _make_evidence(metrics={"test_review_score": 85}),
        ]
        result = test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "PASS")

    def test_flaky_detected_fails(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 2}),
            _make_evidence(metrics={"hard_wait_count": 0}),
        ]
        result = test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("flaky", result["rationale"])

    def test_hard_wait_fails(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 0}),
            _make_evidence(metrics={"hard_wait_count": 3}),
        ]
        result = test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("hard-wait", result["rationale"])

    def test_low_test_review_score_fails(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 0}),
            _make_evidence(metrics={"hard_wait_count": 0}),
            _make_evidence(metrics={"test_review_score": 50}),
        ]
        result = test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("test-review", result["rationale"])

    def test_missing_tea_score_passes(self):
        """§11 graceful degradation: no TEA score = non-blocking."""
        evidence = [
            _make_evidence(metrics={"flaky_count": 0}),
            _make_evidence(metrics={"hard_wait_count": 0}),
        ]
        result = test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "PASS")

    def test_error_status_fail_closed(self):
        evidence = [_make_evidence(status="error")]
        result = test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("fail-closed", result["rationale"])

    def test_timeout_status_fail_closed(self):
        evidence = [_make_evidence(status="timeout")]
        result = test_quality_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_custom_max_flaky(self):
        evidence = [
            _make_evidence(metrics={"flaky_count": 2}),
            _make_evidence(metrics={"hard_wait_count": 0}),
        ]
        result = test_quality_rule(evidence, self._profile(max_flaky=5), {})
        self.assertEqual(result["verdict"], "PASS")


class TestTestQualityRegistered(unittest.TestCase):
    def test_registered_in_category_rules(self):
        self.assertIn("test_quality", CATEGORY_RULES)
        self.assertIs(CATEGORY_RULES["test_quality"], test_quality_rule)
```

- [ ] **Step 2: Implement test_quality_rule**

Add to `skills/bmad-story-automator/src/story_automator/core/category_rules.py`:

```python
def test_quality_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Section 6.2: TEA test-review >= band; 0 flaky over burn-in; no hard-waits."""
    status = worst_evidence_status(evidence)
    rules = rule_for(profile, "test_quality")
    max_flaky = int(rules.get("max_flaky", 0))
    min_score = float(rules.get("min_score", 70))

    flaky_count = int(_aggregate_metrics(evidence, "flaky_count", 0))
    hard_wait_count = int(_aggregate_metrics(evidence, "hard_wait_count", 0))
    test_review_score = _aggregate_metrics(evidence, "test_review_score", None)

    actual = {
        "flaky_count": flaky_count,
        "hard_wait_count": hard_wait_count,
        "test_review_score": test_review_score,
        "status": status,
    }
    req = {"max_flaky": max_flaky, "min_score": min_score, "hard_wait_count": 0}

    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")

    violations: list[str] = []
    if flaky_count > max_flaky:
        violations.append(f"flaky tests: {flaky_count} > {max_flaky}")
    if hard_wait_count > 0:
        violations.append(f"hard-wait(s): {hard_wait_count}")
    if test_review_score is not None and float(test_review_score) < min_score:
        violations.append(f"test-review score: {test_review_score} < {min_score}")
    if status == "violation":
        violations.append("collector reported violation")

    if violations:
        return _make_category_result("FAIL", req, actual, "; ".join(violations))
    return _make_category_result("PASS", req, actual, "all test-quality checks passed")
```

Also add to `CATEGORY_RULES` dict:

```python
CATEGORY_RULES: dict[str, CategoryRuleFn] = {
    "correctness": correctness_rule,
    "security": security_rule,
    "static": static_rule,
    "license": license_rule,
    "test_quality": test_quality_rule,
}
```

- [ ] **Step 3: Verify tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_burn_in_rules.py -v --tb=short
```

---

### Task 9: mutation Category Rule

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/category_rules.py`
- Modify: `tests/test_burn_in_rules.py`

**Interfaces:**
- Produces: `mutation_rule(evidence, profile, required) -> dict` registered in `CATEGORY_RULES`

**Rule logic (§6.2):**
1. Fail-closed: error/timeout → FAIL.
2. If mutation_score < threshold (from `profile.rules.mutation.min_score`, default 60) → FAIL.
3. If tool not found (mutants_total == 0 and status != ok) → FAIL.
4. Otherwise → PASS.

- [ ] **Step 1: Write the tests**

Add to `tests/test_burn_in_rules.py`:

```python
class TestMutationRule(unittest.TestCase):
    def _profile(self, **overrides):
        rules = {"min_score": 60}
        rules.update(overrides)
        return {"rules": {"mutation": rules}}

    def test_score_above_threshold(self):
        evidence = [
            _make_evidence(
                category="mutation",
                metrics={"mutation_score": 75.0, "mutants_total": 20,
                         "mutants_killed": 15, "mutants_survived": 5},
            ),
        ]
        result = mutation_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "PASS")

    def test_score_below_threshold(self):
        evidence = [
            _make_evidence(
                category="mutation",
                metrics={"mutation_score": 40.0, "mutants_total": 10,
                         "mutants_killed": 4, "mutants_survived": 6},
            ),
        ]
        result = mutation_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("mutation score", result["rationale"])

    def test_error_status_fail_closed(self):
        evidence = [_make_evidence(status="error", category="mutation")]
        result = mutation_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_no_mutants_tool_not_run(self):
        evidence = [
            _make_evidence(
                status="violation", category="mutation",
                metrics={"mutation_score": 0.0, "mutants_total": 0},
            ),
        ]
        result = mutation_rule(evidence, self._profile(), {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_custom_threshold(self):
        evidence = [
            _make_evidence(
                category="mutation",
                metrics={"mutation_score": 55.0, "mutants_total": 20,
                         "mutants_killed": 11, "mutants_survived": 9},
            ),
        ]
        result = mutation_rule(evidence, self._profile(min_score=50), {})
        self.assertEqual(result["verdict"], "PASS")


class TestMutationRegistered(unittest.TestCase):
    def test_registered_in_category_rules(self):
        self.assertIn("mutation", CATEGORY_RULES)
        self.assertIs(CATEGORY_RULES["mutation"], mutation_rule)
```

- [ ] **Step 2: Implement mutation_rule**

Add to `skills/bmad-story-automator/src/story_automator/core/category_rules.py`:

```python
def mutation_rule(
    evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    required: dict[str, Any],
) -> dict[str, Any]:
    """Section 6.2: mutation score >= threshold on changed code."""
    status = worst_evidence_status(evidence)
    rules = rule_for(profile, "mutation")
    min_score = float(rules.get("min_score", 60))

    mutation_score = float(_aggregate_metrics(evidence, "mutation_score", 0))
    mutants_total = int(_aggregate_metrics(evidence, "mutants_total", 0))
    mutants_killed = int(_aggregate_metrics(evidence, "mutants_killed", 0))
    mutants_survived = int(_aggregate_metrics(evidence, "mutants_survived", 0))

    actual = {
        "mutation_score": mutation_score,
        "mutants_total": mutants_total,
        "mutants_killed": mutants_killed,
        "mutants_survived": mutants_survived,
        "status": status,
    }
    req = {"min_score": min_score}

    if status in ("error", "timeout"):
        return _make_category_result("FAIL", req, actual, f"fail-closed: collector {status}")
    if mutants_total == 0 and status != "ok":
        return _make_category_result("FAIL", req, actual, "mutation tool did not produce results")
    if mutation_score < min_score:
        return _make_category_result(
            "FAIL", req, actual,
            f"mutation score {mutation_score:.1f}% < {min_score}%",
        )
    if status == "violation":
        return _make_category_result("FAIL", req, actual, "collector reported violation")
    return _make_category_result("PASS", req, actual, "mutation testing passed")
```

Also add `"mutation": mutation_rule` to `CATEGORY_RULES`.

- [ ] **Step 3: Verify tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_burn_in_rules.py -v --tb=short
```

---

### Task 10: Collector Registration

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`
- Modify: `tests/test_core_collectors.py`

**Interfaces:**
- Import `test_quality.COLLECTORS` and `mutation.COLLECTORS`, add to `_ALL` and `register_core_collectors`.

- [ ] **Step 1: Update registration**

Edit `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`:

Add imports:
```python
from .mutation import COLLECTORS as _MUTATION
from .test_quality import COLLECTORS as _TEST_QUALITY
```

Update `_ALL`:
```python
_ALL = (
    _ACCESSIBILITY + _API_COMPAT + _COMPLIANCE + _CORRECTNESS + _DOCS
    + _INVARIANTS + _LICENSE + _MIGRATIONS + _MUTATION + _OBSERVABILITY
    + _PERFORMANCE + _PROCESS + _SECURITY + _STATIC + _SUPPLY_CHAIN
    + _TEST_QUALITY + _TRACEABILITY
)
```

- [ ] **Step 2: Update `tests/test_core_collectors.py` expected sets**

The existing `_EXPECTED_IDS`, `_EXPECTED_CATEGORIES`, and `test_collector_count` must be updated. These are hard-coded assertions that gate the registration test.

Update `_EXPECTED_IDS` — add these 4 IDs to the existing set:
```python
        # test_quality (3)
        "burn-in-test-quality",
        "hard-wait-test-quality",
        "test-review-test-quality",
        # mutation (1)
        "mutmut-mutation",
```

Update `_EXPECTED_CATEGORIES` — add:
```python
        "test_quality",
        "mutation",
```

Update `test_collector_count` assertion:
```python
        self.assertEqual(len(reg.all_collectors()), 43)  # was 39
```

- [ ] **Step 3: Verify existing registration tests pass with new collectors**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_core_collectors.py -v --tb=short
```

---

### Task 11: Integration Test — Test Quality Pipeline

**Files:**
- Create: `tests/test_burn_in_integration.py`

**Interfaces:**
- Tests the full pipeline: register collectors → build config → verify evidence format → run through verdict engine with test_quality category. Uses `unittest.mock` to avoid actual subprocess calls.

- [ ] **Step 1: Write integration tests**

Create `tests/test_burn_in_integration.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SRC = (
    Path(__file__).resolve().parent.parent
    / "skills" / "bmad-story-automator" / "src"
)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from story_automator.core.collector_config import CollectorConfig
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.collectors import register_core_collectors
from story_automator.core.category_rules import (
    apply_category_rule,
    test_quality_rule,
    mutation_rule,
)
from story_automator.core.gate_schema import make_evidence_record
from story_automator.core.verdict_engine import (
    compute_category_verdict,
    compute_all_verdicts,
)


def _msme_profile():
    return {
        "version": 1, "id": "test",
        "matrix": {
            "P0": {"coverage_pct": 100, "levels": ["unit"]},
            "P1": {"coverage_pct": 90, "levels": ["unit"]},
            "P2": {"coverage_pct": 50, "levels": ["unit"]},
            "P3": {"coverage_pct": 20, "levels": ["smoke"]},
        },
        "categories": {
            "code": ["test_quality", "mutation"],
            "system": [],
        },
        "categories_na": [],
        "rules": {
            "test_quality": {"min_score": 70, "burn_in_runs": 5, "max_flaky": 0},
            "mutation": {"min_score": 60},
        },
    }


class TestTestQualityPipeline(unittest.TestCase):
    def test_registry_includes_test_quality(self):
        reg = CollectorRegistry()
        register_core_collectors(reg)
        configs = reg.get_for_category("test_quality")
        self.assertGreater(len(configs), 0)
        ids = {c.collector_id for c in configs}
        self.assertIn("burn-in-test-quality", ids)
        self.assertIn("hard-wait-test-quality", ids)
        self.assertIn("test-review-test-quality", ids)

    def test_registry_includes_mutation(self):
        reg = CollectorRegistry()
        register_core_collectors(reg)
        configs = reg.get_for_category("mutation")
        self.assertGreater(len(configs), 0)
        ids = {c.collector_id for c in configs}
        self.assertIn("mutmut-mutation", ids)

    def test_applicable_filters_for_profile(self):
        reg = CollectorRegistry()
        register_core_collectors(reg)
        profile = _msme_profile()
        applicable = reg.applicable(profile)
        categories = {c.category for c in applicable}
        self.assertIn("test_quality", categories)
        self.assertIn("mutation", categories)

    def test_verdict_engine_with_test_quality_evidence(self):
        profile = _msme_profile()
        evidence = [
            make_evidence_record(
                collector="burn-in-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"flaky_count": 0},
            ),
            make_evidence_record(
                collector="hard-wait-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"hard_wait_count": 0},
            ),
        ]
        result = apply_category_rule("test_quality", evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_verdict_engine_with_flaky_evidence(self):
        profile = _msme_profile()
        evidence = [
            make_evidence_record(
                collector="burn-in-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"flaky_count": 2},
            ),
        ]
        result = apply_category_rule("test_quality", evidence, profile, {})
        self.assertEqual(result["verdict"], "FAIL")

    def test_verdict_engine_with_mutation_evidence(self):
        profile = _msme_profile()
        evidence = [
            make_evidence_record(
                collector="mutmut-mutation", tool="python3",
                category="mutation", status="ok",
                metrics={"mutation_score": 75.0, "mutants_total": 20,
                         "mutants_killed": 15, "mutants_survived": 5},
            ),
        ]
        result = apply_category_rule("mutation", evidence, profile, {})
        self.assertEqual(result["verdict"], "PASS")

    def test_compute_all_verdicts_includes_categories(self):
        profile = _msme_profile()
        evidence_bundle = [
            make_evidence_record(
                collector="burn-in-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"flaky_count": 0},
            ),
            make_evidence_record(
                collector="mutmut-mutation", tool="python3",
                category="mutation", status="ok",
                metrics={"mutation_score": 75.0, "mutants_total": 20,
                         "mutants_killed": 15, "mutants_survived": 5},
            ),
        ]
        verdicts = compute_all_verdicts(evidence_bundle, profile, "P1")
        self.assertIn("test_quality", verdicts)
        self.assertIn("mutation", verdicts)
        self.assertEqual(verdicts["test_quality"]["verdict"], "PASS")
        self.assertEqual(verdicts["mutation"]["verdict"], "PASS")

    def test_overall_fail_on_flaky(self):
        profile = _msme_profile()
        evidence_bundle = [
            make_evidence_record(
                collector="burn-in-test-quality", tool="python3",
                category="test_quality", status="ok",
                metrics={"flaky_count": 3},
            ),
            make_evidence_record(
                collector="mutmut-mutation", tool="python3",
                category="mutation", status="ok",
                metrics={"mutation_score": 75.0, "mutants_total": 20,
                         "mutants_killed": 15, "mutants_survived": 5},
            ),
        ]
        verdicts = compute_all_verdicts(evidence_bundle, profile, "P1")
        self.assertEqual(verdicts["test_quality"]["verdict"], "FAIL")
        self.assertEqual(verdicts["mutation"]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify all tests pass**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_burn_in_integration.py -v --tb=short
```

---

### Task 12: Full Test Suite Validation

**Files:** None (verification only)

- [ ] **Step 1: Run all new tests together**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_burn_in.py tests/test_check_hard_wait.py tests/test_check_mutation.py tests/test_check_test_review.py tests/test_collectors_test_quality.py tests/test_collectors_mutation.py tests/test_burn_in_rules.py tests/test_burn_in_integration.py -v --tb=short
```

- [ ] **Step 2: Run the full existing test suite to confirm no regressions**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short
```

- [ ] **Step 3: Run ruff lint check**

```bash
cd skills/bmad-story-automator && python3 -m ruff check src/story_automator/core/checks/burn_in_check.py src/story_automator/core/checks/hard_wait_check.py src/story_automator/core/checks/mutation_check.py src/story_automator/core/checks/test_review_check.py src/story_automator/core/collectors/test_quality.py src/story_automator/core/collectors/mutation.py src/story_automator/core/category_rules.py
```

- [ ] **Step 4: Verify LOC limits**

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/checks/burn_in_check.py skills/bmad-story-automator/src/story_automator/core/checks/hard_wait_check.py skills/bmad-story-automator/src/story_automator/core/checks/mutation_check.py skills/bmad-story-automator/src/story_automator/core/checks/test_review_check.py skills/bmad-story-automator/src/story_automator/core/collectors/test_quality.py skills/bmad-story-automator/src/story_automator/core/collectors/mutation.py
```

All modules should be well under the 500-LOC soft limit.
