# Phase 01 - Diagnostics Contract

## Clean Context Start

Before doing this phase, read [README.md](./README.md), [TODO.md](./TODO.md), [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), and the Phase 00 handoff. Treat the handoff log as next-agent continuity context. Treat implementation notes as the user-facing record of decisions and tradeoffs.

## Goal

Add reusable diagnostics objects and serialization helpers without changing command behavior.

## Inputs

- `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py`
- `skills/bmad-story-automator/src/story_automator/core/utils.py`
- Existing tests in `tests/`
- Oracle feedback in [implementation-notes.md](./implementation-notes.md)

## Implementation Steps

1. Add `skills/bmad-story-automator/src/story_automator/core/diagnostics.py`.
2. Define `DiagnosticIssue` with first-class fields:
   - `type`
   - `field`
   - `expected`
   - `actual`
   - `message`
   - `recovery`
   - `code`
   - `severity`
   - `source`
3. Define `DiagnosticEvent` for structured observability context, but do not emit standalone event lines to stdout by default.
4. Add serialization helpers:
   - `serialize_issue(issue) -> dict`
   - `serialize_issues(issues) -> list[dict]`
   - `legacy_issue_message(issue) -> str`
   - `issues_from_exception(exc, source, field="")`
5. Add `redact_actual(value)` for long strings, absolute paths, env-like keys, nested dict/list payloads, and other oversized or sensitive values.
6. Add `tests/test_diagnostics.py`.
7. Do not touch command outputs yet.

## Verification

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_diagnostics
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests
```

## Exit Criteria

- Diagnostics serialize to compact JSON-compatible dictionaries.
- Redaction behavior is tested.
- No CLI output shape changes.
- `severity` and `source` are present from day one.

## Implementation Notes Requirements

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record field-name decisions, redaction tradeoffs, event-output decisions, and compatibility constraints.

## Handoff Requirements

Append a Phase 01 entry to [handoff-log.md](./handoff-log.md) with files changed, tests run, exact diagnostics shape, compatibility notes, blockers, and the next recommended command for Phase 02.
