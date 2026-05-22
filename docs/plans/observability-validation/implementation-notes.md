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

## 2026-05-22 - phase-07-review-remediation

### Context

- Phase 07 resolved the clean-context review findings that blocked issue #5 closure after Phase 06.

### Decision, Change, Or Tradeoff

- Added an opt-in JSONL event channel through `STORY_AUTOMATOR_DIAGNOSTICS_FILE`. Command stdout remains unchanged unless existing commands already return JSON diagnostics.
- Added production events for parse stage start/result, state status transitions, state story/step/epic field updates, monitor-session lifecycle results, policy decisions, and policy load failures.
- Event context and diagnostic issue messages are redacted through the shared diagnostics helpers before writing JSONL.
- Parse contract schema leaves are validated before parser sub-agent execution; malformed leaves now return `parse_contract_invalid`.
- Restored generated agent-plan missing-title compatibility by serializing missing titles as `""`.
- Restored `tmux-wrapper kill-all` default compatibility to all automator sessions; `--project-only` remains opt-in.

### User Impact

- Operators can opt into structured lifecycle diagnostics without breaking scripts that parse stdout.
- Phase 07 focused, broad, and aggregate verification passed. Final clean-context baseline is `P0/P1 clean`.

## 2026-05-22 - review-correction

### Context

- Clean-context review was run against branch diff `origin/main...HEAD` for GitHub issue #5 and the observability-validation plan.
- The review checked plan coverage and implementation evidence from source and tests.

### Decision, Change, Or Tradeoff

- Phase 06's local release-ready claim is superseded by review findings until Phase 07 is completed.
- Added Phase 07 to resolve the blocking findings instead of rewriting completed Phase 00-06 history.
- The P1 blocker is that `DiagnosticEvent` is defined and serializable, but no production code emits structured lifecycle, orchestration-stage, state-transition, session, or policy-decision events. Existing implementation mostly adds `structuredIssues` to malformed/error paths.
- Additional findings to resolve:
  - malformed parse schema leaves are caught only after parser sub-agent execution
  - missing complexity story titles serialize as `null` instead of the prior empty string
  - `tmux-wrapper kill-all` default behavior changed outside additive diagnostics scope

### User Impact

- The branch should not close issue #5 until Phase 07 reaches a `P0/P1 clean` review baseline.
- Focused and broad Python verification still passed before this correction, so the blocker is a requirements/coverage gap rather than an existing test failure.

## 2026-05-21 - phase-06-e2e-docs-and-release-readiness

### Context

- Phase 06 closes the observability-validation plan with E2E-lite malformed input coverage, operator docs, and release verification.

### Decision, Change, Or Tradeoff

- Added `tests/test_diagnostics_e2e.py` to exercise malformed LLM parse output, invalid state frontmatter, illegal status transitions, malformed agent-plan JSON, and malformed persisted session state through command-level boundaries.
- Updated operator docs to describe additive `structuredIssues` behavior while keeping legacy `issues`, `reason`, and CSV output expectations explicit.
- Verified documented examples against actual JSON output shapes from the implemented commands.
- Kept this phase to tests and docs only; no new runtime code was needed after Phases 01-05.

### User Impact

- Observability-validation is release-ready locally: focused matrix, full Python suite, CLI check, dry pack, smoke, and aggregate verify pass.
- Release risk: smoke still emits optional `bmad-qa-generate-e2e-tests` warnings when that skill is not installed, but exits successfully.
- File-size note: `commands/orchestrator.py` is exactly 500 lines; `core/runtime_policy.py` and `core/tmux_runtime.py` remain above the soft AGENTS limit from existing structure and were not refactored in this phase.

## 2026-05-21 - phase-05-session-runtime-diagnostics

### Context

- Phase 05 adds diagnostic-aware persisted session-state loading for tmux/runner monitoring.

### Decision, Change, Or Tradeoff

- Legacy `load_session_state()` still returns `{}` for missing, unreadable, invalid JSON, and non-object JSON state.
- New `load_session_state_diagnostics()` returns `SessionStateLoadResult` with `ok`, `state`, `issue`, and `exists`.
- Missing session-state remains silent in `monitor-session --json`; malformed existing state adds `structuredIssues` only when the session is gone and the state issue affects the result.
- CSV commands keep exact existing output. `heartbeat-check`, `tmux-status-check`, and `codex-status-check` are not given structured diagnostics.
- Unexpected state schema versions are warnings in the diagnostic loader, not hard failures.

### User Impact

- Existing runtime callers keep compatibility behavior.
- Operators get structured JSON diagnostics when a stale malformed runner-state file explains a missing session.

## 2026-05-21 - phase-04-agent-complexity-and-story-boundaries

### Context

- Phase 04 hardens agent complexity and agents-plan file boundaries before command handlers consume raw JSON.

### Decision, Change, Or Tradeoff

- Added `core/agent_plan.py` for complexity and agents-plan validators plus file loaders.
- `agents-build` now validates the complexity payload before delegating plan generation to `core.agent_config.build_agents_file`.
- `agents-resolve` now validates the agents-plan payload before delegating resolution to `core.agent_config.resolve_agents`.
- Successful `agents-build`, `agents-resolve`, and `retro-agent` output shapes are preserved.
- Unknown fields in complexity and agents-plan payloads remain allowed unless they break required boundary contracts.
- Fallback normalization and legacy `retro` overrides stay in existing agent config helpers.
- Story/epic parser output was not changed; `StoryKey` and `SprintStatus` remain the typed seams for this phase to avoid unnecessary CLI JSON churn.

### User Impact

- Malformed complexity and agent-plan JSON now fail early with `structuredIssues`.
- Existing valid agent selection flows keep the same response shapes.

## 2026-05-21 - phase-03-parser-and-contract-boundaries

### Context

- Phase 03 moves parse contract validation out of command code and adds field-specific diagnostics for parse/verifier failures.

### Decision, Change, Or Tradeoff

- Parse success output remains exactly the child JSON payload serialized compactly; no `structuredIssues` are added on success.
- Parse failure output preserves legacy `status: "error"` and `reason` values and adds `structuredIssues`.
- Parser diagnostics now include field paths such as `issues_found.critical`, `story_file`, `status`, `requiredKeys`, and `parse.schemaPath`.
- Verifier command-boundary contract failures keep existing `verified`, `reason`, and `error` fields and add `structuredIssues`.
- No diagnostic events are emitted in parse failure JSON; only `structuredIssues` are returned.
- Parse schema expressiveness remains limited to the existing mini-schema rules: nested objects, `integer`, `true|false`, `path or null`, pipe-delimited enums, and non-empty strings.

### User Impact

- Existing automation branching on legacy parse/verifier `reason` values keeps working.
- Operators and future agents can now see the exact malformed field that caused parser rejection.

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
