# Phase 04 - Create Dev Resume Validate Edit Coverage

## Clean Context Start

Before doing this phase, read [README.md](./README.md), this phase file, [TODO/phase-04.md](./TODO/phase-04.md), [gate-map.md](./gate-map.md), [implementation-notes.md](./implementation-notes.md), and relevant earlier entries in [handoff-log.md](./handoff-log.md).

Do not read later phase files or later TODO files as acceptance criteria for this phase.

## Goal

Expand deterministic smoke coverage across create/dev plus the non-create automator modes: resume, validate, and edit. This phase should prove state discovery, sprint comparison, marker lifecycle, validation reports, edit summaries, and mode routing contracts.

Most mode coverage should run against narrow temp BMAD-style fixtures, not the prepared `.smoke/gunz` repo. Prepared-repo coverage remains useful for realistic flow checks, but default verification should not depend on external reset/network surfaces.

## Inputs

- [scripts/run-smoke-automator.py](../../../scripts/run-smoke-automator.py)
- [scripts/run-smoke-dev-loop.py](../../../scripts/run-smoke-dev-loop.py)
- [skills/bmad-story-automator/steps-c/step-01-init.md](../../../skills/bmad-story-automator/steps-c/step-01-init.md)
- [skills/bmad-story-automator/steps-c/step-01b-continue.md](../../../skills/bmad-story-automator/steps-c/step-01b-continue.md)
- [skills/bmad-story-automator/steps-c/step-02-preflight.md](../../../skills/bmad-story-automator/steps-c/step-02-preflight.md)
- [skills/bmad-story-automator/steps-c/step-02a-preflight-config.md](../../../skills/bmad-story-automator/steps-c/step-02a-preflight-config.md)
- [skills/bmad-story-automator/steps-c/step-02b-preflight-finalize.md](../../../skills/bmad-story-automator/steps-c/step-02b-preflight-finalize.md)
- [skills/bmad-story-automator/steps-v/](../../../skills/bmad-story-automator/steps-v)
- [skills/bmad-story-automator/steps-e/](../../../skills/bmad-story-automator/steps-e)

## Implementation Steps

1. Extend current create/dev deterministic smokes or add a new runner for create startup, resume, validate, and edit mode contracts. Prefer a fast `smoke:modes` temp-fixture runner for default verify, with prepared-repo checks kept explicit.
2. Cover preflight breadth: multi-story selection, explicit IDs, invalid ranges, complexity matrix persistence, and at least one richer agent-config variant.
3. Cover create startup guard cases from `step-01-init`: stop-hook ok, changed, pending-trust, and failure payloads; existing-state detection; sprint-status present; sprint-status missing abort; and init log creation.
4. Cover resume by seeding incomplete state files and asserting explicit path handling, no-path latest incomplete discovery, no-incomplete fallback to fresh create, `state-summary`, `sprint-compare`, route selection by `currentStep`, and marker creation only after resume.
5. Cover resume menu branches deterministically where helper-backed: View/inspect, Modify/edit route, Start Over/fresh route, Abort/no mutation, and Resume/continue route.
6. Cover marker lifecycle using dynamic marker path from `orchestrator-helper marker path`: gitignore entry, marker JSON shape, heartbeat update, stop-hook block/allow cases, and marker removal. Do not hard-code `.claude`.
7. Assert state file fields and artifact outputs directly: frontmatter, `status`, `currentStory`, `currentStep`, `agentsFile`, `complexityFile`, policy snapshot path/hash, progress rows, action log deltas, reports, state docs, complexity JSON, agents file, dev logs, marker JSON, and `.gitignore` entries.
8. Cover source-of-truth mismatch cases for story-file status versus `sprint-status.yaml`; surface mismatches rather than treating marker absence or command exit status as completion proof.
9. Cover validate mode helpers: `validate-state --help`, `list-sessions --help`, `derive-project-slug --help`, structure issue reporting, progress-row consistency, and compact report output.
10. Cover edit mode helpers and branches: status, range, overrides, text context, AI command, docs path updates, save, discard, edit-more, post-edit resume, post-edit validate, and exit route hints without requiring interactive input.
11. Update [gate-map.md](./gate-map.md) with create-startup/create/dev/resume/validate/edit gates.
12. When fixture setup writes story files or `sprint-status.yaml`, label it as simulated child workflow output. Do not make tests imply the orchestrator owns sprint-status mutation.

## Verification

- Run `npm run smoke:run`.
- Run `npm run smoke:dev-loop`.
- Run the new resume/validate/edit smoke command.
- Run `npm run test:python`.
- Run `git diff --check`.

## Exit Criteria

- Deterministic smokes cover all public automator modes: create startup, create/preflight/dev, resume, validate, and edit.
- Create startup guard cannot pass if stop-hook setup, existing-state handling, or required sprint-status detection regresses.
- Marker lifecycle uses the helper-resolved path and does not hard-code `.claude`.
- Validate/edit coverage exercises helper contracts without interactive prompts.
- Fast mode coverage is suitable for `npm run verify`; heavier prepared-repo checks remain explicit unless Phase 06 promotes them.
- Phase 04 handoff entry appended.

## Implementation Notes Requirements

Record any behavior that remains interactive-only, any mode that cannot be fully deterministic, and any marker-root tradeoff in [implementation-notes.md](./implementation-notes.md).

## Handoff Requirements

Append a Phase 04 entry to [handoff-log.md](./handoff-log.md) with commands run, seeded state files, marker paths, validation/edit gaps, and next recommended command.
