# M15 Product Profile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned, layered **Product Profile** subsystem (bundled → project override → env), mirroring `runtime_policy.py`, so the factory can be specialized per product. Profile #1 = MSME ERP.

**Architecture:** New `core/product_profile.py` (loader + validator + accessors + snapshot) using the same `_deep_merge` / `_validate_*` / `_resolve_*` patterns as `runtime_policy.py`. Bundled defaults under `skills/bmad-story-automator/data/profiles/`. Project override at `_bmad/bmm/story-automator.profile.json`. Active-profile selection via the new optional `profile` block in `orchestration-policy.json` + `STORY_AUTOMATOR_PROFILE` env var. `runtime_policy._validate_policy_shape` learns two new optional top-level keys (`profile`, `gate`) so future milestones can extend without re-touching it. `doctor` preflights the active profile's declared toolchain.

**Tech Stack:** Python 3.11+, stdlib only (`json`, `pathlib`, `os`, `re`, `hashlib`); `unittest`; existing helpers from `core/utils.py`, `core/runtime_layout.py`.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only. No imports outside this set.
- **Do NOT touch `core/telemetry_events.py`.** M15 emits no new events; it only loads/validates data. New `GateDecision`/`GateRendered` events land in a later M01-owned milestone.
- **500-LOC soft limit per Python module.** `product_profile.py` stays under 500 LOC; split into a sibling `product_profile_schema.py` only if needed.
- **Conventional Commits + `Generated-By:` trailer on every commit.** Branch: `bma-d/m15-product-profile`. One PR per milestone.
- **Run `npm run verify` before the release-style commit at the end of the milestone** (covers `test:python`, `pack:dry-run`, `test:cli`, `test:smoke`).
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path (mirrors `runtime_policy._display_path`).
- **Mirror existing patterns**: `ProfileError(ValueError)` like `PolicyError`; `_ensure_within` for path safety; `_deep_merge` for layering; `md5_hex8` for content hashes.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/product_profile.py` — loader, validator, accessors, snapshot (~450 LOC target)
- `skills/bmad-story-automator/data/profiles/default.json` — minimal bundled default profile
- `skills/bmad-story-automator/data/profiles/msme-erp.json` — Profile #1
- `tests/test_product_profile.py` — unit tests mirroring `test_runtime_policy.py` patterns

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py` — extend `VALID_TOP_LEVEL_KEYS` to include `profile` and `gate`; add `_validate_profile_shape_lite` (just key presence + type, not full profile validation — that stays in `product_profile.py`)
- `skills/bmad-story-automator/data/orchestration-policy.json` — add optional `profile` block referencing `data/profiles/default.json`
- `skills/bmad-story-automator/src/story_automator/commands/doctor.py` — add `_profile_preflight` section reporting profile toolchain availability
- `tests/test_runtime_policy.py` — one regression test confirming the optional `profile` top-level key validates cleanly
- `tests/test_doctor.py` — one new test confirming profile preflight surfaces missing tools

**Untouched (explicit):** `core/telemetry_events.py`, `core/telemetry_emitter.py`, `core/audit.py`, `core/atomic_io.py` (no schema or event additions in M15).

---

### Task 1: Profile schema constants + ProfileError + minimal default profile

**Files:**
- Create: `skills/bmad-story-automator/data/profiles/default.json`
- Create: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Test: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `ProfileError(ValueError)`; module-level constants `VALID_TOP_LEVEL_KEYS`, `VALID_PRIORITIES`, `VALID_CODE_CATEGORIES`, `VALID_SYSTEM_CATEGORIES`, `DEFAULT_PROFILE_PATH`; function `load_bundled_profile(project_root: str | None = None) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_product_profile.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.product_profile import (
    ProfileError,
    load_bundled_profile,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class BundledProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self._install_bundle()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _install_bundle(self) -> None:
        # Mirror test_runtime_policy._install_bundle: copy the bundled story
        # skill into the temp project so the loader resolves real files.
        import shutil
        bundle_src = REPO_ROOT / "skills" / "bmad-story-automator"
        bundle_dest = self.project_root / ".claude" / "skills" / "bmad-story-automator"
        shutil.copytree(bundle_src, bundle_dest)

    def test_bundled_default_profile_loads(self) -> None:
        profile = load_bundled_profile(str(self.project_root))
        self.assertEqual(profile["version"], 1)
        self.assertEqual(profile["id"], "default")
        self.assertIn("matrix", profile)
        self.assertIn("categories", profile)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'story_automator.core.product_profile'`.

- [ ] **Step 3: Create the bundled default profile**

Write `skills/bmad-story-automator/data/profiles/default.json`:

```json
{
  "version": 1,
  "id": "default",
  "snapshot": {
    "relativeDir": "_bmad-output/story-automator/profile-snapshots"
  },
  "seed_template": {
    "ref": "",
    "url": ""
  },
  "toolchain": {},
  "matrix": {
    "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
    "P1": {"coverage_pct": 90,  "levels": ["unit", "integration", "api"]},
    "P2": {"coverage_pct": 50,  "levels": ["unit", "api_happy_path"]},
    "P3": {"coverage_pct": 20,  "levels": ["smoke"]}
  },
  "categories": {
    "code": ["correctness", "static", "security", "license", "observability", "invariants", "process"],
    "system": ["reliability", "resilience", "durable_hitl", "blast_radius", "cost_to_serve"]
  },
  "rules": {
    "security": {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 0},
    "license": {"forbidden": [], "boundary": {}},
    "test_quality": {"min_score": 70, "burn_in_runs": 5, "max_flaky": 0}
  },
  "invariants": {"registry_file": ""},
  "forbidden_until": {}
}
```

- [ ] **Step 4: Create the loader module with the minimal API**

Write `skills/bmad-story-automator/src/story_automator/core/product_profile.py`:

```python
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .runtime_layout import bundled_story_skill_root
from .utils import get_project_root, read_text

VALID_TOP_LEVEL_KEYS = {
    "version",
    "id",
    "snapshot",
    "seed_template",
    "toolchain",
    "matrix",
    "categories",
    "rules",
    "invariants",
    "forbidden_until",
}
VALID_PRIORITIES = {"P0", "P1", "P2", "P3"}
VALID_CODE_CATEGORIES = {
    "correctness", "traceability", "test_quality", "mutation",
    "static", "security", "compliance", "license", "supply_chain",
    "api_compat", "migrations", "performance", "accessibility",
    "observability", "invariants", "agentic", "docs", "process",
}
VALID_SYSTEM_CATEGORIES = {
    "reliability", "resilience", "durable_hitl",
    "blast_radius", "cost_to_serve",
}
DEFAULT_PROFILE_PATH = "data/profiles/default.json"


class ProfileError(ValueError):
    pass


def load_bundled_profile(project_root: str | None = None) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    bundle_root = _bundle_root(root)
    return _read_json(bundle_root / DEFAULT_PROFILE_PATH)


def _bundle_root(project_root: Path) -> Path:
    try:
        return bundled_story_skill_root(project_root)
    except FileNotFoundError as exc:
        raise ProfileError("bundled story automator not found") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(read_text(path))
    except FileNotFoundError as exc:
        raise ProfileError(f"profile file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(f"profile json invalid: {path}") from exc
    if not isinstance(payload, dict):
        raise ProfileError(f"profile json must be an object: {path}")
    return payload
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/data/profiles/default.json \
        skills/bmad-story-automator/src/story_automator/core/product_profile.py \
        tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): add ProfileError + bundled default profile loader

First slice of M15 (Product Profile): introduces the bundled-default
profile under data/profiles/default.json and a minimal load_bundled_profile
loader following the same shape as load_bundled_policy.

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Shape validator (top-level + matrix + categories)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Test: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `_validate_profile_shape(profile: dict[str, Any]) -> None` (private; called by all public loaders); `load_bundled_profile` now raises `ProfileError` on shape violations.

- [ ] **Step 1: Write failing tests for each shape violation**

Append to `tests/test_product_profile.py`:

```python
class ProfileShapeTests(BundledProfileTests):
    def _bundled_path(self) -> Path:
        return self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "profiles" / "default.json"

    def _write_bundled(self, payload: dict) -> None:
        import json
        self._bundled_path().write_text(json.dumps(payload), encoding="utf-8")

    def test_unknown_top_level_key_rejected(self) -> None:
        self._write_bundled({"version": 1, "id": "x", "bogus": True,
                             "matrix": {}, "categories": {"code": [], "system": []}})
        with self.assertRaisesRegex(ProfileError, "unknown top-level profile keys: bogus"):
            load_bundled_profile(str(self.project_root))

    def test_missing_priority_rejected(self) -> None:
        bad = {"version": 1, "id": "x",
               "matrix": {"P0": {"coverage_pct": 100, "levels": []}},
               "categories": {"code": [], "system": []}}
        self._write_bundled(bad)
        with self.assertRaisesRegex(ProfileError, "matrix priorities must include all of"):
            load_bundled_profile(str(self.project_root))

    def test_coverage_pct_out_of_range_rejected(self) -> None:
        bad = {"version": 1, "id": "x",
               "matrix": {p: {"coverage_pct": 101, "levels": []} for p in ("P0","P1","P2","P3")},
               "categories": {"code": [], "system": []}}
        self._write_bundled(bad)
        with self.assertRaisesRegex(ProfileError, "matrix.P0.coverage_pct must be int 0..100"):
            load_bundled_profile(str(self.project_root))

    def test_unknown_code_category_rejected(self) -> None:
        bad = {"version": 1, "id": "x",
               "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0","P1","P2","P3")},
               "categories": {"code": ["nope"], "system": []}}
        self._write_bundled(bad)
        with self.assertRaisesRegex(ProfileError, "unknown code categories: nope"):
            load_bundled_profile(str(self.project_root))

    def test_unknown_system_category_rejected(self) -> None:
        bad = {"version": 1, "id": "x",
               "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0","P1","P2","P3")},
               "categories": {"code": [], "system": ["nope"]}}
        self._write_bundled(bad)
        with self.assertRaisesRegex(ProfileError, "unknown system categories: nope"):
            load_bundled_profile(str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::ProfileShapeTests -v`
Expected: FAIL — no validator yet (tests pass loading invalid input).

- [ ] **Step 3: Implement the validator**

Add to `skills/bmad-story-automator/src/story_automator/core/product_profile.py` (above `load_bundled_profile`, then call from it):

```python
def _validate_profile_shape(profile: dict[str, Any]) -> None:
    unknown_keys = sorted(set(profile) - VALID_TOP_LEVEL_KEYS)
    if unknown_keys:
        raise ProfileError(f"unknown top-level profile keys: {', '.join(unknown_keys)}")
    _validate_version_and_id(profile)
    _validate_matrix(profile.get("matrix"))
    _validate_categories(profile.get("categories"))


def _validate_version_and_id(profile: dict[str, Any]) -> None:
    if not isinstance(profile.get("version"), int) or profile["version"] < 1:
        raise ProfileError("profile.version must be a positive integer")
    if not isinstance(profile.get("id"), str) or not profile["id"].strip():
        raise ProfileError("profile.id must be a non-empty string")


def _validate_matrix(matrix: Any) -> None:
    if not isinstance(matrix, dict):
        raise ProfileError("matrix must be an object")
    missing = sorted(VALID_PRIORITIES - set(matrix))
    if missing:
        raise ProfileError(
            f"matrix priorities must include all of {sorted(VALID_PRIORITIES)}; missing: {missing}"
        )
    unknown = sorted(set(matrix) - VALID_PRIORITIES)
    if unknown:
        raise ProfileError(f"unknown matrix priorities: {', '.join(unknown)}")
    for prio, value in matrix.items():
        if not isinstance(value, dict):
            raise ProfileError(f"matrix.{prio} must be an object")
        coverage = value.get("coverage_pct")
        if not isinstance(coverage, int) or coverage < 0 or coverage > 100 or isinstance(coverage, bool):
            raise ProfileError(f"matrix.{prio}.coverage_pct must be int 0..100")
        levels = value.get("levels")
        if not isinstance(levels, list) or not all(isinstance(item, str) and item for item in levels):
            raise ProfileError(f"matrix.{prio}.levels must be a non-empty-string array")


def _validate_categories(categories: Any) -> None:
    if not isinstance(categories, dict):
        raise ProfileError("categories must be an object")
    for tier, allowed in (("code", VALID_CODE_CATEGORIES), ("system", VALID_SYSTEM_CATEGORIES)):
        items = categories.get(tier, [])
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise ProfileError(f"categories.{tier} must be a string array")
        unknown = sorted(set(items) - allowed)
        if unknown:
            raise ProfileError(f"unknown {tier} categories: {', '.join(unknown)}")
```

Then in `load_bundled_profile`, after the `_read_json` call, add:

```python
    profile = _read_json(bundle_root / DEFAULT_PROFILE_PATH)
    _validate_profile_shape(profile)
    return profile
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS for both `BundledProfileTests` and `ProfileShapeTests` (8 tests total).

- [ ] **Step 5: Commit**

```bash
git add -p   # review hunks
git commit -m "$(cat <<'EOF'
feat(profile): validate profile shape (top-level, matrix, categories)

Adds _validate_profile_shape with positive checks for version/id and
exhaustive priority + category allowlists, raising ProfileError on each
violation. Mirrors runtime_policy._validate_policy_shape style.

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Layered loader — `load_effective_profile`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Test: `tests/test_product_profile.py`

**Interfaces:**
- Consumes: existing helpers `_deep_merge` (this task copies the implementation from `runtime_policy.py` verbatim — DO NOT import the private helper across modules).
- Produces: `load_effective_profile(project_root: str | None = None) -> dict[str, Any]`; reads bundled default, deep-merges project override at `_bmad/bmm/story-automator.profile.json`, re-validates.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class EffectiveProfileTests(BundledProfileTests):
    def _write_override(self, payload: dict) -> None:
        import json
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.profile.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_no_override_returns_bundled(self) -> None:
        from story_automator.core.product_profile import load_effective_profile
        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["id"], "default")

    def test_override_deep_merges(self) -> None:
        from story_automator.core.product_profile import load_effective_profile
        self._write_override({"id": "msme-erp",
                              "rules": {"security": {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 1}}})
        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["id"], "msme-erp")
        self.assertEqual(profile["rules"]["security"]["secrets_max"], 1)
        # Untouched default rule value still present
        self.assertEqual(profile["rules"]["test_quality"]["min_score"], 70)

    def test_override_array_replaces_not_appends(self) -> None:
        from story_automator.core.product_profile import load_effective_profile
        self._write_override({"categories": {"code": ["security"], "system": ["resilience"]}})
        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["categories"]["code"], ["security"])

    def test_override_validation_failure_raises(self) -> None:
        from story_automator.core.product_profile import load_effective_profile
        self._write_override({"categories": {"code": ["nope"], "system": []}})
        with self.assertRaisesRegex(ProfileError, "unknown code categories: nope"):
            load_effective_profile(str(self.project_root))

    def test_malformed_override_json_raises(self) -> None:
        from story_automator.core.product_profile import load_effective_profile
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.profile.json").write_text(
            "{bad json", encoding="utf-8"
        )
        with self.assertRaisesRegex(ProfileError, "profile json invalid"):
            load_effective_profile(str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::EffectiveProfileTests -v`
Expected: FAIL — `load_effective_profile` not yet defined.

- [ ] **Step 3: Implement `load_effective_profile` + `_deep_merge`**

Add to `product_profile.py`:

```python
OVERRIDE_PATH = Path("_bmad") / "bmm" / "story-automator.profile.json"


def load_effective_profile(project_root: str | None = None) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    bundle_root = _bundle_root(root)
    bundled = _read_json(bundle_root / DEFAULT_PROFILE_PATH)
    override_path = root / OVERRIDE_PATH
    override: dict[str, Any] = {}
    if override_path.is_file():
        override = _read_json(override_path)
    merged = _deep_merge(bundled, override)
    _validate_profile_shape(merged)
    return merged


def _deep_merge(base: Any, override: Any) -> Any:
    # Same semantics as runtime_policy._deep_merge: maps merge deeply, arrays
    # are replaced wholesale. Kept local to product_profile to avoid coupling
    # to a private helper in a sibling module.
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _deep_merge(merged[key], value) if key in merged else value
        return merged
    if isinstance(override, list):
        return list(override)
    return override
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (13 tests total).

- [ ] **Step 5: Commit**

```bash
git add -p
git commit -m "$(cat <<'EOF'
feat(profile): layered loader with project override + deep merge

load_effective_profile reads the bundled default, deep-merges the project
override at _bmad/bmm/story-automator.profile.json, then re-validates.
Array-replace / map-deep-merge semantics mirror runtime_policy.

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Toolchain validation + accessor

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Test: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `toolchain_for(profile: dict[str, Any], language: str) -> list[dict[str, Any]]` returning list of `{name, version_min, required}` entries.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class ToolchainTests(BundledProfileTests):
    def _write_bundled(self, toolchain: dict) -> None:
        import json
        path = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "profiles" / "default.json"
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing["toolchain"] = toolchain
        path.write_text(json.dumps(existing), encoding="utf-8")

    def test_toolchain_for_returns_empty_when_language_unknown(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, toolchain_for,
        )
        profile = load_bundled_profile(str(self.project_root))
        self.assertEqual(toolchain_for(profile, "rust"), [])

    def test_toolchain_for_returns_declared_tools(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, toolchain_for,
        )
        self._write_bundled({"python": [
            {"name": "ruff", "version_min": "0.5.0", "required": True},
            {"name": "mypy", "version_min": "1.10.0", "required": True},
        ]})
        profile = load_bundled_profile(str(self.project_root))
        tools = toolchain_for(profile, "python")
        self.assertEqual([t["name"] for t in tools], ["ruff", "mypy"])

    def test_toolchain_entry_missing_name_rejected(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        self._write_bundled({"python": [{"version_min": "0.5.0"}]})
        with self.assertRaisesRegex(ProfileError, "toolchain.python\\[0\\].name must be a non-empty string"):
            load_bundled_profile(str(self.project_root))

    def test_toolchain_entry_bad_required_rejected(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        self._write_bundled({"python": [{"name": "ruff", "required": "yes"}]})
        with self.assertRaisesRegex(ProfileError, "toolchain.python\\[0\\].required must be a bool"):
            load_bundled_profile(str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::ToolchainTests -v`
Expected: FAIL — `toolchain_for` undefined; bad toolchain shape currently accepted.

- [ ] **Step 3: Implement toolchain validation + accessor**

Add to `product_profile.py`:

```python
def toolchain_for(profile: dict[str, Any], language: str) -> list[dict[str, Any]]:
    toolchain = profile.get("toolchain") or {}
    entries = toolchain.get(language) or []
    return [dict(entry) for entry in entries]


def _validate_toolchain(toolchain: Any) -> None:
    if toolchain is None:
        return
    if not isinstance(toolchain, dict):
        raise ProfileError("toolchain must be an object")
    for language, entries in toolchain.items():
        if not isinstance(language, str) or not language:
            raise ProfileError("toolchain keys must be non-empty strings")
        if not isinstance(entries, list):
            raise ProfileError(f"toolchain.{language} must be an array")
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise ProfileError(f"toolchain.{language}[{idx}] must be an object")
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                raise ProfileError(f"toolchain.{language}[{idx}].name must be a non-empty string")
            if "version_min" in entry and not isinstance(entry["version_min"], str):
                raise ProfileError(f"toolchain.{language}[{idx}].version_min must be a string")
            if "required" in entry and not isinstance(entry["required"], bool):
                raise ProfileError(f"toolchain.{language}[{idx}].required must be a bool")
```

Wire it into `_validate_profile_shape` immediately after `_validate_categories(...)`:

```python
    _validate_categories(profile.get("categories"))
    _validate_toolchain(profile.get("toolchain"))
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (17 tests total).

- [ ] **Step 5: Commit**

```bash
git add -p
git commit -m "$(cat <<'EOF'
feat(profile): toolchain accessor + per-entry shape validation

Adds toolchain_for(profile, language) plus structural validation requiring
each toolchain entry to declare a non-empty name and (optionally) typed
version_min and required fields.

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Risk matrix accessor — `required_for_priority`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Test: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `required_for_priority(profile: dict[str, Any], priority: str) -> dict[str, Any]` returning `{"coverage_pct": int, "levels": list[str]}`.
- Raises `ProfileError` on unknown priority.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class RequiredForPriorityTests(BundledProfileTests):
    def test_p0_requires_full_coverage(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, required_for_priority,
        )
        profile = load_bundled_profile(str(self.project_root))
        req = required_for_priority(profile, "P0")
        self.assertEqual(req["coverage_pct"], 100)
        self.assertIn("e2e", req["levels"])

    def test_p3_is_lightweight(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, required_for_priority,
        )
        profile = load_bundled_profile(str(self.project_root))
        req = required_for_priority(profile, "P3")
        self.assertEqual(req["coverage_pct"], 20)

    def test_unknown_priority_raises(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, required_for_priority,
        )
        profile = load_bundled_profile(str(self.project_root))
        with self.assertRaisesRegex(ProfileError, "unknown priority: P9"):
            required_for_priority(profile, "P9")

    def test_returns_copy_not_reference(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, required_for_priority,
        )
        profile = load_bundled_profile(str(self.project_root))
        req = required_for_priority(profile, "P0")
        req["levels"].append("mutated")
        again = required_for_priority(profile, "P0")
        self.assertNotIn("mutated", again["levels"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::RequiredForPriorityTests -v`
Expected: FAIL.

- [ ] **Step 3: Implement the accessor**

Add to `product_profile.py`:

```python
def required_for_priority(profile: dict[str, Any], priority: str) -> dict[str, Any]:
    if priority not in VALID_PRIORITIES:
        raise ProfileError(f"unknown priority: {priority}")
    entry = (profile.get("matrix") or {}).get(priority) or {}
    # Returning a defensive copy: callers should be free to mutate without
    # corrupting the cached profile dict held by the adjudicator.
    return {
        "coverage_pct": int(entry.get("coverage_pct", 0)),
        "levels": list(entry.get("levels") or []),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (21 tests total).

- [ ] **Step 5: Commit**

```bash
git add -p
git commit -m "$(cat <<'EOF'
feat(profile): required_for_priority accessor with defensive copy

Returns the per-priority required coverage_pct + levels; unknown priority
raises ProfileError; the returned dict is independent of the cached
profile so callers can mutate without side effects.

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Rules-shape validation + accessor

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Test: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `rule_for(profile: dict[str, Any], category: str) -> dict[str, Any]` returning `{}` when missing.
- `_validate_rules` enforces only that `rules` is a dict-of-dicts (semantic rule keys land in M18 Adjudicator).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class RuleAccessorTests(BundledProfileTests):
    def test_default_security_rule(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, rule_for,
        )
        profile = load_bundled_profile(str(self.project_root))
        rule = rule_for(profile, "security")
        self.assertEqual(rule["sast_max_high"], 0)

    def test_missing_category_returns_empty(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, rule_for,
        )
        profile = load_bundled_profile(str(self.project_root))
        self.assertEqual(rule_for(profile, "performance"), {})

    def test_rule_shape_must_be_object(self) -> None:
        import json
        from story_automator.core.product_profile import load_bundled_profile
        path = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "profiles" / "default.json"
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing["rules"]["security"] = "bogus"
        path.write_text(json.dumps(existing), encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "rules.security must be an object"):
            load_bundled_profile(str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::RuleAccessorTests -v`
Expected: FAIL.

- [ ] **Step 3: Implement validator + accessor**

Add to `product_profile.py`:

```python
def rule_for(profile: dict[str, Any], category: str) -> dict[str, Any]:
    return dict((profile.get("rules") or {}).get(category) or {})


def _validate_rules(rules: Any) -> None:
    if rules is None:
        return
    if not isinstance(rules, dict):
        raise ProfileError("rules must be an object")
    for category, body in rules.items():
        if not isinstance(category, str) or not category:
            raise ProfileError("rules keys must be non-empty strings")
        if not isinstance(body, dict):
            raise ProfileError(f"rules.{category} must be an object")
```

Wire it into `_validate_profile_shape`, after `_validate_toolchain(...)`:

```python
    _validate_toolchain(profile.get("toolchain"))
    _validate_rules(profile.get("rules"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (24 tests total).

- [ ] **Step 5: Commit**

```bash
git add -p
git commit -m "$(cat <<'EOF'
feat(profile): rule_for accessor + rules-shape validation

Adds rule_for(profile, category) returning a defensive dict copy (or {}
when missing), and shallow shape validation (rules must be object-of-
objects). Per-rule semantics live in the Adjudicator (later milestone).

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `forbidden_until` accessor — story-vs-open-ADR blocking

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Test: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `is_story_blocked(profile: dict[str, Any], story_id: str) -> tuple[bool, str]` returning `(True, "ADR-0083")` if any open-ADR pattern matches the `story_id`, `(False, "")` otherwise. Uses `fnmatch` for glob.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class ForbiddenUntilTests(BundledProfileTests):
    def _write_forbidden(self, mapping: dict) -> None:
        import json
        path = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "profiles" / "default.json"
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing["forbidden_until"] = mapping
        path.write_text(json.dumps(existing), encoding="utf-8")

    def test_no_forbidden_means_unblocked(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, is_story_blocked,
        )
        profile = load_bundled_profile(str(self.project_root))
        self.assertEqual(is_story_blocked(profile, "E1.S1"), (False, ""))

    def test_glob_pattern_blocks_matching_story(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, is_story_blocked,
        )
        self._write_forbidden({"ADR-0083": ["E*.envelope-*"]})
        profile = load_bundled_profile(str(self.project_root))
        self.assertEqual(is_story_blocked(profile, "E1.envelope-sign"), (True, "ADR-0083"))
        self.assertEqual(is_story_blocked(profile, "E1.ledger-write"), (False, ""))

    def test_multiple_blockers_returns_first(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile, is_story_blocked,
        )
        self._write_forbidden({
            "ADR-0083": ["E*.envelope-*"],
            "DG-3": ["E*.envelope-*"],
        })
        profile = load_bundled_profile(str(self.project_root))
        # First match wins (deterministic by sorted ADR id)
        self.assertEqual(is_story_blocked(profile, "E1.envelope-sign"), (True, "ADR-0083"))

    def test_invalid_forbidden_shape_rejected(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile
        self._write_forbidden({"ADR-0083": "E*.envelope-*"})  # string, not array
        with self.assertRaisesRegex(ProfileError, "forbidden_until.ADR-0083 must be a string array"):
            load_bundled_profile(str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::ForbiddenUntilTests -v`
Expected: FAIL.

- [ ] **Step 3: Implement accessor + validation**

Add to `product_profile.py`:

```python
import fnmatch


def is_story_blocked(profile: dict[str, Any], story_id: str) -> tuple[bool, str]:
    mapping = profile.get("forbidden_until") or {}
    for adr in sorted(mapping):
        patterns = mapping.get(adr) or []
        for pattern in patterns:
            if fnmatch.fnmatchcase(story_id, pattern):
                return True, adr
    return False, ""


def _validate_forbidden_until(mapping: Any) -> None:
    if mapping is None:
        return
    if not isinstance(mapping, dict):
        raise ProfileError("forbidden_until must be an object")
    for adr, patterns in mapping.items():
        if not isinstance(adr, str) or not adr:
            raise ProfileError("forbidden_until keys must be non-empty strings")
        if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
            raise ProfileError(f"forbidden_until.{adr} must be a string array")
```

Wire into `_validate_profile_shape`, after `_validate_rules(...)`:

```python
    _validate_rules(profile.get("rules"))
    _validate_forbidden_until(profile.get("forbidden_until"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (28 tests total).

- [ ] **Step 5: Commit**

```bash
git add -p
git commit -m "$(cat <<'EOF'
feat(profile): is_story_blocked maps story IDs to open-ADR blockers

forbidden_until uses fnmatch glob patterns (e.g. "E*.envelope-*") keyed by
ADR id; is_story_blocked returns (True, adr_id) on first match (sorted by
ADR id for determinism) or (False, "").

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Profile snapshot — `snapshot_effective_profile`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Test: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `snapshot_effective_profile(project_root: str | None = None) -> dict[str, Any]` returning `{"profile": dict, "profileVersion": int, "profileSnapshotHash": str, "profileSnapshotFile": str}` — same shape contract as `snapshot_effective_policy`.
- `load_profile_snapshot(snapshot_file: str, *, project_root: str | None = None, expected_hash: str = "") -> dict[str, Any]` for replay.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class ProfileSnapshotTests(BundledProfileTests):
    def test_snapshot_is_deterministic(self) -> None:
        from story_automator.core.product_profile import snapshot_effective_profile
        first = snapshot_effective_profile(str(self.project_root))
        second = snapshot_effective_profile(str(self.project_root))
        self.assertEqual(first["profileSnapshotHash"], second["profileSnapshotHash"])

    def test_snapshot_file_lives_under_project_root(self) -> None:
        from story_automator.core.product_profile import snapshot_effective_profile
        snap = snapshot_effective_profile(str(self.project_root))
        snap_path = self.project_root / snap["profileSnapshotFile"]
        self.assertTrue(snap_path.is_file())

    def test_snapshot_relative_dir_cannot_escape_project_root(self) -> None:
        import json
        from story_automator.core.product_profile import snapshot_effective_profile
        path = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "data" / "profiles" / "default.json"
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing["snapshot"]["relativeDir"] = "../outside"
        path.write_text(json.dumps(existing), encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "snapshot.relativeDir escapes allowed root"):
            snapshot_effective_profile(str(self.project_root))

    def test_load_snapshot_detects_hash_mismatch(self) -> None:
        from story_automator.core.product_profile import (
            load_profile_snapshot, snapshot_effective_profile,
        )
        snap = snapshot_effective_profile(str(self.project_root))
        with self.assertRaisesRegex(ProfileError, "profile snapshot hash mismatch"):
            load_profile_snapshot(
                snap["profileSnapshotFile"],
                project_root=str(self.project_root),
                expected_hash="deadbeef",
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::ProfileSnapshotTests -v`
Expected: FAIL — snapshot helpers undefined.

- [ ] **Step 3: Implement snapshot + replay loaders**

Add to `product_profile.py`:

```python
from .utils import ensure_dir, iso_now, md5_hex8, write_atomic


def snapshot_effective_profile(project_root: str | None = None) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    profile = load_effective_profile(str(root))
    snapshot_dir = _resolve_snapshot_dir(profile, root)
    ensure_dir(snapshot_dir)
    stable_json = _stable_profile_json(profile)
    snapshot_hash = md5_hex8(stable_json)
    stamp = (
        iso_now()
        .replace("-", "")
        .replace(":", "")
        .replace("T", "-")
        .replace("Z", "")
    )
    snapshot_path = snapshot_dir / f"{stamp}-{snapshot_hash}.json"
    write_atomic(snapshot_path, stable_json)
    return {
        "profile": profile,
        "profileVersion": profile.get("version", 1),
        "profileSnapshotHash": snapshot_hash,
        "profileSnapshotFile": _display_path(snapshot_path, root),
    }


def load_profile_snapshot(
    snapshot_file: str,
    *,
    project_root: str | None = None,
    expected_hash: str = "",
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    path = Path(snapshot_file)
    if not path.is_absolute():
        path = root / path
    path = _ensure_within(path, root, "profile snapshot")
    if not path.is_file():
        raise ProfileError(f"profile snapshot missing: {path}")
    raw = read_text(path)
    actual_hash = md5_hex8(raw)
    if expected_hash and actual_hash != expected_hash:
        raise ProfileError(
            f"profile snapshot hash mismatch: expected {expected_hash}, got {actual_hash}"
        )
    profile = _read_json(path)
    _validate_profile_shape(profile)
    return profile


def _snapshot_relative_dir(profile: dict[str, Any]) -> str:
    snapshot = profile.get("snapshot") or {}
    relative_dir = str(snapshot.get("relativeDir") or "").strip()
    if not relative_dir:
        raise ProfileError("snapshot.relativeDir missing")
    return relative_dir


def _resolve_snapshot_dir(profile: dict[str, Any], project_root: Path) -> Path:
    raw = Path(_snapshot_relative_dir(profile))
    candidate = raw if raw.is_absolute() else project_root / raw
    return _ensure_within(candidate, project_root.resolve(), "snapshot.relativeDir")


def _stable_profile_json(profile: dict[str, Any]) -> str:
    return json.dumps(profile, indent=2, sort_keys=True) + "\n"


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _ensure_within(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ProfileError(f"{label} escapes allowed root: {path}") from exc
    return resolved
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (32 tests total).

- [ ] **Step 5: Commit**

```bash
git add -p
git commit -m "$(cat <<'EOF'
feat(profile): deterministic snapshot + replay loader with hash check

snapshot_effective_profile writes a canonical, stable-JSON snapshot under
snapshot.relativeDir; load_profile_snapshot verifies expected_hash on
replay. Mirrors snapshot_effective_policy semantics so future state
documents can reference profile snapshots the same way they reference
policy snapshots.

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Extend `runtime_policy` to accept `profile` and `gate` top-level keys

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py:12-19` (extend `VALID_TOP_LEVEL_KEYS`)
- Modify: `skills/bmad-story-automator/data/orchestration-policy.json` (add optional `profile` block)
- Modify: `tests/test_runtime_policy.py` (one regression test)

**Interfaces:**
- Consumes: existing `_validate_policy_shape` from `runtime_policy.py`.
- Produces: extended `VALID_TOP_LEVEL_KEYS = {"version", "snapshot", "runtime", "workflow", "steps", "security", "profile", "gate"}`; new private `_validate_profile_block` (key presence only; full validation lives in `product_profile.py`).

- [ ] **Step 1: Write the failing regression test**

Append to `tests/test_runtime_policy.py`:

```python
    def test_optional_profile_top_level_key_validates(self) -> None:
        self._write_override({"profile": {"name": "default", "file": "data/profiles/default.json"}})
        policy = load_effective_policy(str(self.project_root))
        self.assertEqual(policy["profile"]["name"], "default")

    def test_optional_gate_top_level_key_validates(self) -> None:
        self._write_override({"gate": {"enabled": False}})
        policy = load_effective_policy(str(self.project_root))
        self.assertFalse(policy["gate"]["enabled"])

    def test_profile_block_must_be_object(self) -> None:
        self._write_override({"profile": []})
        with self.assertRaisesRegex(PolicyError, "profile must be an object"):
            load_effective_policy(str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_runtime_policy.py::RuntimePolicyTests::test_optional_profile_top_level_key_validates tests/test_runtime_policy.py::RuntimePolicyTests::test_optional_gate_top_level_key_validates tests/test_runtime_policy.py::RuntimePolicyTests::test_profile_block_must_be_object -v`
Expected: FAIL — `profile`/`gate` flagged as unknown top-level keys; missing object-shape check.

- [ ] **Step 3: Extend `VALID_TOP_LEVEL_KEYS` and add shape check**

Edit `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py:12-19`:

```python
VALID_TOP_LEVEL_KEYS = {
    "version",
    "snapshot",
    "runtime",
    "workflow",
    "steps",
    "security",
    "profile",
    "gate",
}
```

Inside `_validate_policy_shape`, after `_validate_security_shape(policy)`, add:

```python
    _validate_security_shape(policy)
    if "profile" in policy and not isinstance(policy.get("profile"), dict):
        raise PolicyError("profile must be an object")
    if "gate" in policy and not isinstance(policy.get("gate"), dict):
        raise PolicyError("gate must be an object")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_runtime_policy.py -v`
Expected: PASS (all original tests + 3 new).

- [ ] **Step 5: Add optional `profile` block to the bundled policy**

Edit `skills/bmad-story-automator/data/orchestration-policy.json` after the `security` block:

```json
  "security": {
    "audit_trail": false
  },
  "profile": {
    "name": "default",
    "file": "data/profiles/default.json"
  },
  "runtime": {
```

- [ ] **Step 6: Verify the whole policy + profile test suites still pass together**

Run: `python -m pytest tests/test_runtime_policy.py tests/test_product_profile.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add -p
git commit -m "$(cat <<'EOF'
feat(policy): allow optional profile/gate top-level keys

Extends VALID_TOP_LEVEL_KEYS with profile + gate, validates each as an
object when present, and references the bundled default profile from
orchestration-policy.json. M18 (Adjudicator) will populate the gate block;
M15 just opens the door.

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Doctor preflight — verify active-profile toolchain on PATH

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `load_effective_profile`, `toolchain_for` (from M15 Tasks 1–4).
- Produces: new `_profile_preflight(project_root: str) -> dict[str, Any]` returning `{"profile_id": str, "missing_tools": list[str], "checked_languages": list[str]}`; embedded in doctor's JSON output under the new `"profile"` key.

- [ ] **Step 1: Read the existing doctor.py top of file to learn the pattern**

Read `skills/bmad-story-automator/src/story_automator/commands/doctor.py` (the first 80 lines and the entry point).

- [ ] **Step 2: Write the failing test**

Append to `tests/test_doctor.py`:

```python
    def test_doctor_reports_active_profile_id(self) -> None:
        # Bundled default profile id is "default"; doctor must surface it.
        from story_automator.commands.doctor import cmd_doctor
        result = self._run_doctor()
        self.assertEqual(result["profile"]["profile_id"], "default")

    def test_doctor_flags_missing_toolchain_entries(self) -> None:
        # Override the project's profile so it requires a binary that is
        # almost certainly not on $PATH inside the test sandbox.
        import json
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.profile.json").write_text(
            json.dumps({"toolchain": {"python": [
                {"name": "definitely-not-on-path-xyz", "required": True},
            ]}}),
            encoding="utf-8",
        )
        result = self._run_doctor()
        self.assertIn("definitely-not-on-path-xyz", result["profile"]["missing_tools"])
```

(If `_run_doctor` is the harness name in the existing `test_doctor.py`, reuse it. If the file uses a different helper name, mirror it instead — read the file once before writing the test.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_doctor.py -v -k profile`
Expected: FAIL — `"profile"` key missing from doctor output.

- [ ] **Step 4: Implement `_profile_preflight` and wire into doctor's output**

Add near the top of `doctor.py`:

```python
from story_automator.core.product_profile import (
    ProfileError,
    load_effective_profile,
    toolchain_for,
)
from story_automator.core.utils import command_exists
```

Add the helper:

```python
def _profile_preflight(project_root: str) -> dict[str, Any]:
    try:
        profile = load_effective_profile(project_root)
    except ProfileError as exc:
        return {"profile_id": "", "missing_tools": [], "error": str(exc),
                "checked_languages": []}
    checked: list[str] = []
    missing: list[str] = []
    toolchain = profile.get("toolchain") or {}
    for language in sorted(toolchain):
        checked.append(language)
        for entry in toolchain_for(profile, language):
            if entry.get("required", True) and not command_exists(entry["name"]):
                missing.append(entry["name"])
    return {
        "profile_id": profile.get("id", ""),
        "missing_tools": missing,
        "checked_languages": checked,
    }
```

In the doctor command's output-assembly section, add `"profile": _profile_preflight(project_root)` to the result dict.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_doctor.py tests/test_product_profile.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -p
git commit -m "$(cat <<'EOF'
feat(doctor): preflight active-profile toolchain on PATH

doctor's JSON output gains a "profile" block with profile_id,
checked_languages, and any required tools not found on PATH. Mirrors the
existing PATH probes for tmux/claude/codex.

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: MSME ERP profile (Profile #1)

**Files:**
- Create: `skills/bmad-story-automator/data/profiles/msme-erp.json`
- Test: `tests/test_product_profile.py`

**Interfaces:** none beyond Task 1–8; this is a data-only deliverable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_product_profile.py`:

```python
class MsmeErpProfileTests(BundledProfileTests):
    def test_msme_erp_profile_loads_with_validation(self) -> None:
        # The MSME ERP profile is loaded by pointing the project override at
        # the bundled msme-erp.json: this proves the file is valid against
        # the full schema, including its forbidden_until and rules.
        import json, shutil
        bundled_msme = REPO_ROOT / "skills" / "bmad-story-automator" / "data" / "profiles" / "msme-erp.json"
        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(bundled_msme, override_dir / "story-automator.profile.json")
        from story_automator.core.product_profile import (
            is_story_blocked, load_effective_profile, required_for_priority,
        )
        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["id"], "msme-erp")
        # P0 still demands full coverage in the MSME profile
        self.assertEqual(required_for_priority(profile, "P0")["coverage_pct"], 100)
        # ADR-0083 blocks envelope-signing stories until resolved
        blocked, adr = is_story_blocked(profile, "E1.envelope-sign")
        self.assertTrue(blocked)
        self.assertEqual(adr, "ADR-0083")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_product_profile.py::MsmeErpProfileTests -v`
Expected: FAIL — `msme-erp.json` does not exist yet.

- [ ] **Step 3: Create `msme-erp.json`**

Write `skills/bmad-story-automator/data/profiles/msme-erp.json`:

```json
{
  "version": 1,
  "id": "msme-erp",
  "snapshot": {
    "relativeDir": "_bmad-output/story-automator/profile-snapshots"
  },
  "seed_template": {
    "ref": "msme-erp-golden-template@1.0.0",
    "url": ""
  },
  "toolchain": {
    "python": [
      {"name": "ruff",     "version_min": "0.5.0",  "required": true},
      {"name": "mypy",     "version_min": "1.10.0", "required": true},
      {"name": "pytest",   "version_min": "8.0.0",  "required": true},
      {"name": "alembic",  "version_min": "1.13.0", "required": true}
    ],
    "typescript": [
      {"name": "biome",      "version_min": "1.8.0",  "required": true},
      {"name": "vitest",     "version_min": "1.0.0",  "required": true},
      {"name": "playwright", "version_min": "1.40.0", "required": true},
      {"name": "knip",       "version_min": "5.0.0",  "required": false}
    ],
    "iac": [
      {"name": "opentofu",     "version_min": "1.8.0",  "required": true},
      {"name": "kubeconform",  "version_min": "0.6.0",  "required": false},
      {"name": "conftest",     "version_min": "0.50.0", "required": false},
      {"name": "trivy",        "version_min": "0.50.0", "required": true}
    ],
    "security": [
      {"name": "semgrep",     "version_min": "1.50.0", "required": true},
      {"name": "osv-scanner", "version_min": "1.7.0",  "required": true},
      {"name": "gitleaks",    "version_min": "8.18.0", "required": true},
      {"name": "syft",        "version_min": "1.0.0",  "required": true},
      {"name": "cosign",      "version_min": "2.2.0",  "required": false}
    ]
  },
  "matrix": {
    "P0": {"coverage_pct": 100, "levels": ["unit", "integration", "contract", "e2e"]},
    "P1": {"coverage_pct": 90,  "levels": ["unit", "integration", "api"]},
    "P2": {"coverage_pct": 50,  "levels": ["unit", "api_happy_path"]},
    "P3": {"coverage_pct": 20,  "levels": ["smoke"]}
  },
  "categories": {
    "code": [
      "correctness", "traceability", "test_quality", "mutation",
      "static", "security", "compliance", "license", "supply_chain",
      "api_compat", "migrations", "performance", "accessibility",
      "observability", "invariants", "agentic", "docs", "process"
    ],
    "system": [
      "reliability", "resilience", "durable_hitl",
      "blast_radius", "cost_to_serve"
    ]
  },
  "rules": {
    "security":      {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 0},
    "license":       {"forbidden": ["BSL", "SSPL"], "boundary": {"AGPL-3.0": ["odoo-pod"]}},
    "test_quality":  {"min_score": 70, "burn_in_runs": 5, "max_flaky": 0},
    "accessibility": {"max_serious": 0, "max_critical": 0},
    "performance":   {"max_lighthouse_regression_pct": 5},
    "supply_chain":  {"require_sbom": true, "require_provenance": true, "require_cosign": false}
  },
  "invariants": {
    "registry_file": "data/profiles/msme-erp.invariants.yaml"
  },
  "forbidden_until": {
    "ADR-0083": ["E*.envelope-*"],
    "DG-3":     ["E*.ca-channel-*"]
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_product_profile.py::MsmeErpProfileTests -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite once more for confidence**

Run: `python -m pytest tests/test_product_profile.py tests/test_runtime_policy.py tests/test_doctor.py -v`
Expected: PASS across all three files.

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/data/profiles/msme-erp.json tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): add msme-erp profile (Profile #1)

First non-default product profile: toolchain across Python/TS/IaC/security,
matrix defaults at TEA P0=100/P1=90/P2=50/P3=20 split, full code+system
category set, security/license/test-quality/accessibility/performance/
supply-chain rules, and forbidden_until blockers for ADR-0083 (envelope
signing) and DG-3 (CA-channel mechanic).

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Changelog entry + `npm run verify` + release-style commit

**Files:**
- Modify: `docs/changelog/260620.md` (create if absent; controlled vocabulary per CLAUDE.md)

- [ ] **Step 1: Add a milestone changelog entry**

Create or append to `docs/changelog/260620.md`:

```markdown
## 260620 - [FULL] M15 Product Profile

### Summary
Adds a versioned, layered Product Profile subsystem (bundled → project
override → effective + snapshot/replay) that specializes the general
factory per product. Profile #1 is `msme-erp`.

### Added
- `core/product_profile.py` with `load_bundled_profile`, `load_effective_profile`,
  `snapshot_effective_profile`, `load_profile_snapshot`, `toolchain_for`,
  `required_for_priority`, `rule_for`, `is_story_blocked`.
- `data/profiles/default.json` and `data/profiles/msme-erp.json`.
- Doctor `profile` preflight reporting missing required toolchain entries.
- Optional `profile` and `gate` top-level keys in `orchestration-policy.json`.

### Changed
- `runtime_policy._validate_policy_shape` accepts optional `profile`/`gate`
  blocks (objects), preserving full back-compat with existing policies.

### Files
- skills/bmad-story-automator/src/story_automator/core/product_profile.py
- skills/bmad-story-automator/src/story_automator/core/runtime_policy.py
- skills/bmad-story-automator/src/story_automator/commands/doctor.py
- skills/bmad-story-automator/data/profiles/default.json
- skills/bmad-story-automator/data/profiles/msme-erp.json
- skills/bmad-story-automator/data/orchestration-policy.json
- tests/test_product_profile.py
- tests/test_runtime_policy.py
- tests/test_doctor.py

### QA Notes
- No new Python deps; no telemetry-event changes; no audit-event changes.
- All new persisted paths go through `_ensure_within` / `_display_path`.
- Snapshot hash is content-stable (`json.dumps(..., sort_keys=True, indent=2)`).
```

- [ ] **Step 2: Run `npm run verify` before the release-style commit**

Run: `npm run verify`
Expected: all four sub-runs (`test:python`, `pack:dry-run`, `test:cli`, `test:smoke`) green.

If anything fails, fix the underlying issue inline (do not skip verification).

- [ ] **Step 3: Commit the changelog**

```bash
git add docs/changelog/260620.md
git commit -m "$(cat <<'EOF'
docs(changelog): M15 Product Profile [FULL]

Generated-By: Claude Opus 4.7 (1M context)
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Open the milestone PR**

```bash
git push -u origin bma-d/m15-product-profile
gh pr create --title "M15 Product Profile" --body "$(cat <<'EOF'
## Summary
- Adds versioned, layered Product Profile subsystem (bundled → project override → effective + snapshot/replay)
- Ships default profile + Profile #1 (`msme-erp`)
- Wires doctor toolchain preflight; opens `profile`/`gate` top-level keys in `orchestration-policy.json`

## Test plan
- [ ] `python -m pytest tests/test_product_profile.py tests/test_runtime_policy.py tests/test_doctor.py -v` passes
- [ ] `npm run verify` clean
- [ ] `story-automator doctor` JSON output includes a `profile` block

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## M16–M19 Roadmap (high-level — each gets its own detailed plan when reached)

### M16 — Factory Self-Trust (Evidence-integrity trust boundary)

**Deliverable:** A guarantee that the generation child cannot forge gate evidence. Closes audit findings F-010/F-011 for the gate's purposes.

**Key files:**
- `core/trust_boundary.py` (new) — exposes `prepare_evidence_workspace(commit_sha)` returning a fresh checkout root the orchestrator owns; the tmux child has no write access to it.
- `core/audit.py` (extend) — new audit class `evidence.boundary.created`.
- `commands/tmux.py` (modify) — drop `BMAD_GATE_*` env from spawned child sessions; record per-child filesystem scope in audit event.
- Tests: hypothesis-shaped property test confirming child writes never reach the evidence workspace.

**Dependencies:** none beyond current main.

**Major tasks:** (1) fresh-checkout API + path-isolation guard · (2) audit-event addition (M01-style mini-spec → owning milestone) · (3) tmux-spawn env scrub · (4) closes audit F-010/F-011 (replicated in tests) · (5) changelog + PR.

### M17 — Evidence Collectors

**Deliverable:** A polyglot set of subprocess-driven collectors emitting normalized evidence JSON (the only shape the Adjudicator reads).

**Key files:**
- `core/evidence_schema.py` (new) — Pydantic-free dataclass for the EvidenceRecord shape from spec §6.4.
- `core/evidence_collectors/__init__.py` plus one file per collector (each <200 LOC, kill-switchable): `tests_python.py`, `tests_ts.py`, `coverage.py`, `static_py.py`, `static_ts.py`, `security_sast.py`, `security_deps.py`, `security_secrets.py`, `license_boundary.py`, `otel_wiring.py`, `invariants.py`, plus stubs that consume TEA's `gate-decision.json` / `e2e-trace-summary.json` when present.
- `commands/evidence_collect_cmd.py` (new) — CLI: `story-automator evidence collect --story E1.S1 --commit <sha>` writes normalized JSON under `_bmad/gate/evidence/`.

**Dependencies:** M15 (profile drives which collectors run); M16 (workspace they run in).

**Major tasks:** (1) EvidenceRecord dataclass + JSON serializer + golden-trace seed · (2) per-collector adapter, kill-switch env, fail-closed default · (3) diff-scoping helper (paths-filter) · (4) budget integration with M03 ceilings · (5) `GateScoped` audit record (no silent truncation) · (6) tests per collector against fixtures · (7) changelog + PR.

### M18 — Adjudicator (the pure verdict engine)

**Deliverable:** `verdict = f(risk_profile, evidence[], thresholds)` — pure function, gate file, new `GateDecision` telemetry event + `GateRendered` audit event (M01-style: this milestone *owns* the event-types delta to `telemetry_events.py`).

**Key files:**
- `core/gate_schema.py` (new) — `Verdict`, `CategoryVerdict`, `GateFile` dataclasses.
- `core/gate_rules.py` (new, ≤200 LOC) — one rule function per category; aggregator that applies the deterministic tree from spec §6.3.
- `core/adjudicator.py` (new, ≤300 LOC) — orchestration: load risk profile + evidence + profile rules → compute → persist gate file → emit events.
- `core/telemetry_events.py` (modify, ONLY this milestone) — add `GateDecision`.
- `core/audit.py` (modify) — add `GateRendered` event class.
- `commands/gate_cmd.py` (new) — `story-automator gate render --story E1.S1`.

**Dependencies:** M15, M16, M17.

**Major tasks:** (1) dataclasses + JSON I/O · (2) per-category rule fns (one task each: correctness, traceability, test_quality, static, security, license, supply_chain, observability, invariants, agentic, process) · (3) aggregator + fail-closed default · (4) gate-file writer + hash-chain into audit · (5) replay test (same inputs → same verdict) · (6) M01-style event addition · (7) changelog + PR.

### M19 — Orchestrator Wiring (★ keystone delivery)

**Deliverable:** A working end-to-end code-altitude gate inside the BMAD loop. After this milestone the factory's `review → done` transition is authority-checked by the Adjudicator.

**Key files:**
- `commands/orchestrator.py` (modify) — insert gate step between `code-review` and `done`; consume gate file as the verifier for the `review` step; on FAIL feed structured `[AI-Review]` follow-ups into BMAD's `review_continuation`; on exhaustion/persistent risk-9, PARK + advance via epic DAG.
- `commands/orchestrator_epic_agents.py` (modify) — emit `[AI-Review]` tasks in BMAD-native format (edit-authorization respected).
- `core/success_verifiers.py` (modify) — add `production_ready_gate` verifier kind.
- `core/runtime_policy.py` (extend) — add `gate` block schema (which categories block; which categories' CONCERNS are blocking).
- Tests: end-to-end orchestration-loop test using fakes for the generation child but the real Adjudicator + the real BMAD write-back format.

**Dependencies:** M15, M16, M17, M18.

**Major tasks:** (1) `production_ready_gate` verifier · (2) FAIL → `[AI-Review]` writer (respecting edit-authorization) · (3) PARK+continue via epic DAG · (4) gate-file resumability keyed on `commit_sha` · (5) `gate` policy block (deferred CONCERNS, blocking categories) · (6) end-to-end orchestration test · (7) changelog + PR.

After M19 the factory has a trustworthy, deterministic, BMAD-native code-altitude gate. M20 (risk-scored readiness), M21 (atdd+burn-in+mutation+DoD), M22 (system-altitude), M23 (learning loop) follow on the same pattern — each gets a fresh detailed plan when its turn comes.

---

## Self-Review

**1. Spec coverage:** Every spec §6 code-altitude category that does not require a collector (matrix, categories list, rules shape) is implemented. Categories that require collectors are deliberately deferred to M17; profile only declares them. Snapshot/replay covered. `forbidden_until` covered. Profile-as-config covered. Repo guardrails honored (no new deps; no telemetry-event changes; 500-LOC split path declared).

**2. Placeholder scan:** No `TBD`, no `add error handling`, no `similar to Task N`. Every code step shows actual code; every test step shows actual assertions; every CLI step shows actual commands and expected output.

**3. Type consistency:** `ProfileError(ValueError)` used uniformly. Public functions all return `dict[str, Any]` or `tuple[bool, str]` (consistent with `runtime_policy` style). Accessor names stable: `load_bundled_profile`, `load_effective_profile`, `snapshot_effective_profile`, `load_profile_snapshot`, `toolchain_for`, `required_for_priority`, `rule_for`, `is_story_blocked`.

**4. Ambiguity check:** Task 9 explicitly says profile-block validation is *key presence + type only* in `runtime_policy`; full profile-file validation stays in `product_profile.py`. Task 10's `_run_doctor` helper is noted as "mirror the existing test_doctor.py harness" with explicit instruction to read it first if the name differs.
