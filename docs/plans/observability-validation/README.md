# Observability And Validation Plan

## Purpose

Plan for GitHub issue #5, "Increase automator observability and validation clarity." The goal is to make the automator fail earlier and explain failures better at LLM, file, CLI/config, persisted state, policy, and runtime/session boundaries.

This is not a full object-oriented rewrite. Use small typed/domain seams, structured diagnostics, and focused tests while preserving existing successful workflows.

## Critical Findings

- LLM output validation currently collapses missing fields, wrong nested types, and enum mismatches into generic `sub-agent returned invalid json`.
- `validate-state` currently returns `issues: list[str]`, while skill validation docs already expect structured issue fields such as `.issues[].type` and `.issues[].field`.
- `state-update` directly regex-replaces frontmatter fields without an allowed-transition guard.
- Agent plan and complexity payload handling still accepts raw JSON/dicts at command boundaries and can raise late exceptions.
- Existing policy validation, policy snapshots, `StoryKey`, `SprintStatus`, success verifier contracts, and tmux runtime dataclasses are useful anchors. Build from them instead of replacing everything.

## Review Status

Phase 06 local verification passed, but the clean-context review on 2026-05-22 found the branch was not ready to close issue #5. Phase 07 remediated the blocking findings. A follow-up review on 2026-05-22 confirmed the latest review baseline is `P0/P1 clean`, with non-blocking P2 diagnostic consistency follow-ups captured in Phase 08.

Blocking review findings resolved by Phase 07:

- P1: `DiagnosticEvent` is only a serialization helper; no production path emits structured lifecycle, orchestration-stage, state-transition, or policy-decision diagnostics, despite issue #5 and Phase 06 exit criteria requiring key orchestration stages to emit stable structured diagnostics or events.
- P2: parse schema leaf rules are validated only after the parser sub-agent runs, so malformed parse contracts can fail as `sub-agent returned invalid json` instead of `parse_contract_invalid`.
- P3: `agents-build` emits `title: null` for accepted complexity stories without titles; prior behavior emitted an empty string.
- P3: `tmux-wrapper kill-all` default behavior changed from all automator sessions to current-project sessions, outside the additive diagnostics scope.

Non-blocking P2 follow-ups captured for Phase 08:

- `validate-story-creation` preserves its compatibility schema on diagnostic failures but does not yet add `structuredIssues` where the compatibility strategy says it should.
- `state-update` redacts `structuredIssues` and opt-in events, but raw legacy fields such as `attemptedStatus` and `issues` can still echo sensitive attempted status values.
- `verifier_exception_payload()` redacts `structuredIssues`, but the legacy `error` string can still expose raw exception text.

## Constraints

- Preserve existing public CLI commands and successful workflow behavior unless a phase explicitly documents a compatibility reason.
- Keep output compatibility where scripts may depend on existing fields; add structured fields alongside old fields before removing anything.
- Keep files under roughly 500 LOC. Split helpers into focused modules when needed.
- Prefer end-to-end verification. If blocked, record exact missing command, fixture, or runtime dependency.
- Treat Oracle output as advisory. Verify every recommendation against local source and tests.

## Critical Path

Diagnostic schema -> state validation and transition guards -> parser/verifier field diagnostics -> agent/complexity payload validators -> session-state diagnostics -> E2E/docs.

## Phase Map

0. [Phase 00 - Baseline And Plan Reconciliation](./00-baseline-and-plan-reconciliation.md)
1. [Phase 01 - Diagnostics Contract](./01-diagnostics-contract.md)
2. [Phase 02 - State Validation And Transitions](./02-state-validation-and-transitions.md)
3. [Phase 03 - Parser And Contract Boundaries](./03-parser-and-contract-boundaries.md)
4. [Phase 04 - Agent Complexity And Story Boundaries](./04-agent-complexity-and-story-boundaries.md)
5. [Phase 05 - Session Runtime Diagnostics](./05-session-runtime-diagnostics.md)
6. [Phase 06 - E2E Docs And Release Readiness](./06-e2e-docs-and-release-readiness.md)
7. [Phase 07 - Review Remediation](./07-review-remediation.md)
8. [Phase 08 - Diagnostic Redaction Completion](./08-diagnostic-redaction-completion.md)

## Gate Map

Deterministic verification gates are tracked in [gate-map.md](./gate-map.md). Final review or smoke phases should consume that map instead of rediscovering commands from scattered notes.

## Compatibility Strategy

Use additive compatibility for issue #5. Preserve existing fields and add structured diagnostics beside them:

- `validate-state`: keep `ok`, `structure`, and `issues: list[str]`; add `structuredIssues` and `issueCount`.
- `state-update`: keep `ok`, `updated`, and `error`; add `structuredIssues`, `currentStatus`, `attemptedStatus`, and `allowedTransitions`.
- `parse-output`: keep success payloads unchanged; on failure keep `status: "error"` and legacy `reason`, and add `structuredIssues`.
- `verify-step`, `verify-code-review`, and `validate-story-creation`: keep existing status/reason fields and add `structuredIssues` on diagnostic-worthy failures.
- `agents-build`, `agents-resolve`, and `retro-agent`: keep `ok`, `error`, and current selection fields; add `structuredIssues` on invalid payloads.
- `monitor-session --json`: preserve existing JSON fields; add `structuredIssues` only when session diagnostics affect the result.
- CSV commands: preserve exact CSV output and do not add structured fields.

## High-Risk Source Paths

- `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py`
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator_parse.py`
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py`
- `skills/bmad-story-automator/src/story_automator/commands/state.py`
- `skills/bmad-story-automator/src/story_automator/commands/tmux.py`
- `skills/bmad-story-automator/src/story_automator/commands/validate_story_creation.py`
- `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py`
- `skills/bmad-story-automator/src/story_automator/core/agent_config.py`
- `skills/bmad-story-automator/src/story_automator/core/epic_parser.py`
- `skills/bmad-story-automator/src/story_automator/core/frontmatter.py`
- `skills/bmad-story-automator/src/story_automator/core/story_keys.py`
- `skills/bmad-story-automator/src/story_automator/core/sprint.py`
- `skills/bmad-story-automator/src/story_automator/core/success_verifiers.py`
- `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py`

## Assumptions

- Target branch is `bma-d/e2e-tests`, tracking `origin/main`.
- Current HEAD at plan creation was `33601b9`.
- Issue reference is `bmad-code-org/bmad-automator#5`.
- Oracle feedback has been applied. Oracle review is not a blocking phase.
- Repo-supported broad test command is `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests`; npm wraps it as `npm run test:python`.

## Clean Context Agent Protocol

Before starting any phase, read this README, the assigned phase file, the assigned phase TODO file when one exists, [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), and relevant earlier phase handoff entries. For completed historical phases without phase-scoped TODO files, use the matching section in [TODO.md](./TODO.md) only as history. Do not rely on conversation history.

Do not read later phase files or later TODO files as acceptance criteria for the current phase.

Before ending any phase, append a handoff entry with exact commands, paths, SHAs, decisions, blockers, and next recommended actions.

## Implementation Notes Protocol

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record user-facing decisions, spec gaps, required changes, tradeoffs, deviations, notable risks, and questions there. Use [handoff-log.md](./handoff-log.md) only for next-agent continuity.
