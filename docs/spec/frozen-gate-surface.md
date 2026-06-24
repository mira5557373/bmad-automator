# Frozen Gate-Subsystem Public Surface

> **Status:** locked for the duration of bmad-auto pattern adoption (Phases 0–6 below).
> **Scope:** the symbols, fields, and behaviors listed here are public contracts that bmad-auto-pattern PRs MUST preserve by **wrapping**, not by **rewriting**.

This doc is the authoritative "what not to break" list for any adoption work that touches the gate subsystem (m1–m16 + the 4 audit-fix commits e5a8c55 / fcbe17e / 2bf44f3 / 1069d86).

## Frozen modules + public symbols

### `core/gate_status.py`
- `park_story(project_root, gate_id, story_key, reason, overall, *, audit_policy=None, audit_path=None) -> None`
- `resume_story(project_root, gate_id) -> dict`
- `list_parked(project_root, *, state_filter: str | None = None) -> list[dict]`
- `invalidate_gate(project_root, gate_id) -> bool`
- `invalidate_gates_for_target(project_root, target_kind, target_id) -> int`
- `record_mitigation_debt(project_root, gate_id, story_key, categories) -> None`
- `load_mitigation_debt(project_root) -> dict`
- `clear_mitigation_debt(project_root, gate_id) -> None`

### `core/gate_schema.py`
- `GateFile` shape: `{gate_id, schema_version, target, tier, commit_sha, scanner_data_snapshot, profile, factory_version, risk_profile_ref, categories, overall, waivers, evidence_bundle_hash}` — **additive fields only**; no rename, no removal.
- **Additive top-level fields embedded by the orchestrator** (set after `evaluate_gate` returns; consumers must tolerate their presence):
  - `evidence_merkle_root: str` — sha256 hex (64 chars) of the canonical-JSON evidence bundle, or `""` when the bundle is empty. Pinned by N5 (`run_production_gate`).
  - `lineage_root: str` — sha256 hex (64 chars) of the on-disk cross-genre lineage Merkle chain at evaluation time, or `""` when no chain exists on disk. Pinned by C2 follow-up (`run_production_gate` + `run_system_gate`). Reference: `core/innovation/lineage_ledger.load_lineage_root`.
  - `cost_total_usd: float` — **CONDITIONAL** addition. Present only when the caller supplies the `session_usage: UsageMetrics | None` kwarg to `run_production_gate` / `run_system_gate` AND `core/innovation/cost_evidence.emit_gate_cost_report` succeeds in writing the per-collector cost files under `_bmad/gate/cost/<gate_id>/`. Absent (key not in dict) when `session_usage is None` (the default) or when emission raises (best-effort: cost evidence is observability, not gating). Pinned by C3 (`run_production_gate` + `run_system_gate`). Reference: `core/innovation/cost_evidence.emit_gate_cost_report`.
  - `recovery: dict` — **CONDITIONAL** addition. Present only when mid-`run_production_gate` `_recover_from_crash_locked` reports `quarantined=True` (corrupted-marker quarantine succeeded) OR `cleanup_failed=True` (orphan-evidence cleanup failed mid-recovery). Mirrors the operator-facing subset of `recover_from_crash`'s return: `{quarantined, quarantine_dir, corruption_reason, quarantine_error?, cleanup_failed, cleanup_error}`. Absent (key not in dict) on the common no-marker fast path and on routine orphan-reaper recoveries. Closes the §9.2 "loud, not silent" gap at the orchestrator's single integration point so mid-startup quarantines no longer return a silent PASS.
- Factory functions: `make_evidence_record`, `make_timeout_evidence`, `make_llm_evidence_record`, `make_gate_file`, `make_waiver`.
- Validators: `validate_evidence_record`, `validate_gate_file`, `validate_waiver`, `validate_invariant_entry`, `validate_schema_version`.
- `compute_waiver_signature(waiver_fields)` — deterministic over canonical-JSON; signature shape is wire-format.

### `core/evidence_io.py`
- `GateMarkerCorruptedError` — must remain a public exception class; corruption is loud (audit fix fcbe17e).
- `read_gate_marker(project_root) -> dict | None` — None for absent, raises on corruption.
- `can_reuse_gate_file(gate_file, *, commit_sha, profile_hash, factory_version) -> tuple[bool, str]` — MUST re-check every `gate_file.waivers[].expires_at` on every call (audit fix e5a8c55).
- `write_gate_marker(project_root, gate_id, commit_sha) -> Path` — atomic.
- `clear_gate_marker(project_root) -> None`.
- `persist_gate_file(project_root, gate_file) -> Path`.

### `core/gate_remediation.py`
- `EDITABLE_SECTIONS` constant — BMAD dev-story edit-authorization scope; do not widen.
- `write_remediation_to_story(story_path, tasks) -> None` — signature stable; only the Tasks section is touched.
- `prepare_remediation_tasks(gate_file) -> list[dict]`.
- `request_review_continuation(*, story_key, gate_id, cycle, failing_categories) -> dict`.
- `failing_categories_from_gate(gate_file) -> list[str]`.
- `validate_edit_authorization(touched_sections) -> None` — raises `EditAuthorizationError` on violation.

### `core/gate_orchestrator.py`
- `run_production_gate(...)` — full lifecycle entry point.
- `check_gate_reuse(...)` — returns reuse decision + emits `GateProfileDriftAudit` on mismatch.
- `recover_from_crash(project_root) -> dict` — quarantines on corruption (audit fix fcbe17e).
- `route_gate_verdict(project_root, gate_file, *, story_key, ..., story_path=None) -> dict` — `story_path` parameter is the WIRING-001 contract (audit fix 2bf44f3); descriptor includes `tasks_persisted: bool` and optional `persist_error: str`.
- `resolve_factory_version() -> str`.

### `core/success_verifiers.py`
- `production_ready_gate(*, project_root, story_key, output_file, contract) -> dict` — on FAIL drives the BMAD remediation loop via `route_gate_verdict` and returns a `remediation` descriptor (audit fix 1069d86).
- `readiness_gate(...)`.
- `VERIFIERS` dict registration + `runtime_policy.VALID_VERIFIERS` membership.

### `core/audit.py`
- `AuditKeyMissing`, `AuditLockTimeout`, `AuditLog`, `audit_for_policy`, `derive_key`, `load_key_from_env` — chain-key surface; `load_key_from_env` returns `None` when `BMAD_AUDIT_KEY` is absent (pinned by `LoadKeyFromEnvAbsentContractTests`).
- `scrub_env_for_subprocess` — re-exported from `core/audit_env_scrub.py` (see below) for back-compat with the ~25 existing `from story_automator.core.audit import scrub_env_for_subprocess` call sites. Listed in `audit.__all__`; the implementation is NOT defined here.

### `core/audit_env_scrub.py` (D-04 followup — sibling-module split)
- `scrub_env_for_subprocess(env: Mapping[str, str] | None = None) -> dict[str, str]` — D-04 trust-boundary helper. Returns a copy of `env` (or `os.environ` when `None`) with `BMAD_AUDIT_KEY` removed. MUST be passed to every `subprocess.run` / `Popen` / `call` invocation under `core/` + `commands/` as `env=scrub_env_for_subprocess(...)`. The structural invariant is pinned by `tests/test_audit_regression.py::AuditKeyEnvScrubInvariant::test_ast_no_unscrubbed_subprocess_in_core` — any new unscrubbed subprocess call site fails the suite at parse time. The AST scan skips whichever module defines a top-level `scrub_env_for_subprocess` function, so this split is rename-proof.
- `_AUDIT_ENV_KEYS_TO_SCRUB: frozenset[str]` — module-private closed allowlist `{"BMAD_AUDIT_KEY"}`. Widening this set is a security-policy change; do not re-bind from outside.
- `__all__ = ["scrub_env_for_subprocess"]` — only the helper is public; the allowlist is private.

### `data/profiles/`
- `default.json` and `msme-erp.json` schemas: `{version, id, snapshot, seed_template, toolchain, matrix, categories, categories_na, rules, invariants, cost_tier, timeouts, forbidden_until}` — additive fields only.

### `core/profile_composer.py` (Path B / N4)
- `compose_profiles(base, overlay) -> dict` — the merge authority used by `core/product_profile.load_effective_profile`. Defines union semantics for `categories`, precedence for `timeouts`, and `categories_na` carry-over. Callers must not re-implement profile merging.

### `core/bauto_bridge/hookbus_shim.py` (Path B / N6.2)
- Public in-process callback bus. The dispatch sites live in `commands/orchestrator.py` (Path B / N6.3 orchestrator-helper CLI), not in `core/gate_orchestrator.py`. `KNOWN_EVENTS` is the closed allowlist of 6 lifecycle stages: `post_dev_phase`, `pre_review`, `post_review`, `pre_gate`, `post_gate`, `pre_commit`. Registration order = dispatch order; listener exceptions are fail-closed.

### `core/plugins.py` (Path B / N6.4)
- `PLUGIN_MANIFEST_KEYS` — closed allowlist `{name, version, hooks, timeout_s, fail_closed}`; widening requires a spec-level decision.
- `PluginTrustError` — every rejection (Python-import key, unknown key, malformed TOML, non-allowlisted name) raises this single type.
- `PluginRegistry(plugin_dir, allowlist).load_all() -> list[PluginSpec]` — sorted-by-stem deterministic load; partial loads are not allowed.
- `PluginSpec` — frozen dataclass `{name, version, manifest_path, hooks, timeout_s, fail_closed}`.
- Trust-boundary invariant (pinned by `PluginTrustBoundaryInvariant` in `tests/test_audit_regression.py`): no `importlib` / `__import__` / `import_module` in this module's source.

### `core/cli_dispatcher.py` (Path B / N6.5)
- Stop-hook dialect resolver per `cli_id` (currently `claude-code`; `codex` / `gemini-cli` raise `NotImplementedError` until implemented; the `none` token is a `hook_dialect` value, not a `cli_id`, so it is dispatched via the `hook_dialect` axis rather than `cli_id`).
- `_default_invoker` for `claude-code` is read-only-consumer of `core/tmux_runtime.py`'s existing public surface — `core/tmux_runtime.py` is not modified by Path B.
- Lie-detector fallback when the child reports success without a baseline-commit advance.

### `commands/tmux.py::_spawn` (Path B / N7.1) — feature-flagged dispatcher migration
- Environment flag: **`BMAD_AUTO_USE_CLI_DISPATCHER`**. Truthy values (case-insensitive, whitespace-trimmed): `1`, `true`, `yes`, `on`. Everything else — including unset, `""`, `0`, `false`, `no` — falls back to legacy `spawn_session`.
- **Default behavior (flag off): byte-identical to pre-N7.1.** The legacy `spawn_session(session, command, agent, root, mode=runtime_mode())` path runs unchanged. This is the zero-behavior-change shipment contract.
- **Opt-in behavior (flag on):** the spawn is routed through `cli_dispatcher.dispatch_session` with a `SessionIntent` built from the caller's inputs:
  - `intent.story_key` ← CLI-argv `story_id`
  - `intent.phase` ← `<step>-running` (e.g. `dev-running`, `review-running`)
  - `intent.baseline_sha` ← `git -C <root> rev-parse HEAD` (or `""` on failure; non-fatal)
  - `intent.prompt` ← `--command` value
  - `intent.workspace` ← project root
  - `intent.timeout_s` ← `1800.0` (fixed default; runtime-policy plumbing is a later milestone)
  - `profile` ← `cli_profile.claude_default()` (policy-driven selection deferred to a later N7 task)
- **Result translation contract** (`DispatchResult` → legacy `(out, code)` tuple expected by `_spawn`):
  - `result.ok=True` → `(out="", code=0)` — caller prints the session name on success.
  - `result.ok=False` → `(out=result.stderr_tail or f"dispatcher stop_reason={result.stop_reason}", code=1)`.
  - `DispatcherError` (misconfiguration) → `(out=str(exc), code=1)`.
- **Invariant:** both flag states must yield the same `(str, int)` tuple shape; the migration is a behavior-preserving wrapper, not a contract change.

### `core/gate_lock_observability.py` (Milestone B / B2)
- `GateLockTimeoutError(filelock.Timeout)` — exception subclass raised when `get_gate_lock(...)` times out. Stable public attributes:
  - `lock_file: str` (inherited): absolute path of the lock file (NOT a free-form prose message — replaces the broken `raise Timeout(msg)` pattern; gap B-H1).
  - `holder: dict | None`: marker subset `{pid, started_at, hostname}` when the in-flight gate marker is well-formed, or a `{"_state": "missing" | "corrupt"}` sentinel when the marker is absent or unparseable, or `None` on internal lookup error.
  - `timeout_s: float`: the timeout the caller passed to `get_gate_lock`.
- The module's helpers `_describe_lock_holder` and `_handle_gate_lock_timeout` are leading-underscore private (NOT frozen surface); they are used at all three `get_gate_lock` call sites (`gate_orchestrator.py` x2, `system_gate.py` x1) and a future milestone that needs broader observability must promote them explicitly.

### `core/gate_orchestrator.py` (Milestone B / B1 — legacy-marker PID-reuse hardening)
- Module constants `ISO_TRUNCATION_S = 1.0` and `MAX_ORCHESTRATOR_UPTIME_S = 86400.0` define the two-sided bound used by `_recover_from_crash_locked` to validate liveness for legacy markers carrying `started_at` but no `start_time` (per the v2 rule in `docs/superpowers/specs/2026-06-22-operability-batch-design.md`).
- **Soft-limit waiver:** `core/gate_orchestrator.py` historical baseline was 746 LOC pre-B / 834 LOC post-B; current LOC is **1300** at HEAD (against the 500-LOC soft limit). The original +88 LOC post-B delta covered B1's two-sided bound (with worked-example comments), B2's two `try / acquire / finally release` wraps around the `get_gate_lock` call sites in `recover_from_crash` and `run_production_gate`, and the supporting imports + module constants. The subsequent +466 LOC of post-B growth breaks down as: K-5 quarantine-under-lock + janitor (+90), K-2 evidence-bundle memoization (+5), C2 `lineage_root` embed (+8), C1 `drift_watcher` kwarg + double-poll wiring (+30), C3 `session_usage` kwarg + `cost_total_usd` stamp (+35), C5 `threshold_proposer` kwarg + audit event (+44), G2 `isolation_mode` + `max_workers` per-unit fan-out (+31), +60 LOC across three earlier gate-correctness follow-ups (additive-field-on-reuse fix, `_pending_cleanup` drain on every exit path, and quarantine-on-empty-`gate_id`), +90 LOC across five later gate-correctness follow-ups (evidence-cache invalidation on recovery rename, `fail_closed` override on reuse path, `fail_closed` timeout-audit inclusion, finally-OSError swallow to preserve `KeyboardInterrupt`, drift-watcher early-return docstring clarification), and +73 LOC for the round-2 recovery-descriptor surfacing fix (additive `recovery: {...}` subdict on `run_production_gate`'s return when mid-startup `_recover_from_crash_locked` quarantined a corrupted marker OR reported `cleanup_failed`, closing the §9.2 "loud, not silent" gap at the orchestrator's single integration point). The B2 observability helpers remain extracted into `core/gate_lock_observability.py` (~145 LOC). The next *broad* refactor that touches `gate_orchestrator.py` is expected to split adjudication/lifecycle into sibling modules (target ≤ 500 LOC); the +800 LOC overrun on the soft limit makes that split increasingly urgent. **The current LOC value above is a point-in-time snapshot; the binding contract is the symbol surface in this doc, not the LOC count.**

### `core/action_enum.py` (Path B / N6.6)
- `Literal` type for verifier actions consumed by `route_gate_verdict` and `production_ready_gate`; closed vocabulary `{"continue", "remediate", "park", "halt"}`. Adding a value requires a coordinated change in route + verifier + telemetry.

### `core/gate_orchestrator.py` (Path B / N5 — Merkle export)
- `run_production_gate(...)` additionally emits `evidence_merkle_root` on each persisted gate file. Computed over canonical-JSON evidence in sorted order; deterministic across machines.

### `core/innovation/lineage_ledger.py` (C2 follow-up — disk persistence + gate embed)
- Disk layout: `_bmad/lineage/index.json` (alpha-sorted `"<genre>/<slug>"` -> `{path, merkle_root, timestamp_iso, seq}`) + per-entry `_bmad/lineage/<genre>/<slug>.json`. The `seq` field tracks insertion order so readers reconstruct the chain via `seq` sort; the on-disk byte layout stays alpha-deterministic across machines.
- Public additions: `get_lineage_root_dir`, `get_lineage_lock`, `lineage_index_path`, `persist_lineage_entry`, `load_lineage_entry`, `load_lineage_chain`, `load_lineage_root`.
- Concurrency: `persist_lineage_entry` acquires `get_lineage_lock(...)` (filelock at `_bmad/lineage/.lineage.lock`, 60s timeout) for the full write-entry + rewrite-index sequence.
- Crash safety: entry JSON written via `core/atomic_io.write_atomic_text`; index update is skipped when the entry write raises, so the index never advertises a missing payload.
- Corrupt-index policy: `load_lineage_chain` / `load_lineage_root` re-raise `LineageError` (no silent rebuild — audit-chain analog from M04).
- `core/gate_orchestrator.run_production_gate` and `core/system_gate.run_system_gate` embed `gate_file["lineage_root"]` via `load_lineage_root(project_root)` AFTER `evaluate_gate` (and AFTER fail-closed override on the production path). Empty-string sentinel when no chain exists on disk.

### `core/innovation/cost_evidence.py` (C3 — per-collector cost evidence)
- Disk layout: sibling-of-evidence `_bmad/gate/cost/<gate_id>/summary.json` plus one `_bmad/gate/cost/<gate_id>/<collector_id>.json` per collector. Sibling-NOT-child so Merkle reverification of the evidence bundle never sees cost files.
- Public additions: `CostEvidenceError`, `GateCostReport`, `VALID_COST_ATTRIBUTION_MODES`, `emit_gate_cost_report`, `load_gate_cost_report`, `load_collector_cost_share`, `get_cost_root_dir`, `summary_path`, `collector_cost_path`.
- `emit_gate_cost_report(project_root, gate_id, session_usage, collector_outcomes, *, attribution_mode="duration", timestamp_iso=None) -> GateCostReport` — default attribution mode is `"duration"` (collectors already record `duration_ms`); falls back to `"uniform"` when every collector reports zero duration; `"tool-calls"` raises `CostEvidenceError` until the orchestrator captures per-collector tool-call counts. Empty `collector_outcomes` or unknown `attribution_mode` raises `CostEvidenceError` BEFORE touching disk.
- `core/gate_orchestrator.run_production_gate` and `core/system_gate.run_system_gate` accept an optional `session_usage: UsageMetrics | None = None` kwarg. When provided AND collectors produced any outcomes, the orchestrator calls `emit_gate_cost_report` and stamps `gate_file["cost_total_usd"]`. Emission is wrapped in `try/except Exception` so a disk failure cannot abort the gate — the absence of `cost_total_usd` is the operator's signal that emission failed (vs. operator never opted in).

### `core/innovation/threshold_proposer.py` (C5 — self-improving gate)
- Public surface (advisory-only; never auto-applies):
  - `ThresholdProposer(project_root, *, min_evidence_window=5, target_pass_rate_band=(0.80, 0.95), max_delta_pct=5, consecutive_runs=3, enable_drift_band_proposals=False, ttl_hours=168, operator_id="local")` — raises `ProposerConfigError` when `min_evidence_window < consecutive_runs`.
  - `.observe_gate(project_root, gate_file) -> ThresholdProposal | None` — gate-orchestrator hook; deterministic `proposal_id`; idempotent slug + `created_at_iso` preserved on byte-identical re-emit.
  - `.list_proposals(project_root) -> list[ThresholdProposal]`, `.load_proposal(project_root, proposal_id) -> ThresholdProposal`, `.reject_proposal(project_root, proposal_id, reason, operator_id) -> None`.
  - `ThresholdProposal` frozen dataclass — `proposal_id`, `target_module`, `target_symbol`, `target_category`, `target_file_hint`, `selector`, `current_value`, `proposed_value`, `delta`, `rationale`, `evidence_window`, `created_at_iso`, `confirm_slug`, `proposer_config`. Constructor invariant: `type(proposed_value) is type(current_value)`.
- `core/innovation/threshold_apply.apply_threshold_proposal(project_root, proposal_id, *, confirm: str, operator_id: str) -> AppliedThresholdRecord` — single entry point for the surgical AST-located byte splice. `ThresholdApplyError(RuntimeError)` with closed `code` vocabulary `{PROPOSAL_NOT_FOUND, CONFIRM_MISMATCH, PROPOSAL_EXPIRED, STALE_PROPOSAL, MODULE_NOT_RESOLVABLE, LIVE_VALUE_DRIFTED, TYPE_MISMATCH, NON_LITERAL_TARGET, UNSUPPORTED_SELECTOR_KIND, SELECTOR_NOT_FOUND, BACKUP_FAILED, APPLY_REWRITE_INVALID, LOCK_TIMEOUT}`; optional `hint: str` payload.
- `core/innovation/threshold_decisions.{record_decision, load_decisions, latest_decision_for}` + `DecisionRecord` frozen dataclass. Action vocabulary closed at `{accept, reject, superseded, confirm_failed}`. Durable append via `os.open(O_WRONLY|O_CREAT|O_APPEND) + os.fsync` inside the `.calibration.lock` filelock — fsync runs BEFORE lock release.
- Behavioral invariants (pinned by `tests/test_audit_regression.py`):
  - **Advisory-only / never auto-applies.** `ThresholdApplyIsolationInvariant` rejects any `core/` or `commands/` module that calls `apply_threshold_proposal` directly, via alias rebind, via `getattr`, or via `import_module(...).apply_threshold_proposal`. The canonical helper module is exempt (top-level `def apply_threshold_proposal(...)`); CLI handlers are exempt via the structural-recognition `confirm: str` first-non-self argument signature.
  - **In-memory-only gate-file additions.** `gate_file["threshold_proposal_ref"]` (16-hex or `""`) and `gate_file["threshold_proposer_error"]` (exception class name) are set on the returned dict only. The on-disk `_bmad/gate/verdicts/<gate_id>.json` is byte-identical to pre-C5 (matches `evidence_merkle_root` / `lineage_root` / `cost_total_usd` precedent — `persist_gate_file` runs at `verdict_engine.py:272` BEFORE all orchestrator mutations).
  - **No `telemetry_events.py` touch.** `GateThresholdProposalAudit` is a new dataclass under `gate_audit._AuditEvent` riding `UnknownEvent` forward-compat.
  - **Lock isolation.** `ThresholdLockIsolationInvariant` AST-scans `core/innovation/threshold_*.py` and rejects any `FileLock(...)` construction whose first positional or `lock_file=` literal does not end with `.calibration.lock` — co-acquisition with `.gate.lock` / `.lineage.lock` / `.drift.lock` / `.unified-state.lock` is structurally impossible.
  - **Drift-band proposals default OFF.** `inspect.signature(ThresholdProposer.__init__).parameters["enable_drift_band_proposals"].default is False` is pinned.

### `core/integration/unified_state.py` (Milestone D / G7)
- `read_unified_state(project_root, story_key, *, observe_only=False, read_lock_timeout=2.0) -> tuple[str, str, bool]` — returns the monomorphic `(sprint_status, phase_value, needs_repair)` triple. Read order is REVERSED from the writer's order (sprint-status first, phase second) so a reader observing the new sprint-status also sees the new phase store. With `observe_only=False` (default) the function MAY write to disk (legacy single-store migration; LWW conflict repair). With `observe_only=True` the function NEVER writes; `needs_repair=True` flags on-disk divergence (conflict, migration-pending, or unknown sprint-status string).
- `write_unified_state(project_root, story_key, sprint_status, phase, *, lock_timeout=10.0) -> None` — atomically writes both stores under `unified_state_lock`. Resolves `story_key` to the canonical dotted id via `normalize_story_key(...).id`; deletes orphan slug-keyed entries from the phase store. Phase store written FIRST, sprint-status SECOND (gap D-R-03 mode (b)).
- `unified_state_lock(project_root) -> filelock.FileLock` — per-project lock at `<implementation_artifacts_dir>/.unified-state.lock`. Exposed for advanced callers that need to bracket multi-row updates.
- `UnifiedStateError(ValueError)` — base; raised on consistency/timeout/cross-fs/round-trip failure.
- `UnifiedStateFileMissingError(UnifiedStateError)` — sprint-status / phase store file absent.
- `UnifiedStateRowMissingError(UnifiedStateError)` — file present but the requested row is absent.

Behavioral invariants: (a) read order = REVERSE of write order; (b) LWW by `st_mtime_ns` with `st_dev` same-volume precondition that runs ONLY inside the resolver (migration path skips it because the phase store is absent); (c) mtime-tie → terminal phase wins, else phase store wins; (d) `observe_only=False` may write to disk (migration / repair); `observe_only=True` never writes; (e) sprint-status writer is text-only regex mutation — no YAML re-serialisation (no `import yaml`); (f) self-cancellation guard: resolver re-reads both files under the lock and only projects if the locked re-read still shows a conflict with the same winner.

Pinned by `tests/test_audit_regression.py::UnifiedStateWriteIsolationInvariant` — any new module under `core/` that calls `write_phase(...)` AND `write_atomic(...)` on a sprint-status path WITHOUT acquiring `unified_state_lock(...)` fails the audit-floor suite.

### `core/collector_isolation.py` (G2 — worktree-per-unit isolation)
- Public surface:
  - `IsolationMode = Literal["shared", "per_unit"]` — closed vocabulary; widening requires a coordinated change at the four wiring points + the audit-floor invariant.
  - `DEFAULT_MAX_WORKERS = 4`, `MAX_PARALLEL_CEILING = 16`, `ESTIMATED_PER_WORKER_BYTES = 256 * 1024 * 1024`, `ADD_TIMEOUT_PER_UNIT_S = 90` — module-level constants exposed via `__all__`.
  - `run_collectors_per_unit(project_root, gate_id, commit_sha, profile, collectors, *, max_workers=4, audit_policy=None, audit_path=None) -> list[CollectorOutcome]` — the per-unit dispatch target. Returns outcomes sorted ASCII-ascending by `(category, collector_id)`; length 1:1 with input `collectors`.
- Wiring points (additive optional kwargs; defaults preserve byte-identical behavior):
  - `core/collector_runner.run_gate_collectors(..., isolation_mode="shared", max_workers=4)`.
  - `core/gate_orchestrator._run_collectors(..., isolation_mode="shared", max_workers=4)`.
  - `core/gate_orchestrator.run_production_gate(..., isolation_mode="shared", max_workers=4)`.
  - `core/system_gate.run_system_gate(..., isolation_mode="shared", max_workers=4)`.
  - `core/collector_checkout.create_collector_checkout(..., name_hint="", add_timeout=None)` — sanitize-FIRST-truncate-SECOND-LAST-32-chars; bounded retry on transient git lock errors.
  - `core/worktree_recovery.recover_orphan_worktrees(..., per_unit_window_s=0.0)` — operator-supplied post-crash safety margin biasing `effective_min_age = max(min_age_s, per_unit_window_s)`.
- Behavioral invariants:
  - **`shared` is byte-equivalent to pre-G2.** The default path in `run_gate_collectors` is untouched; on-disk `_bmad/gate/verdicts/<gate_id>.json` and the evidence Merkle root are byte-identical to pre-G2 fixtures (pinned by AC-G-01).
  - **`per_unit` is CATEGORY-VERDICT-equivalent — NOT byte-equivalent.** `categories[*].verdict` and `overall` match `shared` for deterministic fixtures; `duration_ms`, `evidence_merkle_root`, `evidence_bundle_hash`, `cost_total_usd` are EXPECTED to differ by construction (parallel + per-collector checkout has different wall-clock and cost distribution). The byte-identical claim is advisory-only on shared mode default.
  - **Worker boundary catches `BaseException`** and reifies as `_crash_outcome`; the original BaseException is re-raised AFTER outcome collection so the returned list is always 1:1 with input collectors and persisted evidence on disk.
  - **`KeyboardInterrupt`** is caught on the main thread (workers never receive it). The pool drains via `pool.shutdown(wait=False, cancel_futures=True)` (queued-but-not-started workers leave NO worktree); in-flight `subprocess.run` calls complete to their per-category timeout; KI is re-raised after outcome collection.
  - **`AuditLockTimeout`** raised by a worker's `run_single_collector` is caught specifically and retried ONCE before reifying as `_audit_timeout_outcome` with `findings=["audit lock timeout after retry"]` (distinguishes slow-disk events from true collector failures).
  - **Lock-isolation invariant.** `core/collector_isolation.py` MUST NOT acquire ANY `_bmad/*.lock`. Pinned structurally by `tests/test_audit_regression.py::WorktreePerUnitIsolationInvariant::test_ast_no_process_global_state_mutation_in_isolation_module` (sub-test 1), which also rejects `os.chdir`, `os.environ` mutations, and `signal.signal` calls.

## Frozen behaviors (the four audit invariants + plugin trust-boundary)

These are pinned by `tests/test_audit_regression.py`. Every adoption PR must keep that suite green.

| Audit fix | Invariant |
|---|---|
| `e5a8c55` | `can_reuse_gate_file` re-checks **every** waiver's `expires_at` against current time on **every** reuse; expired → `(False, reason)` even when sha/profile/factory all match. |
| `fcbe17e` | `read_gate_marker` raises `GateMarkerCorruptedError` on malformed JSON / non-object shape. `recover_from_crash` returns `{recovered: False, quarantined: True, quarantine_dir, corruption_reason}` and **moves** evidence under `_bmad/gate/quarantine/<ts>/` rather than deleting it. |
| `2bf44f3` | `route_gate_verdict(..., story_path=…)` calls `write_remediation_to_story(story_path, tasks)` on FAIL; descriptor carries `tasks_persisted: bool` and surfaces `persist_error` rather than silently dropping tasks. |
| `1069d86` | `production_ready_gate` on FAIL resolves `story_path` via `artifact_paths.resolve_story_artifact_path`, calls `route_gate_verdict`, and exposes the full descriptor under `result["remediation"]`. Threading of `remediation_cycle` / `max_cycles` / `has_unmitigated_risk_9` from `contract["config"]`. |
| `N6.4` (Path B) | `core/plugins.py` rejects `python_module` / `py_module` keys with `PluginTrustError`, holds `PLUGIN_MANIFEST_KEYS` to exactly `{name, version, hooks, timeout_s, fail_closed}`, and contains no `importlib` / `__import__` / `import_module` API call in its source. Pinned by `PluginTrustBoundaryInvariant`. |

## Adoption-PR checklist

Before opening a PR that touches the gate subsystem:

1. `tests/test_audit_regression.py` runs green
2. `tests/test_gate_status*.py`, `test_evidence_io*.py`, `test_gate_remediation*.py`, `test_success_verifiers*.py`, `test_gate_orchestrator*.py` all green
3. `npm run verify` clean (lint + python + pack + cli + smoke)
4. No symbol from the lists above is renamed, removed, or has its signature reduced (extensions/new optional kwargs are fine)
5. New collector output (incl. result.json from Phase 2) carries no timestamps / PIDs / run-IDs that would break determinism
6. `core/telemetry_events.py` untouched (CLAUDE.md hard guardrail — outside the M01 owner milestone)

## Phased adoption plan

Tracking artifact for the bmad-auto pattern ports. Each phase is its own milestone-tag commit.

| Phase | Scope | Status |
|---|---|---|
| 0 | Audit-floor regression net + this frozen-surface doc | done (`phase-0-audit-floor`) |
| 1 | VerifyOutcome + git_utils + baseline-commit lie detector + collector try/except wrapping | done (`phase-1-defensive-primitives`) |
| 2 | result.json schema + worktree_recovery + fail_closed flag + api_version stamp | done (`phase-2-result-schema-and-policy`) |
| 3 | Pre-gate verifier module wiring 6 inline checks (feature-flagged off by default) | done (`phase-3-pre-gate-verifier`) |
| 4 | TUI watcher + optional Textual extras group | deferred → see [docs/spec/2026-06-21-phases-4-6-deferral.md](./2026-06-21-phases-4-6-deferral.md) |
| 5 | CLIProfile dataclass + stop_hooks dispatch | deferred → see [docs/spec/2026-06-21-phases-4-6-deferral.md](./2026-06-21-phases-4-6-deferral.md) |
| 6 | Action enum + plugin settings overlay | deferred → see [docs/spec/2026-06-21-phases-4-6-deferral.md](./2026-06-21-phases-4-6-deferral.md) |
