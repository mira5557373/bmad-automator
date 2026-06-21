# Collection M5: Core Collectors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement concrete evidence collectors for four §6.2 code-altitude categories — correctness, static, docs, process/DoD — populating the M4 collector framework with real tool wrappers and checker scripts.

**Architecture:** Two kinds of collector. *Tool wrappers* (ruff, mypy, pytest, etc.) construct a shell command via `CollectorConfig.build_cmd` and let the existing `run_collector_with_timeout` runner handle execution, evidence capture, and timeout enforcement. *Logic-based checkers* (presence, coverage threshold, ADR section, traceability) are standalone Python scripts under `core/checks/` invoked via `sys.executable` for cross-platform portability — they print findings to stdout and exit 0 (ok) or 1 (violation). All collectors register into `CollectorRegistry` via a single `register_core_collectors()` entry point in `core/collectors/__init__.py`.

**Tech Stack:** Python 3.11+, stdlib only (no new deps); existing M4 framework (`CollectorConfig`, `CollectorRegistry`, `CollectorOutcome`, `run_collector_with_timeout`, `persist_evidence_record`); `unittest` + `unittest.mock`; subprocess-based checker scripts using stdlib (`os`, `sys`, `json`, `re`).

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Gate telemetry events land in M18.
- **500-LOC soft limit per Python module.** Targets: each collector module ≤ 80, each checker script ≤ 70, each test file ≤ 150.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/<test_file>.py -v` to validate per-task.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform**: checker scripts use `sys.executable` (not bash constructs). Tool-wrapper commands use the tool binary name directly.
- **Checker scripts use stdlib only** — they run as standalone subprocesses and must NOT import from `story_automator`.
- **Encoding safety**: all checker scripts open files with `errors="replace"` to avoid crashes on non-UTF-8 content.
- **npx-based tools**: `collector_doctor.preflight_check` uses `shutil.which(config.tool)`. For npx-invoked tools (tsc, biome, knip, vitest, playwright, docusaurus), the binary may not be in PATH — only accessible via `npx`. Doctor preflight may report "not found" for these; this is expected and non-blocking. Doctor enhancement is deferred.
- **Coverage threshold**: coverage collector uses `profile.matrix.P0.coverage_pct` as a conservative default. The story's actual risk priority is not available to collectors — the adjudicator (M9) will compare coverage metrics against the story-specific risk-required threshold.
- **`core/` has no `__init__.py`** (namespace package). New `collectors/` subpackage gets `__init__.py` (regular package with exports). New `checks/` subpackage gets an empty `__init__.py` for test importability.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/checks/__init__.py` — empty package marker (~0 LOC)
- `skills/bmad-story-automator/src/story_automator/core/checks/presence_check.py` — file-existence checker script (~40 LOC)
- `skills/bmad-story-automator/src/story_automator/core/checks/coverage_check.py` — coverage-threshold checker script (~65 LOC)
- `skills/bmad-story-automator/src/story_automator/core/checks/adr_check.py` — ADR production-readiness checker script (~50 LOC)
- `skills/bmad-story-automator/src/story_automator/core/checks/trace_check.py` — AC↔task↔test traceability checker script (~55 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py` — `register_core_collectors()` entry point (~25 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py` — pytest, vitest, playwright, coverage collectors (~75 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/static.py` — ruff, mypy, tsc, biome, knip collectors (~80 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/docs.py` — doc-presence, docusaurus collectors (~55 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collectors/process.py` — adr, trace collectors (~50 LOC)
- `tests/test_check_presence.py` — presence checker script tests (~70 LOC)
- `tests/test_check_coverage.py` — coverage checker script tests (~100 LOC)
- `tests/test_check_adr.py` — ADR checker script tests (~90 LOC)
- `tests/test_check_trace.py` — trace checker script tests (~90 LOC)
- `tests/test_collectors_docs.py` — docs-category collector tests (~80 LOC)
- `tests/test_collectors_static.py` — static-category collector tests (~130 LOC)
- `tests/test_collectors_correctness.py` — correctness-category collector tests (~120 LOC)
- `tests/test_collectors_process.py` — process-category collector tests (~80 LOC)
- `tests/test_core_collectors.py` — registration + completeness tests (~70 LOC)
- `tests/test_core_collectors_integration.py` — full pipeline integration test (~130 LOC)

**Untouched (explicit):** `core/adjudicator.py`, `core/evidence_io.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/gate_audit.py`, `core/trust_boundary.py`, `core/collector_checkout.py`, `core/collector_config.py`, `core/collector_registry.py`, `core/collector_runner.py`, `core/collector_doctor.py`, `core/diff_scope.py`, `core/product_profile.py`, `core/telemetry_events.py`, `data/profiles/default.json`, `data/profiles/msme-erp.json`.

---

### Task 1: Checker Script Infrastructure + Presence Check

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/__init__.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/presence_check.py`
- Create: `tests/test_check_presence.py`

**Interfaces:**
- Consumes: stdlib only (`os`, `sys`, `json`)
- Produces: `presence_check.main(argv: list[str] | None = None) -> int` — standalone script and importable function. Exit 0 = all files present. Exit 1 = at least one missing. Exit 2 = usage error. Prints `MISSING: <path>` for each missing file, then a summary line.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_check_presence.py`:

```python
from __future__ import annotations

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
_SCRIPT = str(_CHECKS_DIR / "presence_check.py")


class PresenceCheckDirectTests(unittest.TestCase):
    """Test presence_check.main() directly (no subprocess)."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_all_present_returns_zero(self) -> None:
        from story_automator.core.checks.presence_check import main

        Path(self.tmpdir, "a.md").write_text("x", encoding="utf-8")
        result = main([self.tmpdir, '["a.md"]'])
        self.assertEqual(result, 0)

    def test_missing_file_returns_one(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([self.tmpdir, '["gone.md"]'])
        self.assertEqual(result, 1)

    def test_mixed_present_and_missing(self) -> None:
        from story_automator.core.checks.presence_check import main

        Path(self.tmpdir, "exists.md").write_text("x", encoding="utf-8")
        result = main([self.tmpdir, '["exists.md", "gone.md"]'])
        self.assertEqual(result, 1)

    def test_nested_path(self) -> None:
        from story_automator.core.checks.presence_check import main

        nested = Path(self.tmpdir, "docs", "ops")
        nested.mkdir(parents=True)
        (nested / "runbook.md").write_text("x", encoding="utf-8")
        result = main([self.tmpdir, '["docs/ops/runbook.md"]'])
        self.assertEqual(result, 0)

    def test_no_args_returns_two(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([])
        self.assertEqual(result, 2)

    def test_invalid_json_returns_two(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([self.tmpdir, "not-json"])
        self.assertEqual(result, 2)

    def test_non_array_json_returns_two(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([self.tmpdir, '{"a": 1}'])
        self.assertEqual(result, 2)

    def test_empty_list_returns_zero(self) -> None:
        from story_automator.core.checks.presence_check import main

        result = main([self.tmpdir, "[]"])
        self.assertEqual(result, 0)


class PresenceCheckSubprocessTests(unittest.TestCase):
    """Test presence_check.py as a standalone script."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, _SCRIPT, *args],
            capture_output=True, text=True, timeout=10,
        )

    def test_script_exists(self) -> None:
        self.assertTrue(Path(_SCRIPT).is_file(), f"not found: {_SCRIPT}")

    def test_all_present_stdout(self) -> None:
        Path(self.tmpdir, "a.md").write_text("x", encoding="utf-8")
        result = self._run(self.tmpdir, '["a.md"]')
        self.assertEqual(result.returncode, 0)
        self.assertIn("present", result.stdout)

    def test_missing_file_stdout(self) -> None:
        result = self._run(self.tmpdir, '["missing.md"]')
        self.assertEqual(result.returncode, 1)
        self.assertIn("MISSING: missing.md", result.stdout)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_presence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'story_automator.core.checks'`

- [ ] **Step 3: Create the checks package and presence_check script**

Create `skills/bmad-story-automator/src/story_automator/core/checks/__init__.py` (empty file).

Create `skills/bmad-story-automator/src/story_automator/core/checks/presence_check.py`:

```python
"""Check that required files exist in a checkout directory.

Standalone script invoked by the doc-presence collector.
Exit 0 = all present, exit 1 = missing, exit 2 = usage error.
Prints MISSING: <path> for each absent file.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: presence_check.py <checkout> <json_file_list>")
        return 2
    checkout = args[0]
    try:
        required: list[str] = json.loads(args[1])
    except (json.JSONDecodeError, TypeError):
        print(f"invalid file list: {args[1]}")
        return 2
    if not isinstance(required, list) or not all(
        isinstance(f, str) for f in required
    ):
        print("file list must be a JSON string array")
        return 2
    missing = [
        f for f in required
        if not os.path.isfile(os.path.join(checkout, f))
    ]
    for f in missing:
        print(f"MISSING: {f}")
    if missing:
        print(f"{len(missing)} required file(s) missing")
        return 1
    print(f"all {len(required)} required file(s) present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_presence.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/checks/__init__.py \
       skills/bmad-story-automator/src/story_automator/core/checks/presence_check.py \
       tests/test_check_presence.py
git commit -m "feat(collector): add presence checker script for file-existence evidence"
```

---

### Task 2: Collectors Package + Docs Collectors

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/docs.py`
- Create: `tests/test_collectors_docs.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `core.collector_config`; `presence_check.py` from `core.checks`
- Produces: `COLLECTORS: list[CollectorConfig]` (2 entries: `DOC_PRESENCE`, `DOCUSAURUS`). `DOC_PRESENCE.build_cmd` invokes `presence_check.py` with `["docs/operations/gate-troubleshooting.md"]`. `DOCUSAURUS.build_cmd` returns `["npx", "docusaurus", "build"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collectors_docs.py`:

```python
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any


class DocPresenceCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE

        self.assertEqual(DOC_PRESENCE.collector_id, "doc-presence-docs")
        self.assertEqual(DOC_PRESENCE.tool, "python3")
        self.assertEqual(DOC_PRESENCE.category, "docs")
        self.assertTrue(DOC_PRESENCE.deterministic)
        self.assertIn("*.md", DOC_PRESENCE.file_patterns)

    def test_build_cmd_invokes_presence_script(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE

        cmd = DOC_PRESENCE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("presence_check.py", cmd[1])
        self.assertTrue(Path(cmd[1]).is_file(), f"script not found: {cmd[1]}")
        self.assertEqual(cmd[2], "/tmp/checkout")
        files = json.loads(cmd[3])
        self.assertIn("docs/operations/gate-troubleshooting.md", files)

    def test_build_cmd_returns_list_of_strings(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE

        cmd = DOC_PRESENCE.build_cmd("/tmp/co", {"rules": {}})
        self.assertIsInstance(cmd, list)
        self.assertTrue(all(isinstance(s, str) for s in cmd))


class DocusaurusCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.docs import DOCUSAURUS

        self.assertEqual(DOCUSAURUS.collector_id, "docusaurus-docs")
        self.assertEqual(DOCUSAURUS.tool, "docusaurus")
        self.assertEqual(DOCUSAURUS.category, "docs")
        self.assertIsNotNone(DOCUSAURUS.tool_version_cmd)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.docs import DOCUSAURUS

        cmd = DOCUSAURUS.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "docusaurus", "build"])

    def test_file_patterns_include_markdown(self) -> None:
        from story_automator.core.collectors.docs import DOCUSAURUS

        self.assertTrue(
            DOCUSAURUS.file_patterns & {"*.md", "*.mdx"},
            "should match markdown files",
        )


class DocsCollectorListTests(unittest.TestCase):
    def test_collectors_count(self) -> None:
        from story_automator.core.collectors.docs import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)

    def test_all_docs_category(self) -> None:
        from story_automator.core.collectors.docs import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "docs")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.docs import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_docs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'story_automator.core.collectors'`

- [ ] **Step 3: Create the collectors package and docs module**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`:

```python
"""Core evidence collector registration (§6.2).

Populated by Task 10 with register_core_collectors().
"""
```

Create `skills/bmad-story-automator/src/story_automator/core/collectors/docs.py`:

```python
"""Docs-category evidence collectors (§6.2).

PASS rule: docs site builds; API docs generated; runbook present.
Collectors: doc-presence-docs, docusaurus-docs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_REQUIRED_DOC_FILES = [
    "docs/operations/gate-troubleshooting.md",
]


def _doc_presence_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(_REQUIRED_DOC_FILES),
    ]


def _docusaurus_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "docusaurus", "build"]


DOC_PRESENCE = CollectorConfig(
    collector_id="doc-presence-docs",
    tool="python3",
    category="docs",
    build_cmd=_doc_presence_cmd,
    file_patterns=frozenset({"*.md", "*.mdx"}),
)

DOCUSAURUS = CollectorConfig(
    collector_id="docusaurus-docs",
    tool="docusaurus",
    category="docs",
    build_cmd=_docusaurus_cmd,
    tool_version_cmd=("npx", "docusaurus", "--version"),
    file_patterns=frozenset({"*.md", "*.mdx", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [DOC_PRESENCE, DOCUSAURUS]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_docs.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py \
       skills/bmad-story-automator/src/story_automator/core/collectors/docs.py \
       tests/test_collectors_docs.py
git commit -m "feat(collector): add docs-category collectors (presence + docusaurus)"
```

---

### Task 3: Ruff + Mypy Collectors (static/Python)

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/static.py`
- Create: `tests/test_collectors_static.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `core.collector_config`
- Produces: `COLLECTORS: list[CollectorConfig]` (initially 2: `RUFF`, `MYPY`; grows to 5 in Task 4). `RUFF.build_cmd` returns `["ruff", "check", "."]`. `MYPY.build_cmd` returns `["mypy", "."]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collectors_static.py`:

```python
from __future__ import annotations

import unittest
from typing import Any


class RuffCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import RUFF

        self.assertEqual(RUFF.collector_id, "ruff-static")
        self.assertEqual(RUFF.tool, "ruff")
        self.assertEqual(RUFF.category, "static")
        self.assertTrue(RUFF.deterministic)
        self.assertIn("*.py", RUFF.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import RUFF

        cmd = RUFF.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "ruff")
        self.assertIn("check", cmd)
        self.assertIn(".", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.static import RUFF

        self.assertIsNotNone(RUFF.tool_version_cmd)
        self.assertIn("ruff", RUFF.tool_version_cmd)


class MypyCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import MYPY

        self.assertEqual(MYPY.collector_id, "mypy-static")
        self.assertEqual(MYPY.tool, "mypy")
        self.assertEqual(MYPY.category, "static")
        self.assertIn("*.py", MYPY.file_patterns)
        self.assertIn("*.pyi", MYPY.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import MYPY

        cmd = MYPY.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "mypy")
        self.assertIn(".", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.static import MYPY

        self.assertIsNotNone(MYPY.tool_version_cmd)
        self.assertIn("mypy", MYPY.tool_version_cmd)


class StaticCollectorListTests(unittest.TestCase):
    def test_ruff_and_mypy_present(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("ruff-static", ids)
        self.assertIn("mypy-static", ids)

    def test_all_static_category(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "static")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_static.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'story_automator.core.collectors.static'`

- [ ] **Step 3: Create the static collectors module**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/static.py`:

```python
"""Static-analysis evidence collectors (§6.2).

PASS rule: tsc=0, mypy=0, ruff/Biome=0, deadcode ≤ budget.
Collectors: ruff-static, mypy-static (+ tsc, biome, knip added in Task 4).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _ruff_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["ruff", "check", "."]


def _mypy_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["mypy", "."]


RUFF = CollectorConfig(
    collector_id="ruff-static",
    tool="ruff",
    category="static",
    build_cmd=_ruff_cmd,
    tool_version_cmd=("ruff", "--version"),
    file_patterns=frozenset({"*.py"}),
)

MYPY = CollectorConfig(
    collector_id="mypy-static",
    tool="mypy",
    category="static",
    build_cmd=_mypy_cmd,
    tool_version_cmd=("mypy", "--version"),
    file_patterns=frozenset({"*.py", "*.pyi"}),
)

COLLECTORS: list[CollectorConfig] = [RUFF, MYPY]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_static.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/static.py \
       tests/test_collectors_static.py
git commit -m "feat(collector): add ruff + mypy static-analysis collectors"
```

---

### Task 4: tsc + Biome + Knip Collectors (static/TypeScript)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/static.py`
- Modify: `tests/test_collectors_static.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `core.collector_config`
- Produces: adds `TSC`, `BIOME`, `KNIP` to `COLLECTORS` list (total 5). `TSC.build_cmd` returns `["npx", "tsc", "--noEmit"]`. `BIOME.build_cmd` returns `["npx", "@biomejs/biome", "check", "."]`. `KNIP.build_cmd` returns `["npx", "knip"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_collectors_static.py`:

```python
class TscCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import TSC

        self.assertEqual(TSC.collector_id, "tsc-static")
        self.assertEqual(TSC.tool, "tsc")
        self.assertEqual(TSC.category, "static")
        self.assertIn("*.ts", TSC.file_patterns)
        self.assertIn("*.tsx", TSC.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import TSC

        cmd = TSC.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "tsc", "--noEmit"])


class BiomeCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import BIOME

        self.assertEqual(BIOME.collector_id, "biome-static")
        self.assertEqual(BIOME.tool, "biome")
        self.assertEqual(BIOME.category, "static")
        self.assertIn("*.ts", BIOME.file_patterns)
        self.assertIn("*.js", BIOME.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import BIOME

        cmd = BIOME.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "@biomejs/biome", "check", "."])


class KnipCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import KNIP

        self.assertEqual(KNIP.collector_id, "knip-static")
        self.assertEqual(KNIP.tool, "knip")
        self.assertEqual(KNIP.category, "static")

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import KNIP

        cmd = KNIP.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "knip"])


class StaticCollectorFullListTests(unittest.TestCase):
    def test_five_collectors(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        self.assertEqual(len(COLLECTORS), 5)

    def test_all_expected_ids(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "ruff-static", "mypy-static", "tsc-static",
            "biome-static", "knip-static",
        })
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_static.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'TSC'`

- [ ] **Step 3: Add tsc, biome, knip collectors to static.py**

Add to `skills/bmad-story-automator/src/story_automator/core/collectors/static.py` after the `MYPY` definition:

```python
def _tsc_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "tsc", "--noEmit"]


def _biome_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "@biomejs/biome", "check", "."]


def _knip_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "knip"]


TSC = CollectorConfig(
    collector_id="tsc-static",
    tool="tsc",
    category="static",
    build_cmd=_tsc_cmd,
    tool_version_cmd=("npx", "tsc", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx"}),
)

BIOME = CollectorConfig(
    collector_id="biome-static",
    tool="biome",
    category="static",
    build_cmd=_biome_cmd,
    tool_version_cmd=("npx", "@biomejs/biome", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx"}),
)

KNIP = CollectorConfig(
    collector_id="knip-static",
    tool="knip",
    category="static",
    build_cmd=_knip_cmd,
    tool_version_cmd=("npx", "knip", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx", "*.json"}),
)
```

Update the `COLLECTORS` list at the bottom:

```python
COLLECTORS: list[CollectorConfig] = [RUFF, MYPY, TSC, BIOME, KNIP]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_static.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/static.py \
       tests/test_collectors_static.py
git commit -m "feat(collector): add tsc + biome + knip static collectors"
```

---

### Task 5: Pytest Collector (correctness)

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py`
- Create: `tests/test_collectors_correctness.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `core.collector_config`
- Produces: `COLLECTORS: list[CollectorConfig]` (initially 1: `PYTEST`; grows to 4 in Tasks 6-7). `PYTEST.build_cmd` returns `["pytest", "--tb=short", "-q"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collectors_correctness.py`:

```python
from __future__ import annotations

import unittest
from typing import Any


class PytestCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.correctness import PYTEST

        self.assertEqual(PYTEST.collector_id, "pytest-correctness")
        self.assertEqual(PYTEST.tool, "pytest")
        self.assertEqual(PYTEST.category, "correctness")
        self.assertTrue(PYTEST.deterministic)
        self.assertIn("*.py", PYTEST.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.correctness import PYTEST

        cmd = PYTEST.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "pytest")
        self.assertIn("--tb=short", cmd)
        self.assertIn("-q", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.correctness import PYTEST

        self.assertIsNotNone(PYTEST.tool_version_cmd)
        self.assertIn("pytest", PYTEST.tool_version_cmd)


class CorrectnessCollectorListTests(unittest.TestCase):
    def test_pytest_present(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("pytest-correctness", ids)

    def test_all_correctness_category(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "correctness")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_correctness.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create the correctness collectors module**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py`:

```python
"""Correctness-category evidence collectors (§6.2).

PASS rule: all tiers green, 0 regressions, line/branch >= risk-required.
Collectors: pytest-correctness (+ vitest, playwright, coverage added later).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _pytest_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["pytest", "--tb=short", "-q"]


PYTEST = CollectorConfig(
    collector_id="pytest-correctness",
    tool="pytest",
    category="correctness",
    build_cmd=_pytest_cmd,
    tool_version_cmd=("pytest", "--version"),
    file_patterns=frozenset({"*.py"}),
)

COLLECTORS: list[CollectorConfig] = [PYTEST]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_correctness.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py \
       tests/test_collectors_correctness.py
git commit -m "feat(collector): add pytest correctness collector"
```

---

### Task 6: Vitest + Playwright Collectors (correctness)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py`
- Modify: `tests/test_collectors_correctness.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `core.collector_config`
- Produces: adds `VITEST`, `PLAYWRIGHT` to `COLLECTORS` list (total 3). `VITEST.build_cmd` returns `["npx", "vitest", "run"]`. `PLAYWRIGHT.build_cmd` returns `["npx", "playwright", "test"]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_collectors_correctness.py`:

```python
class VitestCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.correctness import VITEST

        self.assertEqual(VITEST.collector_id, "vitest-correctness")
        self.assertEqual(VITEST.tool, "vitest")
        self.assertEqual(VITEST.category, "correctness")
        self.assertIn("*.ts", VITEST.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.correctness import VITEST

        cmd = VITEST.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "vitest", "run"])


class PlaywrightCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.correctness import PLAYWRIGHT

        self.assertEqual(PLAYWRIGHT.collector_id, "playwright-correctness")
        self.assertEqual(PLAYWRIGHT.tool, "playwright")
        self.assertEqual(PLAYWRIGHT.category, "correctness")
        self.assertIn("*.ts", PLAYWRIGHT.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.correctness import PLAYWRIGHT

        cmd = PLAYWRIGHT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "playwright", "test"])


class CorrectnessThreeCollectorsTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("pytest-correctness", ids)
        self.assertIn("vitest-correctness", ids)
        self.assertIn("playwright-correctness", ids)
```

- [ ] **Step 2: Run tests to verify the new tests fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_correctness.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'VITEST'`

- [ ] **Step 3: Add vitest and playwright collectors**

Add to `skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py` after `PYTEST`:

```python
def _vitest_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "vitest", "run"]


def _playwright_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "playwright", "test"]


VITEST = CollectorConfig(
    collector_id="vitest-correctness",
    tool="vitest",
    category="correctness",
    build_cmd=_vitest_cmd,
    tool_version_cmd=("npx", "vitest", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx"}),
)

PLAYWRIGHT = CollectorConfig(
    collector_id="playwright-correctness",
    tool="playwright",
    category="correctness",
    build_cmd=_playwright_cmd,
    tool_version_cmd=("npx", "playwright", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx"}),
)
```

Update `COLLECTORS`:

```python
COLLECTORS: list[CollectorConfig] = [PYTEST, VITEST, PLAYWRIGHT]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collectors_correctness.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py \
       tests/test_collectors_correctness.py
git commit -m "feat(collector): add vitest + playwright correctness collectors"
```

---

### Task 7: Coverage Threshold Checker + Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/coverage_check.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py`
- Create: `tests/test_check_coverage.py`
- Modify: `tests/test_collectors_correctness.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `core.collector_config`; `profile.matrix.P0.coverage_pct` for threshold
- Produces: `coverage_check.main(argv) -> int` — parses coverage JSON (pytest-cov format: `{"totals": {"percent_covered": N}}`, istanbul format: `{"total": {"lines": {"pct": N}}}`). Exit 0 = meets threshold. Exit 1 = below or no data. `COVERAGE` collector config added to `COLLECTORS` (total 4).

- [ ] **Step 1: Write the coverage check tests**

Create `tests/test_check_coverage.py`:

```python
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest


class CoverageCheckDirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, filename: str, data: dict) -> None:
        path = os.path.join(self.tmpdir, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_pytest_cov_above_threshold(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self._write_json("coverage.json", {"totals": {"percent_covered": 95.0}})
        self.assertEqual(main([self.tmpdir, "80"]), 0)

    def test_pytest_cov_below_threshold(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self._write_json("coverage.json", {"totals": {"percent_covered": 50.0}})
        self.assertEqual(main([self.tmpdir, "80"]), 1)

    def test_pytest_cov_exact_threshold(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self._write_json("coverage.json", {"totals": {"percent_covered": 80.0}})
        self.assertEqual(main([self.tmpdir, "80"]), 0)

    def test_istanbul_format(self) -> None:
        from story_automator.core.checks.coverage_check import main

        data = {"total": {"lines": {"pct": 92.5}}}
        self._write_json("coverage/coverage-summary.json", data)
        self.assertEqual(main([self.tmpdir, "80"]), 0)

    def test_istanbul_below_threshold(self) -> None:
        from story_automator.core.checks.coverage_check import main

        data = {"total": {"lines": {"pct": 40.0}}}
        self._write_json("coverage/coverage-summary.json", data)
        self.assertEqual(main([self.tmpdir, "80"]), 1)

    def test_no_coverage_data_returns_one(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self.assertEqual(main([self.tmpdir, "80"]), 1)

    def test_unparseable_data_returns_one(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self._write_json("coverage.json", {"unknown": "format"})
        self.assertEqual(main([self.tmpdir, "80"]), 1)

    def test_no_args_returns_two(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self.assertEqual(main([]), 2)

    def test_invalid_threshold_returns_two(self) -> None:
        from story_automator.core.checks.coverage_check import main

        self.assertEqual(main([self.tmpdir, "abc"]), 2)
```

- [ ] **Step 2: Write the coverage collector tests**

Append to `tests/test_collectors_correctness.py`:

```python
import json
import sys
from pathlib import Path


class CoverageCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.correctness import COVERAGE

        self.assertEqual(COVERAGE.collector_id, "coverage-correctness")
        self.assertEqual(COVERAGE.tool, "python3")
        self.assertEqual(COVERAGE.category, "correctness")

    def test_build_cmd_invokes_coverage_script(self) -> None:
        from story_automator.core.collectors.correctness import COVERAGE

        profile: dict[str, Any] = {
            "matrix": {"P0": {"coverage_pct": 90, "levels": ["unit"]}},
        }
        cmd = COVERAGE.build_cmd("/tmp/co", profile)
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("coverage_check.py", cmd[1])
        self.assertTrue(Path(cmd[1]).is_file())
        self.assertEqual(cmd[2], "/tmp/co")
        self.assertEqual(cmd[3], "90")

    def test_build_cmd_default_threshold(self) -> None:
        from story_automator.core.collectors.correctness import COVERAGE

        cmd = COVERAGE.build_cmd("/tmp/co", {})
        self.assertEqual(cmd[3], "80")

    def test_build_cmd_uses_p0_coverage(self) -> None:
        from story_automator.core.collectors.correctness import COVERAGE

        profile: dict[str, Any] = {
            "matrix": {"P0": {"coverage_pct": 100, "levels": ["unit"]}},
        }
        cmd = COVERAGE.build_cmd("/tmp/co", profile)
        self.assertEqual(cmd[3], "100")


class CorrectnessFourCollectorsTests(unittest.TestCase):
    def test_four_collectors(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        self.assertEqual(len(COLLECTORS), 4)
        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "pytest-correctness", "vitest-correctness",
            "playwright-correctness", "coverage-correctness",
        })
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_coverage.py tests/test_collectors_correctness.py -v`
Expected: FAIL — modules not found

- [ ] **Step 4: Create the coverage check script**

Create `skills/bmad-story-automator/src/story_automator/core/checks/coverage_check.py`:

```python
"""Check that code coverage meets the required threshold.

Standalone script invoked by the coverage-correctness collector.
Looks for coverage data in common locations (pytest-cov, istanbul/vitest).
Exit 0 = threshold met, exit 1 = below threshold or no data, exit 2 = usage.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import json
import os
import sys

_CANDIDATES = [
    "coverage.json",
    ".coverage.json",
    os.path.join("htmlcov", "status.json"),
    os.path.join("coverage", "coverage-summary.json"),
]


def _find_coverage_file(checkout: str) -> str | None:
    for candidate in _CANDIDATES:
        path = os.path.join(checkout, candidate)
        if os.path.isfile(path):
            return path
    return None


def _extract_coverage_pct(data: dict) -> float | None:
    if "totals" in data:
        pct = data["totals"].get("percent_covered")
        if isinstance(pct, (int, float)):
            return float(pct)
    if "total" in data:
        lines = data.get("total", {}).get("lines", {})
        pct = lines.get("pct")
        if isinstance(pct, (int, float)):
            return float(pct)
    return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) < 2:
        print("usage: coverage_check.py <checkout> <threshold_pct>")
        return 2
    checkout = args[0]
    try:
        threshold = int(args[1])
    except ValueError:
        print(f"invalid threshold: {args[1]}")
        return 2
    coverage_file = _find_coverage_file(checkout)
    if not coverage_file:
        print("no coverage data found")
        return 1
    try:
        with open(coverage_file, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"failed to read coverage data: {exc}")
        return 1
    pct = _extract_coverage_pct(data)
    if pct is None:
        print(f"could not parse coverage from {os.path.basename(coverage_file)}")
        return 1
    print(f"coverage: {pct:.1f}% (threshold: {threshold}%)")
    if pct < threshold:
        print(f"BELOW THRESHOLD: {pct:.1f}% < {threshold}%")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Add coverage collector to correctness.py**

Add to `skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py`. Add imports at the top:

```python
import sys
from pathlib import Path
```

Add after `PLAYWRIGHT`:

```python
_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _coverage_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    matrix = profile.get("matrix") or {}
    p0 = matrix.get("P0") or {}
    threshold = p0.get("coverage_pct", 80)
    return [
        sys.executable,
        str(_CHECKS_DIR / "coverage_check.py"),
        checkout,
        str(int(threshold)),
    ]


COVERAGE = CollectorConfig(
    collector_id="coverage-correctness",
    tool="python3",
    category="correctness",
    build_cmd=_coverage_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx"}),
)
```

Update `COLLECTORS`:

```python
COLLECTORS: list[CollectorConfig] = [PYTEST, VITEST, PLAYWRIGHT, COVERAGE]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_coverage.py tests/test_collectors_correctness.py -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/checks/coverage_check.py \
       skills/bmad-story-automator/src/story_automator/core/collectors/correctness.py \
       tests/test_check_coverage.py \
       tests/test_collectors_correctness.py
git commit -m "feat(collector): add coverage threshold checker + correctness collector"
```

---

### Task 8: ADR Production-Readiness Checker + Process Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/adr_check.py`
- Create: `skills/bmad-story-automator/src/story_automator/core/collectors/process.py`
- Create: `tests/test_check_adr.py`
- Create: `tests/test_collectors_process.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `core.collector_config`
- Produces: `adr_check.main(argv) -> int` — scans `docs/architecture/decisions/*.md` for `## Production-Readiness` heading. Exit 0 = all have it (or no ADR dir). Exit 1 = missing. `ADR` collector config in `COLLECTORS: list[CollectorConfig]` (initially 1, grows to 2 in Task 9).

- [ ] **Step 1: Write the ADR check tests**

Create `tests/test_check_adr.py`:

```python
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path


class AdrCheckDirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.adr_dir = os.path.join(
            self.tmpdir, "docs", "architecture", "decisions",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_adr(self, name: str, content: str) -> None:
        os.makedirs(self.adr_dir, exist_ok=True)
        with open(os.path.join(self.adr_dir, name), "w", encoding="utf-8") as f:
            f.write(content)

    def test_all_adrs_have_section(self) -> None:
        from story_automator.core.checks.adr_check import main

        self._write_adr("ADR-001.md", "# ADR\n## Production-Readiness\nok\n")
        self._write_adr("ADR-002.md", "# ADR\n## Production Readiness\nok\n")
        self.assertEqual(main([self.tmpdir]), 0)

    def test_missing_section_returns_one(self) -> None:
        from story_automator.core.checks.adr_check import main

        self._write_adr("ADR-001.md", "# ADR\n## Context\nstuff\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_mixed_adrs(self) -> None:
        from story_automator.core.checks.adr_check import main

        self._write_adr("ADR-001.md", "# ADR\n## Production-Readiness\nok\n")
        self._write_adr("ADR-002.md", "# ADR\n## Context\nmissing\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_no_adr_dir_returns_zero(self) -> None:
        from story_automator.core.checks.adr_check import main

        self.assertEqual(main([self.tmpdir]), 0)

    def test_empty_adr_dir_returns_zero(self) -> None:
        from story_automator.core.checks.adr_check import main

        os.makedirs(self.adr_dir)
        self.assertEqual(main([self.tmpdir]), 0)

    def test_case_insensitive_heading(self) -> None:
        from story_automator.core.checks.adr_check import main

        self._write_adr("ADR-001.md", "# ADR\n### production-readiness\nok\n")
        self.assertEqual(main([self.tmpdir]), 0)

    def test_no_args_returns_two(self) -> None:
        from story_automator.core.checks.adr_check import main

        self.assertEqual(main([]), 2)
```

- [ ] **Step 2: Write the process collector tests**

Create `tests/test_collectors_process.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


class AdrCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.process import ADR

        self.assertEqual(ADR.collector_id, "adr-process")
        self.assertEqual(ADR.tool, "python3")
        self.assertEqual(ADR.category, "process")
        self.assertIn("*.md", ADR.file_patterns)

    def test_build_cmd_invokes_adr_script(self) -> None:
        from story_automator.core.collectors.process import ADR

        cmd = ADR.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("adr_check.py", cmd[1])
        self.assertTrue(Path(cmd[1]).is_file())
        self.assertEqual(cmd[2], "/tmp/checkout")


class ProcessCollectorListTests(unittest.TestCase):
    def test_adr_present(self) -> None:
        from story_automator.core.collectors.process import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("adr-process", ids)

    def test_all_process_category(self) -> None:
        from story_automator.core.collectors.process import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "process")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_adr.py tests/test_collectors_process.py -v`
Expected: FAIL — modules not found

- [ ] **Step 4: Create the ADR check script**

Create `skills/bmad-story-automator/src/story_automator/core/checks/adr_check.py`:

```python
"""Check ADR files for Production-Readiness section.

Standalone script invoked by the adr-process collector.
Scans docs/architecture/decisions/*.md for a heading matching
"Production-Readiness" or "Production Readiness" (case-insensitive).
Exit 0 = all ADRs have it (or no ADR dir/files). Exit 1 = missing.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import re
import sys

_SECTION_RE = re.compile(
    r"^#+\s+Production[- ]Readiness", re.MULTILINE | re.IGNORECASE
)
_ADR_RELDIR = os.path.join("docs", "architecture", "decisions")


def _has_prod_readiness_section(content: str) -> bool:
    return bool(_SECTION_RE.search(content))


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: adr_check.py <checkout>")
        return 2
    checkout = args[0]
    adr_dir = os.path.join(checkout, _ADR_RELDIR)
    if not os.path.isdir(adr_dir):
        print(f"no ADR directory: {_ADR_RELDIR}")
        return 0
    adr_files = sorted(f for f in os.listdir(adr_dir) if f.endswith(".md"))
    if not adr_files:
        print("no ADR files found")
        return 0
    missing: list[str] = []
    for adr_file in adr_files:
        path = os.path.join(adr_dir, adr_file)
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        if not _has_prod_readiness_section(content):
            missing.append(adr_file)
            print(f"MISSING Production-Readiness: {adr_file}")
    if missing:
        print(f"{len(missing)} ADR(s) missing Production-Readiness section")
        return 1
    print(f"all {len(adr_files)} ADR(s) have Production-Readiness section")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Create the process collectors module**

Create `skills/bmad-story-automator/src/story_automator/core/collectors/process.py`:

```python
"""Process/DoD evidence collectors (§6.2).

PASS rule: ADR Production-Readiness section present;
           ACs<->tasks<->tests traced; File List complete.
Collectors: adr-process (+ trace-process added in Task 9).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _adr_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "adr_check.py"),
        checkout,
    ]


ADR = CollectorConfig(
    collector_id="adr-process",
    tool="python3",
    category="process",
    build_cmd=_adr_cmd,
    file_patterns=frozenset({"*.md"}),
)

COLLECTORS: list[CollectorConfig] = [ADR]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_adr.py tests/test_collectors_process.py -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/checks/adr_check.py \
       skills/bmad-story-automator/src/story_automator/core/collectors/process.py \
       tests/test_check_adr.py \
       tests/test_collectors_process.py
git commit -m "feat(collector): add ADR production-readiness checker + process collector"
```

---

### Task 9: Trace Checker + Process Collector

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/checks/trace_check.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/process.py`
- Create: `tests/test_check_trace.py`
- Modify: `tests/test_collectors_process.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `core.collector_config`
- Produces: `trace_check.main(argv) -> int` — scans `_bmad/stories/*.md` for `## File List` heading. Exit 0 = all have it (or no story dir). Exit 1 = missing. `TRACE` collector added to process `COLLECTORS` (total 2).

- [ ] **Step 1: Write the trace check tests**

Create `tests/test_check_trace.py`:

```python
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path


class TraceCheckDirectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.story_dir = os.path.join(self.tmpdir, "_bmad", "stories")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_story(self, name: str, content: str) -> None:
        os.makedirs(self.story_dir, exist_ok=True)
        with open(os.path.join(self.story_dir, name), "w", encoding="utf-8") as f:
            f.write(content)

    def test_all_stories_have_file_list(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n## File List\n- a.py\n")
        self._write_story("S002.md", "# Story\n## File List\n- b.py\n")
        self.assertEqual(main([self.tmpdir]), 0)

    def test_missing_file_list_returns_one(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n## Tasks\n- task\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_mixed_stories(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n## File List\n- a.py\n")
        self._write_story("S002.md", "# Story\n## Tasks\n- task\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_no_story_dir_returns_zero(self) -> None:
        from story_automator.core.checks.trace_check import main

        self.assertEqual(main([self.tmpdir]), 0)

    def test_empty_story_dir_returns_zero(self) -> None:
        from story_automator.core.checks.trace_check import main

        os.makedirs(self.story_dir)
        self.assertEqual(main([self.tmpdir]), 0)

    def test_case_insensitive_heading(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n### file list\n- a.py\n")
        self.assertEqual(main([self.tmpdir]), 0)

    def test_no_args_returns_two(self) -> None:
        from story_automator.core.checks.trace_check import main

        self.assertEqual(main([]), 2)

    def test_empty_file_list_returns_one(self) -> None:
        from story_automator.core.checks.trace_check import main

        self._write_story("S001.md", "# Story\n## File List\n\n## Tasks\n")
        self.assertEqual(main([self.tmpdir]), 1)

    def test_non_md_files_ignored(self) -> None:
        from story_automator.core.checks.trace_check import main

        os.makedirs(self.story_dir, exist_ok=True)
        with open(os.path.join(self.story_dir, "notes.txt"), "w") as f:
            f.write("no file list here")
        self.assertEqual(main([self.tmpdir]), 0)
```

- [ ] **Step 2: Write the trace collector tests**

Append to `tests/test_collectors_process.py`:

```python
class TraceCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.process import TRACE

        self.assertEqual(TRACE.collector_id, "trace-process")
        self.assertEqual(TRACE.tool, "python3")
        self.assertEqual(TRACE.category, "process")
        self.assertIn("*.md", TRACE.file_patterns)

    def test_build_cmd_invokes_trace_script(self) -> None:
        from story_automator.core.collectors.process import TRACE

        cmd = TRACE.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("trace_check.py", cmd[1])
        self.assertTrue(Path(cmd[1]).is_file())
        self.assertEqual(cmd[2], "/tmp/checkout")


class ProcessTwoCollectorsTests(unittest.TestCase):
    def test_two_collectors(self) -> None:
        from story_automator.core.collectors.process import COLLECTORS

        self.assertEqual(len(COLLECTORS), 2)
        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {"adr-process", "trace-process"})
```

- [ ] **Step 3: Run tests to verify the new tests fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_trace.py tests/test_collectors_process.py -v`
Expected: new tests FAIL — modules/names not found

- [ ] **Step 4: Create the trace check script**

Create `skills/bmad-story-automator/src/story_automator/core/checks/trace_check.py`:

```python
"""Check AC/task/test traceability and File List completeness.

Standalone script invoked by the trace-process collector.
Scans _bmad/stories/*.md for a "File List" heading section.
Exit 0 = all pass (or no story dir). Exit 1 = issues found.

Stdlib only — no story_automator imports.
"""
from __future__ import annotations

import os
import re
import sys

_FILE_LIST_RE = re.compile(
    r"^#+\s+File\s+List", re.MULTILINE | re.IGNORECASE
)
_STORY_RELDIR = os.path.join("_bmad", "stories")


def _check_story_file(path: str) -> list[str]:
    issues: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    filename = os.path.basename(path)
    match = _FILE_LIST_RE.search(content)
    if not match:
        issues.append(f"MISSING File List: {filename}")
    else:
        after = content[match.end():]
        next_heading = re.search(r"^#+\s", after, re.MULTILINE)
        section = after[:next_heading.start()] if next_heading else after
        items = [ln for ln in section.strip().splitlines() if ln.strip().startswith("-")]
        if not items:
            issues.append(f"EMPTY File List: {filename}")
    return issues


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: trace_check.py <checkout>")
        return 2
    checkout = args[0]
    story_dir = os.path.join(checkout, _STORY_RELDIR)
    if not os.path.isdir(story_dir):
        print(f"no story directory: {_STORY_RELDIR}")
        return 0
    story_files = sorted(
        f for f in os.listdir(story_dir) if f.endswith(".md")
    )
    if not story_files:
        print("no story files found")
        return 0
    all_issues: list[str] = []
    for story_file in story_files:
        path = os.path.join(story_dir, story_file)
        all_issues.extend(_check_story_file(path))
    for issue in all_issues:
        print(issue)
    if all_issues:
        print(f"{len(all_issues)} traceability issue(s) found")
        return 1
    print(f"all {len(story_files)} story file(s) pass traceability checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Add trace collector to process.py**

Add to `skills/bmad-story-automator/src/story_automator/core/collectors/process.py` after `ADR`:

```python
def _trace_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "trace_check.py"),
        checkout,
    ]


TRACE = CollectorConfig(
    collector_id="trace-process",
    tool="python3",
    category="process",
    build_cmd=_trace_cmd,
    file_patterns=frozenset({"*.md"}),
)
```

Update `COLLECTORS`:

```python
COLLECTORS: list[CollectorConfig] = [ADR, TRACE]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_check_trace.py tests/test_collectors_process.py -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/checks/trace_check.py \
       skills/bmad-story-automator/src/story_automator/core/collectors/process.py \
       tests/test_check_trace.py \
       tests/test_collectors_process.py
git commit -m "feat(collector): add trace checker + process/DoD collector"
```

---

### Task 10: Registration Entry Point

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`
- Create: `tests/test_core_collectors.py`

**Interfaces:**
- Consumes: `COLLECTORS` lists from `collectors.correctness`, `collectors.static`, `collectors.docs`, `collectors.process`; `CollectorRegistry` from `core.collector_registry`
- Produces: `register_core_collectors(registry: CollectorRegistry) -> None` — registers all 13 collectors into the given registry. `CORE_COLLECTOR_IDS: frozenset[str]` — the set of all 13 IDs for completeness checking.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_core_collectors.py`:

```python
from __future__ import annotations

import unittest


_EXPECTED_IDS = frozenset({
    "ruff-static", "mypy-static", "tsc-static", "biome-static", "knip-static",
    "pytest-correctness", "vitest-correctness", "playwright-correctness",
    "coverage-correctness",
    "doc-presence-docs", "docusaurus-docs",
    "adr-process", "trace-process",
})

_EXPECTED_CATEGORIES = frozenset({
    "correctness", "static", "docs", "process",
})


class RegisterCoreCollectorsTests(unittest.TestCase):
    def test_registers_all_collectors(self) -> None:
        from story_automator.core.collector_registry import CollectorRegistry
        from story_automator.core.collectors import register_core_collectors

        reg = CollectorRegistry()
        register_core_collectors(reg)
        registered_ids = {c.collector_id for c in reg.all_collectors()}
        self.assertEqual(registered_ids, _EXPECTED_IDS)

    def test_covers_four_categories(self) -> None:
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
        self.assertEqual(len(reg.all_collectors()), 13)

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_core_collectors.py -v`
Expected: FAIL — `ImportError: cannot import name 'register_core_collectors'`

- [ ] **Step 3: Implement the registration entry point**

Replace `skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py`:

```python
"""Core evidence collector registration (§6.2).

Registers all built-in collectors for correctness, static, docs, process.
"""
from __future__ import annotations

from ..collector_registry import CollectorRegistry
from .correctness import COLLECTORS as _CORRECTNESS
from .docs import COLLECTORS as _DOCS
from .process import COLLECTORS as _PROCESS
from .static import COLLECTORS as _STATIC

__all__ = ["register_core_collectors", "CORE_COLLECTOR_IDS"]

_ALL = _CORRECTNESS + _DOCS + _PROCESS + _STATIC

CORE_COLLECTOR_IDS: frozenset[str] = frozenset(
    c.collector_id for c in _ALL
)


def register_core_collectors(registry: CollectorRegistry) -> None:
    """Register all built-in collectors into the given registry."""
    for config in _ALL:
        registry.register(config)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_core_collectors.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collectors/__init__.py \
       tests/test_core_collectors.py
git commit -m "feat(collector): add register_core_collectors entry point for 13 collectors"
```

---

### Task 11: Full Pipeline Integration Test

**Files:**
- Create: `tests/test_core_collectors_integration.py`

**Interfaces:**
- Consumes: `register_core_collectors` from `core.collectors`; `CollectorRegistry` from `core.collector_registry`; `run_single_collector` from `core.collector_runner`; `CollectorConfig`, `CollectorOutcome` from `core.collector_config`; `make_evidence_record` from `core.gate_schema`; `persist_evidence_record`, `load_evidence_bundle`, `compute_evidence_bundle_hash` from `core.evidence_io`
- Produces: end-to-end validation that registered core collectors produce valid evidence records when run through the existing M4 pipeline

- [ ] **Step 1: Write the integration test**

Create `tests/test_core_collectors_integration.py`:

```python
"""Integration test: core collectors -> registry -> runner -> evidence.

Verifies that the concrete core collectors register correctly, produce
valid build_cmd output, and when run with synthetic success/failure tools
through the M4 pipeline, produce well-formed evidence records.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_config import CollectorConfig, CollectorOutcome
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.collectors import (
    CORE_COLLECTOR_IDS,
    register_core_collectors,
)
from story_automator.core.evidence_io import (
    compute_evidence_bundle_hash,
    load_evidence_bundle,
    persist_evidence_record,
)
from story_automator.core.gate_schema import (
    VALID_EVIDENCE_STATUSES,
    validate_evidence_record,
)


class CoreCollectorBuildCmdTests(unittest.TestCase):
    """Every registered collector must produce a valid command list."""

    def setUp(self) -> None:
        self.registry = CollectorRegistry()
        register_core_collectors(self.registry)
        self.profile: dict[str, Any] = {
            "matrix": {
                "P0": {"coverage_pct": 80, "levels": ["unit"]},
                "P1": {"coverage_pct": 60, "levels": ["unit"]},
                "P2": {"coverage_pct": 30, "levels": ["smoke"]},
                "P3": {"coverage_pct": 10, "levels": ["smoke"]},
            },
            "categories": {
                "code": ["correctness", "static", "docs", "process"],
            },
            "categories_na": [],
            "rules": {},
        }

    def test_all_build_cmds_return_string_lists(self) -> None:
        for config in self.registry.all_collectors():
            cmd = config.build_cmd("/tmp/checkout", self.profile)
            self.assertIsInstance(cmd, list, f"{config.collector_id}")
            self.assertTrue(
                all(isinstance(s, str) for s in cmd),
                f"{config.collector_id} returned non-string elements",
            )
            self.assertTrue(len(cmd) > 0, f"{config.collector_id} empty cmd")

    def test_checker_scripts_exist(self) -> None:
        for config in self.registry.all_collectors():
            cmd = config.build_cmd("/tmp/checkout", self.profile)
            if cmd[0] == sys.executable and len(cmd) > 1:
                script = cmd[1]
                self.assertTrue(
                    Path(script).is_file(),
                    f"{config.collector_id}: script not found: {script}",
                )


class CoreCollectorProfileFilteringTests(unittest.TestCase):
    """Profile-driven filtering works with real collector configs."""

    def setUp(self) -> None:
        self.registry = CollectorRegistry()
        register_core_collectors(self.registry)

    def test_all_four_categories_when_all_active(self) -> None:
        profile: dict[str, Any] = {
            "categories": {
                "code": ["correctness", "static", "docs", "process"],
            },
            "categories_na": [],
        }
        applicable = self.registry.applicable(profile)
        cats = {c.category for c in applicable}
        self.assertEqual(cats, {"correctness", "static", "docs", "process"})

    def test_single_category(self) -> None:
        profile: dict[str, Any] = {
            "categories": {"code": ["correctness"]},
            "categories_na": [],
        }
        applicable = self.registry.applicable(profile)
        self.assertTrue(all(c.category == "correctness" for c in applicable))
        self.assertTrue(len(applicable) > 0)

    def test_empty_profile_returns_nothing(self) -> None:
        profile: dict[str, Any] = {
            "categories": {},
            "categories_na": [],
        }
        applicable = self.registry.applicable(profile)
        self.assertEqual(len(applicable), 0)


class CoreCollectorEvidenceTests(unittest.TestCase):
    """Checker-script collectors produce valid evidence via the pipeline."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = self.tmpdir
        self.gate_id = "test-gate-001"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": ""}, clear=False)
    def test_presence_collector_pass(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE
        from story_automator.core.collector_runner import run_single_collector

        checkout = tempfile.mkdtemp()
        try:
            runbook = Path(checkout, "docs", "operations")
            runbook.mkdir(parents=True)
            (runbook / "gate-troubleshooting.md").write_text("# Runbook\n")
            profile: dict[str, Any] = {"timeouts": {"docs": 30}}
            outcome = run_single_collector(
                DOC_PRESENCE, checkout, profile,
                self.gate_id, self.project_root,
            )
            ev = outcome.evidence
            self.assertEqual(ev["status"], "ok")
            self.assertEqual(ev["collector"], "doc-presence-docs")
            self.assertEqual(ev["tool"], "python3")
            self.assertEqual(ev["category"], "docs")
            self.assertEqual(ev["exit_code"], 0)
            self.assertTrue(ev["deterministic"])
            validate_evidence_record(ev)
        finally:
            shutil.rmtree(checkout, ignore_errors=True)

    @patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": ""}, clear=False)
    def test_presence_collector_violation(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE
        from story_automator.core.collector_runner import run_single_collector

        checkout = tempfile.mkdtemp()
        try:
            profile: dict[str, Any] = {"timeouts": {"docs": 30}}
            outcome = run_single_collector(
                DOC_PRESENCE, checkout, profile,
                self.gate_id, self.project_root,
            )
            self.assertEqual(outcome.evidence["status"], "violation")
            self.assertTrue(
                any("MISSING" in f for f in outcome.evidence["findings"]),
            )
            validate_evidence_record(outcome.evidence)
        finally:
            shutil.rmtree(checkout, ignore_errors=True)

    @patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": ""}, clear=False)
    def test_evidence_persistence_round_trip(self) -> None:
        from story_automator.core.collectors.docs import DOC_PRESENCE
        from story_automator.core.collector_runner import run_single_collector

        checkout = tempfile.mkdtemp()
        try:
            profile: dict[str, Any] = {"timeouts": {"docs": 30}}
            outcome = run_single_collector(
                DOC_PRESENCE, checkout, profile,
                self.gate_id, self.project_root,
            )
            self.assertIsNotNone(outcome.persisted_path)
            bundle = load_evidence_bundle(self.project_root, self.gate_id)
            self.assertEqual(len(bundle), 1)
            self.assertEqual(bundle[0]["collector"], "doc-presence-docs")
            bundle_hash = compute_evidence_bundle_hash(bundle)
            self.assertTrue(len(bundle_hash) > 0)
        finally:
            shutil.rmtree(checkout, ignore_errors=True)
```

- [ ] **Step 2: Run integration tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_core_collectors_integration.py -v`
Expected: all tests PASS

- [ ] **Step 3: Run the full test suite to confirm no regressions**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short`
Expected: all tests PASS (including all existing M1-M4 tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_core_collectors_integration.py
git commit -m "test(collector): add core collectors pipeline integration tests"
```
