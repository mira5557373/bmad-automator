# Observability And Validation TODO

## Phase 00 - Baseline And Plan Reconciliation

- [x] Read README, implementation notes, handoff log, and prior entries.
- [x] Record current branch, HEAD, and working tree status.
- [x] Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests` or document why blocked.
- [x] Run `PYTHONPATH=skills/bmad-story-automator/src python3 -m story_automator --help`.
- [x] Confirm Oracle feedback is incorporated and non-blocking.
- [x] Update implementation notes with baseline surprises or scope changes.
- [x] Append Phase 00 handoff entry.

## Phase 01 - Diagnostics Contract

- [x] Read Phase 00 handoff before starting.
- [x] Add `core/diagnostics.py`.
- [x] Add `DiagnosticIssue` with `severity` and `source`.
- [x] Add `DiagnosticEvent`.
- [x] Add serialization, legacy-message, exception, and redaction helpers.
- [x] Add `tests/test_diagnostics.py`.
- [x] Preserve all command output shapes.
- [x] Update implementation notes with diagnostics shape decisions.
- [x] Append Phase 01 handoff entry.

## Phase 02 - State Validation And Transitions

- [x] Read Phase 01 handoff before starting.
- [x] Add `core/state_validation.py`.
- [x] Add field-specific state diagnostics.
- [x] Preserve legacy `issues: list[str]` and add `structuredIssues` plus `issueCount`.
- [x] Add allowed status transition table.
- [x] Guard `state-update` status transitions.
- [x] Align `steps-v/step-v-01-check.md` with `structuredIssues` and legacy fallback.
- [x] Update state/CLI docs.
- [x] Add `tests/test_state_validation.py`.
- [x] Update implementation notes with transition and compatibility decisions.
- [x] Append Phase 02 handoff entry.

## Phase 03 - Parser And Contract Boundaries

- [x] Read Phase 02 handoff before starting.
- [x] Add `core/parse_contracts.py`.
- [x] Add field-path parser diagnostics.
- [x] Preserve parse success payloads exactly.
- [x] Preserve legacy parse failure `reason` values.
- [x] Extend success verifier diagnostics where safe.
- [x] Add parser/verifier malformed payload tests.
- [x] Update implementation notes with parser compatibility decisions.
- [x] Append Phase 03 handoff entry.

## Phase 04 - Agent Complexity And Story Boundaries

- [x] Read Phase 03 handoff before starting.
- [x] Add `core/agent_plan.py`.
- [x] Move duplicated agent config behavior toward core helper.
- [x] Add complexity JSON validator.
- [x] Add agents plan JSON validator.
- [x] Preserve fallback normalization and retro overrides.
- [x] Strengthen story/epic parse seams while preserving output shape.
- [x] Add `tests/test_agent_plan.py`.
- [x] Update implementation notes with remaining loose payloads and risks.
- [x] Append Phase 04 handoff entry.

## Phase 05 - Session Runtime Diagnostics

- [x] Read Phase 04 handoff before starting.
- [x] Add diagnostic-aware session-state loader.
- [x] Preserve legacy `load_session_state()` behavior where required.
- [x] Add `SessionStateLoadResult` or equivalent typed result.
- [x] Surface `structuredIssues` in `monitor-session --json` only when relevant.
- [x] Preserve CSV outputs exactly.
- [x] Update recovery/troubleshooting docs.
- [x] Add session diagnostics tests.
- [x] Update implementation notes with preserved compatibility behavior.
- [x] Append Phase 05 handoff entry.

## Phase 06 - E2E Docs And Release Readiness

- [x] Read Phase 05 handoff before starting.
- [x] Add E2E-lite malformed input tests or fixtures.
- [x] Update operator docs for structured diagnostics and recovery hints.
- [x] Verify docs examples match actual JSON output.
- [x] Run focused tests from prior phases.
- [x] Run broad verification or document blocker.
- [x] Review diff and file sizes.
- [x] Update implementation notes with coverage gaps and release risks.
- [x] Append Phase 06 handoff entry.
