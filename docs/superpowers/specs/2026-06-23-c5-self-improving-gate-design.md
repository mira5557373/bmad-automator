# C5 — Self-Improving Gate (Drift → Threshold Proposals) — Design Spec (rev 2)

> Date: 2026-06-23 · Status: **Draft post-adversarial-review, ready for implementation** · Milestone: **C5 (self-improving gate)** · Owner branch: `bma-d/integration-all`.
> Rev 2 folds in 6 HIGH + 8 MED + 4 LOW gap fixes from an 8-lens adversarial review of rev 1. The gap report lives at the bottom (§13).
> Topic: close the observation → action loop on existing drift telemetry by auto-emitting **threshold-patch proposals** against the gate's hardcoded knobs (`PRIORITY_THRESHOLDS` in `core/gate_rules.py`) and exposing an explicit, operator-gated apply path. The proposer is advisory; nothing in `core/` may mutate source automatically.
> Validation provenance: builds on M08 calibration (`core/calibration.py`), M09 drift detector (`core/drift_detector.py`), C1 spec-drift watcher (`core/innovation/spec_drift_watcher.py`), N7/C3 cost-evidence persistence pattern (`core/innovation/cost_evidence.py`).
> Frozen-surface contract: ADDITIVE only. New optional kwarg on `run_production_gate`; new optional in-memory-only field on the returned dict; new `calibration` CLI subcommands. Every existing call site keeps byte-identical behavior when the new kwarg is omitted. **No top-level changes to `make_gate_file`** — priority is already persisted per-category at `gate_file["categories"][<cat>]["required"]["priority"]` (verified in `core/category_rules.py:41`).

## 1. Goal

Close the loop that is half-built today:

- `core/drift_detector.py` computes `DriftReport`s — read only.
- `core/innovation/spec_drift_watcher.py` polls AC-coverage drift mid-run — read only.
- `core/calibration.py` aggregates per-model success rates from telemetry — read only.
- `core/gate_rules.PRIORITY_THRESHOLDS` is a hardcoded module-level constant that nothing observes against.

C5 closes that loop by adding a **proposer** that reads the existing per-category coverage evidence persisted in gate files and emits a structured `ThresholdProposal` whenever the observed coverage distribution diverges enough from the live constants to recommend an adjustment. The proposer never mutates source. A separate, deliberately-coupled **apply** step — driven only by an explicit operator CLI call with a per-proposal confirmation slug — performs a single-knob, AST-located, surgical text splice on `gate_rules.py`, with a pre-write re-validation that the live value still matches the proposal's `current_value`. Every proposal and every accept/reject/superseded/confirm_failed decision is recorded in an append-only JSONL ledger under `_bmad/calibration/`.

The motivating constraint: **the gate must not silently rewrite its own rules.** "Self-improving" in C5 means the gate auto-detects a candidate adjustment, presents it as a proposal artifact, and refuses to apply it until an operator types the proposal's confirmation slug back at the CLI. The decision is human-in-the-loop on every patch.

## 2. Out of scope

- **No AST rewrite of the targeted source file.** The applier uses `ast.parse` only to *locate* the byte range of the targeted leaf `ast.Constant`; the rewrite itself is a surgical byte splice over that range. We do NOT round-trip via `ast.unparse` (clobbers comments and quoting).
- **No automatic apply.** No `core/` or `commands/` code path may call `apply_threshold_proposal` implicitly. An audit-floor invariant pins this (§7.5).
- **No CI hook.** C5 ships the proposer + apply CLI only.
- **No multi-knob proposals.** Each proposal targets exactly one leaf Constant (one `(priority, index=0)` tuple slot for `PRIORITY_THRESHOLDS`, OR one module-level numeric constant via the `name` selector — drift-band targets remain registered but default-OFF).
- **No fail_floor (index=1) proposals in v1.** The signal definition (per-category `coverage_pct ≥ required_pct`) covers `required_pct` only; `fail_floor` controls the CONCERNS-vs-FAIL transition and is NOT recoverable from persisted gate files alone. Adjusting it is a follow-up.
- **No rollback command.** Apply writes a pre-mutation backup; operator restores manually.
- **No mutation of `spec_drift_watcher.severity_thresholds`** — those are runtime config, not module-level constants.
- **No mutation of test fixtures or audit invariants.** If `PRIORITY_THRESHOLDS` changes, pinning tests (`tests/test_gate_rules.py`) will fail — that's a deliberate signal that the apply commit must update those tests too. C5 does not generate or modify tests itself.
- **No new telemetry event types.** Per CLAUDE.md hard guardrail, `core/telemetry_events.py` is untouched. Audit events ride `UnknownEvent` forward-compat (matches `gate_audit.py`'s existing pattern).
- **No proposer auto-runs without an opt-in kwarg.** `run_production_gate(threshold_proposer=None)` is byte-identical to today.
- **No proposals derived from a single gate run.** Each proposal cites ≥ `MIN_EVIDENCE_WINDOW` gates (default 5).
- **No proposals for `MAX_WAIVER_TTL_DAYS`, schema versions, or any non-numeric knob.**
- **No new third-party dependency.** Stdlib + `filelock` + `psutil` per CLAUDE.md.
- **No additive top-level field on `make_gate_file`.** The priority signal lives per-category at `gate_file["categories"][<cat>]["required"]["priority"]`; we do not extend `make_gate_file`'s closed kwarg surface and do not touch `GateFileDeterminismBaseline`.

## 3. Decisions captured

| Decision | Choice |
|---|---|
| Module placement | Three sibling modules under `core/innovation/`: `threshold_proposer.py` (≤350 LOC), `threshold_apply.py` (≤250 LOC), `threshold_decisions.py` (≤150 LOC). Isolation lets the audit-floor invariant pin the apply call surface AST-precisely. |
| Targetable knobs in v1 | `core/gate_rules.PRIORITY_THRESHOLDS[priority][0]` (the 4 priority `required_pct` entries) only — `4 tunable integers`. `fail_floor` (index 1) is **registered but disabled** in v1; drift bands (`STABLE_MAX/MINOR_MAX/MAJOR_MAX`) are registered but gated behind `proposer.enable_drift_band_proposals=False` default. |
| Priority sourcing | `priority` is **read per gate** from `gate_file["categories"][<category>][\"required\"][\"priority\"]` (verified at `core/category_rules.py:41`). This avoids extending `make_gate_file` or `GateFileDeterminismBaseline`. The proposer's target registry maps each `(PRIORITY_THRESHOLDS, priority, 0)` slot to a single backing category: `{"P0": "correctness", "P1": "correctness", "P2": "correctness", "P3": "correctness"}` (extensible to `traceability` in a follow-up). Gates whose targeted category is NA or missing `actual.coverage_pct` are dropped from the evidence window. |
| Signal definition | For each `(priority, category)` target, the proposer reads `gate_file["categories"][<category>]["actual"]["coverage_pct"]` per gate. `passed_at_current_threshold = (coverage_pct >= current_required_pct)`. Aggregate per-priority observed pass-rate over the evidence window. Trigger when the most recent `consecutive_runs` entries within the last `min_evidence_window` matching gates are all outside the target band `[0.80, 0.95]`. |
| Proposal algorithm | Conservative ratchet: when observed pass-rate > 0.95 for `consecutive_runs`, propose raising `required_pct` by `min(ceil(observed_mean*100) - current, MAX_DELTA_PCT)`; symmetric for < 0.80. `MAX_DELTA_PCT=5`. Constructor invariant: `min_evidence_window >= consecutive_runs` (raise `ProposerConfigError` otherwise). Below-window returns `None`. **The `M = ceil(N/2)` clause from rev 1 is dropped as redundant; `consecutive_runs` is the authoritative kwarg.** |
| Where the proposer reads from | (a) `_bmad/gate/verdicts/<gate_id>.json` for historical gate files — load via `core.evidence_io.load_gate_file(project_root, gate_id)` (centralizes any future relocation). `_bmad/gate/evidence/<gate_id>/` holds *evidence records*, not gate files — never confuse the two. (b) `telemetry/events.jsonl` via `build_calibration` for rationale enrichment only; calibration data does NOT influence the algorithmic decision. Missing telemetry path degrades the rationale string gracefully. |
| Evidence-window ordering | `evidence_window` is sorted ascending by `gate_id` (lexicographic ASCII). The proposer enumerates `_bmad/gate/verdicts/*.json`, sorts directory listing by `gate_id`, filters by matching priority (read per-category), takes the last `min_evidence_window` matching gates, uses that exact sorted tuple as the proposal's `evidence_window`. Filesystem mtime is never consulted — guarantees cross-machine reproducibility of `proposal_id`. |
| Proposal persistence layout | `_bmad/calibration/proposals/<proposal_id>.json` (atomic write via `core.atomic_io.write_atomic_text`). `proposal_id = sha256(canonical_json({"target_module": ..., "target_symbol": ..., "selector": ..., "current_value": ..., "proposed_value": ..., "evidence_window": [...]}))[:16]` — deterministic over inputs. |
| Confirmation slug | `confirm_slug = os.urandom(4).hex()` (8 hex chars; 32 bits CSPRNG entropy), generated **only when `proposal_id` is first written**. On an idempotent re-emission (same `proposal_id`), the existing slug is **preserved verbatim** by reading the on-disk JSON before write — `created_at_iso` is similarly immutable on re-emit. Comparison at apply time uses `hmac.compare_digest(typed_slug, proposal.confirm_slug)` (constant-time). No separate `apply_nonce` — the slug IS the secret. |
| Resolving the target file | Proposals store `target_module: str` (Python module path, e.g. `"story_automator.core.gate_rules"`) — NOT a project-relative file path. At apply time the file is resolved via `importlib.util.find_spec(target_module).origin` (stdlib only), which works under both source-tree and installed-plugin layouts (see `install.sh:237-238` for the latter). If `find_spec` returns `None` the applier raises `ThresholdApplyError(code="MODULE_NOT_RESOLVABLE")`. An optional `target_file_hint: str` may be cached for human-readable show output but is never trusted at apply time. |
| AST-located splice — walk | The applier (a) reads the target as bytes via `Path.read_bytes()`; (b) detects-and-strips a UTF-8 BOM (`b"\xef\xbb\xbf"`) before parsing, re-prepends on write; (c) calls `ast.parse(bom_stripped_bytes)`; (d) for `selector.kind == "dict_tuple_element"`, walks **module-body** for an `ast.AnnAssign` or `ast.Assign` whose target is a Name matching `target_symbol` AND whose `.value` is an `ast.Dict`; (e) iterates `Dict.keys` to find the `ast.Constant` matching `selector.key`; takes the paired `Dict.values[i]` which must be `ast.Tuple` (or `ast.List`); indexes `.elts[selector.index]`; the leaf MUST be an `ast.Constant`. (f) For `selector.kind == "name"`, walks module-body for `Assign|AnnAssign` whose target Name matches `target_symbol`; `.value` must be `ast.Constant`. (g) **The walker MUST NOT descend into `node.annotation`** — `PRIORITY_THRESHOLDS: dict[str, tuple[int, int]] = ...` contains `Subscript`/`Tuple`/`Name` nodes in the annotation subtree that a naive `ast.walk` would mistake for targets. (h) The walker matches by exact equality on the Name id; aliasing or attribute access in the source is rejected as `SELECTOR_NOT_FOUND`. |
| AST-located splice — byte slice | The splice range is the leaf Constant node's `(lineno, col_offset, end_lineno, end_col_offset)` mapped to a byte slice via a line-start byte index built once by scanning the BOM-stripped bytes for `b"\n"`. `col_offset` and `end_col_offset` are **UTF-8 byte offsets** (not character indices), per the Python AST contract. The splice writes `repr(quantized_proposed_value).encode("ascii")` — numeric `repr()` is always ASCII. The Tuple's parentheses, commas, surrounding whitespace, and trailing same-line comments are **NEVER** in the splice range — only the leaf Constant's bytes. **`ast.get_source_segment` is used ONLY for the pre-splice anti-drift cross-verify (parse the extracted substring with `ast.literal_eval` and compare to `proposal.current_value`) — never as a byte-range helper or via `source.find(segment)` (the latter risks aliasing to a non-target occurrence).** |
| Anti-drift on apply | After locating the leaf, the applier (i) asserts `isinstance(node, ast.Constant)` and raises `ThresholdApplyError(code="NON_LITERAL_TARGET")` if not (catches operator-edited `MINOR_MAX = 1/10` or `(95, 90)` reformulations); (ii) asserts `type(node.value) is type(proposal.current_value)` and raises `code="TYPE_MISMATCH"` on failure (defense against the proposer emitting a float for an int target); (iii) asserts `ast.literal_eval(extracted_segment) == proposal.current_value` and raises `code="LIVE_VALUE_DRIFTED"` otherwise. |
| Numeric serialization & quantization | Numeric fields use `int | float`. `current_value` is captured at proposer time via `ast.literal_eval` on the located leaf (exact). For **float** targets the proposer quantizes `proposed_value` to the source's textual precision: count digits after `.` in `ast.get_source_segment(node)`, then `round(proposed, decimals)`. The rewrite uses `repr(quantized)`; splicer enforces `len(repr(quantized).encode('ascii')) <= 24` to bound expansion. For **int** targets, `int(round(proposed))`. Comparison at apply time is `ast.literal_eval(value_segment) == proposal.current_value` — exact equality. |
| Newer-proposal precedence | Auto-supersede appends a `"superseded"` decision for a prior proposal on the same `(target_module, target_symbol, selector)` ONLY if `latest_decision_for(prior_id) not in {"accept", "reject"}`. Re-emission with the **same** `proposal_id` is a byte-identical no-op (no decision appended; slug + created_at_iso preserved). Atomic ordering under `.calibration.lock`: (1) `write_atomic_text` the new proposal JSON; (2) on success, append `"superseded"` for the prior pending proposal; (3) if step 2 fails after step 1 succeeded, write a partial-supersede record to sidecar `_bmad/calibration/.partial_supersedes.jsonl` for later reconcile. |
| Proposal TTL | `MAX_PROPOSAL_AGE_HOURS = 168` (7 days). At apply time, if `(now_utc - created_at_iso) > MAX_PROPOSAL_AGE_HOURS`, raise `ThresholdApplyError(code="PROPOSAL_EXPIRED")`. Configurable per-proposer constructor; CLI override via `--ttl-hours N`. Bounds the slug brute-force window. |
| Decision ledger | Append-only `_bmad/calibration/decisions.jsonl`. Action vocabulary: `{accept, reject, superseded, confirm_failed}`. Writes use the durable pattern from `spec_drift_persistence.append_drift_event` (`os.open(O_WRONLY|O_CREAT|O_APPEND, 0o600)` + `os.fsync(fd)` BEFORE lock release) so a crash after lock release cannot lose the decision. |
| Concurrent writers | Per-project filelock at `_bmad/calibration/.calibration.lock` serializes (a) proposal writes, (b) decision-ledger appends, (c) applies. Readers (`list_proposals`, `show_proposal`) take no lock — proposals are immutable after first write. |
| Lock-ordering policy | **No code path may hold `.calibration.lock` simultaneously with any other `_bmad/*.lock` (`.gate.lock`, `.lineage.lock`, `.drift.lock`, `.unified-state.lock`).** The proposer reads `_bmad/gate/verdicts/` without acquiring `.gate.lock` (snapshot semantics tolerate concurrent gate writers adding files). The applier acquires `.calibration.lock` only; the splice target lives **outside `_bmad/`** so it is unaffected by gate-stack locks. The audit-floor invariant pins this with an AST scan that rejects any `FileLock` construction in `core/innovation/threshold_*.py` whose path is not `.calibration.lock`. |
| Frozen-gate-surface contract | `run_production_gate` gains one new optional kwarg `threshold_proposer: ThresholdProposer | None = None`. When `None` (default), behavior is byte-identical. When provided, after `evaluate_gate` returns (which has already persisted the gate via `persist_gate_file` at `verdict_engine.py:272`) the orchestrator calls `threshold_proposer.observe_gate(project_root, gate_file)` inside `try/except`. **The in-memory returned dict gains `threshold_proposal_ref: str` (16-hex or `""`).** **The on-disk gate JSON does NOT carry the new field** — this matches the existing in-memory-only pattern shared with `evidence_merkle_root`, `lineage_root`, `cost_total_usd` (all mutated post-`persist_gate_file`). A potential follow-up to re-persist after these mutations is OUT OF SCOPE for C5. |
| Observer failure observability | When `observe_gate` raises, the orchestrator catches and sets `gate_file["threshold_proposal_ref"] = ""` AND `gate_file["threshold_proposer_error"] = type(exc).__name__` (in-memory only). This avoids the "silent breakage" trap where the operator cannot distinguish "no proposal needed" from "proposer crashed". Both fields are in-memory-only on the returned dict. |
| Gate-file field semantics (in-memory) | TWO-state on the returned dict (matches C3 `cost_total_usd` precedent): `threshold_proposal_ref` ABSENT when `threshold_proposer=None`; PRESENT (`""` or 16-hex) when the kwarg was supplied. `threshold_proposer_error` is ABSENT on success, PRESENT (exception class name) on failure. |
| Audit-trail emission | `GateThresholdProposalAudit` dataclass added to `gate_audit.py` and to its `_AuditEvent` union (additive precedent set by `GateReadinessAudit` / `EpicGateDecisionAudit`). `core/telemetry_events.py` is NOT touched — audit events ride `UnknownEvent` forward-compat. Emitted on `proposal_created`, `proposal_accepted` (apply), `proposal_rejected`, `proposal_superseded`, `proposal_confirm_failed`. |
| CLI surface | Top-level `calibration` command (extends `commands/calibration_cmd.py`) gains 5 subcommands: `propose`, `list-proposals`, `show`, `apply`, `reject`. The bare `story-automator calibration` invocation stays **byte-identical** to today (pinned by a golden-fixture regression test). Each subcommand follows the universal exit-code contract: 0 on success, 1 on domain error, 2 on argparse error (matches `lineage_cmd.py`). The dispatcher MUST NOT introduce `sort_keys=True` to `print_json` — would break the bare-call byte-equality. |
| New deps? | **No.** Stdlib `ast`, `hashlib`, `hmac`, `importlib.util`, `json`, `os` + already-imported `filelock` + already-imported `core/atomic_io.write_atomic_text`. |
| Storage budget | Proposal JSON ≤ 4 KiB; decision JSONL ~250 B/line. 1000 proposals + 1000 decisions ≈ 5 MiB. No rotation in v1. |
| Determinism | `proposal_id` is deterministic over inputs (no clock, no random). `confirm_slug` and `created_at_iso` are stamped at first write and PRESERVED on re-emission — so byte-identical re-emit IS byte-identical to disk. |

## 4. Architecture

```
                        ┌────────────────────────────────────────────────────────┐
                        │   threshold_proposer.py    (~350 LOC)                  │
                        │                                                        │
   ThresholdProposer ──>│   ThresholdProposer(project_root,                      │
                        │     *, min_evidence_window=5,                          │
                        │     target_pass_rate_band=(0.80, 0.95),                │
                        │     max_delta_pct=5,                                   │
                        │     consecutive_runs=3,                                │
                        │     enable_drift_band_proposals=False,                 │
                        │     ttl_hours=168,                                     │
                        │     operator_id="local")                               │
                        │                                                        │
                        │   .observe_gate(project_root, gate_file)               │
                        │     ├─ ProposerConfigError if min_window<consec_runs   │
                        │     ├─ extract priority from gate_file["categories"]   │
                        │     │     [target_category]["required"]["priority"]    │
                        │     │     (return None if NA/missing)                  │
                        │     ├─ enumerate _bmad/gate/verdicts/*.json, sorted    │
                        │     │     by gate_id; filter by matching priority      │
                        │     │     and category having actual.coverage_pct      │
                        │     ├─ if matched_count < min_evidence_window: None    │
                        │     ├─ compute observed pass-rate against current      │
                        │     │     required_pct; check tail-of-window           │
                        │     │     (last consecutive_runs entries)              │
                        │     ├─ if last-K all-outside-band: compute proposal    │
                        │     │     (delta clamped to ±max_delta_pct)            │
                        │     ├─ acquire .calibration.lock (30s timeout)         │
                        │     ├─ if existing proposal JSON at deterministic id:  │
                        │     │     preserve slug + created_at; byte-identical   │
                        │     │     re-emit (no decision appended)               │
                        │     ├─ else: NEW slug + created_at; write proposal;    │
                        │     │     auto-supersede prior pending proposal on     │
                        │     │     same (target_module, target_symbol, selector)│
                        │     │     IFF latest_decision NOT IN {accept, reject}  │
                        │     ├─ emit GateThresholdProposalAudit                 │
                        │     └─ return the ThresholdProposal (or None)          │
                        │                                                        │
                        │   .list_proposals() -> list[ThresholdProposal]         │
                        │   .load_proposal(proposal_id) -> ThresholdProposal     │
                        │   .reject_proposal(id, reason, operator_id) -> ...     │
                        └────────────────────────────────────────────────────────┘
                                          │
                                          │ (proposal_id + confirm_slug to operator)
                                          ▼
                        ┌────────────────────────────────────────────────────────┐
                        │   threshold_apply.py    (~250 LOC)                     │
                        │                                                        │
                        │   apply_threshold_proposal(                            │
                        │     project_root,                                      │
                        │     proposal_id: str,                                  │
                        │     *,                                                 │
                        │     confirm: str,           # operator-typed slug      │
                        │     operator_id: str,                                  │
                        │   ) -> AppliedThresholdRecord                          │
                        │                                                        │
                        │   1. validate len(confirm)==8 (length-aware hint);     │
                        │      raise CONFIRM_MISMATCH with hint if not.          │
                        │   2. acquire .calibration.lock (30s)                   │
                        │   3. load_proposal(proposal_id) → PROPOSAL_NOT_FOUND   │
                        │      if absent                                         │
                        │   4. assert TTL not expired → PROPOSAL_EXPIRED         │
                        │   5. validate hmac.compare_digest(confirm, slug);      │
                        │      on mismatch append `confirm_failed` decision      │
                        │      under same lock, then raise CONFIRM_MISMATCH      │
                        │   6. check no newer proposal supersedes →              │
                        │      STALE_PROPOSAL if so                              │
                        │   7. resolve target_file via                           │
                        │      importlib.util.find_spec(target_module).origin    │
                        │      → MODULE_NOT_RESOLVABLE if None                   │
                        │   8. read target as bytes; strip BOM if present        │
                        │   9. ast.parse the BOM-stripped bytes                  │
                        │  10. walk to locate the leaf ast.Constant per          │
                        │      selector → SELECTOR_NOT_FOUND if absent;          │
                        │      NON_LITERAL_TARGET if not ast.Constant            │
                        │  11. TYPE_MISMATCH check; literal_eval check →         │
                        │      LIVE_VALUE_DRIFTED if mismatched                  │
                        │  12. compute byte slice [start, end) over the BOM-     │
                        │      stripped bytes via the line-start index           │
                        │  13. write_atomic_text BACKUP to                       │
                        │      <id>.applied/before.py.gate_rules → BACKUP_FAILED │
                        │      if it raises (no source mutation yet)             │
                        │  14. perform splice; re-prepend BOM if it was present  │
                        │  15. ast.parse the rewritten content; if it raises,    │
                        │      restore from backup via write_atomic_text and     │
                        │      raise APPLY_REWRITE_INVALID                       │
                        │  16. write_atomic_text the new bytes to target file    │
                        │  17. write <id>.applied/record.json                    │
                        │  18. append `accept` decision (durable os.open+fsync)  │
                        │  19. emit GateThresholdProposalAudit (proposal_applied)│
                        │  20. release lock                                      │
                        └────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                        ┌────────────────────────────────────────────────────────┐
                        │   threshold_decisions.py    (~150 LOC)                 │
                        │                                                        │
                        │   record_decision(project_root, proposal_id,           │
                        │     action: Literal["accept","reject","superseded",    │
                        │                     "confirm_failed"],                 │
                        │     operator_id, operator_note="")                     │
                        │   load_decisions(project_root,                         │
                        │     proposal_id=None) -> list[DecisionRecord]          │
                        │   latest_decision_for(project_root, proposal_id)       │
                        │                                                        │
                        │   Append pattern: os.open(O_WRONLY|O_CREAT|O_APPEND,   │
                        │     0o600); os.write(payload); os.fsync(fd); close.    │
                        │   filelock acquired AROUND open+write+fsync+close.     │
                        └────────────────────────────────────────────────────────┘

                        ┌────────────────────────────────────────────────────────┐
                        │   commands/calibration_cmd.py    (extends)             │
                        │                                                        │
                        │   bare (no subcommand):                                │
                        │     UNCHANGED — emits M08 calibration table in the     │
                        │     existing insertion-order JSON shape; print_json    │
                        │     NOT given sort_keys=True (would break byte-eq).    │
                        │                                                        │
                        │   propose [--window N] [--ttl-hours H]:                │
                        │     run proposer once; emit {ok:true, proposal:{...}}  │
                        │     or {ok:true, proposal:null}; ALWAYS includes       │
                        │     proposal_id + confirm_slug at the top level for    │
                        │     copy-paste UX.                                     │
                        │   list-proposals [--include-failed]:                   │
                        │     enumerate _bmad/calibration/proposals/*.json       │
                        │     sorted by created_at_iso desc; each item carries   │
                        │     proposal_id + confirm_slug + target_module +       │
                        │     target_symbol + current_value + proposed_value +   │
                        │     created_at_iso + latest_decision                   │
                        │   show <proposal_id> [--include-slug]:                 │
                        │     emit {ok:true, proposal:{... slug redacted ...},   │
                        │            diff:<unified-diff>, applied_record:...}    │
                        │     diff is ASCII-only LF, 3-line context, ≤7 lines    │
                        │   apply --proposal-id <id> --confirm <slug>:           │
                        │     dispatch to threshold_apply; exit 0/1/2            │
                        │   reject --proposal-id <id> --reason "<note>":         │
                        │     dispatch to threshold_proposer.reject_proposal     │
                        └────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                        ┌────────────────────────────────────────────────────────┐
                        │   gate_orchestrator.run_production_gate (+ ~30 LOC)    │
                        │                                                        │
                        │   ... existing collect / evaluate / cost flow ...      │
                        │   # NOTE: evaluate_gate already persisted gate_file    │
                        │   #       at verdict_engine.py:272 — these mutations   │
                        │   #       are IN-MEMORY ONLY, matching the existing    │
                        │   #       evidence_merkle_root/lineage_root/           │
                        │   #       cost_total_usd pattern.                      │
                        │   if threshold_proposer is not None:                   │
                        │       try:                                             │
                        │           proposal = threshold_proposer                │
                        │               .observe_gate(project_root, gate_file)   │
                        │           gate_file["threshold_proposal_ref"] = (      │
                        │               proposal.proposal_id if proposal else "" │
                        │           )                                            │
                        │       except Exception as _exc:                        │
                        │           gate_file["threshold_proposal_ref"] = ""     │
                        │           gate_file["threshold_proposer_error"] = (    │
                        │               type(_exc).__name__                     │
                        │           )                                            │
                        └────────────────────────────────────────────────────────┘
```

Key properties:

- **Read-only on the gate hot path.** `observe_gate` is bounded disk I/O (≤ `min_evidence_window` gate JSONs, each ≤ 4 KiB). The catch-all preserves gate completion; the `threshold_proposer_error` field gives the operator structural diagnosis.
- **Apply is mechanically isolated.** No `core/` or `commands/` module calls `apply_threshold_proposal` implicitly — pinned by §7.5's structural-recognition invariant.
- **Idempotency.** Re-proposing on identical evidence is a byte-identical no-op (same `proposal_id`, preserved `confirm_slug` + `created_at_iso`, no decision appended). `apply` is NOT idempotent — a second apply with the same slug fails `LIVE_VALUE_DRIFTED` because the source now matches `proposed_value`.
- **One lock per project.** `_bmad/calibration/.calibration.lock` serializes proposal/decision/apply writes. Lock-ordering invariant rejects co-acquisition with other `_bmad/*.lock` files.

## 5. Schemas (compact)

### 5.1 `ThresholdProposal` dataclass

```python
@dataclass(kw_only=True, frozen=True)
class ThresholdProposal:
    proposal_id: str               # 16-hex deterministic id
    target_module: str             # e.g. "story_automator.core.gate_rules"
    target_symbol: str             # e.g. "PRIORITY_THRESHOLDS"
    target_category: str           # e.g. "correctness" (for signal scoping)
    target_file_hint: str          # cosmetic only; resolved fresh at apply
    selector: dict[str, Any]       # see §5.2
    current_value: int | float
    proposed_value: int | float
    delta: int | float             # proposed_value - current_value
    rationale: str                 # human-readable; may cite calibration mean
    evidence_window: tuple[str, ...]  # sorted ascending by gate_id
    created_at_iso: str            # iso_now() at FIRST write; preserved on re-emit
    confirm_slug: str              # 8 hex chars; preserved on re-emit
    proposer_config: dict[str, Any]
```

Invariant enforced at construction: `type(proposed_value) is type(current_value)`. Selectors targeting int constants emit int proposals; float→float.

### 5.2 Selector vocabulary

For `PRIORITY_THRESHOLDS[priority][index]` (a Dict-of-Tuple/List shape):
```json
{"kind": "dict_tuple_element", "key": "P1", "index": 0}
```
For a module-level `Name = Constant` assignment (drift bands):
```json
{"kind": "name", "name": "MINOR_MAX"}
```

The applier dispatches on `selector.kind`. Only these two kinds are supported in v1; an unrecognized kind raises `ThresholdApplyError(code="UNSUPPORTED_SELECTOR_KIND")` before any I/O.

### 5.3 On-disk JSON layout

`_bmad/calibration/proposals/<proposal_id>.json`:
```json
{
  "schema_version": 1,
  "proposal_id": "0a1b2c3d4e5f6789",
  "target_module": "story_automator.core.gate_rules",
  "target_symbol": "PRIORITY_THRESHOLDS",
  "target_category": "correctness",
  "target_file_hint": "skills/bmad-story-automator/src/story_automator/core/gate_rules.py",
  "selector": {"kind": "dict_tuple_element", "key": "P1", "index": 0},
  "current_value": 95,
  "proposed_value": 92,
  "delta": -3,
  "rationale": "Observed P1 correctness coverage 0.62 over last 5 gates is below target band [0.80, 0.95]; ratcheting required_pct down by 3 (max-delta-pct=5) to ease the false-fail bias. Calibration table mean for (model=claude-opus-4-7, task=correctness)=0.71.",
  "evidence_window": ["gate-001", "gate-002", "gate-003", "gate-004", "gate-005"],
  "created_at_iso": "2026-06-23T17:42:11Z",
  "confirm_slug": "deadbeef",
  "proposer_config": {
    "min_evidence_window": 5,
    "target_pass_rate_band": [0.80, 0.95],
    "max_delta_pct": 5,
    "consecutive_runs": 3,
    "enable_drift_band_proposals": false,
    "ttl_hours": 168
  }
}
```

`_bmad/calibration/decisions.jsonl`:
```jsonl
{"proposal_id":"0a1b2c3d4e5f6789","action":"accept","operator_id":"local","decided_at_iso":"2026-06-23T17:50:02Z","operator_note":""}
{"proposal_id":"9876543210fedcba","action":"reject","operator_id":"local","decided_at_iso":"2026-06-23T17:55:14Z","operator_note":"need 2 more weeks of telemetry"}
{"proposal_id":"1111aaaabbbbcccc","action":"superseded","operator_id":"local","decided_at_iso":"2026-06-23T18:00:00Z","operator_note":"superseded by 2222ddddeeeefffe"}
{"proposal_id":"0a1b2c3d4e5f6789","action":"confirm_failed","operator_id":"local","decided_at_iso":"2026-06-23T17:51:09Z","operator_note":""}
```

`_bmad/calibration/proposals/<proposal_id>.applied/before.py.gate_rules` — full pre-apply source of `gate_rules.py`, byte-for-byte. Empty file is invalid.

`_bmad/calibration/.partial_supersedes.jsonl` — sidecar for partial-failure reconcile (rare; only when the supersede append fails after the proposal write succeeded).

### 5.4 `AppliedThresholdRecord`

```python
@dataclass(kw_only=True, frozen=True)
class AppliedThresholdRecord:
    proposal_id: str
    applied_at_iso: str
    operator_id: str
    target_file: str             # absolute resolved path from find_spec
    before_path: str             # relative path of the backup file
```

Persisted at `_bmad/calibration/proposals/<proposal_id>.applied/record.json`.

### 5.5 `ThresholdApplyError` taxonomy

`ThresholdApplyError(RuntimeError)` with one of these `code` attributes (string, exact match per test):

- `PROPOSAL_NOT_FOUND` — no JSON at the expected path.
- `CONFIRM_MISMATCH` — `confirm` arg does not match `proposal.confirm_slug` (compared via `hmac.compare_digest`). Payload includes `hint: str` — `"--confirm must be exactly 8 hex chars (did you swap --confirm and --proposal-id?)"` when `len(confirm) != 8`; `"confirm slug does not match"` otherwise. Length check happens BEFORE proposal load so the existence of the id is not leaked via timing.
- `PROPOSAL_EXPIRED` — `now_utc - created_at_iso > MAX_PROPOSAL_AGE_HOURS`.
- `STALE_PROPOSAL` — a newer proposal supersedes this one.
- `MODULE_NOT_RESOLVABLE` — `importlib.util.find_spec(target_module).origin` returned `None`.
- `LIVE_VALUE_DRIFTED` — live `ast.literal_eval`'d value != `proposal.current_value`.
- `TYPE_MISMATCH` — `type(node.value) is not type(proposal.current_value)`.
- `NON_LITERAL_TARGET` — located node is not `ast.Constant`.
- `UNSUPPORTED_SELECTOR_KIND` — selector kind not in `{"dict_tuple_element", "name"}`.
- `SELECTOR_NOT_FOUND` — the AST walk did not locate the selector.
- `BACKUP_FAILED` — `write_atomic_text` of the backup file raised; target untouched.
- `APPLY_REWRITE_INVALID` — post-splice file failed `ast.parse`; backup restored to target.
- `LOCK_TIMEOUT` — `.calibration.lock` not acquired in 30s.

## 6. Implementation surface — files

| File | New / Modified | LOC delta | Notes |
|---|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/innovation/threshold_proposer.py` | **New** | ~350 | `ThresholdProposer` + `ThresholdProposal` + `ProposerConfigError` + JSON persistence + filelock + deterministic id + observe_gate hook + auto-supersede + idempotent slug preservation. |
| `skills/bmad-story-automator/src/story_automator/core/innovation/threshold_apply.py` | **New** | ~250 | `apply_threshold_proposal` + `_resolve_module_file` + `_locate_leaf_constant` + `_compute_byte_slice` + `_splice_bytes` + BOM strip/restore + post-splice re-parse + backup restore. |
| `skills/bmad-story-automator/src/story_automator/core/innovation/threshold_decisions.py` | **New** | ~150 | `record_decision`, `load_decisions`, `latest_decision_for`; JSONL append with `os.open + os.fsync` durability under filelock. |
| `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` | Modified | +30 | New optional kwarg `threshold_proposer`; additive call site BEFORE `return gate_file` (after lineage_root + cost_total_usd blocks). Catches all exceptions; sets diagnostic field on failure. |
| `skills/bmad-story-automator/src/story_automator/core/gate_audit.py` | Modified | +35 | `GateThresholdProposalAudit` dataclass; added to `_AuditEvent` union — additive precedent set by `GateReadinessAudit`. No `telemetry_events.py` touch. |
| `skills/bmad-story-automator/src/story_automator/commands/calibration_cmd.py` | Modified | +200 | Subcommand dispatcher + 5 handlers (`propose`, `list-proposals`, `show`, `apply`, `reject`). Bare invocation byte-identical (no `sort_keys=True`). Diff rendering helper for `show`. |
| `skills/bmad-story-automator/src/story_automator/cli.py` | Modified | +0–6 | Re-wire `calibration` to a subcommand dispatcher if not already routed. Confirm by reading `cli.py` first. |
| `skills/bmad-story-automator/tests/test_threshold_proposer.py` | **New** | ~360 | ≥17 tests — see §7.2. |
| `skills/bmad-story-automator/tests/test_threshold_apply.py` | **New** | ~380 | ≥18 tests — see §7.3. |
| `skills/bmad-story-automator/tests/test_threshold_decisions.py` | **New** | ~160 | ≥7 tests — see §7.4. |
| `skills/bmad-story-automator/tests/test_calibration_cmd_proposals.py` | **New** | ~240 | ≥10 tests; golden-fixture byte-equality test for bare invocation. |
| `skills/bmad-story-automator/tests/fixtures/calibration_bare_v1.expected.json` | **New** | ~30 | Frozen golden fixture for `tests/test_calibration_cmd_proposals.test_bare_invocation_byte_identical`. |
| `tests/test_audit_regression.py` | Modified | +180 | `ThresholdApplyIsolationInvariant` class with: structural exemption (`_defines_apply_helper` modeled on `_defines_scrub_helper` at lines 659-673), structural CLI-handler recognition, BOTH `core/` AND `commands/` scope, binding-tracking AST walker (modeled on `UnifiedStateWriteIsolationInvariant._module_violates` at 743-855), three sub-tests (direct call rejection / indirect rejection / drift-band default-off pinning), two-direction positive-failure proof. |
| `tests/test_audit_regression.py` | Modified | +50 | `ThresholdLockIsolationInvariant` class — AST-scan `core/innovation/threshold_*.py` and reject any `FileLock(...)` construction whose path arg is not `.calibration.lock`. Positive-failure synthetic violator with a hand-crafted `FileLock(".gate.lock")` call. |
| `docs/changelog/2026-06-23-c5-self-improving-gate.md` | **New** | ~55 | `[FULL]` tag; documents the three new modules, the new kwarg, the new in-memory fields, the new CLI subcommands, both new audit-floor invariants, the lock-ordering policy. |
| `docs/spec/frozen-gate-surface.md` | Modified | +28 | New `### core/innovation/threshold_proposer.py` section listing the public surface and behavioral invariants (advisory-only, never auto-applies, in-memory-only gate-file additions, no telemetry-events touch, lock-isolation). |
| `CLAUDE.md` | Modified | +22 | New "Self-improving gate (C5)" section under "Recently shipped (session 2026-06-23)"; update the "additive kwargs (cumulative)" list to add `threshold_proposer` as the seventh optional kwarg. |

Total LOC delta ≈ +1900, of which ~1170 is tests + docs. Run modules stay comfortably under 500 LOC.

### 6.1 Diff render contract

`commands/calibration_cmd._render_diff(before_source: str, after_source: str, lineno: int) -> str` (lives in `calibration_cmd.py`, not `threshold_apply.py`, so the apply path stays I/O-free of formatting concerns).

- ASCII-only — assert via `output.encode("ascii")` not raising.
- LF line terminators only (no CRLF).
- Unified-diff format: 3 lines of leading + trailing context.
- Output bounded to ≤7 lines.
- Deterministic for fixed inputs (no clock, no random) — repeated calls return byte-identical strings.

## 7. Acceptance criteria

### 7.1 Behavioral

**Proposer**

- AC-P-00 — Proposer reads `priority` per gate from `gate_file["categories"][<target_category>]["required"]["priority"]`. Never re-derives.
- AC-P-01 — `observe_gate` returns `None` when matching gates in `_bmad/gate/verdicts/` are fewer than `min_evidence_window`.
- AC-P-02 — Tail-of-window (last `consecutive_runs` matching gates) all in `target_pass_rate_band` → returns `None`.
- AC-P-03 — Tail-of-window all above the upper band → emits proposal with `delta > 0`, clamped by `max_delta_pct`.
- AC-P-04 — Tail-of-window all below the lower band → emits proposal with `delta < 0`, clamped by `max_delta_pct`.
- AC-P-05 — `proposal_id` is deterministic over `(target_module, target_symbol, selector, current_value, proposed_value, sorted evidence_window)`. Re-running the proposer on identical evidence yields the SAME `proposal_id` AND the existing on-disk JSON is preserved byte-identical (slug + created_at preserved; no decision appended).
- AC-P-06 — Proposal JSON written via `write_atomic_text`, under `_bmad/calibration/.calibration.lock` (30s timeout).
- AC-P-07 — `enable_drift_band_proposals=False` (default) blocks any proposal whose `target_symbol` is one of `{STABLE_MAX, MINOR_MAX, MAJOR_MAX}`.
- AC-P-08 — `observe_gate` does NOT raise on missing `_bmad/calibration/` — lazily created under the lock.
- AC-P-09 — Missing `_bmad/gate/verdicts/` returns `None`. Missing `target_category` from a gate → that gate is dropped from the window (does NOT count toward `min_evidence_window`).
- AC-P-10 — `ProposerConfigError` raised at constructor when `min_evidence_window < consecutive_runs`.
- AC-P-11 — `evidence_window` is sorted ASCII-lexicographically by `gate_id`. Filesystem mtime is never consulted. Verified by populating fixture gate files with different mtimes but same gate_id contents on two checkouts; both must produce identical `proposal_id`.
- AC-P-12 — Floats are quantized to source-textual precision; `repr(quantized).encode("ascii")` length ≤ 24 bytes.
- AC-P-13 — Auto-supersede appends `superseded` for a prior pending proposal on the same `(target_module, target_symbol, selector)` — but NOT if `latest_decision_for(prior_id) in {accept, reject}`.
- AC-P-14 — Idempotent re-emit on the same `proposal_id` preserves `confirm_slug` and `created_at_iso` byte-identically (verified via mtime + content equality).
- AC-P-15 — Auto-supersede atomic ordering: proposal write FIRST under lock; supersede append SECOND. If supersede append fails after write succeeds, partial record is appended to `_bmad/calibration/.partial_supersedes.jsonl`.
- AC-P-16 — Calibration table missing → rationale degrades gracefully (omits the calibration sentence), proposer still emits.
- AC-P-17 — `GateThresholdProposalAudit(event="proposal_created", proposal_id=..., ...)` emitted via `emit_gate_audit` on every NEW proposal (not on byte-identical re-emit).

**Apply**

- AC-A-01 — `len(confirm) != 8` → `CONFIRM_MISMATCH` with `hint="--confirm must be exactly 8 hex chars (did you swap --confirm and --proposal-id?)"`. Validated BEFORE proposal load (no existence leak).
- AC-A-02 — Bad slug (correct length) → `CONFIRM_MISMATCH` with `hint="confirm slug does not match"`. Also appends a `confirm_failed` decision under the same lock before raising.
- AC-A-03 — Missing proposal id → `PROPOSAL_NOT_FOUND`. No source touched. No decision appended.
- AC-A-04 — Newer proposal supersedes → `STALE_PROPOSAL`.
- AC-A-05 — TTL exceeded → `PROPOSAL_EXPIRED`. Tested with a frozen-clock fixture.
- AC-A-06 — `find_spec(target_module).origin is None` → `MODULE_NOT_RESOLVABLE`.
- AC-A-07 — `ast.literal_eval` of the located leaf != `proposal.current_value` → `LIVE_VALUE_DRIFTED`. Source untouched.
- AC-A-08 — Located node is not `ast.Constant` (e.g., operator wrote `MINOR_MAX = 1/10`) → `NON_LITERAL_TARGET`.
- AC-A-09 — `type(node.value) is not type(proposal.current_value)` → `TYPE_MISMATCH`.
- AC-A-10 — Happy-path `dict_tuple_element` splice: target file diff is byte-identical except for the targeted Constant's bytes. Annotation `dict[str, tuple[int, int]]` subtree is byte-identical. Surrounding tuple parentheses, commas, trailing same-line comment (`# required_pct, fail_floor`) preserved.
- AC-A-11 — Happy-path `name` splice: only the targeted constant value's bytes change.
- AC-A-12 — UTF-8 BOM present at file start: BOM stripped before parse, splice on BOM-stripped bytes, BOM re-prepended before write. Result file has BOM and the correct splice.
- AC-A-13 — Non-ASCII content elsewhere in the source (e.g., a Cyrillic comment higher in the file) does NOT misalign the splice; `col_offset` is correctly treated as a UTF-8 byte offset.
- AC-A-14 — Backup written BEFORE splice. Synthetic crash (mocked `write_atomic_text` for the target file raising) leaves target byte-identical to pre-apply.
- AC-A-15 — Post-splice file fails `ast.parse` (synthetic byte corruption via patched splice computer) → backup restored to target; `APPLY_REWRITE_INVALID` raised. Target byte-identical to pre-apply.
- AC-A-16 — Apply happy path: `record.json` written and `decisions.jsonl` appended with `action="accept"` (durable os.open+fsync).
- AC-A-17 — Two concurrent applies on the same proposal from two processes serialize via `.calibration.lock`; second fails `LIVE_VALUE_DRIFTED` because source now matches `proposed_value`.
- AC-A-18 — `LOCK_TIMEOUT` raised when `.calibration.lock` is unavailable for 30s (mocked).
- AC-A-19 — `UNSUPPORTED_SELECTOR_KIND` for hand-crafted proposal with `kind="foo"`.
- AC-A-20 — Apply emits `GateThresholdProposalAudit(event="proposal_applied", ...)` after splice success.

**Decisions**

- AC-D-01 — `record_decision` appends one durable JSONL line (`os.open(O_APPEND)` + `os.fsync(fd)`).
- AC-D-02 — Two concurrent processes appending serialize via filelock; both lines present, no interleaving.
- AC-D-03 — Filter by `proposal_id` returns only matching entries, in append order.
- AC-D-04 — `latest_decision_for` returns the most recent decision for the id, or `None`.
- AC-D-05 — `confirm_failed` entries accumulate; visible via `list-proposals --include-failed`.
- AC-D-06 — Crash between `os.write` and lock release (simulated): the written line IS durable on next read (because `os.fsync` ran inside the lock-held region BEFORE release).
- AC-D-07 — Missing `_bmad/calibration/` lazily created under the lock.

**Gate-orchestrator wiring**

- AC-G-01 — `run_production_gate(..., threshold_proposer=None)` returns a dict with NO `threshold_proposal_ref` AND NO `threshold_proposer_error` keys. Verified by `set(returned.keys())` equality between pre-C5 fixture and C5 default-kwarg call. **The on-disk gate JSON under `_bmad/gate/verdicts/<gate_id>.json` is byte-identical in both pre-C5 and C5 because `persist_gate_file` runs at `verdict_engine.py:272` BEFORE orchestrator mutations — this matches the existing `evidence_merkle_root` / `lineage_root` / `cost_total_usd` pattern.**
- AC-G-02 — `run_production_gate(..., threshold_proposer=proposer)` ALWAYS sets `gate_file["threshold_proposal_ref"]` (in-memory) to either a 16-hex string (proposal emitted) or `""` (no proposal). The on-disk gate file remains byte-identical to the pre-C5 form (no new field on disk).
- AC-G-03 — When `observe_gate` raises, gate completes normally; `threshold_proposal_ref=""`, `threshold_proposer_error=<ExceptionClassName>` on the returned dict. The exception MUST NOT propagate.
- AC-G-04 — When `cost_total_usd` emission AND threshold proposal both run, neither blocks the other; both fields present on the in-memory dict.
- AC-G-05 — `GateThresholdProposalAudit(event="proposal_created", ...)` emitted via `emit_gate_audit` when a NEW proposal is created. The dataclass is in `gate_audit.py`'s `_AuditEvent` union; no `telemetry_events.py` touch.

**CLI**

- AC-C-01 — `story-automator calibration` (bare) emits **byte-identical** JSON to the pre-C5 commit for the same telemetry fixture. Test compares actual bytes to `tests/fixtures/calibration_bare_v1.expected.json`. Exit 0.
- AC-C-02 — `story-automator calibration propose [--window N] [--ttl-hours H]` emits `{ok:true, proposal:{proposal_id, confirm_slug, target_symbol, target_category, current_value, proposed_value, delta, rationale, ...}}` when a proposal is emitted; `{ok:true, proposal:null}` when not. Exit 0.
- AC-C-03 — `story-automator calibration list-proposals [--include-failed]` emits `{ok:true, proposals:[{proposal_id, confirm_slug, target_module, target_symbol, current_value, proposed_value, created_at_iso, latest_decision}, ...]}` sorted by `created_at_iso` descending. Exit 0 (empty list is NOT an error).
- AC-C-04 — `story-automator calibration show <id> [--include-slug]` emits `{ok:true, proposal:{...slug "<redacted>" unless --include-slug...}, diff:"...", applied_record:...|null}`. Diff is ASCII-only unified-diff, 3-line context, ≤7 lines, LF only, deterministic. Exit 0. Missing id → exit 1 + `{ok:false, error:"PROPOSAL_NOT_FOUND", proposal_id:<id>}`.
- AC-C-05 — `story-automator calibration apply --proposal-id <id> --confirm <slug>` calls into `threshold_apply.apply_threshold_proposal`; success returns `{ok:true, applied:true, target_file:<resolved>}` with exit 0; ThresholdApplyError returns `{ok:false, error:<code>, hint?:<str>}` with exit 1; missing flag returns exit 2.
- AC-C-06 — `story-automator calibration reject --proposal-id <id> --reason "<note>"` appends a `reject` decision; success → exit 0 + `{ok:true, rejected:true}`. Missing id → exit 1 + `{ok:false, error:"PROPOSAL_NOT_FOUND"}`. Missing flag → exit 2.
- AC-C-07 — `story-automator calibration --help` (and each subcommand `--help`) lists all 5 subcommands plus the bare-call note; exit 0; rendered via argparse.
- AC-C-08 — Three-way exit-code contract pinned: 0 success, 1 domain error, 2 argparse error. Tested via `subprocess.run(..., capture_output=True).returncode` assertions on each subcommand path.

### 7.2 `tests/test_threshold_proposer.py` minimum coverage
1. Below-window evidence → `None`.
2. Stable in-band evidence → `None`.
3. Above-band tail-of-window → positive delta proposal.
4. Below-band tail-of-window → negative delta proposal.
5. Delta clamped at `max_delta_pct`.
6. Deterministic `proposal_id` over identical inputs.
7. Slug + created_at preserved on byte-identical re-emit (mtime + content equality).
8. `enable_drift_band_proposals=False` blocks drift-band targets.
9. Concurrent writers serialize via filelock.
10. Missing `_bmad/calibration/` created lazily.
11. Missing `_bmad/gate/verdicts/` returns `None`.
12. Gates missing `target_category` or `actual.coverage_pct` dropped from the window.
13. `reject_proposal` appends `reject` decision; proposal JSON unchanged.
14. Auto-supersede of a prior PENDING proposal on the same selector; does NOT supersede an accepted prior.
15. `evidence_window` sorted by gate_id ASCII; deterministic across fixture mtimes.
16. `ProposerConfigError` when `min_evidence_window < consecutive_runs`.
17. Calibration table missing → rationale omits calibration sentence; proposer still emits.

### 7.3 `tests/test_threshold_apply.py` minimum coverage
1. `PROPOSAL_NOT_FOUND` when JSON absent.
2. Bad-length confirm → `CONFIRM_MISMATCH` with length-aware hint (and NO `confirm_failed` decision appended — length check is BEFORE load).
3. Correct-length but wrong slug → `CONFIRM_MISMATCH` + `confirm_failed` decision appended.
4. `PROPOSAL_EXPIRED` (frozen clock).
5. `STALE_PROPOSAL` when a newer proposal supersedes.
6. `MODULE_NOT_RESOLVABLE` (mocked `find_spec` returning None).
7. `LIVE_VALUE_DRIFTED` when source has been edited.
8. `TYPE_MISMATCH` for float-proposed-int-target hand-crafted proposal.
9. `NON_LITERAL_TARGET` (operator wrote `MINOR_MAX = 1/10`).
10. `UNSUPPORTED_SELECTOR_KIND` for `kind="foo"`.
11. Happy path `dict_tuple_element`: byte-diff equals exactly the leaf Constant's bytes; annotation byte-identical; trailing comment byte-identical.
12. Happy path `name`: ditto for a Name = Constant assignment.
13. UTF-8 BOM preserved + splice lands correctly.
14. Non-ASCII content elsewhere in source: splice lands correctly (UTF-8 byte offset honored).
15. Backup written BEFORE splice; mocked target write failure leaves target byte-identical pre-apply.
16. Post-splice `ast.parse` failure (synthetic byte-corruption via patched splice computer): backup restored + `APPLY_REWRITE_INVALID`.
17. `record.json` + `decisions.jsonl` `accept` line written on success.
18. Two concurrent applies on the same proposal: second fails `LIVE_VALUE_DRIFTED`.
19. Re-apply of an already-applied proposal raises `LIVE_VALUE_DRIFTED`.
20. `LOCK_TIMEOUT` (mocked).

### 7.4 `tests/test_threshold_decisions.py` minimum coverage
1. Append one decision, read back.
2. Append from two processes concurrently; both lines present, no interleaving.
3. Filter by `proposal_id`.
4. `latest_decision_for` correctness across multiple appends.
5. Lock timeout (mocked).
6. Missing `_bmad/calibration/` lazily created.
7. Durability: crash between `os.write` and lock release (simulated via mocked `lock.release` raising) — written line IS durable because fsync ran before release.

### 7.5 `tests/test_audit_regression.py` — two new invariants

**`ThresholdApplyIsolationInvariant`** — closes the "self-improving gate could autonomously mutate its own rules" hazard. Modeled exactly on `AuditKeyEnvScrubInvariant` (lines 530–732) + `UnifiedStateWriteIsolationInvariant` (lines 733–906) for structural rename-proof exemption + binding-tracking. Three sub-tests:

1. **`test_ast_no_direct_or_indirect_apply_in_core_and_commands`** — walks every `.py` under BOTH `skills/bmad-story-automator/src/story_automator/core/` AND `skills/bmad-story-automator/src/story_automator/commands/`. For each module, performs structural exemption:
   - `_defines_apply_helper(tree)`: skip any module whose top-level body contains `def apply_threshold_proposal(...)` — rename-proof (matches `_defines_scrub_helper` at lines 659-673).
   - `_is_cli_apply_handler(tree)`: structural recognition — skip any module under a `commands/` path component that defines a top-level FunctionDef whose first non-self argument is typed `confirm: str` AND whose body contains a Call to `apply_threshold_proposal`. (Rename-proof; survives the §3 pre-authorized split into `calibration_subcommands.py`.)
   
   For non-exempt modules, the AST walker tracks bindings (matches `UnifiedStateWriteIsolationInvariant._module_violates` lines 743–855):
   - `from ... import apply_threshold_proposal as ALIAS` → ALIAS added to forbidden set.
   - `Assign(targets=[Name(LHS)], value=<resolves to apply_threshold_proposal or alias>)` → LHS added to forbidden set.
   - Flag any `Call` whose `func` is `Name` in the forbidden set OR `Attribute` whose `attr == "apply_threshold_proposal"` whose receiver is not in the structural-exemption set.
   - Also flag `Call` to `getattr` whose 2nd arg literal-evals to `"apply_threshold_proposal"`.
   - Also flag `importlib.import_module(...).apply_threshold_proposal` attribute chains.

2. **`test_positive_failure_synthetic_violator_is_caught`** — two-direction proof matching `UnifiedStateWriteIsolationInvariant.test_positive_failure_synthetic_violator_is_caught` (lines 859–905). (a) Synthesize source containing direct call + alias-rebinding call + indirect getattr call; assert all three flagged. (b) Take the real `threshold_apply.py` source bytes, strip the `def apply_threshold_proposal` exemption-defining FunctionDef from the AST, re-parse, assert the walker does NOT trip on the residual file — proves the invariant rule itself is operative independent of the exemption.

3. **`test_drift_band_proposals_disabled_by_default`** — `assert inspect.signature(ThresholdProposer.__init__).parameters["enable_drift_band_proposals"].default is False`. Pins the safety-critical default like `PluginTrustBoundaryInvariant.test_plugin_manifest_keys_closed_set` (line 397).

**`ThresholdLockIsolationInvariant`** — closes the lock-ordering deadlock class. One AST-scan test:

1. **`test_threshold_modules_only_acquire_calibration_lock`** — walks `skills/bmad-story-automator/src/story_automator/core/innovation/threshold_*.py` and inspects every `Call` whose `func` (or `func.attr`) is `FileLock` or `filelock.FileLock`. For each such call, the first positional or `lock_file=` kwarg's literal value MUST end with `.calibration.lock`. Any other lock path is flagged. Positive-failure synthetic violator: hand-crafted `FileLock(".gate.lock")` Call must be caught.

(The existing audit-floor suite stays green — `tests.test_audit_regression` exits zero. No hardcoded count claim.)

### 7.6 Quality gates

- `python -m ruff check skills/bmad-story-automator/src/story_automator/core/innovation/threshold_*.py` exits zero.
- `python -m ruff format --check` over the three new modules + `gate_orchestrator.py` + `gate_audit.py` + `calibration_cmd.py` exits zero.
- `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_threshold_proposer tests.test_threshold_apply tests.test_threshold_decisions tests.test_calibration_cmd_proposals tests.test_audit_regression` exits zero, with the full 3,763-test baseline still green.
- `python -m coverage run --include="*/core/innovation/threshold_*.py" -m unittest tests.test_threshold_proposer tests.test_threshold_apply tests.test_threshold_decisions && python -m coverage report --fail-under=90` exits zero.
- Import-allowlist grep over the three new modules: zero `requests|httpx|aiohttp|subprocess|os\.system`.
- `wc -l` on each new module: ≤ 500.
- `npm run verify` exits zero.

## 8. Frozen-gate-surface contract

Per the additive-only contract:

1. **New optional kwarg only.** `run_production_gate(threshold_proposer=None)` defaults to None; existing callers pass nothing and keep byte-identical behavior. The pre-C5 → C5 returned-dict diff is the empty set when `threshold_proposer=None`.
2. **New in-memory-only fields.** `threshold_proposal_ref` and `threshold_proposer_error` are present on the in-memory returned dict only when the kwarg was supplied. **The on-disk gate JSON under `_bmad/gate/verdicts/<gate_id>.json` is unchanged in both pre-C5 and C5 — `persist_gate_file` runs BEFORE all orchestrator mutations.** This matches the existing pattern shared with `evidence_merkle_root`, `lineage_root`, `cost_total_usd`.
3. **`make_gate_file` is unchanged.** `priority` is read per-category from existing `gate_file["categories"][<cat>]["required"]["priority"]` — no new top-level field, no `GateFileDeterminismBaseline` update.
4. **New CLI subcommands only.** Bare `calibration` invocation byte-identical (pinned by golden fixture).
5. **No telemetry-event-type additions.** `GateThresholdProposalAudit` rides `UnknownEvent` per `gate_audit.py`'s existing pattern.
6. **New audit-floor invariants are additive.** The existing audit-floor suite stays green; no method is removed or renamed.

## 9. Adversarial review checklist

- **A-1.** *Source reformatted between propose and apply.* `ast.parse` finds the value expression by structure, not by line number; `ruff format` is supported.
- **A-2.** *Same-line trailing comment.* Splice range is the leaf Constant's bytes only; comments preserved.
- **A-3.** *Two operators apply concurrently.* Per-project filelock serializes; second fails `LIVE_VALUE_DRIFTED`.
- **A-4.** *Wrong-type proposed value.* Constructor invariant `type(proposed) is type(current)`; apply-time `TYPE_MISMATCH` defense-in-depth.
- **A-5.** *Network-mounted `_bmad/`.* `write_atomic_text` uses `os.replace` same-directory; same-volume by construction.
- **A-6.** *Sparse telemetry / noisy 5-gate window.* Wide hysteresis `[0.80, 0.95]` + `consecutive_runs=3` requirement; operator can raise `min_evidence_window`.
- **A-7.** *Non-existent selector.* `SELECTOR_NOT_FOUND` before any write.
- **A-8.** *Malicious proposal JSON.* No `eval` of any field; `proposed_value` is numeric (enforced by dataclass); `apply_threshold_proposal` is mechanically isolated from `core/` per audit-floor invariant.
- **A-9.** *Mid-apply dir deletion.* Filelock acquired before proposal load; concurrent removal races into `PROPOSAL_NOT_FOUND`.
- **A-10.** *Proposal id collision.* 64-bit sha256 prefix; live `current_value` check catches mismatched-but-collided ids.
- **A-11.** *Human-readable view.* `show <id>` renders unified-diff alongside JSON (§6.1).
- **A-12.** *Repeated identical observe_gate calls.* Idempotent — same `proposal_id`, preserved slug + created_at, no decision appended.
- **A-13.** *Audit-event volume.* ≤ 1 proposal/day + ≤ 5 decisions/day → ≤ 200 KiB/year.
- **A-14.** *`gate_rules.py` renamed.* `target_module` is a logical Python path resolved via `find_spec`; survives rename within the same module (a true module rename invalidates pending proposals → `MODULE_NOT_RESOLVABLE`).
- **A-15.** *Windows CRLF + UTF-8 BOM.* Bytes I/O end-to-end; BOM strip-and-restore; LF/CRLF preserved (the splice never touches line terminators).
- **A-16.** *Indirect-call vectors against the apply isolation.* `getattr(ta, "apply_threshold_proposal")`, `importlib.import_module(...).apply_threshold_proposal`, alias rebindings via `from ... import ... as ALIAS` — all flagged by `ThresholdApplyIsolationInvariant`'s binding tracker (§7.5).
- **A-17.** *Operator pipes `show` to a less-trusted tool.* `confirm_slug` redacted by default; `--include-slug` is loud opt-in.
- **A-18.** *Stale proposal applied months later.* `MAX_PROPOSAL_AGE_HOURS = 168` (7 days); `PROPOSAL_EXPIRED` on apply.
- **A-19.** *Buggy LLM loop brute-forcing the slug.* `confirm_failed` decisions accumulate and are visible via `list-proposals --include-failed`; TTL bounds the window; 32-bit entropy × 7 days = infeasible.
- **A-20.** *Race between operator-typed slug and observe_gate re-emit.* Idempotent re-emit preserves the slug; the race is impossible.
- **A-21.** *Lock co-acquisition deadlock with `.gate.lock`.* Structurally pinned by `ThresholdLockIsolationInvariant` — AST-rejects any non-`.calibration.lock` `FileLock` in `core/innovation/threshold_*.py`.
- **A-22.** *Source-vs-installed plugin layout.* `target_module` + `find_spec(...).origin` resolves to the actually-loaded module regardless of layout.

## 10. Open questions

1. **Per-operator passphrase in addition to slug?** Default **no**, per `singleuser-threat-model.md`.
2. **Propose during `recover_from_crash`-derived gate runs?** Default **yes** — those are real evidence.
3. **Auto-supersede at proposal creation or only at apply?** Default **at creation** for cleaner ledger (matches §3 + AC-P-13).
4. **`apply` invokes `npm run verify` as a post-apply gate?** Default **no** — operator runs `verify` themselves before committing.
5. **Multi-pair grouped proposals (e.g., raise BOTH P1.required_pct and P1.fail_floor at once)?** Default **no in v1**.
6. **`fail_floor` (index 1) proposals?** Default **no in v1** — signal underdetermined from persisted gate files; revisit when category metrics carry CONCERNS-vs-FAIL evidence.
7. **`traceability` category as a second registered backing?** Default **no in v1** — single-category-per-priority avoids signal aggregation ambiguity; follow-up after `correctness` calibration confirms the loop works.

## 11. Milestone tag + commit plan

Branch: `bma-d/integration-all`.

Commits (Conventional Commits + `Generated-By: claude-opus-4-7` + `Co-Authored-By:` trailers):

1. `feat(c5): ThresholdProposer + persistence (priority sourced per-category, deterministic ids, idempotent slug)` — `threshold_proposer.py` + tests.
2. `feat(c5): decisions ledger (durable jsonl, confirm_failed tracking)` — `threshold_decisions.py` + tests.
3. `feat(c5): apply step — AST-located byte splice, BOM-aware, find_spec resolution, anti-drift, backup-restore` — `threshold_apply.py` + tests.
4. `feat(c5): orchestrator wiring + audit event` — `gate_orchestrator.py` + `gate_audit.py` + integration tests.
5. `feat(c5): CLI subcommands + diff render + byte-identical bare-call regression` — `calibration_cmd.py` + `tests/fixtures/calibration_bare_v1.expected.json` + CLI tests.
6. `test(c5): ThresholdApplyIsolationInvariant + ThresholdLockIsolationInvariant` — `tests/test_audit_regression.py`.
7. `docs(c5): changelog + frozen-gate-surface + CLAUDE.md` — `docs/changelog/2026-06-23-c5-self-improving-gate.md` + frozen-surface section + CLAUDE.md updates.

Tags after each commit: `compat-c5-proposer`, `compat-c5-decisions`, `compat-c5-apply`, `compat-c5-orchestrator`, `compat-c5-cli`, `compat-c5-invariants`, `compat-c5-docs`. Final tag `milestone-C5-self-improving-gate` closes the series.

## 12. Anti-goals (deliberately not addressed)

- Time-series smoothing, Bayesian updates, or per-(model, task) calibration weighting. Flat moving-average over the evidence window suffices.
- Cross-project proposal sharing. Operators tune per-project.
- Auto-issue creation. Operator pipes JSON to `gh issue create` manually.
- "Learn from rejected proposals" feedback loop. Rejections are recorded but do not shape future proposals.
- Drift-band auto-tuning. Wired but disabled by default; follow-up after `PRIORITY_THRESHOLDS` confidence is built.
- Multi-knob coordinated proposals.
- Rollback CLI. Backups are written; restoring is `cp before.py.gate_rules <target>`.
- Re-persisting the gate file with the additive in-memory fields. Pre-existing pattern across N5/C2/C3; out of C5's scope (and arguably a separate follow-up worth raising — `evidence_merkle_root` / `lineage_root` / `cost_total_usd` would benefit too).

## 13. Gap report (adversarial review fold-in summary)

Rev 2 of this spec folds in 6 HIGH + 8 MEDIUM + 4 LOW gaps surfaced by an 8-lens parallel adversarial review of rev 1. Cross-lens convergence on the high-severity issues:

| Gap | Lenses flagged | Resolution |
|---|---|---|
| Gate file lacks top-level `priority` field | concurrency, audit_floor, frozen_surface, spec_quality, integration_completeness | Source `priority` per-category from `gate_file["categories"][<cat>]["required"]["priority"]` (already persisted at `core/category_rules.py:41`). NO change to `make_gate_file` or `GateFileDeterminismBaseline`. |
| Wrong gate-file persistence path (`evidence/<id>/gate.json` vs `verdicts/<id>.json`) | concurrency, frozen_surface, integration_completeness | Corrected to `_bmad/gate/verdicts/<gate_id>.json`; mandate `core.evidence_io.load_gate_file()` over raw open. |
| AST splice description incoherent (`subscript_pair` over a Dict-of-Tuples, `ast.get_source_segment` misused as byte-range helper, UTF-8 byte-offset / BOM gaps) | ast_rewrite_safety, frozen_surface, spec_quality | Renamed selector to `dict_tuple_element`; comprehensive walk algorithm with annotation-skip; bytes I/O end-to-end; BOM strip-and-restore; `ast.get_source_segment` retained ONLY for anti-drift cross-verify. |
| `threshold_proposal_ref` in-memory-only divergence | concurrency, integration_completeness | Aligned with the existing in-memory-only pattern (verified `persist_gate_file` at `verdict_engine.py:272` runs before all orchestrator mutations). Two-state contract: ABSENT when kwarg=None, PRESENT (`""` or hex) otherwise. Added diagnostic `threshold_proposer_error` field. |
| Audit-floor invariant uses filename allowlist + misses indirect-call vectors | audit_floor, frozen_surface, spec_quality, operator_workflow | Rewrote §7.5 with structural exemption (modeled on `_defines_scrub_helper`/`UnifiedStateWriteIsolationInvariant`), binding tracking, indirect-call detection, two-direction positive-failure proof, BOTH `core/` AND `commands/` scope. |
| `target_file` doesn't resolve in installed-plugin layouts | integration_completeness | Replaced with `target_module` (logical Python path) resolved via `importlib.util.find_spec(...).origin`. New error code `MODULE_NOT_RESOLVABLE`. |

Mediums folded: lock-ordering policy + invariant, idempotent slug preservation + `hmac.compare_digest`, durable `os.open+fsync` decision-ledger, auto-supersede atomicity + accept-skip guard, `int | float` dataclass + quantization, per-category coverage_pct signal definition, `evidence_window` sorted by `gate_id`, two-state field semantics matching C3, three-way CLI exit-code contract + byte-identical bare-call golden fixture.

Lows folded: proposal_id + confirm_slug surfaced in CLI propose/list output, `--include-slug` opt-in redaction on show, `confirm_failed` decision logging + `--include-failed` flag, `MAX_PROPOSAL_AGE_HOURS = 168` TTL with `PROPOSAL_EXPIRED` error, length-aware CONFIRM_MISMATCH hint, `--help` surface, telemetry calibration path noted as advisory-only, `GateThresholdProposalAudit` union-extension acknowledged.

---

**End of rev 2 spec.** Ready for the implementation workflow.
