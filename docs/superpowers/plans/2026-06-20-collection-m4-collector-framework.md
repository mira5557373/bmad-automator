# Collection M4: Collector Framework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Tier 2 evidence collector framework (spec §4) — the infrastructure that configures, registers, scopes, preflights, and orchestrates subprocess-based evidence collectors against a fresh checkout, producing normalized evidence bundles for the Adjudicator.

**Architecture:** Five new modules in `core/`. `CollectorConfig` (frozen dataclass) declares each collector's identity, tool, category, and command builder. `CollectorRegistry` stores configs and filters them by profile (active categories, `categories_na`, per-tool kill-switch). `DiffScope` runs `git diff` to determine which categories are affected by recent changes, enabling the ≤10 min wall-clock target (§18). `CollectorDoctor` preflights tool availability via `shutil.which`. `CollectorRunner` orchestrates the full gate collector loop: creates a fresh checkout (§7), iterates applicable collectors, runs each via the existing `run_collector_with_timeout` (§6.4), persists evidence via `persist_evidence_record`, and emits `EvidenceCollectedAudit` events. All write operations are trust-boundary-guarded (§7). Individual collector configs (semgrep, ruff, etc.) are NOT part of this milestone — only the framework and test-only reference configs.

**Tech Stack:** Python 3.11+, stdlib + `filelock` + `psutil`; existing `adjudicator.run_collector_with_timeout`, `evidence_io.persist_evidence_record`, `gate_schema.make_evidence_record`, `gate_audit.emit_gate_audit`, `collector_checkout.collector_checkout`, `trust_boundary.assert_host_context`, `product_profile.resolve_timeout`; `unittest` + `unittest.mock`.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only.
- **Do NOT touch `core/telemetry_events.py`.** Dedicated gate telemetry events land in M18.
- **500-LOC soft limit per Python module.** Target: `collector_config.py` ≤ 80, `collector_registry.py` ≤ 140, `diff_scope.py` ≤ 150, `collector_doctor.py` ≤ 100, `collector_runner.py` ≤ 200.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/<test_file>.py -v` to validate per-task.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform**: subprocess commands in test reference collectors must use `sys.executable` (not bash-only constructs).

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/collector_config.py` — `CollectorConfig` frozen dataclass + `CollectorOutcome` frozen dataclass (~80 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collector_registry.py` — `CollectorRegistry` class with registration, lookup, and profile-aware filtering (~140 LOC)
- `skills/bmad-story-automator/src/story_automator/core/diff_scope.py` — git diff parsing, file→category mapping, scope computation (~150 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collector_doctor.py` — preflight tool availability checks (~100 LOC)
- `skills/bmad-story-automator/src/story_automator/core/collector_runner.py` — single collector execution + full gate loop orchestration (~200 LOC)
- `tests/test_collector_config.py` — unit tests for config dataclasses (~120 LOC)
- `tests/test_collector_registry.py` — unit tests for registry (~220 LOC)
- `tests/test_diff_scope.py` — unit tests for diff scoping (~200 LOC)
- `tests/test_collector_doctor.py` — unit tests for doctor (~120 LOC)
- `tests/test_collector_runner.py` — unit tests for runner (~300 LOC)
- `tests/test_collector_integration.py` — end-to-end pipeline integration test (~200 LOC)

**Untouched (explicit):** `core/adjudicator.py`, `core/evidence_io.py`, `core/gate_schema.py`, `core/gate_rules.py`, `core/gate_audit.py`, `core/trust_boundary.py`, `core/collector_checkout.py`, `core/product_profile.py`, `core/profile_bridge.py`, `core/telemetry_events.py`.

---

### Task 1: CollectorConfig and CollectorOutcome Dataclasses

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collector_config.py`
- Create: `tests/test_collector_config.py`

**Interfaces:**
- Consumes: `dataclasses`, `pathlib.Path`, `typing`
- Produces: `CollectorConfig(collector_id: str, tool: str, category: str, build_cmd: Callable[[str, dict[str, Any]], list[str]], tool_version_cmd: tuple[str, ...] | None = None, file_patterns: frozenset[str] = frozenset(), deterministic: bool = True)`, `CollectorOutcome(config: CollectorConfig, evidence: dict[str, Any], persisted_path: Path | None = None)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collector_config.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from story_automator.core.collector_config import (
    CollectorConfig,
    CollectorOutcome,
)


def _echo_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "print('ok')"]


class CollectorConfigCreationTests(unittest.TestCase):
    def test_create_minimal(self) -> None:
        cfg = CollectorConfig(
            collector_id="ruff-static",
            tool="ruff",
            category="static",
            build_cmd=_echo_cmd,
        )
        self.assertEqual(cfg.collector_id, "ruff-static")
        self.assertEqual(cfg.tool, "ruff")
        self.assertEqual(cfg.category, "static")
        self.assertIsNone(cfg.tool_version_cmd)
        self.assertEqual(cfg.file_patterns, frozenset())
        self.assertTrue(cfg.deterministic)

    def test_create_full(self) -> None:
        cfg = CollectorConfig(
            collector_id="semgrep-security",
            tool="semgrep",
            category="security",
            build_cmd=_echo_cmd,
            tool_version_cmd=("semgrep", "--version"),
            file_patterns=frozenset({"*.py", "*.ts"}),
            deterministic=True,
        )
        self.assertEqual(cfg.tool_version_cmd, ("semgrep", "--version"))
        self.assertEqual(cfg.file_patterns, frozenset({"*.py", "*.ts"}))

    def test_frozen(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        with self.assertRaises(AttributeError):
            cfg.collector_id = "mutated"  # type: ignore[misc]

    def test_build_cmd_callable(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        cmd = cfg.build_cmd("/checkout", {})
        self.assertEqual(cmd, [sys.executable, "-c", "print('ok')"])

    def test_equality_excludes_build_cmd(self) -> None:
        def other_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            return ["other"]

        a = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=_echo_cmd,
        )
        b = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=other_cmd,
        )
        self.assertEqual(a, b)

    def test_hash_excludes_build_cmd(self) -> None:
        def other_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            return ["other"]

        a = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=_echo_cmd,
        )
        b = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=other_cmd,
        )
        self.assertEqual(hash(a), hash(b))

    def test_different_ids_not_equal(self) -> None:
        a = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=_echo_cmd,
        )
        b = CollectorConfig(
            collector_id="y", tool="t", category="c", build_cmd=_echo_cmd,
        )
        self.assertNotEqual(a, b)


class CollectorOutcomeTests(unittest.TestCase):
    def test_create_without_path(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        evidence = {"status": "ok", "category": "c"}
        outcome = CollectorOutcome(config=cfg, evidence=evidence)
        self.assertEqual(outcome.config.collector_id, "a")
        self.assertEqual(outcome.evidence["status"], "ok")
        self.assertIsNone(outcome.persisted_path)

    def test_create_with_path(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        outcome = CollectorOutcome(
            config=cfg,
            evidence={"status": "ok"},
            persisted_path=Path("/tmp/evidence.json"),
        )
        self.assertEqual(outcome.persisted_path, Path("/tmp/evidence.json"))

    def test_frozen(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        outcome = CollectorOutcome(config=cfg, evidence={})
        with self.assertRaises(AttributeError):
            outcome.evidence = {}  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_config.py -v`
Expected: ModuleNotFoundError — `collector_config` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/collector_config.py`:

```python
"""Collector configuration and outcome dataclasses.

CollectorConfig declares the identity, tool, category, and command builder
for an evidence collector.  CollectorOutcome wraps the evidence record with
the config that produced it and the path where it was persisted.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "CollectorConfig",
    "CollectorOutcome",
]

CmdBuilder = Callable[[str, dict[str, Any]], list[str]]


@dataclasses.dataclass(frozen=True)
class CollectorConfig:
    """Declares a single evidence collector."""

    collector_id: str
    tool: str
    category: str
    build_cmd: CmdBuilder = dataclasses.field(compare=False, hash=False, repr=False)
    tool_version_cmd: tuple[str, ...] | None = None
    file_patterns: frozenset[str] = dataclasses.field(default_factory=frozenset)
    deterministic: bool = True


@dataclasses.dataclass(frozen=True)
class CollectorOutcome:
    """Result of running a single collector: config + evidence + path."""

    config: CollectorConfig
    evidence: dict[str, Any]
    persisted_path: Path | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_config.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collector_config.py tests/test_collector_config.py
git commit -m "feat(gate): add CollectorConfig and CollectorOutcome dataclasses

CollectorConfig declares collector identity, tool, category, command
builder, and file patterns.  CollectorOutcome wraps evidence with the
config that produced it.  build_cmd excluded from eq/hash (spec §4).

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 2: CollectorRegistry — Registration and Lookup

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collector_registry.py`
- Create: `tests/test_collector_registry.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `collector_config.py`
- Produces: `CollectorRegistry` class with `register(config: CollectorConfig) -> None`, `get(collector_id: str) -> CollectorConfig | None`, `get_for_category(category: str) -> list[CollectorConfig]`, `all_categories() -> set[str]`, `all_collectors() -> list[CollectorConfig]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collector_registry.py`:

```python
from __future__ import annotations

import sys
import unittest
from typing import Any

from story_automator.core.collector_config import CollectorConfig
from story_automator.core.collector_registry import CollectorRegistry


def _noop_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "pass"]


def _make_config(
    collector_id: str = "test-collector",
    tool: str = "test",
    category: str = "correctness",
) -> CollectorConfig:
    return CollectorConfig(
        collector_id=collector_id,
        tool=tool,
        category=category,
        build_cmd=_noop_cmd,
    )


class RegistrationTests(unittest.TestCase):
    def test_register_and_get(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("ruff-static", "ruff", "static")
        reg.register(cfg)
        self.assertEqual(reg.get("ruff-static"), cfg)

    def test_get_returns_none_for_unknown(self) -> None:
        reg = CollectorRegistry()
        self.assertIsNone(reg.get("nonexistent"))

    def test_register_duplicate_raises(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("dup", "t", "c")
        reg.register(cfg)
        with self.assertRaises(ValueError) as ctx:
            reg.register(cfg)
        self.assertIn("dup", str(ctx.exception))

    def test_all_collectors(self) -> None:
        reg = CollectorRegistry()
        a = _make_config("a", "ta", "ca")
        b = _make_config("b", "tb", "cb")
        reg.register(a)
        reg.register(b)
        result = reg.all_collectors()
        ids = [c.collector_id for c in result]
        self.assertIn("a", ids)
        self.assertIn("b", ids)

    def test_all_collectors_sorted(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("z", "t", "cat-b"))
        reg.register(_make_config("a", "t", "cat-a"))
        result = reg.all_collectors()
        self.assertEqual(
            [(c.category, c.collector_id) for c in result],
            [("cat-a", "a"), ("cat-b", "z")],
        )


class CategoryLookupTests(unittest.TestCase):
    def test_get_for_category(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("ruff-static", "ruff", "static")
        reg.register(cfg)
        result = reg.get_for_category("static")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].collector_id, "ruff-static")

    def test_get_for_category_empty(self) -> None:
        reg = CollectorRegistry()
        self.assertEqual(reg.get_for_category("static"), [])

    def test_multiple_collectors_per_category(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("semgrep-sec", "semgrep", "security"))
        reg.register(_make_config("trivy-sec", "trivy", "security"))
        result = reg.get_for_category("security")
        self.assertEqual(len(result), 2)
        ids = {c.collector_id for c in result}
        self.assertEqual(ids, {"semgrep-sec", "trivy-sec"})

    def test_all_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "t", "static"))
        reg.register(_make_config("b", "t", "security"))
        reg.register(_make_config("c", "t", "static"))
        self.assertEqual(reg.all_categories(), {"static", "security"})

    def test_all_categories_empty(self) -> None:
        reg = CollectorRegistry()
        self.assertEqual(reg.all_categories(), set())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_registry.py -v`
Expected: ModuleNotFoundError — `collector_registry` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/collector_registry.py`:

```python
"""Collector registry — stores, looks up, and filters collector configs.

Maps collector_id → CollectorConfig and category → [CollectorConfig].
Profile-aware filtering (categories, categories_na, kill-switch) added
in a subsequent task.
"""
from __future__ import annotations

from typing import Any

from .collector_config import CollectorConfig

__all__ = [
    "CollectorRegistry",
]


class CollectorRegistry:
    """Registry of evidence collector configurations."""

    def __init__(self) -> None:
        self._by_id: dict[str, CollectorConfig] = {}
        self._by_category: dict[str, list[str]] = {}

    def register(self, config: CollectorConfig) -> None:
        if config.collector_id in self._by_id:
            raise ValueError(
                f"collector already registered: {config.collector_id!r}"
            )
        self._by_id[config.collector_id] = config
        self._by_category.setdefault(config.category, []).append(
            config.collector_id
        )

    def get(self, collector_id: str) -> CollectorConfig | None:
        return self._by_id.get(collector_id)

    def get_for_category(self, category: str) -> list[CollectorConfig]:
        ids = self._by_category.get(category, [])
        return [self._by_id[cid] for cid in sorted(ids)]

    def all_categories(self) -> set[str]:
        return set(self._by_category.keys())

    def all_collectors(self) -> list[CollectorConfig]:
        return sorted(
            self._by_id.values(),
            key=lambda c: (c.category, c.collector_id),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_registry.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collector_registry.py tests/test_collector_registry.py
git commit -m "feat(gate): add CollectorRegistry — registration and lookup

CollectorRegistry stores configs by id and category, supports
multi-tool-per-category, returns deterministically sorted results.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 3: CollectorRegistry — Profile-Aware Filtering and Kill-Switch

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collector_registry.py`
- Modify: `tests/test_collector_registry.py`

**Interfaces:**
- Consumes: `CollectorConfig`, profile dict with `categories: {code: [...], system: [...]}`, `categories_na: [...]`, `rules: {category: {disabled_tools: [...]}}`
- Produces: `CollectorRegistry.applicable(profile: dict[str, Any]) -> list[CollectorConfig]`, `CollectorRegistry.is_kill_switched(config: CollectorConfig, profile: dict[str, Any]) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_collector_registry.py`:

```python
class ProfileFilteringTests(unittest.TestCase):
    def _profile(
        self,
        code_cats: list[str] | None = None,
        system_cats: list[str] | None = None,
        na: list[str] | None = None,
        rules: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "categories": {
                "code": code_cats or ["correctness", "static", "security"],
                "system": system_cats or [],
            },
            "categories_na": na or [],
            "rules": rules or {},
        }

    def test_applicable_returns_matching_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "t", "static"))
        reg.register(_make_config("b", "t", "security"))
        reg.register(_make_config("c", "t", "performance"))
        profile = self._profile(code_cats=["static", "security"])
        result = reg.applicable(profile)
        ids = [c.collector_id for c in result]
        self.assertIn("a", ids)
        self.assertIn("b", ids)
        self.assertNotIn("c", ids)

    def test_applicable_excludes_na_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "t", "static"))
        reg.register(_make_config("b", "t", "accessibility"))
        profile = self._profile(
            code_cats=["static", "accessibility"],
            na=["accessibility"],
        )
        result = reg.applicable(profile)
        ids = [c.collector_id for c in result]
        self.assertIn("a", ids)
        self.assertNotIn("b", ids)

    def test_applicable_sorted_by_category_then_id(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("z-sec", "t", "security"))
        reg.register(_make_config("a-sec", "t", "security"))
        reg.register(_make_config("m-cor", "t", "correctness"))
        profile = self._profile(code_cats=["correctness", "security"])
        result = reg.applicable(profile)
        self.assertEqual(
            [(c.category, c.collector_id) for c in result],
            [("correctness", "m-cor"), ("security", "a-sec"), ("security", "z-sec")],
        )

    def test_applicable_empty_registry(self) -> None:
        reg = CollectorRegistry()
        self.assertEqual(reg.applicable(self._profile()), [])

    def test_applicable_no_matching_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "t", "performance"))
        profile = self._profile(code_cats=["static"])
        self.assertEqual(reg.applicable(profile), [])

    def test_applicable_includes_system_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "t", "reliability"))
        profile = self._profile(
            code_cats=[], system_cats=["reliability"],
        )
        result = reg.applicable(profile)
        self.assertEqual(len(result), 1)


class KillSwitchTests(unittest.TestCase):
    def test_not_kill_switched_by_default(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("a", "ruff", "static")
        profile: dict[str, Any] = {"rules": {}}
        self.assertFalse(reg.is_kill_switched(cfg, profile))

    def test_kill_switched_when_tool_disabled(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("a", "ruff", "static")
        profile: dict[str, Any] = {
            "rules": {"static": {"disabled_tools": ["ruff"]}},
        }
        self.assertTrue(reg.is_kill_switched(cfg, profile))

    def test_not_kill_switched_for_other_tool(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("a", "mypy", "static")
        profile: dict[str, Any] = {
            "rules": {"static": {"disabled_tools": ["ruff"]}},
        }
        self.assertFalse(reg.is_kill_switched(cfg, profile))

    def test_kill_switch_integrated_with_applicable(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("ruff-static", "ruff", "static"))
        reg.register(_make_config("mypy-static", "mypy", "static"))
        profile: dict[str, Any] = {
            "categories": {"code": ["static"], "system": []},
            "categories_na": [],
            "rules": {"static": {"disabled_tools": ["ruff"]}},
        }
        result = reg.applicable(profile)
        ids = [c.collector_id for c in result]
        self.assertNotIn("ruff-static", ids)
        self.assertIn("mypy-static", ids)

    def test_missing_rules_section(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("a", "ruff", "static")
        self.assertFalse(reg.is_kill_switched(cfg, {}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_registry.py::ProfileFilteringTests tests/test_collector_registry.py::KillSwitchTests -v`
Expected: AttributeError — `applicable` and `is_kill_switched` not yet defined.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/bmad-story-automator/src/story_automator/core/collector_registry.py`, appending methods to the `CollectorRegistry` class:

```python
    def is_kill_switched(
        self, config: CollectorConfig, profile: dict[str, Any]
    ) -> bool:
        """Check if a collector's tool is disabled in profile rules."""
        rules = (profile.get("rules") or {}).get(config.category) or {}
        disabled_tools = rules.get("disabled_tools") or []
        return config.tool in disabled_tools

    def applicable(
        self, profile: dict[str, Any]
    ) -> list[CollectorConfig]:
        """Return collectors whose category is active and not kill-switched.

        Active = listed in profile.categories (any tier) AND NOT in
        profile.categories_na.  Kill-switched = tool listed in
        profile.rules.<category>.disabled_tools.
        """
        active: set[str] = set()
        for tier_cats in (profile.get("categories") or {}).values():
            if isinstance(tier_cats, list):
                active.update(tier_cats)
        na = set(profile.get("categories_na") or [])
        active -= na
        result: list[CollectorConfig] = []
        for config in self._by_id.values():
            if config.category not in active:
                continue
            if self.is_kill_switched(config, profile):
                continue
            result.append(config)
        return sorted(result, key=lambda c: (c.category, c.collector_id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_registry.py -v`
Expected: All 21 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collector_registry.py tests/test_collector_registry.py
git commit -m "feat(gate): add profile-aware filtering and kill-switch to registry

applicable() filters by profile categories, excludes categories_na,
and respects per-tool disabled_tools in profile rules.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 4: DiffScope — Changed File Detection

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/diff_scope.py`
- Create: `tests/test_diff_scope.py`

**Interfaces:**
- Consumes: `subprocess.run`, `pathlib.Path`
- Produces: `DiffScopeError(RuntimeError)`, `compute_changed_files(project_root: str | Path, baseline_sha: str, current_sha: str = "HEAD") -> set[str]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_diff_scope.py`:

```python
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from story_automator.core.diff_scope import (
    DiffScopeError,
    compute_changed_files,
)


def _init_repo(path: Path) -> str:
    """Create a git repo with one commit, return SHA."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "initial.txt").write_text("init\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _add_commit(path: Path, filename: str, content: str) -> str:
    """Add a file and commit, return SHA."""
    (path / filename).write_text(content)
    subprocess.run(
        ["git", "-C", str(path), "add", filename],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", f"add {filename}"],
        capture_output=True, check=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


class ComputeChangedFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-diff-test-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.base_sha = _init_repo(self.repo)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_detects_added_file(self) -> None:
        sha2 = _add_commit(self.repo, "new.py", "x = 1\n")
        changed = compute_changed_files(self.repo, self.base_sha, sha2)
        self.assertIn("new.py", changed)

    def test_detects_modified_file(self) -> None:
        (self.repo / "initial.txt").write_text("modified\n")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", "."],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-m", "modify"],
            capture_output=True, check=True,
        )
        sha2 = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        changed = compute_changed_files(self.repo, self.base_sha, sha2)
        self.assertIn("initial.txt", changed)

    def test_empty_diff(self) -> None:
        changed = compute_changed_files(
            self.repo, self.base_sha, self.base_sha,
        )
        self.assertEqual(changed, set())

    def test_multiple_files(self) -> None:
        _add_commit(self.repo, "a.py", "a\n")
        sha2 = _add_commit(self.repo, "b.ts", "b\n")
        changed = compute_changed_files(self.repo, self.base_sha, sha2)
        self.assertIn("a.py", changed)
        self.assertIn("b.ts", changed)

    def test_invalid_baseline_raises(self) -> None:
        with self.assertRaises(DiffScopeError):
            compute_changed_files(self.repo, "deadbeef" * 5)

    def test_not_a_git_repo_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(DiffScopeError):
                compute_changed_files(td, "abc123")

    def test_default_current_sha_is_head(self) -> None:
        _add_commit(self.repo, "head.py", "h\n")
        changed = compute_changed_files(self.repo, self.base_sha)
        self.assertIn("head.py", changed)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_diff_scope.py -v`
Expected: ModuleNotFoundError — `diff_scope` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/diff_scope.py`:

```python
"""Diff-based evidence scoping (§18 performance target).

Determines which files changed between a baseline and current commit,
maps file patterns to evidence categories, and computes the set of
categories that need re-evaluation.  Enables the ≤10 min wall-clock
target by skipping unchanged categories.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

__all__ = [
    "DiffScopeError",
    "compute_changed_files",
]

_GIT_TIMEOUT = 30


class DiffScopeError(RuntimeError):
    """Raised when diff-scope computation fails."""


def compute_changed_files(
    project_root: str | Path,
    baseline_sha: str,
    current_sha: str = "HEAD",
) -> set[str]:
    """Return file paths changed between baseline and current commit."""
    root = str(Path(project_root).resolve())
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{baseline_sha}..{current_sha}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise DiffScopeError("git diff timed out") from exc
    except FileNotFoundError as exc:
        raise DiffScopeError("git not found") from exc
    if result.returncode != 0:
        raise DiffScopeError(
            f"git diff failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_diff_scope.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/diff_scope.py tests/test_diff_scope.py
git commit -m "feat(gate): add diff scope — changed file detection

compute_changed_files runs git diff to determine which files changed
between a baseline and current commit, enabling diff-scoped gate
evaluation per spec §18 performance target.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 5: DiffScope — File→Category Mapping and Scope Computation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/diff_scope.py`
- Modify: `tests/test_diff_scope.py`

**Interfaces:**
- Consumes: `compute_changed_files` from Task 4
- Produces: `DEFAULT_FILE_CATEGORY_MAP: dict[str, frozenset[str]]`, `affected_categories(changed_files: set[str], file_category_map: dict[str, frozenset[str]] | None = None) -> set[str]`, `compute_diff_scope(project_root: str | Path, baseline_sha: str, current_sha: str = "HEAD", file_category_map: dict[str, frozenset[str]] | None = None) -> set[str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_diff_scope.py`:

```python
from story_automator.core.diff_scope import (
    DEFAULT_FILE_CATEGORY_MAP,
    affected_categories,
    compute_diff_scope,
)


class AffectedCategoriesTests(unittest.TestCase):
    def test_python_file_maps_to_categories(self) -> None:
        result = affected_categories({"src/app.py"})
        self.assertIn("correctness", result)
        self.assertIn("static", result)
        self.assertIn("security", result)

    def test_typescript_file_maps_to_categories(self) -> None:
        result = affected_categories({"components/Button.tsx"})
        self.assertIn("correctness", result)
        self.assertIn("accessibility", result)

    def test_sql_file_maps_to_migrations(self) -> None:
        result = affected_categories({"db/migrate/001.sql"})
        self.assertIn("migrations", result)

    def test_markdown_maps_to_docs(self) -> None:
        result = affected_categories({"docs/README.md"})
        self.assertIn("docs", result)

    def test_unknown_extension_returns_empty(self) -> None:
        result = affected_categories({"data/binary.bin"})
        self.assertEqual(result, set())

    def test_multiple_files_union_categories(self) -> None:
        result = affected_categories({"app.py", "schema.sql"})
        self.assertIn("correctness", result)
        self.assertIn("migrations", result)

    def test_custom_map_overrides_default(self) -> None:
        custom: dict[str, frozenset[str]] = {
            "*.txt": frozenset({"custom"}),
        }
        result = affected_categories({"readme.txt"}, custom)
        self.assertEqual(result, {"custom"})

    def test_default_map_is_not_empty(self) -> None:
        self.assertGreater(len(DEFAULT_FILE_CATEGORY_MAP), 0)

    def test_path_based_pattern_matching(self) -> None:
        result = affected_categories({"Dockerfile"})
        self.assertIn("security", result)
        self.assertIn("supply_chain", result)

    def test_nested_path_matches_extension(self) -> None:
        result = affected_categories({"src/deep/nested/module.py"})
        self.assertIn("correctness", result)


class ComputeDiffScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-scope-test-")
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.base_sha = _init_repo(self.repo)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scope_includes_affected_categories(self) -> None:
        _add_commit(self.repo, "app.py", "x = 1\n")
        scope = compute_diff_scope(self.repo, self.base_sha)
        self.assertIn("correctness", scope)
        self.assertIn("static", scope)

    def test_scope_empty_when_no_changes(self) -> None:
        scope = compute_diff_scope(
            self.repo, self.base_sha, self.base_sha,
        )
        self.assertEqual(scope, set())

    def test_scope_with_custom_map(self) -> None:
        _add_commit(self.repo, "data.csv", "a,b\n")
        custom: dict[str, frozenset[str]] = {
            "*.csv": frozenset({"data_quality"}),
        }
        scope = compute_diff_scope(
            self.repo, self.base_sha, file_category_map=custom,
        )
        self.assertEqual(scope, {"data_quality"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_diff_scope.py::AffectedCategoriesTests tests/test_diff_scope.py::ComputeDiffScopeTests -v`
Expected: ImportError — `DEFAULT_FILE_CATEGORY_MAP` etc. not yet defined.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/bmad-story-automator/src/story_automator/core/diff_scope.py`, updating `__all__` and adding imports:

```python
import fnmatch

__all__ = [
    "DiffScopeError",
    "compute_changed_files",
    "DEFAULT_FILE_CATEGORY_MAP",
    "affected_categories",
    "compute_diff_scope",
]

DEFAULT_FILE_CATEGORY_MAP: dict[str, frozenset[str]] = {
    "*.py": frozenset({"correctness", "static", "security"}),
    "*.pyi": frozenset({"static"}),
    "*.ts": frozenset({"correctness", "static", "security"}),
    "*.tsx": frozenset({"correctness", "static", "security", "accessibility"}),
    "*.js": frozenset({"correctness", "static", "security"}),
    "*.jsx": frozenset({"correctness", "static", "security", "accessibility"}),
    "*.sql": frozenset({"migrations", "security"}),
    "*.tf": frozenset({"security", "compliance"}),
    "*.hcl": frozenset({"security", "compliance"}),
    "*.md": frozenset({"docs"}),
    "*.yaml": frozenset({"invariants", "compliance"}),
    "*.yml": frozenset({"invariants", "compliance"}),
    "Dockerfile": frozenset({"security", "supply_chain"}),
    "Dockerfile.*": frozenset({"security", "supply_chain"}),
    "*.lock": frozenset({"security", "supply_chain"}),
}


def _matches_pattern(filepath: str, pattern: str) -> bool:
    """Match a file path against a glob pattern.

    Patterns containing '/' match the full path.
    Patterns without '/' match only the filename (basename).
    """
    if "/" in pattern:
        return fnmatch.fnmatch(filepath, pattern)
    name = filepath.rsplit("/", maxsplit=1)[-1]
    return fnmatch.fnmatch(name, pattern)


def affected_categories(
    changed_files: set[str],
    file_category_map: dict[str, frozenset[str]] | None = None,
) -> set[str]:
    """Map changed files to the set of affected evidence categories."""
    mapping = file_category_map if file_category_map is not None else DEFAULT_FILE_CATEGORY_MAP
    categories: set[str] = set()
    for filepath in changed_files:
        for pattern, cats in mapping.items():
            if _matches_pattern(filepath, pattern):
                categories.update(cats)
    return categories


def compute_diff_scope(
    project_root: str | Path,
    baseline_sha: str,
    current_sha: str = "HEAD",
    file_category_map: dict[str, frozenset[str]] | None = None,
) -> set[str]:
    """Compute categories affected by changes since baseline.

    §18: enables diff-scoped gate evaluation for ≤10 min wall-clock.
    Returns empty set when no files changed.
    """
    changed = compute_changed_files(project_root, baseline_sha, current_sha)
    if not changed:
        return set()
    return affected_categories(changed, file_category_map)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_diff_scope.py -v`
Expected: All 20 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/diff_scope.py tests/test_diff_scope.py
git commit -m "feat(gate): add file→category mapping and diff scope computation

DEFAULT_FILE_CATEGORY_MAP maps file extensions to evidence categories.
compute_diff_scope combines git diff + mapping to determine which
categories need re-evaluation (spec §18 performance target).

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 6: CollectorDoctor — Preflight Checks

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collector_doctor.py`
- Create: `tests/test_collector_doctor.py`

**Interfaces:**
- Consumes: `CollectorConfig` from `collector_config.py`, `CollectorRegistry.applicable()` from `collector_registry.py`, `shutil.which`, `subprocess.run`
- Produces: `DoctorResult(tool: str, available: bool, version: str, message: str)`, `check_collector_available(config: CollectorConfig) -> DoctorResult`, `preflight_check(registry: CollectorRegistry, profile: dict[str, Any]) -> tuple[bool, list[DoctorResult]]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collector_doctor.py`:

```python
from __future__ import annotations

import sys
import unittest
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_config import CollectorConfig
from story_automator.core.collector_doctor import (
    DoctorResult,
    check_collector_available,
    preflight_check,
)
from story_automator.core.collector_registry import CollectorRegistry


def _noop_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "pass"]


def _make_config(
    collector_id: str = "test",
    tool: str = "python3",
    category: str = "correctness",
    version_cmd: tuple[str, ...] | None = None,
) -> CollectorConfig:
    return CollectorConfig(
        collector_id=collector_id,
        tool=tool,
        category=category,
        build_cmd=_noop_cmd,
        tool_version_cmd=version_cmd,
    )


class CheckCollectorAvailableTests(unittest.TestCase):
    def test_available_tool(self) -> None:
        cfg = _make_config(tool="python3")
        result = check_collector_available(cfg)
        self.assertTrue(result.available)
        self.assertEqual(result.tool, "python3")
        self.assertEqual(result.message, "ok")

    def test_unavailable_tool(self) -> None:
        cfg = _make_config(tool="nonexistent-tool-xyz-999")
        result = check_collector_available(cfg)
        self.assertFalse(result.available)
        self.assertIn("not found", result.message)

    def test_version_cmd_populates_version(self) -> None:
        cfg = _make_config(
            tool="python3",
            version_cmd=(sys.executable, "--version"),
        )
        result = check_collector_available(cfg)
        self.assertTrue(result.available)
        self.assertIn("Python", result.version)

    def test_no_version_cmd_leaves_version_empty(self) -> None:
        cfg = _make_config(tool="python3")
        result = check_collector_available(cfg)
        self.assertEqual(result.version, "")

    def test_version_cmd_failure_still_available(self) -> None:
        cfg = _make_config(
            tool="python3",
            version_cmd=(sys.executable, "-c", "import sys; sys.exit(1)"),
        )
        result = check_collector_available(cfg)
        self.assertTrue(result.available)
        self.assertEqual(result.version, "")

    def test_result_is_frozen(self) -> None:
        result = DoctorResult(
            tool="t", available=True, version="1.0", message="ok",
        )
        with self.assertRaises(AttributeError):
            result.tool = "mutated"  # type: ignore[misc]


class PreflightCheckTests(unittest.TestCase):
    def _profile(self, cats: list[str]) -> dict[str, Any]:
        return {
            "categories": {"code": cats, "system": []},
            "categories_na": [],
            "rules": {},
        }

    def test_all_available(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "python3", "correctness"))
        ok, results = preflight_check(reg, self._profile(["correctness"]))
        self.assertTrue(ok)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].available)

    def test_some_unavailable(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "python3", "correctness"))
        reg.register(_make_config("b", "nonexistent-xyz", "security"))
        ok, results = preflight_check(
            reg, self._profile(["correctness", "security"]),
        )
        self.assertFalse(ok)
        unavailable = [r for r in results if not r.available]
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].tool, "nonexistent-xyz")

    def test_empty_registry(self) -> None:
        reg = CollectorRegistry()
        ok, results = preflight_check(reg, self._profile(["correctness"]))
        self.assertTrue(ok)
        self.assertEqual(results, [])

    def test_skips_non_applicable_collectors(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "nonexistent-xyz", "performance"))
        ok, results = preflight_check(reg, self._profile(["correctness"]))
        self.assertTrue(ok)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_doctor.py -v`
Expected: ModuleNotFoundError — `collector_doctor` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/collector_doctor.py`:

```python
"""Collector preflight checks — verify tool availability before gate runs.

Checks that each applicable collector's binary is available via
shutil.which and optionally retrieves version info.
"""
from __future__ import annotations

import dataclasses
import shutil
import subprocess
from typing import Any

from .collector_config import CollectorConfig
from .collector_registry import CollectorRegistry

__all__ = [
    "DoctorResult",
    "check_collector_available",
    "preflight_check",
]

_VERSION_TIMEOUT = 10


@dataclasses.dataclass(frozen=True)
class DoctorResult:
    """Result of a single tool availability check."""

    tool: str
    available: bool
    version: str
    message: str


def check_collector_available(config: CollectorConfig) -> DoctorResult:
    """Check if a collector's tool binary is available in PATH."""
    if not shutil.which(config.tool):
        return DoctorResult(
            tool=config.tool,
            available=False,
            version="",
            message=f"{config.tool} not found in PATH",
        )
    version = ""
    if config.tool_version_cmd:
        version = _get_tool_version(config.tool_version_cmd)
    return DoctorResult(
        tool=config.tool,
        available=True,
        version=version,
        message="ok",
    )


def _get_tool_version(cmd: tuple[str, ...]) -> str:
    """Best-effort version string extraction."""
    try:
        result = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return ""


def preflight_check(
    registry: CollectorRegistry,
    profile: dict[str, Any],
) -> tuple[bool, list[DoctorResult]]:
    """Run preflight checks for all applicable collectors.

    Returns (all_ok, list_of_results).  Skips collectors not
    applicable to the given profile.
    """
    applicable = registry.applicable(profile)
    results = [check_collector_available(c) for c in applicable]
    all_ok = all(r.available for r in results)
    return all_ok, results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_doctor.py -v`
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collector_doctor.py tests/test_collector_doctor.py
git commit -m "feat(gate): add collector doctor — preflight tool checks

DoctorResult + check_collector_available + preflight_check verify
that the product toolchain binaries are available before starting
the gate collector loop.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 7: CollectorRunner — Single Collector Execution

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/collector_runner.py`
- Create: `tests/test_collector_runner.py`

**Interfaces:**
- Consumes: `CollectorConfig`, `CollectorOutcome` from `collector_config.py`; `run_collector_with_timeout`, `resolve_timeout` from `adjudicator.py`; `persist_evidence_record` from `evidence_io.py`; `make_evidence_record` from `gate_schema.py`; `emit_gate_audit`, `EvidenceCollectedAudit` from `gate_audit.py`; `assert_host_context` from `trust_boundary.py`
- Produces: `run_single_collector(config: CollectorConfig, checkout_path: str, profile: dict[str, Any], gate_id: str, project_root: str | Path, *, audit_policy: dict[str, Any] | None = None, audit_path: Path | None = None) -> CollectorOutcome`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_collector_runner.py`:

```python
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_config import (
    CollectorConfig,
    CollectorOutcome,
)
from story_automator.core.collector_runner import run_single_collector


def _ok_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "print('all good')"]


def _fail_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "import sys; print('bad'); sys.exit(1)"]


def _slow_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "import time; time.sleep(60)"]


def _error_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    raise ValueError("cmd builder exploded")


def _host_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("STORY_AUTOMATOR_CHILD", None)
    return env


def _profile(timeout: int = 10) -> dict[str, Any]:
    return {"timeouts": {"correctness": timeout}}


class RunSingleCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-runner-test-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        (self.project_root / "_bmad" / "gate" / "evidence").mkdir(parents=True)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ok_collector(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-ok",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertIsInstance(outcome, CollectorOutcome)
        self.assertEqual(outcome.evidence["status"], "ok")
        self.assertEqual(outcome.config.collector_id, "test-ok")
        self.assertIsNotNone(outcome.persisted_path)
        self.assertTrue(outcome.persisted_path.exists())

    def test_failing_collector(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-fail",
            tool="python3",
            category="correctness",
            build_cmd=_fail_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertEqual(outcome.evidence["status"], "violation")
        self.assertGreater(len(outcome.evidence.get("findings", [])), 0)

    def test_timeout_collector(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-timeout",
            tool="python3",
            category="correctness",
            build_cmd=_slow_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(timeout=1),
                "gate-001", self.project_root,
            )
        self.assertEqual(outcome.evidence["status"], "timeout")

    def test_build_cmd_error(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-error",
            tool="python3",
            category="correctness",
            build_cmd=_error_cmd,
        )
        with patch.dict(os.environ, _host_env(), clear=True):
            outcome = run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertEqual(outcome.evidence["status"], "error")
        self.assertTrue(
            any("cmd builder" in f for f in outcome.evidence.get("findings", []))
        )
        self.assertIsNotNone(outcome.persisted_path)
        self.assertTrue(outcome.persisted_path.exists())

    def test_emits_audit_event(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-audit",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        audit_path = self.project_root / "audit.jsonl"
        policy = {"security": {"audit_trail": True}}
        with patch.dict(os.environ, {**_host_env(), "BMAD_AUDIT_KEY": "test-key"}):
            run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
                audit_policy=policy,
                audit_path=audit_path,
            )
        self.assertTrue(audit_path.exists())
        import json
        line = audit_path.read_text().strip()
        record = json.loads(line)
        self.assertEqual(record["event"], "EvidenceCollected")

    def test_no_audit_when_not_configured(self) -> None:
        cfg = CollectorConfig(
            collector_id="test-noaudit",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        audit_path = self.project_root / "audit.jsonl"
        with patch.dict(os.environ, _host_env(), clear=True):
            run_single_collector(
                cfg, self.tmpdir, _profile(),
                "gate-001", self.project_root,
            )
        self.assertFalse(audit_path.exists())

    def test_trust_boundary_enforced(self) -> None:
        from story_automator.core.trust_boundary import TrustBoundaryError

        cfg = CollectorConfig(
            collector_id="test-child",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        )
        with patch.dict(os.environ, {"STORY_AUTOMATOR_CHILD": "true"}):
            with self.assertRaises(TrustBoundaryError):
                run_single_collector(
                    cfg, self.tmpdir, _profile(),
                    "gate-001", self.project_root,
                )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_runner.py -v`
Expected: ModuleNotFoundError — `collector_runner` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `skills/bmad-story-automator/src/story_automator/core/collector_runner.py`:

```python
"""Collector runner — orchestrates evidence collection for gate evaluation.

Runs individual collectors via run_collector_with_timeout (§6.4),
persists evidence via persist_evidence_record, and emits audit events.
Full gate loop and diff-scoped mode added in subsequent tasks.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .adjudicator import resolve_timeout, run_collector_with_timeout
from .collector_config import CollectorConfig, CollectorOutcome
from .evidence_io import persist_evidence_record
from .gate_audit import EvidenceCollectedAudit, emit_gate_audit
from .gate_schema import make_evidence_record
from .trust_boundary import assert_host_context

__all__ = [
    "run_single_collector",
]


def run_single_collector(
    config: CollectorConfig,
    checkout_path: str,
    profile: dict[str, Any],
    gate_id: str,
    project_root: str | Path,
    *,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> CollectorOutcome:
    """Run one collector, persist evidence, emit audit event.

    §7: asserts host context before any write.
    §6.4: resolves per-category timeout from profile.
    Fail-closed: build_cmd exceptions produce error evidence.
    """
    assert_host_context("run_single_collector")
    timeout = resolve_timeout(profile, config.category)

    try:
        cmd = config.build_cmd(checkout_path, profile)
    except Exception as exc:
        evidence = make_evidence_record(
            collector=config.collector_id,
            tool=config.tool,
            category=config.category,
            status="error",
            findings=[f"cmd builder error: {exc}"],
            exit_code=-1,
            deterministic=config.deterministic,
        )
        persisted = persist_evidence_record(project_root, gate_id, evidence)
        if audit_policy is not None and audit_path is not None:
            emit_gate_audit(
                audit_policy,
                audit_path,
                EvidenceCollectedAudit(
                    gate_id=gate_id,
                    category=config.category,
                    collector=config.collector_id,
                    tool=config.tool,
                    status="error",
                    duration_ms=0,
                ),
            )
        return CollectorOutcome(
            config=config, evidence=evidence, persisted_path=persisted,
        )

    evidence = run_collector_with_timeout(
        cmd,
        collector=config.collector_id,
        tool=config.tool,
        category=config.category,
        timeout_s=timeout,
        cwd=checkout_path,
    )

    persisted_path = persist_evidence_record(project_root, gate_id, evidence)

    if audit_policy is not None and audit_path is not None:
        emit_gate_audit(
            audit_policy,
            audit_path,
            EvidenceCollectedAudit(
                gate_id=gate_id,
                category=config.category,
                collector=config.collector_id,
                tool=config.tool,
                status=evidence["status"],
                duration_ms=evidence.get("duration_ms", 0),
            ),
        )

    return CollectorOutcome(
        config=config,
        evidence=evidence,
        persisted_path=persisted_path,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_runner.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collector_runner.py tests/test_collector_runner.py
git commit -m "feat(gate): add collector runner — single collector execution

run_single_collector runs one collector with timeout, persists evidence,
emits audit event, and returns CollectorOutcome.  Fail-closed on
build_cmd errors (spec §7).

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 8: CollectorRunner — Full Gate Collector Loop

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/collector_runner.py`
- Modify: `tests/test_collector_runner.py`

**Interfaces:**
- Consumes: `run_single_collector` from Task 7, `CollectorRegistry.applicable()` from `collector_registry.py`, `collector_checkout` from `collector_checkout.py`, `assert_host_context` from `trust_boundary.py`
- Produces: `run_gate_collectors(project_root: str | Path, gate_id: str, commit_sha: str, profile: dict[str, Any], registry: CollectorRegistry, *, diff_categories: set[str] | None = None, audit_policy: dict[str, Any] | None = None, audit_path: Path | None = None) -> list[CollectorOutcome]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_collector_runner.py`:

```python
import subprocess

from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.collector_runner import run_gate_collectors


def _init_repo(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "src.py").write_text("x = 1\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


class RunGateCollectorsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-gate-test-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _profile(self, cats: list[str]) -> dict[str, Any]:
        return {
            "categories": {"code": cats, "system": []},
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }

    def test_runs_all_applicable_collectors(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="b", tool="python3", category="static",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness", "static"]), reg,
            )
        self.assertEqual(len(outcomes), 2)
        ids = {o.config.collector_id for o in outcomes}
        self.assertEqual(ids, {"a", "b"})
        self.assertTrue(all(o.evidence["status"] == "ok" for o in outcomes))

    def test_skips_non_applicable_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="b", tool="python3", category="performance",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].config.collector_id, "a")

    def test_empty_registry_returns_empty(self) -> None:
        reg = CollectorRegistry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(outcomes, [])

    def test_evidence_persisted_to_disk(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertTrue(outcomes[0].persisted_path.exists())

    def test_mixed_pass_and_fail(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="pass", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="fail", tool="python3", category="security",
            build_cmd=_fail_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness", "security"]), reg,
            )
        statuses = {o.config.collector_id: o.evidence["status"] for o in outcomes}
        self.assertEqual(statuses["pass"], "ok")
        self.assertEqual(statuses["fail"], "violation")

    def test_checkout_path_passed_to_collectors(self) -> None:
        captured_paths: list[str] = []

        def capture_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            captured_paths.append(checkout)
            return [sys.executable, "-c", "pass"]

        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=capture_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(len(captured_paths), 1)
        self.assertTrue(Path(captured_paths[0]).is_dir())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_runner.py::RunGateCollectorsTests -v`
Expected: ImportError — `run_gate_collectors` not yet defined.

- [ ] **Step 3: Write minimal implementation**

Add to `skills/bmad-story-automator/src/story_automator/core/collector_runner.py`, updating `__all__` and imports:

```python
from .collector_checkout import collector_checkout
from .collector_registry import CollectorRegistry

__all__ = [
    "run_single_collector",
    "run_gate_collectors",
]

# ... (existing run_single_collector stays above) ...


def run_gate_collectors(
    project_root: str | Path,
    gate_id: str,
    commit_sha: str,
    profile: dict[str, Any],
    registry: CollectorRegistry,
    *,
    diff_categories: set[str] | None = None,
    audit_policy: dict[str, Any] | None = None,
    audit_path: Path | None = None,
) -> list[CollectorOutcome]:
    """Run all applicable collectors for a gate evaluation.

    Creates a fresh checkout at commit_sha (§7), iterates applicable
    collectors from the registry, and returns collected evidence.
    """
    assert_host_context("run_gate_collectors")
    collectors = registry.applicable(profile)
    if diff_categories is not None:
        collectors = [
            c for c in collectors if c.category in diff_categories
        ]
    if not collectors:
        return []

    outcomes: list[CollectorOutcome] = []
    with collector_checkout(project_root, commit_sha) as checkout:
        for config in collectors:
            outcome = run_single_collector(
                config=config,
                checkout_path=str(checkout),
                profile=profile,
                gate_id=gate_id,
                project_root=project_root,
                audit_policy=audit_policy,
                audit_path=audit_path,
            )
            outcomes.append(outcome)
    return outcomes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_runner.py -v`
Expected: All 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/collector_runner.py tests/test_collector_runner.py
git commit -m "feat(gate): add full gate collector loop

run_gate_collectors creates a fresh checkout at commit SHA (spec §7),
iterates applicable collectors, persists evidence, and returns outcomes.
Supports profile filtering and diff-category scoping.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 9: CollectorRunner — Diff-Scoped Mode and Edge Cases

**Files:**
- Modify: `tests/test_collector_runner.py`

**Interfaces:**
- Consumes: `run_gate_collectors` with `diff_categories` parameter
- Produces: Additional tests for diff-scoped filtering, all-fail scenarios, and binary-not-found edge cases

- [ ] **Step 1: Write the tests**

Append to `tests/test_collector_runner.py`:

```python
class DiffScopedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-diff-runner-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _profile(self, cats: list[str]) -> dict[str, Any]:
        return {
            "categories": {"code": cats, "system": []},
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }

    def test_diff_scope_filters_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="b", tool="python3", category="security",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness", "security"]), reg,
                diff_categories={"correctness"},
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].config.category, "correctness")

    def test_diff_scope_empty_skips_all(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
                diff_categories=set(),
            )
        self.assertEqual(outcomes, [])

    def test_diff_scope_none_runs_all(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
                diff_categories=None,
            )
        self.assertEqual(len(outcomes), 1)


class EdgeCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-edge-test-")
        self.project_root = Path(self.tmpdir) / "project"
        self.project_root.mkdir()
        self.sha = _init_repo(self.project_root)

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
        )
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _profile(self, cats: list[str]) -> dict[str, Any]:
        return {
            "categories": {"code": cats, "system": []},
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }

    def test_all_collectors_fail(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_fail_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="b", tool="python3", category="security",
            build_cmd=_fail_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness", "security"]), reg,
            )
        self.assertTrue(
            all(o.evidence["status"] == "violation" for o in outcomes)
        )

    def test_binary_not_found_produces_error(self) -> None:
        def missing_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            return ["nonexistent-binary-xyz-999"]

        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="missing", tool="python3", category="correctness",
            build_cmd=missing_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "error")

    def test_build_cmd_exception_produces_error(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="broken", tool="python3", category="correctness",
            build_cmd=_error_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["correctness"]), reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "error")
        self.assertIsNotNone(outcomes[0].persisted_path)
        self.assertTrue(outcomes[0].persisted_path.exists())

    def test_multiple_collectors_same_category(self) -> None:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="lint-a", tool="python3", category="static",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="lint-b", tool="python3", category="static",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-001", self.sha,
                self._profile(["static"]), reg,
            )
        self.assertEqual(len(outcomes), 2)
        ids = {o.config.collector_id for o in outcomes}
        self.assertEqual(ids, {"lint-a", "lint-b"})
```

- [ ] **Step 2: Run tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_runner.py -v`
Expected: All 20 tests PASS (7 from Task 7 + 6 from Task 8 + 7 new).

- [ ] **Step 3: Commit**

```bash
git add tests/test_collector_runner.py
git commit -m "test(gate): add diff-scoped mode and edge case tests for runner

Tests: diff_categories filtering, empty scope skips all, None runs all,
all-fail, binary not found, build_cmd exception, multiple collectors
per category.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 10: Full Pipeline Integration Test

**Files:**
- Create: `tests/test_collector_integration.py`

**Interfaces:**
- Consumes: All modules from Tasks 1–9: `CollectorConfig`, `CollectorOutcome`, `CollectorRegistry`, `compute_diff_scope`, `preflight_check`, `run_gate_collectors`, `compute_evidence_bundle_hash`, `load_evidence_bundle`, `verdict_for_collector_status`, `aggregate_verdicts`, `EvidenceCollectedAudit`, `emit_gate_audit`
- Produces: End-to-end integration test proving the full collector pipeline works

- [ ] **Step 1: Write the integration tests**

Create `tests/test_collector_integration.py`:

```python
"""End-to-end collector framework integration tests.

Proves the full pipeline: registry → diff scope → doctor → checkout →
collector loop → evidence bundle → audit → verdict aggregation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from story_automator.core.collector_config import (
    CollectorConfig,
    CollectorOutcome,
)
from story_automator.core.collector_doctor import preflight_check
from story_automator.core.collector_registry import CollectorRegistry
from story_automator.core.collector_runner import run_gate_collectors
from story_automator.core.diff_scope import compute_diff_scope
from story_automator.core.evidence_io import (
    compute_evidence_bundle_hash,
    load_evidence_bundle,
)
from story_automator.core.gate_rules import (
    aggregate_verdicts,
    verdict_for_collector_status,
)


def _ok_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "print('all checks pass')"]


def _fail_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "import sys; print('finding: bad code'); sys.exit(1)"]


def _init_repo(path: Path) -> str:
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@t.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "T"],
        capture_output=True, check=True,
    )
    (path / "app.py").write_text("x = 1\n")
    subprocess.run(
        ["git", "-C", str(path), "add", "."],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _add_commit(path: Path, filename: str, content: str) -> str:
    (path / filename).write_text(content)
    subprocess.run(
        ["git", "-C", str(path), "add", filename],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", f"add {filename}"],
        capture_output=True, check=True,
    )
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _host_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("STORY_AUTOMATOR_CHILD", None)
    return env


class FullPipelineTests(unittest.TestCase):
    """End-to-end: registry → run → evidence → bundle hash → verdicts."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="sa-integration-")
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

    def _profile(self) -> dict[str, Any]:
        return {
            "categories": {
                "code": ["correctness", "static", "security"],
                "system": [],
            },
            "categories_na": [],
            "rules": {},
            "timeouts": {},
        }

    def _registry(self) -> CollectorRegistry:
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="pytest-correctness",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
            file_patterns=frozenset({"*.py"}),
        ))
        reg.register(CollectorConfig(
            collector_id="ruff-static",
            tool="python3",
            category="static",
            build_cmd=_ok_cmd,
            file_patterns=frozenset({"*.py"}),
        ))
        reg.register(CollectorConfig(
            collector_id="semgrep-security",
            tool="python3",
            category="security",
            build_cmd=_fail_cmd,
            file_patterns=frozenset({"*.py"}),
        ))
        return reg

    def test_full_pass_pipeline(self) -> None:
        profile = self._profile()
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="check-ok",
            tool="python3",
            category="correctness",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            ok, _ = preflight_check(reg, profile)
            self.assertTrue(ok)

            outcomes = run_gate_collectors(
                self.project_root, "gate-pass", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].evidence["status"], "ok")

        records = load_evidence_bundle(self.project_root, "gate-pass")
        self.assertEqual(len(records), 1)

        bundle_hash = compute_evidence_bundle_hash(records)
        self.assertEqual(len(bundle_hash), 16)

        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        overall = aggregate_verdicts(verdicts)
        self.assertEqual(overall, "PASS")

    def test_mixed_verdict_pipeline(self) -> None:
        profile = self._profile()
        reg = self._registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-mixed", self.base_sha,
                profile, reg,
            )
        self.assertEqual(len(outcomes), 3)

        records = load_evidence_bundle(self.project_root, "gate-mixed")
        verdicts = {
            r["category"]: verdict_for_collector_status(r["status"])
            for r in records
        }
        self.assertEqual(verdicts["correctness"], "PASS")
        self.assertEqual(verdicts["static"], "PASS")
        self.assertEqual(verdicts["security"], "FAIL")
        self.assertEqual(aggregate_verdicts(verdicts), "FAIL")

    def test_diff_scoped_pipeline(self) -> None:
        sha2 = _add_commit(self.project_root, "new.py", "y = 2\n")
        profile = self._profile()
        reg = self._registry()

        diff_cats = compute_diff_scope(
            self.project_root, self.base_sha, sha2,
        )
        self.assertIn("correctness", diff_cats)

        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-diff", sha2,
                profile, reg,
                diff_categories=diff_cats,
            )
        run_cats = {o.config.category for o in outcomes}
        self.assertTrue(run_cats.issubset(diff_cats))

    def test_consistent_statuses_across_runs(self) -> None:
        profile = self._profile()
        reg = self._registry()
        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-det1", self.base_sha,
                profile, reg,
            )
        records1 = load_evidence_bundle(self.project_root, "gate-det1")

        with patch.dict(os.environ, _host_env(), clear=True):
            run_gate_collectors(
                self.project_root, "gate-det2", self.base_sha,
                profile, reg,
            )
        records2 = load_evidence_bundle(self.project_root, "gate-det2")

        statuses1 = {r["category"]: r["status"] for r in records1}
        statuses2 = {r["category"]: r["status"] for r in records2}
        self.assertEqual(statuses1, statuses2)

    def test_audit_events_emitted(self) -> None:
        profile = self._profile()
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="a", tool="python3", category="correctness",
            build_cmd=_ok_cmd,
        ))
        audit_path = self.project_root / "audit.jsonl"
        policy = {"security": {"audit_trail": True}}
        with patch.dict(os.environ, {**_host_env(), "BMAD_AUDIT_KEY": "k"}):
            run_gate_collectors(
                self.project_root, "gate-audit", self.base_sha,
                profile, reg,
                audit_policy=policy,
                audit_path=audit_path,
            )
        self.assertTrue(audit_path.exists())
        lines = audit_path.read_text().strip().split("\n")
        self.assertGreaterEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["event"], "EvidenceCollected")

    def test_kill_switch_excludes_collector(self) -> None:
        profile = {
            "categories": {"code": ["static"], "system": []},
            "categories_na": [],
            "rules": {"static": {"disabled_tools": ["ruff"]}},
            "timeouts": {},
        }
        reg = CollectorRegistry()
        reg.register(CollectorConfig(
            collector_id="ruff", tool="ruff", category="static",
            build_cmd=_ok_cmd,
        ))
        reg.register(CollectorConfig(
            collector_id="mypy", tool="python3", category="static",
            build_cmd=_ok_cmd,
        ))
        with patch.dict(os.environ, _host_env(), clear=True):
            outcomes = run_gate_collectors(
                self.project_root, "gate-kill", self.base_sha,
                profile, reg,
            )
        ids = [o.config.collector_id for o in outcomes]
        self.assertNotIn("ruff", ids)
        self.assertIn("mypy", ids)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the full integration test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_integration.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 3: Run the complete test suite for all milestone files**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_collector_config.py tests/test_collector_registry.py tests/test_diff_scope.py tests/test_collector_doctor.py tests/test_collector_runner.py tests/test_collector_integration.py -v`
Expected: All tests PASS — no regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/test_collector_integration.py
git commit -m "test(gate): add full collector pipeline integration tests

End-to-end: registry → diff scope → doctor → checkout → collector loop
→ evidence bundle → audit → verdict aggregation.  Verifies pass/fail/
mixed/diff-scoped/consistent-statuses/audit/kill-switch scenarios.

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```

---

### Task 11: Full Regression Suite and LOC Verification

**Files:**
- No new files; verify existing work

**Interfaces:**
- Consumes: All modules from Tasks 1–10
- Produces: Verified green test suite with no regressions across the full codebase

- [ ] **Step 1: Run full project test suite**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/ -v --tb=short`
Expected: All tests PASS including both new collector framework tests AND all existing tests (trust boundary, evidence IO, gate schema, gate rules, adjudicator, etc.).

- [ ] **Step 2: Verify LOC limits**

Run: `wc -l skills/bmad-story-automator/src/story_automator/core/collector_config.py skills/bmad-story-automator/src/story_automator/core/collector_registry.py skills/bmad-story-automator/src/story_automator/core/diff_scope.py skills/bmad-story-automator/src/story_automator/core/collector_doctor.py skills/bmad-story-automator/src/story_automator/core/collector_runner.py`
Expected: Each file under 500 LOC.

- [ ] **Step 3: Run ruff lint check**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m ruff check skills/bmad-story-automator/src/story_automator/core/collector_config.py skills/bmad-story-automator/src/story_automator/core/collector_registry.py skills/bmad-story-automator/src/story_automator/core/diff_scope.py skills/bmad-story-automator/src/story_automator/core/collector_doctor.py skills/bmad-story-automator/src/story_automator/core/collector_runner.py`
Expected: No lint errors.

- [ ] **Step 4: Commit (if any linting fixes needed)**

If ruff reported fixable issues, fix them and commit:

```bash
git add -u
git commit -m "fix(gate): resolve lint warnings in collector framework

Generated-By: claude-opus-4-6" --trailer "Generated-By: claude-opus-4-6"
```
