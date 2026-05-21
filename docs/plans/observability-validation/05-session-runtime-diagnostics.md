# Phase 05 - Session Runtime Diagnostics

## Clean Context Start

Before doing this phase, read [README.md](./README.md), [TODO.md](./TODO.md), [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), and prior phase handoff entries. Treat the handoff log as next-agent continuity context. Treat implementation notes as the user-facing record of decisions and tradeoffs.

## Goal

Improve persisted tmux/session-state visibility without changing the session persistence format or breaking existing runtime callers.

## Inputs

- `skills/bmad-story-automator/src/story_automator/core/diagnostics.py`
- `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py`
- `skills/bmad-story-automator/src/story_automator/commands/tmux.py`
- `skills/bmad-story-automator/src/story_automator/adapters/tmux.py`
- `tests/test_tmux_runtime.py`
- `tests/test_success_verifiers.py`
- `skills/bmad-story-automator/data/crash-recovery.md`
- `docs/troubleshooting.md`

## Implementation Steps

1. Keep legacy `load_session_state()` behavior where compatibility requires returning `{}`.
2. Add a diagnostic-aware session-state loader, either in `core/session_state.py` or a focused section of `core/tmux_runtime.py`.
3. Define a typed result:
   ```python
   @dataclass(frozen=True)
   class SessionStateLoadResult:
       ok: bool
       state: dict[str, object]
       issue: DiagnosticIssue | None
       exists: bool
   ```
4. Distinguish diagnostics:
   - missing file: `session_state.missing`
   - unreadable file: `session_state.unreadable`
   - invalid JSON: `session_state.invalid_json`
   - non-object JSON: `session_state.invalid_type`
   - unexpected schema version: warning unless command requires runner state
5. Surface `structuredIssues` in `monitor-session --json` only when malformed/stale session state affects the result.
6. Preserve CSV commands exactly:
   - `heartbeat-check`
   - `tmux-status-check`
   - `codex-status-check`
7. Preserve internal `session_status(...)` return keys unless a phase explicitly documents an additive field.
8. Update recovery/troubleshooting docs.

## Verification

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_tmux_runtime
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_success_verifiers
```

## Exit Criteria

- Missing, invalid, unreadable, and non-object session state can be diagnosed.
- Legacy status paths retain existing behavior where required.
- JSON monitor output gains diagnostics only when useful.
- CSV outputs remain exact.

## Implementation Notes Requirements

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record where silent `{}` behavior is preserved and where diagnostic-aware loading is used.

## Handoff Requirements

Append a Phase 05 entry to [handoff-log.md](./handoff-log.md) with files changed, tests run, compatibility risks, blockers, and the next recommended command for Phase 06.
