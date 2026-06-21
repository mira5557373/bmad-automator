export const meta = {
  name: 'sasa-plus-autonomous-run',
  description: 'Autonomous SASA+ implementation: Wave 0 + Wave 1 (19 cliff fixes) + Wave 2 + Wave 3 + gap analysis',
  phases: [
    { title: 'Anchor' },
    { title: 'Wave0' },
    { title: 'Wave1A' },
    { title: 'Wave1B' },
    { title: 'Wave1C' },
    { title: 'Wave1Verify' },
    { title: 'Wave2' },
    { title: 'Wave3' },
    { title: 'Final' },
  ],
}

const REPO = '/home/ubuntu/projects/personal/bmad-automator'
const SRC = REPO + '/skills/bmad-story-automator/src/story_automator'

const SHARED_RULES = [
  'HARD GUARDRAILS (from CLAUDE.md):',
  '- Python 3.11+, stdlib + filelock + psutil ONLY. No new deps.',
  '- DO NOT touch core/telemetry_events.py outside M01.',
  '- 500-LOC soft limit per Python module.',
  '- Conventional Commits. Every commit needs trailer:',
  '    Generated-By: claude-opus-4-7',
  '- No trailing whitespace, no whitespace-only churn, no line-ending changes.',
  '- All Python: `from __future__ import annotations` at top.',
  '',
  'WORKFLOW PER MILESTONE (sw-style discipline):',
  '1. PLAN: read 1-3 relevant existing files only.',
  '2. IMPLEMENT (TDD):',
  '   a. Write failing test at tests/test_<module>.py',
  '   b. Run only that test, confirm failure.',
  '   c. Write implementation under skills/bmad-story-automator/src/story_automator/core/<module>.py',
  '   d. Run only that test, confirm pass.',
  '3. REVIEW: confirm no telemetry_events.py touched and no new deps.',
  '4. PUSH: stage files, commit with trailer, tag the milestone.',
  '',
  'NEVER:',
  '- npm install / pip install anything new',
  '- modify core/telemetry_events.py',
  '- commit with --no-verify',
  '- amend prior commits',
  '- force-push',
].join('\n')

const REPO_CONTEXT = [
  'Local code at ' + REPO,
  'Python src under ' + SRC + '/core/ and ' + SRC + '/commands/',
  'Tests under ' + REPO + '/tests/',
  'Test invocation: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.<module>',
  'Full suite: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests',
  'Baseline = 3124 tests passing.',
  '',
  'Existing milestone tags: phase-0-audit-floor, phase-1-defensive-primitives, phase-2-result-schema-and-policy, phase-3-pre-gate-verifier, phases-4-6-deferred.',
  'Each milestone adds tag compat-mNN-slug.',
].join('\n')

// ============================================================================
phase('Anchor')

log('Anchor: writing umbrella spec + roadmap + Wave-0 plan in parallel')

await parallel([
  () => agent([
    SHARED_RULES,
    REPO_CONTEXT,
    '',
    'WRITE the UMBRELLA DESIGN SPEC at exactly:',
    '  ' + REPO + '/docs/superpowers/specs/2026-06-21-multi-module-compat-design.md',
    '',
    'Use the Write tool.',
    '',
    'REQUIRED H2 SECTIONS:',
    '1. Goal',
    '2. Five-module landscape (BMAD-METHOD v6.8, TEA v1.19, WDS v0.4.3, bmad-auto v0.6.1, sw v1.4)',
    '3. The 80-contract matrix (top 30 rows + summary)',
    '4. Wave structure (W0 pre-flight, W1 cliff-fixes, W2 composition, W3 innovation moats, W4 deferred upstream)',
    '5. Milestone roadmap (M25 through M60)',
    '6. The 10 innovation moats',
    '7. Cross-module dependencies',
    '8. Hard guardrails reaffirmed',
    '9. Verification strategy',
    '10. Risk register',
    '11. Decision log',
    '',
    'Target length: 600-1200 lines. Use tables. Cite file:line for every contract claim (Bash-grep to verify).',
    'Match the tone of docs/superpowers/specs/2026-06-20-production-ready-factory-design.md but more concise.',
  ].join('\n'), { label: 'spec-umbrella', phase: 'Anchor' }),

  () => agent([
    SHARED_RULES,
    REPO_CONTEXT,
    '',
    'WRITE the MILESTONE ROADMAP at exactly:',
    '  ' + REPO + '/docs/superpowers/specs/2026-06-21-multi-module-compat-roadmap.md',
    '',
    'Use the Write tool.',
    '',
    'One H1, then a giant TABLE with columns:',
    '| M | Wave | Title | Owner module(s) | Depends on | Plan file (relative path) | Status | Effort (LOC/wk) |',
    '',
    '36 milestone rows: M25 through M60.',
    'Wave 1: M25 (phase-bridge), M26 (gate-rules-priority), M27 (story-keys-epic-retro), M28 (story-writer), M29 (story-status), M30 (tea-emit), M31 (deferred-work), M32 (cli-profile), M33 (review-taxonomy), M34 (coverage-status), M35 (test-levels), M36 (kernel-schema), M37 (risk-action-bands), M38 (sprint-schema), M39 (policy-translator), M40 (result-json-bauto), M41 (escalation-emit), M42 (hook-env-bmad-auto), M43 (install-paths-seed).',
    'Wave 2: M44 (profile-composer), M45 (bmad-review-bridge), M46 (risk-to-story-dar), M47 (waiver-to-escalation), M48 (sprint-phase-map), M49 (worktree-baseline), M50 (usage-parsers), M51 (adr-29-criterion), M52 (scalability-collector).',
    'Wave 3: M53 (ramr), M54 (merkle-nfr-ledger), M55 (anti-bias-phase-roundtrip), M56 (stack-risk-weights), M57 (adversarial-review-by-construction), M58 (cross-cli-replay-diff), M59 (phase-shaped-budgets), M60 (kernel-violation-classifier).',
    '',
    'End with H2 sections: Status legend, Dependencies graph (ASCII), How to drive (sw or equivalent).',
    'Target length: 250-450 lines.',
  ].join('\n'), { label: 'spec-roadmap', phase: 'Anchor' }),

  () => agent([
    SHARED_RULES,
    REPO_CONTEXT,
    '',
    'WRITE the WAVE 0 PRE-FLIGHT PLAN at exactly:',
    '  ' + REPO + '/docs/superpowers/plans/2026-06-21-compat-w0-pre-flight.md',
    '',
    'Use the Write tool.',
    '',
    'Three pre-flight tasks:',
    '1. Commit docs/audit/ (untracked).',
    '2. Capture baseline test count to docs/audit/baseline-tests.txt.',
    '3. Pin external/* submodule SHAs in .gitmodules + add CI assertion (defer if non-trivial).',
    '',
    'Match the format of docs/superpowers/plans/2026-06-20-foundation-m1-product-profile.md (checkbox tasks, file paths, conventions). Target length: 200-400 lines.',
  ].join('\n'), { label: 'plan-wave0', phase: 'Anchor' }),
])

log('Anchor docs landed.')

// ============================================================================
phase('Wave0')

log('Wave 0: executing pre-flight (commit audit dir, capture baseline)')

const wave0 = await agent([
  SHARED_RULES,
  REPO_CONTEXT,
  '',
  'EXECUTE WAVE 0. Use Bash tool. CWD = ' + REPO,
  '',
  'TASK 1 — Commit docs/audit/:',
  '  cd ' + REPO,
  '  git status --short',
  '  # If docs/audit/ exists and is untracked, stage and commit it.',
  '  git add docs/audit/',
  '  git commit -m "docs(audit): commit deferred audit-trail for SASA+ Wave 0',
  '',
  'Wave 0 of the multi-module compatibility program. Holds the running matrix of contracts honored vs gaps across BMAD-METHOD, TEA, WDS, bmad-auto, and sw.',
  '',
  'Generated-By: claude-opus-4-7',
  '',
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"',
  '  git tag compat-w0-audit-trail',
  '',
  'TASK 2 — Capture baseline test count:',
  '  cd ' + REPO,
  '  mkdir -p docs/audit',
  '  PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep "^Ran" > /tmp/baseline.txt',
  '  echo "Baseline test count captured 2026-06-21 (SASA+ start)" > docs/audit/baseline-tests.txt',
  '  cat /tmp/baseline.txt >> docs/audit/baseline-tests.txt',
  '  git add docs/audit/baseline-tests.txt',
  '  git commit -m "docs(audit): capture baseline test count before SASA+ Wave 1',
  '',
  'Pre-SASA+ test count recorded so every Wave 1 milestone can demonstrate non-regression.',
  '',
  'Generated-By: claude-opus-4-7',
  '',
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"',
  '  git tag compat-w0-baseline',
  '',
  'Return JSON: {tests_baseline: "<count line>", commits_landed: 2, tags: ["compat-w0-audit-trail", "compat-w0-baseline"]}',
].join('\n'), {
  label: 'exec-wave0',
  phase: 'Wave0',
  schema: {
    type: 'object',
    properties: {
      tests_baseline: { type: 'string' },
      commits_landed: { type: 'number' },
      tags: { type: 'array', items: { type: 'string' } },
    },
    required: ['commits_landed'],
  },
})

log('Wave 0 done: ' + JSON.stringify(wave0).slice(0, 200))

// ============================================================================
// Helper to build per-milestone agent prompt
function milestonePrompt(m) {
  const moduleSlug = m.slug.replace(/-/g, '_')
  return [
    SHARED_RULES,
    REPO_CONTEXT,
    '',
    'MILESTONE ' + m.id + ' — ' + m.slug,
    '',
    m.desc,
    '',
    'EXECUTION:',
    '1. cd ' + REPO,
    '2. Read any existing module you will modify (max 2 reads).',
    '3. Write failing test at tests/test_' + moduleSlug + '.py',
    '4. Run only that test: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_' + moduleSlug + ' — confirm failure.',
    '5. Implement the module under skills/bmad-story-automator/src/story_automator/core/.',
    '6. Re-run only that test, confirm pass.',
    '7. Run full suite for non-regression: PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
    '   If FAILED: STOP, do NOT commit, return {ok: false, milestone: "' + m.id + '", reason: "<failing test>"}.',
    '8. git add the new/modified files.',
    '9. git commit -m "feat(compat): ' + m.id + ' ' + m.slug + ' — <summary>" with Generated-By trailer.',
    '10. git tag compat-' + m.id.toLowerCase() + '-' + m.slug,
    '',
    'Return: {ok: true, milestone: "' + m.id + '", commit_sha: "<sha>", loc_added: N, tests_added: K, tests_total: T}',
    'Or on failure: {ok: false, milestone: "' + m.id + '", reason: "..."}',
    '',
    'No --no-verify. No amend. No push.',
  ].join('\n')
}

const MILESTONE_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    milestone: { type: 'string' },
    commit_sha: { type: 'string' },
    loc_added: { type: 'number' },
    tests_added: { type: 'number' },
    tests_total: { type: 'number' },
    reason: { type: 'string' },
  },
  required: ['ok', 'milestone'],
}

// ============================================================================
phase('Wave1A')

log('Wave 1 Group A: 10 independent new modules in parallel (worktree-isolated)')

const W1A = [
  {
    id: 'M25', slug: 'phase-bridge',
    desc: [
      'Port bmad-auto Phase StrEnum (11 values per external/bmad-auto/src/automator/model.py:11-23):',
      '  pending, dev-running, dev-verify, review-running, review-verify, committing,',
      '  triage-running, triage-verify, done, deferred, escalated',
      '',
      'Public API in core/phase_bridge.py:',
      '  class Phase(StrEnum): ... (11 values, kebab-case strings)',
      '  TERMINAL_PHASES = frozenset({Phase.DONE, Phase.DEFERRED, Phase.ESCALATED})',
      '  PAUSE_STAGES = frozenset({"spec-approval", "epic-boundary", "escalation", "story-gate"})',
      '  STEP_TO_PHASES: dict[str, frozenset[Phase]] — 5-step (create/dev/auto/review/retro) → Phase set',
      '  PHASE_TO_STEP: dict[Phase, str] — Phase → step',
      '  def is_terminal_phase(phase) -> bool',
      '  def pause_stage_for_phase(phase) -> str | None',
      '  def step_for_phase(phase) -> str',
      '  def phases_for_step(step) -> frozenset[Phase]',
      '',
      'Tests in tests/test_phase_bridge.py: at minimum 12 covering each Phase value, TERMINAL_PHASES, PAUSE_STAGES, round-trip step→phase→step, unknown-phase handling.',
    ].join('\n'),
  },
  {
    id: 'M28', slug: 'story-writer',
    desc: [
      'New core/story_writer.py.',
      '',
      'Public API:',
      '  def write_story_header(path, *, epic: int, story: int, title: str) -> Path',
      '    writes "# Story {epic}.{story}: {title}" as first line',
      '  def seed_status_sentinel(path, status: str = "ready-for-dev") -> None',
      '    atomically appends "Status: <status>" if not present',
      '  def write_story_skeleton(path, *, epic, story, title, status="ready-for-dev") -> Path',
      '    convenience combining the two with minimal section scaffold',
      '  VALID_INITIAL_STATUSES = frozenset({"backlog", "ready-for-dev"})',
      '',
      'Use core/atomic_io.write_atomic_text.',
      '',
      'Tests in tests/test_story_writer.py: ≥8 covering correct H1, seeded status, idempotent re-seed, invalid status raises, atomic write, integration with parsing.',
    ].join('\n'),
  },
  {
    id: 'M29', slug: 'story-status',
    desc: [
      'New core/story_status.py — BMAD status state machine.',
      '',
      'VALID_STATUSES = frozenset({"backlog", "ready-for-dev", "in-progress", "review", "done"})',
      'LEGAL_TRANSITIONS: dict mapping each status -> frozenset of legal next statuses.',
      '  backlog -> {ready-for-dev}',
      '  ready-for-dev -> {in-progress, backlog}',
      '  in-progress -> {review, ready-for-dev}',
      '  review -> {in-progress, done}',
      '  done -> frozenset()',
      'LEGACY_ALIASES = {"drafted": "ready-for-dev", "contexted": "in-progress"}',
      '',
      'API: StoryStatusError, canonicalize, is_valid, transition, is_terminal, is_actionable (in {"backlog","ready-for-dev"}).',
      '',
      'Tests in tests/test_story_status.py: ≥10 covering every legal/illegal transition, alias canonicalization, terminal, actionable.',
    ].join('\n'),
  },
  {
    id: 'M30', slug: 'tea-emit',
    desc: [
      'New core/tea_emit.py — emits TEA artifacts.',
      '',
      'def write_trace_summary(path, *, story_key, requirements, coverage_by_level, schema_version="0.1.0") -> Path',
      '  Schema keys: schema_version, story_key, requirements (list of {id, covered, level}), coverage_by_level',
      '',
      'def write_gate_decision(path, *, story_key, verdict, categories, commit_sha, schema_version="0.1.0") -> Path',
      '  verdict in {"PASS","CONCERNS","FAIL","WAIVED"}',
      '  Schema keys: schema_version, story_key, verdict, categories, commit_sha',
      '',
      'VALID_VERDICTS = frozenset({"PASS","CONCERNS","FAIL","WAIVED"})',
      'VALID_CATEGORY_VERDICTS = frozenset({"PASS","CONCERNS","FAIL","NA"})',
      '',
      'Use atomic_io.write_atomic_text + json.dumps(sort_keys=True) for determinism.',
      '',
      'Tests in tests/test_tea_emit.py: ≥8.',
    ].join('\n'),
  },
  {
    id: 'M31', slug: 'deferred-work',
    desc: [
      'New core/deferred_work.py.',
      '',
      'DEFERRED_WORK_PATH_RELATIVE = "_bmad/bmm/deferred-work.md"',
      'VALID_SEVERITIES = frozenset({"CRITICAL", "PREFERENCE"})',
      'def append_entry(project_root, *, title, reason, owner_story, severity="PREFERENCE") -> Path',
      'def list_entries(project_root) -> list[dict]',
      '',
      'Use atomic_io.write_atomic_text + filelock for write coordination.',
      '',
      'Tests in tests/test_deferred_work.py: ≥7.',
    ].join('\n'),
  },
  {
    id: 'M33', slug: 'review-taxonomy',
    desc: [
      'New core/review_taxonomy.py.',
      '',
      'VALID_REVIEW_ACTIONS = frozenset({"decision_needed", "patch", "defer", "dismiss"})',
      'class ReviewActionError(ValueError): pass',
      'def canonicalize_action(raw) -> str  # case-insensitive',
      'def format_review_row(*, action, finding, file_ref="", line=None) -> str',
      '  "[Review][<action>] <file>:<line> <finding>" markdown row',
      'def parse_review_row(row) -> dict | None  # inverse',
      '',
      'Tests in tests/test_review_taxonomy.py: ≥8.',
    ].join('\n'),
  },
  {
    id: 'M34', slug: 'coverage-status',
    desc: [
      'New core/coverage_status.py.',
      '',
      'VALID_COVERAGE_STATUSES = frozenset({"FULL","PARTIAL","UNIT-ONLY","INTEGRATION-ONLY","NONE"})',
      'class CoverageStatusError(ValueError): pass',
      'def classify_coverage(*, has_unit, has_integration, has_e2e) -> str',
      '  (False,False,False)->NONE; (True,False,False)->UNIT-ONLY;',
      '  (False,True,False) or (False,False,True)->INTEGRATION-ONLY;',
      '  (True,True,False) or (True,False,True)->PARTIAL;',
      '  (True,True,True)->FULL',
      'def is_blocking_priority_p0(status) -> bool  # only FULL passes',
      'def is_passing_priority_p1(status) -> bool  # FULL or PARTIAL',
      '',
      'Tests in tests/test_coverage_status.py: ≥10.',
    ].join('\n'),
  },
  {
    id: 'M35', slug: 'test-levels',
    desc: [
      'New core/test_levels.py.',
      '',
      'CANONICAL_LEVELS = ("e2e","api","component","unit")',
      'LEVEL_ALIASES = {"integration":"api", "ui":"component", "unit-test":"unit", "end-to-end":"e2e", "func":"api", "functional":"api"}',
      'class TestLevelError(ValueError): pass',
      'def canonicalize_level(raw) -> str',
      'def is_canonical(level) -> bool',
      'def bucket_levels(levels: list[str]) -> dict[str, list[str]]',
      '',
      'Tests in tests/test_test_levels.py: ≥8.',
    ].join('\n'),
  },
  {
    id: 'M36', slug: 'kernel-schema',
    desc: [
      'New core/kernel_schema.py.',
      '',
      'REQUIRED_H2_SECTIONS = ("Problem","Capabilities","Constraints","Non-goals","Success signal")',
      'class KernelSchemaError(ValueError): pass',
      'def parse_kernel(text) -> dict  # section_name -> body',
      'def validate_kernel(text) -> None  # raises if any section missing or empty',
      'def has_section(text, section_name) -> bool',
      'def kernel_completeness_score(text) -> float  # 0.0-1.0',
      '',
      'Tests in tests/test_kernel_schema.py: ≥8.',
    ].join('\n'),
  },
  {
    id: 'M37', slug: 'risk-action-bands',
    desc: [
      'EXTEND core/risk_profile.py — add TEA action ladder.',
      '',
      'ADD (do NOT modify existing API):',
      '  ACTION_BANDS = ("DOCUMENT","MONITOR","MITIGATE","BLOCK")',
      '  def risk_score_to_action(score: int) -> str',
      '    1-3->DOCUMENT, 4-5->MONITOR, 6-8->MITIGATE, 9->BLOCK',
      '    out-of-range raises RiskProfileError',
      '  def action_blocks_release(action: str) -> bool',
      '    only "BLOCK" returns True',
      '',
      'NEW tests in tests/test_risk_action_bands.py: ≥6. tests/test_risk_profile.py must still pass.',
      'EXISTING file: read first, append cleanly.',
    ].join('\n'),
  },
]

const w1aResults = await parallel(W1A.map(function (m) {
  return function () {
    return agent(milestonePrompt(m), {
      label: 'impl-' + m.id + '-' + m.slug,
      phase: 'Wave1A',
      isolation: 'worktree',
      schema: MILESTONE_SCHEMA,
    })
  }
}))

const w1aOk = w1aResults.filter(function (r) { return r && r.ok })
const w1aFail = w1aResults.filter(function (r) { return r && !r.ok })
log('Wave1A: ' + w1aOk.length + '/' + W1A.length + ' shipped, ' + w1aFail.length + ' failed')

// ============================================================================
phase('Wave1B')

const W1B = [
  {
    id: 'M26', slug: 'gate-rules-priority',
    desc: [
      'EXTEND core/gate_rules.py — add TEA priority-threshold semantics.',
      '',
      'ADD (do NOT modify existing functions):',
      '  PRIORITY_THRESHOLDS = {',
      '    "P0": (100, 100),  # required pct, fail floor',
      '    "P1": (95, 90),',
      '    "P2": (85, 80),',
      '    "P3": (70, 0),',
      '  }',
      '  COLLECTION_STATUSES = frozenset({"COLLECTED","MISSING","ERROR","TIMEOUT"})',
      '  def evaluate_priority_threshold(coverage_pct: float, priority: str) -> str  # PASS/CONCERNS/FAIL',
      '  def gate_eligible(category_collection_status: dict[str, str], required_categories: set[str]) -> tuple[bool, str]',
      '    All required must be COLLECTED.',
      '',
      'NEW tests in tests/test_gate_rules_priority.py: ≥10 covering each priority×coverage band + gate_eligible.',
      'EXISTING file: read first, append cleanly. tests/test_gate_rules.py must still pass.',
    ].join('\n'),
  },
  {
    id: 'M27', slug: 'story-keys-epic-retro',
    desc: [
      'EXTEND core/story_keys.py.',
      '',
      'ADD:',
      '  EPIC_KEY_RE = re.compile(r"^epic-(\\d+)$")',
      '  RETRO_KEY_RE = re.compile(r"^epic-(\\d+)-retrospective$")',
      '  def classify_key(key: str) -> str  # "story" | "epic" | "retrospective" | "unknown"',
      '  def epic_number(key: str) -> int | None',
      '',
      'NEW tests in tests/test_story_keys_epic_retro.py: ≥8. tests/test_story_keys.py must still pass.',
    ].join('\n'),
  },
  {
    id: 'M38', slug: 'sprint-schema',
    desc: [
      'New core/sprint_schema.py — sprint-status.yaml schema validator.',
      '',
      'REQUIRED_TOP_LEVEL = ("epic","sprint_id","started_at","stories")',
      'ALLOWED_TOP_LEVEL = REQUIRED_TOP_LEVEL + ("notes","carry_over")',
      'class SprintSchemaError(ValueError): pass',
      'def validate_sprint_status(data: dict) -> None',
      '  Raises on missing required, unknown extra, invalid status (use core/story_status.canonicalize).',
      '',
      'Tests in tests/test_sprint_schema.py: ≥8.',
    ].join('\n'),
  },
]

const w1bResults = []
for (let i = 0; i < W1B.length; i++) {
  const r = await agent(milestonePrompt(W1B[i]), {
    label: 'impl-' + W1B[i].id + '-' + W1B[i].slug,
    phase: 'Wave1B',
    isolation: 'worktree',
    schema: MILESTONE_SCHEMA,
  })
  w1bResults.push(r)
}

const w1bOk = w1bResults.filter(function (r) { return r && r.ok })
log('Wave1B: ' + w1bOk.length + '/' + W1B.length + ' shipped')

// ============================================================================
phase('Wave1C')

const W1C = [
  {
    id: 'M32', slug: 'cli-profile',
    desc: [
      'New core/cli_profile.py — bmad-auto CLIProfile schema.',
      '',
      'Per external/bmad-auto/src/automator/adapters/profile.py:21.',
      '',
      '@dataclass(frozen=True)',
      'class CLIProfile:',
      '  cli_id: str           # "claude-code" | "codex" | "gemini-cli"',
      '  binary: str',
      '  prompt_template: str',
      '  bypass_flags: tuple[str, ...]',
      '  hook_dialect: str     # "claude" | "codex" | "gemini" | "none"',
      '  canonical_event_map: dict[str, str]',
      '  skill_tree_dir: str   # ".claude/skills" or ".agents/skills" or ".gemini/skills"',
      '  mcp_seed_files: tuple[str, ...]',
      '',
      'KNOWN_CLI_IDS = ("claude-code","codex","gemini-cli")',
      'KNOWN_HOOK_DIALECTS = ("claude","codex","gemini","none")',
      'class CLIProfileError(ValueError): pass',
      'def load_cli_profile(path) -> CLIProfile  # uses stdlib tomllib',
      'def claude_default() -> CLIProfile  # back-compat default for existing tmux runtime',
      '',
      'DO NOT refactor tmux_runtime.py in this milestone — that is M42.',
      'Tests in tests/test_cli_profile.py: ≥10.',
    ].join('\n'),
  },
  {
    id: 'M40', slug: 'result-json-bauto',
    desc: [
      'EXTEND core/result_json.py — bauto-shaped emitter alongside existing v1.',
      '',
      'ADD (DO NOT modify existing functions):',
      '  BAUTO_API_VERSION = 1',
      '  def emit_bauto_result(*, commit_sha, files_changed, summary, spec_file="", escalations=None, task_id="", phase="") -> dict',
      '    Distinct from local v1 because bauto includes task_id + phase fields.',
      '  def write_bauto_result(path, payload) -> Path',
      '  def read_bauto_result(path) -> dict',
      '  def is_bauto_result(payload) -> bool  # detects via task_id+phase presence',
      '',
      'NEW tests in tests/test_result_json_bauto.py: ≥8. tests/test_result_json.py must still pass.',
    ].join('\n'),
  },
  {
    id: 'M41', slug: 'escalation-emit',
    desc: [
      'New core/escalation_emit.py.',
      '',
      'ESCALATION_API_VERSION = 1',
      'VALID_SEVERITIES = frozenset({"CRITICAL","PREFERENCE"})',
      'def emit_escalation(*, story_key, severity, reason, originating_phase, suggested_action="", waiver_ref="") -> dict',
      'def write_escalation(path, payload) -> Path',
      'def read_escalation(path) -> dict',
      'class EscalationError(ValueError): pass',
      '',
      'Tests in tests/test_escalation_emit.py: ≥7.',
    ].join('\n'),
  },
  {
    id: 'M43', slug: 'install-paths-seed',
    desc: [
      'New core/install_paths.py + core/seed_files.py.',
      '',
      'core/install_paths.py:',
      '  SKILL_TREE_DIRS = {"claude-code":".claude/skills", "codex":".agents/skills", "gemini-cli":".gemini/skills"}',
      '  MCP_SEED_DIRS = {"claude-code":".claude/mcp_servers", "codex":".agents/mcp_servers", "gemini-cli":".gemini/mcp_servers"}',
      '  def install_path_for(cli_id) -> Path',
      '  def mcp_seed_path_for(cli_id) -> Path',
      '',
      'core/seed_files.py:',
      '  def seed_worktree(worktree_path, cli_profile) -> None',
      '  class SeedFilesError(IOError): pass',
      '',
      'Tests in tests/test_install_paths.py + tests/test_seed_files.py: ≥6 each.',
    ].join('\n'),
  },
  {
    id: 'M42', slug: 'hook-env-bmad-auto',
    desc: [
      'EXTEND core/tmux_runtime.py — add BMAD_AUTO_* env injection.',
      '',
      'ADD (do NOT break existing build_env):',
      '  BMAD_AUTO_ENV_KEYS = ("BMAD_AUTO_STORY_KEY","BMAD_AUTO_PHASE","BMAD_AUTO_CLI_ID","BMAD_AUTO_COMMIT_SHA","BMAD_AUTO_TASK_ID")',
      '  def inject_bmad_auto_env(env, *, story_key, phase, cli_id="claude-code", commit_sha="", task_id="") -> dict',
      '',
      'tmux_runtime.py is 1706 LOC. Read first 100 lines to understand structure, then append helper at the end.',
      '',
      'NEW tests in tests/test_hook_env_bmad_auto.py: ≥5.',
    ].join('\n'),
  },
  {
    id: 'M39', slug: 'policy-translator',
    desc: [
      'New core/bauto_bridge/policy_translator.py.',
      'Create core/bauto_bridge/__init__.py too.',
      '',
      'def policy_toml_to_runtime(toml_path) -> dict',
      'def runtime_to_policy_toml(runtime, out_path) -> Path',
      'class PolicyTranslationError(ValueError): pass',
      'KNOWN_BAUTO_TABLES = ("scm","review","session","ceilings","drift","policy","trust","calibration","telemetry","plugins","test")',
      '',
      'Use stdlib tomllib (read) + a minimal stdlib TOML writer (no tomlkit).',
      '',
      'Tests in tests/test_policy_translator.py: ≥8.',
    ].join('\n'),
  },
]

const w1cResults = []
for (let i = 0; i < W1C.length; i++) {
  const r = await agent(milestonePrompt(W1C[i]), {
    label: 'impl-' + W1C[i].id + '-' + W1C[i].slug,
    phase: 'Wave1C',
    isolation: 'worktree',
    schema: MILESTONE_SCHEMA,
  })
  w1cResults.push(r)
}

const w1cOk = w1cResults.filter(function (r) { return r && r.ok })
log('Wave1C: ' + w1cOk.length + '/' + W1C.length + ' shipped')

// ============================================================================
phase('Wave1Verify')

const wave1Total = w1aOk.length + w1bOk.length + w1cOk.length
const wave1Planned = W1A.length + W1B.length + W1C.length

const wave1Verify = await agent([
  SHARED_RULES,
  REPO_CONTEXT,
  '',
  'WAVE 1 CLOSE-OUT.',
  '',
  'Reported shipped: ' + wave1Total + ' / ' + wave1Planned,
  '',
  'Do these tasks:',
  '1. cd ' + REPO + ' && git log --oneline -50 | head -50',
  '2. git tag -l "compat-*" | sort',
  '3. Full test suite:',
  '   PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | grep -E "^(OK|FAILED|Ran )" | tail -3',
  '4. Compare against baseline at docs/audit/baseline-tests.txt.',
  '5. Write summary to docs/audit/wave1-status.md.',
  '6. If green: git add docs/audit/wave1-status.md, commit, tag compat-wave1-cliff-fixes.',
  '   If red: do NOT tag, list regressions, commit only the status file.',
  '',
  'Return: {wave1_shipped: N, wave1_failed: M, tests_total: K, regressions: [...], wave1_tag_landed: bool}',
].join('\n'), {
  label: 'verify-wave1',
  phase: 'Wave1Verify',
  schema: {
    type: 'object',
    properties: {
      wave1_shipped: { type: 'number' },
      wave1_failed: { type: 'number' },
      tests_total: { type: 'number' },
      regressions: { type: 'array', items: { type: 'string' } },
      wave1_tag_landed: { type: 'boolean' },
    },
    required: ['wave1_shipped', 'wave1_tag_landed'],
  },
})

log('Wave 1 verify: ' + JSON.stringify(wave1Verify).slice(0, 300))

// ============================================================================
phase('Wave2')

const wave1Ok = wave1Verify && wave1Verify.wave1_tag_landed

let w2Results = []
if (wave1Ok) {
  log('Wave 2: composition + integration bridges (parallel)')
  const W2 = [
    {id: 'M44', slug: 'profile-composer', desc: 'New core/profile_composer.py — merges default + msme-erp + bauto-overlay profiles with per-category precedence. ~400 LOC. Replaces ad-hoc merging in core/product_profile.load_effective_profile. Tests ≥8.'},
    {id: 'M45', slug: 'bmad-review-bridge', desc: 'New core/integration/bmad_review_bridge.py — bridges TEA gate verdicts to BMAD code-review rows using core/review_taxonomy.format_review_row. ~300 LOC. Tests ≥7.'},
    {id: 'M46', slug: 'risk-to-story-dar', desc: 'New core/integration/risk_to_story.py — writes P0..P3 from risk_profile into the Dev Agent Record section of a story file. ~250 LOC. Tests ≥6.'},
    {id: 'M47', slug: 'waiver-to-escalation', desc: 'New core/integration/waiver_to_escalation.py — TEA Waiver ↔ bauto PREFERENCE escalation bidirectional. ~200 LOC. Tests ≥6.'},
    {id: 'M48', slug: 'sprint-phase-map', desc: 'New core/integration/sprint_phase_map.py — dual-store sprint-status + Phase via core/phase_bridge. ~300 LOC. Tests ≥7.'},
    {id: 'M49', slug: 'worktree-baseline', desc: 'New core/integration/worktree_baseline.py — worktree-aware baseline_commit capture for bauto scm.isolation=worktree. ~250 LOC. Tests ≥6.'},
    {id: 'M51', slug: 'adr-29-criterion', desc: 'EXTEND core/checks/adr_check.py — ADR_CRITERIA tuple of 29 strings per TEA ADR rubric. ~300 LOC. NEW tests in tests/test_adr_29_criterion.py: ≥7. Existing tests must still pass.'},
    {id: 'M52', slug: 'scalability-collector', desc: 'New core/collectors/scalability.py — TEA fourth NFR domain. ~250 LOC. Tests ≥6.'},
  ]
  w2Results = await parallel(W2.map(function (m) {
    return function () {
      return agent(milestonePrompt(m), {
        label: 'impl-' + m.id + '-' + m.slug,
        phase: 'Wave2',
        isolation: 'worktree',
        schema: MILESTONE_SCHEMA,
      })
    }
  }))
  log('Wave 2: ' + w2Results.filter(function (r) { return r && r.ok }).length + '/' + W2.length + ' shipped')
} else {
  log('Wave 1 did not close cleanly — skipping Waves 2 + 3')
}

// ============================================================================
phase('Wave3')

let w3Results = []
const w2OkCount = w2Results.filter(function (r) { return r && r.ok }).length
const w2Ok = wave1Ok && w2OkCount >= 5

if (w2Ok) {
  log('Wave 3: innovation moats (parallel)')
  const W3 = [
    {id: 'M53', slug: 'ramr', desc: 'New core/innovation/ramr.py — Risk-Aware Model Routing. Inputs: risk_profile P0..P3, BMAD persona, cli_profile registry. Output: deterministic (cli_id, model, max_tokens, temperature) per (persona, risk, phase) tuple. ~500 LOC. Tests ≥10.'},
    {id: 'M54', slug: 'merkle-nfr-ledger', desc: 'New core/innovation/ledger.py + extend core/evidence_io.py — hash-chains EvidenceRecord rows into a Merkle proof. ~400 LOC. Tests ≥8.'},
    {id: 'M56', slug: 'stack-risk-weights', desc: 'New core/innovation/stack_risk_weights.py — folder taxonomy → per-stack risk multiplier. ~250 LOC. Tests ≥7.'},
    {id: 'M57', slug: 'adversarial-review', desc: 'New core/innovation/adversarial_review.py — P0/P1 review must use a different (cli_id, model) than dev; surface ≥1 substantive finding tied to an evidence record. ~350 LOC. Tests ≥8.'},
    {id: 'M58', slug: 'cross-cli-replay-diff', desc: 'New core/innovation/replay_diff.py — aligns evidence records across 3 CLIProfiles; reports per-collector verdict divergence. ~400 LOC. Tests ≥7.'},
    {id: 'M59', slug: 'phase-shaped-budgets', desc: 'EXTEND core/budget_ceilings.py + new core/innovation/phase_budget.py — dev-running P0 overspend → retry-cheap; review-verify overspend → pause; per-persona ceilings. ~250 LOC. Tests ≥7.'},
    {id: 'M60', slug: 'kernel-violation-classifier', desc: 'New core/innovation/kernel_classifier.py — classifies briefs against 4 violation types (mixed-concerns, non-falsifiable, solution-disguised, vendor-soup) via simple heuristic rules over the kernel_schema sections. ~300 LOC. Tests ≥7.'},
    {id: 'M55', slug: 'anti-bias-phase-roundtrip', desc: 'EXTEND core/phase_bridge.py — enforce RAMR independent-model constraint: dev-verify MUST use different (cli_id, model) than dev-running. Gate auto-FAILs on violation. ~150 LOC. NEW tests in tests/test_anti_bias_phase_roundtrip.py: ≥6.'},
  ]
  w3Results = await parallel(W3.map(function (m) {
    return function () {
      return agent(milestonePrompt(m), {
        label: 'impl-' + m.id + '-' + m.slug,
        phase: 'Wave3',
        isolation: 'worktree',
        schema: MILESTONE_SCHEMA,
      })
    }
  }))
  log('Wave 3: ' + w3Results.filter(function (r) { return r && r.ok }).length + '/8 shipped')
} else {
  log('Wave 2 did not close cleanly enough — skipping Wave 3')
}

// ============================================================================
phase('Final')

const w1aShipped = w1aOk.length
const w1bShipped = w1bOk.length
const w1cShipped = w1cOk.length
const w2Shipped = w2Results.filter(function (r) { return r && r.ok }).length
const w3Shipped = w3Results.filter(function (r) { return r && r.ok }).length
const totalShipped = w1aShipped + w1bShipped + w1cShipped + w2Shipped + w3Shipped
const totalPlanned = 27 + (wave1Ok ? 8 : 0) + (w2Ok ? 8 : 0)

const finalReport = await agent([
  SHARED_RULES,
  REPO_CONTEXT,
  '',
  'FINAL CLOSE-OUT.',
  '',
  'Summary data:',
  '- Wave 0: ' + (wave0 && wave0.commits_landed ? wave0.commits_landed : 0) + ' commits',
  '- Wave 1A: ' + w1aShipped + '/' + W1A.length + ' shipped',
  '- Wave 1B: ' + w1bShipped + '/' + W1B.length + ' shipped',
  '- Wave 1C: ' + w1cShipped + '/' + W1C.length + ' shipped',
  '- Wave 1 verify: ' + (wave1Ok ? 'tag landed' : 'NOT tagged'),
  '- Wave 2: ' + w2Shipped + ' shipped',
  '- Wave 3: ' + w3Shipped + ' shipped',
  '- Total shipped: ' + totalShipped,
  '',
  'Do these tasks:',
  '1. cd ' + REPO + ' && git log --oneline -100',
  '2. git tag -l "compat-*" | sort',
  '3. Full test suite, get final count.',
  '4. Write comprehensive status report at docs/audit/sasa-plus-autonomous-run-report.md with:',
  '   ## Run summary (date, totals, tests baseline → current, tags)',
  '   ## What shipped (per-wave with commit SHAs)',
  '   ## What did not ship + why (per milestone)',
  '   ## Deep gap analysis (for each NOT-shipped milestone: still high-priority? smallest follow-up?)',
  '   ## Enhancement opportunities discovered during the run',
  '   ## Recommended next steps for the operator',
  '   ## Risk register (TODOs introduced, edge cases)',
  '5. Commit and tag:',
  '   git add docs/audit/sasa-plus-autonomous-run-report.md',
  '   git commit -m "docs(audit): SASA+ autonomous run report" with trailer',
  '   git tag sasa-plus-autonomous-run-complete',
  '',
  'Return: {total_shipped, total_failed, tests_baseline, tests_now, loc_added, report_path, final_tag}',
].join('\n'), {
  label: 'final-report',
  phase: 'Final',
})

return {
  wave0: wave0,
  wave1A_shipped: w1aShipped,
  wave1B_shipped: w1bShipped,
  wave1C_shipped: w1cShipped,
  wave1_total_shipped: wave1Total,
  wave1_verify: wave1Verify,
  wave2_shipped: w2Shipped,
  wave3_shipped: w3Shipped,
  total_shipped: totalShipped,
  finalReport: finalReport,
}
