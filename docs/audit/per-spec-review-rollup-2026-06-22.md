# Per-Spec Review Rollup — 2026-06-22

> Aggregator for the four adversarial spec/plan reviews completed on 2026-06-22.
> Generated after the per-spec gap reports and the enhancement triage commit (`acf5337`).
> Reviewer model: claude-opus-4-7 (1M context).
> Reviewed artifacts: 4 spec + 4 plan files under `docs/superpowers/{specs,plans}/2026-06-22-*.md`.

---

## TL;DR (overall verdict per milestone)

| Milestone | Title | HIGH gaps | Total findings | Spec verdict (post-enhancement) | Implementation readiness |
|-----------|-------|-----------|----------------|---------------------------------|--------------------------|
| **A** | E2E Factory Self-Evaluation Harness (`2026-06-22-e2e-factory-harness-design.md`) | 5 | ~23 (A-01..A-23) | **needs-enhancement → enhancements applied** | ready-to-implement |
| **B** | Operability Batch B1+B2+B3 (`2026-06-22-operability-batch-design.md`) | 6 | ~28 (B-H1..B-H6 + B-M1..B-M12 + B-L1..B-L10) | **needs-enhancement → enhancements applied** | ready-to-implement (with serialisation constraint vs C) |
| **C** | Round-3 Bug Sweep, lenses K/L/M (`2026-06-22-round-3-bug-sweep-design.md`) | 3 | ~19 (C-H-01..C-H-03 + C-M-04..C-M-12 + C-L-13..C-L-16) | **needs-enhancement → enhancements applied** | ready-to-implement (with serialisation constraint vs B) |
| **D** | G7 Sprint-Phase Dual-Store Unification (`2026-06-22-g7-sprint-phase-unification-design.md`) | 10 | ~30 (D01..D32) | **needs-enhancement → enhancements applied** | ready-to-implement (largest behavioural surface) |

**Cumulative totals**: 24 HIGH findings, ~100 total findings across all four reviews, **all 24 HIGH gaps patched** into the spec/plan pairs in commit `acf5337` ("docs(specs): enhance A/B/C/D specs from per-spec gap analysis"). Baseline test suite remains 4070 tests green.

**Overall posture**: Every milestone needed material enhancement before implementation; none was a redesign candidate. The four enhanced spec/plan pairs are now collectively `ready-to-implement` modulo the operator decision below (sequencing, parallel-vs-serial, scope cuts).

---

## Per-milestone gap reports (links + 1-line summaries)

### A — End-to-End Factory Self-Evaluation Harness
- Report: [`docs/audit/spec-review-2026-06-22-milestone-a.md`](spec-review-2026-06-22-milestone-a.md)
- Spec (enhanced): [`docs/superpowers/specs/2026-06-22-e2e-factory-harness-design.md`](../superpowers/specs/2026-06-22-e2e-factory-harness-design.md)
- Plan (enhanced): [`docs/superpowers/plans/2026-06-22-e2e-factory-harness-plan.md`](../superpowers/plans/2026-06-22-e2e-factory-harness-plan.md)
- One-line summary: Five HIGH gaps (wrong `audit_policy` shape, mis-anchored profile-hash assertion, missing `run_production_gate` kwargs, empty-registry → forced-FAIL collapse, leaky `BMAD_AUDIT_KEY` save/restore) would have shipped a test that either fails on its own audit-chain assertion or leaks operator secrets; all five are patched.

### B — Operability Batch (B1 legacy-marker PID-reuse window + B2 lock-holder visibility + B3 pre-commit gate)
- Report: [`docs/audit/spec-review-2026-06-22-B-operability.md`](spec-review-2026-06-22-B-operability.md)
- Spec (enhanced): [`docs/superpowers/specs/2026-06-22-operability-batch-design.md`](../superpowers/specs/2026-06-22-operability-batch-design.md)
- Plan (enhanced): [`docs/superpowers/plans/2026-06-22-operability-batch-plan.md`](../superpowers/plans/2026-06-22-operability-batch-plan.md)
- One-line summary: Six HIGH gaps — broken `filelock.Timeout(msg)` raise pattern, missed third `get_gate_lock` call site in `core/system_gate.py:71`, wrong source-file attribution for `iso_now`, reversed cause-and-effect in 5.0s tolerance derivation, undeclared frozen-gate-surface symbol, and a +18 LOC delta on top of an already 718-LOC `gate_orchestrator.py` — would have shipped a non-working B2; all six are patched (observability helpers extracted into new `core/gate_lock_observability.py` sibling module).

### C — Round-3 Bug Sweep (lenses K/L/M)
- Report: [`docs/audit/spec-review-2026-06-22-C-round-3-bug-sweep.md`](spec-review-2026-06-22-C-round-3-bug-sweep.md)
- Spec (enhanced): [`docs/superpowers/specs/2026-06-22-round-3-bug-sweep-design.md`](../superpowers/specs/2026-06-22-round-3-bug-sweep-design.md)
- Plan (enhanced): [`docs/superpowers/plans/2026-06-22-round-3-bug-sweep-plan.md`](../superpowers/plans/2026-06-22-round-3-bug-sweep-plan.md)
- One-line summary: Three HIGH gaps (missing `PYTHONPATH=skills/bmad-story-automator/src` prefix would have collected 3665 tests with 28 import errors instead of 4070 green, reference to a non-existent `tests/test_frozen_gate_surface.py`, stale HEAD pin `6a957d2`) would have corrupted the §0 audit report within the first hour; all three are patched, plus an explicit B↔C serialisation constraint (never concurrent).

### D — G7 Sprint-Phase Dual-Store Unification
- Report: [`docs/audit/spec-review-2026-06-22-milestone-d.md`](spec-review-2026-06-22-milestone-d.md)
- Spec (enhanced): [`docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md`](../superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md)
- Plan (enhanced): [`docs/superpowers/plans/2026-06-22-g7-sprint-phase-unification-plan.md`](../superpowers/plans/2026-06-22-g7-sprint-phase-unification-plan.md)
- One-line summary: Ten HIGH gaps — non-existent sprint-status writer, undecidable `validate_sprint_status` call (would have required `yaml.safe_load` against the no-deps guardrail), cross-volume `mtime` LWW, reader race, write/read interleave ambiguity, undeclared frozen-gate-surface symbol, silent forensic-snapshot corruption via read-auto-write, mtime-tie collapse, ambiguous "missing story" error class, and slug-vs-canonical key drift between writer and phase store — all ten are patched; G7 now ships its own writer, two distinct error subclasses, an `observe_only=True` read path, a same-volume `st_dev` precondition, and a phase-first/sprint-second write order paired with sprint-first/phase-second read order.

---

## Recommended next action per milestone

| Milestone | Recommended next action | Rationale |
|-----------|-------------------------|-----------|
| **A — E2E Factory Harness** | **implement now** | Smallest behavioural surface (one test class, one orchestrator call, one audit-chain assertion). All 5 HIGHs are patched and the test exercises an existing public API (`run_production_gate`) without modifying it. Cheapest first win; lights up the end-to-end self-evaluation loop the other milestones depend on. |
| **B — Operability Batch** | **implement now** (in parallel with A, or sequentially) — but **not concurrent with C** | All 6 HIGHs are patched; observability helpers extracted to a new sibling module to dodge the 500-LOC soft-limit issue on `gate_orchestrator.py`. The legacy-marker PID-reuse fix (B1) closes a real correctness window. B2 (lock-holder visibility) is operator-pain mitigation. B3 (pre-commit gate) is the lowest-risk piece and could be deferred if scope is tight. C↔B serialisation constraint must hold. |
| **C — Round-3 Bug Sweep (K/L/M)** | **implement now** — but **strictly before or after B**, never concurrent | All 3 HIGHs are patched and the §0 audit-report scaffolding is now reproducible. Lens K (cross-module coupling), Lens L (test brittleness), Lens M (extended-path docs) are independent enough that a one-pass sweep should converge inside the budget. If parallelism with A or D is needed, this is the safest concurrent slot because it adds tests/docs and rarely touches production code. |
| **D — G7 Sprint-Phase Unification** | **re-review after enhancement applied** → **then implement** | This is the **largest** behavioural surface (10 HIGHs, ~30 total findings, ships the first-ever sprint-status writer, introduces two new error subclasses, adds `observe_only=True`, declares 4 new frozen-gate-surface symbols, and reconciles slug-vs-canonical key drift). The enhancements are substantial enough that a second adversarial pass against the patched spec is cheap insurance before implementation begins. If the operator wants to ship D in this cycle, an `ultrathink-gap-analysis` re-review of the enhanced D spec is the recommended next step (estimated cost: 1 ultrathink pass). Otherwise, defer to the next cycle. |

### Suggested sequencing options

- **Option 1 (minimum-risk)**: A → C → B → D (re-review) → D (implement). Serial. ~3-4 sessions.
- **Option 2 (balanced)**: A + C in parallel (different surfaces), then B, then D (re-review) → D (implement). ~2-3 sessions.
- **Option 3 (scope-cut)**: A + C + B (drop B3 pre-commit gate to next cycle) in parallel/sequential, defer D entirely to next cycle. ~2 sessions. Recommended if operator wants fastest path to "factory self-evaluation works end-to-end."

---

## Operator decision required: which of A/B/C/D to proceed with

The four enhanced spec/plan pairs are all `ready-to-implement` against the patched HIGH gaps. The operator now owns the **scoping and sequencing decision**. Concrete questions:

1. **Do all four ship in this cycle, or do we scope-cut?**
   - If scope-cut: D is the strongest candidate to defer (largest surface, broadest behavioural change, benefits most from a second adversarial pass).
   - If all four: budget ~3-4 sessions and plan for D to receive an `ultrathink-gap-analysis` re-review first.

2. **Serial or parallel execution?**
   - A and C can run in parallel safely (different surfaces, no shared state).
   - B and C **cannot** be concurrent (the spec enhancements added an explicit `compat-c-bug-sweep` ↔ `compat-b-operability-batch` serialisation constraint to spec §6.0 of C).
   - D should be serial — its surface touches `core/integration/unified_state.py` plus frozen-gate-surface declarations plus a new sprint-status writer; mixing it with another live milestone risks merge-pain and surface-drift.

3. **D re-review: yes or no?**
   - Recommended: yes. 10 HIGH gaps with patches that introduce new public symbols, a new error-class hierarchy, a new write-order discipline, and a new `observe_only` path is a large enough delta that a second pass is cheap insurance. Estimated cost: 1 ultrathink pass (~30-60 min) before implementation begins.
   - If skipped: implementation should explicitly plan a post-impl-review checkpoint before merging G7.

4. **Which milestone leads?**
   - Strong default recommendation: **start with A**. It's the smallest, exercises the existing public API (`run_production_gate`) without modifying it, and the resulting self-evaluation harness is what makes future milestones (including A2/A3 follow-ons) verifiable end-to-end.

### Recommended default plan (for an operator who wants a single action)

1. Implement **A** first (smallest, lights up end-to-end harness).
2. Then **C** (bug sweep) and **B** (operability) in that order (C strictly before B per spec serialisation constraint), or A + C in parallel, then B.
3. Run an `ultrathink-gap-analysis` re-review on the enhanced **D** spec; if the re-review surfaces no new HIGHs, implement D last.
4. After all four merge, run a `post-impl-review` + `production-readiness-review` sweep on the combined diff.

The operator should now indicate which subset (A, B, C, D, or a mix) to proceed with, and whether D re-review is required before D implementation.

---

## Provenance

- Per-spec gap reports written: 2026-06-22.
- Spec/plan enhancements applied: 2026-06-22.
- Triage commit: `acf5337a939779bfa10ebf0711929049964aeb14` (`docs(specs): enhance A/B/C/D specs from per-spec gap analysis (24 HIGH gaps patched)`).
- Baseline tests: 4070 (must remain green post-implementation; this review did not touch Python sources, tests, or telemetry types).
- Branch: `bma-d/integration-all`.
- This rollup tagged: `per-spec-review-complete`.
