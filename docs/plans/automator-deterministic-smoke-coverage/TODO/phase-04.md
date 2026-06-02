# Phase 04 TODO - Create Dev Resume Validate Edit Coverage

## Scope

Use this checklist only for Phase 04. Do not use later phase TODO files as acceptance criteria.

## Checklist

- [x] Read [README.md](../README.md), [04-create-dev-resume-validate-edit-coverage.md](../04-create-dev-resume-validate-edit-coverage.md), this TODO file, [gate-map.md](../gate-map.md), and relevant earlier entries in [handoff-log.md](../handoff-log.md).
- [x] Keep [implementation-notes.md](../implementation-notes.md) current while implementing.
- [x] Add create startup guard checks for stop-hook states, existing-state detection, sprint-status present, and sprint-status missing precondition.
- [x] Prefer temp BMAD-style fixtures for `smoke:modes`; keep prepared `.smoke/gunz` mode checks explicit unless Phase 06 promotes them.
- [x] Extend create/dev smoke coverage for preflight breadth and agent config variants.
- [x] Add resume state discovery, sprint comparison, menu branch, and route checks.
- [x] Add marker lifecycle checks.
- [x] Resolve marker path dynamically through helper output; do not hard-code `.claude`.
- [x] Assert direct state/artifact fields: frontmatter, status, current story/step, agents/complexity files, policy snapshot path/hash, progress rows, action log deltas, reports, state docs, marker JSON, `.gitignore`, and selected artifacts.
- [x] Add source-of-truth mismatch cases for story-file status versus `sprint-status.yaml`; surface mismatches instead of accepting marker absence or exit status as completion proof.
- [x] Label fixture writes to story files or `sprint-status.yaml` as simulated child workflow output.
- [x] Add validate mode helper and report checks.
- [x] Add edit mode helper, menu branch, save/discard/edit-more, and route checks.
- [x] Update [gate-map.md](../gate-map.md) for Phase 04 gates.
- [x] Run the phase verification checks.
- [x] Append the Phase 04 handoff entry before ending.
