# Phase 05 - Automate Review Finish Retro Coverage

## Clean Context Start

Before doing this phase, read [README.md](./README.md), this phase file, [TODO/phase-05.md](./TODO/phase-05.md), [gate-map.md](./gate-map.md), [implementation-notes.md](./implementation-notes.md), and relevant earlier entries in [handoff-log.md](./handoff-log.md).

Do not read later phase files or later TODO files as acceptance criteria for this phase.

## Goal

Add deterministic coverage for the second half of the automator lifecycle: automate, review loop, commit/finalize, epic completion, retrospective routing, execution complete, and wrapup.

This phase is release-blocking. Existing deterministic smokes stop before the review-to-done and finish-loop gates that are most likely to create false-positive smoke readiness.

## Inputs

- [skills/bmad-story-automator/steps-c/step-03a-execute-review.md](../../../skills/bmad-story-automator/steps-c/step-03a-execute-review.md)
- [skills/bmad-story-automator/steps-c/step-03b-execute-finish.md](../../../skills/bmad-story-automator/steps-c/step-03b-execute-finish.md)
- [skills/bmad-story-automator/steps-c/step-03c-execute-complete.md](../../../skills/bmad-story-automator/steps-c/step-03c-execute-complete.md)
- [skills/bmad-story-automator/steps-c/step-04-wrapup.md](../../../skills/bmad-story-automator/steps-c/step-04-wrapup.md)
- [skills/bmad-story-automator/data/code-review-loop.md](../../../skills/bmad-story-automator/data/code-review-loop.md)
- [skills/bmad-story-automator/data/retrospective-automation.md](../../../skills/bmad-story-automator/data/retrospective-automation.md)
- [skills/bmad-story-automator/data/orchestration-policy.json](../../../skills/bmad-story-automator/data/orchestration-policy.json)

## Implementation Steps

1. Add a deterministic finish-loop smoke for two stories that begins after dev completion and drives automate/review/finalize transitions.
2. Cover automate success and non-blocking failure/skip rows.
3. Cover review completion through `verify-code-review` or `verify-step review`, including incomplete review retry/escalation payloads where deterministic.
4. Cover commit/finalize without depending on real product implementation: create a controlled change, run `commit-story`, assert JSON, commit metadata, and progress-row `git-commit=done`.
5. Add host-repo commit isolation sentinel before running finish-loop: record host HEAD/status, create or identify a host-only uncommitted sentinel, run finish-loop against `.smoke/gunz` or an explicit temp smoke repo, then assert host HEAD/status and sentinel state are unchanged while only the smoke repo receives the controlled commit.
6. Add a target-repo safety guard: the finish-loop runner should refuse `commit-story --repo` unless the repo path is under the configured smoke workspace, except behind an explicit unsafe override reserved for manual debugging.
7. Cover sprint-status and story-file fallback rules for finalization.
8. Cover epic completion detection using `check-epic-complete`, `get-epic-stories`, and `sprint-status check-epic`.
9. Cover retrospective agent resolution and `build-cmd retro`; use runner/fake monitor output so retrospective failure is recorded as skipped and non-blocking.
10. Add a seeded multi-epic deterministic fixture and bind it to `npm run smoke:finish-loop -- --scenario multi-epic`, or make `npm run smoke:finish-loop` always include this scenario. Selected stories must cross at least two epics; Epic 1 completes before Epic 2; Epic 1 retrospective triggers inside the execution loop; Epic 1 retrospective failure records `skipped` and does not block Epic 2; Epic 2 continues to completion; state records separate `retrospectives.epic-*`; wrapup occurs only after all selected stories complete.
11. Assert artifact and source-of-truth outputs: final state fields, progress rows, action log deltas, review fallback payloads, incomplete review diagnostics, commit SHA, smoke repo `git log`, story-file status, sprint-status status, retro state entries, summary report, marker removal, and host `.gitignore`/status invariants.
12. Cover `step-03c` and wrapup state transitions: `EXECUTION_COMPLETE`, `COMPLETE`, summary metrics, and marker removal.
13. Update [gate-map.md](./gate-map.md) with automate/review/finalize/commit-isolation/single-epic-retro/multi-epic-retro/wrapup gates.

## Verification

- Run the new finish-loop smoke command.
- Run the multi-epic scenario command if it is split: `npm run smoke:finish-loop -- --scenario multi-epic`.
- Run `npm run smoke:dev-loop`.
- Run `npm run test:python`.
- Run `git log --oneline -3` inside the controlled smoke repo if commit-story creates commits there.
- Run `git diff --check`.

## Exit Criteria

- Deterministic smoke covers the full create-to-wrapup lifecycle except live LLM code quality.
- Review incomplete, single-epic retrospective failure, and multi-epic non-blocking retrospective failure are proven non-happy-path contracts.
- Multi-epic lifecycle proves per-epic retrospective timing and independent continuation to later epics.
- The multi-epic scenario is wired into `smoke:finish-loop` or has a concrete split command that Phase 06 includes in `smoke:deterministic-full`.
- Commit behavior is isolated to the smoke repo and proven with a host HEAD/status sentinel so it cannot commit host repo changes by accident.
- Finish-loop commit/finalize refuses unsafe repo targets unless an explicit manual override is supplied.
- Phase 05 handoff entry appended.

## Implementation Notes Requirements

Record any commit isolation constraints, review-loop limitations, retrospective skip semantics, and source-of-truth fallback decisions in [implementation-notes.md](./implementation-notes.md).

## Handoff Requirements

Append a Phase 05 entry to [handoff-log.md](./handoff-log.md) with commands run, smoke repo SHAs, state files, review/retro outcomes, blockers, and next recommended command.
