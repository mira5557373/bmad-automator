# C1 follow-up (persistence + orchestrator wiring) + C2 query CLI — status report

> Workflow: `c1-followup-and-c2-cli` (parallel: C1 follow-up || C2 query CLI)
> Branch: `bma-d/integration-all`
> Baseline at start: `c6c4ee7` (c2-followup-and-c1-watcher-complete workflow archive, 4224 tests green)
> Tip at finish: `445263e` (4268 tests green)

## TL;DR

Two follow-ups landed in parallel on `bma-d/integration-all`, each tagged
on shipping:

- **C1 follow-up (`compat-c1-followup-persistence-and-wiring`)** — closes
  the two follow-up gaps the C1 MVP recorded as deferred:
  - **Disk-backed baselines.** New OPTIONAL `persistence_key` kwarg on
    `SpecDriftWatcher`. When `None` (default) the watcher is byte-identical
    to the in-memory MVP — no I/O, no state files, no behavior change. When
    set to a slug, the watcher writes its baseline + a JSONL event log
    under `_bmad/drift/<key>/` so the baseline survives orchestrator
    restarts. Atomic writes via `core/atomic_io.py`; concurrent appenders
    serialise through a filelock alongside the events file.
  - **Orchestrator-cadence integration.** New OPTIONAL `drift_watcher`
    kwarg on `run_production_gate`. When `None` (default), zero behavior
    change. When provided, `run_production_gate` polls the watcher once
    after the in-progress marker is written and once after `evaluate_gate`
    returns (before any fail-closed override). Failures inside `poll()`
    are swallowed — drift telemetry can never abort a gate, by design.
  - The split between in-memory MVP and persisted layer is preserved via a
    sibling module (`core/innovation/spec_drift_persistence.py`, ~289 LOC).
    `spec_drift_watcher.py` stays inside the 500-LOC soft cap.
  - Frozen-surface compliance: both new kwargs default to `None` (or
    `drift_watcher=None`) and existing callers see byte-identical
    behavior.

- **C2 query CLI (`compat-c2-query-cli`)** — operators previously had no
  way to inspect the persisted lineage ledger under `_bmad/lineage/`
  without ad-hoc Python. New `orchestrator-helper lineage` command exposes
  the chain as read-only JSON via five subcommands: `show`, `entry`,
  `stats`, `verify`, `orphans`. All actions are read-only — they never
  mutate disk. Output is canonical JSON with alphabetically-sorted
  top-level keys, matching the gate-file embed and audit-chain
  conventions for byte-deterministic output across machines.

Tests rose 4224 → 4268 (+44). Ruff clean. Audit-floor invariants still
26-green. No frozen-surface symbol changed (only additive: new optional
kwargs on `SpecDriftWatcher` and `run_production_gate`; a new
`lineage_cmd` module on a purely new CLI surface). No new dependency.

## C1 follow-up outcome (persistence + orchestrator wiring; ADDITIVE)

Commit `445263e` — `feat(c1): C1 follow-up — baseline persistence + run_production_gate drift_watcher kwarg`.
Tag `compat-c1-followup-persistence-and-wiring`.

### What it adds

- **New OPTIONAL `persistence_key` kwarg on `SpecDriftWatcher`.**
  - Constructor signature gains `persistence_key: str | None = None`.
    Default `None` ⇒ in-memory-only (MVP behavior, byte-identical).
  - When set, the watcher writes its baseline to
    `_bmad/drift/<persistence_key>/baseline.json` and appends each
    `SpecDriftEvent` to `_bmad/drift/<persistence_key>/events.jsonl`.
  - `start()` re-uses an existing on-disk baseline when present and the
    same `story_key` is being watched (so the watcher reattaches across
    orchestrator restarts). Mismatched `story_key` raises loudly — no
    silent baseline reuse across stories.

- **New sibling module
  `core/innovation/spec_drift_persistence.py`** (~289 LOC, well under
  the 500-LOC soft cap):
  - `get_drift_root_dir(project_root) -> Path`
  - `get_drift_dir(project_root, persistence_key) -> Path`
  - `validate_persistence_key(key) -> None` — `[a-z0-9-]{1,64}` slug
    rule.
  - `baseline_path(project_root, key) -> Path`
  - `events_path(project_root, key) -> Path`
  - `events_lock(project_root, key) -> filelock.FileLock` — 60 s
    timeout, alongside the JSONL file.
  - `write_baseline(...)` — `core/atomic_io.write_atomic_text` for
    crash-safety; canonical JSON via `core/canonical_json`.
  - `load_baseline(...)` — returns `None` when the file does not yet
    exist; raises `SpecDriftPersistenceError` on corrupt/JSON-parse
    failures (no silent rebuild — matches `core/audit.py` loud-fail
    policy).
  - `append_event(...)` — filelock-coordinated `O_APPEND` to
    `events.jsonl`. One JSON object per line, no trailing comma, sorted
    keys.

- **New OPTIONAL `drift_watcher` kwarg on
  `gate_orchestrator.run_production_gate`.**
  - Signature gains `drift_watcher: SpecDriftWatcher | None = None`.
    Default `None` ⇒ orchestrator behavior byte-identical.
  - When provided, the orchestrator polls the watcher exactly twice:
    1. After the in-progress marker is written but before any collector
       has run.
    2. After `evaluate_gate` returns but **before** any fail-closed
       override path. This means a drift CRITICAL classification will
       still ride alongside the actual verdict — it does not pre-empt
       fail_closed.
  - Failures inside `watcher.poll()` are caught and swallowed at the
    orchestrator boundary. Drift telemetry is informational; it can
    never abort a gate.

### Frozen-surface rule compliance

- `SpecDriftWatcher()` with no `persistence_key` kwarg continues to work
  identically — covered by a regression test that constructs the watcher
  with the original MVP positional signature.
- `run_production_gate(...)` with no `drift_watcher` kwarg continues to
  work identically — covered by 4 separate regression tests across the
  in-progress-marker, normal-pass, fail-closed-override, and crash-recover
  paths.
- No existing public symbol was renamed, removed, or signature-narrowed.
- The persistence layer is in a sibling module so the watcher's public
  surface in `spec_drift_watcher.py` only gains the one optional kwarg.

### Tests

19 new tests (4224 → 4243 after C1 follow-up; the +25 from C2 CLI takes
the final to 4268):

- `tests/test_spec_drift_persistence.py` (9 tests) — slug validation,
  round-trip baseline, corrupt-baseline raises loudly, missing-baseline
  returns `None`, JSONL append idempotence under filelock, multi-event
  ordering, concurrent appender serialisation, canonical JSON ordering,
  atomic-write failure leaves baseline untouched.
- `tests/test_spec_drift_persistence.py` integration block (5 tests) —
  watcher with `persistence_key` writes baseline on `start()`, watcher
  reattaches across re-instantiation with same key, mismatched
  `story_key` raises, events appended one per `poll()`, `reset()`
  clears on-disk baseline.
- `tests/test_gate_orchestrator_drift_wiring.py` (5 tests) —
  `drift_watcher=None` is byte-identical (regression pin); polling
  happens exactly at both lifecycle points when watcher is provided;
  `poll()` raising is swallowed; fail-closed override path still
  polls; drift event is included on the orchestrator return when
  watcher provided.

## C2 query CLI outcome (subcommands; JSON output)

Commit `1796b08` — `feat(cli): C2 query CLI — lineage show/entry/stats/verify/orphans`.
Tag `compat-c2-query-cli`.

### What it adds

- New module
  `skills/bmad-story-automator/src/story_automator/commands/lineage_cmd.py`
  (~352 LOC, under the 500-LOC soft cap). Purely new surface — no
  frozen impact.
- Five `orchestrator-helper lineage <subcommand>` actions, all
  read-only, all emit canonical JSON to stdout with alphabetically
  sorted top-level keys:

  | Subcommand | Purpose |
  |---|---|
  | `show` | Full chain in canonical `seq` order |
  | `entry <genre> <slug>` | Single `LineageEntry` |
  | `stats` | Counts per genre, root, chain length, orphan count |
  | `verify` | Re-runs `verify_lineage` against disk — exits non-zero on broken chain |
  | `orphans` | Entries whose `parent_root` references an unknown root |

- `orphans` and `stats` use a **lenient loader** so they remain
  informative even when the chain has dangling parent pointers.
  `verify` is the **strict-mode** subcommand that does refuse a broken
  chain — single source of truth for "is the chain healthy?"
- Wired into `cmd_orchestrator_helper` via the existing dispatch table
  (`"lineage": _lineage`). The only change to `orchestrator.py` is a
  12-line additive dispatch hookup; no existing dispatch entry was
  modified.

### Frozen-surface rule compliance

- `commands/lineage_cmd.py` is a new module — no frozen surface to
  honor.
- `lineage_ledger` is consumed read-only — no new symbols added there
  by this commit.
- `orchestrator.cmd_orchestrator_helper`'s dispatch table gains one
  additive `"lineage"` entry; no key was renamed or removed.

### Tests

25 new tests in `tests/test_lineage_cmd.py`:

- `show` empty chain returns empty list, populated chain returns
  canonical order, output is byte-deterministic across two runs.
- `entry` returns the right record, raises `KeyError`-shaped JSON
  error on missing.
- `stats` counts per genre, reports chain length, reports root, reports
  orphan count.
- `verify` exits 0 on healthy chain, exits non-zero on tampered entry,
  exits non-zero on broken parent_root.
- `orphans` returns empty list on healthy chain, returns orphans on a
  partial chain (deleted root entry), is lenient (does not raise) when
  `verify` would.
- Dispatch table: `orchestrator-helper lineage <unknown>` errors
  cleanly; `orchestrator-helper lineage` without subcommand prints
  usage and exits non-zero.
- Stdout is canonical JSON: alphabetically sorted top-level keys, no
  trailing newline drift, no platform-specific path separators in
  payload.

## Final state

- **HEAD:** `445263e` — `feat(c1): C1 follow-up — baseline persistence + run_production_gate drift_watcher kwarg`.
- **Tests:** **4268 total**, 0 failing, 2 skipped (pre-existing). `+44`
  net from the 4224 baseline (+19 from C1 follow-up, +25 from C2 CLI).
- **Ruff:** clean.
- **Audit-floor invariants:** 26 / 26 green
  (`tests/test_audit_regression.py`).
- **Frozen-surface compliance:** zero existing symbol renamed, removed,
  or signature-narrowed; two purely additive OPTIONAL kwargs
  (`SpecDriftWatcher(persistence_key=…)`, `run_production_gate(drift_watcher=…)`),
  both defaulting to `None` and exercising regression-pinned
  byte-identical behavior when omitted; one purely-new CLI subcommand
  surface (`lineage_cmd`).
- **Tags shipped this workflow:**
  - `compat-c1-followup-persistence-and-wiring`
  - `compat-c2-query-cli`

## What remains tracked

### C-class deferred follow-ups still open

- **C3 — cost-attribution metrics on gates.** Per-collector wall-clock
  + subprocess CPU accounting rolled up into a `gate_cost_breakdown`
  block on `GateFile`. **Blocked by N7** (`compat-n7-1-tmux-cli-dispatcher`
  shipped, but the production-gate path doesn't yet route through
  `cli_dispatcher.dispatch_session`, so collector cost numbers would
  miss the dispatch boundary). Tracked for after the N7 rollout closes.
- **C4 — compliance pack (SOC2 / ISO27001 / HIPAA evidence map).**
  Maps the existing evidence categories onto external control
  frameworks. **Deferred** — single-user-VPS threat model does not yet
  warrant the operational overhead; revisit when an enterprise customer
  asks.
- **C5 — self-improving gate (gate rules trained on prior verdicts).**
  Closes the loop between historical gate decisions and rule weights.
  **Blocked by A9 corpus** — needs the canonical multi-month gate
  corpus that A9 will produce. Tracked for after A9 corpus stabilises.

### C-class deferred follow-ups still tracked but lower priority

- **C1 follow-up — multi-story aggregation.** Roll multiple
  `SpecDriftEvent` streams up into a single "epic-drift" view for the
  operator. Pure stdlib; no telemetry change required.
- **C1 follow-up — telemetry-event wiring.** Each `SpecDriftEvent`
  should emit on the audit chain. Needs an M01 telemetry addition
  (`SpecDriftEventAudit`) — bound to the M01 owner milestone, NOT
  this workflow.
- **C2 follow-up — visualisation.** Mermaid/DOT export of
  `LineageChain` for inclusion in retro / planning docs. CLI scaffold
  is ready (`commands/lineage_cmd.py` can grow a `graph` subcommand)
  but defers until an operator asks.

### G-class deferred follow-ups (multi-week)

- **G1 / G3 / G6 / G8** — recorded in `docs/audit/k2-and-c2-2026-06-23.md`
  and earlier reports; none touched by this workflow.

### Push to remote

This workflow shipped against `bma-d/integration-all` locally. The
local-only backlog now stretches across nine workflow-archives
(smoke-expand-and-k5 onward through this C1 follow-up + C2 CLI). Per
the operator push-cadence convention, batched-push to
`origin/bma-d/integration-all` is a separate operator step — this
workflow does not push.

### Audit-floor health

26 invariants. No new invariant added by this workflow. The C1
follow-up adds disk persistence + an optional orchestrator polling
hook (no security/trust-boundary surface beyond
`atomic_io`/`filelock`, both already pinned). The C2 query CLI is
read-only and does not mutate state. The next candidate for a new
invariant is the C1 telemetry-event wiring milestone (when the M01
owner ships `SpecDriftEventAudit`), which will introduce a fresh
audit-chain emission point worth a structural pin.
