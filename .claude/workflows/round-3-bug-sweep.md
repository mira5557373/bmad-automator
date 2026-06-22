# Round-3 bug-sweep — executed-workflow archive

> Date: 2026-06-22 · Branch: `bma-d/integration-all` · Milestone tag:
> `milestone-c-round-3-bug-sweep`. Companion artifacts:
> `docs/audit/round-3-bug-sweep.md`, `docs/audit/round-3-fix-now-list.md`,
> `docs/changelog/2026-06-22-round-3-bug-sweep.md`.

## Methodology actually executed

1. Captured milestone-C-start SHA `abea3f6` (post-Milestone-A); confirmed
   `milestone-b-operability-batch` tag absent (B↔C serialisation: C runs
   before B).
2. Baseline confirmed via `PYTHONPATH=skills/bmad-story-automator/src
   python3 -m unittest discover -s tests`: 4079 passing, 2 skipped.
3. Lens K read 5 target modules (`evidence_io.py`, `calibration.py`,
   `audit.py`, `budget_ceilings.py`, `gate_orchestrator.py`); enumerated
   5 candidate findings.
4. Lens L read 8 docstring-heavy modules (`risk_profile.py`,
   `readiness_gate.py`, `profile_composer.py`, `cli_dispatcher.py`,
   `plugins.py`, `gate_orchestrator.py`, `gate_remediation.py`,
   `product_profile.py`); enumerated 5 candidate findings.
5. Lens M walked every except clause in
   `gate_orchestrator.run_production_gate` /
   `route_gate_verdict` / `audit.AuditLog.append` and adjacent helpers;
   enumerated 6 candidate findings.
6. Per gap C-M-05, ran an adversarial-verifier pass on each `fix-now`
   candidate (3-bullet devil's-advocate). All three promoted candidates
   refuted ≥2/3 counter-arguments.
7. Per gap C-M-08, committed `docs/audit/round-3-fix-now-list.md`
   BEFORE any fix landed.
8. Per fix: RED test → minimal patch → GREEN test → full-suite + audit-
   floor + ruff + telemetry-diff + frozen-surface diff. Committed +
   tagged.
9. Closed with changelog + this workflow archive + milestone tag.

## Finding counts (final)

| Lens | Surfaced | Fix-now | Deferred | Discarded |
|---|---|---|---|---|
| K | 5 | 1 | 2 | 2 |
| L | 5 | 0 | 3 | 2 |
| M | 6 | 2 | 1 | 3 |
| **Total** | **16** | **3** | **6** | **7** |

## Per-fix commit SHAs

| Fix | Slug | Commit (subject) | Tag |
|---|---|---|---|
| C-1 | quarantine-mkdir-honest | `fix(gate-orchestrator): C-1 — _quarantine_corrupted_marker honest mkdir failure (lens M)` | `compat-c-1-quarantine-mkdir-honest` |
| C-2 | ceilings-single-pass | `fix(budget-ceilings): C-2 — evaluate_ceilings single-pass aggregation (lens K)` | `compat-c-2-ceilings-single-pass` |
| C-3 | recover-cleanup-honest | `fix(gate-orchestrator): C-3 — _recover_from_crash_locked partial-rmtree honesty (lens M)` | `compat-c-3-recover-cleanup-honest` |

Plus three docs-only commits (lens execution, triage table, changelog,
this workflow archive).

## Retrospective — what surprised us this round

1. **Lens M produced more fix-worthy findings than Lens K.** Going in,
   the expectation (per the spec) was that Lens K (perf) would be the
   high-yield lens because perf cliffs are easy to spot. The actual
   pattern: Lens K found one clean HIGH/HIGH (the ledger re-scan), but
   Lens M found two HIGH/HIGH bugs in the same `gate_orchestrator.py`
   recovery path — both arising from `except OSError: pass` swallows
   that lied to the operator. The next sweep should weight Lens M more
   heavily.

2. **Lens L's HIGH-severity floor was correct.** Three real docstring
   drifts surfaced (L-1 `forbidden_until` scalar-vs-dict, L-2
   `write_remediation_to_story` non-editable-section claim, L-3
   `risk_profile.py` missing action-band docs) but ALL three were MED
   severity. None cleared the HIGH × HIGH bar. The spec's anti-goal —
   "round-3 is NOT a docs-overhaul milestone" — held; the docstring
   drifts are queued as deferred follow-ups.

3. **The 3-bullet adversarial-verifier step changed one promotion.**
   L-1 (forbidden_until docstring contradiction) initially looked like
   a fix-now candidate but the counter-argument "MED severity, fails
   the HIGH × HIGH ship floor" was the sharpest. The verifier step
   prevented round-3 from sliding into a docs-fix milestone.

4. **The `quarantined=True` lie in `_quarantine_corrupted_marker` is
   the highest-severity bug found this sweep.** The audit-floor
   `MarkerCorruptionInvariant` test relies on quarantined=True
   IMPLYING evidence-was-moved; the legacy code violated that
   implication on mkdir failure. The audit-floor never caught this
   because it didn't inject a mkdir failure. Round-4 should consider
   widening invariant tests to include failure-injection at the
   filesystem boundary.

5. **The 5-fix cap was self-honoring this round.** Triage selected 3
   fix-now items naturally; no demotion was required. Round-2's 11
   fixes was the cautionary tale; round-3's 3 is the corrective
   pattern.

6. **B↔C serialisation gap (C-M-07) was free this round.** Milestone B
   had not started, so C ran strictly before B. No re-read of affected
   modules was needed. Future rounds should retain the
   `git tag --list 'milestone-b-operability-batch'` probe as a
   pre-condition.

## Deferred follow-ups (per the audit report)

- `bug-c-deferred-evidence-bundle-memo` (K-2): memoize
  `load_evidence_bundle` for repeated calls within one gate run.
- `bug-c-deferred-rmtree-under-lock` (K-5): lift `shutil.rmtree` out
  of the gate file lock.
- `bug-c-deferred-forbidden-until-doc` (L-1): fix module docstring
  contradiction in `profile_composer.py`.
- `bug-c-deferred-remediation-doc` (L-2): fix
  `write_remediation_to_story` non-editable-section claim.
- `bug-c-deferred-risk-doc` (L-3): document the action-band system
  alongside the priority system in `risk_profile.py`.
- `bug-c-deferred-audit-dirfsync` (M-3): directory fsync on first
  audit-log write.
