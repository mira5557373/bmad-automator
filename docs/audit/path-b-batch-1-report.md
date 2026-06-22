# Path B — Batch 1 Status Report

**Date:** 2026-06-22
**Branch:** `bma-d/integration-all`
**HEAD:** `b9f9c9b` (`feat(compat): N6.4 — declarative-only plugin registry`)
**Decision doc:** `docs/spec/2026-06-22-engine-adoption-decision.md`

## Summary

- **Tests baseline:** 3825 passing at `6190d96` (post N6.2).
- **Tests current:** 3880 passing, 2 skipped, 0 failures.
- **Net delta:** +55 tests across this batch.
- **Items completed (5):** N5, N4, N6.3, N6.6, N6.4.
- **Items deferred (2):** N6.5 (cli_dispatcher), N6.7 (docs sweep).
- **Commits shipped:**
  - `c7a4194` — N5 Merkle export
  - `39de591` — N4 profile_composer migration
  - `2598442` — N6.3 orchestrator HookBus wiring
  - `03ee7c1` — N6.6 Action Literal type
  - `b9f9c9b` — N6.4 declarative plugin registry
- **Tags published (all reachable from HEAD):**
  - `compat-n3-ramr-review-wired`
  - `compat-n4-profile-composer-migration`
  - `compat-n5-merkle-export`
  - `compat-n6-3-orchestrator-hookbus`
  - `compat-n6-4-plugin-registry`
  - `compat-n6-6-action-enum`

## Per-item outcome

### N5 — Merkle root export in gate file (`c7a4194`)

**Shipped:** Evidence Merkle root (already chained in `evidence_io.py`) is now surfaced on the rendered `GateFile`. The hash chain that has long been written to the audit log is now also published in the gate artifact, closing G5 (external Merkle-witness interop).

**Key design decisions:**
- Re-used the existing hash-chain machinery; no new crypto primitives.
- Exposed via a single new field on `GateFile`; renderer recomputes from the in-memory evidence list to avoid trusting filesystem state.
- Backward-compatible: legacy gate readers ignore the field.

**Caveats:** None. Single-file change with full test coverage.

### N4 — `load_effective_profile` migration to `profile_composer` (`39de591`)

**Shipped:** `core/product_profile.load_effective_profile` now delegates to `core/profile_composer` for layered profile resolution. Closes G6 (single source of truth for profile composition).

**Key design decisions:**
- Kept the `load_effective_profile` symbol stable so all existing callers and tests are unaffected — pure refactor.
- `profile_composer` becomes the canonical merge implementation; `product_profile` is now a thin facade.
- Snapshot/ref helpers continue to work because composition output shape is preserved.

**Caveats:** None observed. `ProfileError` semantics preserved.

### N6.3 — Orchestrator HookBus wiring (`2598442`)

**Shipped:** The HookBus shim (`core/bauto_bridge/hookbus_shim.py`, shipped N6.2) is now fired at 6 lifecycle stages inside the gate orchestrator. This is Path B M2 — the first behavioral integration of plugin-style hooks into the production gate path.

**Key design decisions:**
- Non-vetoing emission: the shim publishes events; veto routing remains the orchestrator's responsibility (kept hook subscribers out of the hot path for crash recovery).
- Lifecycle stages chosen to mirror engine-adoption decision doc: pre-collect, post-collect, pre-adjudicate, post-adjudicate, pre-render, post-render.
- All emissions ride `UnknownEvent` for forward compat — no edit to `telemetry_events.py`, honoring the M01 lock.

**Caveats:** Plugin authors cannot yet block a verdict from a subscriber callback — that capability lands with N6.4's registry plus a future veto-routing milestone.

### N6.6 — `Action` Literal type for verifier vocabulary (`03ee7c1`)

**Shipped:** Verifier action vocabulary (`pass | fail | retry | escalate | park`) is now a `typing.Literal` alias rather than free-form strings. Path B M5.

**Key design decisions:**
- Chose `Literal` over `Enum` to keep zero-cost interop with existing JSON serialization and to avoid touching the runtime_policy public surface.
- Validation happens at the type-checker boundary; runtime guards in `runtime_policy.VALID_VERIFIERS` remain authoritative for safety.
- One type alias module re-exported wherever the action vocabulary is consumed.

**Caveats:** Static-typing benefit only; runtime behavior unchanged. Mypy strictness not yet wired into CI.

### N6.4 — Declarative-only plugin registry (`b9f9c9b`)

**Shipped:** Plugin registry that loads plugin manifests declaratively under trust-boundary enforcement. Plugins cannot execute arbitrary code at registration time — only their declared hook subscriptions are honored. Path B M3.

**Key design decisions:**
- Declarative-only: manifests describe `{name, version, subscriptions, capabilities}`; no `__init__` side-effects permitted.
- Trust-boundary enforcement: registry loads inside the same fresh-checkout sandbox model used by collectors (`core/trust_boundary.py`, `core/collector_checkout.py`).
- Subscriptions resolve against the HookBus stages established in N6.3, giving a usable end-to-end plugin path even before the cli_dispatcher (N6.5) lands.

**Caveats:** Veto semantics still routed by the orchestrator, not the plugin; full plugin-veto loop requires N6.5 + a follow-up wiring step. No third-party plugins ship in this batch — only the registry and shim.

## What remains in Path B

- **N6.5 — cli_dispatcher:** Externalize CLI subcommand dispatch via the same declarative registry shape, so plugins can contribute commands. Estimated 1 milestone; depends on N6.4 (done).
- **N6.7 — docs sweep:** Operator/plugin-author docs for the HookBus, registry, and Action type. Pure docs milestone; safe to schedule after N6.5 so the docs cover a closed surface.

## What remains elsewhere

### G-items (governance / cross-cut)

- **G2 — worktree-per-unit:** Drive collectors into per-unit worktrees rather than a single sandbox. Larger refactor; touches `collector_checkout.py` and `trust_boundary.py`.
- **G7 — sprint-phase unify:** Consolidate sprint-phase tracking across orchestrator + readiness gate + risk profile. Cross-module rename, needs spec first.

### C-items (compatibility)

- **C1–C5:** Pending. Per `n-items-completion-report.md`, these are blocked behind the Path B engine adoption decision and the plugin registry (N6.4) which is now in place — re-evaluate scope.

## Recommended next-up

1. **N6.5 (cli_dispatcher)** — natural continuation of N6.3 + N6.4; completes the plugin extension surface (events + commands). Small-to-medium milestone; tests scaffold already in place.
2. **N6.7 (docs sweep)** — once N6.5 lands, single docs milestone closes Path B for this branch.
3. **C-items re-triage** — re-read the C1–C5 specs against the now-built plugin registry; several may be reducible or already covered.

Holding **G2** and **G7** until C-items are re-triaged — they may inform the worktree-per-unit design.
