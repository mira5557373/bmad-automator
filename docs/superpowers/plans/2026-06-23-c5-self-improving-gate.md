# C5 — Self-Improving Gate — Implementation Plan

> Source spec: `docs/superpowers/specs/2026-06-23-c5-self-improving-gate-design.md` (rev 2).
> Branch: `bma-d/integration-all`. Conventional Commits + `Generated-By: claude-opus-4-7` + `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailers on every commit.
> No `--no-verify`, no `--amend`, no force-push, no worktree isolation.

## Hard constraints (CLAUDE.md)

- Python 3.11+; stdlib + `filelock` + `psutil` ONLY — no new deps.
- 500-LOC soft limit per Python module; sibling-split if approaching.
- ADDITIVE-only on `run_production_gate` + `gate_file` (in-memory only).
- `core/telemetry_events.py` is FROZEN — do not touch.
- `core/innovation/threshold_*.py` may acquire ONLY `_bmad/calibration/.calibration.lock` — `ThresholdLockIsolationInvariant` pins this.
- Tests:
  ```
  PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.<module>
  ```
- Lint/format:
  ```
  python -m ruff check <paths>
  python -m ruff format --check <paths>
  ```

## Stage dependency graph

```
  s1-decisions ──> s2-proposer ──┬─> s3-apply ──┬─> s4-orchestrator ──> s5-cli ──> s6-invariants ──> s7-docs
                                 │              │
                                 └──────────────┘
```

Each stage's agent reads the spec, implements only the scope below, runs targeted tests, commits, and tags.

---

## Stage 1 — `compat-c5-decisions` — append-only decision ledger

**Scope.** Implement `core/innovation/threshold_decisions.py` per spec §4 (threshold_decisions.py box) + §5.3 (decisions.jsonl shape) + §7.4 ACs. Public surface:

- `record_decision(project_root, proposal_id: str, action: Literal["accept","reject","superseded","confirm_failed"], operator_id: str, operator_note: str = "") -> None`
- `load_decisions(project_root, proposal_id: str | None = None) -> list[DecisionRecord]`
- `latest_decision_for(project_root, proposal_id: str) -> DecisionRecord | None`
- `DecisionRecord` frozen dataclass: `proposal_id`, `action`, `operator_id`, `decided_at_iso`, `operator_note`.
- Lock helpers: `_calibration_lock_path(project_root) -> Path`, `_calibration_dir(project_root, *, create=False) -> Path`.

**Append idiom (durable).** Inside the `.calibration.lock` filelock-acquired region:
```python
fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
try:
    os.write(fd, payload + b"\n")
    os.fsync(fd)
finally:
    os.close(fd)
```
fsync runs BEFORE filelock release so a crash after release cannot lose the write. Mirrors `spec_drift_persistence.append_drift_event` (lines 248-289).

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/innovation/threshold_decisions.py` (~150 LOC)
- `skills/bmad-story-automator/tests/test_threshold_decisions.py` (~160 LOC, ≥7 tests)

**Tests (§7.4).** Append+read; concurrent processes; filter by id; `latest_decision_for`; lock timeout; lazy dir creation; fsync durability (mock release raising).

**Quality gates.**
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/innovation/threshold_decisions.py skills/bmad-story-automator/tests/test_threshold_decisions.py
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_threshold_decisions
wc -l skills/bmad-story-automator/src/story_automator/core/innovation/threshold_decisions.py  # ≤500
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/innovation/threshold_decisions.py \
        skills/bmad-story-automator/tests/test_threshold_decisions.py
git commit -m "$(cat <<'EOF'
feat(c5): decisions ledger (durable jsonl, confirm_failed tracking)

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-c5-decisions -m "feat(c5): decisions ledger (durable jsonl, confirm_failed tracking)"
```

---

## Stage 2 — `compat-c5-proposer` — ThresholdProposer + persistence

**Scope.** Implement `core/innovation/threshold_proposer.py` per spec §3 (multiple rows) + §4 (proposer box) + §5.1 (dataclass) + §5.2 (selectors) + §5.3 (JSON layout) + §7.1 AC-P-00..P-17 + §7.2.

**Public surface.**
- `ThresholdProposer` class with constructor kwargs: `min_evidence_window=5`, `target_pass_rate_band=(0.80, 0.95)`, `max_delta_pct=5`, `consecutive_runs=3`, `enable_drift_band_proposals=False`, `ttl_hours=168`, `operator_id="local"`. Validate `min_evidence_window >= consecutive_runs` else `ProposerConfigError`.
- Methods: `observe_gate(project_root, gate_file) -> ThresholdProposal | None`, `list_proposals(project_root) -> list[ThresholdProposal]`, `load_proposal(project_root, proposal_id) -> ThresholdProposal`, `reject_proposal(project_root, proposal_id, reason, operator_id) -> None`.
- `ThresholdProposal` frozen dataclass (see spec §5.1). Constructor invariant: `type(proposed_value) is type(current_value)`.
- `ProposerConfigError(ValueError)`.

**Algorithm (per spec §3 "Proposal algorithm" + §4 observe_gate flow).**
1. Read `priority` from `gate_file["categories"][target_category]["required"]["priority"]`. Return `None` if NA/missing.
2. Build target registry: maps `(target_symbol, priority, index)` → backing category. v1: all priorities → `"correctness"`.
3. Enumerate `_bmad/gate/verdicts/*.json` via `core.evidence_io.load_gate_file(project_root, gate_id)`; sort by `gate_id` ASCII.
4. Filter: gates where the target category is NA or `actual.coverage_pct` is missing are DROPPED.
5. If matched_count < `min_evidence_window` → return `None`.
6. Take last `min_evidence_window` matching gates.
7. Compute observed pass-rate: `passed = sum(1 for g in window if g.coverage_pct >= current_required_pct) / len(window)`.
8. Tail-of-window check: do the last `consecutive_runs` entries ALL lie outside `target_pass_rate_band`?
   - If all > upper band → propose `min(ceil(observed_mean*100) - current, max_delta_pct)` (raise).
   - If all < lower band → symmetric (lower).
   - Otherwise → return `None`.
9. Quantize float proposals to source-textual precision (count digits after `.` via `ast.get_source_segment` on the located leaf); for int targets, `int(round(...))`. Bound `len(repr(quantized).encode("ascii")) <= 24`.
10. Locate the live `current_value` by `ast.literal_eval` on the leaf Constant (uses the same `_locate_leaf_constant` helper as `threshold_apply.py`, factored out via a shared private helper or duplicated minimally — preference: duplicate the small locator here; `threshold_apply.py` owns the canonical implementation).
11. Compute deterministic `proposal_id = sha256(canonical_json({"target_module", "target_symbol", "selector", "current_value", "proposed_value", "evidence_window"}))[:16]`.
12. Acquire `.calibration.lock` (30s).
13. **Idempotent re-emit:** if `_bmad/calibration/proposals/<proposal_id>.json` exists, read it; preserve its `confirm_slug` and `created_at_iso`; rewrite byte-identical content if needed (no decision appended; no audit emitted).
14. **New proposal:** generate `confirm_slug = os.urandom(4).hex()` (8 hex chars); stamp `created_at_iso = iso_now()`; write via `write_atomic_text`.
15. **Auto-supersede:** for any prior proposal whose `(target_module, target_symbol, selector)` matches, check `latest_decision_for(prior_id)`. Skip if it's `accept` or `reject`. Otherwise append a `"superseded"` decision (under same lock). On supersede-append failure after proposal-write success, write to `_bmad/calibration/.partial_supersedes.jsonl`.
16. Emit `GateThresholdProposalAudit(event="proposal_created", ...)` via `emit_gate_audit` (Stage 4 adds this dataclass — for Stage 2 the proposer will import-then-catch; use a try/except ImportError fallback so this stage builds and tests pass even before Stage 4 lands).
17. Return the `ThresholdProposal`.

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/innovation/threshold_proposer.py` (~350 LOC, must stay ≤500)
- `skills/bmad-story-automator/tests/test_threshold_proposer.py` (~360 LOC, ≥17 tests)

**Tests (§7.2).** 17 tests covering below-window, in-band, above-band, below-band, delta clamp, deterministic id, slug-preserved-on-reemit, drift-band default-off, concurrent writers, lazy dir, missing verdicts dir, dropped gates (NA/missing coverage), `reject_proposal`, auto-supersede (with accept-skip), evidence_window sort by gate_id, `ProposerConfigError`, missing telemetry rationale degradation.

**Quality gates.**
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/innovation/threshold_proposer.py skills/bmad-story-automator/tests/test_threshold_proposer.py
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_threshold_proposer tests.test_threshold_decisions
wc -l skills/bmad-story-automator/src/story_automator/core/innovation/threshold_proposer.py  # ≤500
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/innovation/threshold_proposer.py \
        skills/bmad-story-automator/tests/test_threshold_proposer.py
git commit -m "$(cat <<'EOF'
feat(c5): ThresholdProposer + persistence (priority per-category, deterministic ids, idempotent slug)

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-c5-proposer -m "..."
```

---

## Stage 3 — `compat-c5-apply` — AST-located byte splice

**Scope.** Implement `core/innovation/threshold_apply.py` per spec §3 (AST-located splice + Anti-drift + Resolving target_file + Numeric serialization rows) + §4 (apply box, 20 steps) + §5.4 (AppliedThresholdRecord) + §5.5 (ThresholdApplyError taxonomy — all 13 codes) + §7.3.

**Public surface.**
- `apply_threshold_proposal(project_root, proposal_id: str, *, confirm: str, operator_id: str) -> AppliedThresholdRecord`
- `AppliedThresholdRecord` frozen dataclass (spec §5.4): `proposal_id`, `applied_at_iso`, `operator_id`, `target_file`, `before_path`.
- `ThresholdApplyError(RuntimeError)` with `code: str` attribute and optional `hint: str` attribute.
- Private helpers (consumable by tests via name): `_resolve_module_file(target_module) -> Path`, `_strip_bom(raw: bytes) -> tuple[bytes, bool]`, `_locate_leaf_constant(tree, target_symbol, selector) -> ast.Constant`, `_build_line_starts(raw: bytes) -> list[int]`, `_compute_byte_slice(node, line_starts) -> tuple[int, int]`, `_splice_bytes(raw, start, end, replacement) -> bytes`.

**Algorithm (§4 steps 1-20).**
1. `if len(confirm) != 8: raise ThresholdApplyError(code="CONFIRM_MISMATCH", hint="--confirm must be exactly 8 hex chars (did you swap --confirm and --proposal-id?)")` — BEFORE proposal load.
2. Acquire `.calibration.lock` (30s, raise `LOCK_TIMEOUT` on timeout).
3. Load proposal JSON via `<root>/_bmad/calibration/proposals/<id>.json`; missing → `PROPOSAL_NOT_FOUND`.
4. TTL: `now_utc = datetime.now(timezone.utc)`; if `now_utc - parse(created_at_iso) > timedelta(hours=ttl)` → `PROPOSAL_EXPIRED`. TTL source: `proposal.proposer_config.get("ttl_hours", MAX_PROPOSAL_AGE_HOURS)`.
5. `if not hmac.compare_digest(confirm, proposal.confirm_slug)`: append `confirm_failed` decision (under same lock) via `threshold_decisions.record_decision`; raise `CONFIRM_MISMATCH` with `hint="confirm slug does not match"`.
6. Check for newer proposal on same `(target_module, target_symbol, selector)`; if any has `created_at_iso > this.created_at_iso` → `STALE_PROPOSAL`.
7. `spec = importlib.util.find_spec(proposal.target_module)`; if `spec is None or spec.origin is None` → `MODULE_NOT_RESOLVABLE`. `target_file = Path(spec.origin)`.
8. `raw = target_file.read_bytes()`; `bom_present = raw.startswith(b"\xef\xbb\xbf")`; `body = raw[3:] if bom_present else raw`.
9. `tree = ast.parse(body)`.
10. `node = _locate_leaf_constant(tree, proposal.target_symbol, proposal.selector)`. `selector.kind` dispatch:
    - `"dict_tuple_element"`: walk `tree.body` for `Assign|AnnAssign` whose `.targets[0].id` (or `.target.id` for `AnnAssign`) == `target_symbol` AND `.value` is `ast.Dict`. Iterate `Dict.keys` for matching `ast.Constant` whose `.value == selector["key"]`. Take paired `Dict.values[i]` (`ast.Tuple` or `ast.List`); index `.elts[selector["index"]]`. **MUST NOT recurse into `node.annotation`** (skip).
    - `"name"`: walk `tree.body` for `Assign|AnnAssign` whose target Name == `target_symbol`; `.value` must be `ast.Constant`.
    - Any other kind → `UNSUPPORTED_SELECTOR_KIND`. Selector miss → `SELECTOR_NOT_FOUND`. Located node not `ast.Constant` → `NON_LITERAL_TARGET`.
11. `if type(node.value) is not type(proposal.current_value)`: `TYPE_MISMATCH`.
12. `extracted = ast.get_source_segment(body, node)`; `if ast.literal_eval(extracted) != proposal.current_value`: `LIVE_VALUE_DRIFTED`.
13. Build `line_starts = [0] + [i+1 for i,b in enumerate(body) if b == ord("\n")]`. Compute `start = line_starts[node.lineno-1] + node.col_offset`, `end = line_starts[node.end_lineno-1] + node.end_col_offset`. (UTF-8 byte offsets per Python AST contract.)
14. Backup: `backup_path = <root>/_bmad/calibration/proposals/<id>.applied/before.py.gate_rules`; `write_atomic_text(backup_path, raw.decode("utf-8"))`. On failure → `BACKUP_FAILED` (target untouched).
15. `replacement = repr(proposal.proposed_value).encode("ascii")`. `new_body = body[:start] + replacement + body[end:]`.
16. `new_raw = (b"\xef\xbb\xbf" + new_body) if bom_present else new_body`.
17. Verify: `try: ast.parse(new_body) except SyntaxError`: restore from backup via `write_atomic_text(target_file, raw.decode("utf-8"))`; raise `APPLY_REWRITE_INVALID`.
18. Write via `write_atomic_text(target_file, new_raw.decode("utf-8", errors="surrogatepass"))` — or use a `write_atomic_bytes` if available; otherwise add a tiny helper in this module.
19. Write `record.json`: `AppliedThresholdRecord(...)` as canonical JSON.
20. Append `accept` decision via `record_decision`. Emit `GateThresholdProposalAudit(event="proposal_applied", ...)` via `emit_gate_audit` (try/except `ImportError` fallback like Stage 2).
21. Release lock; return `AppliedThresholdRecord`.

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/innovation/threshold_apply.py` (~250 LOC, ≤500)
- `skills/bmad-story-automator/tests/test_threshold_apply.py` (~380 LOC, ≥20 tests)

**Tests (§7.3).** 20 tests per the spec list: PROPOSAL_NOT_FOUND, bad-length confirm (no `confirm_failed` appended), wrong-slug correct-length (DOES append), PROPOSAL_EXPIRED, STALE_PROPOSAL, MODULE_NOT_RESOLVABLE, LIVE_VALUE_DRIFTED, TYPE_MISMATCH, NON_LITERAL_TARGET, UNSUPPORTED_SELECTOR_KIND, happy-path `dict_tuple_element` (byte-diff = leaf only), happy-path `name`, UTF-8 BOM preserved, non-ASCII content elsewhere doesn't misalign, backup-before-splice (mocked target write failure), post-splice ast.parse failure → restore + APPLY_REWRITE_INVALID, record.json + accept-decision written, two concurrent applies (second LIVE_VALUE_DRIFTED), re-apply (LIVE_VALUE_DRIFTED), LOCK_TIMEOUT mocked.

**Quality gates.**
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/innovation/threshold_apply.py skills/bmad-story-automator/tests/test_threshold_apply.py
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_threshold_apply tests.test_threshold_proposer tests.test_threshold_decisions
wc -l ...  # ≤500
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/innovation/threshold_apply.py \
        skills/bmad-story-automator/tests/test_threshold_apply.py
git commit -m "$(cat <<'EOF'
feat(c5): apply step — AST-located byte splice, BOM-aware, find_spec resolution, anti-drift, backup-restore

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-c5-apply -m "..."
```

---

## Stage 4 — `compat-c5-orchestrator` — orchestrator wiring + audit event

**Scope.**

(a) `core/gate_audit.py` (+~35 LOC): add `GateThresholdProposalAudit` dataclass with fields `proposal_id`, `target_module`, `target_symbol`, `event` (str enum: `"proposal_created" | "proposal_applied" | "proposal_rejected" | "proposal_superseded" | "proposal_confirm_failed"`), `operator_id`. Add it to the `_AuditEvent` union (matches `GateReadinessAudit` precedent). The dataclass must be wired into `emit_gate_audit`'s dispatch (its `_AuditEvent` typing or the `isinstance` chain — read the existing file to confirm idiom). DO NOT touch `core/telemetry_events.py`.

(b) `core/gate_orchestrator.py` (+~30 LOC): add `threshold_proposer: ThresholdProposer | None = None` to `run_production_gate`'s kwarg list (alongside the existing `drift_watcher` and `session_usage`). Use `TYPE_CHECKING` import for `ThresholdProposer` per the existing pattern. Add the call site BEFORE `return gate_file` and AFTER the existing `lineage_root` + `cost_total_usd` blocks (see existing flow at lines ~835-882):

```python
if threshold_proposer is not None:
    try:
        proposal = threshold_proposer.observe_gate(project_root, gate_file)
        gate_file["threshold_proposal_ref"] = (
            proposal.proposal_id if proposal is not None else ""
        )
    except Exception as _exc:
        gate_file["threshold_proposal_ref"] = ""
        gate_file["threshold_proposer_error"] = type(_exc).__name__
```

Update the docstring to document the new kwarg (mirroring how `drift_watcher` / `session_usage` are documented).

(c) Integration tests in `tests/test_threshold_proposer.py` (extend, or add `tests/test_c5_orchestrator_wiring.py`):
- AC-G-01: default kwarg `None` → returned dict has no `threshold_proposal_ref`/`threshold_proposer_error`; on-disk `_bmad/gate/verdicts/<id>.json` byte-identical to pre-C5 (via JSON canonical comparison).
- AC-G-02: kwarg supplied + proposal emitted → `gate_file["threshold_proposal_ref"]` is 16-hex; no proposal → `""`.
- AC-G-03: synthetic proposer that raises → `threshold_proposal_ref = ""`, `threshold_proposer_error = "RuntimeError"`. Gate completes normally.
- AC-G-04: `session_usage` + `threshold_proposer` both supplied: both `cost_total_usd` and `threshold_proposal_ref` present.
- AC-G-05: `GateThresholdProposalAudit(event="proposal_created", ...)` emitted on new-proposal path (use a fake audit policy/path to capture).

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` (modify, +35)
- `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` (modify, +30)
- `skills/bmad-story-automator/tests/test_c5_orchestrator_wiring.py` (new, ~200 LOC)

**Quality gates.**
```
python -m ruff check ...
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest \
    tests.test_threshold_proposer tests.test_threshold_apply tests.test_threshold_decisions \
    tests.test_c5_orchestrator_wiring tests.test_gate_orchestrator tests.test_gate_audit \
    tests.test_audit_regression
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/gate_audit.py \
        skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py \
        skills/bmad-story-automator/tests/test_c5_orchestrator_wiring.py
git commit -m "$(cat <<'EOF'
feat(c5): orchestrator wiring + audit event

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-c5-orchestrator -m "..."
```

---

## Stage 5 — `compat-c5-cli` — CLI subcommands + byte-identical bare-call golden

**Scope.**

(a) `commands/calibration_cmd.py` (+~200 LOC): keep `cmd_calibration` (bare invocation) byte-identical; add subcommand dispatcher routing to:

- `_cmd_propose(args)` — flags `--window <N>`, `--ttl-hours <H>`. Emits `{"ok":true, "proposal":{...top-level proposal_id+confirm_slug...}|null}` via `print_json` (insertion-order; NO `sort_keys=True`). Exit 0.
- `_cmd_list_proposals(args)` — flag `--include-failed`. Reads `_bmad/calibration/proposals/*.json`; sorts by `created_at_iso` desc; each item includes `proposal_id`, `confirm_slug`, `target_module`, `target_symbol`, `current_value`, `proposed_value`, `created_at_iso`, `latest_decision`. Exit 0 (empty list NOT an error).
- `_cmd_show(args)` — positional `proposal_id`; flag `--include-slug`. Emits `{ok, proposal:{...slug redacted to "<redacted>" by default...}, diff:"...", applied_record:...|null}`. Missing id → exit 1 + `{ok:false, error:"PROPOSAL_NOT_FOUND", proposal_id:<id>}`.
- `_cmd_apply(args, *, confirm: str)` — the `confirm: str` parameter is REQUIRED for the audit-floor structural-recognition pattern in Stage 6. Flags `--proposal-id <id>` (REQUIRED), `--confirm <slug>` (REQUIRED). Routes to `threshold_apply.apply_threshold_proposal`. Success → exit 0 + `{ok:true, applied:true, target_file:<resolved>}`. `ThresholdApplyError` → exit 1 + `{ok:false, error:<code>, hint?:<str>}`. Missing flag → exit 2 + `{ok:false, error:"missing <flag>"}`.
- `_cmd_reject(args)` — flags `--proposal-id <id>` (REQUIRED), `--reason "<note>"` (REQUIRED). Appends `reject` decision via `threshold_proposer.reject_proposal`. Exit 0 / 1 / 2 per pattern.

Plus `_render_diff(before_source: str, after_source: str, lineno: int) -> str` helper:
- Unified diff format; 3 lines context; bounded to ≤7 lines.
- ASCII only (assert `output.encode("ascii")` doesn't raise).
- LF terminators only.
- Deterministic over `(before, after, lineno)`.

(b) `cli.py` (+0-6 LOC): re-route `calibration` to a subcommand dispatcher if not already routed. READ `cli.py` first to see the existing routing pattern.

(c) Golden fixture: write `tests/fixtures/calibration_bare_v1.expected.json` by running the bare invocation against a deterministic telemetry fixture. The fixture must be regenerable from `tests/_calibration_fixtures.py` (which already exists per Stage 1's reading of the workspace).

(d) `tests/test_calibration_cmd_proposals.py` (~240 LOC, ≥10 tests). Tests cover:
- Bare invocation byte-identical to golden fixture.
- `propose` returns proposal_id + confirm_slug at top level.
- `list-proposals` empty case (exit 0).
- `show` redacted slug; `--include-slug` reveals.
- `show` missing id → exit 1.
- `apply` happy path.
- `apply` bad-length confirm → exit 1 + length-aware hint.
- `apply` missing flag → exit 2.
- `reject` happy path.
- `--help` lists all 5 subcommands.

**Files.**
- `skills/bmad-story-automator/src/story_automator/commands/calibration_cmd.py` (modify, +200)
- `skills/bmad-story-automator/src/story_automator/cli.py` (modify, +0-6)
- `skills/bmad-story-automator/tests/test_calibration_cmd_proposals.py` (new, ~240)
- `skills/bmad-story-automator/tests/fixtures/calibration_bare_v1.expected.json` (new, ~30)

**Quality gates.**
```
python -m ruff check ...
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest \
    tests.test_calibration_cmd_proposals tests.test_calibration tests.test_threshold_proposer tests.test_threshold_apply
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/commands/calibration_cmd.py \
        skills/bmad-story-automator/src/story_automator/cli.py \
        skills/bmad-story-automator/tests/test_calibration_cmd_proposals.py \
        skills/bmad-story-automator/tests/fixtures/calibration_bare_v1.expected.json
git commit -m "$(cat <<'EOF'
feat(c5): CLI subcommands + diff render + byte-identical bare-call regression

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-c5-cli -m "..."
```

---

## Stage 6 — `compat-c5-invariants` — audit-floor invariants

**Scope.** Add TWO new invariant classes to `tests/test_audit_regression.py` per spec §7.5.

### `ThresholdApplyIsolationInvariant`

Mirror **exactly** the structural-recognition + binding-tracking pattern from:
- `AuditKeyEnvScrubInvariant._defines_scrub_helper(tree)` at lines 659-673 — module-level `def scrub_env_for_subprocess` presence.
- `UnifiedStateWriteIsolationInvariant.owns_unified_writer(tree)` at lines 844-849 — same pattern for `write_unified_state`.
- `UnifiedStateWriteIsolationInvariant._module_violates(tree)` at lines 743-855 — full binding-tracking AST walker.

Three sub-tests:

1. **`test_ast_no_direct_or_indirect_apply_in_core_and_commands`** — walks every `.py` under BOTH:
   - `skills/bmad-story-automator/src/story_automator/core/`
   - `skills/bmad-story-automator/src/story_automator/commands/`
   
   For each module: exempt via `_defines_apply_helper(tree)` (top-level FunctionDef named `apply_threshold_proposal` → skip the whole file). Additionally exempt CLI handlers via `_is_cli_apply_handler(tree)`: top-level FunctionDef whose first non-self argument is typed `confirm: str` AND whose body contains a `Call` to `apply_threshold_proposal` — structural, rename-proof.
   
   For non-exempt modules, run the binding-tracking walker:
   - Track `from X import apply_threshold_proposal as ALIAS` → ALIAS in forbidden_names.
   - Track `Assign(target=Name(LHS), value=Name("apply_threshold_proposal"))` (or alias) → LHS in forbidden_names.
   - Flag `Call(func=Name(N))` where N in `{"apply_threshold_proposal"} ∪ forbidden_names`.
   - Flag `Call(func=Attribute(attr="apply_threshold_proposal"))` regardless of receiver (unless exempted).
   - Flag `Call(func=Name("getattr"), args=[_, Constant("apply_threshold_proposal"), ...])`.
   - Flag `Attribute(attr="apply_threshold_proposal", value=Call(func=Attribute(attr="import_module"), ...))`.

2. **`test_positive_failure_synthetic_violator_is_caught`** — two-direction proof:
   - (a) Synthesize source containing direct call + alias-rebinding call (`from x import apply_threshold_proposal as _ap; _ap(...)`) + indirect getattr call (`getattr(ta, "apply_threshold_proposal")(...)`). Assert all three flagged.
   - (b) Read the real `threshold_apply.py` source, AST-strip the `def apply_threshold_proposal` top-level FunctionDef, re-parse, assert the walker does NOT trip on the residual file. Proves the rule itself is operative independent of the exemption (matches `UnifiedStateWriteIsolationInvariant.test_positive_failure_synthetic_violator_is_caught` at lines 859-905).

3. **`test_drift_band_proposals_disabled_by_default`** —
   ```python
   import inspect
   from story_automator.core.innovation.threshold_proposer import ThresholdProposer
   sig = inspect.signature(ThresholdProposer.__init__)
   assert sig.parameters["enable_drift_band_proposals"].default is False
   ```
   Pins the safety-critical default (matches `PluginTrustBoundaryInvariant.test_plugin_manifest_keys_closed_set` at line 397).

### `ThresholdLockIsolationInvariant`

One AST-scan sub-test:

1. **`test_threshold_modules_only_acquire_calibration_lock`** — walks every `.py` under `skills/bmad-story-automator/src/story_automator/core/innovation/threshold_*.py`. For each `Call` whose `func` is `Name("FileLock")` or `Attribute(attr="FileLock")` (e.g., `filelock.FileLock(...)`): the first positional or `lock_file=` kwarg's literal value MUST end with `.calibration.lock`. Resolve string literals via `ast.literal_eval` on `Constant` nodes; for non-literal (`Call` to `str(...)` etc.) the test reports an unresolvable lock-path and flags.
   
   Positive-failure half: synthesize `import filelock; filelock.FileLock(".gate.lock")`, parse, run the walker, assert flagged.

**Files.**
- `tests/test_audit_regression.py` (modify, +~230 LOC total across both classes)

**Quality gates.**
```
python -m ruff check tests/test_audit_regression.py
python -m ruff format --check tests/test_audit_regression.py
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_regression
```

**Commit + tag.**
```
git add tests/test_audit_regression.py
git commit -m "$(cat <<'EOF'
test(c5): ThresholdApplyIsolationInvariant + ThresholdLockIsolationInvariant

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-c5-invariants -m "..."
```

---

## Stage 7 — `compat-c5-docs` — changelog + frozen-surface + CLAUDE.md

**Scope.**

(a) `docs/changelog/2026-06-23-c5-self-improving-gate.md` (~55 LOC): new `[FULL]` changelog entry. Heading: `## 260623 - [FULL] C5 self-improving gate` (verify against other 2026-06-23 entries via `ls docs/changelog/ | grep 260623` to match the established date format). Sections: Summary, Added, Changed, Files, QA Notes (per the M11 controlled vocabulary).

(b) `docs/spec/frozen-gate-surface.md` (+~28 LOC): append a new `### core/innovation/threshold_proposer.py` section enumerating the public surface (ThresholdProposer + ThresholdProposal + ProposerConfigError + apply_threshold_proposal + AppliedThresholdRecord + ThresholdApplyError + 4 decisions helpers) and the behavioral invariants (advisory-only; never auto-applies; in-memory-only gate-file fields; no telemetry-events touch; calibration-lock isolation per ThresholdLockIsolationInvariant).

(c) `CLAUDE.md` (+~22 LOC): under "Recently shipped (session 2026-06-23)", add a "Self-improving gate (C5)" subsection. Update the "additive kwargs (cumulative)" list to add `threshold_proposer: ThresholdProposer | None = None` as the seventh optional kwarg.

**Files.**
- `docs/changelog/2026-06-23-c5-self-improving-gate.md` (new, ~55)
- `docs/spec/frozen-gate-surface.md` (modify, +28)
- `CLAUDE.md` (modify, +22)

**Quality gates.** No Python tests for docs-only commits, but smoke-check that no trailing whitespace was introduced (CLAUDE.md hard guardrail).

**Commit + tag.**
```
git add docs/changelog/2026-06-23-c5-self-improving-gate.md \
        docs/spec/frozen-gate-surface.md \
        CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(c5): changelog + frozen-gate-surface + CLAUDE.md

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-c5-docs -m "..."
```

---

## Verification appendix

After Stage 7, run the full project verification:

```bash
npm run verify
```

This runs (per `package.json`):
- `npm run test:python` — discovers and runs `unittest discover`.
- `npm run pack:dry-run` — verifies the npm package is well-formed.
- `npm run test:cli` — smoke tests the CLI surface.
- `npm run test:smoke` — runs `scripts/smoke-test.sh` (npm pack + install).

Plus targeted spot-checks:
```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_regression -v
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_threshold_proposer tests.test_threshold_apply tests.test_threshold_decisions tests.test_c5_orchestrator_wiring tests.test_calibration_cmd_proposals -v
```

Baseline test count was 3,763 (pre-C5). Expected post-C5 count: ~3850-3900.

## Push plan

After verification is green:

```bash
git tag -a milestone-C5-self-improving-gate -m "C5 self-improving gate — drift signals auto-propose threshold patches against gate_rules.py"
git tag --list 'compat-c5-*' milestone-C5-self-improving-gate
# Expected: 7 compat-c5-* tags (optionally 8 if a review-fixes commit landed) + the milestone tag.
git push origin bma-d/integration-all
git push origin --tags
```

**No `--force`. No `--no-verify`.** If a push is rejected (non-fast-forward), abort and surface to operator; do not force.

## Risk register

| Risk | Mitigation |
|---|---|
| Stage 2 imports `gate_audit.GateThresholdProposalAudit` before Stage 4 lands. | Wrap audit emission in try/except ImportError; tests for Stage 2 use a fake audit policy that doesn't depend on the dataclass. |
| Stage 3's apply targets `gate_rules.py` — applying in a test would mutate real source. | Tests use a tmpdir fixture with a synthesized `gate_rules.py` copy AND a synthesized `target_module` whose `find_spec` is monkeypatched. NO test mutates real source. |
| LOC budget overrun (e.g., proposer hits 600 LOC). | Pre-authorized sibling split: factor `_locate_leaf_constant` + selector resolution into a private `core/innovation/threshold_locator.py`. |
| Stage 6 invariant accidentally over-fires on existing code. | Run `python -m unittest tests.test_audit_regression -v` BEFORE adding the new classes to capture the baseline; verify only the new classes added net-new test methods. |
| `ast.get_source_segment` returns None for some valid nodes on Python ≤3.10. | Project pins Python 3.11+; `get_source_segment` is stable. Fallback would be manual byte slice via line_starts. |
| ruff format check fails on cross-platform CRLF. | All Python files written with LF; ruff auto-normalizes; explicit `python -m ruff format <file>` before commit if check fails. |
