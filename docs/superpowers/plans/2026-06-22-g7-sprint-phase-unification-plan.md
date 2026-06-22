# G7 — Sprint-Phase Dual-Store Unification — Implementation Plan

> Date: 2026-06-22 · Status: **Draft for execution** · Milestone: **D (G7)** · Branch: `bma-d/integration-all` · Spec: `docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md`.
> Strategy: TDD, additive-only. One new module + one extended `__init__` + one new test file + one changelog entry. No edits to M48's frozen surface, no edits to `telemetry_events.py`, no new deps.

## Pre-requisites

- **Branch state**: `git status` clean on `bma-d/integration-all`; HEAD at the post-D-04-followup commit (≥ `6a957d2` or later). Verified by `git log -1 --format=%H`.
- **Baseline gates green**:
  - `python -m unittest discover -s tests -v 2>&1 | tail -5` reports `4070 passing, 2 skipped`.
  - `python -m ruff check skills tests` exits 0.
  - `python -m unittest tests.test_audit_regression -v 2>&1 | tail -3` shows the audit-floor invariant count `≥ 24`.
- **Read in full** before touching any file:
  - `skills/bmad-story-automator/src/story_automator/core/integration/sprint_phase_map.py` (M48 — the frozen surface that G7 wraps).
  - `skills/bmad-story-automator/src/story_automator/core/sprint.py` (`sprint_status_get` — read side of sprint-status).
  - `skills/bmad-story-automator/src/story_automator/core/artifact_paths.py` (`implementation_artifacts_dir`, `sprint_status_path` — where files live).
  - `skills/bmad-story-automator/src/story_automator/core/utils.py` (`write_atomic`, `read_text`, `file_exists`, `trim_lines` — the I/O primitives).
  - `skills/bmad-story-automator/src/story_automator/core/integration/__init__.py` (existing exports — extend, do not rewrite).
- **Spec acceptance** committed: confirm §6.1 / §6.2 / §6.3 of the design spec match the test plan below 1:1.
- **No conflicting work in flight**: `git diff` empty; no untracked Python files under `core/integration/`.

## Task list

### Phase 0 — Spec confirmation (no code)

- [ ] **0.1** Re-read `docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md` §2 (decisions) and §6 (acceptance) once more. If any decision contradicts the existing M48 invariants, **stop** and escalate; do not patch the spec mid-implementation.
- [ ] **0.2** Confirm the existing test fixture pattern: open `tests/test_sprint_phase_map.py` and identify the `tempfile.TemporaryDirectory` + `implementation_artifacts_dir(tmp).mkdir(parents=True)` idiom; G7's tests will follow exactly that style for fixture setup.

### Phase 1 — Failing tests (TDD red phase)

- [ ] **1.1** Create `tests/test_unified_state.py` with the module docstring + imports skeleton; do **not** add any test bodies yet.
- [ ] **1.2** Author **all 12 tests from §6.2 of the spec**, each marked `@unittest.expectedFailure` with a TODO comment stating "remove decorator in Phase 2 step 2.N". Tests must reference the not-yet-existent symbols `read_unified_state`, `write_unified_state`, `UnifiedStateError`, `unified_state_lock` from `story_automator.core.integration.unified_state`.
- [ ] **1.3** Run `python -m unittest tests.test_unified_state -v`; confirm all 12 tests fail with `ImportError: cannot import name 'read_unified_state' ...` (this is the desired RED state).
- [ ] **1.4** Run `python -m unittest discover -s tests 2>&1 | tail -3`; confirm 4070 existing tests still pass + 12 new tests in expected-failure state. **No regression.**

### Phase 2 — Module skeleton (minimal green)

- [ ] **2.1** Create `skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py`. **Required order**: (1) module docstring describing G7 purpose and LWW semantics (≥ 30 lines, matching M48's docstring depth), (2) `from __future__ import annotations`, (3) stdlib imports, (4) `filelock` import, (5) local imports from M48 + `core.sprint` + `core.utils` + `core.artifact_paths` + `core.story_keys`.
- [ ] **2.2** Add the `UnifiedStateError(ValueError)` class with docstring explaining it is **not** a subclass of M48's `DualStoreError` (they sit side-by-side).
- [ ] **2.3** Add `unified_state_lock(project_root)` returning `filelock.FileLock(<implementation_artifacts_dir>/.unified-state.lock)`.
- [ ] **2.4** Add `read_unified_state(project_root, story_key) -> tuple[str, str]` skeleton with **only the happy-path implemented**: read sprint-status, read phase store, if both present and `is_consistent(...)` return `(status, phase.value)`. Raise `UnifiedStateError` for missing sprint row. **Stub** the repair branches with `raise NotImplementedError("phase 3")`.
- [ ] **2.5** Add `write_unified_state(project_root, story_key, sprint_status, phase, *, lock_timeout=10.0)` skeleton: validate pair via `is_consistent`, acquire lock with timeout (catching `filelock.Timeout` → `UnifiedStateError`), call `write_phase` (M48) for the phase side, **stub** the sprint-status row mutation with `raise NotImplementedError("phase 3")`.
- [ ] **2.6** Wire `read_unified_state`, `write_unified_state`, `UnifiedStateError`, `unified_state_lock` into the module's `__all__`.
- [ ] **2.7** Extend `core/integration/__init__.py` to re-export those four symbols. **Do not** remove any existing export.
- [ ] **2.8** Remove `@unittest.expectedFailure` from the happy-path tests (#1, #4, #7, #9, #11, #12 from §6.2). Run `python -m unittest tests.test_unified_state -v`; confirm those 6 tests now PASS while the remaining 6 still RED via `NotImplementedError`.

### Phase 3 — Repair branches + atomic sprint-status writer

- [ ] **3.1** Implement `_write_sprint_status_row(project_root, story_key, new_status)` — **the first sprint-status writer in the codebase** (gap D01; the prior plan assumed an orchestrator writer that does not exist). Contract:
   - Read full sprint-status YAML via `read_text(sprint_status_path(project_root))`. If the path does not exist, raise `UnifiedStateFileMissingError(...)` (gap D09).
   - Locate the matching row via a regex anchored at line-start that captures the key + status + optional trailing comment/whitespace (mirror `_PHASE_LINE` style — re-read M48 for the canonical pattern).
   - If the row is absent, raise `UnifiedStateRowMissingError(...)` (gap D09 — NO auto-creation of rows; that's the orchestrator's job).
   - Mutate ONLY the matching row in-text — replace the status value, preserve the key, preserve the trailing comment/whitespace (gap D13/D22). DO NOT YAML-roundtrip the document (the codebase has zero `import yaml` per gap D02 / CLAUDE.md guardrail).
   - Write via `write_atomic` (temp file in destination dir + `os.replace`).
   - **Round-trip verification** (replaces the `validate_sprint_status` call from the earlier plan — gap D02): re-parse via `sprint_status_get(project_root, story_key)` and assert `state.status == new_status`; raise `UnifiedStateError` if the round-trip fails (defensive — catches regex / atomicity bugs immediately).
   - **Hold the caller's filelock**; do not re-acquire.
- [ ] **3.2** Implement `_resolve_lww(project_root, story_key, sprint_state, phase_value)`:
   - **Same-volume precondition** (gap D03): assert `phase_store_path(root).stat().st_dev == sprint_status_path(root).stat().st_dev`; if not equal, raise `UnifiedStateError("cross-filesystem unified state not supported; phase store and sprint-status must share a volume")`.
   - Compare `sprint_status_path(root).stat().st_mtime_ns` vs `phase_store_path(root).stat().st_mtime_ns`; the later-mtime store wins.
   - **Tie-break (gap D08)**: if mtimes are EQUAL, prefer the entry whose status is in `TERMINAL_PHASES`; if neither or both are terminal, phase store wins (legacy default — per spec §2 / R5).
   - Project the loser via `phase_for_sprint_status` / `sprint_status_for_phase`; acquire lock; write the projection; return the winner's pair.
- [ ] **3.3** Implement the "missing phase entry" branch in `read_unified_state`: derive via `phase_for_sprint_status`; if `None` (unknown status), return `(raw_status, "pending")` **without writing**; else acquire lock + write phase store via `write_phase` + return projected pair.
- [ ] **3.4** Implement the "both present but inconsistent" branch in `read_unified_state`: call `_resolve_lww`; return its result.
- [ ] **3.5** Replace the `NotImplementedError("phase 3")` stub in `write_unified_state` with the full atomic writer (gaps D01, D10):
   - Acquire `unified_state_lock(project_root)` with `timeout=lock_timeout`; catch `filelock.Timeout` → re-raise as `UnifiedStateError("timeout=...")`.
   - **Slug-key reconciliation** (gap D10): call `sprint_status_get(project_root, story_key)` to resolve to the canonical `sprint.story` key. If the phase store has an entry under a descriptive slug (e.g., `1-1-host-feasibility-probe`) but the canonical id is `1.1`, delete the slug-keyed entry as part of the same write.
   - Validate `(sprint_status, phase)` consistency via `is_consistent(...)`; raise `UnifiedStateError` if not.
   - Write the phase store FIRST via `write_phase(...)` (M48 API), under the canonical key.
   - Write sprint-status SECOND via `_write_sprint_status_row(project_root, story_key, sprint_status)`.
   - Release lock (context-manager exit).

   The write order (phase first, sprint-status second) is REVERSED from read order (sprint-status first, phase second) — gap D05. Both orders must be cited as inline code comments.
- [ ] **3.6** Implement the `observe_only=True` branch in `read_unified_state` (gap D07): when set, the function NEVER writes — no migration on legacy stores, no LWW repair. Returns a 3-tuple `(sprint_status, phase, needs_repair: bool)` where `needs_repair=True` flags that the on-disk state is divergent. Add the docstring warning: "Calling this function with the default observe_only=False may write to disk; pass observe_only=True for read-only callers." All write paths in `read_unified_state` are gated behind an `if not observe_only:` check.

- [ ] **3.7** Implement the stat-twice-or-retry pattern in `read_unified_state` (gap D04). After reading sprint-status + phase (in that order — gap D05), re-stat both files; if either mtime is newer than the at-read-start stat, restart the read. Cap at 3 attempts; after 3, acquire `unified_state_lock(...)` briefly to take a serialised snapshot under the lock, then release. Document the consistency model in the public docstring.

- [ ] **3.8** Differentiate the two error subclasses (gap D09): `UnifiedStateFileMissingError(UnifiedStateError)` for file-absent; `UnifiedStateRowMissingError(UnifiedStateError)` for row-absent-in-existing-file. Update all `raise` sites in the module.

- [ ] **3.9** Remove the remaining `@unittest.expectedFailure` decorators from tests #2, #3, #5, #6, #8, #10, plus the new gap-report tests #13-#17 (and the split #4 → #4a/#4b). Run `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_unified_state -v`; **all 17 tests PASS**.

### Phase 4 — Quality gates + audit-floor invariant

- [ ] **4.1** Run `python -m ruff check skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py tests/test_unified_state.py`; resolve any findings (typical: docstring formatting, import order — fix in-place, do not silence with `# noqa`).
- [ ] **4.2** Run `python -m ruff format --check skills tests`; if formatting drift, apply `python -m ruff format <files>` and verify the diff is whitespace-only.
- [ ] **4.3** `wc -l skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py`: confirm ≤ 500. If 480–500, split repair helpers into `core/integration/_unified_state_repair.py` (private sibling). If > 500, **stop** and revisit before commit.
- [ ] **4.4** Extend `tests/test_audit_regression.py` (only the invariant list; never the harness): add the new invariant string `"unified-state-write-isolation: only unified_state.py writes to both stores in the same call"` so the audit-floor count rises from 24 → 25. Implement the AST/grep check per gap D11 — **re-phrased to give it real teeth**: "any module that imports `write_phase` from `sprint_phase_map` AND `sprint_status_file` from `story_keys` MUST also import `unified_state_lock` OR equal `core/integration/unified_state.py` itself". Add a **positive-failure test** (a fixture module that violates the invariant), confirm the check trips on the fixture, then remove the fixture — this proves the invariant has real coverage rather than being vacuously true.

- [ ] **4.4b** Append a new `### core/integration/unified_state.py` section to `docs/spec/frozen-gate-surface.md` (gap D06) declaring all four public functions + the two error subclasses:
   ```
   ### core/integration/unified_state.py
   - read_unified_state(project_root, story_key, *, observe_only=False)
       -> tuple[str, str] | tuple[str, str, bool]
       Reads (sprint_status, phase) atomically; with observe_only=True, never writes.
       Read order is REVERSED from write order (sprint-status first, phase second)
       to pair correctly with the writer's phase-first commit order.
   - write_unified_state(project_root, story_key, sprint_status, phase,
                         *, lock_timeout=10.0) -> None
       Atomically writes both stores under unified_state_lock; resolves story_key
       to canonical sprint.story id; deletes orphan slug-keyed entries.
   - unified_state_lock(project_root) -> filelock.FileLock
       Per-project lock at <implementation_artifacts_dir>/.unified-state.lock.
       Exposed for advanced callers needing to bracket multi-row updates.
   - UnifiedStateError(ValueError): base; raised on consistency/timeout/cross-fs.
   - UnifiedStateFileMissingError(UnifiedStateError): sprint-status / phase store file absent.
   - UnifiedStateRowMissingError(UnifiedStateError): file present but row absent.
   ```
   Behavioral invariants: (a) read order = reverse of write order; (b) LWW by mtime with `st_dev` same-volume precondition; (c) mtime-tie → terminal phase wins, else phase store wins; (d) observe_only=False may write to disk (migration / repair); observe_only=True never writes; (e) writer is text-only on sprint-status (no YAML re-serialisation).
- [ ] **4.5** Run `python -m unittest tests.test_audit_regression -v 2>&1 | tail -5`; confirm 25 invariants pass.
- [ ] **4.6** Run the full suite: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests 2>&1 | tail -3`. Confirm `4070 + 17 = 4087` tests passing, 2 skipped.
- [ ] **4.7** Run `bash scripts/smoke-test.sh` if present; verify exit 0 (npm-pack smoke). If the script is absent on this branch, **fail and ask for guidance** (gap D27 — do NOT silently skip; `scripts/smoke-test.sh` is part of `npm run verify`, and silently skipping degrades the verify gate).

### Phase 5 — Docs + changelog

- [ ] **5.1** Author `docs/changelog/2026-06-22-g7-unified-state.md` with heading `## 260622 - [FULL] G7 sprint-phase dual-store unification`. Sections: `### Summary`, `### Added` (the four new public symbols), `### Files` (new + modified file list), `### QA Notes` (12 new tests, audit-floor lift to 25, ruff clean, full suite green, M48 frozen surface preserved).
- [ ] **5.2** Run `python -m unittest tests.test_changelog_*` (if such tests exist) to confirm the heading parses; otherwise visually inspect via `Read`.

### Phase 6 — Guardrail audit

- [ ] **6.1** `git diff --stat skills/bmad-story-automator/src/story_automator/core/integration/sprint_phase_map.py` — must be **empty** (M48 frozen).
- [ ] **6.2** `git diff --stat skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` — must be **empty** (M01 owns it).
- [ ] **6.3** Banned-dep check — derive the whitelist from `sys.stdlib_module_names` instead of a hand-typed list (gap D18 — `errno`, `stat`, `shutil`, `signal` were legitimate but missing):
   ```
   PYTHONPATH=skills/bmad-story-automator/src python -c '
   import re, sys
   stdlib = sys.stdlib_module_names
   allow = stdlib | {"filelock", "psutil", "story_automator", "__future__"}
   text = open("skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py").read()
   imports = re.findall(r"^(?:import|from)\s+([\w.]+)", text, re.MULTILINE)
   bad = [m for m in imports if m.split(".")[0] not in allow]
   if bad: print("BAD:", bad); sys.exit(1)
   print("OK — no banned deps")
   '
   ```
   Exit code 0 expected.
- [ ] **6.4** Confirm conventional-commit subject and `Generated-By:` trailer ready for the commit step.

### Phase 7 — Commit + tag

- [ ] **7.1** Stage exactly: `unified_state.py`, `_unified_state_repair.py` (if the pre-authorized split happened per gap D12), `__init__.py` (integration package), `docs/spec/frozen-gate-surface.md` (per gap D06 / step 4.4b), `tests/test_unified_state.py`, `tests/test_audit_regression.py`, `docs/changelog/2026-06-22-g7-unified-state.md`. **No** `git add -A`.
- [ ] **7.2** Commit via heredoc (commit-lint-safe — simple hyphen in subject per gap D24, NOT em-dash, so CI normalization doesn't desync the trailer):
   ```
   feat(integration): G7 - sprint-phase dual-store unification

   Adds core/integration/unified_state.py with read_unified_state(),
   write_unified_state(), and unified_state_lock() - a single source
   of truth on top of M48's sprint_phase_map. Reads are lock-free in
   the happy path; writes serialize via .unified-state.lock; conflicts
   resolve via mtime LWW with terminal-phase tie-break and same-volume
   precondition. Legacy single-store projects auto-upgrade on first
   read; observe_only=True provides a read-only audit path. The first
   sprint-status writer ships here (text-only regex mutation, no YAML
   re-serialisation, preserves all non-target lines byte-exact). M48
   frozen surface untouched.

   New tests: 17 in tests/test_unified_state.py.
   Audit-floor invariants: 24 -> 25 (with positive-failure verification).

   Generated-By: claude-opus-4-7
   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   ```
- [ ] **7.3** Tag `compat-g7-unified-state` at the new HEAD via `git tag -a compat-g7-unified-state -m "G7 sprint-phase dual-store unification"`.
- [ ] **7.4** Confirm via `git log --oneline -3` that the commit and tag are in place. **Do not push** (per workflow guardrail — pushing is operator-driven).

## Test files to author

- **New**: `tests/test_unified_state.py` (~320 LOC, 12 tests; see §6.2 of the spec for exact names).
- **Modified**: `tests/test_audit_regression.py` (+1 invariant — the 25th — for unified-state write isolation; ~15 LOC delta).
- **Modified** (declarative only): no other test files. M48's existing `tests/test_sprint_phase_map.py` continues to pass unchanged — this is the proof of frozen-surface preservation.

## Commit + tag spec

- **Branch**: `bma-d/integration-all` (work directly; no worktree).
- **Subject**: `feat(integration): G7 — sprint-phase dual-store unification` (Conventional Commits, 60 chars).
- **Body**: as in step 7.2 above.
- **Trailers**:
  - `Generated-By: claude-opus-4-7`
  - `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- **No** `--amend`, no `--no-verify`, no force-push.
- **Tag**: `compat-g7-unified-state` (annotated, message `"G7 sprint-phase dual-store unification"`).
- **No PR creation** — the orchestrator handles PR semantics. Stop after tag.

## Rollback plan

If Phase 4 or Phase 6 surfaces an unrecoverable guardrail breach **before commit**:

- [ ] Run `git restore --staged --worktree skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py skills/bmad-story-automator/src/story_automator/core/integration/__init__.py tests/test_unified_state.py tests/test_audit_regression.py docs/changelog/2026-06-22-g7-unified-state.md` to revert the working tree.
- [ ] `rm` any untracked files left behind (`unified_state.py`, `_unified_state_repair.py` if split).
- [ ] Confirm via `git status` that the tree is clean.
- [ ] Re-baseline: `python -m unittest discover -s tests 2>&1 | tail -3` reports 4070 passing.

If the commit already landed but a downstream regression appears:

- [ ] **Do not** force-push or amend. Author a follow-up revert commit: `git revert <sha>` with a Conventional Commits revert subject.
- [ ] Re-run the full suite + ruff + audit-floor after the revert.
- [ ] Document the root cause in `docs/audit/g7-rollback.md` for the post-mortem.

If the audit-floor invariant in Phase 4.4 turns out to be too brittle (false positives on legitimate code):

- [ ] Tighten the invariant string-match (e.g., scope to `core/integration/` only).
- [ ] If still brittle, **drop the new invariant entirely** rather than weaken existing ones; the floor returns to 24 and a follow-up plans a more robust check.

## Definition of done

1. `tests/test_unified_state.py` exists and all 12 tests pass.
2. `python -m unittest discover -s tests 2>&1 | tail -3` reports ≥ 4082 passing, 2 skipped.
3. `python -m ruff check skills tests` exits 0.
4. `python -m unittest tests.test_audit_regression -v` reports ≥ 25 invariants passing.
5. `wc -l skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py` ≤ 500.
6. `git diff --stat skills/bmad-story-automator/src/story_automator/core/integration/sprint_phase_map.py` is empty.
7. `git diff --stat skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` is empty.
8. Commit `feat(integration): G7 — sprint-phase dual-store unification` exists with both required trailers.
9. Tag `compat-g7-unified-state` points to the new HEAD.
10. Changelog entry `docs/changelog/2026-06-22-g7-unified-state.md` is present, conforms to the M11 controlled-vocabulary `[FULL]` tag, and lists the four new public symbols.
