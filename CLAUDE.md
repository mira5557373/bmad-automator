# CLAUDE.md

## Project

**bmad-story-automator** — portable BMAD `bmad-story-automator` skill/plugin bundle. Python port of `bma-d/bmad-story-automator-go`. Distributed as an npm package, a Claude Code plugin, and a local marketplace catalog entry.

## Tech stack

- Python 3.11+ runtime (no extra deps beyond stdlib plus `filelock` and `psutil`)
- Node entrypoint (`bin/bmad-story-automator`) and npm packaging
- tmux for child-session orchestration
- Bash smoke tests (`scripts/smoke-test.sh`)
- Markdown changelog under `docs/changelog/`
- Linting/formatting via `ruff`; tests via `unittest`; coverage via `coverage`

## Module map

- `skills/bmad-story-automator/` — installable main skill, contains the Python runtime
  - `src/story_automator/core/` — runtime building blocks (telemetry, tmux runtime, policy, verifiers, common helpers)
  - `src/story_automator/core/innovation/` — cross-cutting observability + scoring substrate (spec-drift watcher + persistence, lineage ledger, cost attribution + cost evidence + session usage capture, RAMR, ledger, kernel classifier, adversarial review, replay diff, phase budget, stack risk weights, threshold proposer + apply + decisions + helpers)
  - `src/story_automator/core/usage_parsers/` — provider-specific session-rollout parsers (`claude_jsonl`, `codex_rollout`, `gemini_chat`, `none`, `types`)
  - `src/story_automator/core/integration/` — cross-module integration helpers (e.g. `unified_state.py` for the sprint-phase dual-store unification)
  - `src/story_automator/core/bauto_bridge/` — bmad-auto-pattern compat shims (HookBus shim)
  - `src/story_automator/commands/` — CLI command implementations (orchestrator, orchestrator_parse, state, tmux, validate_story_creation, basic, gate, lineage, etc.)
  - `src/story_automator/adapters/` — adapters such as tmux
  - `scripts/story-automator` — installed helper CLI wrapper
- `skills/bmad-story-automator-review/` — bundled adversarial code-review skill (no Python)
- `tests/` — `unittest` discovery root
- `bin/bmad-story-automator` — npm bin entrypoint
- `install.sh` — installer copying skill folders into a target project's skill roots
- `scripts/smoke-test.sh` — `npm pack` + install smoke harness
- `docs/` — operator docs, plans, specs, changelog
  - `docs/changelog/*.md` — dated changelog entries, controlled vocabulary `[FULL]`, `[LITE]`, `[SKELETON]`, `[DEFERRED]` per M11
  - `docs/superpowers/specs/` — milestone specs
  - `docs/superpowers/plans/` — milestone implementation plans
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` — Claude plugin and marketplace manifests

### Gate subsystem (added by sw run 20260620-191602, m1–m7 + n4/n5/n6.2–n6.7 complete)

The production-ready factory gate. **Read these existing modules before planning any new milestone — interfaces are stable.**

- **Profile (m1)** `core/product_profile.py` — `load_bundled_profile`, `load_effective_profile`, `snapshot_effective_profile`, `required_for_priority`, `rule_for`, `is_story_blocked`, `toolchain_for`; raises `ProfileError`. Default profile in `data/profiles/default.json`, MSME ERP in `data/profiles/msme-erp.json`.
- **Evidence + gate schemas (m2)** `core/gate_schema.py` (`EvidenceRecord`, `CategoryVerdict`, `GateFile`, `Waiver`), `core/evidence_io.py` (canonical JSON + hash chain), `core/gate_audit.py` (`GateDecision`, `GateRendered`, `GateProfileDrift` event helpers — rides `UnknownEvent` forward-compat; do NOT touch `telemetry_events.py`).
- **Trust boundary (m3)** `core/trust_boundary.py`, `core/collector_checkout.py` — fresh checkout @SHA, sandbox env scrub. Collectors run here, never inside the generation child's tree.
- **Collector framework (m4)** `core/collector_registry.py`, `core/collector_runner.py`, `core/collector_config.py`, `core/collector_doctor.py`, `core/diff_scope.py`, `core/profile_bridge.py`. All collectors implement `run(config: CollectorConfig, scope: DiffScope) -> CollectorOutcome`. Registry is profile-aware (kill-switches via `profile.categories_na` + `profile.timeouts`).
- **Collectors (m5–m7)** `core/collectors/{correctness,static,docs,process, security,license,compliance,supply_chain, traceability,api_compat,migrations,performance,accessibility,observability}.py`. Sub-checks in `core/checks/*_check.py`.
- **Stubs ready for m8+**: `core/adjudicator.py`, `core/gate_rules.py` exist as scaffolds; m9 fills them.
- **Orchestrator wiring (m10)** `core/gate_orchestrator.py` (`run_production_gate`, `route_gate_verdict`, `recover_from_crash`, `check_gate_reuse`, `resolve_factory_version`), `core/gate_status.py` (`park_story`, `resume_story`, `list_parked`, `invalidate_gate`, `invalidate_gates_for_target`, `record_mitigation_debt`, `load_mitigation_debt`, `clear_mitigation_debt`), `core/gate_remediation.py` (`EDITABLE_SECTIONS`, `EditAuthorizationError`, `prepare_remediation_tasks`, `write_remediation_to_story`, `validate_edit_authorization`, `request_review_continuation`, `failing_categories_from_gate`), `commands/gate_cmd.py` (`gate_dispatch`, `gate_status_action`, `gate_resume_action`, `gate_invalidate_action`). `production_ready_gate` verifier registered in `success_verifiers.py` VERIFIERS and `runtime_policy.py` VALID_VERIFIERS.

- **Risk-scored readiness (m12)** `core/risk_profile.py` (`VALID_RISK_CATEGORIES`, `RiskProfileError`, `make_risk_entry`, `validate_risk_entry`, `validate_risk_profile`, `risk_score_to_priority`, `aggregate_risk_priority`, `has_unmitigated_risk_9`, `persist_risk_profile`, `load_risk_profile`, `risk_profile_exists`, `risk_profile_to_evidence`, `compute_risk_profile_ref`, `resolve_tea_risk_inputs`; `DEFAULT_RISK_THRESHOLDS`), `core/readiness_gate.py` (`READINESS_VERDICTS`, `resolve_story_blockers`, `format_blocker_summary`, `check_readiness`, `check_epic_readiness`, `validate_story_creation`, `persist_readiness_result`, `load_readiness_result`). `run_readiness_gate` and `run_epic_readiness_gate` added to `gate_orchestrator.py`; `readiness_gate` verifier registered in `success_verifiers.py` VERIFIERS and `runtime_policy.py` VALID_VERIFIERS; `gate readiness` CLI subcommand added to `gate_cmd.py` with audit passthrough.

- **Profile composer (N4)** `core/profile_composer.py` (`compose_profiles`) — the merge authority used by `core/product_profile.load_effective_profile` when overlaying operator profiles on the bundled default. Single source of truth for category-list union, timeout precedence, and `categories_na` semantics; do not re-implement merging in callers.
- **Merkle export (N5)** `core/gate_orchestrator.run_production_gate` emits `evidence_merkle_root` alongside each persisted gate file; the root is computed over canonical-JSON evidence in sorted order so audit replay is deterministic across machines.
- **HookBus (N6.2/N6.3)** `core/bauto_bridge/hookbus_shim.py` is the in-process Python callback bus; `core/gate_orchestrator.py` fires it at 6 lifecycle stages (`pre_gate`, `pre_collect`, `post_collect`, `pre_adjudicate`, `post_adjudicate`, `post_gate`). Registration order = dispatch order; exceptions in a listener are fail-closed per HookBus contract.
- **Plugin registry (N6.4)** `core/plugins.py` — declarative-only, TOML-manifest plugin index. `PLUGIN_MANIFEST_KEYS` is the closed allowlist `{name, version, hooks, timeout_s, fail_closed}`; `PluginTrustError` rejects any manifest carrying `python_module` / `py_module` (Python-import keys are reserved precisely so an upstream engine cannot silently re-enable them).
- **CLI dispatcher (N6.5)** `core/cli_dispatcher.py` (~545 LOC, already past the 500-LOC soft limit — a further split is now indicated) + sibling `core/cli_dispatcher_invokers.py` (~471 LOC) — resolves stop-hook dialects per `cli_id` (`claude-code`, future `codex`/`gemini-cli`; the `none` token is a `hook_dialect` value, not a `cli_id`) and falls back to a lie-detector when the child reports success without a baseline-commit advance. `_default_invoker` in `cli_dispatcher.py` is a thin shim that delegates to `cli_dispatcher_invokers.default_invoker`, where the per-`cli_id` concrete invokers live (`claude_code_invoker` wires into `core/tmux_runtime.py` as a read-only consumer of its existing public surface).
- **Action enum (N6.6)** `core/action_enum.py` — `Literal` type for verifier actions consumed by `route_gate_verdict` and `success_verifiers.production_ready_gate`; closed vocabulary `{"continue", "remediate", "park", "halt"}`.

### Recently shipped (sessions 2026-06-23 + 2026-06-24)

The following milestones landed in addition to the gate subsystem
above; all under the additive-only contract (optional kwargs,
optional `gate_file` fields, optional CLI subcommands).

- **Spec-drift watcher (C1 + follow-up)** `core/innovation/spec_drift_watcher.py` (MVP) + `core/innovation/spec_drift_persistence.py` (disk-backed baseline + JSONL events). New OPTIONAL `drift_watcher` kwarg on `run_production_gate`; polled twice per gate (pre-collect + post-evaluate); failures inside `poll()` are swallowed (drift telemetry can never abort a gate).
- **Cross-genre lineage ledger (C2 + follow-up + CLI)** `core/innovation/lineage_ledger.py` — brainstorm → gate chain with disk persistence under `_bmad/lineage/`. New additive `lineage_root: str` field on `gate_file`. `lineage` is wired as a top-level CLI command with five read-only subcommands (`show`, `entry`, `stats`, `verify`, `orphans`).
- **Cost evidence (N7 + C3)** `core/innovation/cost_attribution.py` (helper substrate) + `core/usage_parsers/{claude_jsonl,codex_rollout,gemini_chat,none,types}.py` (provider-rollout parsers) + `core/innovation/cost_evidence.py` (per-collector `summary.json` + `<collector_id>.json` under `_bmad/gate/cost/<gate_id>/`) + `core/innovation/session_usage_capture.py` (automatic session-usage capture closing the cost loop end-to-end). New OPTIONAL `session_usage` kwarg on `run_production_gate` and `run_system_gate`; new CONDITIONAL `cost_total_usd: float` field on `gate_file` (present only when caller opts in AND emission succeeds).
- **Trust-boundary audit-key scrub (D-04 + follow-up)** `core/audit_env_scrub.py` — sibling module hosting `scrub_env_for_subprocess`; the AST audit-floor invariant skips whichever module defines the helper, so the split is rename-proof. `core/audit.py` re-exports the symbol for the ~25 existing call sites.
- **Gate-lock observability (L1 + L2 + B)** `core/gate_lock_observability.py` — `GateLockTimeoutError(filelock.Timeout)` carrying `lock_file`, `holder` (PID + started_at + hostname), `timeout_s`; used at all three `get_gate_lock` call sites (`gate_orchestrator.py` x2 + `system_gate.py` x1). PID-reuse hardening via `psutil.create_time()` two-sided bound on legacy markers.
- **Unified sprint-phase store (G7 / D-implement)** `core/integration/unified_state.py` — `read_unified_state` / `write_unified_state` / `unified_state_lock`; read order is REVERSED from write order so a reader observing the new sprint-status also sees the new phase store. Pinned by `UnifiedStateWriteIsolationInvariant` (audit-floor test-method count 24 → 26 at the time of landing; equivalent invariant-class count was 7 → 8).
- **Evidence-bundle memoization (K-2)** `core/evidence_cache.py` — `cached_load_evidence_bundle` + `invalidate_evidence_cache`; in-process cache keyed by `(str(project_root), gate_id)` with explicit invalidation fired by `evidence_io.persist_evidence_record`. Reads return a deep-copied `list[dict]` so caller mutations cannot poison subsequent hits. Observability-only — no behavior change. Imported from `evidence_io.py`, `verdict_engine.py`, and six call sites in `gate_orchestrator.py`.
- **Quarantine evidence cleanup (K-5)** quarantine-under-lock + rmtree-outside-lock + startup janitor for orphaned quarantine trees.
- **N7.1 tmux→dispatcher migration** `commands/tmux.py::_spawn` is feature-flagged behind `BMAD_AUTO_USE_CLI_DISPATCHER`. Flag off (default) ⇒ byte-identical to pre-N7.1; flag on ⇒ routed through `cli_dispatcher.dispatch_session`.
- **Self-improving gate (C5)** `core/innovation/threshold_proposer.py` + `core/innovation/threshold_apply.py` + `core/innovation/threshold_decisions.py` — close the observation→action loop on existing drift telemetry by auto-emitting `ThresholdProposal`s against `core/gate_rules.PRIORITY_THRESHOLDS`. Proposer is advisory; nothing in `core/` may mutate source automatically (pinned by `ThresholdApplyIsolationInvariant`'s binding-tracking AST walker). Apply path is a single explicit operator CLI call (`story-automator calibration apply --proposal-id <id> --confirm <8-hex-slug>`) that performs an AST-located, BOM-aware, surgical byte splice with `find_spec(target_module).origin` resolution, anti-drift pre-write `ast.literal_eval` cross-verify, pre-mutation backup, and post-splice `ast.parse` re-validation with restore-on-failure. Every decision (`accept`/`reject`/`superseded`/`confirm_failed`) is recorded in `_bmad/calibration/decisions.jsonl` via durable `os.open(O_APPEND) + os.fsync` under `.calibration.lock`. New IN-MEMORY-ONLY gate-file fields: `threshold_proposal_ref` (16-hex id or `""`) + `threshold_proposer_error` (exception class name on failure). New `GateThresholdProposalAudit` in `gate_audit._AuditEvent` — `core/telemetry_events.py` untouched. New CLI subcommands: `propose`, `list-proposals`, `show`, `apply`, `reject` (bare `calibration` invocation byte-identical, pinned by golden fixture). Drift-band proposals registered but DEFAULT OFF (`enable_drift_band_proposals=False`).
- **Worktree-per-unit isolation (G2)** `core/collector_isolation.py` + sibling `core/collector_isolation_outcomes.py` (~139 LOC of pure outcome-reifier helpers — `make_error_outcome`, `error_outcome`, `crash_outcome`, `audit_timeout_outcome` — extracted to keep the parent under the 500-LOC soft limit after the AC-I-13 / AC-I-14 fold-in; the helpers do NOT call `run_collectors_per_unit` so do NOT need an audit-floor dispatch exemption) — new public surface `IsolationMode = Literal["shared", "per_unit"]`, `DEFAULT_MAX_WORKERS=4`, `MAX_PARALLEL_CEILING=16`, `ESTIMATED_PER_WORKER_BYTES=256*1024*1024`, `ADD_TIMEOUT_PER_UNIT_S=90`, `run_collectors_per_unit(...)`. Opt-in `isolation_mode="per_unit"` runs each collector inside its own fresh `git worktree --detach @SHA` checkout via a bounded `ThreadPoolExecutor` (RAM-aware clamp via `psutil.virtual_memory()`). New OPTIONAL `isolation_mode` + `max_workers` kwargs on FOUR wiring sites: `run_production_gate`, `run_system_gate`, `_run_collectors`, `run_gate_collectors` — defaults preserve byte-identical behavior. Worker boundary catches `BaseException`, reifies as `_crash_outcome`, and re-raises after outcome collection (1:1 outcomes-to-collectors invariant). `KeyboardInterrupt` drains the queue via `pool.shutdown(wait=False, cancel_futures=True)` and lets in-flight subprocesses finish to their per-category timeout. `AuditLockTimeout` is retried once before reifying as `_audit_timeout_outcome`. Mode-mode equivalence is CATEGORY-VERDICT-level (not byte-level): `duration_ms`, `evidence_merkle_root`, `evidence_bundle_hash`, `cost_total_usd` differ between modes by design. `core/collector_checkout.create_collector_checkout(...)` gains `name_hint` + `add_timeout` kwargs + bounded retry on transient git lock errors. `core/worktree_recovery.recover_orphan_worktrees(...)` gains `per_unit_window_s` safety-margin kwarg. Pinned by `WorktreePerUnitIsolationInvariant` (4 sub-tests; bumps audit-floor invariant-class count 10 → 11) — rejects `os.chdir`, `os.environ` mutations, `signal.signal`, AND any `_bmad/*.lock` acquisition inside `core/collector_isolation.py`.

### `run_production_gate` additive kwargs (cumulative)

The nine OPTIONAL kwargs accumulated by Path B + the C1/C3/C5/G2
follow-ups. All default to off / `None` / `"shared"`; every existing
call site keeps its byte-identical behavior:

- `baseline_sha: str | None = None` — for the lie-detector (Phase 1).
- `fail_closed: bool = False` — phase-2 error-status forces FAIL.
- `enable_pre_gate_verifier: bool = False` — phase-3 inline checks.
- `result_json_path: str | Path | None = None` — phase-2 schema-pinned `result.json` output.
- `drift_watcher: SpecDriftWatcher | None = None` — C1 follow-up.
- `session_usage: UsageMetrics | None = None` — C3 cost-attribution.
- `threshold_proposer: ThresholdProposer | None = None` — C5 self-improving gate.
- `isolation_mode: Literal["shared", "per_unit"] = "shared"` — G2 worktree-per-unit isolation (default `"shared"` preserves byte-identical pre-G2 behavior).
- `max_workers: int = 4` — G2 bounded parallelism for `per_unit` mode (RAM-aware clamp applied at the boundary; type-validated even in `shared` mode).

`enable_lie_detector: bool = False` is the tenth Phase-1 kwarg
predating this session; listed here for completeness.

**Shared invariants for every collector** (verified by existing tests — don't break them):
1. Output is `CollectorOutcome` with `status ∈ {ok, violation, error, timeout}` (fail-closed: error/timeout never count as PASS).
2. Subprocess invocations use `subprocess.run(timeout=…)` honoring `profile.timeouts[category]`; `psutil` SIGKILL on expiry.
3. Evidence is written via `core/evidence_io.py` (canonical JSON, hash-chained into audit).
4. No new Python deps beyond stdlib + `filelock` + `psutil` (Hard guardrail).
5. 500-LOC soft limit per module (split if approaching).

When planning a new milestone, run `grep -rn 'class\\|def ' skills/bmad-story-automator/src/story_automator/core/collectors/ | head` before designing interfaces — chances are the convention already exists.

**Path B compat milestone tags** (engine-adoption-decision; each lands as one tagged commit):
`compat-n4-*` (profile composer), `compat-n5-*` (Merkle evidence root), `compat-n6-3-*` (HookBus orchestrator wiring), `compat-n6-4-*` (declarative plugin registry), `compat-n6-5-*` (CLI dispatcher + stop-hook dialects), `compat-n6-6-*` (Action enum), `compat-n6-7-docs-and-floor` (this sweep), and `compat-path-b-complete` closes the series.

## Conventions

- Conventional Commits for every commit
- Every commit carries a `Generated-By:` git trailer naming the model
- Branch naming `bma-d/<milestone-slug>` for milestone work
- One PR per milestone; milestones numbered M01..MNN
- Docs-only milestones never modify Python sources, tests, or telemetry types
- Changelog entry heading syntax: `## YYMMDD[-HH:MM:SS] - [TAG] Title` where `TAG` is one of the closed four-tag vocabulary
- File size soft limit: 500 LOC per Python module
- Run `npm run verify` (test:python, pack:dry-run, test:cli, test:smoke) before any release-style commit

## Hard guardrails

- Do NOT add Python imports beyond stdlib, `filelock`, `psutil` without an explicit spec waiver
- Do NOT add a fifth changelog vocabulary tag inside M11 — that requires a separate follow-up spec
- Do NOT touch `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` outside its owning milestone (M01)
- Do NOT rewrite the prose body, bullet content, file list, or QA notes of any historical changelog entry — only dated heading lines may change during retroactive audits
- Do NOT modify `### Summary`, `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Files`, `### QA Notes`, or any other sub-section heading when applying tags — tags only attach to dated entry headings matching `^##+ \d{6}`
- Do NOT introduce trailing whitespace, whitespace-only churn, or line-ending changes when editing Markdown
- Do NOT delete, merge, reorder, split, or re-date any historical changelog entry
- Quality gates must remain portable across Windows git-bash, WSL Ubuntu, and Linux CI without modification
- All four tag strings are uppercase ASCII letters only
