## 260622 - [FULL] G7 sprint-phase dual-store unification

### Summary
G7 ships the unified read/write surface for M48's sprint-status /
Phase dual store: one read function returning a deterministic
`(sprint_status, phase_value, needs_repair)` triple, one write function
that atomically updates both stores under a per-project filelock, and a
helper exposing the lock for advanced callers. Conflict resolution is
last-write-wins by `st_mtime_ns` with a same-volume precondition and a
terminal-phase tie-break; legacy single-store projects auto-upgrade on
first read. The first-ever sprint-status writer also ships here as a
private text-only regex mutation helper (no YAML re-serialisation, so
`import yaml` stays out of the deps per the CLAUDE.md hard guardrail).

### Added
- `core/integration/unified_state.py` — public surface:
  - `read_unified_state(project_root, story_key, *, observe_only=False, read_lock_timeout=2.0)`
  - `write_unified_state(project_root, story_key, sprint_status, phase, *, lock_timeout=10.0)`
  - `unified_state_lock(project_root)`
  - `UnifiedStateError` (base)
  - `UnifiedStateFileMissingError` — sprint-status / phase store file absent
  - `UnifiedStateRowMissingError` — file present but row absent
- `core/integration/_unified_state_repair.py` — private repair-branch sibling
  hosting LWW resolution, canonical-key reconciliation, and the stat-twice
  escalation primitives (split per the spec's §5 pre-authorisation to keep
  the public module comfortably under the 500-LOC soft limit).
- `tests/test_unified_state.py` — 21 new tests covering happy-path reads,
  legacy migration, LWW resolution in both directions, mtime-tie tie-break,
  inconsistent-pair writes, concurrent writers, lock-timeout, observe_only,
  slug-key reconciliation, read-repair self-cancellation guard, and the
  M48 frozen-surface compatibility check.
- `tests/test_audit_regression.py::UnifiedStateWriteIsolationInvariant` —
  audit-floor invariant pinning that only `unified_state.py` may call
  `write_phase(...)` AND `write_atomic(...)` on a sprint-status path
  without also acquiring `unified_state_lock(...)`. Ships with a
  positive-failure synthetic violator so the invariant is not vacuously
  true.

### Changed
- `core/integration/__init__.py` — re-exports the six new public symbols.
- `docs/spec/frozen-gate-surface.md` — appended a new
  `### core/integration/unified_state.py` section enumerating all six
  public symbols + the six behavioural invariants (read-order = reverse
  of write-order; LWW with same-volume precondition; mtime-tie ->
  terminal phase wins; observe_only never writes; text-only sprint-status
  writer; self-cancellation guard on the LWW projection).

### Fixed
- Drift hazard: external integrators previously had to pick between
  `sprint_status_get(...)` and `compute_dual_state(...)` to read state,
  and there was no atomic two-store writer at all. The two paths could
  drift; G7 closes the gap by routing both reads and writes through one
  filelock-serialised function.

### Files
- `skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py` (new, 408 LOC)
- `skills/bmad-story-automator/src/story_automator/core/integration/_unified_state_repair.py` (new, 221 LOC)
- `skills/bmad-story-automator/src/story_automator/core/integration/__init__.py` (modified, +6 LOC)
- `tests/test_unified_state.py` (new, 21 tests)
- `tests/test_audit_regression.py` (modified, +1 invariant class / +2 tests)
- `docs/spec/frozen-gate-surface.md` (modified, +16 lines)
- `docs/changelog/2026-06-22-g7-unified-state.md` (new — this file)

### QA Notes
- Full suite: 4105 -> 4128 passing (+23), 2 skipped.
- Audit-floor invariants: 24 -> 26 (one new class with the explicit
  positive-failure test required by gap D11).
- `python -m ruff check skills tests`: exits 0.
- `core/integration/sprint_phase_map.py` (M48 frozen surface) unchanged.
- `core/telemetry_events.py` (M01 owner) unchanged.
- `unified_state.py` is 408 LOC (under the 500-LOC soft limit thanks to
  the pre-authorised `_unified_state_repair.py` split).
- No new Python imports outside `{stdlib, filelock, psutil, story_automator}`.
- G7 emits no new telemetry (event types live in M01).
