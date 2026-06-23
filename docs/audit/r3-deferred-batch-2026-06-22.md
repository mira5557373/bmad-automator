# Round-3 deferred batch — status report

> Workflow: `r3-deferred-batch` (parallel A-follow + M-3 + L-docstrings)
> Branch: `bma-d/integration-all`
> Baseline at start: 3a96d93 (Option 1 serial complete, 4128 tests green)
> Tip at finish: c821979 (4150 tests green)

## TL;DR

Three round-3 follow-ups dispositioned `defer-to-followup` in
`docs/audit/round-3-bug-sweep.md` shipped in parallel as a single batch:

- **A-follow** (e2e real verdict) — the Milestone-A factory self-evaluation
  harness landed an empty-registry lifecycle proof; A-follow upgrades it to a
  real PASS verdict by wiring a one-active-category smoke profile + in-test
  collector. Now exercises the live Merkle branch + parse_metrics + registry
  filtering, catching three regression classes the empty-registry harness
  cannot.
- **M-3** (audit dirfsync) — `AuditLog.append` previously fsynced the file
  fd but never the parent directory, so a crash immediately after the first
  append could leave the on-disk log empty even though the in-memory chain
  advanced. Added `fsync_dir(self.path.parent)` after the file fsync; chain
  semantics unchanged; all 26 audit-floor invariants and all 115 audit
  foundation tests stay green.
- **L-docstrings** (L-1 + L-2 + L-3) — three docstring drifts where the
  prose described behaviour the code does not implement. Docstring-only
  fixes; no signature, behaviour, or export touched.

Tests rose 4128 → 4150 (+22). Ruff clean. Audit-floor invariants still
26-green. No frozen-surface symbol changed. No new dependency.

## Per-item outcomes

| Slot      | Disposition tag                              | Status   | Commit     | Tests +/- |
|-----------|----------------------------------------------|----------|------------|-----------|
| A-follow  | n/a (Round-3 follow-up to Milestone A e2e)   | shipped  | `5216880`  | +5        |
| M-3       | `bug-c-deferred-audit-dirfsync` (round-3 K)  | shipped  | `4d8dde4`  | +5        |
| L-1       | `bug-c-deferred-forbidden-until-doc`         | shipped  | `c821979`  | +4 (combined) |
| L-2       | `bug-c-deferred-remediation-doc`             | shipped  | `c821979`  | (combined) |
| L-3       | `bug-c-deferred-risk-doc`                    | shipped  | `c821979`  | (combined) |

### A-follow — `5216880c2b17cbcd5e37fa8a1db8d670d8e6744f`

`feat(integration): A-follow — smoke profile + in-test collector produces real PASS verdict`

- Adds `tests/integration/data/profiles/smoke.json` — a one-active-category
  profile (correctness only) with the P1 matrix at 90% coverage.
- `FactorySmokeProfileTests` wires a trivial exit-0 subprocess collector
  plus a `parse_metrics` that returns `coverage_pct=95, regressions=0`,
  then asserts:
  - overall verdict = PASS, correctness category verdict = PASS,
  - `evidence_merkle_root` is a 64-hex live root (not the empty-bundle
    sentinel) and round-trips through
    `compute_evidence_bundle_merkle_root`,
  - gate file persists on disk, audit chain still verifies.
- Catches three real regression classes the empty-registry harness cannot:
  registry filtering bug → no collectors fire; `parse_metrics` not wired →
  `coverage_pct=0` → FAIL on P1 floor; evidence persistence dropped →
  empty bundle → fail-closed FAIL.

### M-3 — `4d8dde4d7e25be6acaf20023889428dee1b8be6a`

`fix(audit): M-3 — fsync parent directory after atomic rename for crash durability`

- `core/audit.py::AuditLog.append`: added `fsync_dir(self.path.parent)`
  call after the existing file-fd `os.fsync`.
- Reuses the already-shipped `fsync_dir` helper in `core/common.py` —
  silently no-op on Windows where `O_RDONLY` on a directory fails with
  `EPERM`.
- Tests: `tests/test_bugfix_M3_audit_dirfsync.py` (5 cases) — first append
  dirfsyncs, every subsequent append dirfsyncs, Windows fallback is robust
  to simulated `EPERM`, hash chain end-to-end verifies after dirfsync,
  missing-parent-directory edge case stays robust.

### L-docstrings — `c821979f04a87f2a739f5eb380c379b1c1815b64`

`docs(round-3): L-1+L-2+L-3 — docstring gaps for forbidden_until, remediation, risk action bands`

- **L-1** `core/profile_composer.py` — module docstring previously listed
  `forbidden_until` inside the "scalar top-level fields, last layer wins"
  bullet, but the field is in `_DICT_KEYS` and is deep-merged as an
  ADR-id-keyed dict union. Docstring now matches code.
- **L-2** `core/gate_remediation.py` — `write_remediation_to_story` claimed
  to insert the new `## Tasks` section "before the first non-editable
  section". The regex (`r"^##\s+"`) matches the first `##` heading of any
  kind, so on a story that opens with `## Status` the Tasks section lands
  before `## Status`. Docstring rewritten to describe real regex behaviour
  and explicitly disambiguate against the old wording.
- **L-3** `core/risk_profile.py` — module docstring described only the
  P0–P3 priority bands and omitted the M37 action bands
  (DOCUMENT / MONITOR / MITIGATE / BLOCK). Added a second classification
  block naming each band, its score range, and flagging `BLOCK` as the
  unmitigated-9 trigger.
- Tests: `tests/test_bugfix_L_docstrings.py` — 4 assertions that pin the
  new docstring substrings so future drift fails fast.

## What the factory finally proves

With A-follow shipped, the integration-level guarantee chain is complete:

1. **Profile composer is honoured end-to-end.** A smoke profile that
   names only one active category produces a registry that fires only
   collectors for that category — the empty-registry harness could not
   prove the filter actually runs.
2. **Live Merkle path is exercised.** `evidence_merkle_root` returned to
   the verdict is a 64-hex root computed over real canonical-JSON
   evidence, then round-tripped through
   `compute_evidence_bundle_merkle_root` — the sentinel branch is no
   longer the only branch covered by tests.
3. **Verdict aggregation crosses fail-closed.** `aggregate_verdicts` no
   longer returns FAIL because the active set is empty; it returns PASS
   because at least one collector ran, met its P1 floor, and emitted
   evidence.
4. **Audit chain durability is now crash-safe at the dirent layer.** M-3
   closes the last realistic loss window — first-append-and-crash on
   ext4/xfs/apfs — so the hash chain integrity argument no longer relies
   on best-effort dirent journaling.
5. **Operator-facing docstrings track the real behaviour** for the three
   modules where prose drift was most likely to mislead remediation
   authors (composer field semantics, remediation insertion point, risk
   action bands).

Combined, this means an operator running `run_production_gate` on a
single-active-category profile gets: a real verdict, a verifiable Merkle
root, a durable audit chain, and docstrings that match the code they are
calling.

## What is still deferred (K-2, K-5)

Two round-3 items remain explicitly deferred per the disposition matrix
in `docs/audit/round-3-bug-sweep.md`:

- **K-2** `load_evidence_bundle` called 2-3× per `run_production_gate`
  - Module: `core/gate_orchestrator.py:425, 583`, `core/verdict_engine.py:257`
  - Severity: MED; Confidence: HIGH. Fix requires either memoisation
    (with invalidation discipline against marker writes / mitigation-debt
    persistence) or call-site consolidation; both routes touch the
    frozen gate surface or require a careful invalidation contract.
  - Dispositioned `defer-to-followup` until Round-4 because the
    observable cost is wall-clock only — verdict correctness is not
    affected.

- **K-5** `recover_from_crash` holds gate lock across `shutil.rmtree`
  - Module: `core/gate_orchestrator.py:260-292`
  - Severity: LOW; Confidence: HIGH. Realistic only at 10000+ file
    evidence directories. The fix shape (rename-then-rmtree-outside-lock)
    is straightforward but adds a transient "orphan-evidence-dir" state
    that needs its own sweeper, so it was sized as a standalone Round-4
    item rather than batched here.

Both are tagged `bug-c-deferred-evidence-bundle-memo` and
`bug-c-deferred-rmtree-under-lock` in the round-3 disposition matrix and
will surface in the next round-4 fix-now list when prioritised.

## Final state

- **Branch tip**: `c821979` on `bma-d/integration-all`.
- **Tests**: 4150 passing (was 4128 at batch start), 2 skipped, 0 fail.
- **Ruff**: clean.
- **Audit-floor invariants**: 26 green.
- **Frozen-surface symbols**: untouched.
- **New dependencies**: none.
- **Files touched** (8 total, +677 / -8):
  - `skills/bmad-story-automator/src/story_automator/core/audit.py` (M-3)
  - `skills/bmad-story-automator/src/story_automator/core/profile_composer.py` (L-1)
  - `skills/bmad-story-automator/src/story_automator/core/gate_remediation.py` (L-2)
  - `skills/bmad-story-automator/src/story_automator/core/risk_profile.py` (L-3)
  - `tests/integration/data/profiles/smoke.json` (A-follow)
  - `tests/integration/test_factory_self_evaluation.py` (A-follow)
  - `tests/test_bugfix_M3_audit_dirfsync.py` (M-3)
  - `tests/test_bugfix_L_docstrings.py` (L-docs)
- **Workflow tag**: `r3-deferred-batch-complete`.
