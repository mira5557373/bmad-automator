# Phase 06 TODO - Gate Integration And Readiness Review

## Scope

Use this checklist only for Phase 06. Do not use later phase TODO files as acceptance criteria.

## Checklist

- [ ] Read [README.md](../README.md), [06-gate-integration-and-readiness-review.md](../06-gate-integration-and-readiness-review.md), this TODO file, [gate-map.md](../gate-map.md), and relevant earlier entries in [handoff-log.md](../handoff-log.md).
- [ ] Keep [implementation-notes.md](../implementation-notes.md) current while implementing.
- [ ] Decide default `verify` gates versus heavier explicit smoke gates.
- [ ] Target default `verify`: `test:python`, `version:check`, `pack:assert`, `test:cli`, `smoke:contracts`, `smoke:modes`, and `test:smoke`.
- [ ] Wire selected fast deterministic gates into `verify`.
- [ ] Add or confirm explicit prepared-repo release wrapper, such as `smoke:deterministic-full`, separate from default `verify`.
- [ ] Complete all gate-map fields.
- [ ] Run final verification commands.
- [ ] Run clean-context sub-agent review and triage findings.
- [ ] Append the Phase 06 handoff entry before ending.
