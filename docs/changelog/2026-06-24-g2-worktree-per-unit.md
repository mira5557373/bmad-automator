## 260624 - [FULL] G2 worktree-per-unit isolation

### Summary
Closes the half-built isolation loop on the collector framework by
introducing an opt-in `per_unit` isolation mode that runs each
collector inside its own fresh `git worktree --detach @SHA` checkout,
bounded by a `ThreadPoolExecutor`. Defaults preserve byte-identical
behavior at four wiring points (`run_production_gate`,
`run_system_gate`, `_run_collectors`, `run_gate_collectors`); the
new `isolation_mode="shared"` default routes through the existing
inline path unchanged. Per-unit dispatch defends against per-collector
TOCTOU, enables bounded parallelism, and isolates crash blast-radius
to a single worker — at the cost of CATEGORY-VERDICT (not byte)
equivalence between modes.

### Added
- `core/collector_isolation.py` — `IsolationMode`,
  `DEFAULT_MAX_WORKERS=4`, `MAX_PARALLEL_CEILING=16`,
  `ESTIMATED_PER_WORKER_BYTES=256*1024*1024`,
  `ADD_TIMEOUT_PER_UNIT_S=90`, `run_collectors_per_unit`,
  `_validate_isolation_kwargs` (TypeError on non-int max_workers
  including bool subclass; ValueError on unknown isolation_mode).
  Worker boundary catches `BaseException` and reifies as
  `_crash_outcome`; `KeyboardInterrupt` drains the queue via
  `pool.shutdown(wait=False, cancel_futures=True)` and re-raises
  AFTER outcome collection. `AuditLockTimeout` is retried once
  before reifying as `_audit_timeout_outcome`. RAM-aware clamp via
  `psutil.virtual_memory()` with cpu/ram ceilings and graceful
  degradation when psutil raises.
- `tests/test_collector_isolation.py` — 22+ tests covering
  AC-V-01..V-03 (early validation), AC-I-01..I-20 (per-unit
  behavior, sort order, BaseException semantics, KeyboardInterrupt,
  thread-name save+restore, sanitization, clamp formula).
- `tests/test_gate_orchestrator_g2_wiring.py` — 10+ tests covering
  AC-G-01..G-09 end-to-end including system-gate parity.
- `WorktreePerUnitIsolationInvariant` in `tests/test_audit_regression.py`
  with FOUR sub-tests: process-global-mutation rejection (`os.chdir`,
  `os.environ` mutations, `signal.signal`, `get_gate_lock`),
  refactor-tolerant per_unit-dispatch exemption, MEANINGFUL
  positive-failure proof (residual-strip + synthetic call injection),
  and default-isolation-mode pinning across four signature sites.

### Changed
- `core/collector_runner.run_gate_collectors(...)` gains two new
  optional kwargs: `isolation_mode: Literal["shared","per_unit"] = "shared"`
  + `max_workers: int = 4`. Early validation runs BEFORE
  `assert_host_context`; `shared` path is BYTE-IDENTICAL to pre-G2.
- `core/gate_orchestrator.run_production_gate(...)` + the
  `_run_collectors` wrapper gain the same two kwargs (eighth + ninth
  additive kwargs on `run_production_gate`).
- `core/system_gate.run_system_gate(...)` gains the same two kwargs,
  threaded through to `run_gate_collectors`.
- `core/collector_checkout.create_collector_checkout(...)` gains
  `name_hint: str = ""` (sanitize-FIRST-truncate-SECOND-LAST-32-chars)
  + `add_timeout: int | None = None` (default `_GIT_TIMEOUT=30`,
  byte-identical). Bounded retry on transient git lock errors
  (`could not lock`, `index.lock`, `config.lock`, etc.) — up to 3
  attempts with 50 ms backoff.
- `core/worktree_recovery.recover_orphan_worktrees(...)` gains
  `per_unit_window_s: float = 0.0` safety-margin kwarg; default
  preserves byte-identical behavior.

### Files
- skills/bmad-story-automator/src/story_automator/core/collector_isolation.py
- skills/bmad-story-automator/src/story_automator/core/collector_runner.py
- skills/bmad-story-automator/src/story_automator/core/collector_checkout.py
- skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py
- skills/bmad-story-automator/src/story_automator/core/system_gate.py
- skills/bmad-story-automator/src/story_automator/core/worktree_recovery.py
- skills/bmad-story-automator/tests/test_collector_isolation.py
- skills/bmad-story-automator/tests/test_gate_orchestrator_g2_wiring.py
- skills/bmad-story-automator/tests/test_collector_checkout.py
- skills/bmad-story-automator/tests/test_collector_runner.py
- skills/bmad-story-automator/tests/test_system_gate.py
- skills/bmad-story-automator/tests/test_worktree_recovery.py
- tests/test_audit_regression.py
- docs/changelog/2026-06-24-g2-worktree-per-unit.md
- docs/spec/frozen-gate-surface.md
- CLAUDE.md

### QA Notes
- No new Python deps; stdlib `concurrent.futures`, `threading`,
  `tempfile`, `os`, `shutil`, `subprocess`, `re` + already-imported
  `psutil`.
- `core/telemetry_events.py` untouched (M01 ownership preserved).
- Audit-floor invariants: 10 -> 11 (one new class
  `WorktreePerUnitIsolationInvariant` with meaningful
  two-direction positive-failure proof).
- `collector_isolation.py` is ~470 LOC (under 500-LOC soft limit);
  may sibling-split into `collector_isolation_workers.py` if a
  future change pushes past the threshold.
- Default `isolation_mode="shared"` + `max_workers=4` preserves
  byte-identical behavior at every wiring point; existing
  ~4,471-test baseline stays green.
- Mode-mode equivalence is CATEGORY-VERDICT-LEVEL: the `categories`
  shape, per-category verdicts, and `overall` match between modes
  for deterministic fixtures. `duration_ms`, `evidence_merkle_root`,
  `evidence_bundle_hash`, `cost_total_usd` are EXPECTED TO DIFFER
  between `shared` and `per_unit` by construction (per-unit
  parallel + per-collector checkout has different wall-clock and
  different cost-attribution distribution).
- Lock-ordering invariant: `core/collector_isolation.py` MUST NOT
  acquire ANY `_bmad/*.lock` — pinned by sub-test 1 of
  `WorktreePerUnitIsolationInvariant`.
- KeyboardInterrupt semantics: main thread receives SIGINT; workers
  do not. Pool drain is `wait=False, cancel_futures=True`; in-flight
  subprocesses complete to their per-category timeout (worst case
  `max(profile.timeouts.values())` = 600s for `performance`).
- `worktree_recovery.recover_orphan_worktrees` already reaps
  `/tmp/sa-collector-*` orphans; per-unit's higher orphan-rate is
  handled by the existing janitor + new `per_unit_window_s` safety
  margin for operator-driven post-crash reaping.
- No historical changelog entry mutated.
