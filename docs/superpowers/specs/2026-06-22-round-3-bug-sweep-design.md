# Round-3 Bug Sweep — Design Spec

> Date: 2026-06-22 · Status: **Draft for execution** · Milestone: **C (Round-3 bug sweep)** · Owner branch: `bma-d/integration-all`.
> Topic: a third adversarial sweep of the production-gate codebase, using three *fresh* lenses that rounds 1 and 2 did not exercise — **Lens K (performance + scalability)**, **Lens L (documentation correctness — docstring vs actual behavior)**, **Lens M (failure-mode taxonomy — except-clause recovery audit)**.
> Validation provenance: round-1 audit (`docs/audit/`), round-2 audit (`docs/audit/round-2-bug-sweep.md`, 11 fixes shipped), and the D-04 follow-up arc (`.claude/workflows/d04-followup-sibling-module.md`). This sweep is *deliberately* a meta-milestone: the spec defines **how** the sweep is executed and **what counts as a fix-worthy finding**; the concrete patches are produced during execution and recorded post-hoc in the changelog.

## 1. Goal

Catch the bugs that rounds 1 and 2 missed by *changing the lens*, not by re-running the same checks more carefully. The first two sweeps were dominated by **security**, **concurrency**, **determinism**, and **collector-correctness** lenses; both rounds explicitly *did not* audit performance cliffs, docstring/behavior drift, or except-clause recovery completeness. Round-3 closes those three blind spots with capped triage and capped fix-now scope.

Concretely:

1. **Surface up to 30 candidate findings** (≈10 per lens) on the production-gate codebase as it stands at the **milestone-C-start SHA** (recorded into §0 of the audit report on Phase 1 entry; gap C-H-03 — DO NOT pin a stale literal SHA, as `6a957d2` was two commits behind the actual branch HEAD at review time).
2. **Adversarially triage** each finding to (severity, confidence). Severity ∈ {LOW, MED, HIGH}; confidence ∈ {LOW, MED, HIGH}.
3. **Fix at most 5 findings** that are simultaneously HIGH severity *and* HIGH confidence. Everything else is logged for future sweeps. The cap is non-negotiable — round-2 over-shipped (11 fixes) and burned reviewer attention; round-3 stays surgical.
4. **Each fix lands as one commit + one tag** matching the established `compat-c-N-<slug>` pattern, with the round-3 milestone tag closing the series.
5. **No regression** of any of the 24 audit-floor invariants, the frozen-gate-surface contract, the 4070-test baseline, or `ruff check skills/` cleanliness.

The spec is the **rubric**; the plan is the **workflow**.

## 2. Decisions captured

| Decision | Choice |
|---|---|
| Why three lenses, not five? | Rounds 1+2 already covered 8 lenses (cf. `.claude/workflows/deep-bug-sweep-round-2.md`). The marginal value of lens #4 in a single sweep is lower than the value of *executing* three lenses thoroughly. A round-4 with M-T tier lenses is a separate spec. |
| Why cap fix-now at 5? | Empirical: round-2 shipped 11 fixes, of which 4 had to be amended or extended in follow-ups (D-04 followup, L1 followup). The defect-injection rate from large patch-clusters is too high. Cap forces ruthless triage. |
| Why HIGH × HIGH only? | Anything LOW-severity or LOW-confidence becomes a **finding log** entry, not a patch. Round-3's value is *catching* the bugs; fixing all 30 in one milestone re-creates the round-2 trap. |
| What about MED-severity findings? | Logged in `docs/audit/round-3-bug-sweep.md` with a "deferred" annotation and a recommended follow-up spec slug. They do **not** ship in this milestone. |
| New Python deps? | **No.** stdlib + `filelock` + `psutil` only (CLAUDE.md hard guardrail). All three lenses are *reading* code; fixes are local edits. |
| Telemetry changes? | **No.** `core/telemetry_events.py` is M01-owned (CLAUDE.md guardrail). If a fix appears to need a new event, that's a sign it should be deferred to a telemetry-owning milestone. |
| Frozen-gate-surface? | **No public symbol moves.** Fixes that would require a frozen-surface change are auto-deferred (logged but not shipped). |
| Output artifact format? | One audit report (`docs/audit/round-3-bug-sweep.md`) mirroring the round-2 structure: per-lens section, per-finding subsection with severity/confidence/disposition, plus a fix-summary appendix listing the ≤5 patches that shipped. |
| Commit granularity | One commit per shipped fix; one final docs commit for the audit report + changelog entry. |
| Tag namespace | `compat-c-N-<short-slug>` per fix; `milestone-c-round-3-bug-sweep` closes the series. |

## 3. Lens specifications

### 3.1 Lens K — performance + scalability

**Question per finding**: *does this code path do more work than it must, in a way that will sting at production scale (≥1000 stories or ≥10000 evidence records)?*

**Target modules** (read first, in this order):

| Module | Pre-sweep LOC | Performance hot-path concern |
|---|---|---|
| `core/evidence_io.py` | 442 | `persist_evidence_record` is called per-collector per-story; canonical JSON serialisation + hash-chain compute is on the critical path. |
| `core/calibration.py` | 259 | Iterates over historical traces; risk of repeated file stat / unbounded JSON parse. |
| `core/audit.py` | 482 | `AuditLog.append` holds the file lock + recomputes prev-hash from disk each call. |
| `core/budget_ceilings.py` | 523 | `evaluate_ceilings` reads the ledger; potential O(N) re-scan per emit. |
| `core/gate_orchestrator.py` | 718 | `run_production_gate` orchestrates collector fanout; risk of sequential where parallel would be safe. |

**Checklist** (run mentally per module):

- O(N²) loops over evidence records or audit entries — particularly nested `for` over `gate_file.evidence` × something else.
- List scans where a `dict[str, ...]` keyed lookup is available (e.g., looking up a collector by category-id with a linear search).
- Repeated `Path.stat()` / `Path.exists()` per element in a loop (filesystem syscall cost amplifies on Windows + NFS).
- Missing upper bounds on input size (e.g., a collector returns an unbounded JSON blob and the orchestrator stores all of it).
- `json.loads` on unbounded files without a size check (DoS vector even in single-user threat model when the operator imports a foreign archive).
- Re-serialisation of the same payload more than once in a hot path (canonical JSON cost is non-trivial).
- Lock held across a network or subprocess call (filelock + subprocess.run in the same `with` block).

**Output per finding**: severity (LOW = annoying at scale; MED = visible at 1k stories; HIGH = visible at 100 stories), confidence (do we have a measurement, a citation, or just a hunch?), expected fix shape (constant-factor, algorithmic, schema-change required).

**Anticipated finding count**: 5-10.

### 3.2 Lens L — documentation correctness

**Question per finding**: *does this docstring promise something the implementation does not deliver?*

**Target modules** (read 6-8 with substantial docstrings):

- `core/risk_profile.py`
- `core/readiness_gate.py`
- `core/profile_composer.py`
- `core/cli_dispatcher.py`
- `core/plugins.py`
- `core/gate_orchestrator.py`
- `core/gate_remediation.py`
- `core/product_profile.py`

**Checklist**:

- Docstring claims a return *type* the code does not return (e.g., "returns `dict[str, Any]`" but actually returns `None` on the error path).
- Docstring claims `Raises: X` but the body raises `Y` (or no exception at all, swallowing failures).
- Docstring lists parameters the signature does not have (drift after a refactor).
- Docstring uses controlled-vocabulary terms incorrectly: `[FULL]`, `[LITE]`, `[SKELETON]`, `[DEFERRED]` (M11 closed vocabulary); `PASS`/`CONCERNS`/`FAIL`/`WAIVED` (gate verdicts); `continue`/`remediate`/`park`/`halt` (Action enum closed set).
- Docstring section names diverge from the CLAUDE.md vocabulary (e.g., a docstring titles a section "Errors" where the rest of the codebase says "Raises").
- Docstring references a sibling helper by an old name post-rename.

**Output per finding**: severity (LOW = cosmetic/wrong word; MED = misleading next maintainer; HIGH = production-incident-shaped — operator reads docstring, acts on it, gets surprise behavior), confidence.

**Anticipated finding count**: 5-10.

### 3.3 Lens M — failure-mode taxonomy

**Question per finding**: *for each `except` clause in this critical path, is the recovery actually complete?*

**Target critical paths** (exactly 3):

1. `core/gate_orchestrator.run_production_gate` (and the helpers it calls — `_recover_from_crash_locked`, `route_gate_verdict`).
2. `core/gate_orchestrator.route_gate_verdict` end-to-end.
3. `core/audit.AuditLog.append` (the hash-chained append with file lock).

**Checklist** per except clause:

- Does the except clause leave the system in a **partial-commit** state (e.g., gate file written, marker not cleared; ledger row appended, hash chain not extended)?
- Does it leak a resource? Open file handle, held lock, dangling subprocess, dangling worktree, retained tmp dir.
- Is there a missing `fsync` / `flush` before the rollback path declares "rolled back"?
- Does the except clause swallow the original cause (`raise NewException from None` instead of `from exc`)? Acceptable only when the new exception type is genuinely the operator-facing one and the original is logged elsewhere.
- Is the catch-set correct? `except Exception:` is the usual smell; check whether `KeyboardInterrupt` + `SystemExit` ought to propagate.
- Is the recovery idempotent? A retry after a partial failure should not produce two ledger rows for the same logical event.
- Does the rollback rely on a fact (e.g., "the file does not exist") that an attacker (or a concurrent orchestrator) could falsify between the check and the act? TOCTOU residue.

**Output per finding**: severity (LOW = harmless leak in single-user setting; MED = visible at re-run; HIGH = unrecoverable state, data loss, or audit-chain corruption), confidence.

**Anticipated finding count**: 5-10.

## 4. Triage rubric

A finding is **fix-now** iff:

```
finding.severity == HIGH
AND finding.confidence == HIGH
AND finding.shipping_within_5_fix_budget == True
AND finding.fix_does_not_touch_telemetry_events_py == True
AND finding.fix_does_not_change_frozen_surface == True
AND finding.fix_loc_delta < 80    (per-fix soft cap; spec total < 400 LOC)
```

A finding is **deferred** iff any of the above is False. Deferred findings are still reported in `docs/audit/round-3-bug-sweep.md` with a recommended follow-up tag (`bug-c-deferred-<slug>`) and a one-line rationale.

A finding is **discarded** iff post-investigation reveals the suspected bug does not exist (the code is correct, the docstring is correct, the failure mode is impossible due to an upstream invariant). Discarded findings are still listed — with a one-line "verified-not-a-bug" rationale — to prevent re-discovery in round-4.

### 4.1 The 5-fix cap — how to choose

When more than 5 findings clear the rubric (e.g., 7 HIGH × HIGH candidates surface), rank by:

1. **Blast radius if shipped to production** (data loss > corruption > visible-incorrect > internal-only mis-reporting).
2. **Reversibility of the fix** (rollback-safe > requires-data-migration > requires-state-rewrite).
3. **Test-cost-to-author** (RED/GREEN < 20 LOC > 20-50 LOC > 50+ LOC; lower test cost wins ties).
4. **Cross-lens evidence** (a finding flagged by two lenses outranks a single-lens finding).

The remaining HIGH × HIGH findings move to deferred with a "round-4-priority" annotation.

## 5. Implementation surface

### 5.1 Files

| File | New / Modified | Purpose |
|---|---|---|
| `docs/audit/round-3-bug-sweep.md` | New | The per-lens findings report. Sections: §K, §L, §M, §Triage, §Fix appendix, §Deferred follow-ups. |
| `docs/changelog/2026-06-22-round-3-bug-sweep.md` | New | `[FULL]` changelog entry (CLAUDE.md vocabulary; M11). |
| `tests/test_<bugfix-c-N>.py` × ≤5 | New | One test file per shipped fix; named after the finding slug (`tests/test_bugfix_c_<n>_<slug>.py`). |
| `skills/bmad-story-automator/src/story_automator/core/<module>.py` × ≤5 | Modified | The actual fix; one module per fix wherever possible. |
| `.claude/workflows/round-3-bug-sweep.md` | New | Executed-workflow archive (matches the pattern of `.claude/workflows/deep-bug-sweep-round-2.md`). |

### 5.2 Hard constraints

- **Python deps**: stdlib + `filelock` + `psutil` only. No new package in `package.json` / `setup.py` / `pyproject.toml`.
- **LOC budget**: each fix ≤ 80 LOC; total fix budget ≤ 400 LOC across all 5 patches. The audit report itself is markdown and not LOC-counted.
- **Frozen-gate-surface**: no public symbol added, removed, renamed, or signature-changed. Verified by **`git diff <milestone-C-start-sha>..HEAD -- docs/spec/frozen-gate-surface.md | wc -l == 0`** AND an ad-hoc import-roster smoke (a short Python script that imports every symbol listed in `docs/spec/frozen-gate-surface.md` and asserts each is callable / a class / has the expected attribute). The `tests/test_frozen_gate_surface.py` referenced in earlier drafts **does not exist in the repo** (gap C-H-02); authoring it is OUT of round-3 scope (it would be a separate prerequisite milestone for B/C/D all). The ad-hoc smoke is recorded in §0 of the audit report as the canonical verification.
- **Telemetry**: `core/telemetry_events.py` untouched.
- **500-LOC soft limit**: any fix that pushes a module past 500 LOC for the *first* time triggers an automatic deferral (split obligation belongs to the next refactor milestone). `gate_orchestrator.py` (718 LOC) and `audit.py` (482 LOC) and `budget_ceilings.py` (523 LOC) are already over and are tracked in the audit-floor; fixes there must add ≤ 20 LOC and live in a tightly-quarantined block.

## 6. Acceptance criteria

### 6.0 Serialisation constraint (gap C-M-07 / C-H-03)

**C executes either strictly AFTER `milestone-b-operability-batch` (the B closing tag) exists on the branch, OR strictly BEFORE B's first commit lands.** B and C MUST NOT run concurrently. Reason: B's operability batch modifies `core/evidence_io.py` and `core/gate_orchestrator.py` — the same two modules at the centre of Lens K and Lens M. Concurrent execution would either (a) invalidate C's §3.1 LOC snapshots (stale per-module sizes), (b) cause C to "find" findings that B is in the middle of fixing (which the implementer would then mark as `DUPLICATE-OF-B`, wasting triage cycles), or (c) require C to re-read affected modules mid-sweep. The audit report's §0 records `milestone-b-operability-batch` tag presence (or its absence + a "B not yet started" note) so the ordering is auditable post-hoc.

### 6.0.1 Severity rubric — unified across lenses (gap C-M-04)

A single ordinal rubric inherited by all three lenses; per-lens narratives keep their flavour but the floor is shared:

| Severity | Operator-action language | Lens K specialisation | Lens L specialisation | Lens M specialisation |
|---|---|---|---|---|
| **HIGH** | "operator would file a P1 ticket today" | visible-incorrect at 100 stories OR data loss at 1000 stories | production-incident-shaped (operator reads docstring, acts, gets surprise) | data loss / audit-chain corruption / unrecoverable state |
| **MED** | "operator would file a P2 next week" | visible at 1000 stories OR detectable-but-rare at 100 | misleading next maintainer (drift, not surprise) | visible at re-run / resource leak |
| **LOW** | "cleanup queue" | annoying at scale (≥ 10000) only | cosmetic / wrong word | harmless leak in single-user setting |

If two reviewers disagree on a finding's severity, **resolve to the lower** unless the higher reading is unambiguously the operator-action one.

### 6.1 Behavioral

- A finished `docs/audit/round-3-bug-sweep.md` exists with §K, §L, §M sections and at least 15 total findings across the three lenses (≥5 per lens, on average — under-3 in any lens is a red flag that the lens was not exercised).
- Triage section explicitly lists every finding's (severity, confidence, disposition) tuple. No finding is silently dropped.
- The fix-now list contains **between 0 and 5 entries** (inclusive). Zero is a valid outcome if no finding clears HIGH × HIGH — the audit report alone is the deliverable.
- Each shipped fix has a corresponding RED-then-GREEN test in `tests/`.
- Each shipped fix is a single commit on `bma-d/integration-all`, conventional-commits-formatted, with `Generated-By:` and `Co-Authored-By:` trailers.
- The audit report explicitly enumerates deferred findings with a slug per finding (so a future sweep can reference them).
- The audit report records *discarded* findings with a one-line "not-a-bug because X" rationale.

### 6.2 Test coverage

- Minimum **0 new tests** (acceptable lower bound — zero fixes shipped).
- Maximum **15 new tests** (3 per fix × 5 fixes max). Test names follow `test_bugfix_c_<n>_<short>` convention.
- Total test count after milestone close: 4070 (baseline) + 0..15 (new), 2 skipped, 0 failing.
- Any new test that lands ships with at least one RED-then-GREEN demonstration recorded in the audit report's fix appendix (per-fix QA log).

### 6.3 Quality gates

- `python3 -m unittest discover -s tests` → all green (4070..4085 passing, 2 skipped).
- `ruff check skills/` → zero violations on touched files.
- `tests/test_audit_regression.py` → green; **24 invariants stay at 24** unless a shipped fix legitimately adds a new structural invariant, in which case the audit-floor entry is appended (never removed, never re-numbered).
- Ad-hoc frozen-surface import-roster smoke (gap C-H-02 — `tests/test_frozen_gate_surface.py` does NOT exist; authoring it is OUT of scope): a short Python script imports every symbol in `docs/spec/frozen-gate-surface.md` and asserts each resolves. Recorded in §0 of the audit report. Also: `git diff <milestone-C-start-sha>..HEAD -- docs/spec/frozen-gate-surface.md | wc -l == 0`.
- `core/telemetry_events.py` → zero diff (verified by `git diff HEAD -- skills/bmad-story-automator/src/story_automator/core/telemetry_events.py | wc -l == 0`).
- `npm run verify` → green end-to-end (test:python, pack:dry-run, test:cli, test:smoke).
- No commit uses `--amend`, `--no-verify`, or force-push.

## 7. Risks + mitigations

| Risk | Mitigation |
|---|---|
| The three lenses surface zero HIGH × HIGH findings → milestone "ships nothing." | This is a legitimate outcome. The audit report alone is the deliverable. The changelog entry tags as `[SKELETON]` (M11 vocabulary) in that case, not `[FULL]`. |
| Lens K's "performance" findings are inherently low-confidence without measurement → risk of shipping a hunch-driven "fix" that regresses. | Confidence floor is HIGH; a Lens K finding is HIGH-confidence only if it has either (a) an O(N²) → O(N) algorithmic argument that a peer could verify by reading the code, or (b) a microbenchmark snippet in the audit report. Otherwise it stays MED-confidence and is deferred. |
| Lens L docstring findings are easy to over-detect (every drift is "a finding"). | The severity floor is HIGH for shipping. LOW/MED severity docstring drift is logged but not patched in this milestone — round-3 is not a docs-only milestone. |
| Lens M except-clause findings might require touching `telemetry_events.py` (e.g., to emit a new failure event). | Auto-defer per §4. The deferred entry's annotation explicitly calls out "would require new telemetry event" so the next telemetry-owning milestone (M01-adjacent) can pick it up. |
| The 5-fix cap pressures the executor to skip the audit report writing in favor of more patches. | Plan §B.close.1 explicitly blocks the milestone close on `docs/audit/round-3-bug-sweep.md` existing and being non-trivial (≥15 findings enumerated). No audit report → no milestone tag. |
| A Lens M finding might surface a *real* audit-chain corruption bug — too dangerous to fix in one commit. | Such a finding is *not* shipped in round-3. It becomes a standalone follow-up spec (`bug-c-audit-chain-<slug>`) with its own design review. Round-3's 5-fix cap is a safety budget, not an ambition target. |
| Tests for performance fixes are slow → CI drag. | Cap per-test wall-time at 1.0s. Performance tests should use deterministic data and assert algorithmic invariants (e.g., "operation called N times, not N²"), not wall-clock benchmarks. |
| The audit report itself becomes a 1000-line essay → reviewer fatigue. | Soft cap on the audit report: 600 lines. Findings beyond that are summarized with a one-line entry and a deferred-tag. |

## 8. Verification strategy

1. **Lens K execution** — read all 5 target modules; emit per-finding entries into `docs/audit/round-3-bug-sweep.md §K`.
2. **Lens L execution** — read all 6-8 target modules; emit per-finding entries into `§L`.
3. **Lens M execution** — read the 3 critical paths; enumerate every except clause; emit per-finding entries into `§M`.
4. **Triage pass** — for each finding, classify (severity, confidence, disposition). Update the report with the disposition column.
5. **Rank fix-now candidates** by the §4.1 algorithm; trim to ≤5.
6. **Per shipped fix**:
   a. Author the RED test (`tests/test_bugfix_c_<n>_<slug>.py`) — confirm RED via `python3 -m unittest discover -s tests -k test_bugfix_c_<n>`.
   b. Apply the minimal patch.
   c. Confirm GREEN.
   d. Run full suite — confirm no regression.
   e. Run `ruff check skills/` — confirm clean.
   f. Commit + tag `compat-c-<n>-<slug>`.
7. **Milestone close**:
   a. Author `docs/changelog/2026-06-22-round-3-bug-sweep.md` (`[FULL]` or `[SKELETON]` per outcome).
   b. Run `npm run verify` — confirm green end-to-end.
   c. Tag `milestone-c-round-3-bug-sweep`.
   d. Archive the executed workflow at `.claude/workflows/round-3-bug-sweep.md`.

## 9. Out of scope

- Re-running rounds 1+2 lenses (security, concurrency, determinism, collector-correctness) — those are concluded; new defects discovered in those lenses become standalone follow-up specs, not round-3 findings.
- Refactoring `gate_orchestrator.py`, `audit.py`, or `budget_ceilings.py` to drop under the 500-LOC soft limit — split obligations belong to a future architectural milestone.
- Adding new telemetry events for any failure mode (would touch `core/telemetry_events.py` — M01 owns it).
- Adding new public symbols to the frozen-gate-surface — explicitly out of scope.
- Cross-platform smoke testing of the fixes on Windows / WSL beyond what `npm run verify` provides — the existing portability guardrail covers it.
- A "round-4" with M-T tier lenses — separate spec.

## 10. Compatibility statement

- **CLAUDE.md guardrails honored**: stdlib + `filelock` + `psutil` only; no new fifth changelog tag; `telemetry_events.py` untouched; no historical changelog edit; conventional commits + `Generated-By:` trailer.
- **Frozen-gate-surface honored**: zero public symbol diff.
- **Audit-floor invariants**: 24 stays at 24 (unless a fix legitimately adds an invariant — strictly additive).
- **Cross-platform**: no shell-only artifacts touched; existing portability guardrails apply unchanged.
- **Threat model**: single-user / single-operator-on-VPS (memory: `singleuser-threat-model.md`) — Lens K findings that only matter in a multi-tenant context are auto-MED-severity (not HIGH).

## 11. Quick LOC + scope estimate

| Artifact | Estimated size |
|---|---|
| `docs/audit/round-3-bug-sweep.md` | 350-600 lines markdown |
| `docs/changelog/2026-06-22-round-3-bug-sweep.md` | 40-80 lines markdown |
| `.claude/workflows/round-3-bug-sweep.md` | 80-150 lines markdown |
| Per-fix patch (×5 max) | ≤ 80 LOC Python each, ≤ 100 LOC tests each |
| Total Python LOC delta | ≤ 400 production + ≤ 500 test |
| Total commit count | ≤ 5 fix commits + 1 docs commit + 1 workflow-archive commit = ≤ 7 |

## 12. Validation provenance

- **Round-1 audit** (`docs/audit/*.md`) — established the original lens taxonomy (security, concurrency, determinism, collector-correctness).
- **Round-2 audit** (`docs/audit/round-2-bug-sweep.md`) — shipped 11 fixes; 4 needed follow-ups (D-04, L1, L2). The over-shipping pattern is the direct motivation for round-3's 5-fix cap.
- **D-04 follow-up arc** (`.claude/workflows/d04-followup-sibling-module.md`) — demonstrated that audit-floor invariants need to be widened *during* the bug-sweep, not after. Round-3 explicitly preserves the audit-floor at 24 (no widening this milestone — that's a separate operational batch).
- **CLAUDE.md** — the guardrail set this spec is bounded by. The 500-LOC soft limit, the closed dep list, the M01 ownership of telemetry events, and the frozen-gate-surface contract are inherited as hard constraints.
- **Single-user threat model** (memory: `singleuser-threat-model.md`) — informs the severity calibration: a "multi-tenant secret leak" is not HIGH-severity in this codebase; an "operator's gate file corrupted" is.

## 13. Anti-goals (explicit non-deliverables)

- Round-3 is **not** a refactor milestone. No file is reorganized purely for tidiness.
- Round-3 is **not** a docs-overhaul milestone. Lens L's HIGH-severity floor means most docstring drift is *logged* and *not corrected* this milestone.
- Round-3 is **not** a performance-tuning milestone. Lens K's HIGH-confidence floor means most perf "concerns" are *logged* and *not optimized* this milestone.
- Round-3 is **not** a milestone for "shipping a lot." Zero fixes is a valid outcome — the audit report alone is the deliverable.

The round-3 sweep's success criterion is *information quality*, not patch volume.

---

## Tracked enhancements (MED/LOW gaps not patched into the spec body)

> Source: `docs/audit/spec-review-2026-06-22-C-round-3-bug-sweep.md`. HIGH gaps C-H-01..C-H-03 are resolved inline above (and across the plan).

| ID | Severity | Disposition | Note |
|---|---|---|---|
| C-M-04 | MED | Resolved inline | Unified severity rubric added as §6.0.1 with HIGH/MED/LOW × per-lens table. |
| C-M-05 | MED | Inline plan polish | Add Phase 2.5 "adversarial-verifier" step in the plan: every `fix-now` candidate gets a 3-line devil's-advocate entry (cheapest counter-argument / simplest alternative fix / evidence the bug isn't a bug); survives only if ≥2 of 3 are refuted in writing. |
| C-M-06 | MED | Inline spec polish | Spec §6.1: "if `fix-now` is empty, §Triage enumerates the top-3 closest-misses with a per-candidate 'why MED, not HIGH' rationale paragraph". |
| C-M-07 | MED | Resolved inline | B↔C serialisation constraint in spec §6.0; plan pre-req #2 enforces it via `git tag --list 'milestone-b-operability-batch'` probe. |
| C-M-08 | MED | Inline plan polish | Plan §C2.5 commits a `docs/audit/round-3-fix-now-list.md` with the chosen ≤5 slugs *before* any fix lands; adding a 6th requires editing that commit. |
| C-M-09 | MED | Inline spec polish | Spec §3.3 adds M4 (`AuditLog.verify`), M5 (`recover_from_crash` orchestrator wrapper), M6 (`_quarantine_corrupted_marker`) as additional Lens-M target paths. |
| C-M-10 | MED | Inline spec polish | Spec §5.2: "Lens K + M fixes that touch `gate_orchestrator.py`, `audit.py`, `budget_ceilings.py` are capped at 20-LOC delta and must be lift-and-shift-style refactors; any larger fix becomes a deferred follow-up spec." |
| C-M-11 | MED | Inline plan polish | Plan §C3.N.1: every Lens-L docstring fix lands a 5-LOC pin-test asserting the new docstring text (frozen-string regression net). |
| C-M-12 | MED | Inline plan polish | Plan §C3.N.10: commit subject becomes `fix(<module>): C-N — <slug>` with `(lens K/L/M)` in body, matching round-2 convention. |
| C-L-13 | LOW | Backlog | Add `core/audit.py`, `core/evidence_io.py`, `core/calibration.py` as Lens-L second-tier targets if time permits. |
| C-L-14 | LOW | Inline polish | Bump wall-clock estimate from "2-6 hours" to "4-10 hours" in §11. |
| C-L-15 | LOW | Resolved inline | Plan §C4.2 uses `<milestone-C-start-sha>..HEAD` diff (not `HEAD~7`). |
| C-L-16 | LOW | Inline spec polish | Spec §3.1: HIGH-confidence Lens-K finding must include either (a) a 5-line code excerpt of the offending pattern, or (b) a 10-line `timeit.timeit` snippet — anything else is MED-confidence. |
| C-L-17 | LOW | Backlog | Allow 3-line rationale for "discarded" findings; add a "verifier" sub-field. |

### Resolved-from-gap-report (HIGH)

- **C-H-01** — Every `unittest discover` invocation in the plan now prefixes `PYTHONPATH=skills/bmad-story-automator/src`. Header note in §Pre-requisites makes the requirement explicit and unmissable.
- **C-H-02** — `tests/test_frozen_gate_surface.py` removed from all spec/plan references; replaced with an ad-hoc import-roster smoke (a short Python `from story_automator.core import ...` script) recorded in §0 of the audit report, plus a markdown-diff check on `docs/spec/frozen-gate-surface.md`.
- **C-H-03** — Stale HEAD pin `6a957d2` removed. "Milestone-C-start SHA" is recorded into §0 of the audit report at Phase 1 entry. Plan §C4.2 diffs against that SHA, not `HEAD~7` (also closes C-L-15).
