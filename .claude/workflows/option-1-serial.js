export const meta = {
  name: 'option-1-serial',
  description: 'Serial: A (e2e harness) → C (round-3 sweep) → B (operability) → D-rereview → D-implement',
  phases: [
    { title: 'MilestoneA' },
    { title: 'MilestoneC' },
    { title: 'MilestoneB' },
    { title: 'D-Rereview' },
    { title: 'MilestoneD' },
    { title: 'Final' },
  ],
}

const REPO = '/home/ubuntu/projects/personal/bmad-automator'

const SHARED = [
  'HARD GUARDRAILS:',
  '- Python 3.11+, stdlib + filelock + psutil ONLY. No new deps.',
  '- DO NOT touch core/telemetry_events.py outside M01.',
  '- DO NOT touch frozen-gate-surface public symbols (read docs/spec/frozen-gate-surface.md).',
  '- 500-LOC soft limit per module.',
  '- Conventional Commits + trailer: Generated-By: claude-opus-4-7 + Co-Authored-By line.',
  '- Python: docstring FIRST, then `from __future__ import annotations`, then other imports.',
  '- DO NOT use --no-verify, --amend, force-push, or worktree isolation.',
  '- DO NOT regress audit-floor invariants (24 currently green).',
  '- ALWAYS prefix unittest invocations with PYTHONPATH=skills/bmad-story-automator/src',
  '  (per Milestone-C review finding C-H-01: without it, suite collects 3665 tests with 28 ImportErrors).',
  '',
  'CONTEXT:',
  '- Repo: ' + REPO,
  '- Branch: bma-d/integration-all',
  '- HEAD before this workflow: ae76996 (per-spec review rollup)',
  '- Baseline: 4070 tests passing, ruff clean.',
  '- Enhanced specs (24 HIGH gaps already patched) live at:',
  '    docs/superpowers/specs/2026-06-22-*-design.md',
  '    docs/superpowers/plans/2026-06-22-*-plan.md',
  '- Per-spec gap reports + rollup at docs/audit/spec-review-2026-06-22-*.md',
  '',
  'SEQUENCING (Option 1 — minimum risk serial):',
  '  Phase 1: MilestoneA  — e2e harness (smallest surface)',
  '  Phase 2: MilestoneC  — round-3 bug sweep (lenses K/L/M)',
  '  Phase 3: MilestoneB  — operability batch (B↔C serialisation respected by running B AFTER C)',
  '  Phase 4: D-Rereview  — ultrathink-gap-analysis on enhanced D spec',
  '  Phase 5: MilestoneD  — only if D-Rereview verdict is ready-to-implement',
  '',
  'PER-TASK DISCIPLINE (sw-style):',
  '1. READ the enhanced spec + plan first.',
  '2. PLAN: identify 2-4 existing files to consult.',
  '3. IMPLEMENT (TDD): failing tests first, minimal impl, re-test.',
  '4. REVIEW: confirm no guardrail breach.',
  '5. PUSH: commit + tag with the milestone tag.',
  '6. Return JSON {ok, summary, commit_sha, tests_added, tests_total, notes}.',
].join('\n')

const IMPL_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    summary: { type: 'string' },
    commit_sha: { type: 'string' },
    tests_added: { type: 'number' },
    tests_total: { type: 'number' },
    notes: { type: 'string' },
  },
  required: ['ok', 'summary'],
}

// ============================================================================
phase('MilestoneA')

const aResult = await agent([
  SHARED,
  '',
  'EXECUTE Milestone A — End-to-end factory self-evaluation harness.',
  '',
  'READ FIRST:',
  '  ' + REPO + '/docs/superpowers/specs/2026-06-22-e2e-factory-harness-design.md',
  '  ' + REPO + '/docs/superpowers/plans/2026-06-22-e2e-factory-harness-plan.md',
  '  ' + REPO + '/docs/audit/spec-review-2026-06-22-milestone-a.md (HIGH gap details)',
  '',
  'CRITICAL HIGH-gap fixes already in the enhanced spec — your implementation MUST honor:',
  '  A-01: audit_policy shape is {"security": {"audit_trail": True}} (NOT {"enabled": True}).',
  '  A-02: profile.hash assertion uses compute_profile_hash directly (do NOT re-read gate_file[\\"profile\\"][\\"hash\\"]).',
  '  A-03: run_production_gate kwargs must include tier=\\"code\\" + factory_version via resolve_factory_version().',
  '  A-04: bundled default.json profile activates 12 categories → empty registry → forced FAIL. The test must EXPECT overall=FAIL on the empty-registry happy path; do not assert PASS.',
  '  A-05: BMAD_AUDIT_KEY save-and-restore protocol — wrap setup/teardown so the operator real env value (if any) is preserved.',
  '',
  'STEPS:',
  '1. cd ' + REPO,
  '2. Build tests/integration/__init__.py + tests/integration/test_factory_self_evaluation.py per the enhanced plan.',
  '3. Use unittest.skipUnless(...) for environment guards (git binary, optional tools).',
  '4. Run only this test: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.integration.test_factory_self_evaluation -v',
  '5. Full suite: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
  '6. Ruff: ruff check skills/bmad-story-automator/src/story_automator/ tests/ — must be clean.',
  '7. git commit -m "feat(integration): A — end-to-end factory self-evaluation harness" + trailer.',
  '8. git tag milestone-A-e2e-factory-harness.',
  '',
  'Return {ok, summary, commit_sha, tests_added, tests_total, harness_verdict, notes}.',
].join('\n'), { label: 'exec-A', phase: 'MilestoneA', schema: IMPL_SCHEMA })

log('Milestone A: ' + (aResult.ok ? 'shipped — ' + aResult.commit_sha : 'failed'))

// ============================================================================
phase('MilestoneC')

const cResult = await agent([
  SHARED,
  '',
  'EXECUTE Milestone C — Round-3 bug sweep with lenses K, L, M.',
  '',
  'READ FIRST:',
  '  ' + REPO + '/docs/superpowers/specs/2026-06-22-round-3-bug-sweep-design.md',
  '  ' + REPO + '/docs/superpowers/plans/2026-06-22-round-3-bug-sweep-plan.md',
  '  ' + REPO + '/docs/audit/spec-review-2026-06-22-C-round-3-bug-sweep.md (HIGH gap details)',
  '',
  'CRITICAL HIGH-gap fixes already in the enhanced spec:',
  '  C-H-01: every unittest invocation prefixed with PYTHONPATH=skills/bmad-story-automator/src',
  '  C-H-02: do NOT reference tests/test_frozen_gate_surface.py (does not exist); use docs/spec/frozen-gate-surface.md',
  '  C-H-03: HEAD pin in §0 audit report is captured at workflow-start time, not hard-coded.',
  '  B↔C serialisation: B runs AFTER C; you do NOT modify evidence_io.py / gate_orchestrator.py during this milestone.',
  '',
  'METHODOLOGY:',
  '1. cd ' + REPO,
  '2. LENS K (cross-module coupling): look for imports from a frozen-surface module that bypass its documented public API.',
  '3. LENS L (test brittleness): identify tests with non-deterministic dict iteration, time-based assertions, missing teardown.',
  '4. LENS M (extended-path docs): scan docstrings vs actual behavior in 6-8 modules.',
  '5. Triage: HIGH-confidence + HIGH-severity ONLY get fixed; max 5 fix-now items. Use the explicit rubric from the enhanced spec.',
  '6. Adversarial verifier step: re-read each promoted finding before applying the fix; default-refute.',
  '7. For each surviving promoted finding: write failing reproducer test, apply minimal fix, re-test.',
  '8. Honest no-finding rule: if you find zero HIGH-confidence bugs, return notes="no HIGH-confidence findings this round" — do NOT pad.',
  '9. Full suite + ruff after all fixes.',
  '10. git commit per fix (subject `fix(bug-r3): <description>`) or single roll-up if findings are tightly coupled.',
  '11. git tag milestone-C-round-3-bug-sweep.',
  '',
  'Return {ok, summary, commit_sha (last), tests_added (total), tests_total, findings_count, fixes_shipped, deferred_count, notes}.',
].join('\n'), { label: 'exec-C', phase: 'MilestoneC', schema: IMPL_SCHEMA })

log('Milestone C: ' + (cResult.ok ? 'shipped — ' + cResult.commit_sha : 'failed'))

// ============================================================================
phase('MilestoneB')

const bResult = await agent([
  SHARED,
  '',
  'EXECUTE Milestone B — Operability batch (B1 PID-reuse + B2 lock-holder visibility + B3 pre-commit gate).',
  '',
  'READ FIRST:',
  '  ' + REPO + '/docs/superpowers/specs/2026-06-22-operability-batch-design.md',
  '  ' + REPO + '/docs/superpowers/plans/2026-06-22-operability-batch-plan.md',
  '  ' + REPO + '/docs/audit/spec-review-2026-06-22-B-operability.md (HIGH gap details)',
  '',
  'CRITICAL HIGH-gap fixes already in the enhanced spec:',
  '  B-H1: subclass filelock.Timeout as GateLockTimeoutError(Timeout); do NOT raise Timeout(msg) — wrong constructor.',
  '  B-H2: ALL THREE get_gate_lock call sites must be patched — gate_orchestrator.py:217+, gate_orchestrator.py:529+, AND system_gate.py:71.',
  '  B-H3: iso_now lives in core/utils.py (NOT core/common.py). Both implementations have second precision — adjust tolerance constants accordingly.',
  '  B-H4: 5.0s tolerance for B1 PID-reuse is re-derived. create_time is process start, NOT marker write time.',
  '  B-H5: observability helpers extracted to NEW sibling module core/gate_lock_observability.py (do NOT add to evidence_io.py — frozen surface + LOC budget).',
  '  B-H6: gate_orchestrator.py is already 718 LOC; observability code MUST go to the sibling module.',
  '',
  'STEPS:',
  '1. cd ' + REPO,
  '2. Sub-fix B1 (PID-reuse hardening) first — extend gate-marker liveness check.',
  '3. Sub-fix B2 (lock-holder visibility) — new core/gate_lock_observability.py module; GateLockTimeoutError subclass; patch ALL 3 call sites.',
  '4. Sub-fix B3 (pre-commit hook) — .githooks/pre-commit + scripts/install-hooks.sh + meta test.',
  '5. TDD each sub-fix. Tests under tests/test_operability_B*.py.',
  '6. Full suite + ruff.',
  '7. Either single commit "feat(operability): B — psutil-create-time + lock-holder log + pre-commit hook" OR 3 sub-commits if cleaner.',
  '8. git tag milestone-B-operability-batch.',
  '',
  'Return {ok, summary, commit_sha, tests_added, tests_total, sub_fixes_shipped (1-3), notes}.',
].join('\n'), { label: 'exec-B', phase: 'MilestoneB', schema: IMPL_SCHEMA })

log('Milestone B: ' + (bResult.ok ? 'shipped — ' + bResult.commit_sha : 'failed'))

// ============================================================================
phase('D-Rereview')

const dRereview = await agent([
  SHARED,
  '',
  'D-REREVIEW — second adversarial ultrathink-gap-analysis on the enhanced D spec/plan.',
  '',
  'D was the largest surface (10 HIGH gaps, 30+ findings). The rollup recommended a second pass after enhancement before implementation.',
  '',
  'READ:',
  '  ' + REPO + '/docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md (ENHANCED post-acf5337)',
  '  ' + REPO + '/docs/superpowers/plans/2026-06-22-g7-sprint-phase-unification-plan.md (ENHANCED)',
  '  ' + REPO + '/docs/audit/spec-review-2026-06-22-milestone-d.md (first-pass gap report)',
  '',
  'RE-REVIEW SCOPE (default to dispute; ≥10 fresh findings target):',
  '- Did the enhancement actually patch the 10 original HIGHs, or did it just acknowledge them?',
  '- Are the new behaviors (observe_only=True, same-volume st_dev precondition, phase-first/sprint-second write order, 4 new frozen-surface symbols, 2 new error subclasses) themselves free of new HIGH gaps?',
  '- Does the enhanced spec interact correctly with B (which just shipped) and C (which just shipped)?',
  '- Is the writer path implementable in 500 LOC?',
  '- Are the test scenarios concrete enough?',
  '',
  'RETURN VERDICT: ready-to-implement | needs-enhancement-now | needs-redesign',
  '',
  'If verdict=ready-to-implement: write a short "D-rereview-pass" note to docs/audit/spec-review-2026-06-22-milestone-d-rereview.md, commit, tag d-rereview-pass.',
  '',
  'If verdict=needs-enhancement-now: write a fresh gap report (max 10 NEW HIGH findings), then EDIT the spec/plan to patch them, commit "docs(specs): D-rereview enhancements (N HIGH gaps patched)", tag d-rereview-enhanced. Then return verdict=ready-to-implement (so Phase 5 proceeds).',
  '',
  'If verdict=needs-redesign: STOP. Write the redesign rationale, do NOT modify the spec, return verdict=needs-redesign so Phase 5 SKIPS.',
  '',
  'Return {ok, verdict, fresh_high_count, gap_report_path, summary, commit_sha (if enhancements landed)}.',
].join('\n'), {
  label: 'd-rereview',
  phase: 'D-Rereview',
  schema: {
    type: 'object',
    properties: {
      ok: { type: 'boolean' },
      verdict: { type: 'string' },
      fresh_high_count: { type: 'number' },
      gap_report_path: { type: 'string' },
      commit_sha: { type: 'string' },
      summary: { type: 'string' },
    },
    required: ['ok', 'verdict'],
  },
})

log('D-Rereview verdict: ' + (dRereview?.verdict || 'unknown'))

// ============================================================================
phase('MilestoneD')

let dResult = null
if (dRereview && dRereview.verdict === 'ready-to-implement') {
  dResult = await agent([
    SHARED,
    '',
    'EXECUTE Milestone D — G7 sprint-phase dual-store unification.',
    '',
    'READ FIRST:',
    '  ' + REPO + '/docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md',
    '  ' + REPO + '/docs/superpowers/plans/2026-06-22-g7-sprint-phase-unification-plan.md',
    '  ' + REPO + '/docs/audit/spec-review-2026-06-22-milestone-d.md (first-pass HIGH gaps)',
    '  ' + REPO + '/docs/audit/spec-review-2026-06-22-milestone-d-rereview.md (second-pass — only if exists)',
    '',
    'CRITICAL HIGH-gap fixes already in the enhanced spec:',
    '  D01: G7 ships the FIRST-EVER sprint-status writer (no existing writer to wrap).',
    '  D02: validate_sprint_status MUST NOT use yaml.safe_load (no new deps allowed) — use the existing stdlib-only parser.',
    '  D03: cross-volume mtime LWW guarded by same-volume st_dev precondition.',
    '  D04/D05: phase-first/sprint-second write order paired with sprint-first/phase-second read order.',
    '  D06: 4 new frozen-surface symbols MUST be declared in docs/spec/frozen-gate-surface.md.',
    '  D07: observe_only=True kwarg present from day one (do NOT defer as follow-up).',
    '  D08: mtime ties handled deterministically (e.g. fallback to phase precedence).',
    '  D09: missing-file vs missing-row error classes are separate subclasses.',
    '  D10: slug vs canonical key reconciliation explicit.',
    '',
    'STEPS:',
    '1. cd ' + REPO,
    '2. Build core/integration/unified_state.py (~250 LOC under 500 budget).',
    '3. Add 2 new error subclasses + observe_only path + 4 frozen-surface symbol declarations.',
    '4. Update docs/spec/frozen-gate-surface.md with the 4 new symbols.',
    '5. TDD: tests/test_unified_state.py with ≥10 tests covering: read-only happy path, write happy path, concurrent writes via lock, mtime LWW with same-volume guard, cross-volume rejection, mtime tie deterministic, missing-file → UnifiedStateMissingError, missing-row → UnifiedStateRowMissingError, observe_only never writes, legacy single-store migration.',
    '6. PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_unified_state -v',
    '7. Adjacent suites must remain green: test_sprint_phase_map, test_story_status, test_phase_bridge.',
    '8. Full suite + ruff.',
    '9. git commit -m "feat(g7): D — unified sprint-status + Phase store with conflict resolution" + trailer.',
    '10. git tag milestone-D-g7-sprint-phase-unification.',
    '',
    'Return {ok, summary, commit_sha, tests_added, tests_total, new_frozen_symbols (list), notes}.',
  ].join('\n'), { label: 'exec-D', phase: 'MilestoneD', schema: IMPL_SCHEMA })
  log('Milestone D: ' + (dResult.ok ? 'shipped — ' + dResult.commit_sha : 'failed'))
} else {
  log('Milestone D SKIPPED — D-Rereview verdict was ' + (dRereview?.verdict || 'unknown') + '; no implementation will run')
}

// ============================================================================
phase('Final')

const finalReport = await agent([
  SHARED,
  '',
  'FINAL REPORT — Option 1 serial execution complete.',
  '',
  'Outcomes:',
  '  A: ' + (aResult?.ok ? 'shipped — ' + aResult.commit_sha : 'failed'),
  '  C: ' + (cResult?.ok ? 'shipped — ' + cResult.commit_sha : 'failed'),
  '  B: ' + (bResult?.ok ? 'shipped — ' + bResult.commit_sha : 'failed'),
  '  D-rereview: ' + (dRereview?.verdict || 'unknown'),
  '  D-implement: ' + (dResult?.ok ? 'shipped — ' + dResult.commit_sha : 'skipped or failed'),
  '',
  'Tasks:',
  '1. cd ' + REPO,
  '2. git log --oneline ae76996..HEAD',
  '3. git tag -l "milestone-*" "d-rereview*" 2>/dev/null | sort',
  '4. PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
  '5. ruff check skills/bmad-story-automator/src/story_automator/ tests/',
  '6. git status --short',
  '',
  'Write rolled-up status at docs/audit/option-1-serial-execution-2026-06-22.md with:',
  '## TL;DR (1 paragraph)',
  '## Per-milestone outcomes (A, C, B, D-rereview, D-implement)',
  '## What shipped (commit SHAs + tags + tests added)',
  '## What did NOT ship + why (if any)',
  '## Final state (HEAD, tests, lint, audit-floor, tags)',
  '## Push readiness — ahead of main by N commits + suggested PR description',
  '## Recommended next operator action',
  '',
  'Commit + tag:',
  '  git add docs/audit/option-1-serial-execution-2026-06-22.md',
  '  git commit -m "docs(audit): Option 1 serial execution complete" + trailer.',
  '  git tag option-1-serial-complete',
  '',
  'Return {tests_total, milestones_shipped, milestones_skipped_or_failed, report_path, final_tag, ahead_of_main}.',
].join('\n'), { label: 'final-report', phase: 'Final' })

return {
  A: aResult,
  C: cResult,
  B: bResult,
  D_rereview: dRereview,
  D: dResult,
  final: finalReport,
}
