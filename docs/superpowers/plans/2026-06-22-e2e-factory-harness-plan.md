# Milestone A — End-to-End Factory Self-Evaluation Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL — drive this with `superpowers:subagent-driven-development` (or `superpowers:executing-plans`). Each task is checkbox-tracked. Companion spec: `docs/superpowers/specs/2026-06-22-e2e-factory-harness-design.md`.

**Goal:** Ship `tests/integration/test_factory_self_evaluation.py` + `tests/integration/__init__.py` — a consumer-only end-to-end harness that drives `run_production_gate` against the factory's own working tree using the bundled `default.json` profile and asserts the lifecycle, evidence Merkle export, and audit chain are all intact.

**Architecture:** Two new test files. Zero changes under `skills/`. Zero new dependencies. Single `TestCase` with a `setUpClass` that runs the gate once and ≥ 8 `test_*` methods that assert on the persisted gate file, evidence bundle, and audit chain.

**Tech stack:** Python 3.11+, stdlib + `filelock` + `psutil` (already present). `unittest`. `ruff` for lint.

---

## Pre-requisites

- [ ] Branch is `bma-d/integration-all` and clean (`git status` empty).
- [ ] HEAD baseline: 4070 tests passing, 2 skipped, ruff clean, audit-floor at 24 invariants green. Verify with:
  - `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -q | tail -5`
  - `ruff check skills tests`
- [ ] Repo has a valid HEAD (`git rev-parse HEAD` succeeds).
- [ ] `BMAD_AUDIT_KEY` is writable in the current process env (read-write — needed for audit chain setup).
- [ ] Read the relevant source surface (do not modify):
  - `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — `run_production_gate` signature.
  - `skills/bmad-story-automator/src/story_automator/core/product_profile.py` — `load_bundled_profile`, `compute_profile_hash`.
  - `skills/bmad-story-automator/src/story_automator/core/evidence_io.py` — `load_gate_file`, `load_evidence_bundle`, `compute_evidence_bundle_merkle_root`.
  - `skills/bmad-story-automator/src/story_automator/core/audit.py` — `AuditLog`, `load_key_from_env`.
  - `skills/bmad-story-automator/src/story_automator/core/collector_registry.py` — `CollectorRegistry()`.
  - `skills/bmad-story-automator/data/profiles/default.json` — confirms profile shape.

---

## Task list

### Task 1 — Create `tests/integration/` package and write a smoke-skip harness

**Files:**
- Create `tests/integration/__init__.py`.
- Create `tests/integration/test_factory_self_evaluation.py`.

- [ ] **Step 1.1 — Write the failing test.** Add a `TestFactorySelfEvaluation(unittest.TestCase)` with one method `test_module_imports_cleanly` that imports every consumed public symbol; no `setUpClass` yet. Run:

      PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.integration.test_factory_self_evaluation -v

  Expected: PASS (it's an import smoke test). If FAIL, the symbol surface drifted — stop and reconcile with the spec.

- [ ] **Step 1.2 — Add the package marker.** `tests/integration/__init__.py` contains one line: `"""Integration tests for the gate harness."""`. No code.

- [ ] **Step 1.3 — Confirm collection.** Run:

      PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v 2>&1 | grep test_factory_self_evaluation

  Expected: one or more lines printed → collection works.

### Task 2 — Add `setUpClass` with skip preconditions

- [ ] **Step 2.1 — Write the failing test.** Add `test_setup_class_runs_gate` that asserts `cls.gate_file is not None`. Run; expect FAIL ("`cls.gate_file` AttributeError").

- [ ] **Step 2.2 — Implement `setUpClass`.** Inside the class, add:

  - Import the specifically-caught exception: `from story_automator.core.trust_boundary import TrustBoundaryError`.
  - Resolve `cls.repo_root = Path(__file__).resolve().parents[2]`.
  - Detect HEAD via `subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cls.repo_root, text=True).strip()`; the `.strip()` is REQUIRED — `rev-parse` emits `<sha>\n` and a stale newline poisons the gate_id regex `^[a-zA-Z0-9._-]+$`. Empty stdout (some Windows-git-bash configs) → `raise unittest.SkipTest("git rev-parse HEAD produced empty output")`. On `(FileNotFoundError, subprocess.CalledProcessError)` → `raise unittest.SkipTest("git/HEAD unavailable")`.
  - Build `cls._tmp = tempfile.TemporaryDirectory()` + `cls.project_root = Path(cls._tmp.name) / "factory-self-eval"`; `cls.project_root.mkdir(parents=True)`.
  - **BMAD_AUDIT_KEY save/restore (gap A-05).** Mirror `tests/test_audit_call_sites.py:73`:
    ```python
    cls._saved_audit_key = os.environ.pop("BMAD_AUDIT_KEY", None)
    os.environ["BMAD_AUDIT_KEY"] = "milestone-a-test-secret"
    ```
    NEVER bare-overwrite — that would leak the operator's real secret on teardown.
  - `cls.profile = load_bundled_profile("default")`. **Disable all active categories** (gap A-04) so the empty-registry gate exercises the PASS lifecycle:
    ```python
    _all_active = sorted(set().union(*cls.profile.get("categories", {}).values()))
    cls.profile["categories_na"] = _all_active
    ```
    Then `cls.profile_hash = compute_profile_hash(cls.profile)`.
  - `cls.registry = CollectorRegistry()`.
  - `cls.gate_id = f"factory-self-eval-{cls.commit_sha[:12]}"`.
  - **audit_policy shape (gap A-01).** The wrong shape `{"enabled": True, "path": ...}` silently disables audit:
    ```python
    cls.audit_path = cls.project_root / "audit.jsonl"
    cls.audit_policy = {"security": {"audit_trail": True}}
    ```
    `audit_path` is the SOLE path source; the policy carries the enable flag only.
  - **Gate call wrapped in try/finally** so env restoration is unconditional. Use the full kwarg shape (gap A-03):
    ```python
    try:
        cls.gate_file = run_production_gate(
            cls.project_root, cls.gate_id,
            commit_sha=cls.commit_sha,
            target={"kind": "repo", "id": "bmad-story-automator"},
            profile=cls.profile,
            factory_version="milestone-a",   # DELIBERATELY hand-coded — not resolve_factory_version()
            registry=cls.registry,
            priority="P1",
            tier="code",                     # explicit; protects against tier-vocab drift
            audit_policy=cls.audit_policy,
            audit_path=cls.audit_path,
        )
    except TrustBoundaryError as exc:
        # SPECIFICALLY caught — bare `except RuntimeError` would swallow real
        # wiring bugs (gate raises RuntimeError on lock timeouts and marker
        # corruption that we MUST see).
        raise unittest.SkipTest(f"host context rejects gate: {exc}") from exc
    ```
  - Outer wrap: re-raise `unittest.SkipTest` unmodified; catch only narrowly-scoped sandbox exceptions (`(FileNotFoundError, PermissionError)`) → `raise unittest.SkipTest("…")` with a precise reason. **DO NOT** broaden to `except Exception` or `except RuntimeError` — that swallows real bugs.

- [ ] **Step 2.3 — Implement `tearDownClass`.** Restore the prior `BMAD_AUDIT_KEY` via the canonical pattern (gap A-05):
  ```python
  os.environ.pop("BMAD_AUDIT_KEY", None)
  if cls._saved_audit_key is not None:
      os.environ["BMAD_AUDIT_KEY"] = cls._saved_audit_key
  cls._tmp.cleanup()
  ```
  Avoid `os.environ["BMAD_AUDIT_KEY"] = cls._saved_audit_key` when `_saved_audit_key is None` — that's a `TypeError`.

- [ ] **Step 2.4 — Re-run the test.** Expect PASS in non-sandboxed envs; expect SKIP (with a clear reason) in sandboxes lacking `git` or write-env.

### Task 3 — Assert shape of the returned gate file

- [ ] **Step 3.1 — Add `test_gate_returns_dict`.** Failing first (delete the body, leave `self.fail`). Verify FAIL, then implement: `self.assertIsInstance(self.gate_file, dict)`.

- [ ] **Step 3.2 — Add `test_overall_verdict_in_closed_vocabulary`.** `self.assertIn(self.gate_file["overall"], {"PASS", "CONCERNS", "FAIL", "WAIVED"})`.

- [ ] **Step 3.3 — Add `test_gate_id_round_trips_through_load_gate_file`.** `reloaded = load_gate_file(self.project_root, self.gate_id)`; assert `reloaded["gate_id"] == self.gate_id`.

- [ ] **Step 3.4 — Add `test_gate_file_carries_factory_version`.** `self.assertEqual(self.gate_file.get("factory_version"), "milestone-a")`.

- [ ] **Step 3.5 — Add `test_profile_hash_recorded_on_gate_file`.** Anchored to `verdict_engine.evaluate_gate`'s explicit profile-projection rewrite (gap A-02):
  ```python
  # verdict_engine rewrites gate_file["profile"] to {"id": ..., "hash": ...}
  # at evaluation time. DO NOT assert equality on the full input profile dict;
  # the persisted projection is a 2-key view and full-equality will fail.
  self.assertEqual(self.gate_file["profile"]["hash"], self.profile_hash)
  ```
  If the projection schema ever changes, this assertion and `validate_gate_file` need a coordinated update — they are coupled by design.

### Task 4 — Assert Merkle export shape

- [ ] **Step 4.1 — Add `test_merkle_root_shape_64_hex_or_empty_sentinel`.** Failing first. Implement using a `re.fullmatch(r"^[0-9a-f]{64}$", root)` check OR `root == ""`. Document the sentinel branch in a one-line comment referencing spec §Design / "Empty-registry caveat".

### Task 5 — Assert audit chain integrity

- [ ] **Step 5.1 — Add `test_audit_chain_verifies_after_gate`.** Open `AuditLog(self.audit_path, key=load_key_from_env())`; call `ok, last_seq = log.verify()`; assert `ok is True` and `last_seq >= 1`. (The orchestrator emits `GateStartedAudit` at minimum, so seq is always ≥ 1 on a healthy run.)

### Task 6 — Determinism / reuse-path test

- [ ] **Step 6.1 — Add `test_second_invocation_returns_reused_gate_file`.** Inside the test (not setUpClass — this needs the same args, replaying the call). Per gap A-09, gate_id + Merkle equality alone are insufficient (a buggy re-run that recomputed identical bytes would silently pass). Strengthen the assertion by one of:
  - **Option A — mtime check** (preferred — no mock):
    ```python
    gate_path = self.project_root / "_bmad" / "gate" / "verdicts" / f"{self.gate_id}.json"
    mtime_before = gate_path.stat().st_mtime_ns
    result = run_production_gate(...)  # same args
    self.assertEqual(result["gate_id"], self.gate_id)
    self.assertEqual(result["evidence_merkle_root"], self.gate_file["evidence_merkle_root"])
    self.assertEqual(gate_path.stat().st_mtime_ns, mtime_before,
                     "reuse path must not rewrite the persisted gate file")
    ```
  - **Option B — mock `_run_collectors`** (use only if Option A flakes on coarse-mtime filesystems):
    ```python
    with patch("story_automator.core.gate_orchestrator._run_collectors") as run_cols:
        run_production_gate(...)
        run_cols.assert_not_called()
    ```
  Pick Option A unless a Windows/WSL CI run shows mtime-granularity flakes.

### Task 7 — Lint, format, and LOC sanity

- [ ] **Step 7.1 — Lint.** Run `ruff check tests/integration/` and `ruff format --check tests/integration/`. Fix any complaints.

- [ ] **Step 7.2 — LOC budget.** `wc -l tests/integration/*.py` ≤ 350 combined. If approaching the cap, prune comments — do not split files.

- [ ] **Step 7.3 — Audit-floor.** Run `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_regression -v` → 24 invariants green.

### Task 8 — Full-suite green + smoke

- [ ] **Step 8.1 — Full Python suite.** `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests` — should report 4078+ run, 8+ new, 2 skipped (baseline preserved; the harness may add 0–2 skips depending on env).

- [ ] **Step 8.2 — npm verify.** `npm run verify` — green end-to-end (test:python + pack:dry-run + test:cli + test:smoke).

- [ ] **Step 8.3 — Determinism eyeball.** Re-run the harness twice locally; confirm `gate_id` and `evidence_merkle_root` are identical across runs.

### Task 9 — Commit + tag + archive

- [ ] **Step 9.1 — Stage only the two new files.**

      git add tests/integration/__init__.py tests/integration/test_factory_self_evaluation.py docs/superpowers/specs/2026-06-22-e2e-factory-harness-design.md docs/superpowers/plans/2026-06-22-e2e-factory-harness-plan.md

  Verify with `git status` — only those four paths staged. No `git add -A`.

- [ ] **Step 9.2 — Commit.** Conventional Commits subject + body:

      test(integration): milestone-a — factory self-evaluation harness

      Drive run_production_gate against the factory's own working tree
      using bundled default.json. Eight new assertions cover lifecycle,
      Merkle export, audit-chain integrity, and reuse-path determinism.
      Consumer-only: zero changes under skills/, zero new deps.

      Generated-By: claude-opus-4-7
      Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- [ ] **Step 9.3 — Tag.** `git tag milestone-a-e2e-harness` (lightweight, traceability).

- [ ] **Step 9.4 — Archive workflow.** If `.claude/workflows/` is the session archive root, drop a thin marker recording the milestone (matches the pattern of D-04 / N6.x workflows). Out of scope to design that here; reuse the existing convention.

- [ ] **Step 9.5 — Do NOT push.** Branch hygiene: stay on `bma-d/integration-all`; the integration PR (separate milestone) collects everything.

---

## Test files to author

| Path | Purpose | LOC target |
|---|---|---|
| `tests/integration/__init__.py` | Mark `tests/integration` as a discoverable package. | 1 |
| `tests/integration/test_factory_self_evaluation.py` | The harness `TestFactorySelfEvaluation` with `setUpClass`, `tearDownClass`, and ≥ 8 `test_*` methods listed in the spec acceptance section. | ≤ 300 |

---

## Commit + tag spec

- **Commit type:** `test(integration):` (Conventional Commits).
- **Single commit** that adds the four files (two test files + two doc files).
- **Trailers (required):**
  - `Generated-By: claude-opus-4-7`
  - `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- **Tag:** `milestone-a-e2e-harness` (lightweight, pointing at the commit).
- **No push.** Land on `bma-d/integration-all` locally only.

---

## Rollback plan

If any task fails after commit:

1. **Localised revert (preferred).** `git revert <sha>` creates a `revert: test(integration): milestone-a` commit on the same branch. Keep the spec + plan in tree as historical reference; only the test code is removed by the revert. Rationale: spec/plan stay valuable for the next attempt.

2. **Hard rollback (only if revert is blocked).** Restricted to operator (per guardrails: "DO NOT run destructive git commands unless the user explicitly requests"). If needed:
   - Identify the SHA: `git log --oneline -1`.
   - Operator runs: `git reset --hard HEAD~1` after explicit instruction.
   - Re-confirm baseline: `python -m unittest discover -s tests -q` → 4070 + 2 skipped, ruff clean.

3. **Tag cleanup.** `git tag -d milestone-a-e2e-harness` if the tag was created before the failed verify; do not delete remote refs (the tag never left local).

4. **Audit-floor restoration.** If `test_audit_regression` regressed, the revert restores it automatically; verify with `python -m unittest tests.test_audit_regression`.

5. **Partial failure during implementation (pre-commit).** No rollback needed — uncommitted files can be discarded with `git restore --staged tests/integration/ docs/superpowers/...` followed by `rm` of the new files. (Only after explicit operator request — `restore` is destructive per guardrails.)

---

## Done-definition

- `tests/integration/__init__.py` and `tests/integration/test_factory_self_evaluation.py` committed on `bma-d/integration-all`.
- `git log -1 --format=%B` shows both required trailers.
- `git tag --list 'milestone-*'` lists `milestone-a-e2e-harness`.
- `python -m unittest discover -s tests` reports 4078+ passed, ≤ 4 skipped, 0 failed.
- `ruff check tests` clean.
- `python -m unittest tests.test_audit_regression` reports 24+ invariants green.
- `npm run verify` green.
- No file outside `tests/integration/` or `docs/superpowers/` modified.

---

*Plan companion to spec `2026-06-22-e2e-factory-harness-design.md`. Treat the spec as ground truth on scope and constraints; this plan only sequences the execution.*
