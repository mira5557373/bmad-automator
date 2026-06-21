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

### `data/profiles/`
- `default.json` and `msme-erp.json` schemas: `{version, id, snapshot, seed_template, toolchain, matrix, categories, categories_na, rules, invariants, cost_tier, timeouts, forbidden_until}` — additive fields only.

## Frozen behaviors (the four audit invariants)

These are pinned by `tests/test_audit_regression.py`. Every adoption PR must keep that suite green.

| Audit fix | Invariant |
|---|---|
| `e5a8c55` | `can_reuse_gate_file` re-checks **every** waiver's `expires_at` against current time on **every** reuse; expired → `(False, reason)` even when sha/profile/factory all match. |
| `fcbe17e` | `read_gate_marker` raises `GateMarkerCorruptedError` on malformed JSON / non-object shape. `recover_from_crash` returns `{recovered: False, quarantined: True, quarantine_dir, corruption_reason}` and **moves** evidence under `_bmad/gate/quarantine/<ts>/` rather than deleting it. |
| `2bf44f3` | `route_gate_verdict(..., story_path=…)` calls `write_remediation_to_story(story_path, tasks)` on FAIL; descriptor carries `tasks_persisted: bool` and surfaces `persist_error` rather than silently dropping tasks. |
| `1069d86` | `production_ready_gate` on FAIL resolves `story_path` via `artifact_paths.resolve_story_artifact_path`, calls `route_gate_verdict`, and exposes the full descriptor under `result["remediation"]`. Threading of `remediation_cycle` / `max_cycles` / `has_unmitigated_risk_9` from `contract["config"]`. |

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
| 2 | result.json schema + worktree_recovery + fail_closed flag + api_version stamp | in progress |
| 3 | Pre-gate verifier module wiring 6 inline checks (feature-flagged off by default) | after 2 |
| 4 | TUI watcher + optional Textual extras group | deferred — open question on pyproject location |
| 5 | CLIProfile dataclass + stop_hooks dispatch | deferred — open question on Codex/Gemini timing |
| 6 | Action enum + plugin settings overlay | deferred — pairs with 5 |
