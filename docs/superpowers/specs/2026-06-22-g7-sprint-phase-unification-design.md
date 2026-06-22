# G7 — Sprint-Phase Dual-Store Unification — Design Spec

> Date: 2026-06-22 · Status: **Draft for implementation** · Milestone: **D (G7 unification)** · Owner branch: `bma-d/integration-all`.
> Topic: collapse the M48 sprint-status / Phase dual-store read+write surface behind a **single source of truth** so external tools cannot drift the two stores under normal operation, and so concurrent writers cannot interleave them.
> Validation provenance: builds on M48 (`core/integration/sprint_phase_map.py`) and the L1/L2 gate-marker filelock work (`.claude/workflows/l1-l2-gate-marker-fix.md`). Surgical addition; no public-symbol renames in M48's frozen surface (`compute_dual_state`, `write_phase`, `validate_dual_store`, `read_phase_store`, `phase_for_sprint_status`, `sprint_status_for_phase`, `is_consistent`, `phase_store_path`, `Phase`, `DualStoreError`, `DualStoreState`, `Inconsistency`, `DualStoreInconsistencyError`, `SPRINT_STATUS_TO_PHASE`, `PHASE_TO_SPRINT_STATUS`, `TERMINAL_PHASES` — all preserved verbatim).

## 1. Goal

Close the three latent dual-store hazards M48 left behind:

1. **No single read API.** Today callers either call `sprint_status_get(...)` (sprint-status only) or `compute_dual_state(...)` (both stores, but the result is a 6-field dataclass with derived/found/consistent flags — verbose for callers that just want "what is this story's current pair?"). External integrators ended up importing one or the other based on convenience, which is exactly how drift creeps in.
2. **No atomic write across both stores.** `write_phase(...)` covers the Phase side; **no sprint-status writer exists in the codebase today** (verified via `git grep "sprint_status_path\|sprint-status\.yaml"` — only readers, zero writers — gap D01). G7 therefore ships the **first-ever sprint-status writer** as part of this milestone. The writer is row-targeted (regex-based mutation of one matching row; preserve all non-target lines byte-exact; preserve trailing newline; raise `UnifiedStateError` if the row is absent), text-only (no YAML re-serialization), and atomic via `write_atomic`. This is non-trivial new scope that the prior spec hid; the §11 LOC budget is re-baselined accordingly.
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
| Conflict resolution | **Last-write-wins via mtime with same-volume precondition** (gap D03 — *scoped* to `_resolve_lww` per gap D-R-02). The same-volume check runs ONLY inside `_resolve_lww` (which by construction is invoked only when both phase store and sprint-status files exist on disk and disagree); it MUST NOT run on the migration path (where the phase store file does not yet exist — `.stat()` would raise `FileNotFoundError`). Inside `_resolve_lww`, the reader asserts `phase_store_path(root).stat().st_dev == sprint_status_path(root).stat().st_dev`; if not (e.g. on a WSL setup where the project mixes `<artifacts>/phase-store.yaml` on ext4 with a legacy `_bmad-output/sprint-status.yaml` on NTFS), the reader raises `UnifiedStateError("cross-filesystem unified state not supported; phase store and sprint-status must share a volume")` rather than silently comparing across volumes. On a same-volume layout, the source whose backing file has the later `st_mtime_ns` wins; the loser is re-projected from the winner via `phase_for_sprint_status` / `sprint_status_for_phase`, persisted back under lock, and returned. **Read-repair self-cancellation guard** (gap D-R-09): after `_resolve_lww` acquires the lock, it MUST re-read both files under the lock and re-evaluate the conflict; the projection is performed only if the locked re-read still shows a conflict AND the same winner. Stale-cached LWW state always loses to fresh-locked LWW state — this prevents two concurrent readers (each carrying their own pre-lock observation) from undoing each other's repair. **Mtime-tie secondary tie-break** (gap D08 — coarse-granular filesystems make ties common, not exotic): if mtimes are equal, the entry whose status value is in `TERMINAL_PHASES` wins (terminal phase is semantically "more recent"); if neither or both are terminal, phase store wins (legacy default). |
| Lock granularity | **Per-project**, one lock for both stores. Lock file path: `<implementation_artifacts_dir>/.unified-state.lock`. This mirrors `get_gate_lock`'s pattern (single lock for the entire gate subsystem of one project) and matches `_recover_from_crash_locked`'s `filelock.FileLock` usage. **Timeout**: 10 seconds default for `write_unified_state`; configurable via `write_unified_state(..., lock_timeout=…)`. Holder identity is *not* recorded (lock-holder observability lives in B2, not G7). |
| New dep? | **No.** `filelock` already imported by `gate_orchestrator.py` and is in the CLAUDE.md guardrail allow-list. `psutil` not needed (no liveness check inside G7). |
| Touch sprint-status YAML schema? | **No.** Writer mutates one row of the existing YAML by rewriting the full document — no new fields, no reorder. Schema validator (`core/sprint_schema.py`) is exercised by tests to confirm round-trip parity. |
| Touch `telemetry_events.py`? | **No** — M01 owns that file; CLAUDE.md hard guardrail. G7 emits no new telemetry. (If drift is repaired on read, the existing `core/gate_audit.GateProfileDrift` is not the right shape; we keep G7 silent and rely on the inconsistency being self-correcting. A future milestone may emit `UnifiedStateRepair` rides-`UnknownEvent`-forward-compat, but not in G7.) |
| Migration policy | **Auto-upgrade on first read.** When `read_unified_state` sees an empty phase-store but a valid sprint-status row, it computes the derived phase via `phase_for_sprint_status`, writes the pair atomically through `write_unified_state` under the same lock, and returns the projected pair. No CLI subcommand — invisibly self-heals. |
| Unknown sprint-status string on read | Conservative: return `(raw_status, Phase.PENDING)` and **do not** auto-write — surfacing the misspelling lets the operator fix it instead of silently normalizing. (This matches `compute_dual_state`'s existing fail-soft behavior on unknown statuses.) |
| What about `sprint_status_get`'s "story missing" path? | Treat missing-row as a hard read failure: `read_unified_state` raises `UnifiedStateError`. Auto-creating a row would tread on the orchestrator's state machine — out of scope. Callers can probe with `compute_dual_state(...).found` first. |
| Concurrent writers | The lock serializes writers — but readers do **not** take the lock by default (read-mostly contention model). **Read-order is the REVERSE of write-order — but only in the steady-state branch** (gap D05 + gap D-R-03). Three modes coexist: (a) **Steady-state read** — reader reads sprint-status first, phase second; writer wrote phase first, sprint-status second; the reverse pairing guarantees a reader observing the new sprint-status also sees the new phase store. (b) **Steady-state write** (via `write_unified_state`) — phase first, sprint-status second. (c) **Migration write from inside `read_unified_state`** — only one store is touched (phase store materialisation); ordering is immaterial because there is no second file to coordinate with. Each branch carries an explicit inline code comment naming its mode so an implementer cannot conflate them. **Two-read consistency**: the reader uses a stat-twice-or-retry pattern (gap D04) — after reading sprint-status + phase, re-stat both files; if either mtime is newer than the at-read-start stat, restart the read (capped at 3 attempts to bound retry storms; after 3, acquire the lock briefly with `read_lock_timeout=2.0s` to take a serialised snapshot — see gap D-R-04). On read-lock-timeout the reader returns the best-effort current pair without performing repair; if the call shape supports `needs_repair`, set it `True` to flag divergence. This eliminates the "two reads → writer between → phantom inconsistency → reader writes wrong projection" race while keeping reader latency bounded under writer contention. |
| Read-only callers (forensic / audit) | **`observe_only=True` kwarg ships in G7** (gap D07 — NOT deferred). `read_unified_state(root, key, *, observe_only=False, read_lock_timeout=2.0)` defaults to the write-on-repair behaviour; when `observe_only=True`, the function never writes (no migration, no LWW repair). **Monomorphic return shape** (gap D-R-01 — replaces the prior arity-by-flag contract): the function ALWAYS returns a 3-tuple `(sprint_status: str, phase_value: str, needs_repair: bool)` regardless of the flag. When `observe_only=False` and an in-line repair ran, the post-repair state is coherent and `needs_repair=False`. When `observe_only=True`, `needs_repair=True` flags that the on-disk state is divergent and the caller did NOT mutate it. When `observe_only=True` and the phase store is empty but the sprint-status row exists with a known status (gap D-R-05), the returned `phase_value` is the *derived* phase string (e.g., `phase_for_sprint_status(status).value`) and `needs_repair=True` — semantically "authoritative pair, but on-disk phase store needs materialisation." When `observe_only=True` and the sprint-status row's status is unknown (not in `SPRINT_STATUS_TO_PHASE`), `phase_value="pending"` and `needs_repair=True`. Forensic tools (`tar -czf snapshot.tgz _bmad/`) MUST pass `observe_only=True` to avoid corrupting their own snapshot. Docstring carries an explicit warning: "Calling this function with the default observe_only=False may write to disk; pass observe_only=True for read-only callers." |
| Missing-row error differentiation (gap D09) | Two error subclasses: `UnifiedStateFileMissingError(UnifiedStateError)` when `sprint_status_path(root)` does not exist; `UnifiedStateRowMissingError(UnifiedStateError)` when the file exists but the row is absent. Operators get distinct messages (file-missing = setup problem; row-missing = data problem). |
| Slug-vs-canonical key reconciliation (gap D10 + gap D-R-07) | Before writing the phase entry, `write_unified_state` resolves to the canonical dotted story id via `story_keys.normalize_story_key(root, story_key).id` (NOT via `sprint_status_get(...).story` — that returns the *matched-row key* from the YAML, which is the slug itself when the YAML has only a slug-keyed row; using `SprintStatus.story` would persist under the slug, the inverse of what the spec intends). The canonical id is always the dotted form (`"1.1"`, `"3.14"`); the phase entry is written under that key. Any orphan slug-keyed entry (e.g., `"1-1-host-feasibility-probe"`) in the phase store is deleted as part of the same write under lock. This prevents the "two entries for one story" footgun that M48's `compute_dual_state` fallback (`phase_store.get(key) or phase_store.get(sprint.story)`) currently papers over. |
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

- **`read_unified_state(project_root, story_key, *, observe_only=False, read_lock_timeout=2.0)` return** (gap D07 + gap D-R-01 + D-R-04 + D-R-05): **monomorphic 3-tuple** `(sprint_status: str, phase_value: str, needs_repair: bool)` regardless of the `observe_only` flag (no arity-by-flag — that was rejected as a Python-typing footgun). When `observe_only=False` (default) and the function performs an in-line repair (LWW or migration), the post-repair state is coherent and `needs_repair=False`. When `observe_only=False` and no repair was needed, `needs_repair=False`. When `observe_only=True`, the function never writes; `needs_repair=True` iff the on-disk state was divergent (conflict, migration-pending, or unknown-status). On `observe_only=True` with phase store empty but sprint-status row present (and status known), the returned `phase_value` is the *derived* phase string (e.g., `phase_for_sprint_status(status).value`) and `needs_repair=True`. On `observe_only=True` with unknown sprint-status string, `phase_value="pending"` and `needs_repair=True`. The `read_lock_timeout` kwarg (default 2.0s — generous for normal contention, tight enough not to halt operator tooling) governs the brief lock acquisition the reader takes when the stat-twice-or-retry pattern escalates after 3 failed attempts. On read-lock-timeout, the reader returns its best-effort current pair without performing repair; `needs_repair` is set `True` to flag divergence.
- **`write_unified_state(project_root, story_key, sprint_status, phase, *, lock_timeout=10.0)`**: validates that (status, phase) is consistent via `is_consistent(...)`; raises `UnifiedStateError` if not (no silent normalization on write — writers must commit to a coherent pair). `phase` may be passed as `Phase` enum or kebab-case string. **Key reconciliation** (gap D10 + gap D-R-07 — corrected canonicalisation source): before writing, calls `story_keys.normalize_story_key(project_root, story_key)`; if the result is non-None, uses `.id` (the canonical dotted form, e.g. `"1.1"`) as the phase-store key — NOT `sprint_status_get(...).story` (which would return the matched-row key, possibly the slug itself). If `normalize_story_key` returns None (unrecognisable key shape), raises `UnifiedStateError`. Any orphan slug-keyed entry in the phase store whose normalisation maps to the same canonical id is deleted under the same lock.
- **Sprint-status writer contract** (gap D01 — G7 ships the first-ever writer): `_write_sprint_status_row(root, story_key, new_status)`, private helper. Reads the full sprint-status YAML via `read_text`; mutates only the matching row via regex (mirroring `_PHASE_LINE`-style targeted edit in M48); writes via `write_atomic` (temp file in destination dir → `os.replace`). **Invariants**: (a) all non-target lines preserved byte-exact (including comments, trailing whitespace, ordering); (b) trailing newline preserved; (c) if the target row is absent, raises `UnifiedStateRowMissingError` (no auto-creation); (d) NO YAML re-serialization (text-only mutation); (e) round-trip verified post-write by re-parsing via `sprint_status_get(root, story_key)` and asserting `state.status == new_status` (gap D02 — `validate_sprint_status` cannot be called because it requires a `yaml.safe_load` dict and the codebase has zero `import yaml`; CLAUDE.md hard guardrail forbids adding `yaml` as a dep).
- **`UnifiedStateError(ValueError)`**: base error class. Two subclasses (gap D09):
  - `UnifiedStateFileMissingError(UnifiedStateError)` — sprint-status file or phase store file does not exist on disk.
  - `UnifiedStateRowMissingError(UnifiedStateError)` — file exists but the requested story row is absent.
  Both raised on (a) missing story row, (b) unknown sprint-status string at write time, (c) unknown phase at write time, (d) `(status, phase)` pair fails `is_consistent`, (e) `filelock.Timeout` (re-raised as `UnifiedStateError(timeout=…)` so callers do not need to import `filelock`), (f) cross-filesystem mismatch (`st_dev` differ — gap D03). Subclass of `ValueError` for symmetry with M48's `DualStoreError`. **Not** a subclass of `DualStoreError` — they sit side-by-side; G7 is a new layer on top of M48, not a fork of it.
- **Lock file path**: `<implementation_artifacts_dir>/.unified-state.lock`. Created on first `write_unified_state`; never deleted (cheap, OS will GC if directory is wiped).
- **Migration trigger**: legacy state = `read_phase_store(root)` returns `{}` **and** `sprint_status_file(root)` exists with at least one row. On first read of a story whose sprint-status row is present, derive and persist via the standard write path.

## 5. Implementation surface — files

| File | New / Modified | LOC delta | Notes |
|---|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py` | **New** | ~350-450 (re-baselined per gap D12 after D01 expanded scope) | Module docstring (≥30 lines, matching M48 depth); `from __future__ import annotations`; imports. Public API: `read_unified_state` (with `observe_only` kwarg per D07), `write_unified_state`, `unified_state_lock`, `UnifiedStateError`, `UnifiedStateFileMissingError`, `UnifiedStateRowMissingError`. Private helpers `_resolve_lww`, `_write_sprint_status_row` (the first sprint-status writer — gap D01), `_lock_path`. |
| `skills/bmad-story-automator/src/story_automator/core/integration/_unified_state_repair.py` | **New (pre-authorized split per gap D12)** | ~80 | If `unified_state.py` approaches 450 LOC during impl, repair branches (`_resolve_lww`, stat-twice retry helpers) move here as a private sibling. Plan reserves this filename rather than treating it as a contingency. |
| `skills/bmad-story-automator/src/story_automator/core/integration/sprint_phase_map.py` | **Not modified** | 0 | Frozen surface preserved exactly. (If a private helper turns out to be needed in `unified_state.py`, we add a *new* private symbol there — never re-export from M48.) |
| `skills/bmad-story-automator/src/story_automator/core/integration/__init__.py` | Modified | +6 | Add `unified_state` to the package's import surface (re-export `read_unified_state`, `write_unified_state`, `unified_state_lock`, `UnifiedStateError`, `UnifiedStateFileMissingError`, `UnifiedStateRowMissingError`). No removals. |
| `docs/spec/frozen-gate-surface.md` | **Modified (gap D06)** | +12 | Append a new `### core/integration/unified_state.py` section listing `read_unified_state` (with `observe_only` kwarg), `write_unified_state`, `unified_state_lock`, `UnifiedStateError`, `UnifiedStateFileMissingError`, `UnifiedStateRowMissingError` with signatures + behavioral invariants (LWW direction + tie-break, lock granularity, read-may-write side effect on the default `observe_only=False` path, same-volume precondition). |
| `tests/test_unified_state.py` | **New** | ~420 | ≥17 tests (was 12), see §6.2. |
| `docs/changelog/2026-06-22-g7-unified-state.md` | New | ~30 | `[FULL]` tag — adds capability, no behavior change for existing callers; documents LWW direction + the `observe_only` kwarg + writer contract. |

Total LOC delta ≈ +900, of which ~420 is tests. `unified_state.py` should land between 350 and 450 LOC; if it exceeds 450, the pre-authorized `_unified_state_repair.py` split takes the LWW + stat-twice helpers (~80 LOC) so the main module stays comfortably under the 500-LOC soft limit. The 250-LOC estimate in the prior draft was undercooked because it omitted: (a) the writer (gap D01), (b) the dual error subclasses (gap D09), (c) the same-volume precondition + `observe_only` branch (gap D03/D07), (d) the slug-key reconciliation (gap D10), (e) the stat-twice retry pattern (gap D04).

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

Minimum **18 new tests** in `tests/test_unified_state.py` (was 17 after first enhancement; +1 for D-R-09 read-repair race coverage):

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
13. `test_unified_state_lock_context_manager_round_trip` (gap D20) — `with unified_state_lock(root): write_unified_state(...)` succeeds; sibling `write_unified_state` from another thread blocks until exit.
14. `test_legacy_sprint_status_path_lww` (gap D21) — fixture with `implementation_artifacts_dir` set to a non-default path AND `sprint-status.yaml` still at legacy `_bmad-output/sprint-status.yaml`; if same volume (`st_dev` equal), LWW resolves correctly; if cross-volume, raises `UnifiedStateError("cross-filesystem unified state not supported")` per gap D03.
15. `test_mtime_tie_on_coarse_filesystem_terminal_phase_wins` (gap D08 + gap D-R-06 — tightened to actually force a tie on nanosecond-precision filesystems): use `os.utime(path, ns=(ts_ns, ts_ns))` with INTEGER nanoseconds (NOT `os.utime(path, (atime, mtime))` with float seconds, which on ext4/APFS preserves sub-second precision and silently breaks the tie). Pre-assert via `Path(p1).stat().st_mtime_ns == Path(p2).stat().st_mtime_ns` that the synthetic tie is in effect; if the assertion fails, the test fails with a clear "could not force mtime tie on this filesystem; tie-break test cannot run" message rather than silently exercising the wrong code path. One file carries a terminal phase, the other a non-terminal; assert terminal wins regardless of which file was nominally written first.
16. `test_read_unified_state_observe_only_no_disk_writes` (gap D07 + gap D-R-05) — legacy single-store fixture (phase store empty); call `read_unified_state(root, key, observe_only=True)`; assert returned 3-tuple `(sprint_status, phase_value, needs_repair)` has `needs_repair=True` AND `phase_value == phase_for_sprint_status(sprint_status).value` (the derived phase, NOT empty string and NOT `None`); assert `phase_store_path(root)` is still empty (NO migration); assert sprint-status file bytes byte-identical pre/post.
17. `test_slug_keyed_phase_entry_reconciled_on_write` (gap D10 + gap D-R-07 + gap D-R-10 — fixture setup pinned): fixture explicitly seeds the slug via M48's writer: `from story_automator.core.integration.sprint_phase_map import write_phase; write_phase(tmp_root, "1-1-host-feasibility-probe", Phase.DEV_RUNNING)`. Then call `write_unified_state(tmp_root, "1.1", "in-progress", Phase.DEV_RUNNING)`. The writer MUST canonicalise `"1.1"` via `normalize_story_key(tmp_root, "1.1").id` (NOT via `sprint_status_get(...).story`); assert `read_phase_store(tmp_root) == {"1.1": Phase.DEV_RUNNING}` — dict equality, slug entry must be deleted, canonical entry must be present.
17a. `test_read_repair_self_cancellation_guard` (gap D-R-09) — two concurrent threads invoke `read_unified_state` on a conflicted two-store fixture (phase=done, sprint=in-progress, phase mtime newer). After both threads return, the on-disk state must be internally consistent (`is_consistent(...) is True`) regardless of which read "won." Exercises the locked re-read inside `_resolve_lww`.

**Tests #4 split** to differentiate the two error subclasses (gap D09):
- `test_read_unified_state_missing_file_raises_file_missing_error` — sprint-status.yaml does not exist; raises `UnifiedStateFileMissingError`.
- `test_read_unified_state_missing_row_raises_row_missing_error` — file exists, row absent; raises `UnifiedStateRowMissingError`.

**Read-write race coverage** (gap D04 + D05): in addition to test #10's clean concurrency, add a test that simulates an interleaved writer between the reader's two stats; assert the retry pattern detects the staleness and either restarts the read or escalates to a brief locked read. Implementer adds this as part of the impl when the retry helper lands.

Plus opportunistic-coverage smoke tests if the impl exposes a public helper.

### 6.3 Quality gates

- `ruff check skills/bmad-story-automator/src/story_automator/core/integration/unified_state.py tests/test_unified_state.py` exits 0.
- `python -m unittest discover -s tests` exits 0; total test count = 4070 (baseline) + ≥18 new = ≥4088 passing.
- `python -m unittest tests.test_audit_regression` exits 0; **audit-floor invariants count = 25 after this milestone** (baseline = 24; G7 adds one — see plan §4.4; gap D29 reconciliation). The new invariant's positive-failure test is also required (gap D11): "any module that imports `write_phase` from `sprint_phase_map` AND `sprint_status_file` from `story_keys` MUST also import `unified_state_lock` OR equal `core/integration/unified_state.py` itself".
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
- **R5 — Mtime granularity on Windows / WSL.** Some filesystems (FAT32, exFAT, HFS+ pre-APFS, NFS3, many ZFS configurations) report mtime in 1-2s granularity; two writes within that window could tie on mtime. **On coarse-granular filesystems, ties are common, not exotic** (gap D08). *Mitigation*: secondary tie-break — if mtimes are equal, the entry whose status is in `TERMINAL_PHASES` wins (terminal write is semantically "more recent"); if neither or both are terminal, phase store wins (legacy default). Test #15 (gap D08) forces a synthetic same-whole-second tie via `os.utime(path, (ts, ts))` and asserts terminal-phase precedence. See spec §2 decision matrix for the canonical rule.
- **R6 — Auto-write on read surprises external integrators.** A read-only audit tool that just wants to *observe* state would, on a legacy project, trigger a write through `read_unified_state`. *Mitigation* (gap D07 — resolved in G7, NOT deferred): `read_unified_state(root, key, *, observe_only=True)` ships in G7. When `observe_only=True`, the function never writes (no migration, no LWW repair) and returns a 3-tuple `(sprint_status, phase, needs_repair)`. Forensic/audit callers MUST pass `observe_only=True`. The docstring carries an explicit (emoji-free) warning: "Calling this function with the default observe_only=False may write to disk; pass observe_only=True for read-only callers." Test #16 (gap D07) covers the no-disk-writes path.

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

Acceptance is gated on (a) the 17 listed tests passing (was 12 pre-enhancement), (b) all existing 4070 tests still passing, (c) ruff clean, (d) audit-floor regression = 25 (was 24; G7 adds one — gap D29 reconciliation), (e) module under 500 LOC (with pre-authorized `_unified_state_repair.py` split available per gap D12).

---

## Tracked enhancements (MED/LOW gaps not patched into the spec body)

> Source: `docs/audit/spec-review-2026-06-22-milestone-d.md`. HIGH gaps D01..D10 are resolved inline above. MED/LOW gaps roll forward as inline polish or backlog.

| ID | Severity | Disposition | Note |
|---|---|---|---|
| D11 | MED | Resolved inline | Audit-floor invariant rephrased to require a *positive-failure test*; spec §6.3 carries the new invariant string. |
| D12 | MED | Resolved inline | LOC budget re-baselined to 350-450; `_unified_state_repair.py` pre-authorized as a sibling-module split. |
| D13 | MED | Inline plan polish | Sprint-status writer: minimum mutation contract — preserve all non-target lines byte-exact; preserve trailing newline. Add a test that writes one row and asserts file bytes outside the target row are byte-identical (preserves comments + ordering). |
| D14 | MED | Backlog | Lock-holder observability + PID liveness are owned by milestone B; G7 documents that lockfiles can become stale on operator-killed processes and adds a CLI `state unlock --force` follow-up to the parking lot. |
| D15 | MED | Inline plan polish | Concurrent-writers test is thread-based (current); add a multiprocess variant via `multiprocessing.Process` so the lock isolation is verified across OS process boundaries. Pin `filelock>=3.x` to enforce process-level semantics. |
| D16 | MED | Inline plan polish | LWW-on-conflict tests use `os.utime` for mtime control; add a "skip on FAT / 2s-granular FS" predicate AND a synthetic `mtime_provider` callable in the helper for filesystems where `os.utime` granularity is OS-dependent. |
| D17 | MED | Resolved inline (implicit) | `write_atomic` already creates temp files in the destination directory; both phase store and sprint-status writes go through the same code path. Add a Windows-specific test that asserts atomicity via `os.replace`. |
| D18 | MED | Inline plan polish | Plan §6.3 banned-dep grep: derive the whitelist from `python -c "import sys; print(sys.stdlib_module_names)"` plus the literal `{"filelock", "psutil", "story_automator", "__future__"}`, NOT a hand-typed list. |
| D19 | MED | Backlog | Operator manual-edit conflict resolution: documented in the changelog; "operator override marker" (a `# operator-edit: <ts>` comment line) is a follow-up. |
| D20 | MED | Resolved inline | Test #13 (`test_unified_state_lock_context_manager_round_trip`) added. |
| D21 | MED | Resolved inline | Test #14 (`test_legacy_sprint_status_path_lww`) added. |
| D22 | LOW | Inline plan polish | Writer preserves trailing whitespace + comment after the status word verbatim; add a test with `key: in-progress # owner=alice` and assert post-write the comment is preserved. |
| D23 | LOW | Backlog | CLI subcommand (`gate status --unified`) — documented as out of scope; operators use `python -c "from ...unified_state import read_unified_state; ..."`. |
| D24 | LOW | Inline plan polish | Conventional-commit subject uses a simple hyphen (NOT em-dash) to satisfy commit-lint normalization. |
| D25 | LOW | Inline polish | Validation provenance: if `unified_state.py` ever calls `subprocess.run` (it shouldn't), it MUST use `scrub_env_for_subprocess` per D-04. |
| D26 | LOW | Inline plan polish | Replace `NotImplementedError("phase 3")` stub with a module-level sentinel checked at import time, so a missed stub fails loud. |
| D27 | LOW | Inline plan polish | Plan §4.7: if `scripts/smoke-test.sh` absent, **fail** and ask for guidance, do not silently skip. |
| D28 | LOW | Backlog | Performance NFR "< 5 ms read" is unmeasured; either add a `tests/test_unified_state_perf.py` with `@unittest.skip` by default or drop the quantitative NFR. |
| D29 | LOW | Resolved inline | "No regression" wording reconciled; the new audit-floor invariant lifts the count from 24 → 25 (additive). Spec §6.3 updated. |
| D30 | LOW | Inline plan polish | Plan §0.2: pre-flight check that `tempfile.TemporaryDirectory` + `implementation_artifacts_dir(tmp).mkdir(parents=True)` idiom exists in `test_sprint_phase_map.py`; if not, name the canonical helper module to use. |
| D31 | LOW | Resolved inline | §3 diagram clarified: `phase = read_phase_store(root).get(story_key)`; `dict.get` returning `None` is conflated with "phase missing" — make that explicit. |
| D32 | LOW | Inline polish | Cite B2 by spec path (`docs/superpowers/specs/2026-06-22-operability-batch-design.md`) instead of an implicit forward reference. |

### Resolved-from-gap-report (HIGH)

- **D01** — G7 explicitly ships the **first-ever sprint-status writer** as a private `_write_sprint_status_row` helper with a row-targeted text-only regex mutation contract (preserve all non-target lines byte-exact; raise `UnifiedStateRowMissingError` on absent row). Spec §1 goal #2, §4 schemas, and §5 LOC table all re-baselined.
- **D02** — `validate_sprint_status` removed from the writer (it requires a `yaml.safe_load` dict and `import yaml` is forbidden by CLAUDE.md). Replaced with a regex round-trip equality check: after the row mutation, re-parse via `sprint_status_get(root, story_key)` and assert `state.status == new_status`.
- **D03** — Cross-filesystem precondition added to spec §2 decision matrix: before mtime LWW, the reader asserts `st_dev` equality; if not, raises `UnifiedStateError("cross-filesystem unified state not supported")`.
- **D04** — Reader race: spec §2 decision matrix now pins a stat-twice-or-retry pattern (cap at 3 attempts, then acquire lock briefly for a serialised snapshot).
- **D05** — Read-order = REVERSE of write-order pinned in §2 decision matrix and to be documented as an explicit code comment in `read_unified_state`. Writer commits phase first → sprint-status second; reader reads sprint-status first → phase second.
- **D06** — `docs/spec/frozen-gate-surface.md` is now in §5 file table; new `### core/integration/unified_state.py` section to be appended declaring all four public symbols + the two error subclasses + behavioral invariants.
- **D07** — `observe_only` kwarg ships in G7 (NOT deferred). Test #16 covers the no-disk-writes path. Forensic / audit callers MUST pass `observe_only=True`.
- **D08** — Secondary tie-break: terminal phase wins on mtime tie; phase store wins if neither or both are terminal. Test #15 forces a synthetic tie via `os.utime`.
- **D09** — Two error subclasses: `UnifiedStateFileMissingError` (file absent) and `UnifiedStateRowMissingError` (row absent in existing file). Test #4 splits into two.
- **D10** — Writer resolves to canonical `sprint.story` key via `sprint_status_get` before writing; orphan slug-keyed entries are deleted under the same lock. Test #17 verifies reconciliation. **(Corrected by gap D-R-07: canonicalisation source is `normalize_story_key(...).id`, NOT `SprintStatus.story`.)**

### Resolved-from-rereview (HIGH — fresh gaps surfaced by the second adversarial pass on 2026-06-22)

- **D-R-01** — `read_unified_state` returns a **monomorphic 3-tuple** `(sprint_status, phase_value, needs_repair: bool)` regardless of `observe_only` flag. The prior arity-by-flag contract was rejected as a Python-typing footgun (dynamic flags require defensive unpacking).
- **D-R-02** — Same-volume `st_dev` precondition runs ONLY inside `_resolve_lww` (where both files exist by construction); the migration path skips it (where `phase_store_path(root)` doesn't exist yet — `.stat()` would `FileNotFoundError` before LWW logic could fire).
- **D-R-03** — Read-order ↔ write-order claim split into three modes: (a) steady-state read = sprint→phase reverse-of-write; (b) steady-state write = phase→sprint; (c) migration write (from inside read) = phase-only (single-store mutation; ordering immaterial). Each branch carries an explicit inline code comment naming its mode.
- **D-R-04** — `read_lock_timeout` kwarg (default 2.0s) governs the brief lock acquisition on stat-twice escalation. On read-lock-timeout, the reader returns best-effort current pair with `needs_repair=True`; no infinite block on stuck writers.
- **D-R-05** — `observe_only=True` + empty phase store + known sprint-status status → returned `phase_value` is the *derived* phase string AND `needs_repair=True` (semantically: "authoritative pair, materialisation pending"). Unknown status → `phase_value="pending"`, `needs_repair=True`.
- **D-R-06** — Test #15 uses `os.utime(p, ns=(ts_ns, ts_ns))` with integer nanoseconds; pre-asserts `st_mtime_ns` equality before testing tie-break logic. Floats-as-seconds variant was a silent false-positive on nanosecond-precision filesystems.
- **D-R-07** — Canonicalisation source is `story_keys.normalize_story_key(root, story_key).id` (the dotted canonical form). `SprintStatus.story` is the matched-row key (often the slug itself) and would persist under the slug — the inverse of intended reconciliation.
- **D-R-08** — Audit-floor invariant re-phrased as a syntactic AST call-pattern check (mirroring `AuditKeyEnvScrubInvariant`'s AST walker), not an import-name match. Catches new modules writing both stores without `unified_state_lock`; doesn't false-positive on legitimate sprint-status readers.
- **D-R-09** — `_resolve_lww` re-reads both files **under the lock** and re-runs the conflict check; the projection is performed only if the locked re-read still shows a conflict AND the same winner. Stale-cached LWW state always loses to fresh-locked LWW. Test 17a exercises this.
- **D-R-10** — Test #17 fixture setup explicitly seeds the slug-keyed phase row via M48's `write_phase(...)`; pinned as the only correct setup path.

### Resolved-from-rereview (MED/LOW)

- **D-R-11** (MED) — Smoke-script absence handling: if `scripts/smoke-test.sh` is absent, the milestone hard-fails (returns halt-status to parent orchestrator). No "ask for guidance" — subagent execution has no interactive operator.
- **D-R-12** (LOW) — Audit-floor invariant test class name pinned: `class UnifiedStateWriteIsolationInvariant(unittest.TestCase): ...` — matches the existing `AuditKeyEnvScrubInvariant` / `PluginTrustBoundaryInvariant` convention.
