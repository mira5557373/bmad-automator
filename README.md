# bmad-story-automator

Portable BMAD `bmad-story-automator` skill/plugin bundle plus a Python
port of `bma-d/bmad-story-automator-go`. Ships as an npm package, a
Claude Code plugin, and a local marketplace catalog entry, with a
production-grade evidence-collecting gate subsystem written in Python
(stdlib + `filelock` + `psutil` only).

The repository contains:

- `skills/bmad-story-automator/` — installable skill carrying the
  Python runtime (`src/story_automator/...`), the gate subsystem,
  collectors, verifiers, and CLI commands.
- `skills/bmad-story-automator-review/` — bundled adversarial
  code-review skill.
- `bin/bmad-story-automator`, `install.sh`, `.claude-plugin/` — npm
  bin entrypoint, installer, and plugin / marketplace manifests.
- `docs/` — operator-facing docs, milestone specs / plans, dated
  changelog entries under `docs/changelog/`, and audit status reports
  under `docs/audit/`.

## What shipped this session (2026-06-23 + 2026-06-24)

This session closed out the cost / lineage / drift observability arc
plus the operability + bug-sweep cleanup that preceded it. Highlights:

- **C1 / C2 / C3** — the cross-genre observability triple landed:
  `SpecDriftWatcher` (`core/innovation/spec_drift_watcher.py`) with
  optional disk-backed baselines via
  `core/innovation/spec_drift_persistence.py`; cross-genre artifact
  lineage ledger (`core/innovation/lineage_ledger.py`) with disk
  persistence + a `lineage` top-level query CLI; per-collector cost
  evidence (`core/innovation/cost_evidence.py`) with automatic
  session-usage capture
  (`core/innovation/session_usage_capture.py`).
- **N7 unblocker** — usage parsers under
  `core/usage_parsers/{claude_jsonl,codex_rollout,gemini_chat,none}.py`
  plus the `core/innovation/cost_attribution.py` substrate.
- **L1 / L2 / L1-followup** — gate-marker concurrency hardened via
  filelock + targeted quarantine + PID liveness; lock now also
  protects `system_gate.run_system_gate`.
- **Round-1 / Round-2 / Round-3 bug sweeps** — multi-lens adversarial
  sweeps; deferred-batch follow-ups landed (A-follow, M-3
  fsync-parent-dir for atomic rename durability, L-docstring gaps).
- **D-04 + D-04 follow-up** — `BMAD_AUDIT_KEY` scrubbed from
  subprocess env at the trust boundary; helper extracted into
  `core/audit_env_scrub.py` (rename-proof AST invariant).
- **K-2 + K-5** — evidence-bundle memoization with explicit
  invalidation; quarantine-under-lock + rmtree-outside-lock with
  startup janitor.
- **G7 (D-implement)** — sprint-phase dual-store unification
  (`core/integration/unified_state.py`) with reversed read/write
  order and self-cancellation guard.
- **Path B compat** — N4 (`profile_composer`), N5 (Merkle export),
  N6.3 (HookBus orchestrator wiring), N6.4 (declarative plugin
  registry), N6.5 (CLI dispatcher), N6.6 (Action enum), N7.1
  (feature-flagged tmux→dispatcher migration).
- **Operability batch (B)** — `psutil.create_time()` bound on legacy
  markers, `GateLockTimeoutError` carrying holder PID + started_at +
  hostname, opt-in `.githooks/pre-commit`.

Tests: 4070 at session start → 4720 passing at HEAD (the session
closed at 4348; C5 + G2 + post-session bug-fix rounds landed afterward
and added ~372 more tests).
Ruff clean. Audit-floor invariants: 24 → 26 (G7 added two
write-isolation invariants). Zero new Python dependencies. No edits
to `core/telemetry_events.py`. See `CHANGELOG.md` and the per-workflow
status reports under `docs/audit/` for the dated trail.

## Quick start (Python gate API)

The production-ready gate is invoked via
`core.gate_orchestrator.run_production_gate`. The signature stays
purely additive — all the new this-session kwargs default to `None`
or off, so existing callers keep their byte-identical behavior:

```python
from story_automator.core.gate_orchestrator import run_production_gate

result = run_production_gate(
    project_root,
    gate_id,
    commit_sha=commit_sha,
    target={"kind": "story", "id": story_key},
    profile=profile,                  # core.product_profile.load_effective_profile(...)
    factory_version=factory_version,  # core.gate_orchestrator.resolve_factory_version()
    registry=registry,                # core.collector_registry.CollectorRegistry
    # --- session-2026-06-23 additive kwargs (all OPTIONAL, default off) ---
    enable_lie_detector=False,        # phase-1 baseline-commit drift check
    baseline_sha=None,                # str — for the lie-detector
    fail_closed=False,                # phase-2 error-status forces FAIL
    enable_pre_gate_verifier=False,   # phase-3 inline checks
    result_json_path=None,            # phase-2 schema-pinned result.json output
    drift_watcher=None,               # core.innovation.spec_drift_watcher.SpecDriftWatcher
    session_usage=None,               # core.innovation.cost_attribution.UsageMetrics
    threshold_proposer=None,          # core.innovation.threshold_proposer.ThresholdProposer (C5)
    isolation_mode="shared",          # G2 — "shared" (default) or "per_unit" worktree-per-unit isolation
    max_workers=4,                    # G2 — bounded parallelism for per_unit mode (RAM-aware clamp)
)
```

When `session_usage` is supplied, per-collector cost files land under
`_bmad/gate/cost/<gate_id>/` and the resulting gate file carries an
additional `cost_total_usd` field. When `drift_watcher` is supplied,
the watcher is polled twice (pre-collect, post-evaluate) and a
`SpecDriftEvent` is recorded if drift is detected.

For symmetry, `core.system_gate.run_system_gate` accepts the same
`session_usage` kwarg and emits the same `cost_total_usd` field.

## Operator CLI

The `lineage` command is wired at top level for read-only inspection
of the persisted lineage ledger under `_bmad/lineage/`:

```
PYTHONPATH=skills/bmad-story-automator/src \
  python3 -m story_automator lineage --help
```

Subcommands: `show`, `entry`, `stats`, `verify`, `orphans`. All
read-only; output is canonical JSON with alphabetically-sorted keys
for byte-deterministic diffs across machines.

The `gate` subtree (status, resume, invalidate, readiness) is
unchanged from prior releases.

## Frozen public surface (contract source)

The authoritative "what not to break" list for the gate subsystem
lives at [docs/spec/frozen-gate-surface.md](docs/spec/frozen-gate-surface.md).
Every adoption PR must keep that surface byte-stable (extensions /
new OPTIONAL kwargs are permitted, renames / removals / signature
narrowings are not). The five frozen behaviors (four audit fixes plus
the Path B plugin trust-boundary) are pinned by
`tests/test_audit_regression.py` — keep that suite green.

## License

See [LICENSE](LICENSE) and [SECURITY.md](SECURITY.md).
