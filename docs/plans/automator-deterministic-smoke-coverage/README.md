# Automator Deterministic Smoke Coverage Plan

## Purpose

Build a deterministic smoke coverage suite that verifies the Story Automator control plane before any live LLM smoke run. The suite should prove package/install determinism, helper contracts, create/dev/review/finalize lifecycle behavior, resume/validate/edit modes, marker safety, and gate wiring.

## Critical Findings

- Current deterministic smokes cover prepared `gunz`, epic/story parsing, state creation, story artifact creation, and a two-story dev status transition.
- Current smokes do not yet cover automate, review, commit/finalize, single-epic or multi-epic retrospective behavior, wrapup, validate mode, edit mode, resume routing, monitor terminal states, parser subprocess contracts, or package version alignment.
- `smoke:prepare` pins the `gunz` repo commit but installs `bmad-method@next`; that is a moving input unless pinned or recorded and asserted.
- Workflow metadata already has a likely stale version surface: package/runtime surfaces report `1.15.0`, while `skills/bmad-story-automator/workflow.md` reports `1.12.0`.
- `npm run verify` does not currently include the new deterministic external smokes.
- Oracle review on 2026-06-02 confirmed the plan shape is sound but release readiness must block on Phase 02 package/prep identity, Phase 03 helper JSON contracts, and Phase 05 review/finish-loop coverage. Existing smoke runners alone are not enough to call the repo smoke-ready.

## Oracle-Applied Architecture

Use a layered deterministic control-plane suite instead of one giant automator smoke:

1. Fast in-repo contract gates: fake subprocesses, runner mode, temp fixtures, helper JSON assertions, state/policy/success-verifier matrices.
2. Package/install identity gates: `npm pack --dry-run --json`, tarball identity, selected installed-file checksums, version surface alignment, and forbidden generated files.
3. Local no-network mode fixtures: resume, validate, edit, create startup, marker lifecycle, and source-of-truth mismatch checks using temp BMAD-style projects.
4. Explicit prepared-repo smokes: `smoke:prepare`, `smoke:run`, `smoke:dev-loop`, `smoke:finish-loop`, and `smoke:deterministic-full` against `.smoke/gunz`.

Default `npm run verify` should eventually run only fast deterministic gates. Prepared-repo reset/network gates remain explicit unless CI provides stable cache and time budget.

## Release-Blocking Priorities

- Phase 02 is release-blocking because a prepared repo can pass with a stale same-shape install unless tarball identity and installed checksums are asserted.
- Phase 03 is release-blocking because higher-level runners rely on helper contracts that can exit with structured failure payloads rather than simple process failure.
- Phase 05 is release-blocking because review completion cannot be inferred from a child process exiting; it must be verified through sprint status or story-file fallback, then finalize/retro/wrapup must be proven.
- Host mutation isolation is release-blocking. Any finish-loop runner must prove host HEAD/status are unchanged and should refuse commit/finalize operations unless the target repo is under the smoke workspace, except behind an explicit unsafe override.

## Assertion Contract

Every deterministic smoke should assert structured outputs and selected file contents, not only command exit status.

- State assertions: frontmatter fields, `status`, `currentStory`, `currentStep`, `agentsFile`, `complexityFile`, policy snapshot path/hash, progress rows, and action log deltas.
- Source-of-truth assertions: story-file status, sprint-status status, source mismatch diagnostics, review fallback behavior, incomplete review payloads, and `sprint_status_not_updated` notes where applicable.
- Artifact assertions: reports, state docs, complexity JSON, agents file, dev logs, commit SHA, marker JSON, `.gitignore` entries, and selected checksums. Keep these narrow; do not introduce broad whole-repo snapshots.

## Manual And Live Boundaries

Keep these out of deterministic `verify`:

- Live provider/auth behavior: Claude/Codex auth, rate limits, trust prompts, outages, provider-specific reasoning, and whether a real LLM follows every BMAD step.
- Live implementation quality: whether generated stories, implementation patches, reviews, and retrospectives are semantically good.
- Moving network surfaces unless pinned or recorded/asserted: `bmad-method@next`, registry `next`, external git refs, npm registry state.
- Interactive conversational UX beyond helper-backed branch effects, state mutations, route hints, and file outputs.

## Recommended Implementation Order

1. Version/input determinism.
2. Package identity and installed manifest checks.
3. Helper contracts.
4. Existing smoke marker path fixes.
5. Resume/validate/edit temp-fixture smokes.
6. Create/dev breadth.
7. Finish-loop smoke.
8. Multi-epic fixture.
9. Gate integration and clean-context review.

## Assumptions

- Target repo: `/Users/joon/.codex/worktrees/9b27/bmad-story-automator`.
- Plan root: `docs/plans/automator-deterministic-smoke-coverage/`.
- External target remains the prepared `.smoke/gunz` workspace unless a later phase intentionally broadens it.
- Live LLM implementation quality is out of scope for deterministic smoke; deterministic gates verify the automator control plane and source-of-truth transitions.
- Use this fact status taxonomy when classifying coverage: `fact`, `gap`, `blocked`, `stale`, `spec-only`.

## Phase Files

- [Phase 01 - Baseline And Version Determinism](./01-baseline-and-version-determinism.md)
- [Phase 02 - Package And Prepared Repo Contracts](./02-package-and-prepared-repo-contracts.md)
- [Phase 03 - Runtime Helper Contract Smokes](./03-runtime-helper-contract-smokes.md)
- [Phase 04 - Create Dev Resume Validate Edit Coverage](./04-create-dev-resume-validate-edit-coverage.md)
- [Phase 05 - Automate Review Finish Retro Coverage](./05-automate-review-finish-retro-coverage.md)
- [Phase 06 - Gate Integration And Readiness Review](./06-gate-integration-and-readiness-review.md)

## Supporting Files

- [Coverage baseline](./coverage-baseline.md)
- [TODO index](./TODO.md)
- [Gate map](./gate-map.md)
- [Implementation notes](./implementation-notes.md)
- [Handoff log](./handoff-log.md)

## Clean Context Agent Protocol

Every phase agent must read this `README.md`, its assigned phase file, only its assigned phase TODO file, [implementation-notes.md](./implementation-notes.md), and relevant earlier entries in [handoff-log.md](./handoff-log.md) before starting. Append a new handoff entry before ending.

Do not read later phase files or later TODO files as acceptance criteria for the current phase.

## Implementation Notes Protocol

Every phase agent must keep [implementation-notes.md](./implementation-notes.md) current with user-facing decisions, spec gaps, required changes, tradeoffs, deviations, and notable risks. Use [handoff-log.md](./handoff-log.md) only for next-agent continuity.

## Gate Map Protocol

Every phase that creates, changes, or promotes deterministic gates must update [gate-map.md](./gate-map.md). Final review and smoke readiness must consume the gate map instead of rediscovering commands from scattered notes.

## Smoke Implementation Discipline

Keep new smoke runners small. Extract shared fixture creation, helper invocation, JSON assertions, package identity checks, fake subprocesses, state seeding, marker resolution, and git sentinels into focused modules under `scripts/smoke_prep/` or a new `scripts/smoke_lib/` package instead of duplicating that logic across runners.

When deterministic fixtures write story files or `sprint-status.yaml`, label that as fixture setup that simulates child workflow output. The automator control plane must not claim ownership of sprint-status writes.
