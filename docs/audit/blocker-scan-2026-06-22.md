# Blocker Scan & Fix Report — 2026-06-22

## TL;DR

Comprehensive blocker hunt across the working branch. **6 of 9 surveyed blockers fixed in this run; 3 reclassified as tracked tech-debt (none ship-blocking).** Tests went 3,941 → 3,951 (+10, mostly from the parallel N7.1 landing). Repo state is clean: no leftover worktrees, no lint errors, no working-tree drift, no failing tests.

## Blockers found + status

| ID | Category | Issue | Status | Action |
|---|---|---|---|---|
| **B1** | Hygiene | 4 untracked workflow scripts (n6-5, n6-followup-and-n6-7, path-b-continuation, n7-1-tmux) | ✅ Fixed | Committed in `b6c0c14` (chore: workflow archive) |
| **B2** | Workflow state | 2 files modified by in-flight N7.1 workflow | ✅ Resolved | N7.1 workflow landed at `582be81`; working tree clean afterward |
| **B3** | Hygiene | 35 leftover `.claude/worktrees/wf_d544535d-f31-*` directories | ✅ Fixed | `git worktree remove --force` on all 35 + `git worktree prune` |
| **B3b** | Hygiene | 36 leftover local branches (`worktree-wf_d544535d-f31-*` + `m26-gate-rules-priority`) from the lying autonomous run | ✅ Fixed | `git branch -D` on all 36 |
| **B4** | Hygiene | 35 dangling `compat-m25..m60` tags pointing to detached worktree commits | ⏭️ **Kept (intentional)** | Code merged into HEAD via SASA+ landing `f4eabba`; tags preserved as historical traceability — `git show compat-m25-phase-bridge` still shows the original agent intent. No action needed; documented here. |
| **B5** | Tech debt | 5 modules over 500-LOC soft limit | 📋 **Tracked, not a ship blocker** | See "Module size watchlist" below. None are blocking; splits are their own milestones. |
| **B6** | Test health | Skipped tests | ✅ No issue | 2 skipped tests, both intentional, both pre-existing. |
| **B7** | Test health | `tests/deferred/` parked files | ✅ Clear | Directory empty — all previously deferred tests (M51, M59) were restored and pass. |
| **B8** | Lint | 28 ruff errors across 10 files | ✅ Fixed | 26 × E402 fixed by swapping `from __future__ import annotations` to come AFTER module docstring (PEP 257 order). 1 × F841 auto-fixed (unused `as exc`). 1 × F401 auto-fixed (unused KNOWN_STAGES import). Commit `809f05c`. |
| **B9** | Build | Python compile errors | ✅ No issue | 0 compile errors across all 100+ modules. |

## Module size watchlist (B5 detail)

| Module | LOC | Soft limit | Origin | Recommended next action |
|---|---|---|---|---|
| `core/tmux_runtime.py` | 1,749 | 500 | Pre-existing M-something | Major refactor candidate; G3 milestone (4 weeks). Touched only via additive helpers since N6.2 launch. |
| `core/runtime_policy.py` | 622 | 500 | Pre-existing | Validator + accessor split could land in a 1-week cleanup milestone. |
| `core/gate_orchestrator.py` | 595 | 500 | Grew with N5 Merkle export (+10 LOC) | Approaching watch threshold; split next major addition. |
| `core/stop_hooks.py` | 547 | 500 | Pre-existing M-something | Stable; no recent growth. |
| `core/budget_ceilings.py` | 523 | 500 | M59 follow-up added PhaseBudgetCeiling + OverspendAction | Designed for import-locality; agent noted preference for staying-together over splitting. |

**Recommendation:** None of these are ship blockers. Promote to a "tech debt sweep" milestone after Path B is fully bedded in (i.e., after N7.2 flips the cli_dispatcher default).

## Dangling-tag inventory (B4 detail)

35 tags `compat-m25-phase-bridge` through `compat-m60-kernel-violation-classifier` reference commits made by the SASA+ autonomous workflow in detached worktrees (rooted at `9db75a73...`, an unrelated branch). The code these commits embody was successfully re-applied to `bma-d/integration-all` via the recovery landing `f4eabba`.

**Keep status:** the tags are harmless and act as traceability artifacts. An operator can `git show <tag>` to see the original agent's intended file content for any milestone. They will eventually be garbage-collected if reachability falls below `gc.reflogExpire` (default 90 days) and no operator pins them.

**To delete (operator decision, not required):**
```
git tag -l "compat-m[2-6][0-9]-*" | xargs git tag -d
```

## Open items that are NOT blockers but worth tracking

These were surfaced during the blocker scan but determined to be follow-up milestones:

1. **N7.2** — flip `BMAD_AUTO_USE_CLI_DISPATCHER` default to on (after operator exercises the new path in production).
2. **N7.3** — remove the legacy `spawn_session` direct call once N7.2 has bedded in.
3. **Issue 3** (task #47) — orchestrator does not call cli_dispatcher. **Now partially addressed by N7.1's commands/tmux.py wiring**; the orchestrator command itself still routes through the existing path because Path B's design says cli_dispatcher coexists with the legacy path rather than replacing the orchestrator.
4. **G2** — Worktree-per-unit isolation in production paths (3 weeks).
5. **G3** — tmux_runtime de-Claude-ification (4 weeks, unblocked by N6.4 + N6.5 invokers).
6. **G7** — Sprint-phase dual-store unification (1 week).
7. **C1-C5** — live spec-drift watcher, cross-genre lineage, per-collector cost, compliance pack, self-improving gate.

## Verification of clean state

```
HEAD                        : b6c0c14
Branch                      : bma-d/integration-all (ahead of main by 266 commits)
Working tree                : clean
Test suite                  : 3951 passing, 2 skipped, 0 failures
Lint                        : ruff clean (all checks passed)
Compile                     : 0 py_compile errors
Leftover worktrees          : 0
Leftover worktree branches  : 0
Untracked files             : 0
Reachable tags              : every compat-n* tag reachable from HEAD
```

## Decision log

| Decision | Rationale |
|---|---|
| Keep B4 dangling tags | Cheap traceability; deletion is operator-discretionary, not blocking. |
| Skip B5 module splits | Pre-existing; no observable harm. Split as part of dedicated tech-debt milestone. |
| Commit lint cleanup separately from N7.1 | N7.1 was a feature change; lint cleanup is independent stylistic work. Separate commits = clearer history. |
| Move worktree cleanup to this run | Worktrees consumed disk space and cluttered `git worktree list` output. Safe to remove since their tag SHAs are preserved. |
