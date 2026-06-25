## 260625 - [FULL] Consolidate origin/main into integration-all

### Summary
Cherry-picks 4 origin/main production-readiness commits onto
`bma-d/integration-all` to produce `bma-d/consolidated-main`. No
capability loss from either side: integration-all's full gate
subsystem (C5 self-improving thresholds, G2 worktree-per-unit
isolation, C1/C2/C3 cross-genre observability, K-2/K-5, L1/L2/B
lock observability, G7 sprint-phase unification, N4..N6.7 Path B
compat) lands alongside main's bug fixes for R09 (`epic_complete`
per-epic scoping), R05 (`_spawn_runner` collision refusal),
frontmatter line-anchored `---` split, and the 28-bug deep audit.

Method: cherry-pick (not merge). Linear history of 6 commits on
top of integration-all; per-commit attribution preserved.

### Added
- `docs/environment-variables.md` (from main `fb6c834`) —
  documents the ~11 env vars the shipped runtime reads.
- `tests/test_audit_fixes.py` (from main `eb0b964`) — 29
  deep-audit regression tests; 2 assertions adjusted to align
  with integration-all's pre-existing `test_error_contract`
  contracts (lenient marker-create defaulting, descriptive
  `marker_corrupt`/`invalid_set_operand` error names).
- `tests/test_version_sync.py` (from main `eb0b964`) — guards
  the six hand-synced version surfaces.
- `tests/test_no_unauthorized_imports.py` (from main `fb6c834`)
  — guards against silent third-party-dep additions. Allow-list
  extended with `filelock` + `psutil` (declared deps per
  CLAUDE.md hard guardrail).
- `docs/audit/2026-06-19/**` (from main `3e63d4e`) — 71-finding
  production-readiness audit reference.
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator_parse.py`
  (from main `eb0b964`) — extracted `parse_output_action`.

### Changed
- `core/epic_parser.py` — R09: `epic_complete` scopes max-story
  comparison to `target_epics` (was: global max across all epics).
  Multi-epic file range `"1.1,1.2"` now correctly reports complete
  even when `"2.1"` exists.
- `core/tmux_runtime.py` — R05: `_spawn_runner` refuses to spawn
  when a tmux session of that name is already live, instead of
  running unconditional cleanup that orphans the live session's
  state/command/runner/output files.
- `core/frontmatter.py` — line-anchored `_FENCE_LINE` regex
  `(?m)^---[ \t]*$` replaces bare `text.split("---", 2)`.
  Frontmatter with `---` inside a quoted value (e.g.
  `customInstructions`) no longer truncates at the embedded `---`.
- `core/sprint.py` — `sprint_status_in_text` becomes the public
  API; `sprint_status_get` + `sprint_status_done_in_text` are
  one-line wrappers. Matches main's contract; preserves
  integration-all's normalization machinery.
- `core/utils.py` — `get_project_root` uses `or` fallback so an
  explicitly-empty `PROJECT_ROOT` env var falls back to cwd
  (matches `common.project_root`).
- `core/runtime_policy.py` — `_max_parallel` coercion clamp `>= 1`
  (from main) on top of integration-all's `VALID_VERIFIERS`
  superset.
- `core/success_verifiers.py` — union of main's bug fixes
  (active_task CSV strip, legacy Claude tense-aware marker,
  story-file path-traversal guard, escalate / parse-output
  `resolve_assets=False`) AND integration-all's `VERIFIERS` dict
  additions (`production_ready_gate`, `readiness_gate`).
- `commands/orchestrator.py` — `_state_update` uses atomic_write
  (integration-all's M05) + `audit_state_change` (M04 audit
  trail). Marker corruption path keeps `marker_corrupt` (more
  descriptive than main's `marker_invalid`). `safe_int(_, 0)` for
  non-numeric `--remaining` / `--pid` (lenient contract pinned by
  `test_error_contract.MarkerCreateNumericContractTests`).
  HookBus `pre_commit` emit + git exit-code propagation BOTH land
  in `_commit_ready`. `story-file-status` falls back to
  `extract_title(read_text(...))` when frontmatter `Title:` is
  absent (BMAD's fenceless H1 case).
- `commands/state.py` — atomic state-doc write with utf-8 pin;
  `_max_parallel` validation early-return; `metrics_text` (HTML
  comment stripped) used for review-cycle/escalation counting
  (main's production-readiness fix #03).
- `commands/basic.py` — `read_text(encoding="utf-8")` on marker
  reads; broader `(OSError, ValueError)` exception handling kept
  from integration-all.
- `commands/tmux.py` — added `safe_int` import alongside
  integration-all's `cli_dispatcher` / `audit` / `cli_profile`
  imports (N6.5 surface).
- `commands/orchestrator_epic_agents.py` — main's defensive
  `storyId` skip-and-count for missing-id complexity entries;
  non-dict `complexity` graceful handling.
- `pyproject.toml` — drops `../bmad-story-automator-review`
  force-include (main's `fb6c834` sdist→wheel build regression
  fix).
- `install.sh` — host-tool preflight (`bash`/`python3`/`jq`
  hard-fail with install hints, `tmux` warn), `__pycache__` strip;
  backups now stored OUTSIDE skills root at
  `$TARGET_ROOT/.bmad-story-automator-backups/` (rejects skill
  discovery on backup trees) with diff-skip idempotency.
  integration-all's `skill_root_has_required_skill_files` +
  `cleanup_obsolete_command_shims` machinery preserved.
- `scripts/smoke-test.sh` — `verify_legacy_backups` updated to
  match new backup location.
- `.github/workflows/ci.yml` — main's "real command from clean
  dir" wheel guard unioned with integration-all's gate-related
  jobs.
- `README.md` — main's user-onboarding sections (Install Into A
  BMAD Project, Use From A Local Clone, Starting The Orchestrator,
  BMAD Method Install Channels, Expectations, Requirements,
  Install Verification, Docs Map) inserted before the License
  footer.
- `docs/cli-reference.md` — main's per-command parameter
  signatures (parse-output, marker, escalate, commit-ready,
  normalize-key, story-file-status, agent-config).
- `docs/troubleshooting.md` — main's first-run failure modes
  (missing jq/tmux, story/sprint-status not found, wrong
  story_location, missing dependency skills).
- `skills/bmad-story-automator/workflow.md` — version stamp
  synced 1.12.0 → 1.15.0 (was a stale surface flagged by
  bma-d/smoke-suite's Oracle review; the rest of the version
  family had already converged).
- `skills/bmad-story-automator/steps-c/step-02-preflight.md` —
  matched to main's `{"exists": bool}` sprint-status JSON shape.
- `skills/bmad-story-automator/src/story_automator/cli.py` —
  dropped dead `safe_int` import surfaced by ruff.

### Removed
- `bma-d/e2e-tests` sibling branch — DROPPED. Rationale:
  54-commit doc-plan series for GitHub issue #5 ("Increase
  automator observability and validation clarity") superseded by
  integration-all's `docs/superpowers/specs/2026-06-22-e2e-factory-harness-design.md`
  and the associated implementation work.
- `bma-d/smoke-suite` sibling branch — DROPPED. Rationale:
  67-commit doc-plan series ("Automator Deterministic Smoke
  Coverage Plan") superseded by integration-all's actual smoke
  profile at `tests/integration/data/profiles/smoke.json` and
  `scripts/smoke-test.sh`. One actionable finding from that plan
  — `workflow.md` version stamp drift — is fixed by this
  consolidation as a one-line change.
- `fix/bmad-artifacts-config-path` sibling branch — DROPPED.
  Rationale: 14-commit artifact-path normalization series
  superseded by main's `fb6c834` `PROJECT_ROOT` fallback +
  integration-all's `core/artifact_paths.py`.
- `bma-d/baut-compat` sibling branch — DROPPED. Rationale:
  `scripts/compat-test.sh` is a CI test script for legacy
  `baut` → `automator` rename compat, not a runtime feature.
  Adopt only when migrating from a `baut`-named install (no
  consolidation consumer does).
- `bma-d/versioning`, `fix/project-slug-relative-root`,
  `bma-d/pr-8-review-fixes`, `fix/sprint-compare-key-format`,
  `fix/state-frontmatter-unicode-roundtrip`,
  `fix/dev-step-test-counts`, `fix/dev-step-filelist-reconcile` —
  ALREADY REPLAYED on integration-all under different SHAs.
  No action required.

### Files
- `0dc74dd` (eb0b964): 21 files (+685, −80) — deep-audit batch.
- `8b659dd` (98a6069): 4 files (+73, −6) — R09 + R05.
- `054c707` (fb6c834): 14 files (+137, −15) — build regression
  + ecosystem subset; adds 2 new test files.
- `8135dae` (3e63d4e): 10 files (+450, −22) — production-readiness
  audit (15 confirmed findings).
- `fd69a42`: 1 file (+1, −1) — workflow.md version sync.
- `b550cef`: 6 files (+45, −22) — validation-gate reconciliation
  (test contracts + smoke backup location + unused-import cleanup).

`9db75a7` (`.gitignore` for `.claude/settings.local.json`) is a
no-op on integration-all — the file is already gitignored at line
14 / 48 of integration-all's `.gitignore`.

### QA Notes
- `npm run lint:python` (ruff): PASS (all checks).
- `npm run test:python` (`unittest discover -s tests`):
  PASS — 4873 tests, 2 skipped, 0 failed.
- `tests/test_audit_fixes`: PASS — 39 tests (29 deep-audit
  regressions from main + integration-all's pre-existing).
- `tests/test_audit_regression`: PASS — 50 tests (audit-floor
  invariants for G2 / D-04 / C5 / K-5 /
  WorktreePerUnitIsolationInvariant intact).
- `tests/test_error_contract.MarkerCreateNumericContractTests`:
  PASS — lenient default-to-zero contract preserved.
- `tests/test_epic_parser.test_epic_complete_scopes_to_requested_epic`:
  PASS — R09 fix verified.
- `tests/test_tmux_runtime.SpawnCollisionTests`: PASS — R05 fix
  verified.
- Frontmatter line-anchored sanity: `extract_frontmatter` over
  `'---\nkey: "value-with---inside"\nother: 1\n---\nbody'`
  correctly retains the `other: 1` key after the embedded `---`.
- `npm run pack:dry-run`: PASS — wheel/sdist produces
  `bmad-story-automator-1.15.0.tgz`, 392 files, 976.8 kB.
- `npm run test:cli`: PASS — `--help` exits 0 on both
  `python -m story_automator` and the helper CLI wrapper.
- `npm run test:smoke`: PASS — `smoke ok`.
- `npm run verify`: PASS end-to-end.

### Hard guardrails verified
- No edits to `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
  (M01-owned).
- No new Python deps beyond stdlib + `filelock` + `psutil`.
- All four version surfaces still synced at `1.15.0`
  (package.json, pyproject.toml, plugin.json, marketplace.json,
  workflow.md).
- `core/telemetry_events.py` untouched (verified by
  `git show 0dc74dd..b550cef --name-only`).
