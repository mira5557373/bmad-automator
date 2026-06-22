# Option 1 — Serial Execution Rollup (2026-06-22)

## TL;DR

Option 1 (minimum-risk serial sequencing: A → C → B → D-rereview → D-implement)
executed end-to-end without a single rollback. All four planned milestones
shipped, plus the D-rereview gate, which graded the enhanced D spec
`ready-to-implement` and unblocked D-implement (G7 sprint-phase dual-store
unification). The factory ends the day with **4128 tests passing**
(baseline 4070 → +58 net), **ruff clean**, **26 audit-floor invariants
green** (baseline 24 → +2 from G7), zero changes under
`core/telemetry_events.py`, zero new Python dependencies, and the frozen
gate-surface waiver lines updated for every LOC excursion. The branch is
868 commits ahead of `main` and ready for PR.

## Per-milestone outcomes

| Milestone | Verdict | Commit(s) | Tag |
| --- | --- | --- | --- |
| **A** — e2e factory self-evaluation harness | shipped | `abea3f6` | `milestone-A-e2e-factory-harness` |
| **C** — round-3 bug sweep (lenses K/L/M) | shipped | `5501216` → `c9032df` (5 commits) | `milestone-c-round-3-bug-sweep` |
| **B** — operability batch (B1 PID, B2 lock-holder, B3 pre-commit) | shipped | `bc79b2b` | `milestone-B-operability-batch` |
| **D-rereview** — ultrathink-gap-analysis on enhanced D spec | ready-to-implement | `d3ab4b4` | `d-rereview-enhanced` |
| **D-implement** — G7 sprint-phase dual-store unification | shipped | `f5c8cdf` | _(no separate tag — gated by `d-rereview-enhanced`)_ |

### A — e2e factory self-evaluation harness (`abea3f6`)
Consumer-only milestone — zero source changes under `skills/`. Adds
`tests/integration/test_factory_self_evaluation.py` driving
`run_production_gate` against the factory's own working tree using the
bundled `default.json` profile. Nine new assertions cover lifecycle
shape (return type, verdict vocabulary, gate_id round-trip,
factory_version, profile-hash projection), Merkle export sentinel,
audit-chain integrity, and reuse-path determinism (mtime-unchanged).
**+312 lines test code; +9 tests.**

### C — round-3 bug sweep (5 commits, `5501216` → `c9032df`)
5-lens parallel survey (K = budget/concurrency, L = lifecycle, M = error
paths) with adversarial verification. 16 raw findings → 3 fix-now,
6 deferred, 7 discarded. Shipped fixes:
- **C-1** (`5aa096d`, lens M, P1) — `_quarantine_corrupted_marker` honest mkdir failure.
- **C-2** (`b84c026`, lens K, P2) — `evaluate_ceilings` single-pass aggregation.
- **C-3** (`7086d10`, lens M, P1) — `_recover_from_crash_locked` partial-rmtree honesty.
- Changelog `[FULL]` entry `adecd53`; workflow archive `c9032df`.
- **+10 tests added.**

### B — operability batch (`bc79b2b`)
Three additive operability fixes shipped as one milestone (none touches
frozen gate-surface; no new deps):
- **B1** — psutil `create_time()` bound on legacy markers without `start_time`.
- **B2** — `get_gate_lock` raises `GateLockTimeoutError(filelock.Timeout)`
  carrying holder PID + started_at + hostname (subclass preserves
  existing `except filelock.Timeout:` callers).
- **B3** — opt-in `.githooks/pre-commit` running unittest + ruff + M11
  vocabulary gate; `--no-verify` and `BMAD_SKIP_PRECOMMIT=1` escapes;
  Windows-git-bash / WSL portable.
- New sibling module `core/gate_lock_observability.py` (145 LOC) keeps
  `gate_orchestrator.py` under the 500-LOC waiver (746 → 834, waiver
  line added in `docs/spec/frozen-gate-surface.md`).
- **+19 tests added** (`tests/test_bugfix_L1_pid_reuse.py`,
  `tests/test_lock_holder_observability.py`,
  `tests/test_pre_commit_hook.py`).

### D-rereview — ultrathink-gap-analysis (`d3ab4b4`)
Re-graded the post-enhancement D spec against 10 HIGH-severity gap
categories. Verdict: **ready-to-implement** — patched in-place with 10
HIGH gaps closed (slug-key reconciliation, observe_only monomorphic
3-tuple, mtime-tie terminal-phase precedence, repair-module split,
synthetic violator audit-floor test, etc.). Tag `d-rereview-enhanced`
gated D-implement.

### D-implement — G7 sprint-phase dual-store unification (`f5c8cdf`)
New module `core/integration/unified_state.py` (408 LOC, under the
soft limit by design) with `read_unified_state()`,
`write_unified_state()`, and `unified_state_lock()` — single source of
truth over M48's `sprint_phase_map`. Reads are lock-free in the happy
path; writes serialize via `.unified-state.lock`; conflicts resolve via
mtime LWW with terminal-phase tie-break and a same-volume precondition
that fires only inside the resolver (migration path skips it). Legacy
single-store projects auto-upgrade on first read; `observe_only=True`
provides a read-only audit path returning a monomorphic 3-tuple
(status, phase, needs_repair). The first sprint-status writer in the
codebase ships here as a private text-only regex mutation helper (no
YAML re-serialisation, no `import yaml`). Slug-keyed phase entries are
reconciled to the canonical dotted id on every write. Repair branches
extracted to pre-authorised private sibling
`_unified_state_repair.py` (221 LOC). M48 frozen surface untouched;
`telemetry_events.py` untouched.
- **+21 tests added** in `tests/test_unified_state.py`.
- **Audit-floor invariants: 24 → 26** (new
  `UnifiedStateWriteIsolationInvariant` + explicit positive-failure
  synthetic violator test per gap D11).

## What shipped (commit SHAs + tags + tests added)

| Commit | Subject | Tests added | Tag |
| --- | --- | --- | --- |
| `abea3f6` | test(integration): A — end-to-end factory self-evaluation harness | +9 | `milestone-A-e2e-factory-harness` |
| `5501216` | docs(audit): round-3 bug-sweep lens execution (K, L, M) | 0 | — |
| `e3316f9` | docs(audit): round-3 triage | 0 | — |
| `5aa096d` | fix(gate-orchestrator): C-1 — quarantine_corrupted_marker honest mkdir failure | +4 | — |
| `b84c026` | fix(budget-ceilings): C-2 — evaluate_ceilings single-pass aggregation | +3 | — |
| `7086d10` | fix(gate-orchestrator): C-3 — _recover_from_crash_locked partial-rmtree honesty | +3 | — |
| `adecd53` | docs(changelog): round-3 bug sweep [FULL] | 0 | — |
| `c9032df` | chore(workflows): archive round-3 bug-sweep executed workflow | 0 | `milestone-c-round-3-bug-sweep` |
| `bc79b2b` | feat(operability): B — psutil-create-time + lock-holder log + pre-commit hook | +19 | `milestone-B-operability-batch` |
| `d3ab4b4` | docs(specs): D-rereview enhancements (10 HIGH gaps patched) | 0 | `d-rereview-enhanced` |
| `f5c8cdf` | feat(integration): G7 — sprint-phase dual-store unification | +21 | — |

**Net tests added in Option 1: +58 (4070 → 4128).** Two tests
remain skipped (pre-existing platform-conditional skips); zero
failures.

## What did NOT ship + why

- **Round-3 deferred findings (6 items)** — explicitly logged in
  `docs/audit/round-3-fix-now-list.md`. Reasons spanned scope creep
  (would require touching telemetry_events.py outside M01),
  cost/benefit (P3 fixes with no production exposure under
  single-operator threat model), and "needs a separate spec" (e.g.,
  cross-platform path-canonicalisation for Windows non-ASCII roots).
  None are blockers; each carries a one-line disposition.
- **Round-3 discarded findings (7 items)** — verifier step demoted
  them (false positives, already-mitigated, or design-intent).
- **No D-implement → D' follow-up needed** — the D-rereview gate ran
  *before* D-implement specifically to avoid a remediation tail. The
  enhanced spec was implemented as-graded.

## Final state

- **HEAD** — `f5c8cdf1fa439f0e0d2e7355e332ce130f3eefe1` on
  `bma-d/integration-all`.
- **Tests** — `Ran 4128 tests in 59.887s — OK (skipped=2)`.
- **Lint** — `ruff check skills/bmad-story-automator/src/story_automator/ tests/` →
  `All checks passed!`.
- **Audit-floor** — 26 invariants green (was 24; +2 from G7).
- **Tags created this run** — `milestone-A-e2e-factory-harness`,
  `milestone-c-round-3-bug-sweep`, `milestone-B-operability-batch`,
  `d-rereview-enhanced`.
- **Guardrails** — `core/telemetry_events.py` untouched; no new
  Python deps; frozen-gate-surface waiver lines updated for the two
  modules that crossed the 500-LOC soft limit (`gate_orchestrator.py`
  834, `system_gate.py` 256); Conventional Commits + `Generated-By:`
  trailer + `Co-Authored-By:` on every shipped commit.

## Push readiness

`bma-d/integration-all` is **868 commits ahead of `main`**. The branch
is push-ready: working tree is clean (single untracked workflow file
`.claude/workflows/option-1-serial.js` which is the orchestrator
harness, not factory code).

### Suggested PR description

> **Title:** `bma-d/integration-all → main: Option 1 serial execution + 868-commit integration sweep`
>
> **Summary**
>
> Closes the integration-all branch with Option 1 serial sequencing of
> milestones A (e2e harness), C (round-3 bug sweep), B (operability
> batch), and D (G7 sprint-phase dual-store unification — gated by a
> D-rereview ultrathink pass). 4070 → 4128 tests passing, ruff clean,
> 24 → 26 audit-floor invariants, zero deps added, zero changes to
> `telemetry_events.py`, frozen-gate-surface waivers updated.
>
> **What's in this PR**
>
> - Path-B compat milestones (N4 / N5 / N6.2 / N6.3 / N6.4 / N6.5 /
>   N6.6 / N6.7) shipped earlier in the branch.
> - Round-1 and round-2 bug sweeps (24 fixes total).
> - D-04 secfix + sibling-module followup.
> - Option 1 milestones A / C / B / D (this final phase).
>
> **Verification**
>
> ```
> PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests
> # Ran 4128 tests — OK (skipped=2)
>
> ruff check skills/bmad-story-automator/src/story_automator/ tests/
> # All checks passed!
> ```
>
> **Risk profile**
>
> Low. All work is additive (new modules, new tests, new invariants).
> The only frozen-gate-surface impact is the documented LOC growth in
> `gate_orchestrator.py` and `system_gate.py`, both waiver-line-tracked
> in `docs/spec/frozen-gate-surface.md`.

## Recommended next operator action

1. **Open the PR** using the description above.
2. **Run `npm run verify`** locally on a clean checkout to confirm the
   smoke-test + pack-dry-run gates pass on the operator's machine
   before merge. (Option 1 verified unittest + ruff; the full release
   gate also includes `test:cli` and `test:smoke`.)
3. **Tag `option-1-serial-complete`** on this commit before merge so
   the squash-merge SHA on `main` carries forward the milestone
   anchor.
4. **Post-merge**, retire the four milestone tags and the
   `d-rereview-enhanced` tag from the branch — they live on the
   pre-squash SHAs for archaeology and don't need to follow to `main`.
