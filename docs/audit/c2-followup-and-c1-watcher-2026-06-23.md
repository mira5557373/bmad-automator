# C2 follow-up (disk persistence + gate embed) + C1 spec-drift watcher MVP — status report

> Workflow: `c2-followup-and-c1-watcher` (parallel: C2 follow-up || C1 watcher MVP)
> Branch: `bma-d/integration-all`
> Baseline at start: `a2b6f27` (k2-and-c2-complete workflow archive, 4192 tests green)
> Tip at finish: `ec83a39` (4224 tests green)

## TL;DR

Two innovation-adjacent items landed in parallel on `bma-d/integration-all`:

- **C2 follow-up (`compat-c2-followup-disk-and-gate-embed`)** — closes the
  C2 MVP's two known gaps. C2 MVP shipped lineage entries as in-memory
  records only, with no on-disk persistence and no gate-file embedding.
  This follow-up persists each `LineageEntry` to
  `_bmad/lineage/<genre>/<slug>.json` (canonical JSON, atomic write) plus
  an alpha-sorted `_bmad/lineage/index.json` for byte-deterministic
  layout across machines. Concurrent persisters serialise through a single
  filelock (`_bmad/lineage/.lineage.lock`, 60s timeout). Insertion order
  is preserved via a `seq` integer on each index row, so
  `load_lineage_chain` can reconstruct the chain even though the on-disk
  index is alpha-sorted by `"<genre>/<slug>"` key. Gate integration:
  both `run_production_gate` (after `evaluate_gate` + after fail-closed
  override) and `run_system_gate` (after the audit-emit block) now embed
  `gate_file["lineage_root"] = load_lineage_root(project_root)` —
  empty-string sentinel when no chain exists, mirroring N5's
  `evidence_merkle_root` convention. `gate_file` is an open-set shape,
  so this is a purely additive top-level field; documented in
  `docs/spec/frozen-gate-surface.md`.
- **C1 MVP (`compat-c1-spec-drift-watcher-mvp`)** — first concrete
  innovation milestone in the C1 lane. Adds
  `core/innovation/spec_drift_watcher.py`, a poll-based detector that
  captures a baseline `SpecDriftSnapshot` at session start and re-scores
  via `core.spec_compliance.check_compliance` on each `poll()` call.
  Drift is classified into four buckets (OK / INFO / WARNING / CRITICAL)
  by a configurable delta-against-baseline (defaults: 0.05 / 0.15 / 0.30).
  Negative deltas (coverage improved) always classify as OK. Pure
  stdlib + existing `spec_compliance` surface — no new deps, no
  telemetry coupling (M01 surface untouched), no threads/async/disk
  persistence (orchestrator-cadence polling + disk-backed baselines are
  recorded as deferred follow-ups in the module docstring tail).

Tests rose 4192 → 4224 (+32). Ruff clean. Audit-floor invariants still
26-green. No frozen-surface symbol changed (only additive: `lineage_root`
in `GateFile`, plus the new public symbols on `lineage_ledger.py`). No
new dependency.

## C2 follow-up outcome (disk persistence + gate_file embed; frozen-surface declaration)

Commit `ec83a39` — `feat(innovation): C2 follow-up — lineage disk persistence + gate_file lineage_root field`.
Tag `compat-c2-followup-disk-and-gate-embed`.

### What it adds

- `skills/bmad-story-automator/src/story_automator/core/innovation/lineage_ledger.py`
  grows from MVP (~95 LOC in-memory ledger) to a persisted ledger
  (~310 LOC, still under the 500-LOC soft cap). New public symbols:
  - `get_lineage_root_dir(project_root) -> Path` — resolves
    `_bmad/lineage/` under the project root.
  - `get_lineage_lock(project_root) -> filelock.FileLock` —
    `_bmad/lineage/.lineage.lock`, 60s timeout.
  - `lineage_index_path(project_root) -> Path`.
  - `persist_lineage_entry(project_root, entry) -> Path` — writes
    `_bmad/lineage/<genre>/<slug>.json` via `core.atomic_io.write_atomic_text`,
    then rewrites the alpha-sorted index under the filelock. Idempotent:
    re-persisting the same `(genre, slug)` reuses the existing `seq`
    when present.
  - `load_lineage_entry(project_root, genre, slug) -> LineageEntry`.
  - `load_lineage_chain(project_root) -> LineageChain` — reads the
    index, sorts by `seq`, loads each per-entry file, and validates the
    full Merkle/parent chain. Raises `LineageError` on any corruption
    (no silent rebuild — same loud-fail policy as `core/audit.py` from
    M04).
  - `load_lineage_root(project_root) -> str` — convenience wrapper:
    returns the Merkle root of the chain on disk, or `""` when no
    index/chain exists.
- Gate-file embed (orchestrator wiring):
  - `core/gate_orchestrator.run_production_gate` adds
    `gate_file["lineage_root"] = load_lineage_root(project_root)` AFTER
    `evaluate_gate` and AFTER the fail-closed-error override path.
  - `core/system_gate.run_system_gate` adds the same line AFTER the
    audit-emit block so the system-gate path mirrors the production
    path.
- Frozen-surface declaration:
  - `docs/spec/frozen-gate-surface.md` gains a paragraph under
    `GateFile` listing the two orchestrator-embedded additive top-level
    fields (`evidence_merkle_root` from N5 and `lineage_root` from this
    follow-up), and a new dedicated section for
    `core/innovation/lineage_ledger.py` capturing the disk layout,
    concurrency, crash-safety, and corrupt-index policy.

### Frozen-surface rule compliance

- `gate_file` shape is open-set (existing consumers tolerate unknown
  extra keys — `validate_gate_file` is non-strict on additive fields).
- `lineage_root` is a purely additive top-level field; no existing
  key was renamed or removed.
- `docs/spec/frozen-gate-surface.md` is updated to declare the new
  field BEFORE the orchestrator started emitting it (declaration
  precedes wire emission in the same commit).
- Sentinel value when no chain exists is `""` — matches the
  `evidence_merkle_root` convention from N5.

### Tests

- `tests/test_lineage_persistence.py` (13 tests) — round-trip disk
  layout, alpha-sorted index determinism, `seq` insertion order,
  filelock serialisation across concurrent persisters, atomic-write
  failure leaving the index untouched, idempotent re-persist, corrupt
  index re-raises `LineageError`, `load_lineage_root` returns `""`
  when no index exists, `load_lineage_root` vs `LineageChain.merkle_root`
  agree.
- `tests/test_lineage_gate_embed.py` (5 tests) — `run_production_gate`
  with chain present embeds 64-hex root; with no chain embeds `""`;
  `run_system_gate` symmetric; `validate_gate_file` tolerates the
  additive field; sentinel format checked.

## C1 watcher MVP outcome (severity classification, baseline + delta tracking, what is in scope vs deferred)

Commit `8a4db9d` — `feat(innovation): C1 MVP — SpecDriftWatcher with severity classification`.
Tag `compat-c1-spec-drift-watcher-mvp`.

### What it adds

`skills/bmad-story-automator/src/story_automator/core/innovation/spec_drift_watcher.py`
(~461 LOC, under the 500-LOC soft cap). Public surface:

- `SpecDriftSeverity` — `Literal["OK", "INFO", "WARNING", "CRITICAL"]`.
- `SpecDriftThresholds` — frozen dataclass with three positive floats
  (`info`, `warning`, `critical`); defaults `0.05`, `0.15`, `0.30`.
  Strictly increasing — constructor validates.
- `SpecDriftSnapshot` — frozen dataclass capturing
  `{coverage, total_acceptance_criteria, covered_acceptance_criteria,
  captured_at_iso, story_key}`.
- `SpecDriftEvent` — frozen dataclass capturing
  `{severity, delta, baseline, current, story_key, observed_at_iso,
  thresholds, reason}`.
- `SpecDriftWatcher` — class wrapping `core.spec_compliance.check_compliance`.
  - Constructor: `(story_path, *, thresholds=None, clock=None)`.
  - `start() -> SpecDriftSnapshot` — captures baseline; idempotent
    until `reset()`.
  - `poll() -> SpecDriftEvent` — re-scores current coverage, computes
    `delta = baseline - current` (positive = regression), classifies
    via the thresholds. Negative delta always returns OK.
  - `reset() -> None` — clears baseline; next `start()` re-captures.
  - `current_baseline() -> SpecDriftSnapshot | None`.

### Severity classification rule

| Delta range | Severity |
|---|---|
| `delta < 0` (coverage improved) | `OK` |
| `0 <= delta < thresholds.info` (≤5% by default) | `OK` |
| `thresholds.info <= delta < thresholds.warning` (5–15%) | `INFO` |
| `thresholds.warning <= delta < thresholds.critical` (15–30%) | `WARNING` |
| `delta >= thresholds.critical` (≥30%) | `CRITICAL` |

### In scope

- Baseline capture + delta tracking against `core.spec_compliance`
  output.
- Four-bucket severity classification with operator-configurable
  thresholds (default 5/15/30%).
- Negative-delta OK clamp (improvement never trips a regression).
- Injectable clock for deterministic tests.
- `SpecDriftEvent.reason` carries a human-readable explanation
  (`"coverage regressed by 18.0% — WARNING"` etc.).

### Deferred (recorded in the module docstring tail)

- Orchestrator-cadence integration (current MVP is caller-driven
  `poll()`; no asyncio/threads).
- Disk-backed baselines (current MVP is per-session in-memory; baseline
  evaporates when the watcher is GC'd).
- `SpecDriftEvent` telemetry wiring (M01 owner milestone — current MVP
  returns the event for the caller to emit; no `telemetry_events.py`
  edit).
- Multi-story aggregation (current MVP is one watcher per story).

### Tests

`tests/test_spec_drift_watcher.py` (13 tests) — baseline capture,
threshold validation rejects non-strictly-increasing tuples, OK on
negative delta, OK at-or-below `info`, INFO at `info` boundary, WARNING
at `warning` boundary, CRITICAL at `critical` boundary, custom thresholds,
deterministic clock injection, idempotent `start()`, `reset()`
re-captures, error before `start()`, end-to-end story-AC scoring.

## Final state

- **HEAD:** `ec83a39` — `feat(innovation): C2 follow-up — lineage disk persistence + gate_file lineage_root field`.
- **Tests:** 4224 total, 0 failing, 2 skipped (pre-existing). `+32`
  net from the 4192 baseline (+19 from C2 follow-up, +13 from C1
  watcher).
- **Ruff:** clean.
- **Audit-floor invariants:** 26 / 26 green
  (`tests/test_audit_regression.py`).
- **`gate_file["lineage_root"]`:** emitted by both
  `run_production_gate` and `run_system_gate` after evaluation;
  `""` sentinel when no chain on disk; 64-hex Merkle root otherwise.
- **Frozen-surface compliance:** zero existing symbol renamed,
  removed, or signature-narrowed; one additive field on `GateFile`
  declared in `docs/spec/frozen-gate-surface.md` before being emitted;
  six new public symbols on `lineage_ledger.py` declared in the same
  doc.
- **Tags shipped this workflow:**
  - `compat-c1-spec-drift-watcher-mvp`
  - `compat-c2-followup-disk-and-gate-embed`

## What remains tracked

### C-class deferred follow-ups

- **C1 follow-up — orchestrator integration:** wire `SpecDriftWatcher`
  into the gate orchestrator so each poll cadence is owned by
  `run_production_gate` rather than the caller. Will need a small
  M01 telemetry-event addition (`SpecDriftEventAudit`) and a
  disk-backed baseline so the watcher survives orchestrator restarts.
- **C1 follow-up — multi-story aggregation:** roll multiple
  `SpecDriftEvent` streams up into a single "epic-drift" view for
  the operator. Pure stdlib; no telemetry change required.
- **C2 follow-up — operator CLI:** `bmad lineage list / show / verify`
  subcommands to inspect the persisted chain without a Python REPL.
  No frozen-surface change; commands-only milestone.
- **C2 follow-up — visualisation:** Mermaid/DOT export of
  `LineageChain` for inclusion in retro / planning docs.

### G-class deferred follow-ups (unchanged from prior workflow)

- **G1 / G3 / G6 / G8** — recorded in
  `docs/audit/k2-and-c2-2026-06-23.md` and earlier reports; none
  touched by this workflow.

### Push to remote

This workflow shipped against `bma-d/integration-all` locally. The
last seven workflow commits (smoke-expand-and-k5 onward through
this C2 follow-up + C1 MVP) are still **local-only**. Per the operator
push-cadence convention, batched-push to `origin/bma-d/integration-all`
is a separate operator step — this workflow does not push.

### Audit-floor health

26 invariants. No new invariant added by this workflow (C2 follow-up
adds disk persistence + an additive gate-file field, neither of which
warrants a structural audit-floor invariant; C1 MVP adds a pure
in-memory innovation module with no security/trust-boundary surface).
The next candidate for a new invariant is the C1 orchestrator
integration milestone, which will introduce a telemetry-event emission
point and therefore wants an audit-regression structural pin.
