# N-Items Completion Report

**Run date:** 2026-06-22
**Branch:** `bma-d/integration-all`
**Final commit:** `120b90c feat(compat): N6.2 hookbus-shim — Path B foundations for plugin-veto interop`
**Reference roadmap:** `docs/audit/sasa-plus-autonomous-run-report.md` — "Recommended next steps for the operator"

## Summary

| Metric | Value |
| --- | --- |
| Tests at run start (`22e2712`) | 3,763 (OK, skipped=2) |
| Tests at run end (`120b90c`) | 3,825 (OK, skipped=2) |
| Net test delta | +62 (no regressions) |
| N-items completed | 4 (N1, N2, N3, N6) |
| N-items partially completed | 0 |
| N-items skipped this run | 2 (N4, N5 — bounded follow-ups; N7 still blocked on N4-N5) |
| New tags | `compat-m51-complete`, `compat-m59-complete`, `n6-engine-decision`, `n6-2-hookbus-shim` |

The four items shipped — N1 verification, N2 partial resolutions for M51 and M59, N3 RAMR review-skill wire-up, and the N6 architectural decision plus its first concrete implementation step — close the highest-impact entries from the deep gap analysis without burning the green test baseline or adding any non-stdlib dependency.

## N1 verification

Baseline confirmed at the top of the run:

- `git log -1` → `22e2712 docs(audit): replace inaccurate workflow-generated report with truth`.
- `git tag -l "sasa-plus*"` listed both `sasa-plus-wave1-2-3-landing` and `sasa-plus-wave1-2-3-recovery`.
- Full suite: `Ran 3763 tests in ... OK (skipped=2)`.

Landing of `f4eabba` (SASA+ Wave 1+2+3) is therefore verified ancestral to the working tree; the 33-of-35 milestone claim in `sasa-plus-autonomous-run-report.md` matches the runtime state.

## N2 — M51 + M59 partials resolved

Both partial milestones were closed by porting the missing surface from the original milestone-tag worktrees and re-promoting the parked tests out of `tests/deferred/`. Each lives in its own commit and its own tag so the operator can isolate a revert if needed.

### M51 adr-29-criterion (`compat-m51-complete`, `adfccbf`)

Replaced the kebab-case stub criteria with the canonical 29-entry title-case rubric (Identity / Substance / Consequences / Quality / Operability / Governance) and added the four contract functions the deferred test pinned:

- `criterion_for(name)` — validated lookup; raises `AdrCriterionError` on unknown / non-string input.
- `has_production_readiness_section(content)` — fail-closed wrapper kept so existing process-collector callers keep compiling.
- `evaluate_adr_criteria(content)` — scores each criterion PASS|FAIL in declared order via pre-compiled ATX-heading patterns that tolerate hyphens, underscores, and case variation.
- `missing_criteria(content)` — required criteria absent from the body, with `OPTIONAL_CRITERIA` filtered out.

The legacy `_has_prod_readiness_section` helper and `_SECTION_RE` are retained for binary back-compat with the process collector.

Tests now passing: the entire restored M51 suite (the file previously parked under `tests/deferred/` is back at `tests/test_m51_adr29_criterion.py`).

### M59 phase-shaped-budgets (`compat-m59-complete`, `28b12f7`)

Added the M59 phase-shaped budget layer to `core/budget_ceilings.py`:

- `OverspendAction` enum (`ALLOW` / `RETRY_CHEAP` / `PAUSE` / `ESCALATE`) matching the shape from `compat-m59-phase-shaped-budgets`.
- `PhaseBudgetCeiling` dataclass (positive-int `limit` + non-empty `priority`) — deliberately distinct from the M03 `BudgetCeiling` keyed by gate name with `limit_usd`. Both coexist for import-locality; downstream callers pick by semantics.
- `classify_overspend(*, priority, phase)` returns `OverspendAction`: review-verify → `PAUSE`; dev-running P0 → `RETRY_CHEAP`; dev-running non-P0 → `ESCALATE`; unknown phase → `ESCALATE`.
- `overspend_action_for` alias for call-site clarity.
- `BudgetLedger.snapshot` now returns concrete `dict` (was `Mapping`) for ergonomic JSON serialization.

Also unbroke `core/innovation/phase_budget.py`, which was non-importable because it referenced an `OverspendAction` and a `BudgetCeiling(limit=, priority=)` shape that didn't exist in this module. Renamed those references to `PhaseBudgetCeiling` so M03 cost-USD ledger semantics stay untouched.

Tests now passing: the restored M59 suite (`tests/test_m59_phase_shaped_budgets.py`), plus the existing M03 budget-ceilings tests, plus the M59 phase-budget tests that referenced the broken `innovation/phase_budget.py`.

## N3 — RAMR pre-flight wired into review skill

**Option chosen:** call RAMR at review-session dispatch time and refuse to spawn a same-(cli_id, model) reviewer rather than wait for the M55 gate to reject post-hoc.

**Why:** the deep gap analysis (G4) noted that M57 + M55 enforce reviewer distinctness *at gate time*, after the review has already been performed and the tokens have already been spent. The cheapest fix is the earliest fix: route the assignment selection through RAMR before the session is created.

**Shipped (`89cbf75`):**

- `core/integration/ramr_review_dispatch.py` — `select_reviewer_assignment` routes a reviewer assignment via RAMR, falls back to an alternative registry entry on (cli_id, model) collision with the dev assignment, and raises `ReviewDispatchEscalation` when no independent pair exists in the registry. No new dependencies; pure stdlib + the existing RAMR surface.
- `skills/bmad-story-automator-review/SKILL.md` documents the new pre-flight requirement so anyone authoring a review session reads "must call `select_reviewer_assignment` before tmux spawn."
- `tests/test_ramr_review_dispatch.py` — 9 tests across happy-path, collision fallback, escalation, and audit-trace shape.

This closes G4 with no change to the gate program — the gate still enforces distinctness as a backstop; the dispatcher just refuses to make work the gate would later reject.

## N6 — Architectural decision (Engine vs registry-of-callables)

**Recommendation: PATH_B** — keep our deterministic registry-of-callables dispatcher; add an in-process HookBus-compat layer to satisfy multi-CLI dispatch and the bmad-auto plugin contract.

**Decision spec** (`dfafc48` → `docs/spec/2026-06-22-engine-adoption-decision.md`, tag `n6-engine-decision`, 395 LOC) frames Path A vs Path B side by side:

- **Path A (full Engine adoption)** would replace ~3,000 LOC of deterministic, well-tested orchestration (`gate_orchestrator` + verifiers + `runtime_policy` + commands) with bmad-auto's 1,454-LOC `Engine` class and ~2,500 LOC of supporting modules. The capability gain — pluggable lifecycle hooks across 14+ stages, multi-CLI dispatch, worktree isolation — is real, but most of it duplicates infrastructure we already own (`gate_orchestrator`, `gate_audit`, `trust_boundary`, `tmux_runtime`, `policy_translator`).
- **Path B (HookBus shim)** delivers the same end-user capabilities (multi-CLI dispatch, hookable lifecycle) in ~600-900 LOC of additive code, preserves the deterministic gate program, keeps the 3,763-test baseline green, and avoids importing bmad-auto's non-deterministic global state (signal-handler ownership, process-wide `_stop_signals_owner`, mutable `PluginRegistry.validate`).

For a single trusted operator on their own VPS (per `singleuser-threat-model.md`), Path A's plugin sandbox + signal-ownership + workspace-isolation machinery is sized for a multi-team CI server that doesn't exist in this threat model. Path B sizes the surface to actual need.

**First implementation step shipped (N6.2, `120b90c`, tag `n6-2-hookbus-shim`):**

- `core/bauto_bridge/hookbus_shim.py` — `HookBusShim`, `HookSpec`, `HookbusShimError`, `KNOWN_EVENTS` frozenset (`post_dev_phase`, `pre_review`, `post_review`, `pre_gate`, `post_gate`, `pre_commit`). The shim holds no global state, mirrors bmad-auto's registration-order dispatch, and keeps `VerifyOutcome` deterministic (no timestamps / PIDs / run-IDs) so emit results stay safe to embed in gate-file payloads. `fail_closed` converts callback exceptions to FAIL outcomes; `BaseException` propagates so the orchestrator can shut down cleanly.
- `core/bauto_bridge/__init__.py` re-exports the shim surface alongside the existing policy-translator surface.
- `tests/test_hookbus_shim.py` — 23 tests covering register / emit / blocking veto / fail_closed / severity propagation / `list_hooks` / `has_blocking_veto`.

What's intentionally **out of scope** for this first step and queued for the next Path B milestone: declarative subprocess hooks, mutation-pipeline context, plugin-manifest loading. Those are the next 300-500 LOC and they slot in additively on the same shim.

## Remaining work (from the deep gap analysis)

Numbered per the original priority list in `sasa-plus-autonomous-run-report.md`. Items not in this run, with current status notes.

| Item | Estimate | Status | Notes |
| --- | --- | --- | --- |
| **N4 — Migrate `profile_composer` into `product_profile.load_effective_profile` (G6).** | 4 hours | Open | Single-call-site refactor; replaces ad-hoc merging with the layered overlay composer. Self-contained. |
| **N5 — Add Merkle root to gate-file export (G5).** | 1 day | Open | One-function change in `gate_orchestrator.run_production_gate`: after `evaluate_gate` returns, compute root via `compute_evidence_bundle_merkle_root` and add to the gate file's top-level keys. Closes the "auditors can't externally verify" capability gap. |
| **N6.3+ — Subsequent Path B HookBus milestones.** | ~2-3 weeks total | Open | Spec exists. Next-up: declarative subprocess hooks (~150 LOC), mutation-pipeline context (~100 LOC), plugin-manifest loading (~250 LOC). All slot additively on `hookbus_shim`. |
| **N7 — M50 usage-parsers + RAMR wire-up.** | 2 weeks | Blocked on N4-N5 | Once N5 lands, M50's 4 parsers (claude_jsonl, codex_rollout, gemini_chat, none) have a real consumer in the cost-attribution path. |
| **G2 — Worktree-per-unit isolation in production paths.** | 3 weeks | Open | Orchestrator still runs collectors inline; isolation surface exists in `trust_boundary` + `collector_checkout` but not wired through `gate_orchestrator.run_production_gate`. |
| **G3 — Multi-CLI runtime is plumbing-only.** | 4 weeks | Open, now unblocked by N6.2 | `tmux_runtime.py` (1,706 LOC) still hardcodes Claude. M32 CLIProfile is schema-only. With the HookBus shim in place, the dispatcher can now be split out behind a hook event without touching the deterministic gate program. |
| **G7 — Sprint-phase dual-store unification.** | 1 week | Open | M48 persists sprint-status AND Phase; no single-source-of-truth resolver. Add `read_unified_state`. |
| **C1 — Live spec-drift watcher.** | 4 weeks | Open | Compose `core/spec_compliance` + a tool-call stream tail; post-hoc detection exists via M58. |
| **C2 — Cross-genre artifact lineage.** | 3 weeks | Open | Extend M54 ledger with parent-ref to link brainstorm → braindump → brief → BRD → PRD → kernel → story → gate. |
| **C3 — Per-collector cost attribution.** | 2 weeks | Open, depends on N7 | Needs the M50 parsers for token-cost ingest. |
| **C4 — Compliance evidence pack export (SOC2/HIPAA/SOX).** | 3 weeks | Open | Out of single-operator threat model; defer until a regulated buyer materializes. |
| **C5 — Self-improving gate (drift → auto-threshold).** | 3 weeks | Open | Build on `drift_detector.py` + `calibration.py`; ship as a follow-up after N6.3+. |
| **E1-E6 — Enhancements.** | 2-4 hours each | Open | Refactor / discoverability wins; not blockers. `E5` (`tests/deferred/` as project convention) and `E6` (workflow-recovery skill) are the highest-leverage. |
| **P1-P4 — Process gaps from the autonomous run.** | n/a | Open | Lessons codified in the SASA+ report; no code change required, but any future workflow with `isolation: 'worktree'` should assert `baseSha == orchestrator HEAD` (P1) and verify shipped claims with `git merge-base --is-ancestor` (P2). |

**Recommended next step:** N5 (Merkle root export, 1 day) — smallest unit, closes a real auditor-facing capability gap, unblocks N7. After N5, take the next Path B HookBus milestone (declarative subprocess hooks) so multi-CLI dispatch starts to materialize in the runtime.
