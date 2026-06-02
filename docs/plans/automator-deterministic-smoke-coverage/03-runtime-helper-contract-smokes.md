# Phase 03 - Runtime Helper Contract Smokes

## Clean Context Start

Before doing this phase, read [README.md](./README.md), this phase file, [TODO/phase-03.md](./TODO/phase-03.md), [gate-map.md](./gate-map.md), [implementation-notes.md](./implementation-notes.md), and relevant earlier entries in [handoff-log.md](./handoff-log.md).

Do not read later phase files or later TODO files as acceptance criteria for this phase.

## Goal

Add fast deterministic contract smokes for the helper layer that the automator relies on during live orchestration: parser subprocess, monitor JSON, runner lifecycle, build-command safety flags, state-update failures, runtime policy snapshots, and success verifiers.

This phase is release-blocking. Higher-level lifecycle smokes must not hide helper drift behind broad success output; they should depend on helper JSON contracts that are already proven here.

## Inputs

- [skills/bmad-story-automator/src/story_automator/commands/orchestrator_parse.py](../../../skills/bmad-story-automator/src/story_automator/commands/orchestrator_parse.py)
- [skills/bmad-story-automator/src/story_automator/commands/tmux.py](../../../skills/bmad-story-automator/src/story_automator/commands/tmux.py)
- [skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py](../../../skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py)
- [skills/bmad-story-automator/src/story_automator/core/success_verifiers.py](../../../skills/bmad-story-automator/src/story_automator/core/success_verifiers.py)
- [skills/bmad-story-automator/src/story_automator/core/state_validation.py](../../../skills/bmad-story-automator/src/story_automator/core/state_validation.py)
- [skills/bmad-story-automator/src/story_automator/core/runtime_policy.py](../../../skills/bmad-story-automator/src/story_automator/core/runtime_policy.py)
- [skills/bmad-story-automator/data/orchestration-policy.json](../../../skills/bmad-story-automator/data/orchestration-policy.json)

## Implementation Steps

1. Add a fast `smoke:contracts` runner or equivalent Python/unit-test gate.
2. Exercise `orchestrator-helper parse-output` with a fake `claude` on `PATH` and a parser matrix covering: success JSON, missing/empty output file, missing `--state-file` value, invalid runtime policy, unknown step contract, parse-contract load failure, subprocess timeout, subprocess nonzero, no JSON object, JSON decode failure, and schema-invalid JSON. Assert exit code plus JSON `status`, `reason`, and `structuredIssues` where present.
3. Exercise `monitor-session --json` terminal states and diagnostics covering: `not_found`, `timeout`, `completed`, `incomplete`, `crashed`, `stuck`, completed-but-unverified output, invalid option handling, and invalid persisted session-state diagnostics. Assert `final_state`, `exit_reason`, `output_verified`, and `structuredIssues` shape rather than relying on exit code.
4. Exercise `SA_TMUX_RUNTIME=runner` success and crash paths through `tmux-wrapper spawn`.
5. Assert runner edge states where deterministic: `spawn_error`, interrupted output/state, and launch-never-succeeded/stuck mapping.
6. Assert `build-cmd` launch branches: default Codex safety flags, `AI_COMMAND` override behavior, non-Codex `--agent claude`, quoted `--model`, unknown step, invalid state file, and invalid/missing state policy.
7. Assert invalid `state-update` transitions and malformed `--set` fail without mutating the state file.
8. Assert success verifier happy and failure paths: missing/duplicate create artifacts, incomplete review, story-file fallback, epic incomplete, source mismatch diagnostics, and `sprint_status_not_updated` notes where story file says done but sprint status does not.
9. Assert marker path and runtime-root resolution helpers for `.agents`, `.codex`, and `.claude` layouts so higher-level smokes do not hard-code `.claude`.
10. Assert status/source-of-truth helper behavior for story-file status, sprint-status status, and mismatch surfacing.
11. Assert runtime policy snapshot creation at state-doc build time, state/reference binding to the snapshot path/hash, and later helper reads from the pinned snapshot rather than mutable source policy.
12. Assert runtime policy snapshot drift or missing snapshots fail closed.
13. Keep this runner local and fast enough for `npm run verify`; prefer temp fixtures, fake subprocesses, and `SA_TMUX_RUNTIME=runner` over live tmux/provider behavior.
14. Update [gate-map.md](./gate-map.md) with named rows or stable coverage IDs for every helper contract family and edge matrix, not a single generic helper row.

## Verification

- Run the new `smoke:contracts` command.
- Run `npm run test:python`.
- Run `npm run test:cli`.
- Run `git diff --check`.

## Exit Criteria

- Parser, monitor, runner, build-command, state-update, marker/root resolution, status/source-of-truth helpers, runtime-policy snapshot creation/failure, and success-verifier contracts are tested without live LLM dependence.
- Gate-map rows are split by helper contract family so future implementation cannot hide missing edge matrices behind one broad gate.
- Contract failures produce structured diagnostics where the code claims they should.
- `smoke:contracts` is ready to be wired into the future default `npm run verify`.
- Phase 03 handoff entry appended.

## Implementation Notes Requirements

Record any helper behavior that differs from docs, especially exit-code versus JSON-contract behavior, in [implementation-notes.md](./implementation-notes.md).

## Handoff Requirements

Append a Phase 03 entry to [handoff-log.md](./handoff-log.md) with commands run, fake parser setup, runner runtime settings, failure classes tested, and next recommended command.
