export const meta = {
  name: 'r3-deferred-batch',
  description: 'Parallel: A-follow (e2e real verdict) + M-3 (audit dirfsync) + L-docstrings batched. Defers K-2 / K-5.',
  phases: [
    { title: 'Parallel' },
    { title: 'Regression' },
    { title: 'Final' },
  ],
}

const REPO = '/home/ubuntu/projects/personal/bmad-automator'

const SHARED = [
  'HARD GUARDRAILS:',
  '- Python 3.11+, stdlib + filelock + psutil ONLY. No new deps.',
  '- DO NOT touch core/telemetry_events.py outside M01.',
  '- DO NOT touch frozen-gate-surface public symbols.',
  '- 500-LOC soft limit per module.',
  '- Conventional Commits + trailer: Generated-By: claude-opus-4-7 + Co-Authored-By line.',
  '- Python: docstring FIRST, then `from __future__ import annotations`, then other imports.',
  '- DO NOT use --no-verify, --amend, force-push, or worktree isolation.',
  '- DO NOT regress audit-floor invariants (26 currently green).',
  '- ALWAYS prefix unittest invocations with PYTHONPATH=skills/bmad-story-automator/src',
  '',
  'CONTEXT:',
  '- Repo: ' + REPO,
  '- Branch: bma-d/integration-all',
  '- HEAD: 3a96d93 (Option 1 serial complete)',
  '- Baseline: 4128 tests passing, ruff clean.',
  '',
  'PER-TASK DISCIPLINE (sw-style):',
  '1. READ 1-3 relevant existing files.',
  '2. PLAN: identify edit points.',
  '3. IMPLEMENT (TDD): failing tests first, minimal impl, re-test.',
  '4. REVIEW: confirm no guardrail breach.',
  '5. PUSH: commit + tag.',
  '6. Return JSON {ok, summary, commit_sha, tests_added, tests_total, notes}.',
].join('\n')

const ITEM_SCHEMA = {
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

phase('Parallel')

const [aFollow, m3, lDocs] = await parallel([

  // ---- A-follow ----
  () => agent([
    SHARED,
    '',
    'TASK A-FOLLOW — extend e2e factory harness to produce a real (non-forced-FAIL) verdict.',
    '',
    'BACKGROUND:',
    'Milestone A landed at abea3f6 — runs run_production_gate against the factory using bundled default.json, but the registry is EMPTY so gate_rules fail-closes on empty active set → overall=FAIL is forced. The lifecycle (Merkle, audit, reuse) is proven; the (collector evidence → verdict) chain is NOT.',
    '',
    'SCOPE: ship the smallest extension that exercises the collector-to-verdict path end-to-end.',
    '',
    'APPROACH (pick the simpler one that actually works):',
    'Option A: Create tests/integration/data/profiles/smoke.json — a profile with exactly ONE active category (correctness). Build a trivial in-test collector that emits status=ok evidence with metrics={coverage_pct: 95, regressions: 0}. Wire it into CollectorRegistry. Run gate. Assert verdict is PASS (or whatever the rules say for those metrics).',
    'Option B: Wire an existing collector (e.g. core/collectors/correctness.py) into the registry against the bundled default profile; skip categories that need tools we do not have via categories_na.',
    '',
    'Pick Option A — simpler, smaller surface, no environmental flakiness.',
    '',
    'STEPS:',
    '1. cd ' + REPO,
    '2. Read tests/integration/test_factory_self_evaluation.py to understand the existing harness shape.',
    '3. Read core/collector_config.py + core/collector_registry.py for the CollectorConfig + registry API.',
    '4. Read core/category_rules.py:correctness_rule to understand what metrics the verdict expects.',
    '5. Read data/profiles/default.json — find category list + rule thresholds for correctness (or pick the simplest category).',
    '6. Create tests/integration/data/profiles/smoke.json with exactly one active category (correctness) + minimal threshold rules.',
    '7. Extend tests/integration/test_factory_self_evaluation.py with a NEW test class FactorySmokeProfileTests that:',
    '   - Sets up a temp project + copies smoke profile into _bmad/.',
    '   - Builds a CollectorRegistry containing ONE in-test CollectorConfig whose build_cmd returns a trivial subprocess that emits metrics on stdout (or write evidence directly via persist_evidence_record).',
    '   - Calls run_production_gate(... registry=registry ...).',
    '   - Asserts overall=PASS AND evidence_merkle_root is 64-hex AND categories has the correctness key with verdict=PASS.',
    '8. Run only the new test: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.integration.test_factory_self_evaluation.FactorySmokeProfileTests -v',
    '9. Full suite: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
    '10. Ruff clean.',
    '11. git commit -m "feat(integration): A-follow — smoke profile + in-test collector produces real PASS verdict" + trailer.',
    '12. git tag a-follow-real-verdict',
    '',
    'IMPORTANT: if Option A turns out impossible due to category_rules requiring evidence shape you cannot fake from a test fixture, document why + ship a partial — assert at least overall != "FAIL_FORCED_BY_EMPTY_REGISTRY".',
    '',
    'Return {ok, summary, commit_sha, tests_added, tests_total, harness_verdict_real, notes}.',
  ].join('\n'), { label: 'a-follow', phase: 'Parallel', schema: ITEM_SCHEMA }),

  // ---- M-3 audit dirfsync ----
  () => agent([
    SHARED,
    '',
    'TASK M-3 — audit log parent-dir fsync for crash durability.',
    '',
    'BACKGROUND:',
    'core/audit.py writes via atomic_io.write_atomic_text (which fsyncs the file). On most filesystems (ext4 default, xfs, apfs), an fsync of the file does NOT guarantee the rename is durable — the parent directory must also be fsynced. Without it, a power loss can revert the rename even though the file content is on disk. This is a real (if subtle) durability bug.',
    '',
    'SCOPE:',
    'Add parent-dir fsync AFTER the atomic rename in core/audit.py append paths. If atomic_io already does this, surface the existing behavior + add a regression test. If it does not, add a dirfsync helper + call it from audit append.',
    '',
    'STEPS:',
    '1. cd ' + REPO,
    '2. Read core/audit.py (find AuditLog.append + write paths).',
    '3. Read core/atomic_io.py write_atomic_text — does it fsync the PARENT DIR?',
    '4. If atomic_io already dirfsyncs: write a regression test in tests/test_bugfix_M3_audit_dirfsync.py that mocks os.fsync and asserts the parent-dir fd is fsynced. Done.',
    '5. If atomic_io does NOT dirfsync: add the dirfsync (open parent O_RDONLY, os.fsync(fd), close) AFTER os.replace. Either in atomic_io.write_atomic_text directly (preferred — fixes ALL atomic writes) OR in a wrapper specifically for audit.',
    '6. Tests: tests/test_bugfix_M3_audit_dirfsync.py — at least 4 tests covering: parent-dir fsync called once per write, missing parent dir handled, Windows fallback (os.fsync on dir not supported — should silently skip), audit-chain integrity preserved after the new fsync.',
    '7. Run: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_bugfix_M3_audit_dirfsync',
    '8. Run audit-foundations: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_audit_foundations tests.test_audit_append tests.test_audit_verify — must remain green.',
    '9. Full suite + ruff.',
    '10. git commit -m "fix(audit): M-3 — fsync parent directory after atomic rename for crash durability" + trailer.',
    '11. git tag compat-bugfix-m3-audit-dirfsync',
    '',
    'WINDOWS NOTE: os.fsync on a directory fd raises on Windows. Detect via sys.platform and silently skip (Windows has different durability semantics on NTFS).',
    '',
    'Return {ok, summary, commit_sha, tests_added, tests_total, dirfsync_was_already_present (bool), notes}.',
  ].join('\n'), { label: 'm3-dirfsync', phase: 'Parallel', schema: ITEM_SCHEMA }),

  // ---- L-1 + L-2 + L-3 docstring batch ----
  () => agent([
    SHARED,
    '',
    'TASK L-DOCS BATCH — fix L-1, L-2, L-3 docstring gaps in a single commit.',
    '',
    'BACKGROUND from round-3 deferred list (docs/audit/round-3-bug-sweep.md):',
    '- L-1: forbidden_until docstring missing/wrong in some module — find the cited file and fix.',
    '- L-2: remediation docstring missing or wrong (likely core/gate_remediation.py).',
    '- L-3: risk action-band docs (likely core/risk_profile.py — describe the 4 bands DOCUMENT/MONITOR/MITIGATE/BLOCK).',
    '',
    'STEPS:',
    '1. cd ' + REPO,
    '2. Read docs/audit/round-3-bug-sweep.md — find the L-1, L-2, L-3 entries with their file paths + recommended patches.',
    '3. For each: read the cited file, write the corrected docstring per the round-3 recommendations.',
    '4. Add tests in tests/test_bugfix_L_docstrings.py (≥3 tests) that import the module and inspect __doc__ for the documented terms (e.g. "forbidden_until" appears in the docstring; "DOCUMENT/MONITOR/MITIGATE/BLOCK" appears in risk action-band docstring).',
    '5. Run: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_bugfix_L_docstrings',
    '6. Full suite + ruff.',
    '7. git commit -m "docs(round-3): L-1+L-2+L-3 — docstring gaps for forbidden_until, remediation, risk action bands" + trailer.',
    '8. git tag compat-bugfix-L-docstrings',
    '',
    'IMPORTANT: docstrings only — do NOT change behavior, do NOT touch signatures.',
    '',
    'Return {ok, summary, commit_sha, tests_added, tests_total, modules_touched (list), notes}.',
  ].join('\n'), { label: 'l-docs', phase: 'Parallel', schema: ITEM_SCHEMA }),

])

const okCount = [aFollow, m3, lDocs].filter(r => r && r.ok).length
log('Parallel: ' + okCount + '/3 shipped')

phase('Regression')

const regression = await agent([
  SHARED,
  '',
  'REGRESSION SWEEP after the 3 parallel agents.',
  '',
  'Tasks:',
  '1. cd ' + REPO,
  '2. git log --oneline 3a96d93..HEAD',
  '3. git tag -l "a-follow-*" "compat-bugfix-m3-*" "compat-bugfix-L-*" | sort',
  '4. Full suite: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
  '5. Audit-floor: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_audit_regression 2>&1 | tail -3',
  '6. Ruff: ruff check skills/bmad-story-automator/src/story_automator/ tests/ 2>&1 | tail -2',
  '7. Working tree status.',
  '',
  'Return {tests_total, audit_floor_count, ruff_clean, working_tree_clean, regressions (list)}.',
].join('\n'), {
  label: 'regression',
  phase: 'Regression',
  schema: {
    type: 'object',
    properties: {
      tests_total: { type: 'number' },
      audit_floor_count: { type: 'number' },
      ruff_clean: { type: 'boolean' },
      working_tree_clean: { type: 'boolean' },
      regressions: { type: 'array', items: { type: 'string' } },
    },
  },
})

phase('Final')

const finalReport = await agent([
  SHARED,
  '',
  'FINAL REPORT.',
  '',
  'Outcomes:',
  '  A-follow: ' + (aFollow?.ok ? 'shipped — ' + aFollow.commit_sha : 'failed'),
  '  M-3:      ' + (m3?.ok ? 'shipped — ' + m3.commit_sha : 'failed'),
  '  L-docs:   ' + (lDocs?.ok ? 'shipped — ' + lDocs.commit_sha : 'failed'),
  '',
  'Tasks:',
  '1. Write status report at docs/audit/r3-deferred-batch-2026-06-22.md with:',
  '   ## TL;DR',
  '   ## Per-item outcomes',
  '   ## What the factory finally proves',
  '   ## What is still deferred (K-2, K-5)',
  '   ## Final state',
  '2. Commit + tag r3-deferred-batch-complete.',
  '',
  'Return {tests_total, items_shipped, report_path, final_tag}.',
].join('\n'), { label: 'final-report', phase: 'Final' })

return { aFollow, m3, lDocs, regression, finalReport }
