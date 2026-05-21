# Observability And Validation Implementation Notes

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

## 2026-05-21 - phase-02-state-validation-and-transitions

### Context

- Phase 02 wires diagnostics into `validate-state` and guards `orchestrator-helper state-update --set status=...`.

### Decision, Change, Or Tradeoff

- `validate-state` keeps `ok`, `structure`, and legacy `issues: list[str]`, and adds `structuredIssues` plus `issueCount`.
- State validation now returns field-specific diagnostics for required frontmatter, status enum, last-updated shape, runtime command config, and policy snapshot metadata.
- Status transitions follow the planned table exactly, including the compatibility allowance `IN_PROGRESS -> COMPLETE`.
- Invalid status updates return `ok:false`, `error:"invalid_status_transition"`, `currentStatus`, `attemptedStatus`, `allowedTransitions`, `issues`, and `structuredIssues` before writing.
- Non-status `state-update` calls keep the existing success response shape.
- The execution workflow already said to set `IN_PROGRESS` before execution, but only in prose. Phase 02 makes that state update explicit so the later `EXECUTION_COMPLETE` update remains a valid transition.

### User Impact

- Existing consumers of `validate-state` legacy string issues keep working.
- New validation/reporting code can read `structuredIssues` for field-specific diagnostics.
- Manual state regressions such as `READY -> COMPLETE` are blocked with actionable allowed transitions.

## 2026-05-21 - phase-01-diagnostics-contract

### Context

- Phase 01 adds the shared diagnostics contract without wiring it into command outputs.

### Decision, Change, Or Tradeoff

- `DiagnosticIssue` and `DiagnosticEvent` are frozen dataclasses so later phases can pass stable typed values without side effects.
- Serialized issue keys are stable and always include `type`, `field`, `expected`, `actual`, `message`, `recovery`, `code`, `severity`, and `source`.
- `actual` is redacted during serialization; `expected` is converted to JSON-safe values without redaction so validators can explain the contract.
- Redaction masks secret-like dict keys and inline assignments, shortens absolute paths to `<path:name>`, truncates long strings, and caps nested collections.
- `DiagnosticEvent` is only a structured payload helper in this phase; it does not emit standalone stdout or log lines.
- Added `tests/__init__.py` so the Phase 01 focused command `python3 -m unittest tests.test_diagnostics` works with the repository test layout.

### User Impact

- No CLI behavior changes in Phase 01.
- Later phases can add `structuredIssues` from the same helper while preserving legacy fields.

## 2026-05-21 - phase-00-baseline

### Context

- Phase 00 established the starting test and CLI baseline before diagnostics implementation.
- The requested local `.claude/skills/bmad-quick-dev/SKILL.md` and `_bmad/bmm/config.yaml` files are not present in this worktree.

### Decision, Change, Or Tradeoff

- Applied the generic BMaD quick-dev workflow from an installed/source copy on disk only where it was compatible with this repository, while using the local phase packet as source truth.
- Oracle feedback is confirmed incorporated in the plan and non-blocking.
- Broad `npm run verify` was run during Phase 00 instead of deferring to Phase 06 because baseline runtime was acceptable.

### User Impact

- Baseline is green: 207 Python tests pass, CLI help imports, package dry run succeeds, CLI smoke succeeds, and smoke test passes.
- Smoke verification emits warnings for missing optional `bmad-qa-generate-e2e-tests` skill fixtures; this is not blocking because the command exits successfully.
- The local repo is missing the requested BMaD config/quick-dev files, so subsequent phases should continue from the observability plan artifacts unless those files are added.

## 2026-05-21 - planning/session

### Context

- GitHub issue #5 asks for observability and validation clarity.
- User clarified that this is also the basis for more encapsulated, domain-based modules that can be tested separately.

### Decision, Change, Or Tradeoff

- Plan uses incremental typed/domain seams, not a full domain rewrite.
- First implementation slice should target structured diagnostics and `validate-state`, because docs already expect issue objects with fields such as `type` and `field`.
- Parser, agent plan, state transition, and session diagnostics follow after the shared diagnostics contract exists.
- Oracle output is requested as a manual paste bundle, not a browser/API run, because the local Oracle skill notes say browser automation is unreliable.

### User Impact

- The implementation should improve failure messages before changing orchestration semantics.
- Existing successful workflows should keep working while diagnostics become richer.

## 2026-05-21 - oracle-feedback-application

### Context

- Oracle reviewed the initial packet and recommended concrete changes to the critical path and phase shape.

### Decision, Change, Or Tradeoff

- Oracle review is no longer a blocking Phase 01. It is treated as already received, and Phase 00 is now only baseline and plan reconciliation.
- The critical path is now explicit: diagnostic schema -> state validation and transition guards -> parser/verifier field diagnostics -> agent/complexity payload validators -> session-state diagnostics -> E2E/docs.
- The previous agent/story/session phase was split into Phase 04 for agent, complexity, and story boundaries, and Phase 05 for session runtime diagnostics.
- The diagnostics schema now requires `severity` and `source` from the first implementation phase.
- Compatibility strategy is additive only. `validate-state` keeps `issues: list[str]` and adds `structuredIssues` plus `issueCount`; successful parser output remains unchanged.
- Verification commands now use the repo-supported `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest ...` pattern instead of defaulting to `pytest`.

### User Impact

- The plan is more executable by clean-context agents and reduces risk by isolating tmux/session work from agent-plan validation.
- Oracle response is considered applied; implementation can start without another external review step.
