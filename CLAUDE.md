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
  - `src/story_automator/commands/` — CLI command implementations (orchestrator, orchestrator_parse, state, tmux, validate_story_creation, basic, etc.)
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
- **CLI dispatcher (N6.5)** `core/cli_dispatcher.py` — resolves stop-hook dialects per `cli_id` (`claude-code`, future `codex`/`gemini`/`none`) and falls back to a lie-detector when the child reports success without a baseline-commit advance. `_default_invoker` for `claude-code` wires into `core/tmux_runtime.py` (read-only consumer of its existing public surface). 500-LOC soft limit watched; split into `core/cli_dispatcher_invokers.py` if approached.
- **Action enum (N6.6)** `core/action_enum.py` — `Literal` type for verifier actions consumed by `route_gate_verdict` and `success_verifiers.production_ready_gate`; closed vocabulary `{"continue", "remediate", "park", "halt"}`.

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
