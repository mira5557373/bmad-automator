# Smoke expansion + K-5 quarantine-rmtree — status report

> Workflow: `smoke-expand-and-k5` (serial: A-follow-2 e2e widening → K-5 deferred round-3 fix)
> Branch: `bma-d/integration-all`
> Baseline at start: `cdc7ee5` (r3-deferred-batch workflow archive, 4150 tests green)
> Tip at finish: `ee215b8` (4167 tests green)

## TL;DR

Two follow-ups landed serially on `bma-d/integration-all`:

- **Smoke expansion (A-follow-2)** — extends the Milestone-A factory
  self-evaluation harness from a one-active-category PASS proof to a
  three-active-category matrix that drives `run_production_gate` through
  correctness + static + docs in a single run, including a real
  end-to-end negative path (one category fails → overall verdict demotes
  off PASS). Catches multi-category-only regression classes the
  one-active harness cannot: verdict aggregation across mixed-status
  records, per-category Merkle determinism, and one
  `EvidenceCollected` audit event per collector.
- **K-5 (`bug-c-deferred-rmtree-under-lock`)** — `recover_from_crash`
  previously held the gate lock across `shutil.rmtree` of orphan
  evidence directories. On slow storage and/or large evidence bundles,
  that blocked every concurrent `run_production_gate` /
  `run_system_gate` caller on the same `project_root` for seconds at a
  time. K-5 splits the cleanup into (a) `os.rename` into
  `_bmad/gate/cleanup/<gate_id>-<uuid4>/` under the lock, (b)
  `shutil.rmtree` outside the lock, plus a startup janitor that sweeps
  leftover quarantine subdirs at the next `run_production_gate` /
  `run_system_gate` entry. Closes the last round-3 deferred concurrency
  smell.

Tests rose 4150 → 4167 (+17). Ruff clean. Audit-floor invariants still
26-green. No frozen-surface symbol changed. No new dependency.

## Smoke expansion outcome (3 categories now active; negative-path coverage)

Commit `3d462f6` — `feat(integration): A-follow-2 — smoke expanded to 3 categories with negative-path coverage`.

**What it adds**

- New profile fixture `tests/integration/data/profiles/smoke_3cat.json`
  — three active categories (`correctness`, `static`, `docs`), each at
  the P1 matrix at 90% coverage, all other categories under the closed
  registry marked `categories_na`.
- New `FactorySmoke3CategoryTests` driving `run_production_gate` with
  three in-test fake collectors. The static + docs fakes are
  parameterizable (`pass`/`fail` `build_cmd`) so a single category can
  be flipped to FAIL without changing the profile or breaking the other
  two collectors.
- Six new tests covering:
  - `test_3category_all_pass_overall_pass` — happy path, all three
    categories PASS, overall verdict = PASS.
  - `test_3category_static_fails_overall_concerns_or_fail` —
    single-category FAIL demotes overall verdict to NOT-PASS.
  - `test_3category_docs_fails_overall_concerns_or_fail` — symmetric
    proof on a different category to catch
    "verdict-aggregation-only-trusts-correctness" style regressions.
  - `test_3category_each_category_renders_individual_verdict` — the
    rendered gate file exposes a per-category verdict map, not just an
    overall.
  - `test_3category_merkle_root_changes_with_category_count` — running
    the same profile with one active category vs three produces
    distinct `evidence_merkle_root` values (catches
    records-dropped-before-hashing bugs).
  - `test_3category_audit_chain_records_each_collector` — one
    `EvidenceCollected` audit event per active collector (catches the
    chain-eats-events-silently failure mode).

**Why it matters**

The pre-existing one-active-category harness (`A-follow`, commit
`5216880`) proved the live Merkle path runs and a real PASS is
reachable, but could not catch any regression that only manifests
across a mixed-status verdict matrix. Concretely, A-follow-2 closes:

- **Verdict aggregation across mixed-status records.** With three
  categories where one is FAIL and two are PASS, the aggregator has
  to honour fail-closed semantics — the one-active harness cannot
  exercise this branch because there is only ever one category to
  aggregate.
- **Per-category Merkle determinism.** The bundle Merkle root is
  computed over canonical-JSON evidence in sorted order; widening to
  three categories proves the sort key is stable and the root
  changes deterministically when the active set widens.
- **Audit chain per-collector accounting.** The chain must record one
  `EvidenceCollected` event per collector — a single-collector harness
  cannot prove the chain doesn't silently coalesce multi-collector runs
  into one event.

**Consumer-only.** Zero changes under `skills/`. Production code is
untouched. In-test fake collectors avoid `ruff` / `mkdocs`
tool-availability flakiness on CI. The negative-path assertion is
`assertNotEqual(verdict, "PASS")` rather than pinning a specific
verdict, so future tweaks to `aggregate_verdicts` (e.g. CONCERNS vs
FAIL boundary) do not silently regress this net.

## K-5 outcome (concurrent gates no longer blocked by cleanup)

Commit `ee215b8` — `fix(gate): K-5 — quarantine evidence under lock, rmtree outside lock, janitor cleans orphans at startup`.

**Problem (round-3 round-3-bug-sweep ID K-5,
`bug-c-deferred-rmtree-under-lock`)**

Before K-5, `_recover_from_crash_locked` invoked `shutil.rmtree` on
orphan evidence directories INSIDE the gate lock. Large evidence
bundles (10000+ files is realistic at scale) can take seconds to
delete on slow storage, blocking every concurrent
`run_production_gate` / `run_system_gate` caller on the same
`project_root` for the duration. That defeated the purpose of the L1
lock — it exists to serialize the marker lifecycle, not to gate bulk
I/O.

**Fix shape (three-phase)**

1. **Under the gate lock** — `os.rename` each orphan evidence directory
   to `_bmad/gate/cleanup/<gate_id>-<uuid4>/`. The destination lives
   on the same filesystem as `evidence/` so `EXDEV` cannot occur, and
   `uuid4` keeps back-to-back recoveries of the same `gate_id` from
   colliding inside `cleanup/`.
2. **Outside the gate lock** — `shutil.rmtree` each quarantined
   directory. Slow, but concurrent `run_production_gate` /
   `run_system_gate` calls are no longer blocked on the same project
   root.
3. **Crash resilience** — new helper `run_cleanup_janitor` scans
   `_bmad/gate/cleanup/` on `run_production_gate` /
   `run_system_gate` startup and `shutil.rmtree`s any leftover
   subdirs left by a process crash between phase 1 and phase 2. The
   janitor runs BEFORE the gate lock is acquired — the subdirs in
   `cleanup/` are by construction unreferenced once renamed there, so
   no lock is needed to clean them. Per-subdir `try/except OSError`
   keeps one corrupt subdir from blocking the rest.

**Contracts preserved**

- `recover_from_crash` STILL acquires the gate lock for the marker
  read + decision phase (L1 / L2 / L1-followup contract preserved).
- `_recover_from_crash_locked` STILL the inner-no-lock helper used by
  BOTH `run_production_gate` AND `run_system_gate` — symmetric coverage
  preserved.
- `MarkerCorruptionInvariant` + L1 / L2 audit-floor tests stay green.
- Fix C-3 honesty preserved: `rmtree` failures (now post-lock) still
  surface as `cleanup_failed=True` + `cleanup_error` in the descriptor
  returned to the caller.

**Tests added** (`tests/test_bugfix_K5_quarantine_rmtree.py`) — six
cases covering:

- Rename-under-lock semantics (the orphan directory disappears from
  `evidence/` while the lock is held).
- `rmtree`-outside-lock semantics (the quarantine subdir is gone after
  the call returns, but the gate lock was released BEFORE the
  filesystem walk started).
- Concurrent-gate non-blocking proof — a second
  `run_production_gate` on the same `project_root` proceeds while the
  first is still draining its quarantine subdir.
- `uuid4` collision proof — back-to-back recoveries of the same
  `gate_id` produce distinct quarantine subdirs.
- Janitor idempotency, per-subdir isolation (one corrupt subdir does
  not block the rest), and pre-lock execution.
- Re-asserts the L1 + L2 audit-floor invariants under the refactor so
  the new orchestration cannot silently regress the marker lifecycle.

Tests `tests/test_bugfix_L1_system_gate_lock.py` and
`tests/test_system_gate.py` got minor adjustments to match the new
janitor entry — both stay green.

## Final state

- **Branch tip**: `ee215b8` on `bma-d/integration-all`.
- **Tests**: 4167 passing (was 4150 at workflow start), 2 skipped, 0 fail.
- **Ruff**: clean.
- **Audit-floor invariants**: 26 green.
- **Frozen-surface symbols**: untouched.
- **New dependencies**: none.
- **Files touched** (8 total, +1058 / -25):
  - `skills/bmad-story-automator/src/story_automator/core/evidence_io.py` (K-5)
  - `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` (K-5)
  - `skills/bmad-story-automator/src/story_automator/core/system_gate.py` (K-5)
  - `tests/integration/data/profiles/smoke_3cat.json` (smoke expansion)
  - `tests/integration/test_factory_self_evaluation.py` (smoke expansion)
  - `tests/test_bugfix_K5_quarantine_rmtree.py` (K-5)
  - `tests/test_bugfix_L1_system_gate_lock.py` (K-5 adjustment)
  - `tests/test_system_gate.py` (K-5 adjustment)
- **Per-item tags already in place**:
  - `a-follow-smoke-3-categories` → `3d462f6`
  - `compat-bugfix-k5-quarantine-rmtree` → `ee215b8`
- **Workflow umbrella tag**: `smoke-expand-and-k5-complete` (this commit).

## What is still tracked

Items not in this workflow's scope, deliberately left open for a
later sweep:

- **K-2 (`bug-c-deferred-evidence-bundle-memo`)** — `load_evidence_bundle`
  is invoked 2–3× per `run_production_gate`
  (`core/gate_orchestrator.py:425, 583` and
  `core/verdict_engine.py:257`). Severity MED, wall-clock only. The
  fix requires either memoisation with an invalidation discipline
  against marker writes / mitigation-debt persistence, or call-site
  consolidation that touches the frozen gate surface. Disposition
  `defer-to-followup` per `docs/audit/round-3-bug-sweep.md`; still on
  the round-4 fix-now list. A memo describing the invalidation
  contract (in-process cache only? whole-bundle vs per-record? cache
  key includes marker mtime?) is the natural prerequisite before
  picking a fix shape — that memo is still TODO.

- **Dangling tags on local-only state** — every commit and every
  `<workflow>-complete` umbrella tag landed on this workflow lives on
  the local clone only. No `git push origin <tag>` has been run for
  any of:
  - `a-follow-smoke-3-categories`
  - `compat-bugfix-k5-quarantine-rmtree`
  - `smoke-expand-and-k5-complete`
  Same applies to the prior workflow tag `r3-deferred-batch-complete`
  and every commit-level tag landed since `pre-upstream-integration-start`.

- **Push to remote (`bma-d/integration-all`)** — the branch tip is
  ahead of `origin/bma-d/integration-all` by every commit since
  `cdc7ee5` (this workflow alone added 2; the prior workflows added
  many more). No `git push` has been run; operator intervention is
  required.

- **Merge to main** — `bma-d/integration-all` is still a long-lived
  integration branch. Merging into `main` is an explicit operator step
  that should land via the conventional one-PR-per-milestone flow
  with a final reconciliation of the changelog. None of the
  round-3 / round-3-deferred / round-3-K-5 work has merged into
  `main` yet.
