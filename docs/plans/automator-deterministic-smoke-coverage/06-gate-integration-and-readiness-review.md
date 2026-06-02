# Phase 06 - Gate Integration And Readiness Review

## Clean Context Start

Before doing this phase, read [README.md](./README.md), this phase file, [TODO/phase-06.md](./TODO/phase-06.md), [implementation-notes.md](./implementation-notes.md), [gate-map.md](./gate-map.md), and relevant earlier entries in [handoff-log.md](./handoff-log.md).

Do not read later phase files or later TODO files as acceptance criteria for this phase.

## Goal

Wire the deterministic smoke suite into the right repo gates, then run a clean-context coverage review to verify the plan and implementation cover the automator's full functionality.

Default verification should stay fast, local, and deterministic. Prepared-repo reset/network gates should be explicit pre-release or nightly checks unless CI proves they are stable enough for every `npm run verify`.

## Inputs

- [package.json](../../../package.json)
- [gate-map.md](./gate-map.md)
- All phase handoff entries
- Existing test commands: `test:python`, `test:cli`, `pack:dry-run`, `test:smoke`, `smoke:run`, `smoke:dev-loop`, and new smoke commands from earlier phases.

## Implementation Steps

1. Decide which deterministic smokes belong in `npm run verify` and which remain heavier manual/pre-live gates. Target default verify shape: `test:python && version:check && pack:assert && test:cli && smoke:contracts && smoke:modes && test:smoke`.
2. Update `package.json` scripts so fast deterministic contract gates are always run by `verify`; keep external repo reset-heavy gates explicit if they are too slow for default verify.
3. Add or confirm an explicit full prepared-repo wrapper target, for example `smoke:deterministic-full`, that runs `smoke:prepare -- --reset`, `smoke:run`, `smoke:dev-loop`, and `smoke:finish-loop`.
4. Ensure every gate in [gate-map.md](./gate-map.md) has owner/location, command, reset/cache policy, CI status, pass/fail signal, failure diagnostic, and risk note.
5. Document live/manual smoke boundaries separately from deterministic gates: provider auth, rate limits, trust prompts, provider outages, semantic quality of generated stories/code/reviews/retrospectives, moving registry/git inputs without pin/assert, and conversational UX beyond helper-backed effects.
6. Run the full local verification set selected by the gate map.
7. Run `general-subagent-review-loop` against the completed implementation and gate map with at least:
   - workflow lifecycle reviewer
   - runtime/helper contract reviewer
   - package/install determinism reviewer
   - validate/edit/resume reviewer
8. Triage reviewer findings; fix credible P0/P1 gaps or explicitly document blockers.
9. Update [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), and [gate-map.md](./gate-map.md) with final readiness.

## Verification

- Run `npm run verify`.
- Run every additional deterministic smoke command marked required in [gate-map.md](./gate-map.md).
- Run `git diff --check`.
- Run clean-context sub-agent review and record results in [handoff-log.md](./handoff-log.md).

## Exit Criteria

- Gate map is complete and no required deterministic gate is missing a command or pass/fail signal.
- `verify` includes the intended fast deterministic gates.
- `smoke:deterministic-full` or equivalent explicit prepared-repo release gate exists and is documented separately from default verify.
- Manual/live boundaries are documented so deterministic smoke readiness is not misrepresented as LLM quality or provider readiness.
- Clean-context review is P0/P1 clean or blockers are explicitly documented.
- Phase 06 handoff entry appended.

## Implementation Notes Requirements

Record gate inclusion tradeoffs, slow-gate exclusions, CI assumptions, and final coverage risks in [implementation-notes.md](./implementation-notes.md).

## Handoff Requirements

Append a Phase 06 entry to [handoff-log.md](./handoff-log.md) with commands run, reviewer roles/results, unresolved risks, and final recommended merge/readiness action.
