# G7 — Sprint-Phase Dual-Store Unification — Design Spec

> Date: 2026-06-22 · Status: **Draft for implementation** · Milestone: **D (G7 unification)** · Owner branch: `bma-d/integration-all`.
> Topic: collapse the M48 sprint-status / Phase dual-store read+write surface behind a **single source of truth** so external tools cannot drift the two stores under normal operation, and so concurrent writers cannot interleave them.
> Validation provenance: builds on M48 (`core/integration/sprint_phase_map.py`) and the L1/L2 gate-marker filelock work (`.claude/workflows/l1-l2-gate-marker-fix.md`). Surgical addition; no public-symbol renames in M48's frozen surface (`compute_dual_state`, `write_phase`, `validate_dual_store`, `read_phase_store`, `phase_for_sprint_status`, `sprint_status_for_phase`, `is_consistent`, `phase_store_path`, `Phase`, `DualStoreError`, `DualStoreState`, `Inconsistency`, `DualStoreInconsistencyError`, `SPRINT_STATUS_TO_PHASE`, `PHASE_TO_SPRINT_STATUS`, `TERMINAL_PHASES` — all preserved verbatim).

## 1. Goal

Close the three latent dual-store hazards M48 left behind:

1. **No single read API.** Today callers either call `sprint_status_get(...)` (sprint-status only) or `compute_dual_state(...)` (both stores, but the result is a 6-field dataclass with derived/found/consistent flags — verbose for callers that just want "what is this story's current pair?"). External integrators ended up importing one or the other based on convenience, which is exactly how drift creeps in.
2. **No atomic write across both stores.** `write_phase(...)` covers the Phase side; the sprint-status side is mutated by the orchestrator's separate YAML writer. The two writes happen back-to-back but without a shared lock, so a crash between them — or a competing writer touching sprint-status outside the orchestrator — leaves the pair inconsistent.
3. **No legacy upgrade path.** Projects that pre-date M48 have only sprint-status (no `phase-store.yaml`). `compute_dual_state` already *derives* a Phase on read, but never *materializes* the derived value, so the next non-M48 reader still sees an empty phase store.

G7 adds a thin unified-state module that:

- Exposes one **read** function returning a `(sprint_status, phase)` tuple — the simplest possible surface so external tools have no excuse to bypass it.
- Exposes one **write** function that updates both stores under a single shared `filelock` so they cannot diverge during a normal update, and uses **last-write-wins (mtime)** to break any pre-existing conflict at read time.
- **Materializes** the derived Phase on first read when the phase store is empty but sprint-status has a value, so legacy projects upgrade transparently — silently writing the synthesised pair back through the same atomic path the new writer uses.
- Stays a pure addition on top of `sprint_phase_map.py` — no rename, no signature change, no behavioral regression for existing callers.

## 2. Decisions captured

| Decision | Choice |
|---|---|
| New module or extend `sprint_phase_map.py`? | **New module** `core/integration/unified_state.py`. `sprint_phase_map.py` is at ~480 LOC after M48; piling on a writer + reader + lock + migration would crash the 500-LOC soft limit. Sibling module keeps the M48 frozen surface untouched. |
| Public API shape | Two top-level functions: `read_unified_state(project_root, story_key) -> tuple[str, str]` and `write_unified_state(project_root, story_key, sprint_status, phase) -> None`. Tuple, not dataclass — explicit "minimum surface". A third helper `unified_state_lock(project_root)` exposes the underlying `filelock.FileLock` for callers that need to bracket multi-row updates. |
| Conflict resolution | **Last-write-wins via mtime**. If the two stores disagree on read, the source whose backing file has the later `Path.stat().st_mtime_ns` wins; the loser is re-projected from the winner via `phase_for_sprint_status` / `sprint_status_for_phase`, persisted back under lock, and returned. Mtime is sufficient because both files live on the same volume in `_bmad/{automation,output}/`, so no cross-host clock skew matters. |
| Lock granularity | **Per-project**, one lock for both stores. Lock file path: `<implementation_artifacts_dir>/.unified-state.lock`. This mirrors `get_gate_lock`'s pattern (single lock for the entire gate subsystem of one project) and matches `_recover_from_crash_locked`'s `filelock.FileLock` usage. **Timeout**: 10 seconds default for `write_unified_state`; configurable via `write_unified_state(..., lock_timeout=…)`. Holder identity is *not* recorded (lock-holder observability lives in B2, not G7). |
| New dep? | **No.** `filelock` already imported by `gate_orchestrator.py` and is in the CLAUDE.md guardrail allow-list. `psutil` not needed (no liveness check inside G7). |
| Touch sprint-status YAML schema? | **No.** Writer mutates one row of the existing YAML by rewriting the full document — no new fields, no reorder. Schema validator (`core/sprint_schema.py`) is exercised by tests to confirm round-trip parity. |
| Touch `telemetry_events.py`? | **No** — M01 owns that file; CLAUDE.md hard guardrail. G7 emits no new telemetry. (If drift is repaired on read, the existing `core/gate_audit.GateProfileDrift` is not the right shape; we keep G7 silent and rely on the inconsistency being self-correcting. A future milestone may emit `UnifiedStateRepair` rides-`UnknownEvent`-forward-compat, but not in G7.) |
| Migration policy | **Auto-upgrade on first read.** When `read_unified_state` sees an empty phase-store but a valid sprint-status row, it computes the derived phase via `phase_for_sprint_status`, writes the pair atomically through `write_unified_state` under the same lock, and returns the projected pair. No CLI subcommand — invisibly self-heals. |
| Unknown sprint-status string on read | Conservative: return `(raw_status, Phase.PENDING)` and **do not** auto-write — surfacing the misspelling lets the operator fix it instead of silently normalizing. (This matches `compute_dual_state`'s existing fail-soft behavior on unknown statuses.) |
| What about `sprint_status_get`'s "story missing" path? | Treat missing-row as a hard read failure: `read_unified_state` raises `UnifiedStateError`. Auto-creating a row would tread on the orchestrator's state machine — out of scope. Callers can probe with `compute_dual_state(...).found` first. |
| Concurrent writers | The lock serializes writers — but readers do **not** take the lock by default (read-mostly contention model). Readers see the most-recent-fully-written pair because both writes happen inside `write_atomic`'s rename, and the two atomic renames happen in **deterministic order under the lock**: phase store first, sprint-status second. This means a reader observing sprint-status post-rename is guaranteed to also see the matching phase store. |
| Touch existing call sites | **No M48 call site changes in G7.** `sprint_phase_map.write_phase(...)` continues to work unchanged for callers that only need the phase side. A follow-up milestone may migrate orchestrator call sites onto `write_unified_state` once external integrations have been audited. |

## 3. Architecture

```
            ┌────────────────────────────────────────────────┐
            │  unified_state.py  (NEW, ~250 LOC)             │
            │                                                │
   reader──>│  read_unified_state(root, story)               │
            │     ├─ filelock-free fast path:                │
            │     │    sprint = sprint_status_get(...)       │
            │     │    phase  = read_phase_store(...).get()  │
            │     ├─ both present + consistent → return      │
            │     ├─ both present + conflict → resolve_lww() │
            │     │    └─ writes loser back under lock,      │
            │     │       returns winner's pair              │
            │     └─ phase missing + sprint present →        │
            │          derive → write under lock → return    │
            │                                                │
   writer──>│  write_unified_state(root, story, st, ph,      │
            │                      lock_timeout=10.0)        │
            │     ├─ acquire FileLock(.unified-state.lock)   │
            │     ├─ validate (sprint_status, phase) pair    │
            │     ├─ atomic-write phase store first          │
            │     ├─ atomic-write sprint-status YAML second  │
            │     └─ release lock                            │
            │                                                │
   helper──>│  unified_state_lock(root) -> FileLock          │
            │     (advanced callers; e.g., multi-row update) │
            └────────────────────────────────────────────────┘
                              │
                              ▼
       sprint_phase_map.py  (M48 — UNCHANGED, frozen surface)
       core/sprint.py       (sprint_status_get — read-only)
       core/utils.py        (write_atomic — atomic rename)
       filelock.FileLock    (already imported elsewhere)
```

Key properties:

- **Read path stays lock-free in the common case** (both stores agree). Only the *repair* paths (conflict, missing phase) take the lock — and only briefly, to write the projection back.
- **Write path holds one lock for two writes**, guaranteed in-order, both atomic. A crash between writes still leaves a recoverable state because the next reader will see "phase store advanced, sprint-status not yet" → conflict → LWW reads phase as newer → re-projects sprint-status → repair.
- **No new lock file naming collisions**: `.unified-state.lock` is distinct from `gate.lock` (gate orchestrator).

## 4. Schemas (compact)

- **`read_unified_state(project_root, story_key)` return**: `tuple[str, str]` — `(sprint_status, phase_value)`. Both are strings (sprint-status raw, phase as the `Phase.value` kebab-case). Tuple unpacking is the intended call style: `status, phase = read_unified_state(root, key)`.
- **`write_unified_state(project_root, story_key, sprint_status, phase, *, lock_timeout=10.0)`**: validates that (status, phase) is consistent via `is_consistent(...)`; raises `UnifiedStateError` if not (no silent normalization on write — writers must commit to a coherent pair). `phase` may be passed as `Phase` enum or kebab-case string.
- **`UnifiedStateError(ValueError)`**: raised on (a) missing story row, (b) unknown sprint-status string at write time, (c) unknown phase at write time, (d) `(status, phase)` pair fails `is_consistent`, (e) `filelock.Timeout` (re-raised as `UnifiedStateError(timeout=…)` so callers do not need to import `filelock`). Subclass of `ValueError` for symmetry with M48's `DualStoreError`. **Not** a subclass of `DualStoreError` — they sit side-by-side; G7 is a new layer on top of M48, not a fork of it.
- **Lock file path**: `<implementation_artifacts_dir>/.unified-state.lock`. Created on first `write_unified_state`; never deleted (cheap, OS will GC if directory is wiped).
- **Migration trigger**: legacy state = `read_phase_store(root)` returns `{}` **and** `sprint_status_file(root)` exists with at least one row. On first read of a story whose sprint-status row is present, derive and persist via the standard write path.

## 5. Implementation surface — files

| File | New / Modified | LOC delta | Notes |
|---|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py` | **New** | ~250 | Module docstring first, then `from __future__ import annotations`, then imports. Public API: `read_unified_state`, `write_unified_state`, `unified_state_lock`, `UnifiedStateError`. Helpers `_resolve_lww`, `_atomic_write_sprint_status_row`, `_lock_path` private. |
| `skills/bmad-story-automator/src/story_automator/core/integration/sprint_phase_map.py` | **Not modified** | 0 | Frozen surface preserved exactly. (If a private helper turns out to be needed in `unified_state.py`, we add a *new* private symbol there — never re-export from M48.) |
| `skills/bmad-story-automator/src/story_automator/core/integration/__init__.py` | Modified | +4 | Add `unified_state` to the package's import surface (re-export `read_unified_state`, `write_unified_state`, `UnifiedStateError`). No removals. |
| `tests/test_unified_state.py` | **New** | ~320 | ≥10 tests, see §6.2. |
| `docs/changelog/2026-06-22-g7-unified-state.md` | New | ~25 | `[FULL]` tag — adds capability, no behavior change for existing callers. |

Total LOC delta ≈ +600, of which ~320 is tests. `unified_state.py` lands under the 500-LOC soft limit with substantial headroom; if it grows past 400 LOC during impl, split repair helpers into `_unified_state_repair.py` (sibling module, private).

## 6. Acceptance criteria

### 6.1 Behavioral

**Read path**
- Clean state (sprint-status row + matching phase entry both present, consistent): `read_unified_state(root, key)` returns `(sprint_status, phase_value)` **without** acquiring the lock. Determinism verified by calling twice with no intervening writes and asserting identical results.
- Missing phase entry, sprint-status row present, status is in `SPRINT_STATUS_TO_PHASE`: derive the Phase, persist the pair under lock, return the projected pair. After the read, `read_phase_store(root)` includes the new key.
- Missing phase entry, sprint-status row present, status **unknown** (not in `SPRINT_STATUS_TO_PHASE`): return `(raw_status, "pending")` and do **not** write. `read_phase_store(root)` is unchanged.
- Conflicting on-disk values (e.g., sprint-status says `"in-progress"`, phase store says `done` — both forms valid in isolation, inconsistent with each other): resolve to whichever file has the later `st_mtime_ns`; project from winner; persist loser via `write_unified_state` under lock; return the winner's pair.
- Missing sprint-status row (story not in YAML at all): raise `UnifiedStateError` with a message identifying the story key. **Do not** auto-create the row.

**Write path**
- `write_unified_state(root, key, "in-progress", Phase.DEV_RUNNING)` writes both stores atomically; subsequent `read_unified_state` returns `("in-progress", "dev-running")` without taking the lock.
- `write_unified_state(root, key, "done", Phase.DEV_RUNNING)` (inconsistent pair) raises `UnifiedStateError` *before* touching either file. Both files unchanged on disk.
- Concurrent writers: two threads invoking `write_unified_state` with distinct story keys serialize via the lock; final on-disk state contains both rows in both stores. Verified by spawning 8 threads writing 8 distinct keys and asserting `read_phase_store(...)` returns all 8 entries and `sprint_status_get` resolves each.
- Lock-timeout: forcing a lock contention (hold the lock from another process via `unified_state_lock(root).acquire()`) and calling `write_unified_state(..., lock_timeout=0.1)` raises `UnifiedStateError` whose message contains `"timeout"`. Original `filelock.Timeout` not surfaced.
- Phase accepted as enum **or** kebab-case string: `write_unified_state(..., phase=Phase.DEV_RUNNING)` and `write_unified_state(..., phase="dev-running")` produce identical on-disk bytes.

**Legacy upgrade**
- Project with sprint-status row `"in-progress"` and **no** `phase-store.yaml`: first call to `read_unified_state(root, key)` returns `("in-progress", "dev-running")` and *materializes* `phase-store.yaml` with `key: dev-running`. Second call (now clean) returns the same tuple without writing.
- Migration is per-story (lazy), not whole-store eager — a project with 50 sprint-status rows materializes phase entries one read at a time, which is the cheapest correct option for warm caches.

**M48 call-site invariants**
- `compute_dual_state(root, key)` returns the same `DualStoreState` shape pre- and post-G7 for any state G7 produces. (Tests assert by constructing G7-produced state then calling `compute_dual_state` and checking the dataclass fields.)
- `validate_dual_store(root)` returns `[]` (no inconsistencies) for any state produced by `write_unified_state`. (G7's writer is a stricter superset of M48's `write_phase`; it cannot create inconsistency.)
- `write_phase(root, key, phase)` (M48 API) continues to work — touching only the phase store — and the resulting state is detected as inconsistent by `validate_dual_store` exactly as it was before G7.

### 6.2 Test coverage

Minimum **12 new tests** in `tests/test_unified_state.py`:

1. `test_read_unified_state_clean_state_returns_pair_deterministic` — clean two-store fixture; two reads return identical tuples; the lock file is not modified (mtime unchanged).
2. `test_read_unified_state_missing_phase_materialises_derived_pair` — phase store empty; sprint-status row `"in-progress"`; first read returns `("in-progress", "dev-running")` AND phase store now has the row.
3. `test_read_unified_state_unknown_sprint_status_returns_pending_no_write` — sprint-status row `"made-up-status"`; read returns `("made-up-status", "pending")`; phase store remains empty.
4. `test_read_unified_state_missing_story_row_raises` — empty sprint-status file; `read_unified_state(...)` raises `UnifiedStateError` mentioning the story key.
5. `test_read_unified_state_conflict_lww_phase_newer` — two-store fixture where phase store has `done` and sprint-status has `in-progress`; touch phase file to later mtime; read resolves to `("done", "done")` AND sprint-status is rewritten on disk to `done`.
6. `test_read_unified_state_conflict_lww_sprint_newer` — same fixture but sprint-status mtime is later; resolves to `("in-progress", "dev-running")` AND phase store is rewritten to `dev-running`.
7. `test_write_unified_state_atomic_both_stores_present` — write `("review-running", Phase.REVIEW_RUNNING)`; both files reflect the new pair; `is_consistent(...)` true.
8. `test_write_unified_state_inconsistent_pair_raises_before_write` — write `("done", Phase.DEV_RUNNING)` → `UnifiedStateError`; neither file modified (verify by checksumming before/after).
9. `test_write_unified_state_phase_accepts_enum_or_string` — write once with `Phase.DEV_RUNNING`, once with `"dev-running"`; resulting bytes byte-identical.
10. `test_write_unified_state_concurrent_writers_serialize_via_lock` — 8 threads write 8 distinct story keys; final state has all 8 in both stores; no torn lines (regex-validated).
11. `test_write_unified_state_lock_timeout_raises_unified_state_error` — pre-acquire the lock from a sibling thread; call with `lock_timeout=0.1`; raises `UnifiedStateError`, message includes `"timeout"`; `filelock.Timeout` *not* exposed to caller.
12. `test_m48_call_sites_still_work` — call `compute_dual_state` and `validate_dual_store` on a state produced by `write_unified_state`; assert `state.consistent is True` and `validate_dual_store(...) == []`.

Plus opportunistic-coverage smoke tests if the impl exposes a public helper (e.g., `unified_state_lock(root)` round-trip test).

### 6.3 Quality gates

- `ruff check skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py tests/test_unified_state.py` exits 0.
- `python -m unittest discover -s tests` exits 0; total test count = 4070 (baseline) + ≥12 new = ≥4082 passing.
- `python -m unittest tests.test_audit_regression` exits 0; **audit-floor invariants count ≥ 24** (no regression — the bma-d/integration-all baseline has 24).
- `wc -l skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py` ≤ 500. If approaching 480 during impl, split repair helpers as noted in §5.
- No new Python imports outside `{stdlib, filelock, psutil}` (CLAUDE.md guardrail).
- No edits to `core/telemetry_events.py` (M01 owns it).
- No edits to `sprint_phase_map.py` (M48 frozen surface preserved).
- `git grep -n "sprint_phase_map" skills/` post-impl shows no removals — only `unified_state.py` may *import* from it.

## 7. Risks + mitigations

- **R1 — LWW conflict resolution masks an operator's manual edit.** If an operator hand-edits `phase-store.yaml` to fix a known-bad state and then a stale orchestrator touches sprint-status, the orchestrator's later mtime overwrites the operator's repair. *Mitigation*: G7 is read-mostly; the orchestrator already writes sprint-status only during state transitions, which are themselves under the gate lock. The window is small and recoverable (just re-edit). Document the LWW semantics in the changelog entry and in the unified-state module docstring. A future op runbook entry covers manual conflict resolution.
- **R2 — Migration write storm.** A project with 200 sprint-status rows would materialize 200 phase entries on first reads — each a full phase-store rewrite under lock. *Mitigation*: each rewrite is a tiny YAML (one line per row); 200 rewrites complete in well under a second even on cold disk. If perf bites in practice, a follow-up may add a bulk `migrate_all_unmaterialized_rows(root)` helper (out of scope for G7).
- **R3 — Hidden coupling to YAML formatting.** The sprint-status writer rewrites the whole document. If the document carries comments or non-canonical ordering, we lose them. *Mitigation*: the sprint-status writer reads → mutates one row → writes via the **same** path the orchestrator's existing writer uses, so any formatting loss is identical to status-quo. Tests assert round-trip equality on a representative fixture pulled from `tests/data/sprint-status-*.yaml`.
- **R4 — Lock contention with `gate.lock`.** A long-running gate hold could starve unified-state writes that happen concurrently. *Mitigation*: G7's lock is **distinct** from the gate lock (different file, `.unified-state.lock`). Writers contend only with other unified-state writers. Default 10s timeout is generous; CLI exposes `--state-lock-timeout` (post-G7, not in scope).
- **R5 — Mtime granularity on Windows / WSL.** Some filesystems report mtime in 1-2s granularity; two writes within that window could tie on mtime. *Mitigation*: ties break **in favor of the phase store** (deterministic — the phase store is the "authoritative dev-loop ledger" per M48's docstring). Test asserts the tie-breaker explicitly with a fixture that touches both files to the same nanosecond.
- **R6 — Auto-write on read surprises external integrators.** A read-only audit tool that just wants to *observe* state would, on a legacy project, trigger a write through `read_unified_state`. *Mitigation*: provide a read-only variant `read_unified_state_observe(...)` that skips migration / repair and returns the raw pair (or a tuple with a third "needs_repair" flag) — **deferred to a follow-up**, not in G7 scope. Document the side effect in the docstring loudly.

## 8. Verification strategy

- **Unit tests**: the 12 listed in §6.2 cover happy path, all repair branches, all error branches, and concurrency. They use `tempfile.TemporaryDirectory` + the existing test-helper pattern (one fixture per state shape) and are reachable from `tests/` discovery as-is.
- **Concurrency test methodology**: thread-based (not multiprocess), each thread calls `write_unified_state` with a distinct story key, joined via `concurrent.futures.ThreadPoolExecutor`. The test asserts (a) all 8 keys present in both stores, (b) no torn lines via line-count regex on the YAML, (c) no `filelock.Timeout` escaped to any thread.
- **Migration test methodology**: a fixture in `tests/data/legacy-sprint-status-only/` ships sprint-status.yaml with 3 rows and no phase store; the test calls `read_unified_state` three times (one per row) and asserts the resulting phase store has 3 entries with the correctly-derived phases.
- **Round-trip integrity**: a fixture `tests/data/sprint-status-canonical.yaml` is read → unified-state writer rewrites one row → resulting YAML re-validated by `core/sprint_schema.validate_sprint_status(...)` and reparsed by `sprint_status_get` returning the new value.
- **Audit-floor invariant**: `python -m unittest tests.test_audit_regression` after the patch lands must report ≥ 24 invariants — `add` the new dual-store unification invariant ("no module other than `unified_state.py` writes to both stores within the same operation") as a string-grep check, lifting the floor to 25.
- **Smoke**: `bash scripts/smoke-test.sh` exits 0 after the patch (no npm-payload regression; new module ships in the skill bundle but adds no runtime cost).
- **Lint**: `ruff check` and `python -m ruff format --check` clean across both the new module and the test file.

## 9. Non-functional requirements

- **Determinism**: `read_unified_state` on a clean state is byte-deterministic (no clock reads, no nondet ordering).
- **Performance**: read in the no-repair path completes in < 5 ms on a warm fixture (one YAML parse + one phase-store parse; both files small). Write completes in < 50 ms under typical contention.
- **Resilience**: a `SIGKILL` between the two atomic renames inside `write_unified_state` leaves the system recoverable: the next reader sees mtime-mismatched stores → LWW repair runs → state converges. Verified by manually corrupting the temp file mid-write in a test.
- **Observability**: G7 emits no new telemetry events (per CLAUDE.md M01 guardrail). If a repair write fires from inside `read_unified_state`, it is silent — operators discovering it via `validate_dual_store` is acceptable.
- **Compatibility**: no new dep; cross-platform (Windows git-bash, WSL Ubuntu, Linux CI) verified via existing `scripts/smoke-test.sh`.
- **Replayability**: state transitions are observable post-hoc via the sprint-status YAML + phase store on disk; no in-memory-only state.

## 10. Out of scope

- Migration of M48 orchestrator call sites onto `write_unified_state` — those still use `write_phase(...)` + the orchestrator's own sprint-status writer. Migration is a separate, larger milestone once external integrations have been audited.
- `read_unified_state_observe(...)` read-only variant (R6 mitigation deferral).
- CLI subcommand (`story-automator state get/set`) — operators interact with the unified state through the existing `story-automator gate status` UX; a dedicated state CLI is out of scope.
- Bulk migration helper `migrate_all_unmaterialized_rows(root)` (R2 follow-up).
- Cross-host clock-skew resolution (still LWW by mtime; cross-host orchestration is out of scope for the factory's single-trusted-operator model).
- Telemetry event for unified-state repair writes (deferred; would require M01 milestone for the event type).
- Schema validator for the phase store (today it's a line-regex parser in `read_phase_store`; tightening it is an M48 concern, not G7).

## 11. Validation provenance

This spec was authored after reading M48's `sprint_phase_map.py` in full (lines 1–476, including the frozen-surface `__all__` block), the existing audit-floor regression test, and the L1/L2 gate-marker filelock work (`.claude/workflows/l1-l2-gate-marker-fix.md`) to align G7's lock idiom with the pattern the codebase already uses. The decision matrix in §2 reflects review against:

- CLAUDE.md hard guardrails (no telemetry-events edit; no new deps; 500-LOC limit; portable across Windows git-bash / WSL / Linux CI).
- M48's frozen public surface (every symbol in `__all__` is preserved verbatim; G7 only *imports* from M48).
- Round-2 audit findings (the dual-store concurrency hazard was flagged but not fixed; G7 closes it).
- Single-trusted-operator threat model ([[singleuser-threat-model]]): G7 does not need cross-tenant isolation; one operator, one VPS, one project.

Acceptance is gated on (a) the 12 listed tests passing, (b) all existing 4070 tests still passing, (c) ruff clean, (d) audit-floor regression ≥ 24, (e) module under 500 LOC.
