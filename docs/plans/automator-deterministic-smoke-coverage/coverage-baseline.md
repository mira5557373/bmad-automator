# Automator Coverage Baseline

## Scope

Phase 01 source-of-truth baseline for deterministic smoke coverage. Status values:
`fact`, `gap`, `blocked`, `stale`, and `spec-only`.

## Baseline

| Surface | Source | Current deterministic gate | Status | Notes |
| --- | --- | --- | --- | --- |
| create mode route | `workflow.md`, `steps-c/` | `npm run smoke:run` | fact | Prepared `.smoke/gunz` create smoke verifies state creation and story `1.1` creation. |
| resume mode route | `workflow.md`, `steps-c/step-01b-continue.md` | none | gap | Planned for `smoke:modes`; no deterministic route fixture yet. |
| validate mode route | `workflow.md`, `steps-v/` | none | gap | Public mode exists but has no deterministic report/helper smoke. |
| edit mode route | `workflow.md`, `steps-e/` | none | gap | Public mode exists but has no deterministic save/discard/edit-more smoke. |
| create-story policy step | `orchestration-policy.json` step `create` | `npm run smoke:run` | fact | Existing smoke asserts generated story artifact for one story. |
| dev-story policy step | `orchestration-policy.json` step `dev` | `npm run smoke:dev-loop` | fact | Existing dev-loop smoke covers two-story transition with parsed fixture output. |
| automate policy step | `orchestration-policy.json` step `auto` | none | gap | No deterministic automate success/skip coverage yet. |
| review policy step | `orchestration-policy.json` step `review` | partial helper tests | gap | Unit tests cover verifier pieces; no full review completion/incomplete smoke yet. |
| commit/finalize | `steps-c/step-03b-finalize.md` | none | gap | No smoke-repo-only commit/finalize sentinel yet. |
| retrospective policy step | `orchestration-policy.json` step `retro` | partial unit tests | gap | Unit tests cover retro agent logic; no single/multi-epic route smoke yet. |
| wrapup | `steps-c/step-04-wrapup.md`, `data/wrapup-templates.md` | none | gap | No execution-complete or wrapup smoke yet. |
| parser subprocess contracts | `data/parse/*.json`, helper CLI | unit tests only | gap | Needs fake-subprocess fail-closed matrix under `smoke:contracts`. |
| monitor terminal states | helper CLI, tmux runtime | unit tests only | gap | Needs terminal-state JSON matrix under `smoke:contracts`. |
| marker/root resolution | runtime layout helper | `npm run test:python` | fact | Existing unit tests cover runtime-layout helper behavior. |
| package version surfaces | package/plugin/module/Python/workflow metadata | `npm run version:check` | fact | Workflow frontmatter was stale at `1.12.0`; Phase 01 aligned it to `1.15.0`. |
| smoke repo input | `scripts/smoke_prep/config.py`, `gunz.py` | `npm run smoke:input-check` | fact | `gunz` repo is pinned by full SHA; command resolves `bmad-method@next` version/integrity. |
| package/install identity | package tarball and prepared repo install | `npm run pack:dry-run` | gap | Phase 02 must replace terminal-output-only dry run with JSON assertions/checksums. |
| installed BMAD Method input | `scripts/smoke_prep/inputs.py` | `.smoke/SMOKE_INPUTS.json` from `smoke:prepare` | fact | Moving npm dist-tag remains explicit and recorded with resolved version/integrity per prep run. |
| live LLM quality | provider/auth/runtime behavior | none | blocked | Explicitly outside deterministic smoke gates. |

## Deferred Work

No Phase 01 deferred-work items. Remaining `gap` and `blocked` rows are already
owned by Phase 02-06 TODOs and will be validated or implemented in those phases.
