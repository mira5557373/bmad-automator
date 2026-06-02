# Automator Coverage Baseline

## Scope

Phase 01 source-of-truth baseline for deterministic smoke coverage. Status values:
`fact`, `gap`, `blocked`, `stale`, and `spec-only`.

## Baseline

| Surface | Source | Current deterministic gate | Status | Notes |
| --- | --- | --- | --- | --- |
| create mode route | `workflow.md`, `steps-c/` | `npm run smoke:run`; `npm run smoke:modes` | fact | Prepared `.smoke/gunz` create smoke verifies story `1.1`; Phase 04 mode smoke adds multi-story temp state setup, sprint-status present/missing checks, stop-hook guard states, and init-log proof. |
| resume mode route | `workflow.md`, `steps-c/step-01b-continue.md` | `npm run smoke:modes` | fact | Phase 04 temp fixture covers explicit path summary, latest incomplete discovery, no-incomplete fresh-create fallback, sprint compare, workflow-derived menu branch names/route hints, view action-log summary, start-over backup simulation, abort state update, and marker creation timing. |
| validate mode route | `workflow.md`, `steps-v/` | `npm run smoke:modes` | fact | Phase 04 covers helper help contracts, happy-path state validation, structure issue reporting, session inventory, sprint compare, progress-row metrics, and compact mode report output. |
| edit mode route | `workflow.md`, `steps-e/` | `npm run smoke:modes` | fact | Phase 04 covers workflow-derived menu names/post-edit route hints plus helper-backed status/range/current-story/AI-command/artifact-path/text saves, discard rollback, and edit-more state update. Interactive prompts remain workflow-only. |
| create-story policy step | `orchestration-policy.json` step `create` | `npm run smoke:run` | fact | Existing smoke asserts generated story artifact for one story. |
| dev-story policy step | `orchestration-policy.json` step `dev` | `npm run smoke:dev-loop`; `npm run smoke:modes` | fact | Dev-loop smoke covers two-story transition with parsed fixture output; Phase 04 mode smoke adds complexity-file persistence and richer per-task agent-config state coverage. |
| automate policy step | `orchestration-policy.json` step `auto` | `npm run smoke:finish-loop` | fact | Phase 05 temp git-backed finish-loop smoke covers automate `done` and non-blocking `skip` progress rows. |
| review policy step | `orchestration-policy.json` step `review` | `npm run smoke:contracts`; `npm run smoke:finish-loop` | fact | Unit tests cover verifier pieces; Phase 05 smoke covers incomplete review diagnostics and verified review completion from story/sprint source truth. |
| commit/finalize | `steps-c/step-03b-finalize.md` | `npm run smoke:finish-loop` | fact | Phase 05 smoke commits controlled story changes inside a temp smoke repo, records commit SHAs, and proves host HEAD/status isolation plus unsafe-host target rejection. |
| retrospective policy step | `orchestration-policy.json` step `retro` | `npm run smoke:finish-loop` | fact | Phase 05 multi-epic fixture resolves retro agent/build command and records per-epic skipped retrospectives as non-blocking before later epic continuation. |
| wrapup | `steps-c/step-04-wrapup.md`, `data/wrapup-templates.md` | `npm run smoke:finish-loop` | fact | Phase 05 smoke covers `EXECUTION_COMPLETE`, `COMPLETE`, summary metrics, learnings file creation, final state validation, and marker removal. |
| parser subprocess contracts | `data/parse/*.json`, helper CLI | `npm run smoke:contracts` | fact | Phase 03 covers success, missing/empty output, state flag/policy/contract failures, subprocess timeout/nonzero/no-json, and schema-invalid JSON. |
| monitor terminal states | helper CLI, tmux runtime | `npm run smoke:contracts` | fact | Phase 03 covers completed, incomplete, crashed, stuck, timeout, invalid persisted session-state diagnostics on not_found, invalid options, and runner success/crash/edge mapping. |
| build-cmd helper branches | `tmux-wrapper build-cmd` | `npm run smoke:contracts` | fact | Phase 03 covers Codex safety flags, `AI_COMMAND`, Claude/model quoting, unknown step, state-file, and invalid policy branches. |
| marker/root resolution | runtime layout helper | `npm run test:python` | fact | Existing unit tests cover runtime-layout helper behavior. |
| package version surfaces | package/plugin/module/Python/workflow metadata | `npm run version:check` | fact | Workflow frontmatter was stale at `1.12.0`; Phase 01 aligned it to `1.15.0`. |
| smoke repo input | `scripts/smoke_prep/config.py`, `gunz.py` | `npm run smoke:input-check` | fact | `gunz` repo is pinned by full SHA; command resolves `bmad-method@next` version/integrity. |
| package/install identity | package tarball and prepared repo install | `npm run pack:assert`; `.smoke/PACKAGE_IDENTITY.json`; `.smoke/INSTALLED_AUTOMATOR_MANIFEST.json` | fact | Phase 02 replaced terminal-output-only dry run with JSON identity, tarball SHA256, and installed-file checksum assertions. |
| installed BMAD Method input | `scripts/smoke_prep/inputs.py` | `.smoke/SMOKE_INPUTS.json` from `smoke:prepare` | fact | Moving npm dist-tag remains explicit and recorded with resolved version/integrity per prep run. |
| prepared `.claude/skills` install root | `install.sh`, `.smoke/gunz/.claude/skills` | `npm run smoke:prepare -- --reset` | fact | Phase 02 installed manifest verifies dependency entrypoints, package identity, and selected copied-file checksums. |
| prepared `.agents/skills` install root | `install.sh`, `.smoke/gunz/.agents/skills` | `npm run smoke:prepare -- --reset` | spec-only | Installer supports the root, but BMAD prep with `--tools claude-code` does not create `.agents/skills` dependency entrypoints; installed manifest reports this as `unsupported`. |
| prepared `.codex/skills` install root | `install.sh`, `.smoke/gunz/.codex/skills` | `npm run smoke:prepare -- --reset` | spec-only | Installer supports the root, but BMAD prep with `--tools claude-code` does not create `.codex/skills` dependency entrypoints; installed manifest reports this as `unsupported`. |
| live LLM quality | provider/auth/runtime behavior | none | blocked | Explicitly outside deterministic smoke gates. |

## Deferred Work

No Phase 01 deferred-work items. Remaining `gap` and `blocked` rows are already
owned by Phase 02-06 TODOs and will be validated or implemented in those phases.
