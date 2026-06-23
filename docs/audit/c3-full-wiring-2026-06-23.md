# C3 full wiring (cost attribution → orchestrator) — status report

> Workflow: `c3-full-wiring`
> Branch: `bma-d/integration-all`
> Baseline at start: `8b98374` (n7-unblocker-and-cli-polish-complete, 4312 tests green)
> Tip at finish: `6bf56e4` (4330 tests green)
> Tag shipped: `compat-c3-cost-attribution-wiring`
> Workflow tag: `c3-full-wiring-complete`

## TL;DR

The C3 milestone wires the N7 cost-attribution substrate (usage
parsers + `CollectorCostShare` helpers) into the production gate
lifecycle. One purely-new module (`core/innovation/cost_evidence.py`),
two orchestrator entry points augmented with a single OPTIONAL
`session_usage` kwarg each (`run_production_gate`,
`run_system_gate`), and one additive `cost_total_usd` field on
`GateFile` — conditional on the kwarg being supplied. All frozen
surfaces remain frozen: no evidence-record schema change, no
telemetry-events touch, no edits to `core/usage_parsers/` or
`core/innovation/cost_attribution.py`. Cost data lives in **side
files** under a sibling disk path (`_bmad/gate/cost/<gate_id>/`) so the
evidence-Merkle reverification path is unaffected.

Tests rose 4312 → 4330 (+18). Ruff clean. Audit-floor invariants
still 26-green.

## What shipped

### `core/innovation/cost_evidence.py` (new, 433 LOC)

Per-collector cost evidence — disk emission plus a load surface.
Closed public API exported via `__all__`:

- `GateCostReport` — dataclass capturing the gate-level rollup
  (`gate_id`, `session_usage`, `attribution_mode`, `total_cost_usd`,
  `collector_count`, `emitted_at_utc`).
- `CostEvidenceError` — single error type for misuse (empty
  collector list, unknown attribution mode, unsupported `tool-calls`
  mode today).
- `VALID_COST_ATTRIBUTION_MODES` — closed vocabulary
  `{"duration", "uniform", "tool-calls"}` — `tool-calls` is reserved
  for a future milestone and raises today.
- `emit_gate_cost_report(gate_id, project_root, session_usage,
  collector_outcomes, attribution_mode="duration")` — writes the
  rollup `summary.json` plus one `<collector_id>.json` per collector
  under `_bmad/gate/cost/<gate_id>/`. Atomic writes via
  `core/atomic_io.write_atomic_text`. Empty collector list and
  unknown attribution mode raise BEFORE any directory is created so
  invalid input never leaves a half-written tree. Zero-duration
  sessions silently fall back to `"uniform"` and the *actual* mode
  used is recorded in `summary.json` so auditors can distinguish.
- `load_gate_cost_report(gate_id, project_root) -> GateCostReport`
  and `load_collector_cost_share(gate_id, project_root,
  collector_id) -> CollectorCostShare` — symmetric read paths.
- `get_cost_root_dir`, `summary_path`, `collector_cost_path` —
  path helpers exported for downstream tooling that walks the cost
  tree.

Disk layout — **sibling** of `_bmad/gate/evidence/`, never a child:

    _bmad/gate/cost/<gate_id>/summary.json
    _bmad/gate/cost/<gate_id>/<collector_id>.json

The sibling placement is load-bearing — listing the evidence tree for
Merkle reverification (N5 surface) must remain byte-identical with or
without cost evidence present.

### `core/gate_orchestrator.run_production_gate` — additive kwarg

Single new OPTIONAL kwarg: `session_usage: UsageMetrics | None = None`.
When `None` (the default), the gate path is byte-identical to the
prior baseline — no new disk writes, no new `gate_file` fields. When a
caller supplies usage:

1. The orchestrator captures `collector_outcomes` from
   `_run_collectors` (this list is already computed; we just
   forward it).
2. After the lineage-root stamp (N5/C2 ordering preserved),
   `emit_gate_cost_report` is called.
3. On success, `gate_file["cost_total_usd"]` is added.
4. The whole emission block is wrapped in `try/except Exception` —
   a disk failure cannot abort an in-flight gate. Cost evidence is
   observability, not gating.

The orchestrator signature change is **purely additive** — every
existing keyword path keeps its old default, every existing call site
keeps working unchanged.

### `core/system_gate.run_system_gate` — symmetric wiring

Same OPTIONAL `session_usage` kwarg, same try/except wrap, same
conditional `cost_total_usd` field. Symmetry matters: anything the
production gate path emits, the system-gate path must emit too, so
operator scripts can pivot between the two without losing cost
observability.

### `GateFile` — additive `cost_total_usd` field

Conditional on the kwarg being supplied. When the gate is invoked
without `session_usage`, the field is absent from the persisted
`gate_file.json`. This means the existing evidence-record schema
(`gate_schema.make_evidence_record`) is **untouched** — cost data
never lives on an evidence record. The frozen-gate-surface doc
(`docs/spec/frozen-gate-surface.md`) was updated to document the new
conditional field and the new public surface from
`cost_evidence.py`.

## Sum-of-shares invariant preserved end-to-end

The N7 unblocker established the bit-exact invariant: for integer
token counts, the per-collector `CollectorCostShare` rollup sums to
exactly the session total — float-rounding drift from weighted modes
is absorbed into the final share. C3 preserves this guarantee
end-to-end:

1. The N7 attribution helpers
   (`core/innovation/cost_attribution.py`) compute the integer-exact
   distribution.
2. `emit_gate_cost_report` writes each `CollectorCostShare` to its
   own `<collector_id>.json` file, byte-identical to the in-memory
   dataclass.
3. `load_collector_cost_share` round-trips each share back to the
   same `CollectorCostShare` instance.
4. Test
   `tests/test_cost_evidence.py::test_sum_of_shares_invariant_preserved`
   verifies the rollup loaded from disk still sums to the original
   session total token-for-token, across both `duration` and
   `uniform` modes, including the zero-duration-fallback path.

No frozen-surface helper was modified to make this hold — the
invariant is a property of the existing N7 code paths, and C3 just
serialised/deserialised them faithfully.

## Tests

`tests/test_cost_evidence.py` — 18 new tests grouped by concern:

- **Emission unit tests (8):** default-mode duration attribution;
  zero-duration fallback explicitly recorded in `summary.json`;
  unknown attribution mode raises `CostEvidenceError` before any
  directory is created; empty collector list raises before disk
  touch; `tool-calls` mode raises today; round-trip
  `GateCostReport` and `CollectorCostShare`; sum-of-shares
  invariant after disk round-trip; per-collector cost paths use
  canonical id sanitisation.
- **Orchestrator wiring tests (7):** byte-identical baseline when
  the kwarg is omitted; `gate_file["cost_total_usd"]` appears when
  the kwarg is supplied; cost summary + per-collector files exist
  on disk; cost emission failure does not abort the gate
  (try/except); system-gate symmetry — same field, same path;
  lineage-root and cost-root both present when both kwargs
  supplied; cost path is sibling of evidence path (no overlap).
- **Gate-file embed contract (3):** `cost_total_usd` present iff
  `session_usage` provided; field is `float`, not `Decimal`, in
  canonical JSON; field is **absent**, not `null`, when the kwarg
  is omitted (matches the additive-only schema rule).

Test count: 4312 → 4330 (+18). All other suites unchanged.

## Final state

- **HEAD:** `6bf56e4` — `feat(c3): wire cost-attribution into
  orchestrator — per-collector cost files + gate_file
  cost_total_usd`.
- **Tests:** **4330 total**, 0 failing, 2 skipped (pre-existing).
  `+18` net from the 4312 baseline.
- **Ruff:** clean.
- **Audit-floor invariants:** 26 / 26 green
  (`tests/test_audit_regression.py`).
- **Frozen-surface compliance:**
  - `core/telemetry_events.py` — untouched (M01 owner).
  - `core/gate_schema.make_evidence_record` — untouched (cost data
    lives in side files, never on evidence records).
  - `core/usage_parsers/` — untouched (N7 surface frozen).
  - `core/innovation/cost_attribution.py` — untouched (N7 surface
    frozen).
  - `core/innovation/ramr.py` — untouched (read-only consumer per
    hard guardrail).
  - `run_production_gate` / `run_system_gate` — additive kwarg
    only; the drift-watcher (C1) and lineage-root (C2) precedents
    already exist for this pattern.
- **Tags shipped this workflow:**
  - `compat-c3-cost-attribution-wiring` — applied to the C3 feature
    commit `6bf56e4`.
  - `c3-full-wiring-complete` — workflow-completion tag on this
    status report.

## What still requires future work

### Automatic session-output capture from `tmux_runtime` — separate milestone

C3 ships the wiring for cost evidence **when the caller supplies a
parsed `UsageMetrics`**. The matching automation — having the
orchestrator harvest the child-session transcript directly from
`core/tmux_runtime.py`, dispatch it through `core/usage_parsers/`
based on the active `cli_id` from the profile composer, and call
`run_production_gate(..., session_usage=parsed)` without the
operator-level glue — is intentionally deferred:

- The CLI dispatcher (N6.5) already knows which parser to use per
  `cli_id`. The plumbing question is *when* in the gate lifecycle
  the transcript is finalised on disk; today only the production
  Claude Code stop-hook path produces one reliably.
- `core/tmux_runtime.py` is a read-only consumer for now per the
  N6.5 contract; widening it to expose a "finalised transcript
  path" hook is a separate one-milestone scope.
- The fail-soft try/except wrap in `run_production_gate` means a
  caller that *forgets* to plumb usage today simply gets no cost
  evidence — no gate failure, no operator-facing regression.

Estimated as a one-milestone follow-up; unblocked by C3.

### `gate cost` operator CLI

A `story-automator gate cost <gate_id>` subcommand to inspect the
emitted summary + per-collector breakdown is sketched in the N7
status report and remains queued. The disk layout is now stable
(`_bmad/gate/cost/<gate_id>/summary.json` +
`<collector_id>.json`), so the CLI is a pure read-only consumer
exercise.

### Audit-floor invariant for `cost_total_usd` shape

The current audit-floor invariants (`tests/test_audit_regression.py`)
do not yet pin the structural shape of the new conditional field.
Adding one now would over-fit the canonical-JSON ordering before the
`gate cost` CLI ships; deferred until the field has at least one
external consumer, at which point both the field and the disk-layout
get pinned together. Tracked alongside the next audit-floor sweep.

### `tool-calls` attribution mode

`VALID_COST_ATTRIBUTION_MODES` includes `"tool-calls"` but raises
`CostEvidenceError` today — the orchestrator does not yet capture
per-collector tool-call counts during `_run_collectors`. That gap
gets closed when the same milestone that automates transcript capture
also threads tool-call counters through the collector runner.

### Push to remote

This workflow shipped against `bma-d/integration-all` locally. Per
the operator push-cadence convention, batched-push to
`origin/bma-d/integration-all` is a separate operator step — this
workflow does not push.
