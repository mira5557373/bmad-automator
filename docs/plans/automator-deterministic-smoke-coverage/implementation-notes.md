# Automator Deterministic Smoke Coverage Implementation Notes

## Purpose

This file is the running user-facing implementation record. Keep decisions, spec gaps, required changes, tradeoffs, deviations, risks, and user-relevant context here.

This is separate from [handoff-log.md](./handoff-log.md). Use the handoff log for next-agent continuity: what to read, exact commands, blockers, and next recommended actions.

## Note Template

```md
## YYYY-MM-DD - phase/session

### Context

- What part of the spec or implementation this note concerns.

### Decision, Change, Or Tradeoff

- What was decided or changed.
- Why it was necessary.

### User Impact

- What the user should know.
- Follow-up needed, or `None`.
```

## Notes

## 2026-06-02 - plan creation

### Context

- The deterministic smoke suite currently covers planning/create and two-story dev-loop plumbing.

### Decision, Change, Or Tradeoff

- The plan separates live LLM quality from deterministic control-plane verification. Deterministic gates should prove helper contracts, source-of-truth transitions, state updates, package/install determinism, and mode routing.
- The plan treats automator validate and edit modes as public surfaces that require deterministic coverage, not optional documentation-only flows.

### User Impact

- The next implementation work should not stop at create/dev. It needs to verify review, finalize, retrospective, wrapup, resume, validate, edit, marker, parser, monitor, and packaging behavior.
- `bmad-method@next` and stale workflow version metadata are known risks to resolve early.

## 2026-06-02 - oracle review application

### Context

- Oracle reviewed the deterministic smoke plan and attached critical source paths from the 2026-06-02 bundle.

### Decision, Change, Or Tradeoff

- The plan now treats Phase 02 package/prep identity, Phase 03 helper JSON contracts, and Phase 05 review/finish-loop coverage as release-blocking.
- Default `npm run verify` should target fast local deterministic gates: `test:python`, `version:check`, `pack:assert`, `test:cli`, `smoke:contracts`, `smoke:modes`, and `test:smoke`.
- Prepared-repo reset/network checks should remain explicit through `smoke:prepare`, `smoke:run`, `smoke:dev-loop`, `smoke:finish-loop`, and a wrapper such as `smoke:deterministic-full`.
- Phase 04 should prefer temp BMAD-style fixtures for resume/validate/edit and only use `.smoke/gunz` for realistic external flow coverage.
- Finish-loop commit/finalize needs a hard target-repo safety guard, not only an after-the-fact host HEAD/status sentinel.

### User Impact

- The plan is stricter now: smoke readiness cannot be claimed after only create/dev smokes.
- Implementers should extract shared smoke utilities instead of growing large repeated runners.
- Fixture writes to story files or `sprint-status.yaml` must be described as simulated child workflow output, not automator-owned mutation.
