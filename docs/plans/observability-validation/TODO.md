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

- [ ] Read Phase 03 handoff before starting.
- [ ] Add `core/agent_plan.py`.
- [ ] Move duplicated agent config behavior toward core helper.
- [ ] Add complexity JSON validator.
- [ ] Add agents plan JSON validator.
- [ ] Preserve fallback normalization and retro overrides.
- [ ] Strengthen story/epic parse seams while preserving output shape.
- [ ] Add `tests/test_agent_plan.py`.
- [ ] Update implementation notes with remaining loose payloads and risks.
- [ ] Append Phase 04 handoff entry.

## Phase 05 - Session Runtime Diagnostics

- [ ] Read Phase 04 handoff before starting.
- [ ] Add diagnostic-aware session-state loader.
- [ ] Preserve legacy `load_session_state()` behavior where required.
- [ ] Add `SessionStateLoadResult` or equivalent typed result.
- [ ] Surface `structuredIssues` in `monitor-session --json` only when relevant.
- [ ] Preserve CSV outputs exactly.
- [ ] Update recovery/troubleshooting docs.
- [ ] Add session diagnostics tests.
- [ ] Update implementation notes with preserved compatibility behavior.
- [ ] Append Phase 05 handoff entry.

## Phase 06 - E2E Docs And Release Readiness

- [ ] Read Phase 05 handoff before starting.
- [ ] Add E2E-lite malformed input tests or fixtures.
- [ ] Update operator docs for structured diagnostics and recovery hints.
- [ ] Verify docs examples match actual JSON output.
- [ ] Run focused tests from prior phases.
- [ ] Run broad verification or document blocker.
- [ ] Review diff and file sizes.
- [ ] Update implementation notes with coverage gaps and release risks.
- [ ] Append Phase 06 handoff entry.
