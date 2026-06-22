# D-Rereview — Second Adversarial Pass on Enhanced G7 Spec/Plan

> Reviewer: claude-opus-4-7 (autonomous, default-to-dispute)
> Date: 2026-06-22 · Branch: `bma-d/integration-all` · HEAD before re-review: `bc79b2b` (B operability shipped)
> Files under re-review (post-enhancement state from acf5337):
> - `docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md`
> - `docs/superpowers/plans/2026-06-22-g7-sprint-phase-unification-plan.md`
> Validation provenance: re-read `core/integration/sprint_phase_map.py` (lines 1–476), `core/sprint.py` (all 140 lines), `core/artifact_paths.py` (all 156 lines), `core/story_keys.py` (lines 1–40), `core/utils.py:write_atomic`, `tests/test_audit_regression.py` (24 tests pinned across 7 invariant classes), B-operability shipped surface (`core/gate_lock_observability.py`).

## TL;DR

The first-pass enhancement at acf5337 closed the 10 original HIGHs *as policy decisions*, but a second adversarial pass surfaces **10 fresh HIGHs** that emerge precisely from the patches themselves. The dominant failure mode is **interaction risk between the new behaviors**: `observe_only`'s tuple-arity-branching collides with `_resolve_lww`'s lock semantics; the same-volume precondition fires before the migration path checks for file existence; the read-order ↔ write-order coupling claim is broken by the migration path (which writes phase-first, like the writer); the slug-key reconciliation via `sprint_status_get` misreads what `SprintStatus.story` actually returns. None of the original 10 HIGHs is *un*resolved, but the patches introduce 10 new HIGH-severity correctness/observability gaps that need a second round of spec edits before implementation.

Verdict: **needs-enhancement-now**. The fresh gaps are mechanical (most are wording or test-scope tightening) and should land as a second spec-enhancement commit before Phase 5 of the workflow proceeds. After the second enhancement, the milestone is **ready-to-implement**.

## Findings table (HIGH first)

| ID | Section | Severity | Issue | Suggested patch (one sentence) |
|---|---|---|---|---|
| D-R-01 | Spec §4, plan 3.6 | HIGH | `read_unified_state` tuple arity branches on `observe_only` flag: returns `tuple[str, str]` when False, `tuple[str, str, bool]` when True. Python static typing can't discriminate without `Literal[True/False]` overloads; callers that pass a *dynamic* `observe_only` value must defensively unpack with `len()` or risk `ValueError: not enough values to unpack`. | Either (a) split into two public functions (`read_unified_state` / `read_unified_state_observe`) with monomorphic return shapes, OR (b) always return a 3-tuple `(status, phase, needs_repair)` regardless of the flag (writer-on-repair just always sets `needs_repair=False` after writing). Pick (b) — simpler. |
| D-R-02 | Spec §2 (cross-fs precondition), plan 3.2 | HIGH | The `st_dev` same-volume check calls `.stat()` on `phase_store_path(root)` — but on the **legacy single-store migration path** that file does **not exist yet**, so `.stat()` raises `FileNotFoundError` *before* the LWW branch is reached. The spec/plan never reconciles this. | Spec §2 must say: the same-volume check runs ONLY when both files exist (i.e. inside `_resolve_lww`, never on the migration path); the migration path skips it because there is only one file. Plan 3.2 update accordingly. |
| D-R-03 | Spec §2 (read-order pinning), plan 3.3 | HIGH | The decision-matrix entry pins reader = sprint-status-first, phase-second; writer = phase-first, sprint-second. But the **migration path** (`read_unified_state` derives a phase + persists it on first read) does phase-store-first writes (via `write_phase`), then *re-returns the projected pair* — matching the writer's order, **not** the reverse. So the "read order = REVERSE of write order" invariant has two readers: the steady-state reader (sprint→phase) and the migration reader (which writes phase-first like the writer). This is not documented; an implementer will write the steady-state read-order claim into the docstring and silently violate it on the migration path. | Spec §2 must split the read-order claim into two sub-rules: (a) steady-state observation = sprint→phase reverse-of-write; (b) on migration write-back, the reader becomes a writer and follows the writer's phase-first → sprint-second order. Plan must reflect this in step 3.3's code comments. |
| D-R-04 | Spec §2 (stat-twice retry), plan 3.7 | HIGH | The retry pattern caps at 3 attempts, then "acquire `unified_state_lock(...)` briefly to take a serialised snapshot." But the spec does NOT specify the lock-timeout used by the reader on this escalation path. If the reader passes the default `lock_timeout=10.0` (writer default), readers will block for 10s under writer contention — and worse, a heavily contended writer queue means the *reader* now occupies a slot in that queue, blocking other writers. | Spec §4 must define a separate `read_lock_timeout` kwarg (or a hard-coded short timeout, e.g., 2.0s) for the escalation path AND specify that on read-lock-timeout, the reader returns the best-effort pair without further repair, possibly with `needs_repair=True` if the call shape supports it. |
| D-R-05 | Spec §2 (observe_only return shape) | HIGH | Spec §4 says `observe_only=True` returns `(sprint_status, phase_value, needs_repair: bool)` — but on the migration path (phase store empty), what is `phase_value`? §7 R6 hints at `phase_or_none` (suggesting Optional) but §4 typed it as `str`. If empty-string is used for "no phase known", callers can't distinguish from `phase=""`; if `"pending"` is used, callers can't distinguish from a real `pending` value. | Spec §4 must pin one of: (a) `phase_value=""` ⇔ "phase store empty for this row"; (b) `phase_value="pending"` AND set `needs_repair=True` to signal it's derived. Pick (b); document the contract. |
| D-R-06 | Spec §6.2 test #15, plan 3.2 (mtime-tie) | HIGH | Test #15 uses `os.utime(path, (ts, ts))` to force a tie, but on ext4 (Linux CI) `os.utime` honors nanosecond precision when `ns=` kwarg isn't passed — meaning two `os.utime(path, (1000, 1000))` calls on different files BOTH get `st_mtime_ns = 1_000_000_000_000`, which IS a tie on that fs. But test #15's wording "force two writes to the *same* whole-second mtime" is ambiguous: a careless implementer will pass `(ts, ts)` where `ts` is a `time.time()` fractional value, get nanosecond resolution, and the tie will NOT happen — the test will pass but for the wrong reason (LWW wins on actual mtime difference, not tie-break). | Spec §6.2 test #15 must specify: use `os.utime(path, ns=(ts_ns, ts_ns))` with integer nanoseconds AND assert via `Path(p).stat().st_mtime_ns == ts_ns` that the tie really exists before testing the tie-break logic. |
| D-R-07 | Spec §2, §6.2 test #17, plan 3.5 (slug-key reconciliation) | HIGH | The patch says "writer calls `sprint_status_get(root, story_key)` to resolve to the canonical `sprint.story` key." But `sprint_status_get` returns `SprintStatus(found=True, story=<matched-row-key>, ...)` where `<matched-row-key>` is the key from the YAML row that matched the lookup — when the YAML has only `1-1-host-feasibility-probe: in-progress` and the caller looks up `"1.1"`, `_best_status_match` returns the row keyed by the slug (see `sprint.py:96` — `return SprintStatus(True, key, status, status == "done")` where `key` is whichever row matched). So `state.story` is the *slug*, not `"1.1"` — writing under that key persists the slug, not the canonical id. **The reconciliation is the inverse of what the spec claims.** | Spec §2 + plan 3.5 must redefine "canonical key" as the **normalized story id** (via `story_keys.normalize_story_key(root, story_key).id`), NOT `SprintStatus.story`. Add an explicit test that constructs the YAML with a slug-row and verifies the phase store ends up keyed by the normalized id `"1.1"`, not the slug. |
| D-R-08 | Plan 4.4 (audit-floor invariant phrasing) | HIGH | The invariant reads "any module that imports `write_phase` from `sprint_phase_map` AND `sprint_status_file` from `story_keys` MUST also import `unified_state_lock` OR equal `unified_state.py`." But: (a) `validate_dual_store` in `sprint_phase_map.py` already imports `sprint_status_file` — it's an internal helper, not a writer. (b) `gate_orchestrator` and other modules may legitimately need to read sprint-status via `sprint_status_file` without writing the dual store. (c) The invariant doesn't catch the actual hazard: a *new* module writing both stores without using `unified_state_lock`. As phrased the invariant will either over-trigger (false positives on legitimate readers) or under-trigger (writer that doesn't touch `sprint_status_file` directly slides past). | Re-phrase: "any module that calls `write_phase(...)` AND mutates the sprint-status file (via `write_atomic`, `os.replace`, or `Path.write_text` on a path resolved by `sprint_status_file` / `sprint_status_path`) MUST also acquire `unified_state_lock(...)`." Implement as a syntactic AST check over function-call patterns, not import names. Pin positive-failure test that constructs a fixture module violating this exact pattern. |
| D-R-09 | Spec §2 (read repair concurrency), plan 3.2 / 3.4 | HIGH | Two concurrent readers each observing "phase=done / sprint=in-progress" both compute LWW resolution from their **already-captured** in-memory state. Reader A acquires the lock, projects sprint→done, releases. Reader B then acquires the lock — but B's `sprint_state` was read at T0 (pre-A's-projection); B re-projects the stale "in-progress" back over A's correct "done." Result: a repair race that **undoes** the repair. | Spec §2 must add: "Inside `_resolve_lww`, after acquiring the lock, RE-READ both files under the lock and re-evaluate LWW; only project if the locked re-read still shows a conflict." Plan 3.2 update: reader's `_resolve_lww` must do `re-stat under lock → re-read both → re-check conflict → only project if conflict persists`. Add a regression test simulating two readers + one writer interleaving. |
| D-R-10 | Spec §6.2 test #17 (fixture setup) | HIGH | Test #17 requires a phase store with a slug-keyed entry (`1-1-host-feasibility-probe: in-progress`). But the only way to *create* that fixture today is via M48's `write_phase(root, "1-1-host-feasibility-probe", ...)` directly. The test's setup must explicitly call M48's writer with a slug key, then call G7's writer with `"1.1"`, and assert the slug entry is deleted. The spec/plan never describes this fixture-setup procedure; an implementer may try `write_unified_state(root, slug, ...)` (which would resolve back to canonical, defeating the test) or use `_write_phase_store` (private). | Plan 3.5 / test #17 must explicitly call out: `from story_automator.core.integration.sprint_phase_map import write_phase; write_phase(root, "1-1-host-feasibility-probe", Phase.DEV_RUNNING)` to seed the slug-keyed phase row, then `write_unified_state(root, "1.1", "in-progress", Phase.DEV_RUNNING)`, then `assert read_phase_store(root) == {"1.1": Phase.DEV_RUNNING}` (note: dict equality — slug entry must be gone). |
| D-R-11 | Plan 4.7 (smoke-script fail-loud) | MED | The plan says "fail and ask for guidance" if `scripts/smoke-test.sh` is absent. But this milestone executes within a non-interactive subagent — there is no operator to ask. The instruction is unactionable as written. | Plan 4.7 must specify: if `scripts/smoke-test.sh` is absent, FAIL the milestone with a halt-status return; the parent orchestrator handles escalation. No "ask for guidance" — it must be a hard fail. |
| D-R-12 | Plan 4.4 (audit-floor class name) | LOW | The new invariant string is `"unified-state-write-isolation: only unified_state.py writes to both stores in the same call"`, but no test class name is pinned. Implementer may use `UnifiedStateWriteIsolationInvariant`, `UnifiedStateInvariant`, or just inline as a top-level function — divergent naming makes the audit-floor count brittle on review. | Plan 4.4 must pin the test class name: `class UnifiedStateWriteIsolationInvariant(unittest.TestCase): ...` matching the existing `AuditKeyEnvScrubInvariant` naming convention. |

Total fresh findings: **12** — HIGH=10, MED=1, LOW=1.

(Threshold of 10 HIGH is met → verdict is `needs-enhancement-now` per the workflow contract.)

## HIGH findings — detail

### D-R-01 — Tuple-arity branching on `observe_only` is a Python typing footgun

**File:section**: Spec §4 (schemas), Plan 3.6.

**Problem**: The current contract is:
```python
def read_unified_state(root, key, *, observe_only=False):
    if observe_only: return (status, phase, needs_repair)   # 3-tuple
    return (status, phase)                                  # 2-tuple
```

Python's type system cannot express "return type depends on argument value" without `@overload`. A caller doing:
```python
flag = config.get("observe_only", False)
status, phase = read_unified_state(root, key, observe_only=flag)
```
will silently lose `needs_repair` when `flag=True`, or crash with `ValueError: too many values to unpack` if Python returns the 3-tuple.

The spec's "Tuple-arity-by-flag is acceptable because Python callers explicitly opt-in" is wishful — most operators copy/paste code without reading docstrings.

**Suggested patch**: Always return a 3-tuple `(sprint_status, phase_value, needs_repair: bool)` regardless of flag. When `observe_only=False` and the function repaired in-line, return with `needs_repair=False` (the post-repair state is already coherent). When `observe_only=True`, the function never writes; `needs_repair=True` flags divergence.

This is **monomorphic**, satisfies the read-only-caller intent, and is one fewer footgun.

### D-R-02 — Same-volume precondition fires on a missing file

**File:section**: Spec §2 (decision matrix, cross-fs entry), Plan 3.2.

**Problem**: The patch:
```python
if phase_store_path(root).stat().st_dev != sprint_status_path(root).stat().st_dev:
    raise UnifiedStateError("cross-filesystem unified state not supported...")
```

But on the migration path, `phase_store_path(root)` is **empty / doesn't exist**. `Path.stat()` on a non-existent path raises `FileNotFoundError` — the `UnifiedStateError` is never reached.

The migration path is the primary use case for legacy projects; the precondition fails *before* the function can do its job.

**Suggested patch**: Spec §2 must restrict the precondition to `_resolve_lww` (which only runs when BOTH files exist by construction — conflict detection requires both rows present). The migration path (phase missing + sprint present) skips the check entirely because cross-fs only matters for mtime LWW comparison.

### D-R-03 — Read-order = REVERSE-of-write-order claim breaks on migration path

**File:section**: Spec §2 (decision matrix), Plan 3.3.

**Problem**: The patch pins:
- Writer: phase first → sprint-status second.
- Reader: sprint-status first → phase second (REVERSE).
- Claim: "a reader observing the new sprint-status also sees the new phase store (matching write was committed first)."

But the migration path inside `read_unified_state` does:
1. Read sprint-status (steady-state order, fine).
2. Read phase store (steady-state order, fine).
3. Detect phase missing → call `write_phase(...)` (writes phase first).
4. Does NOT write sprint-status (it's already correct, just adding the phase entry).

Step 3-4 is **writer behavior** with a different write order — phase-only, not phase-then-sprint. The "REVERSE-of-write-order" rule has hidden third case (phase-only migration write). An implementer reading the docstring will pin sprint→phase read order and miss that migration is a *writer*, not a reader.

**Suggested patch**: Spec §2 must split into three rules:
- **Steady-state read**: sprint-status first → phase second.
- **Steady-state write**: phase first → sprint-status second.
- **Migration write** (from inside read): phase only; no sprint-status mutation; ordering immaterial since only one file is touched.

Plan 3.3 must add inline code comments specifying which mode the current branch is in.

### D-R-04 — Stat-twice escalation lacks a read-lock-timeout

**File:section**: Spec §2 (stat-twice-or-retry), Plan 3.7.

**Problem**: After 3 retries the patch says "acquire `unified_state_lock(...)` briefly." But:
- The only documented timeout is `lock_timeout` on `write_unified_state` (default 10s).
- The reader is not a writer; if it uses 10s, two readers waiting on a writer queue add up to 20s wall-clock for *reads*, which the spec earlier promised would be < 5ms (NFR in §9).
- If the reader uses no timeout (infinite block), a stuck writer halts all reads.

**Suggested patch**: Spec §4 must define `read_lock_timeout` (default 2.0s — generous enough for normal contention, fast enough not to halt operator tooling). On read-lock-timeout, the reader returns its current best-effort pair WITHOUT performing repair; if the call is `observe_only=True`, also set `needs_repair=True`. Plan 3.7 update accordingly.

### D-R-05 — `observe_only` return phase-value when phase store is empty is undefined

**File:section**: Spec §4 (schemas), §7 R6.

**Problem**: §4 says `observe_only=True` returns `(str, str, bool)`. §7 R6 hints at "phase_or_none." But the spec never pins the **value** of the phase string when:
- Phase store is empty (legacy single-store).
- Sprint-status row exists with a known status.

Three possible interpretations:
(a) Return the *derived* phase (e.g., `"dev-running"`) and set `needs_repair=True` — semantically correct.
(b) Return `""` (empty string) and set `needs_repair=True` — preserves "I literally read nothing from the phase store."
(c) Return `None` — but the type is `str`, not `Optional[str]`.

Different operators pick differently; tests that don't assert exact tuple contents will silently let any of these slide.

**Suggested patch**: Pin interpretation (a). Spec §4: "On observe_only=True with phase store empty + sprint row present, return the derived phase (e.g., `phase_for_sprint_status(status).value`) and `needs_repair=True`. Caller treats this as 'authoritative pair, but on-disk phase store needs materialisation.' "

### D-R-06 — Test #15's mtime-tie isn't actually a tie on the test filesystem

**File:section**: Spec §6.2 test #15.

**Problem**: `os.utime(path, (atime, mtime))` accepts seconds-as-float; on ext4/APFS with nanosecond precision, **both writes are recorded with full sub-second precision**. The test asserts a tie but doesn't *force* it correctly; on ext4 CI, the test passes because the LWW wins on actual mtime difference, masking whether the tie-break logic works.

Worse, if the test runs on a CI runner with fast filesystem (NVMe ext4) and two close-but-not-equal mtimes, the test passes via the wrong code path (LWW comparison, not tie-break). The implementer thinks the tie-break is verified; it isn't.

**Suggested patch**: Use `os.utime(path, ns=(ts_ns, ts_ns))` with integer nanoseconds (Python 3.3+ supports `ns=` kwarg). Then assert before the test logic that `Path(p1).stat().st_mtime_ns == Path(p2).stat().st_mtime_ns` — if False, `self.fail("could not force mtime tie on this filesystem; tie-break test cannot run")`. This makes the test honest: either it really tests the tie-break, or it fails loudly to skip.

### D-R-07 — `SprintStatus.story` returns the matched-row key, not the canonical id

**File:section**: Spec §2 (slug reconciliation), Plan 3.5, Test #17.

**Problem**: Read `sprint.py:96`:
```python
_, _, key, status = max(candidates)
return SprintStatus(True, key, status, status == "done")
```
`key` here is the **YAML row key that matched** — when the row reads `1-1-host-feasibility-probe: in-progress` and the caller looks up `"1.1"`, the matched row's key is the SLUG, and `SprintStatus.story` IS the slug, not `"1.1"`.

So the patch's claim — "writer calls `sprint_status_get(root, story_key)` to resolve to the canonical `sprint.story` key" — is **the inverse of correct**. Writing under `sprint.story` writes under the slug. The reconciliation moves data in the wrong direction.

**Suggested patch**: Use `story_keys.normalize_story_key(root, story_key)`, which returns a `StoryKey(id, prefix, key)` dataclass where `id` is the canonical dotted form (`"1.1"`). Pin: writer uses `normalize_story_key(root, story_key).id` as the canonical key. Plan 3.5 update; test #17 fixture assertions update.

### D-R-08 — Audit-floor invariant catches wrong pattern

**File:section**: Plan 4.4.

**Problem**: The phrasing "any module that imports `write_phase` AND `sprint_status_file` MUST also import `unified_state_lock`" creates false positives. `sprint_status_file` is widely used as a *reader path resolver* by `core/sprint.py`, `core/story_keys.py`, `core/integration/sprint_phase_map.py:validate_dual_store`, etc. None of those write to both stores.

Worse, a future module could write to both stores by going through `core/utils.write_atomic` directly on a path computed by `sprint_status_path()` without importing the name `sprint_status_file` — slipping past the invariant.

**Suggested patch**: Re-phrase as a **semantic** AST check, not a string match:
- "Any module under `core/` that contains both: (a) a function call to `write_phase(...)` AND (b) a function call to `write_atomic(<expr involving sprint_status_path or sprint_status_file>, ...)` — MUST also contain `unified_state_lock(` somewhere in its source."
- Implement via `ast.NodeVisitor` matching call patterns, mirroring `AuditKeyEnvScrubInvariant::test_ast_no_unscrubbed_subprocess_in_core` (which already does AST analysis).

The positive-failure test stays useful: fixture module that calls both writers without the lock; invariant trips; remove fixture.

### D-R-09 — Read-repair race: two readers undo each other

**File:section**: Spec §2 (LWW), Plan 3.2 / 3.4.

**Problem**: Reader A and Reader B both call `read_unified_state(root, "1.1")` at T0. Both read `(sprint=in-progress, phase=done)` — conflict. Both enter `_resolve_lww`.

- A acquires the lock first, sees `(sprint=in-progress, phase=done)`, projects to `("done", Phase.DONE)`, writes sprint-status, releases.
- B then acquires the lock. **B's in-memory `sprint_state.status` is still `"in-progress"` from T0.** B re-runs LWW comparison... but spec §2 doesn't say B re-reads both files. B's stale in-memory state projects sprint=in-progress→phase, **overwriting A's correct repair**.

This is exactly the kind of race the writer lock is supposed to prevent. But because the reader caches its observation **before** the lock acquisition, the lock doesn't protect the operation.

**Suggested patch**: Spec §2 + Plan 3.2 must specify: `_resolve_lww` after lock acquisition **re-reads both files under the lock** and re-runs the conflict check; only project if conflict persists AND mtime ordering still favors the same winner. Stale-cached LWW must always lose to fresh-locked LWW.

Add a regression test (extends test #5/#6): two threads concurrently call `read_unified_state` on a conflicted fixture; assert final state is internally consistent (no two-store divergence) regardless of which read "won."

### D-R-10 — Test #17 fixture setup is unspecified; implementer may set it up wrong

**File:section**: Spec §6.2 test #17, Plan 3.5.

**Problem**: Test #17 requires the phase store contain `{1-1-host-feasibility-probe: in-progress}` *before* `write_unified_state(root, "1.1", ...)` is invoked. The only way to seed that is by calling M48's `write_phase(root, "1-1-host-feasibility-probe", Phase.DEV_RUNNING)` directly. The spec/plan never says this — an implementer trying `write_unified_state(root, "1-1-host-feasibility-probe", ...)` (which resolves back to canonical via D-R-07's fix) cannot set up the fixture.

**Suggested patch**: Plan 3.5 / test #17 must specify:
```python
from story_automator.core.integration.sprint_phase_map import write_phase, Phase, read_phase_store
write_phase(tmp_root, "1-1-host-feasibility-probe", Phase.DEV_RUNNING)  # seed slug
# sprint-status.yaml has row "1.1: in-progress"
write_unified_state(tmp_root, "1.1", "in-progress", Phase.DEV_RUNNING)
assert read_phase_store(tmp_root) == {"1.1": Phase.DEV_RUNNING}  # slug deleted, canonical present
```

## MED + LOW

### D-R-11 (MED) — "ask for guidance" is unactionable in a subagent

The smoke-script fail-loud instruction expects an interactive operator. Subagent execution has none. Replace with: hard-fail the milestone (return verdict=halt to parent) and write the absence reason to `docs/audit/g7-smoke-missing.md`.

### D-R-12 (LOW) — Pin test class name for the new invariant

Plan 4.4: pin `class UnifiedStateWriteIsolationInvariant(unittest.TestCase): ...` matching existing convention (e.g., `AuditKeyEnvScrubInvariant`, `PluginTrustBoundaryInvariant`). Prevents class-name drift on review.

## Recommended action

Apply 10 HIGH patches inline to spec/plan via a second enhancement commit:
- `D-R-01`: 3-tuple monomorphic return for `read_unified_state` (drop arity-by-flag).
- `D-R-02`: `st_dev` precondition runs only inside `_resolve_lww`; migration path skips it.
- `D-R-03`: Split read-order claim into three modes (steady-read, steady-write, migration-write); pin in code comments.
- `D-R-04`: Add `read_lock_timeout` (default 2.0s); on timeout, return best-effort without repair.
- `D-R-05`: `observe_only=True` + empty phase store → return derived phase + `needs_repair=True`.
- `D-R-06`: Test #15 uses `os.utime(p, ns=(ts_ns, ts_ns))`; assert tie via `st_mtime_ns` equality before testing tie-break.
- `D-R-07`: Use `normalize_story_key(root, key).id` for canonicalisation, NOT `SprintStatus.story`.
- `D-R-08`: Re-phrase audit-floor invariant as an AST call-pattern check, not import-name match.
- `D-R-09`: `_resolve_lww` re-reads both files under the lock; project only if conflict persists.
- `D-R-10`: Test #17 fixture explicitly seeds slug via M48's `write_phase`.

After enhancement, the milestone is **ready-to-implement** — these are mechanical contract tightenings, not redesigns.
