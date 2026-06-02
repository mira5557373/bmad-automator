# Phase 03 TODO - Runtime Helper Contract Smokes

## Scope

Use this checklist only for Phase 03. Do not use later phase TODO files as acceptance criteria.

## Checklist

- [x] Read [README.md](../README.md), [03-runtime-helper-contract-smokes.md](../03-runtime-helper-contract-smokes.md), this TODO file, [gate-map.md](../gate-map.md), and relevant earlier entries in [handoff-log.md](../handoff-log.md).
- [x] Keep [implementation-notes.md](../implementation-notes.md) current while implementing.
- [x] Add deterministic parse-output success and fail-closed matrix checks.
- [x] Add monitor-session terminal state and diagnostics matrix checks.
- [x] Add runner lifecycle and edge-state checks.
- [x] Add build-cmd branch, safety flag, model, override, and negative checks.
- [x] Add state-update, runtime-policy snapshot creation/failure, and success-verifier edge checks.
- [x] Add marker/root resolution helper checks for `.agents`, `.codex`, and `.claude`; prove smokes do not hard-code `.claude`.
- [x] Add status/source-of-truth helper checks for story-file status, sprint-status status, mismatch diagnostics, story-file fallback, and `sprint_status_not_updated`.
- [x] Keep `smoke:contracts` local/fast with fake subprocesses and `SA_TMUX_RUNTIME=runner` so it can run in default `npm run verify`.
- [x] Update [gate-map.md](../gate-map.md) with named rows or stable IDs for each Phase 03 helper contract family.
- [x] Run the phase verification checks.
- [x] Append the Phase 03 handoff entry before ending.
