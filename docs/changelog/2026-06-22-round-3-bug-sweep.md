## 260622 - [FULL] Round-3 bug sweep (K+L+M lenses)

### Summary

Adversarial sweep #3 of the production-gate codebase using three
*fresh* lenses — K (performance + scalability), L (documentation
correctness — docstring vs actual behavior), and M (failure-mode
taxonomy — except-clause recovery audit). 16 findings surfaced (5 K,
5 L, 6 M); triage promoted 3 to fix-now (HIGH severity × HIGH
confidence), 7 deferred for round-4 / follow-up specs, 6 discarded
as verified-not-a-bug. Total ledger of findings preserved in
`docs/audit/round-3-bug-sweep.md` for cross-round traceability.

### Added

- `docs/audit/round-3-bug-sweep.md` — full per-lens findings report
  (16 findings, triage table, fix appendix, deferred + discarded).
- `docs/audit/round-3-fix-now-list.md` — locked fix-now slug list
  committed before any fix landed (per spec gap C-M-08).
- `tests/test_bugfix_c_1_quarantine_mkdir_honest.py` — pins truthful
  `quarantined` flag in `_quarantine_corrupted_marker`.
- `tests/test_bugfix_c_2_ceilings_single_pass.py` — pins single
  ledger open per `evaluate_ceilings` call.
- `tests/test_bugfix_c_3_recover_cleanup_honest.py` — pins
  `cleanup_failed` surface in `_recover_from_crash_locked`.

### Changed

- `core/gate_orchestrator.py` — `_quarantine_corrupted_marker`
  truthfully reports `quarantined=False` + `quarantine_error` on
  mkdir failure (fix C-1, Lens M).
- `core/budget_ceilings.py` — `evaluate_ceilings` now streams the
  JSONL ledger ONCE per call (was O(N·K) for K applicable ceilings,
  now O(N) + O(K)). Verdict identity preserved on existing
  fixtures (fix C-2, Lens K).
- `core/gate_orchestrator.py` — `_recover_from_crash_locked`
  surfaces `cleanup_failed=True` + `cleanup_error` when the orphan
  rmtree raises mid-walk; marker is still cleared regardless (fix
  C-3, Lens M).

### Fixed

- `_quarantine_corrupted_marker` no longer claims a successful
  quarantine after a failed mkdir. The audit-floor
  MarkerCorruptionInvariant's implicit contract (quarantined=True ⇒
  evidence-moved) holds again (C-1).
- `evaluate_ceilings` no longer re-streams the ledger once per
  applicable ceiling. With the canonical 4-window profile, gate-eval
  ledger I/O dropped from 4× to 1× (C-2).
- `_recover_from_crash_locked` no longer silently swallows partial
  rmtree failures; operators see `cleanup_failed=True` with the
  OSError text so the half-deleted-evidence state is investigable
  (C-3).

### Files

- `docs/audit/round-3-bug-sweep.md` (new)
- `docs/audit/round-3-fix-now-list.md` (new)
- `docs/changelog/2026-06-22-round-3-bug-sweep.md` (this file, new)
- `.claude/workflows/round-3-bug-sweep.md` (new)
- `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py`
- `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py`
- `tests/test_bugfix_c_1_quarantine_mkdir_honest.py` (new)
- `tests/test_bugfix_c_2_ceilings_single_pass.py` (new)
- `tests/test_bugfix_c_3_recover_cleanup_honest.py` (new)

### QA Notes

- Baseline (pre-C, post-A): 4079 passing, 2 skipped, 0 failing.
- Post-C: 4086 passing, 2 skipped, 0 failing (+7 tests across 3 fixes).
- Audit-floor invariants: 24, unchanged.
- Ruff: clean on `skills/`.
- `core/telemetry_events.py`: zero diff vs milestone-C-start
  (`abea3f6`).
- `docs/spec/frozen-gate-surface.md`: zero diff vs milestone-C-start.
- Frozen-gate-surface import-roster smoke: green — 14 symbols
  importable from `story_automator.core`.
- Tags created: `compat-c-1-quarantine-mkdir-honest`,
  `compat-c-2-ceilings-single-pass`,
  `compat-c-3-recover-cleanup-honest`, plus the milestone close
  `milestone-c-round-3-bug-sweep`.
- B↔C serialisation gap C-M-07 honored: C executed strictly BEFORE
  `milestone-b-operability-batch` (absent at milestone-C-start).
- 5-fix cap honored: 3 fix-now < 5 cap, with a pre-fix
  `docs/audit/round-3-fix-now-list.md` commit (gap C-M-08).
- HIGH-gap remediation from spec-review-2026-06-22-C:
  - C-H-01 PYTHONPATH: every unittest invocation prefixed with
    `PYTHONPATH=skills/bmad-story-automator/src`.
  - C-H-02 frozen-surface test: ad-hoc import-roster smoke recorded
    in audit §0; markdown-diff check confirmed zero diff.
  - C-H-03 stale HEAD pin: milestone-C-start SHA `abea3f6` recorded
    in audit §0 (not `6a957d2` as the original spec body claimed).
