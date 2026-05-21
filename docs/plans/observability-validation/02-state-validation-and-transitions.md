# Phase 02 - State Validation And Transitions

## Clean Context Start

Before doing this phase, read [README.md](./README.md), [TODO.md](./TODO.md), [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), and prior phase handoff entries. Treat the handoff log as next-agent continuity context. Treat implementation notes as the user-facing record of decisions and tradeoffs.

## Goal

Fix the most visible docs/runtime mismatch by adding field-specific state diagnostics, and guard orchestration status updates against invalid transitions.

## Inputs

- `skills/bmad-story-automator/src/story_automator/core/diagnostics.py`
- `skills/bmad-story-automator/src/story_automator/commands/state.py`
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py`
- `skills/bmad-story-automator/src/story_automator/core/frontmatter.py`
- `skills/bmad-story-automator/templates/state-document.md`
- `skills/bmad-story-automator/steps-v/step-v-01-check.md`
- `docs/state-and-resume.md`
- `docs/cli-reference.md`
- `tests/test_state_policy_metadata.py`
- `tests/test_replacement_unicode.py`

## Implementation Steps

1. Add `skills/bmad-story-automator/src/story_automator/core/state_validation.py`.
2. Validate state frontmatter fields with structured issues:
   - `epic`
   - `epicName`
   - `storyRange`
   - `status`
   - `lastUpdated`
   - runtime command config through `aiCommand` or usable `agentConfig`
   - policy snapshot metadata
3. Preserve `validate-state` compatibility:
   - keep `ok`
   - keep `structure`
   - keep `issues: list[str]`
   - add `structuredIssues: list[object]`
   - add `issueCount`
4. Add `ALLOWED_STATUS_TRANSITIONS`:
   ```python
   ALLOWED_STATUS_TRANSITIONS = {
       "INITIALIZING": {"INITIALIZING", "READY", "ABORTED"},
       "READY": {"READY", "IN_PROGRESS", "PAUSED", "ABORTED"},
       "IN_PROGRESS": {"IN_PROGRESS", "PAUSED", "EXECUTION_COMPLETE", "COMPLETE", "ABORTED"},
       "PAUSED": {"PAUSED", "IN_PROGRESS", "ABORTED"},
       "EXECUTION_COMPLETE": {"EXECUTION_COMPLETE", "COMPLETE", "ABORTED"},
       "COMPLETE": {"COMPLETE"},
       "ABORTED": {"ABORTED"},
   }
   ```
5. Update `orchestrator-helper state-update` so `status=<value>` changes are checked before writing.
6. Invalid transitions must return `ok: false`, `error: "invalid_status_transition"`, `currentStatus`, `attemptedStatus`, `allowedTransitions`, legacy `issues`, and `structuredIssues`.
7. Update `steps-v/step-v-01-check.md` to read `.structuredIssues[]?` first and fall back to legacy `.issues[]?` strings.
8. Update `docs/state-and-resume.md` and `docs/cli-reference.md` for additive diagnostics and transition rules.
9. Add `tests/test_state_validation.py` for focused state validation and transition coverage. Existing state tests may also be extended, but this phase must create the focused module because verification depends on it.

## Verification

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_state_policy_metadata tests.test_replacement_unicode
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_state_validation
```

## Exit Criteria

- `validate-state` returns field-specific diagnostics without replacing legacy string issues.
- Docs/runtime mismatch around state validation issue shape is resolved.
- `state-update` blocks invalid status regressions with actionable diagnostics.
- Legacy states remain valid where intended.

## Implementation Notes Requirements

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record the exact compatibility choice for `issues` versus `structuredIssues`, the transition table, and any allowed compatibility compromises such as `IN_PROGRESS -> COMPLETE`.

## Handoff Requirements

Append a Phase 02 entry to [handoff-log.md](./handoff-log.md) with files changed, tests run, transition table, docs changes, blockers, and the next recommended command for Phase 03.
