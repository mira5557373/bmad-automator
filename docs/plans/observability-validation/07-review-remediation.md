# Phase 07 - Review Remediation

## Clean Context Start

Before doing this phase, read [README.md](./README.md), [TODO.md](./TODO.md), [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), the Phase 06 handoff, and the 2026-05-22 review correction handoff entry. Treat the handoff log as next-agent continuity context. Treat implementation notes as the user-facing record of decisions and tradeoffs.

## Goal

Resolve the clean-context review findings that block issue #5 closure, especially the missing structured orchestration-stage diagnostics/events. Keep changes additive unless a compatibility fix restores prior behavior.

## Inputs

- GitHub issue `bmad-code-org/bmad-automator#5`
- [README.md](./README.md) Review Status section
- [implementation-notes.md](./implementation-notes.md) 2026-05-22 review correction entry
- [handoff-log.md](./handoff-log.md) 2026-05-22 review correction entry
- `skills/bmad-story-automator/src/story_automator/core/diagnostics.py`
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py`
- `skills/bmad-story-automator/src/story_automator/commands/state.py`
- `skills/bmad-story-automator/src/story_automator/commands/tmux.py`
- `skills/bmad-story-automator/src/story_automator/core/parse_contracts.py`
- `skills/bmad-story-automator/src/story_automator/core/agent_plan.py`
- `tests/test_diagnostics.py`
- `tests/test_orchestrator_parse.py`
- `tests/test_agent_plan.py`
- `tests/test_cli_contracts.py`
- `tests/test_diagnostics_e2e.py`

## Implementation Steps

1. Resolve the structured diagnostics/event channel.
   - Define where production `DiagnosticEvent` payloads are emitted without breaking legacy command output.
   - Prefer an explicit opt-in channel, file, or JSON field over unconditional stdout changes.
   - Cover key orchestration lifecycle/stage/state/policy decisions from issue #5: orchestration step start/result, story/epic/session state transition, and policy decision or policy load failure.
   - Redact context through existing diagnostics helpers.
2. Add event diagnostics tests.
   - Assert at least one successful or in-flight orchestration path emits a structured event through the chosen channel.
   - Assert state transition or policy diagnostics include useful context without leaking absolute paths or secret-like values.
   - Preserve successful parse payload shape where Phase 03 required exact output compatibility.
3. Validate parse contract schema leaves before sub-agent execution.
   - Recursively validate parse schema leaves in `validate_parse_contract()`.
   - Return `parse_contract_invalid` for malformed schema rules.
   - Add a regression test proving `run_cmd` is not called when a schema leaf is invalid.
4. Restore generated agent-plan title compatibility.
   - Ensure missing complexity story titles serialize as `""`, not `null`.
   - Add a regression test for missing `title`.
5. Restore or explicitly document `tmux-wrapper kill-all` compatibility.
   - Preferred fix: restore prior default all-session behavior and keep `--project-only` as opt-in.
   - If project-only default is intentional, document the compatibility break in user-facing docs and implementation notes before marking this item done.
6. Re-run focused tests, then broad verification.
7. Request or run a final clean-context review pass focused on Phase 07 changes and issue #5 acceptance criteria.

## Verification

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_diagnostics tests.test_orchestrator_parse tests.test_agent_plan tests.test_cli_contracts tests.test_diagnostics_e2e
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests
npm run test:cli
npm run test:smoke
npm run verify
git diff --check
```

If npm verification is unavailable or requires external setup, record the exact command, error, and closest completed Python/CLI verification.

## Exit Criteria

- Production code emits structured diagnostics/events for key orchestration-stage, state-transition, session, or policy decisions through a documented compatibility-safe channel.
- Parse contract schema defects fail before sub-agent execution with `parse_contract_invalid` and `structuredIssues`.
- Missing complexity story title preserves prior generated output compatibility.
- `tmux-wrapper kill-all` behavior is either restored to prior compatibility or explicitly documented as an intentional compatibility break.
- Focused and broad verification pass, or exact blockers are recorded.
- Latest clean-context review baseline is `P0/P1 clean`, or any remaining `P0/P1` blocker is documented with exact owner/action.

## Implementation Notes Requirements

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record:

- chosen structured event/diagnostics channel and compatibility tradeoff
- exact event names and contexts added
- whether `kill-all` default was restored or intentionally changed
- any diagnostics output shape changes
- unresolved release risks

## Handoff Requirements

Append a Phase 07 entry to [handoff-log.md](./handoff-log.md) with:

- what changed
- exact commands run and results
- final review baseline status
- decisions or assumptions the next agent must preserve or re-check
- blockers or risks
- recommended PR summary or next phase if not complete
