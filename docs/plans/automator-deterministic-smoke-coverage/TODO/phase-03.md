# Phase 03 TODO - Runtime Helper Contract Smokes

## Scope

Use this checklist only for Phase 03. Do not use later phase TODO files as acceptance criteria.

## Checklist

- [ ] Read [README.md](../README.md), [03-runtime-helper-contract-smokes.md](../03-runtime-helper-contract-smokes.md), this TODO file, [gate-map.md](../gate-map.md), and relevant earlier entries in [handoff-log.md](../handoff-log.md).
- [ ] Keep [implementation-notes.md](../implementation-notes.md) current while implementing.
- [ ] Add deterministic parse-output success and fail-closed matrix checks.
- [ ] Add monitor-session terminal state and diagnostics matrix checks.
- [ ] Add runner lifecycle and edge-state checks.
- [ ] Add build-cmd branch, safety flag, model, override, and negative checks.
- [ ] Add state-update, runtime-policy snapshot creation/failure, and success-verifier edge checks.
- [ ] Add marker/root resolution helper checks for `.agents`, `.codex`, and `.claude`; prove smokes do not hard-code `.claude`.
- [ ] Add status/source-of-truth helper checks for story-file status, sprint-status status, mismatch diagnostics, story-file fallback, and `sprint_status_not_updated`.
- [ ] Keep `smoke:contracts` local/fast with fake subprocesses and `SA_TMUX_RUNTIME=runner` so it can run in default `npm run verify`.
- [ ] Update [gate-map.md](../gate-map.md) with named rows or stable IDs for each Phase 03 helper contract family.
- [ ] Run the phase verification checks.
- [ ] Append the Phase 03 handoff entry before ending.
