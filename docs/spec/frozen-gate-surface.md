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
- Public in-process callback bus. `core/gate_orchestrator.run_production_gate` fires it at 6 lifecycle stages: `pre_gate`, `pre_collect`, `post_collect`, `pre_adjudicate`, `post_adjudicate`, `post_gate`. Registration order = dispatch order; listener exceptions are fail-closed.

### `core/plugins.py` (Path B / N6.4)
- `PLUGIN_MANIFEST_KEYS` — closed allowlist `{name, version, hooks, timeout_s, fail_closed}`; widening requires a spec-level decision.
- `PluginTrustError` — every rejection (Python-import key, unknown key, malformed TOML, non-allowlisted name) raises this single type.
- `PluginRegistry(plugin_dir, allowlist).load_all() -> list[PluginSpec]` — sorted-by-stem deterministic load; partial loads are not allowed.
- `PluginSpec` — frozen dataclass `{name, version, manifest_path, hooks, timeout_s, fail_closed}`.
- Trust-boundary invariant (pinned by `PluginTrustBoundaryInvariant` in `tests/test_audit_regression.py`): no `importlib` / `__import__` / `import_module` in this module's source.

### `core/cli_dispatcher.py` (Path B / N6.5)
- Stop-hook dialect resolver per `cli_id` (currently `claude-code`; `codex` / `gemini` / `none` raise `NotImplementedError` until implemented).
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
- **Soft-limit waiver:** `core/gate_orchestrator.py` is currently 746 LOC pre-B / 834 LOC post-B (against the 500-LOC soft limit). The +88 LOC delta is for B1's two-sided bound (with worked-example comments), B2's two `try / acquire / finally release` wraps around the `get_gate_lock` call sites in `recover_from_crash` and `run_production_gate`, and the supporting imports + module constants. The B2 observability helpers are deliberately extracted into `core/gate_lock_observability.py` (~145 LOC) to converge the LOC budget partially — without that extraction the file would have grown another +145 LOC. The next *broad* refactor that touches `gate_orchestrator.py` is expected to split adjudication/lifecycle into sibling modules (target ≤ 500 LOC).

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

### `core/integration/unified_state.py` (Milestone D / G7)
- `read_unified_state(project_root, story_key, *, observe_only=False, read_lock_timeout=2.0) -> tuple[str, str, bool]` — returns the monomorphic `(sprint_status, phase_value, needs_repair)` triple. Read order is REVERSED from the writer's order (sprint-status first, phase second) so a reader observing the new sprint-status also sees the new phase store. With `observe_only=False` (default) the function MAY write to disk (legacy single-store migration; LWW conflict repair). With `observe_only=True` the function NEVER writes; `needs_repair=True` flags on-disk divergence (conflict, migration-pending, or unknown sprint-status string).
- `write_unified_state(project_root, story_key, sprint_status, phase, *, lock_timeout=10.0) -> None` — atomically writes both stores under `unified_state_lock`. Resolves `story_key` to the canonical dotted id via `normalize_story_key(...).id`; deletes orphan slug-keyed entries from the phase store. Phase store written FIRST, sprint-status SECOND (gap D-R-03 mode (b)).
- `unified_state_lock(project_root) -> filelock.FileLock` — per-project lock at `<implementation_artifacts_dir>/.unified-state.lock`. Exposed for advanced callers that need to bracket multi-row updates.
- `UnifiedStateError(ValueError)` — base; raised on consistency/timeout/cross-fs/round-trip failure.
- `UnifiedStateFileMissingError(UnifiedStateError)` — sprint-status / phase store file absent.
- `UnifiedStateRowMissingError(UnifiedStateError)` — file present but the requested row is absent.

Behavioral invariants: (a) read order = REVERSE of write order; (b) LWW by `st_mtime_ns` with `st_dev` same-volume precondition that runs ONLY inside the resolver (migration path skips it because the phase store is absent); (c) mtime-tie → terminal phase wins, else phase store wins; (d) `observe_only=False` may write to disk (migration / repair); `observe_only=True` never writes; (e) sprint-status writer is text-only regex mutation — no YAML re-serialisation (no `import yaml`); (f) self-cancellation guard: resolver re-reads both files under the lock and only projects if the locked re-read still shows a conflict with the same winner.

Pinned by `tests/test_audit_regression.py::UnifiedStateWriteIsolationInvariant` — any new module under `core/` that calls `write_phase(...)` AND `write_atomic(...)` on a sprint-status path WITHOUT acquiring `unified_state_lock(...)` fails the audit-floor suite.

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
