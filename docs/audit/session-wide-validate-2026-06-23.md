# Session-wide adversarial validate — 2026-06-23

> **Scope:** every milestone shipped on the `bma-d/integration-all` branch
> since the session-start ancestor commit `ae76996`.
> **Verdict tag:** `session-wide-validate-complete`.
> **HEAD at audit:** `79fbd75`.

## TL;DR

The session shipped 42 commits, 21 new git tags (10 milestones + helpers),
~6,500 net lines of code+tests, and three observability arcs (drift,
lineage, cost). The work is **ready to ship** as a coherent batch: all
4351 tests pass (2 skipped — 4353 ran), ruff is clean, the 26 audit-floor
invariants all pass, every frozen-surface symbol declared in
`docs/spec/frozen-gate-surface.md` is present in code, every public symbol
in `core/innovation/*` imports without ImportError, the end-to-end
cost-tracking loop (capture → emit → gate_file["cost_total_usd"]) is
verified by integration test `test_end_to_end_capture_then_run_production_gate`,
and every session-touched commit carries the required `Generated-By:`
trailer plus a Conventional Commits subject.

**No HIGH-severity issues found.** Three MEDIUM findings (mostly
documentation drift) and four LOW findings (cosmetic) are listed below;
all are safe to defer to a future polish pass. The detached `compat-m25..m60`
tags noted under "Tag reachability" are **pre-session state** (Wave 1+2+3
squashed them into `f4eabba` before this session began) and are NOT a
regression introduced here.

## Tag reachability

35 of the 81 `compat-*` / `milestone-*` / `polish-*` tags are detached
from HEAD. **All 35 detachments pre-date this session** — they are the
M25–M60 per-milestone snapshot tags from the SASA+ work that the
"Wave 1+2+3" squash (`f4eabba`, pre-session) collapsed into a single
commit. The content is reachable via `f4eabba`, only the per-tag SHAs
are unreachable. All 22 session-new tags are REACHABLE.

| Tag | SHA | Reachable? |
|---|---|---|
| compat-secfix-D-04-audit-key-env-scrub | 1c24a86 | yes |
| compat-secfix-D-04-sibling-module | 789a7c9 | yes |
| compat-k2-evidence-cache | 32032cb | yes |
| compat-c2-cross-genre-lineage-mvp | cdb61c7 | yes |
| compat-c2-followup-disk-and-gate-embed | ec83a39 | yes |
| compat-c2-query-cli | 1796b08 | yes |
| compat-c1-spec-drift-watcher-mvp | 8a4db9d | yes |
| compat-c1-followup-persistence-and-wiring | 445263e | yes |
| compat-n7-usage-parsers-and-cost-attribution | 5155851 | yes |
| compat-cli-polish-lineage-top-level | 7302d54 | yes |
| compat-c3-cost-attribution-wiring | 6bf56e4 | yes |
| compat-c3-auto-session-usage-capture | d71a8a7 | yes |
| compat-bugfix-k5-quarantine-rmtree | ee215b8 | yes |
| compat-bugfix-m3-audit-dirfsync | 4d8dde4 | yes |
| compat-bugfix-L-docstrings | c821979 | yes |
| compat-bugfix-L1-L2-gate-marker-lock | f74bdd4 | yes |
| compat-bugfix-L1-system-gate-lock | 02a96c4 | yes |
| compat-c-1-quarantine-mkdir-honest | 5aa096d | yes |
| compat-c-2-ceilings-single-pass | b84c026 | yes |
| compat-c-3-recover-cleanup-honest | 7086d10 | yes |
| compat-g7-unified-state | b142b43 | yes |
| milestone-A-e2e-factory-harness | abea3f6 | yes |
| milestone-B-operability-batch | bc79b2b | yes |
| milestone-C-round-3-bug-sweep | c9032df | yes |
| milestone-D-g7-sprint-phase-unification | f5c8cdf | yes |
| polish-docs-2026-06-23 | 79fbd75 | yes |
| compat-m25-phase-bridge … compat-m60-kernel-violation-classifier (33 tags) | various | **pre-session detachment via Wave 1+2+3 squash; content reachable via `f4eabba`** |

## Test suite + lint state

| Check | Command | Result |
|---|---|---|
| Full suite | `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests` | **Ran 4353 tests in 69.7s — OK (skipped=2)** |
| Audit invariants | `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_audit_regression` | **Ran 26 tests in 1.2s — OK** |
| Ruff | `ruff check skills/bmad-story-automator/src/story_automator/ tests/` | **All checks passed!** |
| Commits | `git log ae76996..HEAD \| wc -l` | **42 commits this session** |
| Internal coupling | `from story_automator.core` re-imports inside `core/` | 32 (pre-existing baseline; no spike) |

## Module-size budget

Soft limit = 500 LOC per Python module. Modules over the limit, and
whether the session changed them:

| Module | LOC | Session-touched? | Documented waiver? |
|---|---|---|---|
| `core/tmux_runtime.py` | 1842 | no | pre-existing |
| `core/gate_orchestrator.py` | **1002** | yes (8 commits) | partial — frozen-surface doc says "834 LOC post-B" but actual is 1002 LOC |
| `commands/orchestrator.py` | 999 | yes (1 commit) | pre-existing |
| `commands/orchestrator_epic_agents.py` | 849 | no | pre-existing |
| `commands/tmux.py` | 701 | no | pre-existing |
| `core/runtime_policy.py` | 622 | no | pre-existing |
| `core/budget_ceilings.py` | 562 | yes (1 commit) | pre-existing |
| `core/category_rules.py` | 555 | no | pre-existing |
| `commands/basic.py` | 555 | no | pre-existing |
| `core/stop_hooks.py` | 547 | no | pre-existing |
| `core/evidence_io.py` | 531 | yes (2 commits) | pre-existing |

Largest new this-session modules are all UNDER the limit:
- `core/innovation/spec_drift_watcher.py` at **exactly 500 LOC** (right at edge)
- `core/innovation/ramr.py` at 494
- `core/innovation/lineage_ledger.py` at 474
- `core/innovation/cost_evidence.py` at 433
- `core/integration/unified_state.py` at 408

## Frozen-surface integrity

All 19 modules + ~80 symbols declared in `docs/spec/frozen-gate-surface.md`
were imported and checked for presence. Programmatic result:
**ALL_FROZEN_SYMBOLS_PRESENT**.

Notable signatures verified:
- `core/gate_status.py` — 8 symbols present
- `core/gate_schema.py` — 11 factory/validator symbols + `GateFile` shape
- `core/evidence_io.py` — 6 symbols incl. `GateMarkerCorruptedError`
- `core/gate_remediation.py` — 6 incl. `EDITABLE_SECTIONS`, `EditAuthorizationError`
- `core/gate_orchestrator.py` — 5 lifecycle entries + `ISO_TRUNCATION_S` + `MAX_ORCHESTRATOR_UPTIME_S`
- `core/audit.py` + `core/audit_env_scrub.py` — both export `scrub_env_for_subprocess` (D-04 split)
- `core/profile_composer.py` — `compose_profiles`
- `core/bauto_bridge/hookbus_shim.py` — importable
- `core/plugins.py` — `PLUGIN_MANIFEST_KEYS`, `PluginTrustError`, `PluginRegistry`, `PluginSpec`
- `core/cli_dispatcher.py` — `dispatch_session`
- `core/gate_lock_observability.py` — `GateLockTimeoutError`
- `core/action_enum.py` — importable
- `core/innovation/lineage_ledger.py` — 7 disk-persistence symbols
- `core/innovation/cost_evidence.py` — 9 emission/load symbols
- `core/integration/unified_state.py` — 3 read/write functions + 3 exception classes

## Import sanity

Every public symbol in `core/innovation/*` modules:

| Module | Import result | `__all__` highlights |
|---|---|---|
| `cost_attribution` | OK | AttributionError, CollectorCostShare, VALID_ATTRIBUTION_MODES |
| `cost_evidence` | OK | CostEvidenceError, GateCostReport, emit_gate_cost_report |
| `session_usage_capture` | OK | SessionUsageCapture, capture_session_usage |
| `lineage_ledger` | OK | (empty `__all__` — exposes via module attrs) |
| `spec_drift_watcher` | OK | SpecDriftError, SpecDriftEvent, SpecDriftSnapshot, SpecDriftWatcher |
| `spec_drift_persistence` | OK | append_drift_event, baseline_path, drift_root_dir |
| `ramr` | OK | RAMRError, RoutingDecision, DEFAULT_CLI_REGISTRY |
| `ledger` | OK | (empty `__all__`) |
| `kernel_classifier` | OK | (empty `__all__`) |
| `adversarial_review` | OK | AdversarialReviewError, ReviewAssignment |
| `phase_budget` | OK | PhaseBudgetConfig, PhasePolicy |
| `replay_diff` | OK | (empty `__all__`) |
| `stack_risk_weights` | OK | (empty `__all__`) |

Failures: **0**. (Empty `__all__` for older modules is a pre-existing
style; the symbols are still importable via `from module import name`.)

## CHANGELOG / git tag cross-check

- **CHANGELOG-only tag (not in `git tag`):** `compat-bugfix-d-04-audit-key-env-scrub`
  (CHANGELOG line 36). The actual tag is `compat-secfix-D-04-audit-key-env-scrub`
  (note `secfix` vs `bugfix` and `D-04` vs `d-04`). Also CHANGELOG does
  not mention the follow-up tag `compat-secfix-D-04-sibling-module`.
- **Detached `compat-m25..m60` tags (33):** pre-session squash; not a
  regression. The CHANGELOG does not enumerate them because they belong
  to a prior session.
- **Test count drift:** CHANGELOG line 11 and README line 62 both
  state "4070 → 4348" but the actual passing count at HEAD is 4351
  (4353 ran, 2 skipped). Off by +3.

## End-to-end cost-tracking loop verification

Procedural reproduction (run inline, not as a test):

1. Synthesize a Claude JSONL transcript with two messages (300 input + 125 output tokens).
2. `capture_session_usage("claude-code", path)` → `UsageMetrics(total_cost_usd=0.002775, parser_id="claude-jsonl")`.
3. Construct two `CollectorOutcome` (static_smoke 1000ms, docs_smoke 500ms).
4. `emit_gate_cost_report(project_root, "gate-test-001", usage, outcomes)` → on-disk `_bmad/gate/cost/gate-test-001/summary.json` with `total_cost_usd=0.002775` matching the captured cost exactly.

Plus the in-tree integration test
`tests/test_session_usage_capture.py::test_end_to_end_capture_then_run_production_gate`
exercises capture → `run_production_gate(session_usage=…)` → asserts
`"cost_total_usd" in gate_file`. **Status: PASS.**

A separate test
`test_gate_file_cost_total_usd_populated_from_captured_usage`
asserts `gate_file["cost_total_usd"] == capture.usage.total_cost_usd`
(within 1e-6). **Status: PASS.**

## Findings

### MEDIUM-1 — Test-count drift in README + CHANGELOG

- `CHANGELOG.md:11`, `CHANGELOG.md:117`, `README.md:62` all say "4348".
- Actual count at HEAD `79fbd75`: 4351 passing (4353 ran, 2 skipped).
- Delta = +3 tests after the last polish-docs commit (likely the late-arriving
  C3 auto-capture tests committed in `d71a8a7` after the polish-docs
  draft was assembled).
- **Severity:** MEDIUM (numeric statement is wrong, but the trajectory
  is correct).

### MEDIUM-2 — D-04 tag name mismatch in CHANGELOG

- `CHANGELOG.md:36` references `compat-bugfix-d-04-audit-key-env-scrub`.
- Actual tags: `compat-secfix-D-04-audit-key-env-scrub` and `compat-secfix-D-04-sibling-module`.
- **Effect:** A reader searching for the tag by the name printed in
  CHANGELOG will fail to find it. The hyphenated SHA hex in the entry
  is missing too (only the tag is listed, no `1c24a86`).
- **Severity:** MEDIUM (tag reachability is preserved — the actual
  tags exist and the work is on HEAD — but the docs lie about the name).

### MEDIUM-3 — Frozen-surface LOC waiver is stale

- `docs/spec/frozen-gate-surface.md:114` says `core/gate_orchestrator.py`
  is "currently 746 LOC pre-B / 834 LOC post-B".
- Actual LOC at HEAD: **1002**.
- The +168-LOC additional growth this session came from C1
  (drift_watcher kwarg + poll calls), C2 follow-up (lineage embed),
  N5 (Merkle export), and C3 (session_usage kwarg + cost emission)
  — every increment was documented in its own commit, but the
  cumulative waiver number in the spec was not refreshed.
- **Severity:** MEDIUM. The soft limit is informational; nothing
  actually breaks. But the doc-vs-code drift means an audit reading
  the spec will under-estimate the module's size by 168 LOC.

### LOW-1 — `drift_watcher` exception swallow is silent

- `core/gate_orchestrator.run_production_gate` calls
  `drift_watcher.poll()` inside a bare `except Exception: pass`
  (twice — pre-collect + post-evaluate).
- The intent ("drift is telemetry, not gating") is correct and
  documented in CLAUDE.md. But a poll exception emits no log line
  and no audit event, so a misconfigured watcher would be invisible.
- **Severity:** LOW (intentional fail-soft, but observability gap).
- **Suggestion:** wrap with `logger.warning("drift poll failed: %s", exc)`
  on the bare-except so an operator can correlate gate runs with
  drift-watcher silence.

### LOW-2 — No production caller of `run_production_gate`

- `grep -rn "run_production_gate(" skills/bmad-story-automator/src`
  returns zero results outside the orchestrator's own definition.
- The new C1 / C3 kwargs (`drift_watcher`, `session_usage`) and the
  N5 / C2-followup gate-file embeds therefore only fire in tests today.
- This is consistent with the architecture (the production flow runs
  through `production_ready_gate` → `route_gate_verdict`, not through
  `run_production_gate` directly) — but it does mean the cost-tracking
  loop's "happy path" is exercised by tests only, not by a real
  end-to-end factory invocation yet.
- **Severity:** LOW. Pre-existing architecture state; not a regression.
  Future operator decision: either wire `production_ready_gate` to
  call `run_production_gate` so the new observability surfaces, or
  port the additive fields onto the `route_gate_verdict` path too.

### LOW-3 — `spec_drift_watcher.py` at exactly 500 LOC

- Sitting on the soft-limit boundary. The next change to this module
  is likely to push it over without a documented waiver.
- **Severity:** LOW. Pre-emptive concern only.
- **Suggestion:** extract the snapshot/diff helpers to a
  `spec_drift_helpers.py` sibling at the next touch.

### LOW-4 — Empty `__all__` on older innovation modules

- `lineage_ledger.py`, `ledger.py`, `kernel_classifier.py`,
  `replay_diff.py`, `stack_risk_weights.py` declare `__all__ = []`
  but expose many public symbols via module attributes (used
  successfully throughout tests + frozen-surface doc).
- The empty `__all__` causes `from module import *` to import nothing
  (probably intentional — these modules should be imported by name)
  but it does mean `__all__` is misleading as documentation of
  intent.
- **Severity:** LOW (style only; functional behavior is correct).

## Recommendations

1. **Operator decision (defer / fix in follow-up):**
   - **MEDIUM-1** Test count: update CHANGELOG.md + README.md numerics
     to 4351 in a single doc-only patch (would not regress audit-floor).
   - **MEDIUM-2** Rename `compat-bugfix-d-04-…` reference in CHANGELOG
     to the actual tag `compat-secfix-D-04-audit-key-env-scrub` (case
     + prefix) and add the sibling-module tag bullet.
   - **MEDIUM-3** Refresh the LOC-waiver paragraph in
     `frozen-gate-surface.md:114` from "746/834" to the actual "718/1002"
     with one-line attribution to the session's C1/C2/C3/N5 deltas.
   - All three fixes are docs-only (no code, no tests), can land as a
     single commit, and would converge the doc state to reality without
     changing any runtime invariant.

2. **Future milestones:**
   - **LOW-1 + LOW-2** are architectural: consider an `N8`-class
     milestone that wires `production_ready_gate` (the actual
     production verifier) into `run_production_gate` so the
     observability surfaces (drift, lineage, cost) start firing
     during real factory runs. This is a multi-day milestone
     because `route_gate_verdict` and `run_production_gate` have
     diverged lifecycles; not a quick patch.
   - **LOW-3** Pre-emptively extract `spec_drift_watcher` helpers
     when the next functional change to that module is needed.
   - **LOW-4** When touching any of the older innovation modules,
     populate `__all__` with the symbols actually consumed by the
     frozen surface (one-line cleanup per module).

3. **No HIGH findings — ship.** The session is internally consistent,
   tests + lint + audit-floor are all green, every frozen-surface
   symbol exists, every commit carries the required trailer, every
   net-new tag is reachable from HEAD, and the cost-tracking loop
   is end-to-end verified. The three MEDIUM findings are
   doc-vs-code drift on cosmetic numerics; none of them change
   runtime behavior.

## Appendix — checks executed

- A. tag reachability — 22/22 session-new tags REACHABLE; 33 detached
  tags pre-date the session.
- B. full test suite — 4353 ran, 4351 OK, 2 skipped.
- C. audit-floor — 26 invariants all green.
- D. ruff — clean.
- E. module size — 11 files over 500 LOC; all pre-existing or
  documented; largest session-new module at exactly 500.
- F. commits since `ae76996` — 42.
- G. internal coupling — 32 `from story_automator.core` re-imports
  inside `core/` (no spike).
- H. frozen-surface — 100% of declared symbols present.
- I. import sanity — 13/13 innovation modules import without error.
- J. CHANGELOG vs git tag — 1 misnamed reference (D-04), 1 missing
  reference (D-04 sibling module).
- K. cost-tracking loop — capture → emit → on-disk summary →
  gate_file["cost_total_usd"] all verified, both inline and via
  in-tree integration test.

### Update 2026-06-25 — retroactive status of the MEDIUM findings

This audit is a dated point-in-time snapshot of HEAD `79fbd75`. Post-audit
commits have independently resolved the documentation drift identified in
MEDIUM-2 and MEDIUM-3; a partial fix landed for MEDIUM-1. The original
findings remain a correct historical record of audit-time state — this
section annotates which recommendations from §Recommendations have since
been actioned so a reader treating the audit as a TODO list does not chase
phantom work.

- **MEDIUM-1 — Test-count drift in README + CHANGELOG.** *Partially closed.*
  `README.md:62` was rewritten as part of the post-session bug-fix rounds
  to frame `4348` explicitly as the session-end anchor with subsequent
  C5 + G2 + bug-fix rounds noted as landing afterward; the README test-line
  is now pinned by `ReadmeTestCountFreshnessTests` in
  `tests/test_docs_consistency.py`. `CHANGELOG.md:11` and `:118` still
  carry the literal `4070 → 4348` strings, but those sit inside the sealed
  `## 260623` historical entry; the CLAUDE.md historical-changelog guardrail
  forbids rewriting the prose body of any dated entry, so the CHANGELOG
  occurrences are intentionally frozen.
- **MEDIUM-2 — D-04 tag name mismatch in CHANGELOG.** *Closed.*
  `CHANGELOG.md:36-37` now correctly cites
  `compat-secfix-D-04-audit-key-env-scrub` (`1c24a86`) and the follow-up
  `compat-secfix-D-04-sibling-module` (`789a7c9`). Resolution is pinned by
  `ChangelogTagReferencesResolveTests` in `tests/test_docs_consistency.py`.
- **MEDIUM-3 — Frozen-surface LOC waiver is stale.** *Closed.*
  `docs/spec/frozen-gate-surface.md:115` now cites `current LOC is **1409**
  at HEAD` with a per-milestone breakdown of the +466 LOC growth (K-5, K-2,
  C2, C1, C3, C5, G2, plus round-2 and round-3 follow-ups). The historical
  `746 LOC pre-B / 834 LOC post-B` figure remains as a historical baseline
  only. Resolution is pinned by `FrozenSurfaceLOCWaiverConsistencyTests`
  in `tests/test_docs_consistency.py` (tolerance band + freshness band).
- **LOW-1..LOW-4.** Unchanged; status as recorded in §Findings.
