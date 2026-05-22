# Phase 08 - Diagnostic Redaction Completion

## Clean Context Start

Before doing this phase, read [README.md](./README.md), this phase file, [TODO/phase-08.md](./TODO/phase-08.md), [implementation-notes.md](./implementation-notes.md), and the Phase 07 plus Phase 08 planning entries in [handoff-log.md](./handoff-log.md). Treat the handoff log as next-agent continuity context. Treat implementation notes as the user-facing record of decisions and tradeoffs.

Do not read later phase files or later TODO files as acceptance criteria for this phase.

## Goal

Resolve the non-blocking P2 review findings from the 2026-05-22 follow-up review by making diagnostic redaction and additive `structuredIssues` behavior consistent across remaining compatibility fields, without breaking existing successful command contracts.

## Inputs

- GitHub issue `bmad-code-org/bmad-automator#5`
- [README.md](./README.md) Review Status section
- [implementation-notes.md](./implementation-notes.md) 2026-05-22 phase-08-planning entry
- [handoff-log.md](./handoff-log.md) Phase 08 planning entry
- `skills/bmad-story-automator/src/story_automator/commands/validate_story_creation.py`
- `skills/bmad-story-automator/src/story_automator/core/state_validation.py`
- `skills/bmad-story-automator/src/story_automator/core/parse_contracts.py`
- `skills/bmad-story-automator/src/story_automator/core/diagnostics.py`
- `tests/test_success_verifiers.py`
- `tests/test_state_validation.py`
- `tests/test_diagnostics_e2e.py`
- [gate-map.md](./gate-map.md)

## Implementation Steps

1. Add `structuredIssues` to `validate-story-creation` diagnostic-worthy failures while preserving existing compatibility fields:
   - keep `valid`, `verified`, `created_count`, `expected`, `prefix`, `action`, `reason`, `source`, `pattern`, and `matches`
   - add `structuredIssues` only on failures where a field-specific diagnostic can be produced
   - cover policy/contract failures, missing or unreadable state file failures, invalid count arguments, unsupported flags, and missing flag values where practical
2. Redact sensitive values in `state-update` invalid-transition compatibility fields:
   - preserve existing field names and array/object shapes
   - ensure `currentStatus`, `attemptedStatus`, and legacy `issues` do not expose raw secret-like assignments or absolute paths
   - keep `allowedTransitions` unchanged
3. Redact `verifier_exception_payload()` legacy `error` text while preserving the `error` field name and existing `structuredIssues`.
4. Add regression tests:
   - `validate-story-creation` failures include useful `structuredIssues` while keeping the old schema
   - invalid status stdout omits raw `token=abc123` and absolute paths
   - verifier exception payload omits raw `token=abc123` and absolute paths outside redacted placeholders
5. Update operator docs only if any visible compatibility field now intentionally redacts values.
6. Update [gate-map.md](./gate-map.md) if verification commands or pass/fail signals change.

## Verification

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_success_verifiers tests.test_state_validation tests.test_diagnostics_e2e
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests
npm run verify
git diff --check
```

If any command is unavailable or requires external runtime setup, record the exact blocker and closest completed verification.

## Exit Criteria

- `validate-story-creation` diagnostic-worthy failures carry additive `structuredIssues` without removing legacy fields.
- Invalid `state-update` outputs redact raw secret-like attempted status values and absolute paths in both structured and legacy fields.
- Verifier exception payloads redact legacy `error` text consistently with `structuredIssues`.
- Focused and broad verification pass, or exact blockers are recorded.
- Latest clean-context review remains `P0/P1 clean`; any remaining P2+ risks are documented with owner/action.

## Implementation Notes Requirements

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record:

- any compatibility fields that now redact rather than echo raw input
- any diagnostic failures intentionally left without `structuredIssues`
- test coverage choices and remaining risks
- whether docs needed updates

## Handoff Requirements

Append a Phase 08 entry to [handoff-log.md](./handoff-log.md) with:

- what changed
- commands run and results
- important SHAs, tags, versions, and paths
- decisions or assumptions the next agent must preserve or re-check
- blockers or risks
- next recommended command or PR summary
