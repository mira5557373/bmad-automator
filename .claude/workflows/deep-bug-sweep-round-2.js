export const meta = {
  name: 'deep-bug-sweep-round-2',
  description: 'Round-2 bug hunt — 10 lenses covering collectors, checks, commands, integration, innovation, concurrency, determinism, test quality',
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

const SHARED = [
  'HARD GUARDRAILS (CLAUDE.md):',
  '- Python 3.11+, stdlib + filelock + psutil ONLY. No new deps.',
  '- DO NOT touch core/telemetry_events.py outside M01.',
  '- DO NOT touch frozen-gate-surface public symbols (docs/spec/frozen-gate-surface.md).',
  '- 500-LOC soft limit per module (tracked tech-debt; do not regress further).',
  '- Conventional Commits + trailer: Generated-By: claude-opus-4-7 + Co-Authored-By line.',
  '- Python: docstring FIRST, then `from __future__ import annotations`, then other imports (PEP 257, ruff E402).',
  '- DO NOT use --no-verify, --amend, force-push, or worktree isolation.',
  '- DO NOT regress audit-floor invariants in tests/test_audit_regression.py.',
  '- DO NOT regress the L1+L2 gate-marker lock contract (commits f74bdd4 + 02a96c4).',
  '- Work directly on bma-d/integration-all.',
  '',
  'CONTEXT:',
  '- Repo: ' + REPO,
  '- Branch: bma-d/integration-all',
  '- HEAD: 02a96c4 (L1 follow-up shipped)',
  '- Baseline: 3996 tests passing, 2 skipped, ruff clean, 0 compile errors.',
  '- Prior bug-sweep report: docs/audit/bug-sweep-2026-06-22.md (5 HIGH bugs already fixed; 21 medium + 22 low deferred).',
  '',
].join('\n')

const SURVEY_HEADER = SHARED + [
  '',
  'YOU ARE A BUG HUNTER. Be exhaustive but precise — every finding cites file:line and explains the failure mode + severity + confidence.',
  '',
  'OUTPUT FORMAT (one finding per block):',
  '  ## <ID> — <Title>',
  '  - File: <path>:<line>',
  '  - Severity: HIGH | MEDIUM | LOW',
  '  - Confidence: HIGH | MEDIUM | LOW',
  '  - Symptom: <what goes wrong>',
  '  - Reproducer: <how to trigger or what input>',
  '  - Suggested fix: <minimal patch description>',
  '',
  'TRIAGE BAR:',
  '- HIGH severity = wrong output, crash, data loss, security, determinism break, race with real consequence, fail-open in a fail-closed path.',
  '- MEDIUM = degraded behavior, edge case mishandled, latent risk.',
  '- LOW = style, dead code, minor inconsistency.',
  '',
  'DO NOT REPORT:',
  '- Lint issues (ruff is already clean).',
  '- Module-size soft-limit violations.',
  '- Things clearly documented as TODOs.',
  '- Items already fixed in the prior sweep (L3 worst-of, L4 fail-closed empty, L5 naive ISO, LENS-B-01 lockfile nonce, E2_C9 env contamination, L1+L2 gate marker).',
  '- Tests that merely "could be more comprehensive" — only missing tests for KNOWN bugs.',
  '',
  'TARGET: 5-12 findings per lens, prioritized by impact.',
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

phase('Survey')
log('Survey: 10 parallel lenses (broader scope than prior sweep)')

const surveyResults = await parallel([

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS A — Collectors: subprocess invocation, output parsing, evidence emission.',
    '',
    'Read 4-6 collectors (pick a mix):',
    '  - core/collectors/security.py (semgrep, trivy, osv, gitleaks)',
    '  - core/collectors/correctness.py (unit-test runners)',
    '  - core/collectors/license.py',
    '  - core/collectors/supply_chain.py',
    '  - core/collectors/static.py',
    '  - core/collectors/scalability.py (M52, newest)',
    '',
    'Look for:',
    '  - subprocess.run without timeout (could hang forever).',
    '  - shell=True usage.',
    '  - Stdout parsing that crashes on unexpected JSON / empty output / encoding errors.',
    '  - Evidence emission with wrong metric keys (would not be reduced correctly by the worst-of aggregator from L3 fix).',
    '  - Exit-code interpretation: treating non-zero as PASS or zero as FAIL by mistake.',
    '  - File globbing that follows symlinks.',
    '  - Hardcoded paths that assume Linux.',
    '  - subprocess that ignores stderr when stderr contains the actual error message.',
  ].join('\n'), { label: 'lens-a-collectors', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS B — Check modules: individual check logic + boundary conditions.',
    '',
    'Read 5-7 check modules:',
    '  - core/checks/coverage_check.py',
    '  - core/checks/mutation_check.py',
    '  - core/checks/burn_in_check.py',
    '  - core/checks/hard_wait_check.py (M21)',
    '  - core/checks/adr_check.py (M21, extended in M51)',
    '  - core/checks/invariant_check.py',
    '  - core/checks/presence_check.py',
    '',
    'Look for:',
    '  - Off-by-one in threshold comparisons (< vs <=).',
    '  - Float comparison without tolerance.',
    '  - Empty-input handling (zero tests, zero ADRs).',
    '  - Regex that does not anchor (matches substrings).',
    '  - Division by zero.',
    '  - Iteration over a dict that may be mutated.',
    '  - Functions that return None when caller assumes a dict.',
  ].join('\n'), { label: 'lens-b-checks', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS C — Commands / CLI: argument parsing, action dispatch, JSON output, exit codes.',
    '',
    'Read 5-7 command modules:',
    '  - commands/orchestrator.py + commands/orchestrator_parse.py',
    '  - commands/gate_cmd.py',
    '  - commands/audit_verify_cmd.py',
    '  - commands/triage_cmd.py',
    '  - commands/calibration_cmd.py',
    '  - commands/tmux.py (recent N7.1)',
    '',
    'Look for:',
    '  - argparse without required-args validation.',
    '  - Exit codes that conflict with shell conventions (e.g. 0 on failure).',
    '  - JSON output written to stdout that mixes with debug prints.',
    '  - Command dispatch that does not normalize action name (case-sensitive lookup).',
    '  - Missing newline on JSON output.',
    '  - Path arg accepted but not validated for traversal (../../).',
    '  - Stderr swallow.',
  ].join('\n'), { label: 'lens-c-commands', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS D — Integration glue: bridges, composers, mappers.',
    '',
    'Read 4-6 integration modules:',
    '  - core/integration/bmad_review_bridge.py',
    '  - core/integration/risk_to_story.py',
    '  - core/integration/waiver_to_escalation.py',
    '  - core/integration/sprint_phase_map.py',
    '  - core/integration/worktree_baseline.py',
    '  - core/integration/ramr_review_dispatch.py (N3)',
    '',
    'Look for:',
    '  - Translation losing fields (input keys dropped silently in output).',
    '  - Symmetric round-trip broken (forward then backward does not equal identity).',
    '  - Severity downgrade: CRITICAL mapped to PREFERENCE accidentally.',
    '  - State-machine writes that do not honor LEGAL_TRANSITIONS from M29.',
    '  - Dual-store divergence: M48 sprint-phase-map writes one store but reads the other.',
    '  - Override hierarchy bugs (overlay should win; sometimes base wins).',
  ].join('\n'), { label: 'lens-d-integration', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS E — Innovation modules deep review.',
    '',
    'Read 4-6:',
    '  - core/innovation/ramr.py (RAMR routing)',
    '  - core/innovation/ledger.py (Merkle NFR ledger)',
    '  - core/innovation/replay_diff.py (cross-CLI replay)',
    '  - core/innovation/adversarial_review.py',
    '  - core/innovation/stack_risk_weights.py',
    '  - core/innovation/kernel_classifier.py',
    '  - core/innovation/phase_budget.py',
    '',
    'Look for:',
    '  - Merkle: adding a record changes a PREVIOUSLY-COMPUTED root (ordering bug).',
    '  - Merkle: hash function used on non-canonical JSON (whitespace breaks chain).',
    '  - RAMR: same model returned for both dev and review (anti-bias should reject this).',
    '  - Replay-diff: alignment by (file, check, commit-range) misses cases where one CLI emitted nothing.',
    '  - Adversarial review: failure-mode if reviewer escalates instead of finding.',
    '  - Stack risk: multiplier capped or not? Could go above 9.',
    '  - Kernel classifier: false-positive rate concerns; what if brief uses violation keywords ironically.',
    '  - Phase budget: integer overflow on large token counts; off-by-one in threshold.',
  ].join('\n'), { label: 'lens-e-innovation', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS F — Test quality: flakiness, wrong assertions, gaps.',
    '',
    'Read 5-8 test files (pick a mix of new + old):',
    '  - tests/test_gate_orchestrator.py',
    '  - tests/test_audit_regression.py',
    '  - tests/test_atomic_io.py',
    '  - tests/test_audit_append.py',
    '  - tests/test_telemetry_emitter.py',
    '  - tests/test_bugfix_L1_L2_gate_marker.py (new)',
    '  - tests/test_bugfix_L1_system_gate_lock.py (new)',
    '  - tests/test_cli_dispatcher.py (recent)',
    '',
    'Look for:',
    '  - assertEqual that compares dicts whose key order is non-deterministic.',
    '  - Time-based assertions without freezegun-style time control.',
    '  - Tests that rely on os.environ state at test-run time (test pollution).',
    '  - Tests that share state across methods without proper tearDown.',
    '  - Tests using threading without join timeout (could hang CI).',
    '  - Subprocess in tests without timeout.',
    '  - Race-condition tests that depend on sleep durations.',
    '  - Assertions that check len() == 0 but should check identity.',
    '  - tempfile.mkdtemp without cleanup on test failure.',
  ].join('\n'), { label: 'lens-f-test-quality', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS G — Resource cleanup + error path correctness.',
    '',
    'Read 4-6 modules with resource lifecycle:',
    '  - core/tmux_runtime.py (subprocess + pty + tmux sessions)',
    '  - core/collector_checkout.py (git worktree creation/teardown)',
    '  - core/trust_boundary.py',
    '  - core/atomic_io.py (file handles, tmp files, locks)',
    '  - core/audit.py',
    '  - core/run_liveness.py',
    '',
    'Look for:',
    '  - open() without context manager.',
    '  - Subprocess.Popen without ensuring wait() / terminate().',
    '  - try/except that swallows the original exception (re-raise needed).',
    '  - finally block that itself can raise and mask the original.',
    '  - Temp directories created but not cleaned on exception.',
    '  - File handles inherited by spawned children (FD leak).',
    '  - tmux session leak on collector timeout.',
    '  - SIGPIPE / EPIPE handling on broken stdout pipe.',
    '  - Cleanup order: lock release before file close (or vice versa).',
  ].join('\n'), { label: 'lens-g-resource-cleanup', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS H — Concurrency beyond gate marker (telemetry, audit, calibration writes).',
    '',
    'L1 / L2 already fixed the gate marker. Now look at OTHER concurrent writers.',
    '',
    'Read 4-5 modules:',
    '  - core/telemetry_emitter.py (filelock + threading + fsync)',
    '  - core/audit.py (HMAC chain under filelock)',
    '  - core/calibration.py (read-only? confirm)',
    '  - core/budget_ceilings.py (ledger reader)',
    '  - core/deferred_work.py (already L1B fixed in lockfile-nonce)',
    '',
    'Look for:',
    '  - Append-only writes that race with another writer on the same file.',
    '  - filelock acquired but not released on exception path.',
    '  - Threading.Lock used where filelock is needed (Lock is process-local only).',
    '  - audit-chain breakage: two concurrent appends producing same prev_hash.',
    '  - filelock timeout that is too short for slow disks (e.g. network mount).',
    '  - Multiple readers + one writer without proper coordination.',
    '  - Write that reads, modifies, writes back without holding the lock the whole time.',
  ].join('\n'), { label: 'lens-h-concurrency', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS I — Determinism + reproducibility.',
    '',
    'Read modules whose output should be byte-deterministic:',
    '  - core/evidence_io.py (canonical JSON, hash chain)',
    '  - core/gate_schema.py (waiver signature, factory functions)',
    '  - core/result_json.py + result_json bauto extension',
    '  - core/tea_emit.py',
    '  - tests/golden_trace_helpers.py + tests/golden/*.json',
    '  - core/innovation/ledger.py (Merkle root)',
    '',
    'Look for:',
    '  - json.dumps without sort_keys=True.',
    '  - Dict iteration order assumed (Python 3.7+ guarantees insertion order, but does that match across processes/machines).',
    '  - set() iteration order leaking into output.',
    '  - time.time() / datetime.now() called inline in computation (should be parameterized).',
    '  - random / uuid used in supposedly-deterministic paths.',
    '  - Locale-dependent string operations (.lower() with Turkish locale, etc.).',
    '  - Float repr that varies by platform.',
    '  - tempfile.mkdtemp suffix leaking into hashed evidence.',
  ].join('\n'), { label: 'lens-i-determinism', phase: 'Survey', schema: SURVEY_SCHEMA }),

  () => agent([
    SURVEY_HEADER,
    '',
    'LENS J — Re-triage of deferred MEDIUM-confidence findings from the prior sweep.',
    '',
    'Read the prior sweep report: docs/audit/bug-sweep-2026-06-22.md.',
    '',
    'Section "Bugs deferred (per-lens, with reason)" lists items that were either MEDIUM-confidence, non-fail-closed, or not adjudication-critical.',
    '',
    'Re-evaluate each: with fresh eyes + the round-1 fixes already in place, are any of those deferred items actually HIGH severity in light of new context?',
    '',
    'Specifically look for:',
    '  - Items that interact with the L1+L2 fix (e.g. anything that previously assumed no lock now misbehaves).',
    '  - Items that interact with the L3 worst-of fix (e.g. a collector emitting metrics that the new aggregator handles wrong).',
    '  - Items where a small additional check would prevent a class of bugs.',
    '',
    'Pick 5-10 items from the deferred list that deserve promotion to fix-now status. Re-justify them with current context.',
  ].join('\n'), { label: 'lens-j-redeferred', phase: 'Survey', schema: SURVEY_SCHEMA }),

])

const totalFindings = surveyResults.reduce((s, r) => s + (r ? (r.finding_count || 0) : 0), 0)
const totalHigh = surveyResults.reduce((s, r) => s + (r ? (r.high_count || 0) : 0), 0)
log('Survey done: ' + totalFindings + ' findings (' + totalHigh + ' HIGH)')

phase('Triage')

const triageResult = await agent([
  SHARED,
  '',
  'TRIAGE the 10-lens survey findings into a ranked fix-list.',
  '',
  'Lens A (collectors): ' + (surveyResults[0]?.findings_markdown || ''),
  '',
  'Lens B (checks): ' + (surveyResults[1]?.findings_markdown || ''),
  '',
  'Lens C (commands): ' + (surveyResults[2]?.findings_markdown || ''),
  '',
  'Lens D (integration): ' + (surveyResults[3]?.findings_markdown || ''),
  '',
  'Lens E (innovation): ' + (surveyResults[4]?.findings_markdown || ''),
  '',
  'Lens F (test quality): ' + (surveyResults[5]?.findings_markdown || ''),
  '',
  'Lens G (resource cleanup): ' + (surveyResults[6]?.findings_markdown || ''),
  '',
  'Lens H (concurrency): ' + (surveyResults[7]?.findings_markdown || ''),
  '',
  'Lens I (determinism): ' + (surveyResults[8]?.findings_markdown || ''),
  '',
  'Lens J (re-triage): ' + (surveyResults[9]?.findings_markdown || ''),
  '',
  'Output ranked sections:',
  '',
  '## FIX NOW (HIGH severity + HIGH confidence). For each: id, file:line, one-line, suggested fix, est LOC, est tests.',
  '## FIX IF TIME (MEDIUM severity OR MEDIUM confidence, easy fix).',
  '## TRACKED TECH DEBT (LOW severity OR LOW confidence).',
  '## DUPLICATES (collapse cross-lens overlaps).',
  '## DROPPED (false positives or out-of-scope).',
  '',
  'For FIX NOW items, group by whether they can be fixed in parallel (independent files) or must be sequential (shared file).',
  '',
  'Cap FIX NOW at 15 items if more pass — keep the top 15 by (severity × confidence × blast-radius).',
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
      parallel_safe_ids: { type: 'array', items: { type: 'string' } },
      sequential_ids: { type: 'array', items: { type: 'string' } },
    },
    required: ['fix_now', 'summary'],
  },
})

log('Triage: ' + (triageResult.fix_now?.length || 0) + ' fix-now items')

phase('Verify')

const verifyResult = await agent([
  SHARED,
  '',
  'ADVERSARIAL VERIFY the triage. Default to dispute=true unless evidence is overwhelming.',
  '',
  'Triage output (FIX NOW only):',
  JSON.stringify(triageResult.fix_now || [], null, 2).slice(0, 14000),
  '',
  'For each FIX NOW item: independently re-read the cited file:line + decide if the bug claim is REAL.',
  '',
  'For each:',
  '  - id',
  '  - verdict: confirmed | refuted | overstated',
  '  - actual_severity: HIGH | MEDIUM | LOW | NOT_A_BUG',
  '  - reasoning (2-3 sentences)',
  '  - if refuted: file:line of the existing handling that makes it a non-issue',
  '',
  'Output filtered list = items with verdict=confirmed AND actual_severity in {HIGH, MEDIUM}.',
  '',
  'Cap filtered list at 12 items.',
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

phase('Fix-Wave-1')

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

const parallelCap = 8
const wave1Items = fixList.slice(0, parallelCap)
log('Wave-1: ' + wave1Items.length + ' parallel fix agents')

const wave1Results = await parallel(
  wave1Items.map((bug, idx) => () => agent([
    SHARED,
    '',
    'FIX BUG #' + (idx + 1) + ' from the verified fix-list.',
    '',
    'Bug payload:',
    JSON.stringify(bug, null, 2),
    '',
    'STEPS:',
    '1. cd ' + REPO,
    '2. Read the cited file + 1-2 closely related files.',
    '3. Write a FAILING test reproducing the bug at tests/test_bugfix_r2_<bug_id>.py.',
    '4. Run only that test, confirm failure.',
    '5. Apply MINIMAL fix.',
    '6. Re-run test, confirm pass.',
    '7. Run full suite: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
    '   - If regressions: STOP, return {ok: false, reason}.',
    '8. git add + commit with subject `fix(bug-r2): <short description>` + Generated-By trailer + Co-Authored-By.',
    '',
    'IMPORTANT: if your fix would touch a file ANOTHER agent in this wave might touch, return {ok: false, deferred: true, reason: "file conflict candidate"}.',
    '',
    'Return {ok, bug_id, summary, commit_sha, tests_added, notes}.',
  ].join('\n'), {
    label: 'fix-r2-' + (bug.id || ('bug-' + idx)),
    phase: 'Fix-Wave-1',
    schema: FIX_SCHEMA,
  }))
)

const wave1Ok = wave1Results.filter(r => r && r.ok)
const wave1Deferred = wave1Results.filter(r => r && !r.ok && r.notes && r.notes.includes('deferred'))
const wave1Fail = wave1Results.filter(r => r && !r.ok && !(r.notes && r.notes.includes('deferred')))
log('Wave-1: ' + wave1Ok.length + ' ok, ' + wave1Deferred.length + ' deferred, ' + wave1Fail.length + ' failed')

phase('Fix-Wave-2')

const wave2Candidates = [...fixList.slice(parallelCap), ...wave1Deferred]
log('Wave-2: ' + wave2Candidates.length + ' sequential fixes')

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
    'Same TDD steps as wave 1.',
    'Return {ok, bug_id, summary, commit_sha, tests_added, notes}.',
  ].join('\n'), {
    label: 'fix-r2-' + (bug.id || ('bug-w2-' + i)),
    phase: 'Fix-Wave-2',
    schema: FIX_SCHEMA,
  })
  wave2Results.push(r)
}

const wave2Ok = wave2Results.filter(r => r && r.ok)
log('Wave-2: ' + wave2Ok.length + ' ok')

phase('Regression')

const regressionResult = await agent([
  SHARED,
  '',
  'REGRESSION SWEEP.',
  '',
  'Reported fixes — Wave 1: ' + wave1Ok.length + ', Wave 2: ' + wave2Ok.length + ', total: ' + (wave1Ok.length + wave2Ok.length),
  '',
  'Tasks:',
  '1. cd ' + REPO,
  '2. git log --oneline -15',
  '3. git tag -l "compat-bugfix-r2-*" | sort',
  '4. Full suite + count.',
  '5. Ruff check.',
  '6. py_compile across entire src tree.',
  '7. Working tree clean check.',
  '8. Audit-floor invariants: PYTHONPATH=... python3 -m unittest tests.test_audit_regression 2>&1 | tail -3',
  '',
  'Return {tests_total, ruff_clean, compile_errors, working_tree_clean, audit_floor_green, commits_added, notes}.',
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
      audit_floor_green: { type: 'boolean' },
      commits_added: { type: 'number' },
      notes: { type: 'string' },
    },
  },
})

phase('Final')

const finalReport = await agent([
  SHARED,
  '',
  'FINAL REPORT.',
  '',
  'Summary:',
  '- Survey findings: ' + totalFindings + ' (' + totalHigh + ' HIGH)',
  '- Triage fix-now: ' + (triageResult.fix_now?.length || 0),
  '- Verify confirmed: ' + (verifyResult.confirmed_count || 0) + ', refuted: ' + (verifyResult.refuted_count || 0),
  '- Wave 1 shipped: ' + wave1Ok.length + ' / ' + wave1Items.length,
  '- Wave 2 shipped: ' + wave2Ok.length + ' / ' + wave2Candidates.length,
  '- Regression: ' + JSON.stringify(regressionResult).slice(0, 300),
  '',
  'Write report at docs/audit/bug-sweep-round-2-2026-06-22.md with:',
  '',
  '## TL;DR',
  '## What we surveyed (10 lenses + scope)',
  '## Findings matrix (severity × confidence)',
  '## Bugs fixed (with commit SHAs + 1-line summaries)',
  '## Bugs deferred',
  '## Adversarial-verifier refutations',
  '## Tracked tech debt (LOW-severity for future cleanup)',
  '## Final state (HEAD, tests, lint, compile, audit-floor)',
  '## Recommended next-up',
  '',
  'Commit the report:',
  '  git add docs/audit/bug-sweep-round-2-2026-06-22.md',
  '  git commit -m "docs(audit): round-2 bug sweep report (<N> bugs fixed)" + trailer',
  '  git tag bug-sweep-round-2-complete',
  '',
  'Return {report_path, total_bugs_fixed, tests_total, final_tag, deferred_count}.',
].join('\n'), { label: 'final-report', phase: 'Final' })

return {
  survey: surveyResults,
  totalFindings,
  totalHigh,
  triage: triageResult,
  verify: verifyResult,
  wave1: { shipped: wave1Ok.length, failed: wave1Fail.length, deferred: wave1Deferred.length, results: wave1Results },
  wave2: { shipped: wave2Ok.length, results: wave2Results },
  regression: regressionResult,
  finalReport,
}
