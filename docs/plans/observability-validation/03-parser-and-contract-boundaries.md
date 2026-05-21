# Phase 03 - Parser And Contract Boundaries

## Clean Context Start

Before doing this phase, read [README.md](./README.md), [TODO.md](./TODO.md), [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), and prior phase handoff entries. Treat the handoff log as next-agent continuity context. Treat implementation notes as the user-facing record of decisions and tradeoffs.

## Goal

Make LLM parse failures and verifier contract failures field-specific while keeping existing parse contracts and successful output unchanged.

## Inputs

- `skills/bmad-story-automator/src/story_automator/core/diagnostics.py`
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator_parse.py`
- `skills/bmad-story-automator/src/story_automator/core/success_verifiers.py`
- `skills/bmad-story-automator/src/story_automator/core/review_verify.py`
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py`
- `skills/bmad-story-automator/src/story_automator/commands/tmux.py`
- `skills/bmad-story-automator/src/story_automator/commands/validate_story_creation.py`
- `skills/bmad-story-automator/data/parse/*.json`
- `skills/bmad-story-automator-review/contract.json`
- `tests/test_orchestrator_parse.py`
- `tests/test_success_verifiers.py`

## Implementation Steps

1. Add `skills/bmad-story-automator/src/story_automator/core/parse_contracts.py`.
2. Move parse schema/payload validation out of command code.
3. Replace boolean schema checks with diagnostics for:
   - missing required key
   - wrong nested type
   - invalid enum
   - empty string
   - invalid `path or null`
4. Preserve parse success output exactly as-is. Do not add diagnostics or events to valid parsed payloads.
5. On parse failure, preserve `status: "error"` and legacy `reason`, and add `structuredIssues`.
6. Wrap success verifier contract failures into structured issues at command boundaries where safe.
7. Add or update tests for field paths such as `issues_found.critical`.

## Verification

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_orchestrator_parse tests.test_success_verifiers
```

## Exit Criteria

- Parser boundary reports specific field-level diagnostics.
- Existing parse success payloads are unchanged.
- Legacy failure `reason` values remain available.
- Verifier contract failures expose structured diagnostics where command outputs already carry errors.

## Implementation Notes Requirements

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record any compatibility choice around legacy `reason` values, whether events are returned in failure JSON, and parse schema expressiveness limits.

## Handoff Requirements

Append a Phase 03 entry to [handoff-log.md](./handoff-log.md) with files changed, tests run, schema issue examples, compatibility notes, blockers, and the next recommended command for Phase 04.
