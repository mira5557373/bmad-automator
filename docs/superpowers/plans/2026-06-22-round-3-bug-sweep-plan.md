# Round-3 Bug Sweep — Implementation Plan

> Date: 2026-06-22 · Status: **Ready to execute** · Milestone: **C (Round-3 bug sweep)** · Branch: `bma-d/integration-all` (direct; no worktree, no PR).
> Companion spec: `docs/superpowers/specs/2026-06-22-round-3-bug-sweep-design.md`.
> Three fresh lenses — **Lens K (performance + scalability)**, **Lens L (documentation correctness)**, **Lens M (failure-mode taxonomy)** — surface findings; ≤ 5 HIGH × HIGH fixes ship; everything else is logged.

## Pre-requisites

1. **HEAD pinned**: confirm `git log -1 --oneline` reads `6a957d2` (or later — all D-04 follow-up commits reachable).
2. **Baseline green**:
   ```
   python3 -m unittest discover -s tests          # → 4070 passing, 2 skipped, 0 failing
   ruff check skills/                              # → clean
   python3 -m unittest tests.test_audit_regression # → 24 invariants
   python3 -m unittest tests.test_frozen_gate_surface # → green
   ```
3. **No worktree** (CLAUDE.md guardrail for this run); work directly on `bma-d/integration-all`.
4. **No `--no-verify`, no `--amend`, no force-push** at any step. New commits only.
5. **Output directories exist**: confirm `docs/audit/` is a real directory (it is — round-2 lives there) and `.claude/workflows/` is a real directory (it is — round-2 workflow lives there).
6. **Read the round-2 report first** (`docs/audit/round-2-bug-sweep.md`) — so the round-3 lenses are demonstrably different. If a round-3 finding duplicates a round-2 finding, that's a flag the lens wasn't fresh.
7. **Confirm modules' pre-sweep LOC** (recorded in the spec §3.1):
   ```
   wc -l skills/bmad-story-automator/src/story_automator/core/{evidence_io,calibration,audit,budget_ceilings,gate_orchestrator,risk_profile,readiness_gate,profile_composer,cli_dispatcher,plugins,gate_remediation,product_profile}.py
   ```
   Snapshot the numbers in the audit report's §0 (pre-sweep state) so post-sweep growth is auditable.

## Task list

### Phase 1 — Lens execution (read-only; produces the audit report draft)

- [ ] **C1.1** Create `docs/audit/round-3-bug-sweep.md` skeleton:
   ```
   # Round-3 bug sweep

   ## §0 — Pre-sweep state
     (HEAD sha, baseline test count, LOC snapshot per touched module, audit-floor invariant count)

   ## §K — Performance + scalability (Lens K)
   ## §L — Documentation correctness (Lens L)
   ## §M — Failure-mode taxonomy (Lens M)

   ## §Triage
     (table of all findings with (severity, confidence, disposition))

   ## §Fix appendix
     (per-shipped-fix QA log)

   ## §Deferred
     (deferred findings with follow-up slugs)

   ## §Discarded
     (verified-not-a-bug findings with rationale)
   ```

- [ ] **C1.2** **Lens K execution** — read each target module end-to-end:
   - `core/evidence_io.py` (442 LOC) — focus on `persist_evidence_record`, `read_gate_marker`, `write_gate_marker`, the canonical-JSON helper, hash-chain compute.
   - `core/calibration.py` (259 LOC) — iteration patterns over historical traces; JSON parse without size cap.
   - `core/audit.py` (482 LOC) — `AuditLog.append` (file lock + prev-hash compute); whether prev-hash is cached or re-read from disk per call.
   - `core/budget_ceilings.py` (523 LOC) — `evaluate_ceilings` (ledger scan); whether the ledger is re-loaded per event.
   - `core/gate_orchestrator.py` (718 LOC) — `run_production_gate` collector fan-out (sequential vs parallel-safe); `route_gate_verdict` (any nested loops).

   For each finding, append a subsection to `§K`:
   ```
   ### K-N: <slug>
   - **Module**: <file>:<line-range>
   - **Symptom**: <one paragraph>
   - **Severity**: LOW | MED | HIGH (with justification at 100 / 1000 / 10000 stories)
   - **Confidence**: LOW | MED | HIGH (with citation — code excerpt or microbenchmark)
   - **Fix shape**: constant-factor | algorithmic | schema-change
   - **Disposition**: (filled in during §C2)
   ```

   Target: 5-10 findings.

- [ ] **C1.3** **Lens L execution** — read each target module's docstrings and confirm each promise against the implementation:
   - `core/risk_profile.py`
   - `core/readiness_gate.py`
   - `core/profile_composer.py`
   - `core/cli_dispatcher.py`
   - `core/plugins.py`
   - `core/gate_orchestrator.py`
   - `core/gate_remediation.py`
   - `core/product_profile.py`

   Use `grep -n '"""' <file>` to enumerate docstrings, then `grep -n 'def \|class ' <file>` to enumerate the surrounding signatures; cross-check parameters and return types. Look for:
   - Return type mismatch (docstring says `dict[str, Any]`, code can return `None`).
   - Raises drift (docstring says `Raises: X`, code raises `Y`).
   - Parameter drift (docstring lists a param the signature does not have).
   - Closed-vocabulary misuse (`[FULL]`/`[LITE]`/`[SKELETON]`/`[DEFERRED]`; `PASS`/`CONCERNS`/`FAIL`/`WAIVED`; `continue`/`remediate`/`park`/`halt`).
   - Stale sibling reference (docstring names a helper that was renamed).

   For each finding, append to `§L`:
   ```
   ### L-N: <slug>
   - **Module**: <file>:<line-range>
   - **Docstring claim**: <exact quote>
   - **Actual behavior**: <code excerpt>
   - **Severity**: LOW | MED | HIGH (operator-incident shaped?)
   - **Confidence**: LOW | MED | HIGH (is the actual behavior unambiguous?)
   - **Fix shape**: docstring-only | docstring + small code adjustment | code-only (docstring is correct, code is wrong)
   - **Disposition**: (filled in during §C2)
   ```

   Target: 5-10 findings.

- [ ] **C1.4** **Lens M execution** — three critical paths, every except clause:

   **Path M1: `run_production_gate`**
   - `grep -n 'except ' skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — enumerate every `except` in the file; mark which are inside `run_production_gate` or its callee `_recover_from_crash_locked`.
   - For each: walk the recovery path, check for partial commit, resource leak, missing fsync, `from None` swallowing, TOCTOU.

   **Path M2: `route_gate_verdict`**
   - Same module; walk the verdict-routing branches; check for cases where the verdict is written but the marker is not cleared, or vice versa.

   **Path M3: `AuditLog.append`**
   - `grep -n 'except ' skills/bmad-story-automator/src/story_automator/core/audit.py` — enumerate every `except`.
   - Particular attention: the hash-chain compute path. Does an except mid-write leave a half-written line in the ledger?

   For each finding, append to `§M`:
   ```
   ### M-N: <slug>
   - **Path**: M1 | M2 | M3 — <function>
   - **Except clause**: <file>:<line> `except <Exception>:`
   - **Failure injected**: <description>
   - **Observed end-state**: <what survives in the filesystem / locks / open handles>
   - **Severity**: LOW | MED | HIGH (data loss? audit-chain corruption? operator-visible inconsistency?)
   - **Confidence**: LOW | MED | HIGH (can we write a test that reproduces?)
   - **Fix shape**: add cleanup | re-order operations | add fsync | broaden catch-set | narrow catch-set
   - **Disposition**: (filled in during §C2)
   ```

   Target: 5-10 findings.

- [ ] **C1.5** **Cross-check** against the round-2 report. Any round-3 finding that materially duplicates a round-2 finding gets marked `DUPLICATE-OF-R2:<finding-id>` and discarded with a one-line rationale.

- [ ] **C1.6** Commit the audit-report skeleton + lens-execution sections (no fixes shipped yet):
   ```
   git add docs/audit/round-3-bug-sweep.md
   git commit -m "docs(audit): round-3 bug-sweep lens execution (K, L, M) — findings logged"
   ```
   This commit ships the *findings*, even if zero fixes ship later. The information has value standalone.

### Phase 2 — Triage (fills in dispositions; selects ≤ 5 fix-now)

- [ ] **C2.1** For every finding (K, L, M combined), assign disposition: `fix-now` | `defer-to-round-4` | `defer-to-followup` | `discard`. Apply the rubric from spec §4.

- [ ] **C2.2** Apply the cap algorithm (spec §4.1). If more than 5 findings are `fix-now`, demote the lowest-ranked excess to `defer-to-round-4` with the rationale "round-3 5-fix cap displaced this finding."

- [ ] **C2.3** Update `docs/audit/round-3-bug-sweep.md §Triage` with the full table:
   ```
   | ID | Lens | Severity | Confidence | Disposition | Fix-now rank (if applicable) |
   |---|---|---|---|---|---|
   ```

- [ ] **C2.4** Decision gate: how many `fix-now` rows?
   - **0**: skip Phase 3 entirely. Milestone closes with a `[SKELETON]` changelog entry. Audit report alone is the deliverable.
   - **1-5**: proceed to Phase 3 for each.
   - **>5**: triage was sloppy — re-run §C2.2. The cap is non-negotiable.

- [ ] **C2.5** Commit the triage table:
   ```
   git add docs/audit/round-3-bug-sweep.md
   git commit -m "docs(audit): round-3 triage — N findings dispositioned (<=5 fix-now)"
   ```

### Phase 3 — Per-fix execution (run once per `fix-now` finding, 0-5 times total)

For each finding `C-N`:

- [ ] **C3.N.1** Author `tests/test_bugfix_c_<n>_<slug>.py`:
   - 2-4 tests, each RED-then-GREEN.
   - At least one test asserts the *production-incident-shaped* behavior described in the finding's "Symptom" or "Failure injected" entry.
   - For Lens K fixes: test asserts an *algorithmic invariant* (e.g., "operation called N times, not N²"), not a wall-clock benchmark.
   - For Lens L fixes: test asserts the *new* documented behavior matches the code OR (if it's a docstring-only fix) re-imports the module and inspects `__doc__`.
   - For Lens M fixes: test injects the failure (via `unittest.mock.patch` or fault-injection helpers) and asserts the end-state is consistent.

- [ ] **C3.N.2** Run `python3 -m unittest discover -s tests -k test_bugfix_c_<n>` — confirm RED.

- [ ] **C3.N.3** Apply the minimal patch in the target module. Per-fix LOC cap: ≤ 80 LOC. If the fix exceeds 80 LOC, **stop**; the finding becomes a follow-up spec, not a round-3 fix. Replace it in the fix-now list with the highest-ranked deferred candidate (if any).

- [ ] **C3.N.4** Re-run `python3 -m unittest discover -s tests -k test_bugfix_c_<n>` — confirm GREEN.

- [ ] **C3.N.5** Re-run full `python3 -m unittest discover -s tests` — confirm no regression. Audit-floor + frozen-gate-surface still green.

- [ ] **C3.N.6** `ruff check skills/` — confirm clean on touched files.

- [ ] **C3.N.7** Verify telemetry-events untouched:
   ```
   git diff HEAD -- skills/bmad-story-automator/src/story_automator/core/telemetry_events.py | wc -l
   # → must be 0
   ```

- [ ] **C3.N.8** Verify frozen-gate-surface untouched:
   ```
   python3 -m unittest tests.test_frozen_gate_surface
   ```

- [ ] **C3.N.9** Update `docs/audit/round-3-bug-sweep.md §Fix appendix` with the per-fix QA log (RED count → GREEN count, full-suite count before/after, ruff output).

- [ ] **C3.N.10** Commit + tag:
   ```
   git add tests/test_bugfix_c_<n>_<slug>.py skills/.../core/<module>.py docs/audit/round-3-bug-sweep.md
   git commit -m "fix(round-3): C-<n> — <slug> (lens <K|L|M>)"
   git tag compat-c-<n>-<slug>
   ```
   Conventional Commits subject; `fix(round-3):` for code fixes, `docs(round-3):` for docstring-only fixes.

### Phase 4 — Milestone close

- [ ] **C4.1** Author `docs/changelog/2026-06-22-round-3-bug-sweep.md`:
   ```
   ## 260622 - [FULL] Round-3 bug sweep (K+L+M lenses)
   # OR if zero fixes shipped:
   ## 260622 - [SKELETON] Round-3 bug sweep (K+L+M lenses, no fixes shipped)

   ### Summary
   ### Added           — new tests under tests/test_bugfix_c_*.py
   ### Changed         — per-fix bullet list (one line per shipped fix)
   ### Fixed           — same content as Changed, restated in terms of the operator-visible defect closed
   ### Files           — full list of touched paths
   ### QA Notes        — full-suite count before/after, audit-floor invariant count (stayed 24), npm run verify result
   ```
   Honor M11 closed vocabulary; honor CLAUDE.md changelog guardrails (no whitespace churn; one of the four tags only).

- [ ] **C4.2** Final verification matrix:
   ```
   python3 -m unittest discover -s tests              # → 4070 + N passing, 2 skipped
   ruff check skills/                                  # → clean
   python3 -m unittest tests.test_audit_regression     # → 24 invariants, green
   python3 -m unittest tests.test_frozen_gate_surface  # → green
   git diff HEAD~7 -- skills/bmad-story-automator/src/story_automator/core/telemetry_events.py | wc -l   # → 0
   npm run verify                                       # → green end-to-end
   ```

- [ ] **C4.3** Commit the changelog:
   ```
   git add docs/changelog/2026-06-22-round-3-bug-sweep.md
   git commit -m "docs(changelog): round-3 bug sweep (<FULL|SKELETON>) — N fixes, M deferred, K discarded"
   ```

- [ ] **C4.4** Archive the executed workflow at `.claude/workflows/round-3-bug-sweep.md` (matches the round-2 archive pattern):
   ```
   git add .claude/workflows/round-3-bug-sweep.md
   git commit -m "chore(workflows): archive round-3 bug-sweep executed workflow"
   ```
   The archive should record: actual finding counts per lens, actual fix-now / defer / discard counts, per-fix commit shas, and a one-paragraph retrospective ("what surprised us this round").

- [ ] **C4.5** Final milestone tag:
   ```
   git tag milestone-c-round-3-bug-sweep
   ```
   (No remote push from this plan — the user controls when remote-push happens.)

## Test files to author

Up to 5 files (one per shipped fix). Paths follow the convention `tests/test_bugfix_c_<n>_<slug>.py`. Each file ≤ 150 LOC.

The exact slug list cannot be enumerated in advance — it depends on which findings survive the triage gate in Phase 2. The audit report's §Fix appendix is the canonical post-hoc record.

If zero fixes ship, **zero test files** are authored. That is a valid outcome and not a failure mode of this plan.

## Commit + tag spec

| Step | Commit subject (Conventional Commits) | Tag |
|---|---|---|
| C1 (lens execution) | `docs(audit): round-3 bug-sweep lens execution (K, L, M) — findings logged` | — |
| C2 (triage) | `docs(audit): round-3 triage — N findings dispositioned (<=5 fix-now)` | — |
| C3.N (per fix, ×0-5) | `fix(round-3): C-<n> — <slug> (lens <K|L|M>)` *or* `docs(round-3): C-<n> — <slug> (lens L docstring-only)` | `compat-c-<n>-<slug>` |
| C4.1 (changelog) | `docs(changelog): round-3 bug sweep (<FULL|SKELETON>) — N fixes, M deferred, K discarded` | — |
| C4.4 (workflow archive) | `chore(workflows): archive round-3 bug-sweep executed workflow` | — |
| C4.5 (milestone close) | (no commit — pure tag) | `milestone-c-round-3-bug-sweep` |

Every commit body ends with:
```
Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Total commit count: 2 (lens + triage) + 0..5 (fixes) + 2 (changelog + workflow) = **4..9 commits**.

No `--amend`, no `--no-verify`, no force-push. All on `bma-d/integration-all`.

## Rollback plan

Round-3 is uniquely revert-friendly: each shipped fix is its own commit + tag, and the audit report itself is purely additive markdown.

- **Per-fix rollback** (any C3.N commit): `git revert <C-N sha>`. The audit report still records the finding; the §Fix appendix entry should be amended in a follow-up commit to note `REVERTED <sha> on <date>` rather than deleted.
- **Triage rollback** (C2 commit): pure markdown; revert affects only the §Triage table. The lens-execution data (C1) is preserved.
- **Lens-execution rollback** (C1 commit): pure markdown; reverting wipes the audit report. Only do this if a deeper bug in the lens methodology surfaces — in which case the round-3 milestone aborts entirely and re-launches as round-3-v2 against a revised spec.
- **Changelog rollback** (C4.1 commit): pure markdown; revert leaves the fix commits in place and the milestone tag intact (or absent, depending on ordering).
- **Workflow-archive rollback** (C4.4 commit): pure markdown under `.claude/workflows/`; no runtime impact.

If the full suite goes red after any C3.N commit, revert *that* commit immediately, restore green, then either (a) re-author the test to better isolate the bug and re-attempt, or (b) demote the finding to `defer-to-followup`.

If `tests/test_audit_regression.py` goes red after any commit, that's a structural invariant violation — revert immediately and investigate before re-attempting. The audit-floor must stay at 24.

If `tests/test_frozen_gate_surface.py` goes red, a public symbol was accidentally moved — revert immediately. Frozen-surface is non-negotiable.

## Risk monitoring after merge

1. **Audit report completeness**: at one-week, sanity-check that the deferred findings are being picked up by follow-up specs. If `defer-to-followup` items languish > 30 days, that's a signal the triage was too aggressive.
2. **Fix-stability**: at one-week, check no shipped C3.N fix has needed a follow-up patch (the round-2 pattern was 4-of-11 follow-ups; round-3's cap should drive that ratio toward 0-of-5).
3. **Lens utility**: at one-week, retrospective on which lens produced the most fix-worthy findings. If one lens produced zero `fix-now` findings while the others produced 2+, the under-producing lens may need methodology revision for round-4.
4. **Audit-floor invariant count**: monitor `tests/test_audit_regression.py` — must stay at 24 unless a future milestone legitimately widens the invariant set.

## Execution-time budget

| Phase | Wall-clock estimate |
|---|---|
| C1 (lens execution × 3) | 60-90 minutes (the heavy phase — careful reading) |
| C2 (triage) | 15-30 minutes |
| C3 (per-fix, ×0-5) | 20-45 minutes per fix → 0-225 minutes total |
| C4 (close) | 20-30 minutes |
| **Total** | **2-6 hours** depending on fix count |

If C1 finds *zero* candidate findings across all three lenses (extremely unlikely), the milestone closes after C1 alone with a `[SKELETON]` changelog and the audit report archived as a methodology negative-result (still valuable).

## Definition of done

- [ ] `docs/audit/round-3-bug-sweep.md` exists, ≥ 15 findings enumerated, every finding dispositioned, fix appendix matches shipped fixes 1:1.
- [ ] `docs/changelog/2026-06-22-round-3-bug-sweep.md` exists with a closed-vocabulary tag (`[FULL]` or `[SKELETON]`).
- [ ] `.claude/workflows/round-3-bug-sweep.md` exists with per-fix sha references and retrospective paragraph.
- [ ] 0-5 `compat-c-N-<slug>` tags exist on the branch.
- [ ] `milestone-c-round-3-bug-sweep` tag exists on the final commit.
- [ ] Full unittest suite green (4070..4085 passing, 2 skipped, 0 failing).
- [ ] `ruff check skills/` clean.
- [ ] Audit-floor invariants: 24, unchanged.
- [ ] Frozen-gate-surface: zero diff.
- [ ] `core/telemetry_events.py`: zero diff.
- [ ] `npm run verify`: green end-to-end.
