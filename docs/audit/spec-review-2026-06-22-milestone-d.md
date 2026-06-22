# Adversarial Spec Review — Milestone D (G7 Sprint-Phase Dual-Store Unification)

> Reviewer: claude-opus-4-7 (autonomous adversarial gap pass)
> Date: 2026-06-22 · Branch: `bma-d/integration-all` · HEAD: 5424b7e (specs A/B/C/D committed)
> Files under review:
> - `docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md`
> - `docs/superpowers/plans/2026-06-22-g7-sprint-phase-unification-plan.md`
> Validation against actual source: `core/integration/sprint_phase_map.py`, `core/sprint.py`, `core/sprint_schema.py`, `core/artifact_paths.py`, `core/utils.py`, `core/evidence_io.py`, `docs/spec/frozen-gate-surface.md`.

## TL;DR

The spec presents a tidy "thin unified-state wrapper on top of M48" story but the contract is undercooked at the trust boundary where it actually matters — disk. Three problems dominate: (1) the **sprint-status row writer does not exist** today (the spec assumes "the orchestrator's existing writer", but `git grep` shows zero writers of `sprint-status.yaml` anywhere — only readers; the plan in 3.1 punts to "mirror `_PHASE_LINE`-style targeted edit" without specifying a regex, atomicity contract, or what happens when the row is absent vs. present-but-mid-document). (2) **LWW by mtime is unsafe under the project's actual file layout**: `phase_store_path` lives in `<implementation_artifacts_dir>/phase-store.yaml` but `sprint_status_path` may fall back to a *legacy* path under `_bmad-output/` when the artifacts dir is unset — two different parent directories, possibly different filesystems on WSL bind-mounts, and a tie-break that the spec only weakly defines (phase-store wins). (3) **Reader-writer race is asymmetric without locks on the read path**: the spec asserts "atomic renames in deterministic order under lock" but `read_unified_state` re-reads both files lock-free *with two separate parses* — a writer can complete the phase-store rename between the reader's two reads, yielding a transient observed inconsistency that immediately triggers a *write* repair on the reader's path, racing future writers on the same key. Also: `unified_state_lock` is implicitly a new frozen-gate-surface symbol but the spec never says so; `read_unified_state` is documented as "read" but writes under the lock on legacy/conflict paths (no `_observe` variant), violating the principle of least surprise for read-only callers (audit/CLI/observability). Recommend: **needs-enhancement** before implementation — tighten the writer contract, define mtime tie-break + filesystem-granularity tests, document the symbol as frozen surface, document the read-may-write surprise in the public docstring, and add explicit negative tests for legacy-path / docs-bmad split.

## Findings table (HIGH first)

| ID  | Section          | Severity | Issue                                                                                                                                   | Suggested patch (one sentence)                                                                                                                                |
| --- | ---------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D01 | Spec §3, Plan 3.1 | HIGH     | The spec/plan repeatedly invoke "the orchestrator's existing sprint-status writer" but no such writer exists in the source today.       | Either (a) ship the writer as part of G7 with an explicit regex + atomic-rename contract, or (b) explicitly mark this as the *first* sprint-status writer.    |
| D02 | Spec §4, Plan 3.1 | HIGH     | Plan calls `core.sprint_schema.validate_sprint_status(...)` after a row-mutation but that validator expects a `yaml.safe_load` dict — and the codebase has zero YAML parsers (stdlib + filelock + psutil only). | Drop the `validate_sprint_status` step (the schema validator can't be called without adding a YAML dep) and replace with a regex-based round-trip equality check against the input. |
| D03 | Spec §2, §6.1    | HIGH     | LWW via mtime: spec asserts "same volume" but `sprint_status_path` may return either `<artifacts>/sprint-status.yaml` *or* a legacy path under `_bmad-output/`; phase store always lives in `<artifacts>`. These can be on different filesystems on WSL bind mounts. | Require both files resolve to the same parent dir before mtime LWW applies; if they don't, raise `UnifiedStateError` rather than silently comparing across volumes. |
| D04 | Spec §2          | HIGH     | `read_unified_state` is lock-free, but it does two independent reads (`sprint_status_get` then `read_phase_store`). A writer's rename between those reads creates a phantom inconsistency the reader then *writes through*, racing the original writer. | Either take the read lock briefly to snapshot both files, or implement a "read snapshot via stat-twice-or-retry" pattern and document the consistency model. |
| D05 | Spec §2, §3      | HIGH     | The spec says "phase store first, sprint-status second" is the write order so a reader sees the phase advance first → conflict → LWW repair. But if `sprint_status_get` returns the *post-rename* sprint while `read_phase_store` returns the *pre-rename* phase (interleaved), the reader observes the *opposite* order and resolves LWW backwards. | Define write order, read order, AND the LWW tie-break for the in-flight case explicitly; tests must exercise both interleavings. |
| D06 | Spec §5, plan §6 | HIGH     | `unified_state_lock(root)` is a public helper "for advanced callers" — that makes it a frozen-gate-surface symbol the moment G7 lands, but `frozen-gate-surface.md` is not in the plan's edit list. | Add `docs/spec/frozen-gate-surface.md` to the plan's edit set with a new `### core/integration/unified_state.py` section listing all four symbols + their behavioral invariants. |
| D07 | Spec §2          | HIGH     | "Auto-write on read" is a surprising side effect (R6 acknowledges this but defers a fix). With no `_observe` variant in G7, audit tooling that calls `read_unified_state` on a legacy project will mutate disk — this can corrupt forensic snapshots. | Ship `_observe=False` kwarg in G7 (not a follow-up): when True, never write on read, return raw pair plus a `needs_repair` flag (third tuple element behind a flag, or a dataclass-returning sibling). |
| D08 | Spec §2, Plan 3.2 | HIGH     | "Tie-break: phase store wins on mtime tie" is described in R5 as deterministic, but R5 also notes WSL/Windows mtime is 1-2s granular — meaning ties are *common*, not exotic; the test only covers an artificial nanosecond tie. | Add explicit test where two writes occur within one mtime tick on a 1s-granular filesystem (use `os.utime` to force the tie) and assert phase-store wins; document the policy in the module docstring under "Conflict resolution".  |
| D09 | Spec §6.2 #4     | HIGH     | "Missing story row raises `UnifiedStateError`" — but `sprint_status_get` returns `found=False` with `status="not_found"` *or* `status="unknown"` depending on whether the file exists at all. The spec collapses these into one error case with no message distinction. | Differentiate: file-missing → one error subclass/message; row-missing-in-existing-file → a second; test both. |
| D10 | Spec §6.1, §6.2  | HIGH     | The spec claims `compute_dual_state` invariant preservation but doesn't test the "phase store row keyed by descriptive slug (`1-1-host-feasibility-probe`)" case that M48's `compute_dual_state` handles via the `sprint.story` fallback. G7's writer keys only by the literal `story_key` — round-trip via `compute_dual_state` will *miss* the row. | Add a test where the phase-store has a slug-style key and `write_unified_state` is called with the canonical key; assert both keys are reconciled (or document the behavior + raise). |
| D11 | Plan 4.4         | MED      | The proposed audit-floor invariant ("no module other than `unified_state.py` writes to both stores within the same operation") is an AST-grep over "imports both `write_phase` AND mutates `sprint_status_path`" — but no module currently writes to sprint-status at all, so the invariant is vacuously true and provides zero coverage. | Re-phrase the invariant as "any module that imports `write_phase` from `sprint_phase_map` and `sprint_status_file` from `story_keys` MUST also import `unified_state_lock` OR equal `core/integration/unified_state.py` itself" and add a positive failure test. |
| D12 | Spec §5, Plan §0 | MED      | LOC budget: spec says "~250 LOC" for `unified_state.py`. With (a) the module docstring ≥30 lines, (b) writer for sprint-status (which spec assumes exists but doesn't), (c) repair branches, (d) LWW resolver, (e) error class with docstring, (f) `__all__` — the realistic LOC is closer to 350-450. The 500-LOC ceiling is tight given the missing-writer scope creep. | Re-estimate after spec patch for D01; if writer lands in G7, plan should pre-authorize splitting `_unified_state_repair.py` rather than treating it as a contingency. |
| D13 | Spec §3          | MED      | The ASCII diagram in §3 shows the writer doing "atomic-write sprint-status YAML second" but the actual sprint-status file may have hundreds of rows. A full-document rewrite for a single row update is O(n) and competes with future operator manual edits (comments, ordering). | Specify the *minimum* mutation contract (preserve all non-target lines byte-exact; preserve trailing newline) and add a test that writes one row and asserts file bytes outside the target row are byte-identical. |
| D14 | Spec §2          | MED      | "Holder identity is not recorded" — but the L1/L2 gate-marker work specifically added PID liveness checks because stale lockfiles after SIGKILL on Windows/WSL can survive arbitrarily long. G7 uses the same idiom with no PID liveness. | Either reuse the L1 lock-with-PID-liveness helper, or document explicitly that G7 lockfiles can become stale on operator-killed processes and add a CLI `state unlock --force` follow-up. |
| D15 | Spec §6.2 #10    | MED      | Concurrent-writers test uses **threads**, not processes. `filelock.FileLock` is process-level on POSIX (fcntl) but thread-mutex behavior differs by version — threads in the same process may share the lock by default. | Either add a multiprocess variant of the concurrency test using `multiprocessing`, or document explicitly that thread-level concurrency is the only supported isolation level and pin a `filelock` version that enforces it. |
| D16 | Spec §6.2 #5/#6  | MED      | LWW-on-conflict tests assume the test can `os.utime(path, (atime, mtime_ns))` to force ordering — but the spec text uses `st_mtime_ns`. `os.utime` granularity is OS-dependent (Windows FAT: 2s; ext4: 1ns; APFS: 1ns). | Add a "skip on FAT / 2s-granular FS" pytest skip predicate or use a synthetic clock injected via a `mtime_provider` callable.  |
| D17 | Spec §6.1        | MED      | "Reader observes sprint-status post-rename is guaranteed to also see the matching phase store" — this is only true if the OS's rename appears atomic across `os.stat` calls. `os.replace` on POSIX is atomic; on Windows it's atomic via `MoveFileEx` only for same-volume renames. The spec doesn't qualify this. | Explicitly require both temp files to be created in the destination directory (write_atomic already does this), and add a Windows-specific test that asserts atomicity. |
| D18 | Plan §6.3        | MED      | Plan filter to detect "no banned deps" greps for module names but the whitelist hard-codes `time, threading, ...` — implementer could legitimately need `errno`, `stat`, `shutil`, `signal`. The whitelist is too narrow and will produce false failures. | Re-derive the whitelist from CLAUDE.md's actual hard guardrail (stdlib + filelock + psutil) using `python -c "import sys; print(sys.stdlib_module_names)"` rather than a hand-typed list. |
| D19 | Spec §7 R1        | MED      | "Operator manual edits to phase-store get LWW-overwritten" — the mitigation is "documented in changelog + manual conflict resolution in runbook (out of scope)". This is the dominant operability bug from the L1/L2 work; deferring it is a regression risk. | Either ship the "operator override marker" (e.g., a `# operator-edit: <ts>` comment line that LWW treats as locked) or escalate to needs-redesign. |
| D20 | Spec §6.2        | MED      | The 12-test minimum has no test for **`unified_state_lock(root)` as context manager** (the public helper). Without a round-trip test, the helper's release semantics are unverified. | Add test #13: `with unified_state_lock(root): write_unified_state(...)` succeeds, sibling `write_unified_state` blocks until exit. |
| D21 | Spec §6.2        | MED      | No test for **legacy `_bmad-output/sprint-status.yaml` path** — spec mentions the fallback but no test exercises a project whose `implementation_artifacts_dir` is the legacy location with mismatched phase-store. | Add legacy-path fixture test that confirms `sprint_status_path` legacy fallback + `phase_store_path` artifacts dir produces a valid LWW result. |
| D22 | Spec §2          | LOW      | The decision matrix entry "Touch sprint-status YAML schema? No" is technically correct but the writer must add/modify a row format ("key: status [optional-tail]"); the *layout* is preserved but the *semantic* of an unknown trailing field per row is unspecified. | Document: writer preserves any trailing whitespace + comment after the status word verbatim; add a test with `key: in-progress # owner=alice` and assert post-write the comment is preserved. |
| D23 | Spec §10         | LOW      | "Out of scope: CLI subcommand `story-automator state get/set`" — but operators currently have NO way to inspect unified state without writing a Python one-liner. The Phase-D milestone slug `compat-g7-unified-state` implies parity; not shipping a CLI breaks "thin layer, no behavior change for callers" because there's no caller. | Either ship a minimal `gate status --unified` flag in G7, or document that no CLI exists and operators must use `python -c "from ...unified_state import read_unified_state; ..."`. |
| D24 | Plan §7.2        | LOW      | The conventional-commit subject "feat(integration): G7 — sprint-phase dual-store unification" is 63 chars (within 72-char gitlint default). But the subject *line* uses an em-dash; some CI commit-lint tools normalize em-dashes to hyphens, which would mismatch the trailer in `Generated-By`. | Use a simple hyphen in the subject or pin the lint rule explicitly in the spec. |
| D25 | Spec §11         | LOW      | "Validation provenance" cites the L1/L2 filelock work but doesn't cite the D-04 audit-key scrub or the AST invariant — both relevant because `unified_state.py` may need to invoke subprocesses (e.g., for cross-platform mtime fudge in tests) and those must scrub `BMAD_AUDIT_KEY`. | Add: "If `unified_state.py` ever calls `subprocess.run` (it shouldn't, but…), it MUST use `scrub_env_for_subprocess` per D-04." |
| D26 | Plan 3.5          | LOW      | "Replace the `NotImplementedError("phase 3")` stub" — the stub is in `write_unified_state`, but the prior phase (2.5) already mentions it. Two locations to track; if one is missed, tests still pass because the writer's happy path doesn't exercise the stub. | Use a sentinel `_TODO_WRITE_SPRINT_STATUS = object()` that is checked at module import time and fail-loud if still set; or just centralize the stub in one place. |
| D27 | Plan §4.7        | LOW      | "If smoke script absent, skip with a note" — the smoke script is part of `npm run verify`; if it's absent on the branch the entire verify gate is degraded silently. | Replace with: "If `scripts/smoke-test.sh` is absent, fail the plan and ask for guidance — do not silently skip." |
| D28 | Spec §9          | LOW      | Performance NFR: "read in no-repair path < 5 ms on warm fixture" — but the metric is unmeasured today and `sprint_status_get` already does a regex walk over potentially many rows. No baseline. | Add a perf-baseline test (`tests/test_unified_state_perf.py` with `@unittest.skip` by default) measuring a fixture of 50 rows; or drop the quantitative NFR. |
| D29 | Spec §6.3        | LOW      | "audit-floor invariants count ≥ 24 (no regression — baseline has 24)" then plan 4.4 raises to 25. The "no regression" wording conflicts with the active raise. | Reword: "must be ≥ 25 after this patch lands; baseline is 24; G7 adds the new unified-state invariant in §4.4". |
| D30 | Plan §0.2         | LOW      | Plan instructs to "open `tests/test_sprint_phase_map.py` and identify the `tempfile.TemporaryDirectory` + `implementation_artifacts_dir(tmp).mkdir(parents=True)` idiom" — but if that test file uses a different idiom (e.g., `pytest.tmp_path` fixture in another suite), the plan instruction misleads. | Verify the idiom exists in `test_sprint_phase_map.py` as a pre-flight check; if not, name the canonical helper module to use. |
| D31 | Spec §3          | LOW      | The diagram says reader's "filelock-free fast path" calls `read_phase_store(...).get()` — but `read_phase_store` returns a `dict[str, Phase]` not a sentinel-bearing object; `dict.get(key)` returns `None`, which the diagram conflates with "phase missing". | Clarify the diagram with `phase = read_phase_store(root).get(story_key)`. |
| D32 | Spec §2          | LOW      | "Lock-holder observability lives in B2, not G7" — but B2 isn't named in the spec's cross-reference list, and the dependency on B2's surface is implicit. | Cite B2 by spec path (`docs/superpowers/specs/2026-06-22-B-operability.md` if that's its name) or remove the forward reference. |

Total findings: **32** — HIGH=10, MED=12, LOW=10.

## HIGH-severity findings (detail)

### D01 — Sprint-status writer does not exist yet

**File:section**: Spec §3 (architecture diagram), §5 (file table), Plan 3.1.

**Problem**: The architecture diagram shows `write_unified_state` doing "atomic-write sprint-status YAML second" and Plan task 3.1 says "mutate only the matching row via regex (mirror `_PHASE_LINE`-style targeted edit), validate via `core.sprint_schema.validate_sprint_status`, write via `write_atomic`." But `grep -rn "sprint_status_path\|sprint-status\.yaml" skills/.../src/story_automator/` finds **zero writers** in the codebase. The only "writer" referenced in spec §2 ("the orchestrator's separate YAML writer") does not exist. G7 must ship the first-ever sprint-status writer — that is non-trivial scope creep the spec hides.

**Suggested patch**: Either (a) explicitly call out that G7 ships the first sprint-status writer (and budget its contract: row-targeted regex mutation, preserve all non-target lines byte-exact, preserve final newline, must not modify document if the row is absent — raise instead, no YAML re-serialization), or (b) confirm the writer already exists by citing the call site (it doesn't; verify with `git grep`).

### D02 — `validate_sprint_status` call is impossible without a YAML dep

**File:section**: Spec §4 (validator step), Plan 3.1.

**Problem**: Plan task 3.1 calls `core.sprint_schema.validate_sprint_status(...)`. But the validator's docstring says "validates the in-memory representation of a `sprint-status.yaml` document (typically the dict returned by `yaml.safe_load`)" — meaning it expects a **parsed dict**. The codebase has zero `import yaml` (verified by `grep -rn "import yaml" skills/.../src/`); CLAUDE.md hard guardrail forbids adding deps. The validator therefore cannot be called from `unified_state.py` without violating a hard guardrail.

**Suggested patch**: Remove the `validate_sprint_status` step from the writer. Replace with a regex round-trip equality assertion: after the row mutation, re-parse the new text via `sprint_status_get(project_root, story_key)` and assert `state.status == new_status`. This stays text-only and respects the stdlib-only guardrail.

### D03 — LWW via mtime crosses filesystem boundaries

**File:section**: Spec §2 (decision matrix), §6.1 (acceptance).

**Problem**: `sprint_status_path(root)` returns:
- Preferred: `<artifacts>/sprint-status.yaml` where `<artifacts>` comes from BMAD config
- Legacy fallback: `<root>/_bmad-output/sprint-status.yaml`

But `phase_store_path(root)` is **always** `<artifacts>/phase-store.yaml`. On a project where BMAD config moves `implementation_artifacts` to `docs/bmad/implementation-artifacts/` but sprint-status.yaml is still in the legacy `_bmad-output/`, the two files live in *different parent directories*. On WSL with `\\wsl$\` bind-mounts these can be on **different filesystems** with different mtime granularity (NTFS: 100ns; ext4: 1ns). LWW comparison across filesystems is undefined behavior and may flap arbitrarily.

**Suggested patch**: Before comparing mtimes, assert both files resolve to the same `Path.stat().st_dev` (POSIX device id). If not, raise `UnifiedStateError("cross-filesystem unified state not supported; phase store and sprint-status must share a volume")`. Add a regression test.

### D04 — Reader race: two reads, one writer between them

**File:section**: Spec §2 (decision matrix: "readers do not take the lock").

**Problem**: `read_unified_state` does:
1. `status = sprint_status_get(root, key)` (parses sprint-status.yaml)
2. `phase = read_phase_store(root)[key]` (parses phase-store.yaml)

A writer that completes between steps 1 and 2 has renamed the phase store to a newer version — the reader sees `(old_status, new_phase)`. That observation is **transiently inconsistent**, and the reader's current code treats inconsistency as "must repair via write". The reader will then **write back the wrong projection**, corrupting the just-written-correctly state.

**Suggested patch**: Either (a) acquire the lock on the read path when the first two reads disagree (re-read under lock; only repair if the locked read still disagrees), or (b) implement a "stat-then-read-then-stat-again" pattern: if the second stat shows a newer mtime, restart the read. Document the consistency model explicitly.

### D05 — Write order vs read order interleaving

**File:section**: Spec §2 (last bullet of decision matrix), §3 (architecture).

**Problem**: Spec says writer does "phase store first, sprint-status second" and asserts "a reader observing sprint-status post-rename is guaranteed to also see the matching phase store." But this is only true if the *reader* reads in the *reverse* order (sprint-status first, then phase). If the reader reads phase first (which is what §6.1 does for the "missing phase entry" branch — `read_phase_store` is invoked first to decide which branch to take), and the writer is mid-flight (phase rewritten, sprint-status not yet), the reader sees `(stale_status, new_phase)` and **incorrectly resolves LWW with phase winning** when in fact the writer is about to commit the matching sprint-status.

**Suggested patch**: Pin read order = reverse of write order in the public contract. Add an explicit comment in `read_unified_state`: "Read sprint-status first to pair with the prior phase write; the writer commits phase-first, so reading phase-first sees stale-against-future pairs." Add a test that simulates the interleaving.

### D06 — `unified_state_lock` is a frozen-gate-surface symbol but not declared

**File:section**: Spec §2 (decision matrix), §5 (file table), Plan §5/§6.

**Problem**: The spec defines `unified_state_lock(root) -> FileLock` as "exposed for advanced callers that need to bracket multi-row updates." That makes it a **public** symbol consumed by external code from day one. Per `docs/spec/frozen-gate-surface.md`, every such symbol must be added to that doc. The plan's edit list (Plan §5 / Plan §6) does not mention `docs/spec/frozen-gate-surface.md`.

**Suggested patch**: Add Plan task 5.x: "Append a new `### core/integration/unified_state.py` section to `docs/spec/frozen-gate-surface.md` listing `read_unified_state`, `write_unified_state`, `unified_state_lock`, `UnifiedStateError` with signatures + behavioral invariants (LWW direction, lock granularity, read-may-write side effect)."

### D07 — Read auto-writes silently corrupt forensic snapshots

**File:section**: Spec §2 (migration policy), §7 R6 (deferred mitigation).

**Problem**: Audit / observability tooling that snapshots a project's state (e.g., `tar -czf snapshot.tgz _bmad/`) calls `read_unified_state` to dump the current state. On a legacy single-store project, that read **writes** `phase-store.yaml`, mutating the snapshot the operator is trying to capture. R6 acknowledges this and defers fix to "follow-up `read_unified_state_observe`." But the follow-up is unscheduled and the snapshot corruption is non-recoverable (the original phase-store-empty state is lost).

**Suggested patch**: Ship `read_unified_state(root, key, *, observe_only=False)` in G7. When `observe_only=True`, never write, return `(status, phase_or_none, repair_pending: bool)`. Document the default `observe_only=False` clearly in the docstring with a warning emoji-free note: "Calling this function may write to disk; pass observe_only=True for read-only callers."

### D08 — Mtime tie on coarse-granular filesystems is normal, not rare

**File:section**: Spec §2, §7 R5.

**Problem**: R5 says "phase store wins on tie" with a test that touches both files to the same nanosecond. But on FAT32 / exFAT (USB-mounted volumes), HFS+ pre-APFS, NFS3, and many ZFS configurations, mtime granularity is 1-2s. Two writes within 1s — totally plausible for back-to-back orchestrator operations — will **always tie**, making LWW degenerate to "always phase-store wins" regardless of which write was actually later.

**Suggested patch**: Add a secondary tie-breaker: if mtimes tie, compare file contents (canonical sort) for "which value is in `TERMINAL_PHASES`" — terminal phases override non-terminal on ties because a terminal write is more recent semantically. Document policy in §2 decision matrix.

### D09 — Two different "missing story" cases collapsed into one error

**File:section**: Spec §6.2 test #4.

**Problem**: `sprint_status_get` returns:
- `found=False, status="unknown", reason="sprint-status.yaml not found"` when the file is missing
- `found=False, status="not_found"` when the file exists but the row is absent

These are operationally different (one is a setup problem, the other is a data problem). Spec collapses both into "raises `UnifiedStateError` mentioning the story key" — the operator gets the same message for both. Debugging the difference requires reading the source.

**Suggested patch**: Either two error subclasses (`UnifiedStateFileMissingError`, `UnifiedStateRowMissingError`) or a structured error with a `reason: str` attribute exposing `sprint.reason`. Add separate tests for each case.

### D10 — Phase store can be keyed by slug, writer keys by canonical id

**File:section**: Spec §6.1 (M48 call-site invariants), Plan 3.1.

**Problem**: M48's `compute_dual_state` handles this case explicitly:

```python
stored_phase = phase_store.get(key) or phase_store.get(sprint.story)
```

— meaning the phase store may have entries keyed by descriptive slug (`1-1-host-feasibility-probe`) rather than canonical id (`1.1`). G7's `write_unified_state(root, story_key, ...)` will write under the *literal* `story_key`. A future `compute_dual_state` call with the canonical id will read the slug entry from the same store; G7's writer leaves the old slug entry orphaned + the new id entry written → **two entries for one story**, both valid but inconsistent.

**Suggested patch**: Before writing the phase entry, call `sprint_status_get(root, story_key)` to resolve to the canonical `sprint.story` key, and write under that key. Delete any orphan slug-keyed entry as part of the same write under lock. Add a regression test.

## MED-severity findings (table only — backlog or enhancement candidates)

See findings table above (rows D11–D21).

## LOW-severity findings (table only — backlog)

See findings table above (rows D22–D32).

## Recommended enhancements to spec/plan (BEFORE implementation)

1. **Resolve D01 (writer scope)** — spec/plan must either own the new sprint-status writer or cite the (currently-missing) existing one. Without this resolution the implementation will either silently corrupt sprint-status.yaml or balloon past the 500-LOC budget. **Must-fix.**

2. **Resolve D02 (validator dep)** — remove the `validate_sprint_status` invocation; replace with regex round-trip. **Must-fix.**

3. **Resolve D03 (cross-filesystem LWW)** — add `st_dev` equality precondition before mtime comparison; document in §2.

4. **Resolve D04+D05 (reader/writer race)** — explicitly pin read order ↔ write order coupling, document the consistency model. Optionally take the lock briefly on conflict-suspicious reads.

5. **Resolve D06 (frozen-gate-surface)** — extend `docs/spec/frozen-gate-surface.md` as part of G7; do not defer.

6. **Resolve D07 (read-may-write)** — ship `observe_only=False` kwarg in G7. The follow-up "deferred" is too risky.

7. **Resolve D08 (mtime tie on coarse FS)** — secondary tie-breaker (terminal phases > non-terminal).

8. **Resolve D09 (missing-row error differentiation)** — two error subclasses or structured `reason`.

9. **Resolve D10 (slug vs canonical key)** — resolve to `sprint.story` before write; reconcile orphans.

10. **Plan enhancement** — re-do LOC budget after D01 expands scope; pre-authorize `_unified_state_repair.py` split.

11. **Plan enhancement** — Plan §6.3 banned-dep grep: derive whitelist from `sys.stdlib_module_names`, not hand-typed.

12. **Test additions** — multiprocess concurrency test (D15); legacy-path fixture test (D21); `unified_state_lock` context-manager round-trip (D20).

## Verdict

**needs-enhancement** → **enhancements applied (2026-06-22)**

The spec is structurally sound and the milestone scope is appropriate. But three HIGH findings (D01, D02, D07) materially alter the work — the writer doesn't exist, the validator can't be called as-spec'd, and the read-may-write side effect needs to be addressed before landing rather than deferred. The remaining seven HIGH findings (D03–D06, D08–D10) are operability + correctness concerns that the spec already half-acknowledges but doesn't close.

Recommended action: patch the spec to address D01, D02, D06, D07 explicitly (these are policy decisions, ~20 minutes of spec work); document D03, D04, D05, D08, D09, D10 with explicit test cases (these are mostly test additions to §6.2, ~30 minutes). MED/LOW findings may roll into the implementation PR as inline fixes without further spec revision.

After enhancement, the plan should re-baseline LOC budget (D12) and re-confirm the audit-floor invariant has real teeth (D11). Once those land, the milestone is **ready-to-implement**.

## Resolved (enhancements applied 2026-06-22)

All 10 HIGH-severity findings have been patched into `docs/superpowers/specs/2026-06-22-g7-sprint-phase-unification-design.md` and `docs/superpowers/plans/2026-06-22-g7-sprint-phase-unification-plan.md`:

- ~~**D01**~~ — G7 explicitly ships the first-ever sprint-status writer (`_write_sprint_status_row`) with a row-targeted text-only regex mutation contract; spec §1, §4, §5, and plan step 3.1 fully re-baselined.
- ~~**D02**~~ — `validate_sprint_status` call removed (requires `yaml.safe_load`; codebase has zero YAML deps per CLAUDE.md guardrail). Replaced with a regex round-trip equality assertion via `sprint_status_get`.
- ~~**D03**~~ — Same-volume `st_dev` precondition added to spec §2 decision matrix and plan step 3.2; cross-filesystem raises `UnifiedStateError`.
- ~~**D04**~~ — Stat-twice-or-retry pattern (capped at 3 attempts, then locked snapshot) added to spec §2 + plan step 3.7.
- ~~**D05**~~ — Read order pinned as REVERSE of write order in spec §2 decision matrix + inline code comment in `read_unified_state`. Writer = phase-first → sprint-second; reader = sprint-first → phase-second.
- ~~**D06**~~ — `docs/spec/frozen-gate-surface.md` added to spec §5 file table + plan step 4.4b; new `### core/integration/unified_state.py` section declares all four public symbols + two error subclasses + behavioral invariants.
- ~~**D07**~~ — `observe_only=True` kwarg ships in G7 (NOT deferred). Test #16 covers the no-disk-writes path. Spec §7 R6 updated. Plan step 3.6 implements the branch.
- ~~**D08**~~ — Mtime tie secondary tie-break: terminal phase wins on tie; phase store wins if neither or both are terminal. Spec §2 + R5; test #15 forces synthetic tie.
- ~~**D09**~~ — Two error subclasses: `UnifiedStateFileMissingError` and `UnifiedStateRowMissingError`. Test #4 split into #4a/#4b. Plan step 3.8 differentiates raise sites.
- ~~**D10**~~ — Writer resolves to canonical `sprint.story` key via `sprint_status_get` before writing; deletes orphan slug-keyed entries under the same lock. Test #17 verifies. Plan step 3.5 documents the reconciliation.

MED + LOW gaps (D11..D32) are tracked in the new "Tracked enhancements" section appended to the spec; D11 (audit-floor positive-failure test), D12 (LOC re-baseline + pre-authorized split), D17 (atomic-rename — implicit via `write_atomic`), D20 (lock context-manager test), D21 (legacy-path test), D27 (smoke-script fail-loud), D29 (audit-floor wording reconciliation) are resolved inline as part of the HIGH patches; the rest are inline plan polish (D13 byte-exact preservation, D15 multiprocess concurrency test, D16 mtime_provider, D18 banned-dep grep via sys.stdlib_module_names, D22 trailing comment preservation, D24 hyphen-not-em-dash, D25 D-04 scrub note, D26 sentinel stub, D30 fixture idiom pre-check, D31 dict.get clarification, D32 B2 spec citation) or backlog (D14 PID liveness deferral, D19 operator override marker, D23 CLI subcommand, D28 perf NFR).
