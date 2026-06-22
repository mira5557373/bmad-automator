## 260622 - [FULL] Operability batch (B1+B2+B3)

### Summary
Three small, surgical operability fixes that harden gate-lifecycle
observability without expanding the frozen public gate-surface or
adding any new Python deps:

- **B1 — legacy-marker PID-reuse hardening.** `_recover_from_crash_locked`
  now consults `marker.started_at` against the live PID's `create_time()`
  when `start_time` is absent (legacy markers from before the J-03 fix).
  Uses a two-sided bound `[started_at - 24h, started_at + 1s]` so a
  long-lived orchestrator process is correctly classified as live while
  a PID seen alive after the marker (or >24h before it) is recovered.
- **B2 — lock-holder observability.** `get_gate_lock(...)` timeouts now
  surface a new `GateLockTimeoutError(filelock.Timeout)` carrying the
  holder PID + `started_at` + hostname. Wraps all three call sites:
  `gate_orchestrator.recover_from_crash`, `gate_orchestrator.run_production_gate`,
  and `system_gate.run_system_gate`. Existing `except filelock.Timeout`
  callers still match by inheritance.
- **B3 — opt-in pre-commit gate.** New `.githooks/pre-commit` runs the
  full unittest suite + ruff + M11 vocabulary gate before every commit.
  Opt-in via `scripts/install-hooks.sh`; recoverable via
  `scripts/uninstall-hooks.sh`. Honors both `git commit --no-verify`
  and `BMAD_SKIP_PRECOMMIT=1` escape hatches. Probes for `python3 / python / py`
  and a venv-local `ruff` to keep Windows git-bash + WSL paths working.

### Added
- `core/gate_lock_observability.py` — new sibling module hosting
  `GateLockTimeoutError`, `_describe_lock_holder`, `_handle_gate_lock_timeout`.
- `gate_orchestrator.ISO_TRUNCATION_S` and
  `gate_orchestrator.MAX_ORCHESTRATOR_UPTIME_S` module constants for the
  B1 v2 rule.
- `.githooks/pre-commit`, `scripts/install-hooks.sh`,
  `scripts/uninstall-hooks.sh`.
- "Pre-commit hook" section in `CONTRIBUTING.md`.
- Frozen-surface declarations for `GateLockTimeoutError` and a soft-limit
  waiver line for `core/gate_orchestrator.py` (746 → 834 LOC).
- Tests: `tests/test_bugfix_L1_pid_reuse.py` (9 tests),
  `tests/test_lock_holder_observability.py` (5 tests),
  `tests/test_pre_commit_hook.py` (5 tests). 19 new tests total.

### Changed
- `_recover_from_crash_locked` liveness branch extended with the B1 v2
  rule (only fires when `start_time` is absent and `started_at` is
  present; preserves the post-J-03 fast path and the foreign-host
  short-circuit).
- All three `get_gate_lock` call sites now wrap acquisition in a
  `try/except Timeout` that converts the bare `filelock.Timeout` into
  a `GateLockTimeoutError` via `_handle_gate_lock_timeout`. Lock release
  remains in a `try/finally`.

### Files
- skills/bmad-story-automator/src/story_automator/core/gate_lock_observability.py
- skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py
- skills/bmad-story-automator/src/story_automator/core/system_gate.py
- docs/spec/frozen-gate-surface.md
- .githooks/pre-commit
- scripts/install-hooks.sh
- scripts/uninstall-hooks.sh
- CONTRIBUTING.md
- tests/test_bugfix_L1_pid_reuse.py
- tests/test_lock_holder_observability.py
- tests/test_pre_commit_hook.py

### QA Notes
- Full unittest suite: 4105 tests, 2 skipped, 0 failing (baseline+19).
- Audit-floor invariants: 24/24 green.
- `ruff check skills/ tests/`: clean.
- No new Python deps; `filelock.Timeout` and `psutil` already imported.
- `core/telemetry_events.py` untouched (M01 ownership preserved).
- No historical changelog entry mutated.
- The B2 helpers `_describe_lock_holder` and `_handle_gate_lock_timeout`
  are leading-underscore private (NOT frozen surface); only
  `GateLockTimeoutError` is declared in `docs/spec/frozen-gate-surface.md`.
- B1 v2 rule constants exposed for testability:
  `ISO_TRUNCATION_S = 1.0`, `MAX_ORCHESTRATOR_UPTIME_S = 86400.0`.
