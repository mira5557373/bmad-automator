# Automator Deterministic Smoke Coverage Handoff Log

## Purpose

This file carries implementation context between clean-context agents. Each phase agent must read all earlier entries before starting and append a new entry before ending.

Do not rely on conversation history for phase continuity. Put next-agent continuity facts here.

For user-facing decisions, spec gaps, required changes, tradeoffs, deviations, and notable risks, update [implementation-notes.md](./implementation-notes.md).

## Entry Template

```md
## Phase NN - YYYY-MM-DD - agent/session

### Summary

- What changed or was verified.

### Commands Run

```bash
exact command
```

### Results

- Pass/fail.
- Important SHAs, tags, paths, versions.

### Decisions And Assumptions

- Decision made and why.
- Assumptions the next phase should preserve or re-check.

### Blockers Or Risks

- Blocker, owner, next action.
- Or `None`.

### Next Phase Notes

- Read these files.
- Run this command next.
- Watch for this failure mode.
```

## Phase Entries

## Plan Creation - 2026-06-02 - Codex

### Summary

- Created the phased plan packet for deterministic Story Automator smoke coverage.
- Source inputs were prior deterministic smoke work plus three read-only sub-agent audits: workflow coverage, runtime/helper contracts, and package/prep integration.

### Commands Run

```bash
git status --short --branch
find docs/plans -maxdepth 2 -type f
sed -n '1,220p' skills/bmad-story-automator/workflow.md
sed -n '1,220p' skills/bmad-story-automator/data/orchestration-policy.json
sed -n '1,220p' skills/bmad-story-automator/steps-v/step-v-01-check.md
sed -n '1,220p' skills/bmad-story-automator/steps-v/step-v-02-report.md
sed -n '1,260p' skills/bmad-story-automator/steps-e/step-e-01-load.md
```

### Results

- Plan packet created under `docs/plans/automator-deterministic-smoke-coverage/`.
- No implementation code changed in this plan creation step.

### Decisions And Assumptions

- Plan slug: `automator-deterministic-smoke-coverage`.
- The plan must cover the full policy sequence `create`, `dev`, `auto`, `review`, `retro` plus public modes `create`, `resume`, `validate`, and `edit`.
- Deterministic smokes should avoid live LLM dependence by using fake parser subprocesses, runner mode, seeded state files, and controlled smoke repo commits.

### Blockers Or Risks

- `bmad-method@next` is a moving smoke-prep input until pinned or asserted.
- Workflow version metadata may be stale relative to package version.

### Next Phase Notes

- Start Phase 01 with [01-baseline-and-version-determinism.md](./01-baseline-and-version-determinism.md).
- Update [gate-map.md](./gate-map.md) as soon as concrete commands are added.

## Oracle Review Applied - 2026-06-02 - Codex

### Summary

- Applied Oracle's deterministic smoke architecture review to the plan packet.
- Strengthened release-blocking language for package/prep identity, helper JSON contracts, and finish-loop review/finalize coverage.
- Split intended gates into fast default `verify` targets versus explicit prepared-repo release/nightly smoke targets.

### Commands Run

```bash
sed -n '1,260p' /Users/joon/.codex/attachments/74a1085b-7972-4524-9413-63f6757a1af1/pasted-text.txt
git status --short --branch
find docs/plans/automator-deterministic-smoke-coverage -maxdepth 2 -type f | sort
sed -n '1,260p' docs/plans/automator-deterministic-smoke-coverage/README.md
sed -n '1,260p' docs/plans/automator-deterministic-smoke-coverage/gate-map.md
```

### Results

- Updated `README.md`, `gate-map.md`, phase files 02-06, phase TODO files 02-06, and `implementation-notes.md`.
- No implementation code changed in this application step.

### Decisions And Assumptions

- `npm run verify` should eventually run fast local deterministic gates only.
- Prepared `.smoke/gunz` reset/network gates should remain explicit unless Phase 06 proves CI/runtime stability.
- `smoke:finish-loop` must refuse unsafe host repo commit targets by default.
- `smoke:modes` should use temp BMAD-style fixtures for default verification.

### Blockers Or Risks

- The gates are still planned, not implemented.
- Phase 02, Phase 03, and Phase 05 remain release-blocking before smoke readiness can be claimed.

### Next Phase Notes

- Start implementation with Phase 01, then prioritize Phase 02 and Phase 03 before adding broader lifecycle runners.
- Preserve the Oracle-applied gate split in [gate-map.md](./gate-map.md).

## Oracle Application Review Loop - 2026-06-02 - Codex

### Summary

- Ran `general-subagent-review-loop` against the Oracle-applied plan packet.
- Used three read-only reviewer slices: requirements coverage, gate/command mapping, and phase/TODO consistency.
- Fixed all credible P2 findings, then ran a targeted final Oracle-application review pass.

### Commands Run

```bash
sed -n '1,220p' /Users/joon/.agents/skills/general-subagent-review-loop/steps/01-scope-review-pass.md
sed -n '1,240p' /Users/joon/.agents/skills/general-subagent-review-loop/steps/02-build-review-packets.md
sed -n '1,220p' /Users/joon/.agents/skills/general-subagent-review-loop/steps/03-triage-findings.md
sed -n '1,240p' /Users/joon/.agents/skills/general-subagent-review-loop/steps/04-fix-and-verify.md
sed -n '1,240p' /Users/joon/.agents/skills/general-subagent-review-loop/steps/05-stop-or-loop.md
rg -n '[[:blank:]]$' docs/plans/automator-deterministic-smoke-coverage || true
wc -l docs/plans/automator-deterministic-smoke-coverage/*.md docs/plans/automator-deterministic-smoke-coverage/TODO/*.md
rg -n "pack:identity|pack:assert|pack --json --pack-destination|multi-epic|marker/root|Status/source|Mode state/artifact|Mode source-mismatch|Manual And Live Boundaries|sprint_status_not_updated|frontmatter|commit SHA|smoke:deterministic-full" docs/plans/automator-deterministic-smoke-coverage
git status --short --branch
```

### Results

- Requirements reviewer: no actionable findings.
- Gate/command reviewer: two P2 findings fixed.
- Phase/TODO consistency reviewer: two P2 findings fixed.
- Targeted final Oracle-application auditor: no actionable findings.
- Static verification: no trailing whitespace; all plan files remain under 500 LOC.

### Decisions And Assumptions

- Tarball identity is now bound to `npm run pack:assert` or an explicit `npm run pack:identity`.
- Multi-epic retrospective coverage is now bound to `npm run smoke:finish-loop -- --scenario multi-epic`, or to `npm run smoke:finish-loop` if that command always includes the scenario.
- Phase 03 now has explicit marker/root and status/source-of-truth helper matrix rows and TODOs.
- Phase 04 now has explicit state/artifact and source-mismatch matrix rows and TODOs.

### Blockers Or Risks

- None for Oracle application completeness.
- Implementation gates are still not built; Phase 02, Phase 03, and Phase 05 remain release-blocking before smoke readiness.

### Next Phase Notes

- Start Phase 01 implementation.
- Preserve the P0/P1/P2-clean review baseline when later phases change the gate map.

## Phase 01 - 2026-06-02 - Codex

### Summary

- Added the Phase 01 coverage baseline at `coverage-baseline.md`.
- Added `npm run version:check` for package/plugin/module/Python/runtime/workflow version alignment.
- Fixed stale `skills/bmad-story-automator/workflow.md` frontmatter from `1.12.0` to `1.15.0`.
- Added `npm run smoke:input-check` and `.smoke/SMOKE_INPUTS.json` manifest recording for deterministic smoke inputs.
- Changed `smoke:prepare` to resolve `bmad-method@next` once, record version/integrity, and install the resolved `bmad-method@<version>` package.
- Updated `gate-map.md`, `implementation-notes.md`, `docs/versioning.md`, and Phase 01 TODO status.
- Ran two clean-context review agents; fixed all P2 findings.

### Commands Run

```bash
npm run version:check
npm run smoke:input-check
npm run test:cli
npm run smoke:prepare -- --skip-bmad-install --skip-automator-install
npm run test:python
git diff --check
wc -l scripts/check-version-alignment.py scripts/check-smoke-inputs.py scripts/smoke_prep/*.py docs/plans/automator-deterministic-smoke-coverage/*.md docs/plans/automator-deterministic-smoke-coverage/TODO/*.md docs/versioning.md
```

### Results

- `npm run version:check`: pass; all checked surfaces report `1.15.0`.
- `npm run smoke:input-check`: pass; resolved `bmad-method@next` to `6.8.1-next.0` with integrity `sha512-r8lDToLh57N0BiNsBOcD5wV+JWrR87rvdU2oKm3bhOGykHiCkj3f6BB96ymgftuTDdeK5OMr3AiQNKAsk6/I0A==`.
- `npm run test:cli`: pass.
- `npm run smoke:prepare -- --skip-bmad-install --skip-automator-install`: pass; wrote ignored `.smoke/SMOKE_INPUTS.json`; reused prepared `.smoke/gunz` at commit `fca6470d329668019dace305b5f0f3c9b62cb113`.
- `npm run test:python`: pass, 537 tests.
- `git diff --check`: pass.
- File size check: all touched files remain below 500 LOC.

### Decisions And Assumptions

- `package.json.version` remains the canonical stable release version for metadata alignment.
- Alias names are intentionally different by channel: npm `bmad-story-automator`, plugin `bmad-automator`, BMAD module `automator`, Python/workflow `story-automator`.
- `bmad-method@next` remains the requested installer input for now, but prep installs the resolved version recorded in `SMOKE_INPUTS.json`, avoiding a second dist-tag resolution.
- No Phase 01 deferred-work items remain. Remaining `gap` and `blocked` baseline rows are already owned by Phase 02-06 TODOs.

### Blockers Or Risks

- No Phase 01 blocker.
- Phase 02 still needs package tarball identity and prepared-repo installed manifest assertions.
- The prepared `.smoke/gunz` checkout was already dirty in ignored smoke artifacts during prep; this did not affect host repo status.

### Next Phase Notes

- Start Phase 02 with `02-package-and-prepared-repo-contracts.md` and `TODO/phase-02.md`.
- Preserve the resolved-install behavior when adding package identity checks.
- Recommended next command: `npm pack --dry-run --json` as the first input to `pack:assert`.

## Phase 02 - 2026-06-02 - Codex

### Summary

- Added `pack:assert` with JSON package content, executable mode, forbidden generated-file, tarball identity, SHA256, and selected checksum assertions.
- Added shared package contract helpers in `scripts/smoke_prep/package_contracts.py`.
- Updated `smoke:prepare` to write `.smoke/PACKAGE_IDENTITY.json` and `.smoke/INSTALLED_AUTOMATOR_MANIFEST.json`.
- Installed-file verification now compares selected copied skill files in prepared `.smoke/gunz` against the current packed tarball.
- Classified prepared root support: `.claude/skills` is verified fact; `.agents/skills` and `.codex/skills` are spec-only for the current `--tools claude-code` smoke prep.

### Commands Run

```bash
npm run pack:assert
npm run smoke:prepare -- --reset
npm run smoke:run
npm run smoke:dev-loop
npm run smoke:dev-loop
npm run version:check
npm run smoke:input-check
npm run test:cli
npm run test:python
git diff --check
```

### Results

- `npm run pack:assert`: pass. Tarball `bmad-story-automator-1.15.0.tgz`; integrity `sha512-rlnPSIrZqXA76GLR7GHWKsKKW1bVHfGSVSQhdjBPwbAiufHynFtADAC51p9if6r6JBlA1PmPdZSc7ez1G9RAkw==`; shasum `8883e0199744c914f941de51af26a4b690a1c048`; SHA256 `b4c228d8441cebcea7d041f89bb46d5498953111c6c3a1441ee5c1dbd821b5ae`; entry count `195`; selected checksum count `115`.
- `npm run smoke:prepare -- --reset`: pass. Reinstalled current tarball and wrote package/installed manifests.
- Installed workflow proof: `.smoke/gunz/.claude/skills/bmad-story-automator/workflow.md` reports `1.15.0`.
- `npm run smoke:run`: pass; created story `1.1` smoke state and report.
- `npm run smoke:dev-loop`: ran twice. First run failed on an `agents_file_not_found` state left by the just-created partial dev-loop attempt; second run reset artifacts and passed both stories.
- `npm run version:check`: pass.
- `npm run smoke:input-check`: pass; BMAD Method resolved to `6.8.1-next.0`.
- `npm run test:cli`: pass.
- `npm run test:python`: pass, 537 tests.
- `git diff --check`: pass.

### Decisions And Assumptions

- `pack:assert` is fast and temp-dir only, so it is suitable for future default `verify`.
- Prepared repo install checks remain tied to `smoke:prepare -- --reset` because they require network/cache-heavy BMAD prep.
- The installed manifest reports roots without required dependency skill entrypoints as `unsupported`; the plan taxonomy records these prepared-gunz roots as `spec-only`.

### Blockers Or Risks

- No Phase 02 blocker.
- Phase 03 should reuse `package_contracts.py` style: narrow fixtures, JSON assertions, no terminal-output-only success.

### Next Phase Notes

- Start Phase 03 with `03-runtime-helper-contract-smokes.md` and `TODO/phase-03.md`.
- Recommended first command: inspect existing unit coverage around `parse-output`, `monitor-session`, `tmux-wrapper build-cmd`, and runtime policy helpers before designing `smoke:contracts`.

## Phase 03 - 2026-06-02 - Codex

### Summary

- Added `npm run smoke:contracts` as the Phase 03 fast helper-contract gate, backed by `scripts/run-smoke-contracts.py`.
- Added `tests/test_runtime_helper_contracts.py` for missing parser subprocess, monitor terminal-state, build-cmd, runner edge-state, and `tmux-wrapper spawn` runner-mode assertions.
- Reused existing focused suites for state-update no-mutation, runtime-policy snapshots, state metadata, marker/root resolution, success verifiers, and status/source-of-truth helper behavior.
- Updated `coverage-baseline.md`, `gate-map.md`, `implementation-notes.md`, and Phase 03 TODO status.

### Commands Run

```bash
npm run smoke:contracts
npm run test:python
npm run test:cli
git diff --check
wc -l tests/test_runtime_helper_contracts.py scripts/smoke_prep/package_contracts.py
```

### Results

- `npm run smoke:contracts`: pass, 296 tests.
- `npm run test:python`: pass, 544 tests.
- `npm run test:cli`: pass.
- `git diff --check`: pass.
- File size check: `tests/test_runtime_helper_contracts.py` is 280 LOC; Phase 02 `package_contracts.py` remains 329 LOC.

### Decisions And Assumptions

- `smoke:contracts` intentionally composes focused unittest modules instead of adding a large shell runner, and fails if any selected contract test is skipped.
- `monitor-session` remains a JSON-contract command: crashed, timeout, incomplete, and not_found states can return process exit code `0`.
- `parse-output` JSON-decode handling is defensive because `extract_json_line` returns only JSON-valid candidate lines; no-json and schema-invalid payloads are the deterministic failure cases.
- `tmux-wrapper spawn` success/crash coverage runs in `SA_TMUX_RUNTIME=runner`; tmux must be available because skipped contract tests fail the gate.

### Blockers Or Risks

- No Phase 03 blocker.
- `smoke:contracts` is not wired into `npm run verify` yet; Phase 06 owns verify promotion after Phase 04 creates `smoke:modes`.

### Next Phase Notes

- Start Phase 04 with `04-create-dev-resume-validate-edit-coverage.md` and `TODO/phase-04.md`.
- Preserve the split: Phase 04 should use temp BMAD-style fixtures for resume/validate/edit mode smokes and keep prepared `.smoke/gunz` for realistic external flow only.

## Phase 04 - 2026-06-02 - Codex

### Summary

- Added `npm run smoke:modes` backed by `scripts/run-smoke-modes.py`.
- The new mode smoke uses a temp BMAD-style `.agents` fixture and asserts create startup guards, preflight selection breadth, resume discovery/routes/fallback, marker JSON lifecycle, validation/source mismatch, artifact outputs, and edit helper branch contracts.
- Prepared `.smoke/gunz` create/dev checks remain explicit through `smoke:run` and `smoke:dev-loop`.
- Updated `coverage-baseline.md`, `gate-map.md`, `implementation-notes.md`, and Phase 04 TODO status.

### Commands Run

```bash
npm run smoke:modes
npm run smoke:run
npm run smoke:dev-loop
npm run test:python
git diff --check
wc -l scripts/run-smoke-modes.py
```

### Results

- `npm run smoke:modes`: pass; wrote `.smoke/MODE_SMOKE_REPORT.json`.
- `npm run smoke:run`: pass; created story `1.1` smoke state and report in prepared `.smoke/gunz`.
- `npm run smoke:dev-loop`: pass; simulated dev completion for stories `1.1` and `1.2` in prepared `.smoke/gunz`.
- `npm run test:python`: pass, 544 tests.
- `git diff --check`: pass.
- `scripts/run-smoke-modes.py` is under the 500 LOC repo limit.
- Seeded temp fixture state fields: `storyRange=["1.1","1.2"]`, `status=IN_PROGRESS`, `currentStory=1.1`, `currentStep=step-03-execute`, `complexityFile=_bmad-output/story-automator/complexity-smoke.json`, `agentsFile=_bmad-output/story-automator/agents-smoke.md`, and a policy snapshot path/hash.
- Seeded simulated child outputs: `_bmad-output/implementation-artifacts/sprint-status.yaml`, `_bmad-output/implementation-artifacts/1-1-first.md`, `_bmad-output/story-automator/dev-log-smoke.md`, and `_bmad-output/story-automator/mode-report-smoke.json`.
- Preflight proof: multi-story selection, explicit story IDs, reversed numeric ranges, invalid range empty-selection behavior, and rendered `review=claude` agent config.
- Resume proof: explicit state summary, latest incomplete discovery, no-incomplete fresh-create fallback, workflow-derived menu labels/route hint, view action-log extraction, start-over backup simulation, and abort state update.
- Marker path proof: helper resolved `.agents/.story-automator-active`; `.gitignore` entry was added dynamically from helper output; marker JSON shape and heartbeat mutation were parsed from the marker file.
- Source mismatch proof: shared review verifier returned `note=sprint_status_not_updated` when story-file status was `done` but sprint status remained `ready-for-dev`.
- Startup precondition proof: helper checked sprint-status present and missing states; there is no standalone startup CLI, so abort wording remains a workflow precondition rather than an executed branch.
- Validation/edit boundary: validation helper contracts include happy path, structure issue reporting, progress-row metrics, exact-ID done branch, and compact report output; edit menu prompts remain interactive-only, while workflow-derived menu labels/route hints plus status/range/current-story/AI-command/artifact-path/text save, discard rollback, and edit-more state update are covered through asserted state helper mutations.

### Decisions And Assumptions

- Mode fixtures write story files and `sprint-status.yaml` as simulated child workflow output, not as orchestrator-owned mutation.
- Edit mode remains interactive in the workflow. Phase 04 asserts deterministic helper-backed save/discard/edit-more route contracts and post-edit route hints.
- Marker assertions resolve the active marker path through helper output and verify `.agents/.story-automator-active`; no hard-coded `.claude` path is used.

### Blockers Or Risks

- No Phase 04 blocker.
- Phase 06 should decide whether to promote `smoke:modes` into `npm run verify`; prepared `.smoke/gunz` checks remain explicit.

### Next Phase Notes

- Start Phase 05 with `05-automate-review-finish-retro-coverage.md` and `TODO/phase-05.md`.
- Preserve the host mutation isolation requirement for finish-loop work.
- Recommended next command: inspect commit/finalize helpers and host HEAD/status sentinel surfaces before implementing `smoke:finish-loop`.
