## 260623 - [FULL] C5 self-improving gate

### Summary
Closes the observation → action loop on existing drift telemetry by
auto-emitting threshold-patch proposals against the gate's hardcoded
knobs (`PRIORITY_THRESHOLDS` in `core/gate_rules.py`) and exposing an
explicit, operator-gated apply path. The proposer is advisory: nothing
in `core/` may mutate source automatically. An explicit operator CLI
call carrying a per-proposal 8-hex confirmation slug performs the
single-knob, AST-located, surgical byte splice — pre-validated against
the live source and backed up before write. Every proposal and every
accept/reject/superseded/confirm_failed decision is recorded in an
append-only JSONL ledger under `_bmad/calibration/`.

### Added
- `core/innovation/threshold_proposer.py` — `ThresholdProposer`,
  `ThresholdProposal`, `ProposerConfigError`; deterministic `proposal_id`
  over `(target_module, target_symbol, selector, current_value,
  proposed_value, evidence_window)`; idempotent slug + `created_at_iso`
  preservation on byte-identical re-emit; auto-supersede of prior
  pending proposals on the same selector (accept/reject-aware).
- `core/innovation/threshold_apply.py` — `apply_threshold_proposal`,
  `AppliedThresholdRecord`, `ThresholdApplyError` taxonomy (13 codes).
  AST-located byte splice with UTF-8-byte-offset honoring, BOM
  strip-and-restore, `find_spec(target_module).origin` resolution
  (works under source-tree AND installed-plugin layouts), backup
  before splice, post-splice `ast.parse` verification with restore
  on failure, `hmac.compare_digest` slug check.
- `core/innovation/threshold_decisions.py` — `record_decision`,
  `load_decisions`, `latest_decision_for`, `DecisionRecord`. Durable
  `os.open(O_APPEND) + os.fsync` append under `.calibration.lock`.
- `gate_audit.GateThresholdProposalAudit` dataclass added to the
  `_AuditEvent` union (precedent set by `GateReadinessAudit`); rides
  `UnknownEvent` forward-compat — `core/telemetry_events.py` NOT touched.
- `commands/calibration_cmd.py` subcommand dispatcher: `propose`,
  `list-proposals`, `show`, `apply`, `reject`. Bare `calibration`
  invocation byte-identical to pre-C5 (pinned by golden fixture).
- `ThresholdApplyIsolationInvariant` + `ThresholdLockIsolationInvariant`
  in `tests/test_audit_regression.py` — structural-recognition AST
  invariants preventing direct/indirect/getattr/import_module call
  surfaces from any `core/` or `commands/` module (except the canonical
  apply helper itself and CLI-handler `confirm: str` signatures), and
  pinning `core/innovation/threshold_*.py` to ONLY ever acquire
  `.calibration.lock`.

### Changed
- `core/gate_orchestrator.run_production_gate(...)` gains a SEVENTH
  optional kwarg `threshold_proposer: ThresholdProposer | None = None`.
  When `None` (default), byte-identical to pre-C5. When provided, after
  `evaluate_gate` returns the orchestrator invokes
  `threshold_proposer.observe_gate(project_root, gate_file)` inside
  `try/except`; on success sets in-memory `gate_file[
  "threshold_proposal_ref"]` to the proposal id (or `""` when no
  proposal emitted); on failure sets `"threshold_proposal_ref" = ""`
  AND `"threshold_proposer_error" = type(exc).__name__`. Both fields
  are IN-MEMORY ONLY on the returned dict — `persist_gate_file` runs
  inside `evaluate_gate` BEFORE these mutations, matching the existing
  `evidence_merkle_root` / `lineage_root` / `cost_total_usd` pattern.

### Files
- skills/bmad-story-automator/src/story_automator/core/innovation/threshold_proposer.py
- skills/bmad-story-automator/src/story_automator/core/innovation/threshold_apply.py
- skills/bmad-story-automator/src/story_automator/core/innovation/threshold_decisions.py
- skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py
- skills/bmad-story-automator/src/story_automator/core/gate_audit.py
- skills/bmad-story-automator/src/story_automator/commands/calibration_cmd.py
- skills/bmad-story-automator/src/story_automator/cli.py
- skills/bmad-story-automator/tests/test_threshold_proposer.py
- skills/bmad-story-automator/tests/test_threshold_apply.py
- skills/bmad-story-automator/tests/test_threshold_decisions.py
- skills/bmad-story-automator/tests/test_c5_orchestrator_wiring.py
- skills/bmad-story-automator/tests/test_calibration_cmd_proposals.py
- skills/bmad-story-automator/tests/fixtures/calibration_bare_v1.expected.json
- tests/test_audit_regression.py
- docs/changelog/2026-06-23-c5-self-improving-gate.md
- docs/spec/frozen-gate-surface.md
- CLAUDE.md

### QA Notes
- No new Python deps; stdlib `ast`, `hashlib`, `hmac`, `importlib.util`,
  `json`, `os` + already-imported `filelock` + already-imported
  `core/atomic_io.write_atomic_text`.
- `core/telemetry_events.py` untouched (M01 ownership preserved).
- `make_gate_file` signature and `GateFileDeterminismBaseline`
  unchanged — `priority` is read per-category from
  `gate_file["categories"][<cat>]["required"]["priority"]`.
- On-disk `_bmad/gate/verdicts/<gate_id>.json` byte-identical to
  pre-C5 in both default and kwarg-supplied modes; the new
  `threshold_proposal_ref` / `threshold_proposer_error` fields are
  IN-MEMORY ONLY (matches N5 / C2 / C3 precedent).
- Lock-ordering invariant: `_bmad/calibration/.calibration.lock` is
  the only lock acquired by `core/innovation/threshold_*.py`; AST-scan
  pinned by `ThresholdLockIsolationInvariant`.
- Apply isolation: no `core/` or `commands/` module calls
  `apply_threshold_proposal` except the canonical helper itself and
  CLI handlers carrying `confirm: str` in their signature — pinned by
  `ThresholdApplyIsolationInvariant` binding-tracking AST walker.
- Drift-band proposals registered but disabled by default
  (`enable_drift_band_proposals=False`); pinned by inspect.signature
  invariant test.
- Proposal TTL: `MAX_PROPOSAL_AGE_HOURS = 168` (7 days); apply raises
  `PROPOSAL_EXPIRED` past the bound (configurable via `--ttl-hours`).
- Bare `story-automator calibration` invocation byte-identical to
  pre-C5 (regression test against `tests/fixtures/calibration_bare_v1.expected.json`).
- No historical changelog entry mutated.
