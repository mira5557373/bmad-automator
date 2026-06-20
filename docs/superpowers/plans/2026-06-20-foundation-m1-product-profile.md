# Foundation M1: Product Profile — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Product Profile subsystem — versioned schema, layered loader (bundled → project → env), accessors, hash, and snapshot — so the factory can be specialized per product. Ships default profile + Profile #1 (MSME ERP).

**Architecture:** New `core/product_profile.py` following `runtime_policy.py`'s layered-loading pattern (bundled → project override → env var). Bundled profiles live under `data/profiles/`. Project overrides at `_bmad/bmm/story-automator.profile.json`. Profile selection via `STORY_AUTOMATOR_PROFILE` env var. `runtime_policy._validate_policy_shape` gains `profile`/`gate` as valid top-level keys so future milestones can extend the policy without re-touching it.

**Tech Stack:** Python 3.11+, stdlib only (`json`, `pathlib`, `os`, `hashlib`, `fnmatch`); `unittest`; existing helpers from `core/utils.py`, `core/runtime_layout.py`.

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only. No imports outside this set.
- **Do NOT touch `core/telemetry_events.py`.** M15 emits no new events. New `GateDecision`/`GateRendered` events land in a later milestone that owns the `telemetry_events.py` delta.
- **500-LOC soft limit per Python module.** `product_profile.py` target ~400 LOC.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `npm run verify` before the release-style commit at the end of the milestone** (covers `test:python`, `pack:dry-run`, `test:cli`, `test:smoke`).
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: use `Path.as_posix()` for any persisted relative path (mirrors `runtime_policy._display_path`).
- **`ProfileError(ValueError)`**: parallel to `PolicyError(ValueError)` — independent class, no cross-module coupling.

## File Structure

**New files:**
- `skills/bmad-story-automator/src/story_automator/core/product_profile.py` — loader, validator, accessors, hash, snapshot (~400 LOC)
- `skills/bmad-story-automator/data/profiles/default.json` — minimal bundled default profile
- `skills/bmad-story-automator/data/profiles/msme-erp.json` — Profile #1 (MSME ERP)
- `tests/test_product_profile.py` — unit tests mirroring `test_runtime_policy.py` patterns

**Modified files:**
- `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py` — extend `VALID_TOP_LEVEL_KEYS` with `profile` and `gate`; add type checks in `_validate_policy_shape`
- `skills/bmad-story-automator/src/story_automator/commands/doctor.py` — add `_profile_preflight` section

**Untouched (explicit):** `core/telemetry_events.py`, `core/telemetry_emitter.py`, `core/audit.py`, `core/atomic_io.py`.

---

### Task 1: ProfileError + Schema Constants + Default Profile Data File

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Create: `skills/bmad-story-automator/data/profiles/default.json`
- Create: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `ProfileError(ValueError)`; constants `VALID_TOP_LEVEL_KEYS`, `VALID_PRIORITIES`, `VALID_CODE_CATEGORIES`, `VALID_SYSTEM_CATEGORIES`, `DEFAULT_TIMEOUTS`, `DEFAULT_TIMEOUT_FALLBACK`; function `load_bundled_profile(profile_id: str = "default", project_root: str | None = None) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_product_profile.py
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class BundledProfileTests(unittest.TestCase):
    """Base class: copies the skill bundle into a temp project directory."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self._install_bundle()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _install_bundle(self) -> None:
        bundle_src = REPO_ROOT / "skills" / "bmad-story-automator"
        bundle_dest = (
            self.project_root / ".claude" / "skills" / "bmad-story-automator"
        )
        shutil.copytree(bundle_src, bundle_dest)

    def _bundled_path(self, profile_id: str = "default") -> Path:
        return (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "data"
            / "profiles"
            / f"{profile_id}.json"
        )

    def _write_bundled(self, payload: dict) -> None:
        self._bundled_path().write_text(
            json.dumps(payload), encoding="utf-8"
        )


class LoadBundledProfileTests(BundledProfileTests):
    def test_bundled_default_profile_loads(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(profile["id"], "default")
        self.assertIsInstance(profile["version"], int)
        self.assertIn("matrix", profile)
        self.assertIn("categories", profile)

    def test_profile_error_is_value_error(self) -> None:
        from story_automator.core.product_profile import ProfileError

        self.assertTrue(issubclass(ProfileError, ValueError))

    def test_unknown_profile_id_raises(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        with self.assertRaisesRegex(ProfileError, "unknown bundled profile"):
            load_bundled_profile(
                "nonexistent", project_root=str(self.project_root)
            )

    def test_valid_constants_exist(self) -> None:
        from story_automator.core.product_profile import (
            DEFAULT_TIMEOUT_FALLBACK,
            DEFAULT_TIMEOUTS,
            VALID_CODE_CATEGORIES,
            VALID_PRIORITIES,
            VALID_SYSTEM_CATEGORIES,
            VALID_TOP_LEVEL_KEYS,
        )

        self.assertIn("id", VALID_TOP_LEVEL_KEYS)
        self.assertIn("cost_tier", VALID_TOP_LEVEL_KEYS)
        self.assertIn("categories_na", VALID_TOP_LEVEL_KEYS)
        self.assertIn("timeouts", VALID_TOP_LEVEL_KEYS)
        self.assertIn("forbidden_until", VALID_TOP_LEVEL_KEYS)
        self.assertEqual(VALID_PRIORITIES, {"P0", "P1", "P2", "P3"})
        self.assertIn("correctness", VALID_CODE_CATEGORIES)
        self.assertIn("agentic", VALID_CODE_CATEGORIES)
        self.assertIn("reliability", VALID_SYSTEM_CATEGORIES)
        self.assertIn("cost_to_serve", VALID_SYSTEM_CATEGORIES)
        self.assertEqual(DEFAULT_TIMEOUTS["security"], 300)
        self.assertEqual(DEFAULT_TIMEOUTS["correctness"], 1800)
        self.assertEqual(DEFAULT_TIMEOUT_FALLBACK, 120)


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
  "categories_na": [],
  "rules": {
    "security": {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 0},
    "license": {"forbidden": [], "boundary": {}},
    "test_quality": {"min_score": 70, "burn_in_runs": 5, "max_flaky": 0}
  },
  "invariants": {"registry_file": ""},
  "cost_tier": {"sku_id": "", "arpu_monthly": 0, "max_pod_cost_per_tenant": 0},
  "timeouts": {},
  "forbidden_until": {}
}
```

- [ ] **Step 4: Create the product_profile module with minimal loader**

Write `skills/bmad-story-automator/src/story_automator/core/product_profile.py`:

```python
"""Product Profile subsystem.

Loads, validates, and snapshots the per-product profile that specializes
the general factory (gate rubric, toolchain, matrix, rules, invariants).

Layered resolution (mirrors runtime_policy):
    bundled default  ->  project override  ->  env overrides

Paths:
    bundled: <skills_root>/bmad-story-automator/data/profiles/<id>.json
    project override: <project_root>/_bmad/bmm/story-automator.profile.json
    env selection: STORY_AUTOMATOR_PROFILE
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .runtime_layout import bundled_story_skill_root
from .utils import get_project_root, read_text


class ProfileError(ValueError):
    pass


VALID_TOP_LEVEL_KEYS = {
    "version",
    "id",
    "snapshot",
    "seed_template",
    "toolchain",
    "matrix",
    "categories",
    "categories_na",
    "rules",
    "invariants",
    "forbidden_until",
    "cost_tier",
    "timeouts",
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
DEFAULT_TIMEOUTS: dict[str, int] = {
    "security": 300,
    "performance": 600,
    "accessibility": 180,
    "test_quality": 900,
    "correctness": 1800,
}
DEFAULT_TIMEOUT_FALLBACK = 120

_PROFILES_DIR = "data/profiles"
_PROFILE_ID_ENV = "STORY_AUTOMATOR_PROFILE"


def load_bundled_profile(
    profile_id: str = "default",
    project_root: str | None = None,
) -> dict[str, Any]:
    bundle_root = _bundle_root(project_root)
    profiles_dir = bundle_root / _PROFILES_DIR
    path = profiles_dir / f"{profile_id}.json"
    if not path.is_file():
        available = sorted(p.stem for p in profiles_dir.glob("*.json"))
        raise ProfileError(
            f"unknown bundled profile {profile_id!r}; available: {available}"
        )
    return _read_json(path)


def _bundle_root(project_root: str | None) -> Path:
    root = Path(project_root or get_project_root()).resolve()
    try:
        return bundled_story_skill_root(root)
    except FileNotFoundError as exc:
        raise ProfileError("bundled story automator not found") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(read_text(path))
    except FileNotFoundError as exc:
        raise ProfileError(f"profile file missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileError(
            f"profile json invalid: {path}: {exc.msg} (line {exc.lineno})"
        ) from exc
    if not isinstance(payload, dict):
        raise ProfileError(f"profile json must be an object: {path}")
    return payload
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/data/profiles/default.json \
       skills/bmad-story-automator/src/story_automator/core/product_profile.py \
       tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): add ProfileError, schema constants, bundled default loader

First slice of Foundation M1 (Product Profile): introduces the bundled
default profile under data/profiles/default.json and load_bundled_profile
with profile_id selection. Constants define valid categories, priorities,
and timeout defaults per spec §5 and §6.4.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 2: Shape Validator — Core Fields (top-level, version, id, matrix, categories)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Modify: `tests/test_product_profile.py`

**Interfaces:**
- Consumes: `ProfileError`, `VALID_TOP_LEVEL_KEYS`, `VALID_PRIORITIES`, `VALID_CODE_CATEGORIES`, `VALID_SYSTEM_CATEGORIES` from Task 1.
- Produces: `_validate_profile_shape(profile: dict[str, Any]) -> None` (private; wired into `load_bundled_profile`).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class ProfileShapeTests(BundledProfileTests):
    def test_unknown_top_level_key_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x", "bogus": True,
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "unknown top-level profile keys: bogus"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_version_must_be_positive_int(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": "1.0", "id": "x",
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "profile.version must be a positive integer"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_id_must_be_non_empty_string(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "",
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "profile.id must be a non-empty string"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_matrix_must_include_all_priorities(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x",
             "matrix": {"P0": {"coverage_pct": 100, "levels": []}},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "matrix priorities must include all of"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_coverage_pct_out_of_range_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x",
             "matrix": {p: {"coverage_pct": 101, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, r"matrix\.P0\.coverage_pct must be int 0\.\.100"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_unknown_code_category_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x",
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": ["nope"], "system": []}}
        )
        with self.assertRaisesRegex(ProfileError, "unknown code categories: nope"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_unknown_system_category_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
        )

        self._write_bundled(
            {"version": 1, "id": "x",
             "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
             "categories": {"code": [], "system": ["nope"]}}
        )
        with self.assertRaisesRegex(ProfileError, "unknown system categories: nope"):
            load_bundled_profile(project_root=str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::ProfileShapeTests -v`
Expected: FAIL — no validator yet (invalid input accepted).

- [ ] **Step 3: Implement the validator and wire into loader**

Add to `product_profile.py` (above `load_bundled_profile`):

```python
def _validate_profile_shape(profile: dict[str, Any]) -> None:
    unknown_keys = sorted(set(profile) - VALID_TOP_LEVEL_KEYS)
    if unknown_keys:
        raise ProfileError(
            f"unknown top-level profile keys: {', '.join(unknown_keys)}"
        )
    _validate_version_and_id(profile)
    _validate_matrix(profile.get("matrix"))
    _validate_categories(profile.get("categories"))


def _validate_version_and_id(profile: dict[str, Any]) -> None:
    version = profile.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProfileError("profile.version must be a positive integer")
    pid = profile.get("id")
    if not isinstance(pid, str) or not pid.strip():
        raise ProfileError("profile.id must be a non-empty string")


def _validate_matrix(matrix: Any) -> None:
    if not isinstance(matrix, dict):
        raise ProfileError("matrix must be an object")
    missing = sorted(VALID_PRIORITIES - set(matrix))
    if missing:
        raise ProfileError(
            f"matrix priorities must include all of "
            f"{sorted(VALID_PRIORITIES)}; missing: {missing}"
        )
    unknown = sorted(set(matrix) - VALID_PRIORITIES)
    if unknown:
        raise ProfileError(f"unknown matrix priorities: {', '.join(unknown)}")
    for prio, value in matrix.items():
        if not isinstance(value, dict):
            raise ProfileError(f"matrix.{prio} must be an object")
        coverage = value.get("coverage_pct")
        if (
            not isinstance(coverage, int)
            or isinstance(coverage, bool)
            or coverage < 0
            or coverage > 100
        ):
            raise ProfileError(
                f"matrix.{prio}.coverage_pct must be int 0..100"
            )
        levels = value.get("levels")
        if not isinstance(levels, list) or not all(
            isinstance(item, str) for item in levels
        ):
            raise ProfileError(
                f"matrix.{prio}.levels must be a string array"
            )


def _validate_categories(categories: Any) -> None:
    if not isinstance(categories, dict):
        raise ProfileError("categories must be an object")
    for tier, allowed in (
        ("code", VALID_CODE_CATEGORIES),
        ("system", VALID_SYSTEM_CATEGORIES),
    ):
        items = categories.get(tier, [])
        if not isinstance(items, list) or not all(
            isinstance(item, str) for item in items
        ):
            raise ProfileError(f"categories.{tier} must be a string array")
        unknown = sorted(set(items) - allowed)
        if unknown:
            raise ProfileError(
                f"unknown {tier} categories: {', '.join(unknown)}"
            )
```

Then add `_validate_profile_shape(profile)` to `load_bundled_profile` after the `_read_json` call:

```python
def load_bundled_profile(
    profile_id: str = "default",
    project_root: str | None = None,
) -> dict[str, Any]:
    bundle_root = _bundle_root(project_root)
    profiles_dir = bundle_root / _PROFILES_DIR
    path = profiles_dir / f"{profile_id}.json"
    if not path.is_file():
        available = sorted(p.stem for p in profiles_dir.glob("*.json"))
        raise ProfileError(
            f"unknown bundled profile {profile_id!r}; available: {available}"
        )
    profile = _read_json(path)
    _validate_profile_shape(profile)
    return profile
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/product_profile.py \
       tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): validate profile shape (top-level keys, matrix, categories)

Adds _validate_profile_shape with exhaustive checks for version/id, matrix
priority completeness + coverage_pct range, and category allowlists. Wired
into load_bundled_profile so invalid profiles are rejected at load time.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 3: Shape Validator — Ancillary + §6.4 Fields

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Modify: `tests/test_product_profile.py`

**Interfaces:**
- Consumes: `_validate_profile_shape` from Task 2; `VALID_CODE_CATEGORIES`, `VALID_SYSTEM_CATEGORIES` from Task 1.
- Produces: `_validate_toolchain(toolchain)`, `_validate_rules(rules)`, `_validate_seed_template(seed)`, `_validate_invariants(invariants)`, `_validate_snapshot(snapshot)`, `_validate_cost_tier(cost_tier)`, `_validate_categories_na(categories_na)`, `_validate_timeouts(timeouts)`, `_validate_forbidden_until(mapping)` — all wired into `_validate_profile_shape`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class AncillaryValidationTests(BundledProfileTests):
    """Tests for toolchain, rules, seed_template, invariants, snapshot validators."""

    def _valid_base(self) -> dict:
        return {
            "version": 1, "id": "x",
            "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
            "categories": {"code": [], "system": []},
        }

    def test_toolchain_entry_missing_name_rejected(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["toolchain"] = {"python": [{"version_min": "0.5.0"}]}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, r"toolchain\.python\[0\]\.name must be"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_toolchain_entry_bad_required_rejected(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["toolchain"] = {"python": [{"name": "ruff", "required": "yes"}]}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, r"toolchain\.python\[0\]\.required must be a bool"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_rules_entry_must_be_object(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["rules"] = {"security": "strict"}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, r"rules\.security must be an object"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_seed_template_ref_must_be_string(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["seed_template"] = {"ref": 42}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "seed_template.ref must be a string"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_invariants_registry_file_must_be_string(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["invariants"] = {"registry_file": 42}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "invariants.registry_file must be a string"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_snapshot_relative_dir_required(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["snapshot"] = {"relativeDir": ""}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "snapshot.relativeDir must be a non-empty string"):
            load_bundled_profile(project_root=str(self.project_root))


class Sec64ValidationTests(BundledProfileTests):
    """Tests for §6.4 fields: cost_tier, categories_na, timeouts, forbidden_until."""

    def _valid_base(self) -> dict:
        return {
            "version": 1, "id": "x",
            "matrix": {p: {"coverage_pct": 0, "levels": []} for p in ("P0", "P1", "P2", "P3")},
            "categories": {"code": [], "system": []},
        }

    def test_cost_tier_must_be_object(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["cost_tier"] = []
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "cost_tier must be an object"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_cost_tier_arpu_must_be_non_negative_number(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["cost_tier"] = {"sku_id": "x", "arpu_monthly": -1}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "cost_tier.arpu_monthly must be a non-negative number"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_categories_na_must_be_string_array(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["categories_na"] = "performance"
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "categories_na must be a string array"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_categories_na_unknown_entry_rejected(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["categories_na"] = ["bogus"]
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "unknown categories_na entries: bogus"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_timeouts_unknown_category_rejected(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["timeouts"] = {"bogus_cat": 300}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "unknown category in timeouts: bogus_cat"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_timeouts_must_be_positive_integer(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["timeouts"] = {"security": 0}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, "timeouts.security must be a positive integer"):
            load_bundled_profile(project_root=str(self.project_root))

    def test_forbidden_until_value_must_be_string_array(self) -> None:
        from story_automator.core.product_profile import ProfileError, load_bundled_profile

        base = self._valid_base()
        base["forbidden_until"] = {"ADR-0083": "E*.envelope-*"}
        self._write_bundled(base)
        with self.assertRaisesRegex(ProfileError, r"forbidden_until\.ADR-0083 must be a string array"):
            load_bundled_profile(project_root=str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::AncillaryValidationTests tests/test_product_profile.py::Sec64ValidationTests -v`
Expected: FAIL — sub-validators not implemented yet.

- [ ] **Step 3: Implement all sub-validators**

Add to `product_profile.py` and wire into `_validate_profile_shape`:

```python
def _validate_toolchain(toolchain: Any) -> None:
    if toolchain is None:
        return
    if not isinstance(toolchain, dict):
        raise ProfileError("toolchain must be an object")
    for language, entries in toolchain.items():
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


def _validate_rules(rules: Any) -> None:
    if rules is None:
        return
    if not isinstance(rules, dict):
        raise ProfileError("rules must be an object")
    for category, body in rules.items():
        if not isinstance(body, dict):
            raise ProfileError(f"rules.{category} must be an object")


def _validate_seed_template(seed: Any) -> None:
    if seed is None:
        return
    if not isinstance(seed, dict):
        raise ProfileError("seed_template must be an object")
    if "ref" in seed and not isinstance(seed["ref"], str):
        raise ProfileError("seed_template.ref must be a string")
    if "url" in seed and not isinstance(seed["url"], str):
        raise ProfileError("seed_template.url must be a string")


def _validate_invariants(invariants: Any) -> None:
    if invariants is None:
        return
    if not isinstance(invariants, dict):
        raise ProfileError("invariants must be an object")
    if "registry_file" in invariants and not isinstance(invariants["registry_file"], str):
        raise ProfileError("invariants.registry_file must be a string")


def _validate_snapshot(snapshot: Any) -> None:
    if snapshot is None:
        return
    if not isinstance(snapshot, dict):
        raise ProfileError("snapshot must be an object")
    rel = snapshot.get("relativeDir")
    if rel is not None and (not isinstance(rel, str) or not rel.strip()):
        raise ProfileError("snapshot.relativeDir must be a non-empty string")


_COST_TIER_NUMERIC = {"arpu_monthly", "max_pod_cost_per_tenant"}


def _validate_cost_tier(cost_tier: Any) -> None:
    if cost_tier is None:
        return
    if not isinstance(cost_tier, dict):
        raise ProfileError("cost_tier must be an object")
    if "sku_id" in cost_tier and not isinstance(cost_tier["sku_id"], str):
        raise ProfileError("cost_tier.sku_id must be a string")
    for key in _COST_TIER_NUMERIC:
        value = cost_tier.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ProfileError(f"cost_tier.{key} must be a non-negative number")


def _validate_categories_na(categories_na: Any) -> None:
    if categories_na is None:
        return
    if not isinstance(categories_na, list) or not all(
        isinstance(item, str) for item in categories_na
    ):
        raise ProfileError("categories_na must be a string array")
    unknown = sorted(set(categories_na) - VALID_CODE_CATEGORIES - VALID_SYSTEM_CATEGORIES)
    if unknown:
        raise ProfileError(
            f"unknown categories_na entries: {', '.join(unknown)}"
        )


def _validate_timeouts(timeouts: Any) -> None:
    if timeouts is None:
        return
    if not isinstance(timeouts, dict):
        raise ProfileError("timeouts must be an object")
    for category, seconds in timeouts.items():
        if category not in VALID_CODE_CATEGORIES and category not in VALID_SYSTEM_CATEGORIES:
            raise ProfileError(f"unknown category in timeouts: {category}")
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds <= 0:
            raise ProfileError(
                f"timeouts.{category} must be a positive integer"
            )


def _validate_forbidden_until(mapping: Any) -> None:
    if mapping is None:
        return
    if not isinstance(mapping, dict):
        raise ProfileError("forbidden_until must be an object")
    for adr, patterns in mapping.items():
        if not isinstance(adr, str) or not adr:
            raise ProfileError("forbidden_until keys must be non-empty strings")
        if not isinstance(patterns, list) or not all(
            isinstance(p, str) and p for p in patterns
        ):
            raise ProfileError(
                f"forbidden_until.{adr} must be a string array"
            )
```

Extend `_validate_profile_shape` to call all sub-validators:

```python
def _validate_profile_shape(profile: dict[str, Any]) -> None:
    unknown_keys = sorted(set(profile) - VALID_TOP_LEVEL_KEYS)
    if unknown_keys:
        raise ProfileError(
            f"unknown top-level profile keys: {', '.join(unknown_keys)}"
        )
    _validate_version_and_id(profile)
    _validate_matrix(profile.get("matrix"))
    _validate_categories(profile.get("categories"))
    _validate_toolchain(profile.get("toolchain"))
    _validate_rules(profile.get("rules"))
    _validate_seed_template(profile.get("seed_template"))
    _validate_invariants(profile.get("invariants"))
    _validate_snapshot(profile.get("snapshot"))
    _validate_cost_tier(profile.get("cost_tier"))
    _validate_categories_na(profile.get("categories_na"))
    _validate_timeouts(profile.get("timeouts"))
    _validate_forbidden_until(profile.get("forbidden_until"))
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (24 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/product_profile.py \
       tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): validate ancillary + §6.4 fields

Adds sub-validators for toolchain, rules, seed_template, invariants,
snapshot, cost_tier, categories_na, timeouts, and forbidden_until. All
wired into _validate_profile_shape for exhaustive load-time checking.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 4: Effective Profile Loader (deep merge + project override + env)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Modify: `tests/test_product_profile.py`

**Interfaces:**
- Consumes: `load_bundled_profile`, `_validate_profile_shape` from Tasks 1-3.
- Produces: `load_effective_profile(project_root: str | None = None, *, profile_id: str | None = None) -> dict[str, Any]` with layered loading (bundled → project override → env var selection).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class EffectiveProfileTests(BundledProfileTests):
    def _write_override(self, payload: dict) -> None:
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

        self._write_override({
            "id": "custom",
            "rules": {"security": {"sast_max_high": 0, "deps_max_critical": 0, "secrets_max": 1}},
        })
        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["id"], "custom")
        self.assertEqual(profile["rules"]["security"]["secrets_max"], 1)
        # Untouched default rule value still present
        self.assertEqual(profile["rules"]["test_quality"]["min_score"], 70)

    def test_override_array_replaces_not_appends(self) -> None:
        from story_automator.core.product_profile import load_effective_profile

        self._write_override({
            "categories": {"code": ["security"], "system": ["resilience"]},
        })
        profile = load_effective_profile(str(self.project_root))
        self.assertEqual(profile["categories"]["code"], ["security"])

    def test_override_validation_failure_raises(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_effective_profile,
        )

        self._write_override({
            "categories": {"code": ["nope"], "system": []},
        })
        with self.assertRaisesRegex(ProfileError, "unknown code categories: nope"):
            load_effective_profile(str(self.project_root))

    def test_malformed_override_json_raises(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_effective_profile,
        )

        override_dir = self.project_root / "_bmad" / "bmm"
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "story-automator.profile.json").write_text(
            "{bad json", encoding="utf-8"
        )
        with self.assertRaisesRegex(ProfileError, "profile json invalid"):
            load_effective_profile(str(self.project_root))

    def test_env_var_selects_profile_id(self) -> None:
        from unittest.mock import patch

        from story_automator.core.product_profile import load_effective_profile

        # Default profile has id "default"; env var cannot select
        # msme-erp yet (data file created in Task 10). Test the
        # mechanism: env var overrides the default profile_id.
        with patch.dict(os.environ, {"STORY_AUTOMATOR_PROFILE": "default"}):
            profile = load_effective_profile(str(self.project_root))
            self.assertEqual(profile["id"], "default")

    def test_explicit_profile_id_takes_precedence_over_env(self) -> None:
        from unittest.mock import patch

        from story_automator.core.product_profile import load_effective_profile

        with patch.dict(os.environ, {"STORY_AUTOMATOR_PROFILE": "nonexistent"}):
            profile = load_effective_profile(
                str(self.project_root), profile_id="default"
            )
            self.assertEqual(profile["id"], "default")
```

Add `import os` to the test file imports at the top.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::EffectiveProfileTests -v`
Expected: FAIL — `load_effective_profile` not yet defined.

- [ ] **Step 3: Implement load_effective_profile + _deep_merge**

Add to `product_profile.py`:

```python
_OVERRIDE_PATH = Path("_bmad") / "bmm" / "story-automator.profile.json"


def load_effective_profile(
    project_root: str | None = None,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root or get_project_root()).resolve()
    resolved_id = (
        profile_id
        or os.environ.get(_PROFILE_ID_ENV, "").strip()
        or "default"
    )
    bundled = load_bundled_profile(resolved_id, project_root=str(root))
    override_path = root / _OVERRIDE_PATH
    if override_path.is_file():
        override = _read_json(override_path)
        merged = _deep_merge(bundled, override)
    else:
        merged = bundled
    _validate_profile_shape(merged)
    return merged


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = (
                _deep_merge(merged[key], value) if key in merged else value
            )
        return merged
    if isinstance(override, list):
        return list(override)
    return override
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (31 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/product_profile.py \
       tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): layered loader with project override + env var selection

load_effective_profile reads the bundled profile (selected by explicit
profile_id → STORY_AUTOMATOR_PROFILE env → "default"), deep-merges the
project override at _bmad/bmm/story-automator.profile.json, then
re-validates. Array-replace / map-deep-merge semantics mirror
runtime_policy.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 5: Profile Accessors (required_for_priority, toolchain_for, rule_for)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Modify: `tests/test_product_profile.py`

**Interfaces:**
- Consumes: loaded profile dicts from Tasks 1-4.
- Produces: `required_for_priority(profile: dict, priority: str) -> dict[str, Any]`; `toolchain_for(profile: dict, language: str) -> list[dict[str, Any]]`; `rule_for(profile: dict, category: str) -> dict[str, Any]`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class AccessorTests(BundledProfileTests):
    def test_required_for_priority_p0(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            required_for_priority,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        req = required_for_priority(profile, "P0")
        self.assertEqual(req["coverage_pct"], 100)
        self.assertIn("e2e", req["levels"])

    def test_required_for_priority_unknown_raises(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_bundled_profile,
            required_for_priority,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        with self.assertRaisesRegex(ProfileError, "unknown priority: P9"):
            required_for_priority(profile, "P9")

    def test_required_for_priority_returns_copy(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            required_for_priority,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        req = required_for_priority(profile, "P0")
        req["levels"].append("mutated")
        again = required_for_priority(profile, "P0")
        self.assertNotIn("mutated", again["levels"])

    def test_toolchain_for_unknown_language_returns_empty(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            toolchain_for,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(toolchain_for(profile, "rust"), [])

    def test_rule_for_missing_category_returns_empty(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            rule_for,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(rule_for(profile, "performance"), {})

    def test_rule_for_present_category(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            rule_for,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        rule = rule_for(profile, "security")
        self.assertEqual(rule["sast_max_high"], 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::AccessorTests -v`
Expected: FAIL — accessors not defined.

- [ ] **Step 3: Implement accessors**

Add to `product_profile.py`:

```python
def required_for_priority(
    profile: dict[str, Any], priority: str
) -> dict[str, Any]:
    if priority not in VALID_PRIORITIES:
        raise ProfileError(f"unknown priority: {priority}")
    entry = (profile.get("matrix") or {}).get(priority) or {}
    return {
        "coverage_pct": int(entry.get("coverage_pct", 0)),
        "levels": list(entry.get("levels") or []),
    }


def toolchain_for(
    profile: dict[str, Any], language: str
) -> list[dict[str, Any]]:
    entries = (profile.get("toolchain") or {}).get(language) or []
    return [dict(entry) for entry in entries]


def rule_for(profile: dict[str, Any], category: str) -> dict[str, Any]:
    return dict((profile.get("rules") or {}).get(category) or {})
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (37 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/product_profile.py \
       tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): add required_for_priority, toolchain_for, rule_for accessors

Defensive-copy accessors for the three most-used profile subsections.
required_for_priority raises ProfileError on unknown priority; the other
two return {} or [] when the key is absent.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 6: forbidden_until Accessor (is_story_blocked)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Modify: `tests/test_product_profile.py`

**Interfaces:**
- Produces: `is_story_blocked(profile: dict[str, Any], story_id: str) -> tuple[bool, str]` — returns `(True, "ADR-0083")` if any pattern matches, `(False, "")` otherwise. Uses `fnmatch.fnmatchcase` for glob.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class ForbiddenUntilTests(BundledProfileTests):
    def _write_forbidden(self, mapping: dict) -> None:
        bundled = json.loads(self._bundled_path().read_text(encoding="utf-8"))
        bundled["forbidden_until"] = mapping
        self._write_bundled(bundled)

    def test_no_forbidden_means_unblocked(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(is_story_blocked(profile, "E1.S1"), (False, ""))

    def test_glob_pattern_blocks_matching_story(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        self._write_forbidden({"ADR-0083": ["E*.envelope-*"]})
        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(
            is_story_blocked(profile, "E1.envelope-sign"), (True, "ADR-0083")
        )
        self.assertEqual(
            is_story_blocked(profile, "E1.ledger-write"), (False, "")
        )

    def test_multiple_blockers_returns_first_sorted(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        self._write_forbidden({
            "DG-3": ["E*.envelope-*"],
            "ADR-0083": ["E*.envelope-*"],
        })
        profile = load_bundled_profile(project_root=str(self.project_root))
        blocked, adr = is_story_blocked(profile, "E1.envelope-sign")
        self.assertTrue(blocked)
        self.assertEqual(adr, "ADR-0083")

    def test_dg2_blocks_cost_to_serve(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        self._write_forbidden({"DG-2": ["*.cost-to-serve"]})
        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(
            is_story_blocked(profile, "E5.cost-to-serve"), (True, "DG-2")
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_product_profile.py::ForbiddenUntilTests -v`
Expected: FAIL — `is_story_blocked` not defined.

- [ ] **Step 3: Implement is_story_blocked**

Add `import fnmatch` to the top of `product_profile.py`, then add:

```python
def is_story_blocked(
    profile: dict[str, Any], story_id: str
) -> tuple[bool, str]:
    mapping = profile.get("forbidden_until") or {}
    for adr in sorted(mapping):
        for pattern in mapping[adr]:
            if fnmatch.fnmatchcase(story_id, pattern):
                return True, adr
    return False, ""
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (41 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/product_profile.py \
       tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): is_story_blocked maps story IDs to open-ADR blockers

forbidden_until uses fnmatch glob patterns keyed by ADR/DG id.
is_story_blocked returns (True, adr_id) on first match (sorted by ADR id
for determinism) or (False, "").

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 7: Profile Hash + Snapshot + Replay

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/product_profile.py`
- Modify: `tests/test_product_profile.py`

**Interfaces:**
- Consumes: `load_effective_profile` from Task 4; `ensure_dir`, `iso_now`, `md5_hex8`, `write_atomic` from `utils.py`.
- Produces: `compute_profile_hash(profile: dict[str, Any]) -> str`; `snapshot_effective_profile(project_root: str | None = None) -> dict[str, Any]`; `load_profile_snapshot(snapshot_file: str, *, project_root: str | None = None, expected_hash: str = "") -> dict[str, Any]`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class ProfileHashTests(BundledProfileTests):
    def test_hash_is_deterministic(self) -> None:
        from story_automator.core.product_profile import (
            compute_profile_hash,
            load_bundled_profile,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        self.assertEqual(
            compute_profile_hash(profile), compute_profile_hash(profile)
        )

    def test_hash_changes_on_modification(self) -> None:
        from story_automator.core.product_profile import (
            compute_profile_hash,
            load_bundled_profile,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        h1 = compute_profile_hash(profile)
        profile["id"] = "modified"
        h2 = compute_profile_hash(profile)
        self.assertNotEqual(h1, h2)

    def test_hash_is_8_char_hex(self) -> None:
        from story_automator.core.product_profile import (
            compute_profile_hash,
            load_bundled_profile,
        )

        profile = load_bundled_profile(project_root=str(self.project_root))
        h = compute_profile_hash(profile)
        self.assertEqual(len(h), 8)
        int(h, 16)  # must be valid hex


class ProfileSnapshotTests(BundledProfileTests):
    def test_snapshot_is_deterministic(self) -> None:
        from story_automator.core.product_profile import (
            snapshot_effective_profile,
        )

        first = snapshot_effective_profile(str(self.project_root))
        second = snapshot_effective_profile(str(self.project_root))
        self.assertEqual(
            first["profileSnapshotHash"], second["profileSnapshotHash"]
        )

    def test_snapshot_file_lives_under_project_root(self) -> None:
        from story_automator.core.product_profile import (
            snapshot_effective_profile,
        )

        snap = snapshot_effective_profile(str(self.project_root))
        snap_path = self.project_root / snap["profileSnapshotFile"]
        self.assertTrue(snap_path.is_file())

    def test_snapshot_includes_profile_hash(self) -> None:
        from story_automator.core.product_profile import (
            snapshot_effective_profile,
        )

        snap = snapshot_effective_profile(str(self.project_root))
        self.assertIn("profileHash", snap)
        self.assertEqual(len(snap["profileHash"]), 8)

    def test_snapshot_escape_rejected(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            snapshot_effective_profile,
        )

        bundled = json.loads(
            self._bundled_path().read_text(encoding="utf-8")
        )
        bundled["snapshot"]["relativeDir"] = "../outside"
        self._write_bundled(bundled)
        with self.assertRaisesRegex(ProfileError, "escapes allowed root"):
            snapshot_effective_profile(str(self.project_root))

    def test_load_snapshot_detects_hash_mismatch(self) -> None:
        from story_automator.core.product_profile import (
            ProfileError,
            load_profile_snapshot,
            snapshot_effective_profile,
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

Run: `python -m pytest tests/test_product_profile.py::ProfileHashTests tests/test_product_profile.py::ProfileSnapshotTests -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement hash, snapshot, and replay**

Add imports to `product_profile.py`:

```python
from .utils import ensure_dir, iso_now, md5_hex8, write_atomic
```

Add functions:

```python
def compute_profile_hash(profile: dict[str, Any]) -> str:
    canonical = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    return md5_hex8(canonical)


def snapshot_effective_profile(
    project_root: str | None = None,
) -> dict[str, Any]:
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
        "profileHash": compute_profile_hash(profile),
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
            f"profile snapshot hash mismatch: "
            f"expected {expected_hash}, got {actual_hash}"
        )
    profile = json.loads(raw)
    _validate_profile_shape(profile)
    return profile


def _resolve_snapshot_dir(
    profile: dict[str, Any], project_root: Path
) -> Path:
    snapshot = profile.get("snapshot") or {}
    relative_dir = str(snapshot.get("relativeDir") or "").strip()
    if not relative_dir:
        raise ProfileError("snapshot.relativeDir missing")
    raw = Path(relative_dir)
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

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (49 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/product_profile.py \
       tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): deterministic hash + snapshot + replay loader

compute_profile_hash returns md5_hex8 of canonical JSON for drift
detection. snapshot_effective_profile writes a stable-JSON snapshot under
snapshot.relativeDir. load_profile_snapshot verifies expected_hash on
replay. Mirrors snapshot_effective_policy semantics.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 8: Policy Shape Validator Update (profile/gate keys)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py:12-19`
- Modify: `tests/test_runtime_policy.py`

**Interfaces:**
- Consumes: `VALID_TOP_LEVEL_KEYS`, `_validate_policy_shape` from `runtime_policy.py`.
- Produces: extended `VALID_TOP_LEVEL_KEYS` with `"profile"` and `"gate"`; type checks for both keys.

- [ ] **Step 1: Write failing regression tests**

Append the following 4 methods to the existing `RuntimePolicyTests` class in `tests/test_runtime_policy.py` (which has `_write_override` and `load_effective_policy` already in scope):

```python
    def test_optional_profile_top_level_key_validates(self) -> None:
        self._write_override(
            {"profile": {"name": "default", "file": "data/profiles/default.json"}}
        )
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

    def test_gate_block_must_be_object(self) -> None:
        self._write_override({"gate": "enabled"})
        with self.assertRaisesRegex(PolicyError, "gate must be an object"):
            load_effective_policy(str(self.project_root))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_runtime_policy.py -v -k "profile or gate"`
Expected: FAIL — `profile`/`gate` flagged as unknown top-level keys.

- [ ] **Step 3: Extend VALID_TOP_LEVEL_KEYS and add type checks**

Edit `runtime_policy.py` lines 12-18 to add `"profile"` and `"gate"`:

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

At the end of `_validate_policy_shape` (after the for-loop over steps, around line 356), add the new type checks:

```python
    if "profile" in policy and not isinstance(policy["profile"], dict):
        raise PolicyError("profile must be an object")
    if "gate" in policy and not isinstance(policy["gate"], dict):
        raise PolicyError("gate must be an object")
```

- [ ] **Step 4: Run ALL runtime_policy tests to verify no regressions**

Run: `python -m pytest tests/test_runtime_policy.py -v`
Expected: PASS (all original + 4 new).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/runtime_policy.py \
       tests/test_runtime_policy.py
git commit -m "$(cat <<'EOF'
feat(policy): allow optional profile/gate top-level keys

Extends VALID_TOP_LEVEL_KEYS with profile + gate and validates each as
an object when present. M18 (Adjudicator) will populate the gate block;
Foundation M1 just opens the door.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 9: MSME-ERP Profile (Profile #1)

**Files:**
- Create: `skills/bmad-story-automator/data/profiles/msme-erp.json`
- Modify: `tests/test_product_profile.py`

**Interfaces:**
- Consumes: `load_bundled_profile`, `is_story_blocked`, `required_for_priority` from Tasks 1-6.
- Produces: validated MSME-ERP profile data file.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_product_profile.py`:

```python
class MsmeErpProfileTests(BundledProfileTests):
    def test_msme_erp_loads_and_validates(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        self.assertEqual(profile["id"], "msme-erp")
        self.assertEqual(profile["version"], 1)

    def test_msme_erp_p0_full_coverage(self) -> None:
        from story_automator.core.product_profile import (
            load_bundled_profile,
            required_for_priority,
        )

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        req = required_for_priority(profile, "P0")
        self.assertEqual(req["coverage_pct"], 100)
        self.assertIn("e2e", req["levels"])

    def test_msme_erp_forbidden_until_adr0083(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        blocked, adr = is_story_blocked(profile, "E1.envelope-sign")
        self.assertTrue(blocked)
        self.assertEqual(adr, "ADR-0083")

    def test_msme_erp_forbidden_until_dg2(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        blocked, dg = is_story_blocked(profile, "E5.cost-to-serve")
        self.assertTrue(blocked)
        self.assertEqual(dg, "DG-2")

    def test_msme_erp_cost_tier_zero_placeholders(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        self.assertEqual(profile["cost_tier"]["arpu_monthly"], 0)
        self.assertEqual(profile["cost_tier"]["max_pod_cost_per_tenant"], 0)

    def test_msme_erp_timeouts_match_spec(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        self.assertEqual(profile["timeouts"]["security"], 300)
        self.assertEqual(profile["timeouts"]["performance"], 600)
        self.assertEqual(profile["timeouts"]["accessibility"], 180)
        self.assertEqual(profile["timeouts"]["test_quality"], 900)
        self.assertEqual(profile["timeouts"]["correctness"], 1800)

    def test_msme_erp_full_code_categories(self) -> None:
        from story_automator.core.product_profile import load_bundled_profile

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        code_cats = profile["categories"]["code"]
        for required in ("correctness", "security", "agentic", "docs", "process"):
            self.assertIn(required, code_cats)

    def test_msme_erp_dg3_blocks_ca_channel(self) -> None:
        from story_automator.core.product_profile import (
            is_story_blocked,
            load_bundled_profile,
        )

        profile = load_bundled_profile(
            "msme-erp", project_root=str(self.project_root)
        )
        blocked, dg = is_story_blocked(profile, "E3.ca-channel-premium")
        self.assertTrue(blocked)
        self.assertEqual(dg, "DG-3")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_product_profile.py::MsmeErpProfileTests -v`
Expected: FAIL — `msme-erp.json` does not exist.

- [ ] **Step 3: Create msme-erp.json**

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
      {"name": "ruff",    "version_min": "0.5.0",  "required": true},
      {"name": "mypy",    "version_min": "1.10.0", "required": true},
      {"name": "pytest",  "version_min": "8.0.0",  "required": true},
      {"name": "alembic", "version_min": "1.13.0", "required": true}
    ],
    "typescript": [
      {"name": "biome",      "version_min": "1.8.0",  "required": true},
      {"name": "vitest",     "version_min": "1.0.0",  "required": true},
      {"name": "playwright", "version_min": "1.40.0", "required": true},
      {"name": "knip",       "version_min": "5.0.0",  "required": false}
    ],
    "iac": [
      {"name": "opentofu",    "version_min": "1.8.0",  "required": true},
      {"name": "kubeconform", "version_min": "0.6.0",  "required": false},
      {"name": "conftest",    "version_min": "0.50.0", "required": false},
      {"name": "trivy",       "version_min": "0.50.0", "required": true}
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
  "categories_na": [],
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
  "cost_tier": {
    "sku_id": "",
    "arpu_monthly": 0,
    "max_pod_cost_per_tenant": 0
  },
  "timeouts": {
    "security":      300,
    "performance":   600,
    "accessibility": 180,
    "test_quality":  900,
    "correctness":   1800
  },
  "forbidden_until": {
    "ADR-0083": ["E*.envelope-*"],
    "DG-2":     ["*.cost-to-serve"],
    "DG-3":     ["E*.ca-channel-*"]
  }
}
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_product_profile.py -v`
Expected: PASS (57 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/data/profiles/msme-erp.json \
       tests/test_product_profile.py
git commit -m "$(cat <<'EOF'
feat(profile): add msme-erp profile (Profile #1)

Full MSME ERP product profile: toolchain across Python/TS/IaC/security,
P0=100/P1=90/P2=50/P3=20 coverage matrix, all 18 code + 5 system
categories, security/license/test-quality/accessibility/performance/
supply-chain rules, and forbidden_until blockers for ADR-0083, DG-2,
DG-3 per spec §5 and §6.4.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 10: Doctor Preflight — Profile Toolchain Check

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/doctor.py`
- Modify: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `load_effective_profile`, `toolchain_for`, `ProfileError` from product_profile.py.
- Produces: a `_check_profile()` function returning a `_check("profile", status, detail)` result, added to the `checks` list in `cmd_doctor`. Uses the existing `_check()` pattern; doctor.py's own `_project_root()` helper for project root; `shutil.which` for tool lookups (matching the existing doctor pattern, not importing from utils).

**Existing patterns to follow:**
- `doctor.py` uses `_check(name, status, detail)` returning `{"name": str, "status": str, "detail": str}`.
- `_project_root()` helper at line 31: `os.environ.get("PROJECT_ROOT") or os.getcwd()`.
- Tests use module-level `_run(args)` function that calls `cmd_doctor(args)` and parses JSON output.
- `_EXPECTED_CHECKS` set in the test file must include all check names.

- [ ] **Step 1: Write failing tests**

Update `_EXPECTED_CHECKS` in `tests/test_doctor.py` to add `"profile"`:

```python
_EXPECTED_CHECKS = {
    "python", "dependencies", "tmux", "agents", "git", "disk",
    "audit_key", "config", "file_descriptors", "profile",
}
```

Then append a new test method to `DoctorCommandTests`:

```python
    def test_profile_check_present(self) -> None:
        _code, payload, _ = _run([])
        profile_check = next(
            c for c in payload["checks"] if c["name"] == "profile"
        )
        self.assertIn(profile_check["status"], ("ok", "warn"))
        self.assertIn("profile", profile_check["detail"].lower())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_doctor.py -v`
Expected: FAIL — `_EXPECTED_CHECKS` now includes `"profile"` but `cmd_doctor` doesn't emit it, so the set comparison fails.

- [ ] **Step 3: Implement _check_profile and wire into cmd_doctor**

Add import at the top of `doctor.py` (after existing imports):

```python
from ..core.product_profile import ProfileError, load_effective_profile
```

Add the check function (before `cmd_doctor`):

```python
def _check_profile() -> dict[str, str]:
    try:
        profile = load_effective_profile(_project_root())
    except ProfileError as exc:
        return _check("profile", "warn", f"profile load failed: {exc}")
    profile_id = profile.get("id", "unknown")
    missing: list[str] = []
    toolchain = profile.get("toolchain") or {}
    for language in sorted(toolchain):
        for entry in toolchain.get(language) or []:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            if entry.get("required", True) and name and shutil.which(name) is None:
                missing.append(name)
    if missing:
        return _check(
            "profile", "warn",
            f"profile '{profile_id}' loaded; missing required tools: {', '.join(missing)}"
        )
    return _check("profile", "ok", f"profile '{profile_id}' loaded; toolchain OK")
```

Add `_check_profile()` to the `checks` list in `cmd_doctor()`, after `_check_config_files()`:

```python
    checks = [
        _check_python(),
        _check_dependencies(),
        _check_tmux(),
        _check_agents(),
        _check_git(),
        _check_disk(),
        _check_audit_key(),
        _check_config_files(),
        _check_profile(),
        _check_file_descriptors(),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_doctor.py tests/test_product_profile.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/doctor.py \
       tests/test_doctor.py
git commit -m "$(cat <<'EOF'
feat(doctor): preflight active-profile toolchain on PATH

Doctor gains a "profile" check that loads the effective profile and
reports any required toolchain entries not found on PATH. Follows the
existing _check() pattern for consistent JSON output.

Generated-By: claude-opus-4-6
EOF
)"
```

---

### Task 11: Changelog + npm run verify

**Files:**
- Create or modify: `docs/changelog/260620.md`

**Interfaces:** none — this is the release-style capstone task.

- [ ] **Step 1: Add milestone changelog entry**

Create or append to `docs/changelog/260620.md`:

```markdown
## 260620 - [FULL] Foundation M1 Product Profile

### Summary
Adds a versioned, layered Product Profile subsystem (bundled → project
override → effective + snapshot/replay) that specializes the general
factory per product. Profile #1 is `msme-erp`.

### Added
- `core/product_profile.py` with `load_bundled_profile`, `load_effective_profile`,
  `snapshot_effective_profile`, `load_profile_snapshot`, `compute_profile_hash`,
  `toolchain_for`, `required_for_priority`, `rule_for`, `is_story_blocked`.
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
- tests/test_product_profile.py
- tests/test_runtime_policy.py
- tests/test_doctor.py

### QA Notes
- No new Python deps; no telemetry-event changes; no audit-event changes.
- All new persisted paths go through `_ensure_within` / `_display_path`.
- Snapshot hash is content-stable (`json.dumps(..., sort_keys=True, indent=2)`).
- Profile hash uses `md5_hex8` of canonical compact JSON for drift detection.
```

- [ ] **Step 2: Run npm run verify**

Run: `npm run verify`
Expected: all four sub-runs (`test:python`, `pack:dry-run`, `test:cli`, `test:smoke`) green.

If anything fails, fix the underlying issue before proceeding.

- [ ] **Step 3: Commit the changelog**

```bash
git add docs/changelog/260620.md
git commit -m "$(cat <<'EOF'
docs(changelog): Foundation M1 Product Profile [FULL]

Generated-By: claude-opus-4-6
EOF
)"
```

---

## Self-Review

**1. Spec coverage:** §5 (Product Profile schema, layered loading, ID fields, toolchain, matrix, categories, rules, cost_tier, invariants, forbidden_until, seed_template) — all covered in Tasks 1-6, 9. §6.4 (cost_tier, categories_na, timeouts, forbidden_until schemas) — all covered in Task 3. §14 (repo-guardrail compat: no new deps, 500-LOC, conventional commits, Generated-By trailer) — enforced in Global Constraints. M15 milestone deliverable ("schema + layered loader; policy shape-validator learns profile/gate keys") — fully covered.

**2. Placeholder scan:** No TBD, TODO, "add appropriate", "similar to Task N", or description-only steps. Every code step shows actual code; every test step shows actual assertions.

**3. Type consistency:** `ProfileError(ValueError)` used uniformly. All public functions return `dict[str, Any]` or `tuple[bool, str]`. Accessor names stable across all tasks: `load_bundled_profile`, `load_effective_profile`, `snapshot_effective_profile`, `load_profile_snapshot`, `compute_profile_hash`, `toolchain_for`, `required_for_priority`, `rule_for`, `is_story_blocked`. Import path consistent: `from .utils import ...` for all utility helpers.
