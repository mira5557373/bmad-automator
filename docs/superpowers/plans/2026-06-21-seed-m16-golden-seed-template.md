# Seed M16: Golden Seed-Template Bundle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the factory-owned golden seed-template system (spec §16 M24): a template bundle loader, renderer, and instantiation engine that pre-wires production-ready patterns into new product projects. The first bundle (`msme-erp-golden-template@1.0.0`) instantiates six categories of TEA reference fragments: Pact contract tests, network-first interception, selector-resilience, data-factories with auto-cleanup, HAR recorder, and OTel/SLO/healthz+readyz endpoints. This converts "production-ready from day one" from a property the factory *verifies* (via collectors) into one it *seeds*.

**Architecture:** Two-module design under `core/`: `seed_template.py` handles ref parsing, manifest schema validation, bundle resolution, and loading (~250 LOC). `seed_renderer.py` handles variable resolution, `string.Template` rendering, file instantiation with conflict modes, path safety, and result tracking (~250 LOC). Template bundles live under `data/templates/<template-id>/` with a `manifest.json` describing categories, files, variables, and TEA fragment provenance. Profile integration reads `profile.seed_template.ref`, parses the `id@version` ref, resolves the bundle directory, loads the manifest, and delegates to the renderer for instantiation. Version matching is stdlib-only (exact, major-wildcard, or any).

**Tech Stack:** Python 3.11+, stdlib only (no new deps); `string.Template` for rendering; existing `product_profile.py` for profile loading; `utils.py` for `write_atomic`, `ensure_dir`, `read_text`; `unittest` + `tempfile` for test isolation.

**Dependency:** `foundation-m1-product-profile` (complete) — uses `load_effective_profile`, `load_bundled_profile`, profile shape validation, `seed_template.ref` field.

**Parent artifacts:**
- Spec: `docs/superpowers/specs/2026-06-20-production-ready-factory-design.md` (§5, §8 module 4, §16 M24)
- Profile: `data/profiles/msme-erp.json` (`seed_template.ref: "msme-erp-golden-template@1.0.0"`)
- Profile module: `core/product_profile.py` (seed_template validation already exists)

## Global Constraints

- **No new Python deps.** Python 3.11+, stdlib + `filelock` + `psutil` only. `string.Template` is stdlib.
- **Do NOT touch `core/telemetry_events.py`.** Gate telemetry events land in M18.
- **Do NOT touch `core/product_profile.py`.** Profile validation for `seed_template` already exists and is sufficient.
- **500-LOC soft limit per Python module.** Targets: `seed_template.py` ~250, `seed_renderer.py` ~250, each test file ≤ 250.
- **Conventional Commits + `Generated-By:` trailer on every commit.**
- **Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py tests/test_seed_renderer.py -v` to validate per-task.**
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform**: template `dst` paths use forward slashes (POSIX); instantiation converts to `os.sep` at write time.
- **Template files use `.tmpl` suffix** to prevent IDE/linter confusion. The manifest's separate `src` (with `.tmpl`) and `dst` (without) fields handle the mapping — no runtime suffix stripping is needed.
- **Template content uses `string.Template` `$variable` / `${variable}` syntax.** `$$` escapes a literal `$`.
- **`on_conflict` default is `"skip"`** — never overwrite existing product files unless the manifest explicitly says `"overwrite"`.

## File Structure

**New source files:**
- `skills/bmad-story-automator/src/story_automator/core/seed_template.py` — ref parsing, manifest schema, bundle resolution, loading (~250 LOC)
- `skills/bmad-story-automator/src/story_automator/core/seed_renderer.py` — variable resolution, template rendering, instantiation, result tracking (~250 LOC)

**New test files:**
- `tests/test_seed_template.py` — tests for seed_template.py (~350 LOC)
- `tests/test_seed_renderer.py` — tests for seed_renderer.py (~350 LOC)

**New data files:**
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/manifest.json` — MSME ERP bundle manifest
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/contracts/conftest.py.tmpl` — Pact contract test conftest
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/contracts/pact_consumer.py.tmpl` — Pact consumer test scaffold
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/network/network_first.py.tmpl` — network-first interception fixture
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/network/har_recorder.py.tmpl` — HAR recording fixture
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/resilience/selectors.py.tmpl` — selector resilience helpers
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/factories/factory_base.py.tmpl` — data factory base with auto-cleanup
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/observability/otel_setup.py.tmpl` — OTel tracing/metrics/logs wiring
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/observability/health_endpoints.py.tmpl` — /healthz + /readyz handlers
- `skills/bmad-story-automator/data/templates/msme-erp-golden-template/observability/slo_config.yaml.tmpl` — SLO definitions

**Untouched (explicit):** `core/product_profile.py`, `core/telemetry_events.py`, `core/gate_schema.py`, `core/evidence_io.py`, `core/gate_audit.py`, `core/trust_boundary.py`, `core/collector_registry.py`, `core/collector_runner.py`, `data/profiles/default.json`, `data/profiles/msme-erp.json`.

## Test runner commands

| Action | Command |
|---|---|
| Run seed_template tests | `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py -v` |
| Run seed_renderer tests | `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py -v` |
| Run both test files | `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py tests/test_seed_renderer.py -v` |
| Lint new files | `python3 -m ruff check skills/bmad-story-automator/src/story_automator/core/seed_template.py skills/bmad-story-automator/src/story_automator/core/seed_renderer.py tests/test_seed_template.py tests/test_seed_renderer.py` |
| Format check | `python3 -m ruff format --check skills/bmad-story-automator/src/story_automator/core/seed_template.py skills/bmad-story-automator/src/story_automator/core/seed_renderer.py` |
| Full suite still passes | `npm run test:python` |
| Module sizes | `wc -l skills/bmad-story-automator/src/story_automator/core/seed_template.py skills/bmad-story-automator/src/story_automator/core/seed_renderer.py` |

## BLOCKED protocol

If any step produces unexpected output:
1. Stop. Do NOT proceed to the next step.
2. Capture the exact command, full stdout, full stderr, exit code.
3. Report: "BLOCKED at Task N Step S: <one-line summary>. Command: ..., Expected: ..., Actual: ..."
4. Wait for guidance before resuming.

---

## Phase 1: Foundation — Core Types, Ref Parsing, Manifest Schema

### Task 1: SeedTemplateError + resolve_template_ref

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/seed_template.py` (skeleton)
- Create: `tests/test_seed_template.py` (first test class)

**Interfaces:**
- Produces: `SeedTemplateError(ValueError)`, `TEMPLATE_SCHEMA_VERSION = 1`, `resolve_template_ref(ref: str) -> tuple[str, str]` — parses `"msme-erp-golden-template@1.0.0"` → `("msme-erp-golden-template", "1.0.0")`. Empty ref → `("", "")`. Invalid ref (path traversal, slashes) → raises `SeedTemplateError`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_seed_template.py` with `ResolveTemplateRefTests`:

| Test | Input | Expected |
|---|---|---|
| `test_parse_exact_version` | `"msme-erp-golden-template@1.0.0"` | `("msme-erp-golden-template", "1.0.0")` |
| `test_parse_major_wildcard` | `"msme-erp-golden-template@1.x"` | `("msme-erp-golden-template", "1.x")` |
| `test_parse_major_only` | `"msme-erp-golden-template@1"` | `("msme-erp-golden-template", "1")` |
| `test_parse_no_version` | `"msme-erp-golden-template"` | `("msme-erp-golden-template", "")` |
| `test_empty_ref` | `""` | `("", "")` |
| `test_invalid_path_traversal` | `"../evil@1.0"` | raises `SeedTemplateError` |
| `test_invalid_slashes` | `"foo/bar@1.0"` | raises `SeedTemplateError` |
| `test_multiple_at_signs` | `"template@1.0@extra"` | raises `SeedTemplateError` |
| `test_whitespace_ref` | `"  "` | `("", "")` (treated as empty after strip) |

Verify: tests import and fail with `ImportError` or `AttributeError`.

- [ ] **Step 2: Implement minimum code to pass**

Create `seed_template.py` with:
- `from __future__ import annotations` header
- Module docstring referencing spec §5, §16 M24
- `SeedTemplateError(ValueError)` class
- `TEMPLATE_SCHEMA_VERSION = 1`
- `resolve_template_ref(ref: str) -> tuple[str, str]` — strips whitespace, splits on first `@` (rejects refs with multiple `@`), validates no path traversal (no `/`, no `..`, no `os.sep`), returns `(template_id, version)`. Whitespace-only → treated as empty.

- [ ] **Step 3: Verify all 9 tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py::ResolveTemplateRefTests -v`

- [ ] **Step 4: Lint**

Run: `python3 -m ruff check skills/bmad-story-automator/src/story_automator/core/seed_template.py tests/test_seed_template.py`

- [ ] **Step 5: Commit**

`feat(seed-template): add SeedTemplateError and resolve_template_ref`

---

### Task 2: Manifest Schema Validation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_template.py`
- Modify: `tests/test_seed_template.py`

**Interfaces:**
- Produces: `validate_manifest(manifest: dict) -> None` — raises `SeedTemplateError` on invalid manifest. Validates: `schema_version` (int == TEMPLATE_SCHEMA_VERSION), `template_id` (non-empty str), `template_version` (non-empty str), `categories` (dict with ≥1 entry, each category has `description` str + `files` list), optional `variables` (dict of variable defs), optional `description` (str). Per-file entry: `src` (non-empty str), `dst` (non-empty str), optional `on_conflict` ("skip" | "overwrite"). Per-variable entry: optional `required` (bool), optional `default` (str), optional `description` (str). Cross-category: duplicate `dst` paths across all categories rejected. Variable names must be valid Python identifiers (`str.isidentifier()`) to match `string.Template` rules.

- [ ] **Step 1: Write failing tests**

Add `ValidateManifestTests` to `tests/test_seed_template.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_valid_minimal_manifest` | all required fields, one category, one file | passes |
| `test_valid_full_manifest` | all fields including variables, tea_fragment | passes |
| `test_missing_schema_version` | no `schema_version` | raises `SeedTemplateError` |
| `test_wrong_schema_version` | `schema_version: 99` | raises `SeedTemplateError` |
| `test_missing_template_id` | no `template_id` | raises `SeedTemplateError` |
| `test_empty_template_id` | `template_id: ""` | raises `SeedTemplateError` |
| `test_missing_template_version` | no `template_version` | raises `SeedTemplateError` |
| `test_missing_categories` | no `categories` | raises `SeedTemplateError` |
| `test_empty_categories` | `categories: {}` | raises `SeedTemplateError` |
| `test_category_missing_files` | category without `files` key | raises `SeedTemplateError` |
| `test_category_missing_description` | category without `description` | raises `SeedTemplateError` |
| `test_file_entry_missing_src` | file entry without `src` | raises `SeedTemplateError` |
| `test_file_entry_missing_dst` | file entry without `dst` | raises `SeedTemplateError` |
| `test_file_entry_invalid_on_conflict` | `on_conflict: "merge"` | raises `SeedTemplateError` |
| `test_variable_invalid_required_type` | `required: "yes"` (not bool) | raises `SeedTemplateError` |
| `test_duplicate_dst_across_categories` | two files with same `dst` in different categories | raises `SeedTemplateError` |
| `test_variable_name_invalid_identifier` | variable name `"foo-bar"` (not a valid Python identifier) | raises `SeedTemplateError` |

Use a helper `_make_manifest(**overrides)` that returns a valid manifest dict with overrides applied.

- [ ] **Step 2: Implement validate_manifest**

Add to `seed_template.py`:
- `VALID_CONFLICT_MODES = frozenset({"skip", "overwrite"})`
- `validate_manifest(manifest: dict) -> None` with validation per the interface spec.

- [ ] **Step 3: Verify all manifest tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py::ValidateManifestTests -v`

- [ ] **Step 4: Verify all previous tests still pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py -v`

- [ ] **Step 5: Commit**

`feat(seed-template): add manifest schema validation`

---

### Task 3: Bundle Directory Resolution

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_template.py`
- Modify: `tests/test_seed_template.py`

**Interfaces:**
- Consumes: `runtime_layout.bundled_story_skill_root`
- Produces: `resolve_bundle_dir(template_id: str, project_root: str | None = None) -> Path` — resolves `data/templates/<template_id>/` under the bundled skill root. Raises `SeedTemplateError` if the directory doesn't exist.

- [ ] **Step 1: Write failing tests**

Add `ResolveBundleDirTests` to `tests/test_seed_template.py`. Use `tempfile.mkdtemp` to create a fake skill root with `data/templates/test-template/` directory. Patch `bundled_story_skill_root` to return the fake root.

| Test | Scenario | Expected |
|---|---|---|
| `test_existing_bundle_resolves` | template dir exists | returns correct Path |
| `test_missing_bundle_raises` | template dir doesn't exist | raises `SeedTemplateError` |
| `test_path_traversal_blocked` | template_id with `..` | raises `SeedTemplateError` |
| `test_result_is_absolute` | any valid call | returned path is absolute |

- [ ] **Step 2: Implement resolve_bundle_dir**

Add to `seed_template.py`:
- Import `bundled_story_skill_root` from `.runtime_layout`
- `_TEMPLATES_DIR = "data/templates"`
- `resolve_bundle_dir(template_id: str, project_root: str | None = None) -> Path`

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py::ResolveBundleDirTests -v`

- [ ] **Step 4: Commit**

`feat(seed-template): add bundle directory resolution`

---

### Task 4: Load Template Manifest

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_template.py`
- Modify: `tests/test_seed_template.py`

**Interfaces:**
- Consumes: `resolve_bundle_dir`, `validate_manifest`
- Produces: `load_template_manifest(ref: str, project_root: str | None = None) -> dict | None` — parses ref via `resolve_template_ref`, resolves bundle dir, reads `manifest.json`, validates, checks version compatibility. Returns `None` if ref is empty. Raises `SeedTemplateError` on load/validation failure.

Also: `version_satisfies(manifest_version: str, ref_version: str) -> bool` — checks if the manifest's version satisfies the ref constraint. Exact match, major wildcard (`1.x` or `1`), or empty ref_version (any).

- [ ] **Step 1: Write failing tests**

Add `VersionSatisfiesTests` and `LoadTemplateManifestTests`.

`VersionSatisfiesTests`:

| Test | manifest_version | ref_version | Expected |
|---|---|---|---|
| `test_exact_match` | `"1.0.0"` | `"1.0.0"` | `True` |
| `test_exact_mismatch` | `"1.0.0"` | `"2.0.0"` | `False` |
| `test_major_wildcard_match` | `"1.2.3"` | `"1.x"` | `True` |
| `test_major_wildcard_mismatch` | `"2.0.0"` | `"1.x"` | `False` |
| `test_major_only_match` | `"1.2.3"` | `"1"` | `True` |
| `test_empty_ref_matches_any` | `"3.0.0"` | `""` | `True` |

`LoadTemplateManifestTests` (use temp dir + mock bundled_story_skill_root):

| Test | Scenario | Expected |
|---|---|---|
| `test_empty_ref_returns_none` | ref is `""` | returns `None` |
| `test_loads_valid_manifest` | valid manifest.json in bundle dir | returns parsed dict |
| `test_missing_manifest_raises` | bundle dir exists but no manifest.json | raises `SeedTemplateError` |
| `test_invalid_json_raises` | manifest.json is malformed JSON | raises `SeedTemplateError` |
| `test_version_mismatch_raises` | manifest version doesn't satisfy ref | raises `SeedTemplateError` |

- [ ] **Step 2: Implement version_satisfies + load_template_manifest**

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py -v`

- [ ] **Step 4: Commit**

`feat(seed-template): add version matching and manifest loader`

---

## Phase 2: Template Operations — Variables, Listing, Rendering, Validation

### Task 5: Variable Resolution

**Files:**
- Create: `skills/bmad-story-automator/src/story_automator/core/seed_renderer.py` (skeleton)
- Create: `tests/test_seed_renderer.py` (first test class)

**Interfaces:**
- Produces: `SeedRenderError(ValueError)`, `resolve_variables(manifest: dict, provided: dict[str, str]) -> dict[str, str]` — merges provided variables with manifest defaults. Raises `SeedRenderError` if a required variable is missing. Returns the final variable dict (provided overrides defaults; extra provided keys are silently included for forward-compat).

- [ ] **Step 1: Write failing tests**

Create `tests/test_seed_renderer.py` with `ResolveVariablesTests`:

| Test | Scenario | Expected |
|---|---|---|
| `test_required_provided` | required var provided | returns merged dict |
| `test_required_missing_raises` | required var not provided | raises `SeedRenderError` |
| `test_optional_uses_default` | optional var not provided, has default | uses default value |
| `test_provided_overrides_default` | optional var provided and has default | uses provided value |
| `test_no_variables_in_manifest` | manifest has no `variables` key | returns provided dict |
| `test_extra_provided_kept` | extra key not in manifest | included in result |
| `test_empty_provided_empty_manifest` | both empty | returns empty dict |

Use a helper `_make_manifest_with_vars(variables: dict)`.

- [ ] **Step 2: Implement**

Create `seed_renderer.py` with:
- `from __future__ import annotations` header
- Module docstring
- `SeedRenderError(ValueError)` class
- `resolve_variables(manifest: dict, provided: dict[str, str]) -> dict[str, str]`

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py::ResolveVariablesTests -v`

- [ ] **Step 4: Commit**

`feat(seed-renderer): add variable resolution`

---

### Task 6: Template File Listing

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_renderer.py`
- Modify: `tests/test_seed_renderer.py`

**Interfaces:**
- Produces: `list_template_files(manifest: dict, category: str | None = None) -> list[dict[str, str]]` — returns list of file entries `{"src": ..., "dst": ..., "on_conflict": ..., "category": ...}`. If `category` is given, filters to that category only. If category doesn't exist, raises `SeedRenderError`. `on_conflict` defaults to `"skip"` if not specified in the manifest entry.

- [ ] **Step 1: Write failing tests**

Add `ListTemplateFilesTests`:

| Test | Scenario | Expected |
|---|---|---|
| `test_list_all_files` | no category filter | returns all files with category tag |
| `test_filter_by_category` | category="contracts" | returns only contracts files |
| `test_unknown_category_raises` | category="nonexistent" | raises `SeedRenderError` |
| `test_default_on_conflict` | file without `on_conflict` | entry has `on_conflict: "skip"` |
| `test_explicit_on_conflict` | file with `on_conflict: "overwrite"` | entry has `on_conflict: "overwrite"` |
| `test_empty_category_files` | category with empty `files` list | returns empty list |

- [ ] **Step 2: Implement list_template_files**

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py -v`

- [ ] **Step 4: Commit**

`feat(seed-renderer): add template file listing by category`

---

### Task 7: Template Content Rendering

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_renderer.py`
- Modify: `tests/test_seed_renderer.py`

**Interfaces:**
- Produces: `render_template_content(content: str, variables: dict[str, str]) -> str` — uses `string.Template.safe_substitute` to replace `$variable` / `${variable}` placeholders. `$$` produces literal `$`. Unresolved placeholders are left as-is (safe_substitute). Returns the rendered string.

- [ ] **Step 1: Write failing tests**

Add `RenderTemplateContentTests`:

| Test | Scenario | Expected |
|---|---|---|
| `test_simple_substitution` | `"Hello $name"` + `{name: "World"}` | `"Hello World"` |
| `test_braced_substitution` | `"${service}_api"` + `{service: "erp"}` | `"erp_api"` |
| `test_dollar_escape` | `"Price: $$5"` + `{}` | `"Price: $5"` |
| `test_missing_var_safe` | `"Hello $unknown"` + `{}` | `"Hello $unknown"` |
| `test_empty_content` | `""` + `{x: "y"}` | `""` |
| `test_multiline` | multiline template | rendered correctly |
| `test_no_variables_passthrough` | plain text, no `$` | identical output |

- [ ] **Step 2: Implement render_template_content**

Add import of `string.Template` (stdlib). Implement using `string.Template(content).safe_substitute(variables)`.

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py::RenderTemplateContentTests -v`

- [ ] **Step 4: Commit**

`feat(seed-renderer): add template content rendering`

---

### Task 8: Bundle Integrity Validation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_template.py`
- Modify: `tests/test_seed_template.py`

**Interfaces:**
- Produces: `validate_bundle(bundle_dir: Path, manifest: dict) -> list[str]` — checks that every `src` file in every category of the manifest exists on disk under `bundle_dir`. Returns a list of missing file paths (empty = valid). Does NOT raise; caller decides severity.

- [ ] **Step 1: Write failing tests**

Add `ValidateBundleTests` to `tests/test_seed_template.py`. Use temp dir with manifest files.

| Test | Scenario | Expected |
|---|---|---|
| `test_all_files_present` | all src files exist | returns empty list |
| `test_missing_file_reported` | one src file missing | returns list with that path |
| `test_multiple_missing` | two files missing | returns both paths |
| `test_empty_manifest_valid` | category with no files | returns empty list |

- [ ] **Step 2: Implement validate_bundle**

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py -v`

- [ ] **Step 4: Commit**

`feat(seed-template): add bundle integrity validation`

---

## Phase 3: Instantiation

### Task 9: InstantiationResult + Core Instantiation

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_renderer.py`
- Modify: `tests/test_seed_renderer.py`

**Interfaces:**
- Consumes: `render_template_content`, `list_template_files`, `resolve_variables`
- Produces:
  - `InstantiationResult` (dataclass): `written: list[str]` (dst paths written), `skipped: list[str]` (dst paths skipped due to conflict), `errors: list[str]` (error descriptions)
  - `instantiate_template(bundle_dir: Path, manifest: dict, target_dir: Path, variables: dict[str, str], *, category: str | None = None) -> InstantiationResult` — resolves variables, lists files (optionally filtered by category), reads each `src` template from `bundle_dir`, renders with resolved variables, writes to `target_dir / dst`. Creates parent directories. Returns result tracking.

- [ ] **Step 1: Write failing tests**

Add `InstantiationResultTests` and `InstantiateTemplateTests`.

`InstantiateTemplateTests` (use temp dirs for bundle and target):

| Test | Scenario | Expected |
|---|---|---|
| `test_basic_instantiation` | one template file, all vars provided | file written at dst, content rendered |
| `test_creates_parent_dirs` | dst path has nested directories | directories created |
| `test_multiple_files` | two files in one category | both written |
| `test_multiple_categories` | files in two categories | all written |
| `test_filter_by_category` | category filter provided | only that category's files written |
| `test_rendered_content` | template has `$product_name` | rendered with variable value |
| `test_result_tracks_written` | successful write | `result.written` contains dst path |

Fixture: create a temp bundle dir with a manifest and a `.tmpl` file containing `$product_name`.

- [ ] **Step 2: Implement InstantiationResult + instantiate_template**

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py -v`

- [ ] **Step 4: Commit**

`feat(seed-renderer): add core template instantiation`

---

### Task 10: Instantiation Safeguards

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_renderer.py`
- Modify: `tests/test_seed_renderer.py`

**Interfaces:**
- Enhances `instantiate_template` with:
  - **skip mode**: if `on_conflict == "skip"` and dst file exists, skip and record in `result.skipped`
  - **overwrite mode**: if `on_conflict == "overwrite"`, write even if dst exists
  - **path safety**: dst must not escape `target_dir` (path traversal via `..`); raises `SeedRenderError`
  - **src must be within bundle_dir**: raises `SeedRenderError` on traversal

- [ ] **Step 1: Write failing tests**

Add `InstantiationSafeguardTests`:

| Test | Scenario | Expected |
|---|---|---|
| `test_skip_existing_file` | dst exists, on_conflict="skip" | file not overwritten, in `result.skipped` |
| `test_overwrite_existing_file` | dst exists, on_conflict="overwrite" | file overwritten, in `result.written` |
| `test_dst_path_traversal_blocked` | dst is `"../../etc/passwd"` | raises `SeedRenderError` |
| `test_src_path_traversal_blocked` | src is `"../../secrets.py"` | raises `SeedRenderError` |
| `test_missing_src_recorded_as_error` | src file doesn't exist in bundle | error recorded in `result.errors` |

- [ ] **Step 2: Implement safeguards**

Add path resolution + safety checks inside `instantiate_template`. Follow the `_ensure_within` pattern from `product_profile.py:464` — `Path.resolve()` + `relative_to()` for containment, raising on escape.

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py -v`

- [ ] **Step 4: Commit**

`feat(seed-renderer): add instantiation safeguards`

---

## Phase 4: MSME ERP Template Bundle

### Task 11: MSME ERP Manifest

**Files:**
- Create: `skills/bmad-story-automator/data/templates/msme-erp-golden-template/manifest.json`
- Modify: `tests/test_seed_template.py`

**Interfaces:**
- Produces: a manifest declaring six categories (`contracts`, `network`, `resilience`, `factories`, `har`, `observability`), with TEA fragment provenance (`tea_fragment` field), variable definitions (`product_name`, `service_prefix`, `health_port`, `otel_endpoint`, `pact_broker_url`, `db_name`), and file entries for 10 template files.

- [ ] **Step 1: Write test validating manifest**

Add `MsmeErpManifestTests` to `tests/test_seed_template.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_manifest_loads_and_validates` | load via `load_template_manifest` with real bundle | passes validate_manifest |
| `test_manifest_has_expected_categories` | check category names | contains all six categories |
| `test_manifest_version` | check template_version | `"1.0.0"` |
| `test_manifest_has_variables` | check variables dict | has `product_name`, `service_prefix` as required |

These tests import and call the actual `load_template_manifest` against the real bundle dir (not mocked).

- [ ] **Step 2: Create manifest.json**

Create `data/templates/msme-erp-golden-template/manifest.json` with all six categories, variable definitions, and file entries.

Category → TEA fragment mapping:
- `contracts` → `pact-consumer-framework-setup.md`
- `network` → `network-first.md`
- `resilience` → `selector-resilience.md`
- `factories` → `data-factories.md`
- `har` → `network-recorder.md`
- `observability` → `null` (factory-native, not TEA-sourced)

- [ ] **Step 3: Verify manifest tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py::MsmeErpManifestTests -v`

Note: bundle validation tests (all src files exist) will fail until template files are created in Tasks 12-13. That's expected.

- [ ] **Step 4: Commit**

`feat(seed-template): add MSME ERP manifest`

---

### Task 12: Contract + Network + HAR Template Files

**Files:**
- Create: `data/templates/msme-erp-golden-template/contracts/conftest.py.tmpl`
- Create: `data/templates/msme-erp-golden-template/contracts/pact_consumer.py.tmpl`
- Create: `data/templates/msme-erp-golden-template/network/network_first.py.tmpl`
- Create: `data/templates/msme-erp-golden-template/network/har_recorder.py.tmpl`

**Content guidelines:**
- **conftest.py.tmpl**: Pact provider/consumer fixture setup. Uses `$service_prefix` for provider name, `$pact_broker_url` for broker. Imports `pact-python`. Defines `pact` fixture with auto-cleanup (publish on teardown).
- **pact_consumer.py.tmpl**: Sample consumer test scaffold. One example test demonstrating request/response expectation pattern. Uses `$service_prefix`.
- **network_first.py.tmpl**: Network-first interception fixture. Pytest fixture that intercepts HTTP requests via `responses` or `pytest-httpx`. Route registration helper. Uses `$service_prefix` for base URL.
- **har_recorder.py.tmpl**: HAR recording fixture. Captures HTTP traffic to `.har` file during test runs. Uses Playwright's `page.route_from_har()` pattern.

All templates should have `$product_name` in header comment, use `$service_prefix` for naming, be syntactically valid Python after rendering (barring missing imports from the product), and include brief inline comments explaining what to customize.

- [ ] **Step 1: Write template rendering tests**

Add `ContractTemplateRenderTests` to `tests/test_seed_renderer.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_conftest_renders` | render with standard vars | contains provider name, no unresolved required vars |
| `test_pact_consumer_renders` | render with standard vars | valid Python-looking output |
| `test_network_first_renders` | render with standard vars | contains base URL |
| `test_har_recorder_renders` | render with standard vars | contains har reference |

Use a shared fixture that provides standard variables.

- [ ] **Step 2: Create template files**

Write the four `.tmpl` files under the appropriate directories.

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py -v`

- [ ] **Step 4: Commit**

`feat(seed-template): add contract, network, and HAR template files`

---

### Task 13: Resilience + Data Factory + Observability Template Files

**Files:**
- Create: `data/templates/msme-erp-golden-template/resilience/selectors.py.tmpl`
- Create: `data/templates/msme-erp-golden-template/factories/factory_base.py.tmpl`
- Create: `data/templates/msme-erp-golden-template/observability/otel_setup.py.tmpl`
- Create: `data/templates/msme-erp-golden-template/observability/health_endpoints.py.tmpl`
- Create: `data/templates/msme-erp-golden-template/observability/slo_config.yaml.tmpl`

**Content guidelines:**
- **selectors.py.tmpl**: Selector resilience helpers. `data-testid` based selector builder. Fallback chain pattern. Uses `$product_name` in docstring.
- **factory_base.py.tmpl**: Data factory base class. Auto-cleanup mixin that tracks created entities and deletes on teardown. Sample entity factory. Uses `$db_name` for connection reference.
- **otel_setup.py.tmpl**: OTel SDK initialization. Configures tracer provider, meter provider, and log handler. Uses `$service_prefix` for service name, `$otel_endpoint` for exporter endpoint.
- **health_endpoints.py.tmpl**: `/healthz` (liveness) and `/readyz` (readiness) endpoint handlers. FastAPI route definitions. Uses `$service_prefix`, `$health_port`.
- **slo_config.yaml.tmpl**: SLO definitions. Availability, latency, error-rate targets. Uses `$service_prefix` for service identification.

- [ ] **Step 1: Write template rendering tests**

Add `ResilienceFactoryObservabilityTemplateTests` to `tests/test_seed_renderer.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_selectors_renders` | standard vars | contains data-testid reference |
| `test_factory_base_renders` | standard vars | contains cleanup reference, db_name |
| `test_otel_setup_renders` | standard vars | contains service name, endpoint |
| `test_health_endpoints_renders` | standard vars | contains healthz, readyz paths |
| `test_slo_config_renders` | standard vars | valid YAML-looking output with service name |

- [ ] **Step 2: Create template files**

Write the five `.tmpl` files under the appropriate directories.

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py -v`

- [ ] **Step 4: Commit**

`feat(seed-template): add resilience, factory, and observability templates`

---

### Task 14: Bundle Integrity Self-Test

**Files:**
- Modify: `tests/test_seed_template.py`

**Interfaces:**
- Validates the MSME ERP bundle is complete: all manifest-referenced files exist, manifest validates, bundle validates with zero missing files.

- [ ] **Step 1: Write integrity tests**

Add `MsmeErpBundleIntegrityTests` to `tests/test_seed_template.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_all_manifest_files_exist` | `validate_bundle` on real bundle | returns empty list |
| `test_manifest_passes_validation` | `validate_manifest` on loaded manifest | no error |
| `test_ref_resolves` | `resolve_template_ref("msme-erp-golden-template@1.0.0")` | valid tuple |
| `test_bundle_dir_resolves` | `resolve_bundle_dir("msme-erp-golden-template")` | existing Path |

These tests run against the actual data files, not mocks. They verify the bundle shipped with the factory is internally consistent.

- [ ] **Step 2: Verify all tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py -v`

- [ ] **Step 3: Commit**

`test(seed-template): add MSME ERP bundle integrity self-tests`

---

## Phase 5: Profile Integration + End-to-End

### Task 15: Profile-to-Template Integration

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/seed_template.py`
- Modify: `tests/test_seed_template.py`

**Interfaces:**
- Produces: `seed_template_for_profile(profile: dict, project_root: str | None = None) -> tuple[dict | None, Path | None]` — reads `profile.seed_template.ref`, loads the template manifest, resolves the bundle dir. Returns `(manifest, bundle_dir)` or `(None, None)` if no seed template is configured (ref is empty or `seed_template` key is absent).

- [ ] **Step 1: Write failing tests**

Add `SeedTemplateForProfileTests` to `tests/test_seed_template.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_profile_with_ref` | MSME ERP profile (real) | returns (manifest, bundle_dir) |
| `test_profile_empty_ref` | profile with `seed_template.ref: ""` | returns (None, None) |
| `test_profile_no_seed_template` | profile without `seed_template` key | returns (None, None) |
| `test_profile_invalid_ref` | profile with invalid ref | raises `SeedTemplateError` |

The first test uses the real MSME ERP profile (integration-style). Others use synthetic profiles.

- [ ] **Step 2: Implement seed_template_for_profile**

- [ ] **Step 3: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py -v`

- [ ] **Step 4: Commit**

`feat(seed-template): add profile-to-template integration`

---

### Task 16: End-to-End Integration Test

**Files:**
- Modify: `tests/test_seed_renderer.py`

**Interfaces:**
- Full round-trip test: load profile → resolve template → instantiate all files → verify output.

- [ ] **Step 1: Write E2E tests**

Add `EndToEndIntegrationTests` to `tests/test_seed_renderer.py`:

| Test | Scenario | Expected |
|---|---|---|
| `test_full_round_trip` | load MSME ERP profile → seed_template_for_profile → instantiate_template to temp dir | all 10 template files written, content rendered, result.written has 10 entries, result.skipped/errors empty |
| `test_round_trip_skip_existing` | pre-create one dst file → instantiate | that file in `result.skipped`, others in `result.written` |
| `test_default_profile_no_op` | default profile (empty ref) → seed_template_for_profile | returns (None, None), no instantiation needed |
| `test_idempotent_skip` | instantiate twice with skip mode | second run: all in `result.skipped` |

Fixture: load the real profile from `data/profiles/msme-erp.json`, use temp dir as target.

- [ ] **Step 2: Verify tests pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_renderer.py::EndToEndIntegrationTests -v`

- [ ] **Step 3: Commit**

`test(seed-template): add end-to-end integration tests`

---

### Task 17: Quality Gate

**Files:** All files from this milestone.

- [ ] **Step 1: Lint all new files**

```
python3 -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/seed_template.py \
  skills/bmad-story-automator/src/story_automator/core/seed_renderer.py \
  tests/test_seed_template.py \
  tests/test_seed_renderer.py
```

- [ ] **Step 2: Format check**

```
python3 -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/seed_template.py \
  skills/bmad-story-automator/src/story_automator/core/seed_renderer.py \
  tests/test_seed_template.py \
  tests/test_seed_renderer.py
```

- [ ] **Step 3: Module size check**

```
wc -l \
  skills/bmad-story-automator/src/story_automator/core/seed_template.py \
  skills/bmad-story-automator/src/story_automator/core/seed_renderer.py
```

Each must be ≤ 500 LOC.

- [ ] **Step 4: Full test suite**

```
npm run test:python
```

All existing tests must still pass.

- [ ] **Step 5: Run both test files in verbose**

```
PYTHONPATH=skills/bmad-story-automator/src python3 -m pytest tests/test_seed_template.py tests/test_seed_renderer.py -v
```

- [ ] **Step 6: Commit if any lint/format fixes were needed**

`style(seed-template): lint and format fixes`
