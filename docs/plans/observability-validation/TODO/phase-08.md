# Phase 08 TODO - Diagnostic Redaction Completion

## Scope

Use this checklist only for Phase 08. Do not use later phase TODO files as acceptance criteria.

## Checklist

- [ ] Read [README.md](../README.md), [08-diagnostic-redaction-completion.md](../08-diagnostic-redaction-completion.md), this TODO file, [implementation-notes.md](../implementation-notes.md), and relevant earlier entries in [handoff-log.md](../handoff-log.md).
- [ ] Review the 2026-05-22 Phase 08 planning note and P2 findings.
- [ ] Add additive `structuredIssues` to diagnostic-worthy `validate-story-creation` failures while preserving legacy fields.
- [ ] Redact invalid `state-update` legacy fields that can echo raw secret-like values or absolute paths.
- [ ] Redact `verifier_exception_payload()` legacy `error` text.
- [ ] Add focused regression tests for the three findings.
- [ ] Update docs only if visible output semantics need explanation.
- [ ] Update [gate-map.md](../gate-map.md) if gate commands or signals change.
- [ ] Run the Phase 08 focused verification checks.
- [ ] Run broad verification or record exact blockers.
- [ ] Keep [implementation-notes.md](../implementation-notes.md) current while implementing.
- [ ] Append the Phase 08 handoff entry before ending.
