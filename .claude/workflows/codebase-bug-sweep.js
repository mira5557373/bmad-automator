export const meta = {
  name: 'codebase-bug-sweep',
  description: 'Codebase-wide bug hunt — 5-lens parallel survey, adversarial verify, fix waves, regression',
  phases: [
    { title: 'Survey' },
    { title: 'Triage' },
    { title: 'Verify' },
    { title: 'Fix-Wave-1' },
    { title: 'Fix-Wave-2' },
    { title: 'Regression' },
    { title: 'Final' },
  ],
}

const REPO = '/home/ubuntu/projects/personal/bmad-automator'
const SRC = REPO + '/skills/bmad-story-automator/src/story_automator'

const SHARED = [
  'HARD GUARDRAILS (CLAUDE.md):',
  '- Python 3.11+, stdlib + filelock + psutil ONLY. No new deps.',
  '- DO NOT touch core/telemetry_events.py outside M01.',
  '- 500-LOC soft limit per module (existing violations are tracked tech debt; do not regress them further).',
  '- Conventional Commits + trailer: Generated-By: claude-opus-4-7 and Co-Authored-By line.',
  '- All Python: from __future__ import annotations BUT after the module docstring (PEP 257).',
  '- DO NOT use --no-verify, --amend, force-push, or worktree isolation.',
  '- DO NOT touch frozen-gate-surface public symbols listed in docs/spec/frozen-gate-surface.md.',
  '- DO NOT modify previous milestone commits.',
  '- Work directly on bma-d/integration-all (no worktrees).',
  '',
  'CONTEXT:',
  '- Repo: ' + REPO,
  '- Branch: bma-d/integration-all',
  '- HEAD: 3b93ef3 (blocker scan report)',
  '- Baseline: 3951 tests passing, 2 skipped, ruff clean, 0 compile errors.',
  '- Recent milestones shipped: SASA+ Wave 1-3 (35 milestones), Path B (N6.2-N6.7), N7.1.',
  '',
].join('\n')

const SURVEY_HEADER = SHARED + [
  '',
  'YOU ARE A BUG HUNTER. Be exhaustive but precise — every finding must cite file:line and explain WHY it is a bug, what the failure mode is, and what severity (HIGH / MEDIUM / LOW).',
  '',
  'OUTPUT FORMAT (JSON-friendly markdown). For each finding:',
  '  ## <ID> — <Title>',
  '  - File: <path>:<line>',
  '  - Severity: HIGH | MEDIUM | LOW',
  '  - Confidence: HIGH | MEDIUM | LOW (how sure are you it is a bug, not intentional)',
  '  - Symptom: <what would go wrong>',
  '  - Reproducer (if possible): <how to trigger>',
  '  - Suggested fix: <minimal patch description>',
  '',
  'TRIAGE BAR:',
  '- HIGH severity = wrong output, crash, data loss, security, determinism break, race condition with real consequence.',
  '- MEDIUM severity = degraded behavior, edge case mishandled, unsafe code that has not yet bitten.',
  '- LOW severity = style, dead code, minor inconsistency.',
  '',
  'DO NOT report:',
  '- Lint issues (already clean).',
  '- Module-size soft-limit violations (tracked tech debt).',
  '- Things that are clearly TODOs or documented limitations.',
  '- Tests that "could be more comprehensive" — only missing tests for KNOWN bugs.',
  '',
  'TARGET: ~5-15 findings per agent, prioritized by impact.',
].join('\n')

const SURVEY_SCHEMA = {
  type: 'object',
  properties: {
    findings_markdown: { type: 'string' },
    finding_count: { type: 'number' },
    high_count: { type: 'number' },
    medium_count: { type: 'number' },
  },
  required: ['findings_markdown', 'finding_count'],
}

// ============================================================================
phase('Survey')

log('Survey: 5 parallel lenses')

const [funcBugs, ioBugs, apiBugs, secBugs, recentBugs] = await parallel([

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS A — Functional bugs + edge cases in core gate subsystem.',
    '',
    'Read modules in this priority order (3-5 files max):',
    '  - core/gate_orchestrator.py (lifecycle, marker handling, gate file emission)',
    '  - core/verdict_engine.py (rule evaluation, evidence aggregation)',
    '  - core/adjudicator.py (verdict synthesis)',
    '  - core/category_rules.py (per-category PASS/CONCERNS/FAIL/NA rules)',
    '  - core/risk_profile.py (P×I matrix, action ladder)',
    '',
    'Look for:',
    '  - Off-by-one in priority threshold boundaries (P0=100/100, P1=95/90, etc.)',
    '  - Edge cases when coverage_pct == fail_floor or boundary',
    '  - Empty evidence bundle handling',
    '  - Waiver expiry comparison (timezone, monotonic vs wallclock)',
    '  - Verdict-routing decisions that swallow exceptions silently',
    '  - Risk score 0 or > 9 handling (out-of-range)',
    '  - Concurrent gate-marker write / read races',
    '',
    'Aim 5-10 findings.',
  ].join('\n'), { label: 'lens-a-functional', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS B — IO correctness, cross-platform, locking, atomicity.',
    '',
    'Read modules (4-6 max):',
    '  - core/atomic_io.py (write_atomic_text, acquire_run_lock, Windows replace retry)',
    '  - core/audit.py (HMAC chain, filelock-based append)',
    '  - core/evidence_io.py (persist_evidence_record, gate marker)',
    '  - core/run_identity.py + core/run_liveness.py (heartbeat, staleness)',
    '  - core/deferred_work.py (custom O_CREAT|O_EXCL lock)',
    '',
    'Look for:',
    '  - Race windows between mkdir + write_atomic + replace.',
    '  - Filelock leaks if exception fires mid-acquire.',
    '  - Windows-replace fallback that swallows non-PermissionError exceptions.',
    '  - hash-chain breakages: if chain interrupted by partial write, can the chain re-validate?',
    '  - Heartbeat staleness threshold off-by-one.',
    '  - Path traversal possible via story_key or gate_id.',
    '  - tempfile.mkdtemp without cleanup on exception path.',
    '  - Unicode normalization for paths (NFC vs NFD).',
    '  - CRLF vs LF in text writes that affect golden-trace comparisons.',
    '',
    'Aim 5-10 findings.',
  ].join('\n'), { label: 'lens-b-io-crossplat', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS C — API consistency, dead code, type bugs.',
    '',
    'Read modules (5-8 max):',
    '  - core/cli_dispatcher.py + core/cli_dispatcher_invokers.py (new N6.5)',
    '  - core/bauto_bridge/hookbus_shim.py (N6.2)',
    '  - core/plugins.py (N6.4)',
    '  - core/action_enum.py (N6.6)',
    '  - core/result_json.py (M40 extension + bauto half)',
    '  - core/profile_composer.py + core/product_profile.py (N4)',
    '  - core/phase_bridge.py + M55 enforcement helpers',
    '',
    'Look for:',
    '  - Functions whose docstring describes a different return type than the code returns.',
    '  - Public functions that are not in __all__ but probably should be.',
    '  - Functions reachable only by dead code paths.',
    '  - Inconsistent error-class hierarchies (some raise ValueError, others raise custom class for same error condition).',
    '  - Type hints that lie (Optional missing, str vs bytes mix, list vs tuple invariants).',
    '  - canonicalize_action vs canonicalize_level vs canonicalize_review_action — same idea, three different APIs.',
    '  - dict-mutation-during-iteration risks.',
    '  - Optional[T] = None defaults that get mutated.',
    '',
    'Aim 5-10 findings.',
  ].join('\n'), { label: 'lens-c-api-deadcode', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS D — Security: command injection, path traversal, unsafe deserialization, trust boundary.',
    '',
    'Read modules (4-6 max):',
    '  - core/trust_boundary.py + core/collector_checkout.py (M16)',
    '  - core/audit.py (HMAC key handling, BMAD_AUDIT_KEY env)',
    '  - core/plugins.py (PluginTrustError, manifest validation)',
    '  - core/tmux_runtime.py (subprocess spawning + env injection)',
    '  - core/cli_dispatcher_invokers.py (subprocess via tmux_runtime)',
    '  - core/checks/*.py (subprocess-driven checks)',
    '',
    'Look for:',
    '  - Any subprocess call that interpolates user input without shlex.quote.',
    '  - shell=True usage (should never happen).',
    '  - eval / exec / pickle usage on untrusted data.',
    '  - YAML safe_load missing somewhere (we are stdlib-only so this might not apply).',
    '  - File reads that follow symlinks into untrusted territory.',
    '  - Path-traversal: story_key or gate_id used in path joining without sanitization.',
    '  - HMAC-key handling: timing attacks, key derivation reuse, fixed-IV concerns.',
    '  - Trust-boundary breaks: collector running in child context, audit-key visible to collectors.',
    '  - Env-var leak: BMAD_AUDIT_KEY exposed in subprocess env.',
    '  - Race conditions in trust-boundary assertions (TOCTOU).',
    '',
    'Single-user threat model context: per ~/.claude/projects/.../memory/singleuser-threat-model.md, threat model is one trusted operator on their own VPS. Do NOT report findings that only matter in multi-tenant deployments.',
    '',
    'Aim 5-10 findings.',
  ].join('\n'), { label: 'lens-d-security', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS E — Recently-shipped modules deep review (Path B + N7.1).',
    '',
    'These are the freshest LOC; they have had the least operator exposure.',
    '',
    'Read in priority (5-7 max):',
    '  - core/cli_dispatcher.py + core/cli_dispatcher_invokers.py (N6.5 + follow-up)',
    '  - core/bauto_bridge/hookbus_shim.py (N6.2)',
    '  - core/plugins.py (N6.4)',
    '  - core/integration/ramr_review_dispatch.py (N3)',
    '  - core/innovation/ramr.py (M53)',
    '  - core/innovation/ledger.py (M54)',
    '  - commands/tmux.py (N7.1 migration)',
    '',
    'Look for:',
    '  - Default values that hide bugs (e.g., empty string sentinel that should be None).',
    '  - Branches that look unreachable but actually are reachable in production.',
    '  - HookBus emit / register order issues.',
    '  - Plugin manifest validation gaps (e.g., empty hooks dict accepted?).',
    '  - SessionIntent / DispatchResult fields that get dropped in translation.',
    '  - Feature flag (BMAD_AUTO_USE_CLI_DISPATCHER) parsing edge cases beyond what tests cover.',
    '  - RAMR routing returning the same model for both dev and review (M55 anti-bias intent).',
    '  - Merkle ledger ordering — does adding an evidence record change a previously-computed root?',
    '',
    'Aim 5-10 findings.',
  ].join('\n'), { label: 'lens-e-recent', phase: 'Survey', schema: SURVEY_SCHEMA }),
])

const totalFindings = funcBugs.finding_count + ioBugs.finding_count + apiBugs.finding_count + secBugs.finding_count + recentBugs.finding_count
const totalHigh = (funcBugs.high_count || 0) + (ioBugs.high_count || 0) + (apiBugs.high_count || 0) + (secBugs.high_count || 0) + (recentBugs.high_count || 0)
log('Survey: ' + totalFindings + ' findings (' + totalHigh + ' HIGH)')

// ============================================================================
phase('Triage')

const triageResult = await agent([
  SHARED,
  '',
  'TRIAGE the survey findings into a single ranked fix-list.',
  '',
  'Inputs (5 survey lenses):',
  '',
  '--- LENS A (functional / gate subsystem) ---',
  funcBugs.findings_markdown,
  '',
  '--- LENS B (IO / cross-platform) ---',
  ioBugs.findings_markdown,
  '',
  '--- LENS C (API / dead code) ---',
  apiBugs.findings_markdown,
  '',
  '--- LENS D (security) ---',
  secBugs.findings_markdown,
  '',
  '--- LENS E (recent modules) ---',
  recentBugs.findings_markdown,
  '',
  'OUTPUT a ranked fix-list:',
  '',
  '## FIX NOW (HIGH severity + HIGH confidence)',
  '   For each: ID, file:line, one-line description, suggested patch sketch, est LOC, est test count',
  '',
  '## FIX IF TIME (MEDIUM severity OR MEDIUM confidence, easy fix)',
  '',
  '## TRACKED TECH DEBT (LOW severity OR LOW confidence OR not worth the churn)',
  '',
  '## DUPLICATES (findings that overlap across lenses — collapse them)',
  '',
  '## DROPPED (false-positives or out-of-scope findings)',
  '',
  'For FIX NOW items, group them by whether they can be fixed in parallel (independent files) or must be sequential (shared file).',
  '',
  'Output total counts at the top.',
].join('\n'), {
  label: 'triage',
  phase: 'Triage',
  schema: {
    type: 'object',
    properties: {
      fix_now: { type: 'array', items: { type: 'object' } },
      fix_if_time: { type: 'array', items: { type: 'object' } },
      tracked_debt: { type: 'array', items: { type: 'object' } },
      duplicates: { type: 'array', items: { type: 'object' } },
      dropped: { type: 'array', items: { type: 'object' } },
      summary: { type: 'string' },
      parallel_safe_count: { type: 'number' },
      sequential_count: { type: 'number' },
    },
    required: ['fix_now', 'summary'],
  },
})

log('Triage: ' + (triageResult.fix_now?.length || 0) + ' fix-now, ' + (triageResult.fix_if_time?.length || 0) + ' fix-if-time')

// ============================================================================
phase('Verify')

const verifyResult = await agent([
  SHARED,
  '',
  'ADVERSARIAL VERIFY of the triage output.',
  '',
  'Triage output:',
  JSON.stringify(triageResult, null, 2).slice(0, 12000),
  '',
  'For each item in FIX NOW: independently re-read the cited file:line and decide if the bug claim is REAL.',
  '',
  'Default to refuted=true unless evidence is overwhelming. Many "bug reports" are intentional behavior or already-handled.',
  '',
  'For each FIX NOW item return:',
  '  - id',
  '  - verdict: confirmed | refuted | overstated',
  '  - actual_severity: HIGH | MEDIUM | LOW | NOT_A_BUG',
  '  - reasoning: 2-3 sentences',
  '  - if refuted, point to the code that already handles it',
  '',
  'Then output the FILTERED FIX-NOW list = only the items with verdict=confirmed and actual_severity=HIGH.',
  '',
  'Cap the filtered list at 12 items — if more pass verification, keep the top 12 by (severity, blast-radius).',
].join('\n'), {
  label: 'verify',
  phase: 'Verify',
  schema: {
    type: 'object',
    properties: {
      verifications: { type: 'array', items: { type: 'object' } },
      filtered_fix_now: { type: 'array', items: { type: 'object' } },
      refuted_count: { type: 'number' },
      confirmed_count: { type: 'number' },
    },
    required: ['filtered_fix_now'],
  },
})

const fixList = verifyResult.filtered_fix_now || []
log('Verify: ' + verifyResult.confirmed_count + ' confirmed, ' + verifyResult.refuted_count + ' refuted; ' + fixList.length + ' to fix')

// ============================================================================
phase('Fix-Wave-1')

log('Fix-Wave-1: parallel fixes (independent files)')

const FIX_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    bug_id: { type: 'string' },
    summary: { type: 'string' },
    commit_sha: { type: 'string' },
    tests_added: { type: 'number' },
    notes: { type: 'string' },
  },
  required: ['ok', 'summary'],
}

// Cap fix-wave-1 at 8 parallel agents to respect concurrency
const parallelCap = 8
const fixesToTry = fixList.slice(0, parallelCap)
log('Dispatching ' + fixesToTry.length + ' parallel fix agents')

const wave1Results = await parallel(
  fixesToTry.map((bug, idx) => () => agent([
    SHARED,
    '',
    'FIX BUG #' + (idx + 1) + ' from the verified fix-list.',
    '',
    'Bug:',
    JSON.stringify(bug, null, 2),
    '',
    'STEPS:',
    '1. cd ' + REPO,
    '2. Read the cited file + 1-2 closely related files.',
    '3. Write a FAILING test that reproduces the bug at tests/test_bugfix_<bug_id>.py.',
    '4. Run only that test: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_bugfix_<bug_id> — confirm it fails.',
    '5. Apply the MINIMAL fix.',
    '6. Re-run the test — must pass.',
    '7. Run full suite: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
    '8. If full suite breaks: STOP, do not commit, return {ok: false, reason: "regression in <test>"}.',
    '9. git add the modified + new files.',
    '10. git commit -m "fix(bug): <short subject covering the bug>" with Generated-By trailer + Co-Authored-By.',
    '',
    'IMPORTANT — if your fix would touch a file ANOTHER agent in this wave might also touch, return {ok: false, deferred: true, reason: "file conflict candidate; defer to wave 2"}.',
    '',
    'Return {ok, bug_id, summary, commit_sha, tests_added, notes}.',
  ].join('\n'), {
    label: 'fix-' + (bug.id || ('bug-' + idx)),
    phase: 'Fix-Wave-1',
    schema: FIX_SCHEMA,
  }))
)

const wave1Ok = wave1Results.filter(r => r && r.ok)
const wave1Deferred = wave1Results.filter(r => r && !r.ok && r.notes && r.notes.includes('deferred'))
const wave1Fail = wave1Results.filter(r => r && !r.ok && !(r.notes && r.notes.includes('deferred')))
log('Wave-1: ' + wave1Ok.length + ' ok, ' + wave1Deferred.length + ' deferred, ' + wave1Fail.length + ' failed')

// ============================================================================
phase('Fix-Wave-2')

const wave2Candidates = [
  ...fixList.slice(parallelCap),
  ...wave1Deferred,
]
log('Fix-Wave-2: ' + wave2Candidates.length + ' sequential fixes')

const wave2Results = []
for (let i = 0; i < wave2Candidates.length; i++) {
  const bug = wave2Candidates[i]
  const r = await agent([
    SHARED,
    '',
    'FIX BUG (sequential wave 2).',
    '',
    'Bug:',
    JSON.stringify(bug, null, 2),
    '',
    'Same TDD steps as wave 1. No concurrency concerns now — you have exclusive write access.',
    '',
    'Return {ok, bug_id, summary, commit_sha, tests_added, notes}.',
  ].join('\n'), {
    label: 'fix-' + (bug.id || ('bug-w2-' + i)),
    phase: 'Fix-Wave-2',
    schema: FIX_SCHEMA,
  })
  wave2Results.push(r)
}

const wave2Ok = wave2Results.filter(r => r && r.ok)
log('Wave-2: ' + wave2Ok.length + ' ok')

// ============================================================================
phase('Regression')

const regressionResult = await agent([
  SHARED,
  '',
  'REGRESSION SWEEP.',
  '',
  'Total reported fixes:',
  '- Wave 1 shipped: ' + wave1Ok.length,
  '- Wave 1 failed: ' + wave1Fail.length,
  '- Wave 1 deferred to wave 2: ' + wave1Deferred.length,
  '- Wave 2 shipped: ' + wave2Ok.length,
  '',
  'Tasks:',
  '1. cd ' + REPO,
  '2. git log --oneline -15',
  '3. git tag -l "bugfix-*" "compat-*" 2>/dev/null | tail -10',
  '4. Full suite: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
  '5. Ruff: ruff check skills/bmad-story-automator/src/story_automator/ tests/ 2>&1 | tail -3',
  '6. Py compile: python3 -c "',
  '     import sys, py_compile, pathlib',
  '     errs = 0',
  '     for p in pathlib.Path(\'skills/bmad-story-automator/src\').rglob(\'*.py\'):',
  '         try:',
  '             py_compile.compile(str(p), doraise=True, quiet=1)',
  '         except py_compile.PyCompileError as e:',
  '             print(f\'COMPILE ERROR: {p}\')',
  '             errs += 1',
  '     print(f\'py_compile errors: {errs}\')"',
  '7. Working tree: git status --short',
  '',
  'Return {tests_total, ruff_clean, compile_errors, working_tree_clean, commits_added_count, notes}.',
].join('\n'), {
  label: 'regression',
  phase: 'Regression',
  schema: {
    type: 'object',
    properties: {
      tests_total: { type: 'number' },
      ruff_clean: { type: 'boolean' },
      compile_errors: { type: 'number' },
      working_tree_clean: { type: 'boolean' },
      commits_added_count: { type: 'number' },
      notes: { type: 'string' },
    },
  },
})

// ============================================================================
phase('Final')

const finalReport = await agent([
  SHARED,
  '',
  'FINAL REPORT.',
  '',
  'Run summary data:',
  '- Survey findings total: ' + totalFindings + ' (' + totalHigh + ' HIGH)',
  '- Triage: ' + (triageResult.fix_now?.length || 0) + ' fix-now, ' + (triageResult.tracked_debt?.length || 0) + ' tracked debt',
  '- Verify confirmed: ' + (verifyResult.confirmed_count || 0) + ', refuted: ' + (verifyResult.refuted_count || 0),
  '- Wave 1 shipped: ' + wave1Ok.length + ' / ' + fixesToTry.length,
  '- Wave 2 shipped: ' + wave2Ok.length + ' / ' + wave2Candidates.length,
  '- Regression result: ' + JSON.stringify(regressionResult).slice(0, 300),
  '',
  'Write comprehensive status report at docs/audit/bug-sweep-2026-06-22.md with:',
  '',
  '## TL;DR',
  '## What we surveyed (5 lenses + scope)',
  '## Total findings table (severity × confidence matrix)',
  '## Bugs fixed (with commit SHAs + 1-line summary each)',
  '## Bugs deferred (per-lens, with reason)',
  '## Adversarial-verifier refutations (what was reported but was not actually a bug)',
  '## Tracked tech debt (LOW-severity items kept for future cleanup)',
  '## Final state (HEAD, tests, lint, compile)',
  '## Recommended follow-ups',
  '',
  'Commit the report:',
  '  git add docs/audit/bug-sweep-2026-06-22.md',
  '  git commit -m "docs(audit): codebase-wide bug sweep report (<N> bugs fixed)" + trailer',
  '  git tag bug-sweep-2026-06-22-complete',
  '',
  'Return {report_path, total_bugs_fixed, tests_total, final_tag}.',
].join('\n'), { label: 'final-report', phase: 'Final' })

return {
  survey: { funcBugs, ioBugs, apiBugs, secBugs, recentBugs, totalFindings, totalHigh },
  triage: triageResult,
  verify: verifyResult,
  wave1: { shipped: wave1Ok.length, failed: wave1Fail.length, deferred: wave1Deferred.length, results: wave1Results },
  wave2: { shipped: wave2Ok.length, results: wave2Results },
  regression: regressionResult,
  finalReport,
}
