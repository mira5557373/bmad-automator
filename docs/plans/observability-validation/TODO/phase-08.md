# Phase 08 TODO - Diagnostic Redaction Completion

## Scope

Use this checklist only for Phase 08. Do not use later phase TODO files as acceptance criteria.

## Checklist

- [x] Read [README.md](../README.md), [08-diagnostic-redaction-completion.md](../08-diagnostic-redaction-completion.md), this TODO file, [implementation-notes.md](../implementation-notes.md), and relevant earlier entries in [handoff-log.md](../handoff-log.md).
- [x] Review the 2026-05-22 Phase 08 planning note and P2 findings.
- [x] Add additive `structuredIssues` to diagnostic-worthy `validate-story-creation` failures while preserving legacy fields.
- [x] Redact invalid `state-update` legacy fields that can echo raw secret-like values or absolute paths.
- [x] Redact `verifier_exception_payload()` legacy `error` text.
- [x] Add focused regression tests for the three findings.
- [x] Update docs only if visible output semantics need explanation.
- [x] Update [gate-map.md](../gate-map.md) if gate commands or signals change.
- [x] Run the Phase 08 focused verification checks.
- [x] Run broad verification or record exact blockers.
- [x] Keep [implementation-notes.md](../implementation-notes.md) current while implementing.
- [x] Append the Phase 08 handoff entry before ending.
