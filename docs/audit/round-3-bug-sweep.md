# Round-3 bug sweep — Lenses K / L / M

> Date: 2026-06-22 · Milestone: **C** · Branch: `bma-d/integration-all`
> Companion spec: `docs/superpowers/specs/2026-06-22-round-3-bug-sweep-design.md`
> Companion plan: `docs/superpowers/plans/2026-06-22-round-3-bug-sweep-plan.md`

## §0 — Pre-sweep state

- **HEAD at milestone-C-start**: `abea3f6` (`test(integration): A — end-to-end factory self-evaluation harness`).
- **`milestone-b-operability-batch` tag**: absent (B↔C serialisation respected: C runs strictly BEFORE B's first commit lands).
- **Baseline test count**: 4079 passing, 2 skipped, 0 failing (via `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests`).
- **Audit-floor invariants**: 24 (via `tests.test_audit_regression`).
- **Ruff**: `ruff check skills/` clean.
- **Frozen-gate-surface import-roster smoke**: green — all 14 symbols (`gate_orchestrator, evidence_io, audit, product_profile, collector_registry, trust_boundary, gate_schema, gate_audit, readiness_gate, risk_profile, profile_composer, cli_dispatcher, plugins, action_enum`) importable from `story_automator.core`.

### Pre-sweep LOC snapshot

| Module | LOC |
|---|---|
| `core/evidence_io.py` | 442 |
| `core/calibration.py` | 259 |
| `core/audit.py` | 482 |
| `core/budget_ceilings.py` | 523 |
| `core/gate_orchestrator.py` | 718 |
| `core/risk_profile.py` | 312 |
| `core/readiness_gate.py` | 240 |
| `core/profile_composer.py` | 369 |
| `core/cli_dispatcher.py` | 477 |
| `core/plugins.py` | 355 |
| `core/gate_remediation.py` | 137 |
| `core/product_profile.py` | 478 |

## §K — Performance + scalability

### K-1: `evaluate_ceilings` re-streams the ledger once per applicable ceiling

- **Module**: `core/budget_ceilings.py:333-380` (`evaluate_ceilings` -> `_compute_spent`)
- **Symptom**: For each applicable ceiling, `_compute_spent(events_path, ceiling.window, now_iso)` is called inside the loop. Each call re-opens the JSONL ledger, streams it line-by-line, and re-parses every event. With the four canonical windows (`per_run`, `24h`, `7d`, `30d`) all bound to the same gate, a single `evaluate_ceilings` call performs **four full ledger scans**. Order is O(N · K) where N=event count, K=applicable-ceiling count.
- **Code excerpt** (the offending pattern, 5 lines):
  ```python
  verdicts: list[tuple[CeilingDecision, str]] = []
  for ceiling in applicable:
      spent = _compute_spent(events_path, ceiling.window, now_iso)
      verdicts.append(_decide(ceiling, spent))
  ```
- **Severity**: **HIGH** — visible at 1000 stories OR 100-story ledger with K≥4. The factory is expected to evaluate budgets on every gate fire; a 4× ledger-scan multiplier on the hot path means a 50 ms scan becomes 200 ms per gate.
- **Confidence**: **HIGH** — algorithmic argument is reader-verifiable in the 5-line excerpt above; no microbenchmark needed.
- **Fix shape**: algorithmic — single ledger pass that aggregates per-window totals in one stream, then per-ceiling decide.
- **Disposition**: **fix-now (rank 2)**.

### K-2: `load_evidence_bundle` is called 2-3× per `run_production_gate`

- **Module**: `core/gate_orchestrator.py:425, 583`, `core/verdict_engine.py:257`
- **Symptom**: A successful `run_production_gate` triggers `load_evidence_bundle(project_root, gate_id)`:
  1. Once inside `evaluate_gate` (verdict computation).
  2. Once after lock release for the Merkle root export.
  3. Once more inside `_collect_error_evidence` when `fail_closed=True`.
  Each call does `sorted(evidence_dir.glob("*.json"))` + per-file `read_text` + `json.loads`. The bundle is immutable for the lifetime of the gate, so the second and third loads are pure waste.
- **Severity**: **MED** — N=evidence-record-count (~10-30 in practice) is small; the redundant parse cost is meaningful only at high evidence density. The hot-path concern is real but not P1-shaped.
- **Confidence**: **HIGH** — call sites enumerated above; no microbenchmark required.
- **Fix shape**: pass already-loaded bundle through. *BUT* the verdict_engine signature is on the frozen-gate-surface and changing it touches the public API. The cheaper fix (memoize on `(project_root, gate_id)` via lru_cache) has a TTL/invalidation problem since gates are re-evaluated post-recovery.
- **Disposition**: **defer-to-followup** (`bug-c-deferred-evidence-bundle-memo`). Slug: round-4-priority. The fix requires either a frozen-surface tweak or a careful memoization story; both are larger than the round-3 budget.

### K-3: `_compute_spent` parses every event even after `cost_usd` is missing

- **Module**: `core/budget_ceilings.py:263-317`
- **Symptom**: The inner loop calls `parse_event(line)` (full schema validation) on EVERY line — even events that have no `cost_usd` field at all (StoryStarted, etc.). The `cost_usd` filter happens *after* the parse. parse_event is the slow path; a cheap pre-filter on the raw line could skip the parse for irrelevant events.
- **Severity**: **LOW** — constant-factor speedup; algorithmic complexity unchanged.
- **Confidence**: **MED** — relies on the assumption that a string-substring check on the raw line is materially faster than json.loads + dataclass construction.
- **Fix shape**: constant-factor — `if '"cost_usd"' not in line: continue` before parse_event.
- **Disposition**: **discard** — `parse_event` is the canonical entry point and a textual prefilter would create a parser/decoder divergence (e.g., for compressed/escaped JSON). Verified-not-a-bug: the fix would be a micro-optimization at the cost of correctness invariants.

### K-4: `AuditLog.append` does a `path.stat()` on every append

- **Module**: `core/audit.py:303-405`
- **Symptom**: Every `append` calls `self.path.stat().st_size`. On Windows + NFS the stat syscall is ~1-5 ms. The cache check (`self._cached_size == current_size`) avoids the disk re-read but not the stat itself.
- **Severity**: **LOW** — single syscall per audit emit; audit emits are infrequent (~1-3 per gate).
- **Confidence**: **LOW** — without measurement we can't confirm the stat is hot. The cache pattern is a known acceptable trade-off (file-lock guarantees cross-process correctness via the size check).
- **Disposition**: **discard** — verified-not-a-bug: the stat is intentional defense-in-depth for cross-process append.

### K-5: `recover_from_crash` holds gate lock across `shutil.rmtree`

- **Module**: `core/gate_orchestrator.py:260-292`
- **Symptom**: `recover_from_crash` acquires the gate file lock and may call `shutil.rmtree(evidence_dir)` under it. For large evidence dirs (10000+ files) the rmtree blocks all concurrent `run_production_gate` calls.
- **Severity**: **LOW** — evidence dirs are bounded by collector count (~14 collectors → 14-50 files); a 10000-file dir is not a realistic scenario.
- **Confidence**: **HIGH** — code structure is clear.
- **Disposition**: **defer-to-followup** (`bug-c-deferred-rmtree-under-lock`). Round-4-priority.

## §L — Documentation correctness

### L-1: `profile_composer.py` module docstring contradicts `_DICT_KEYS` for `forbidden_until`

- **Module**: `core/profile_composer.py:28-33` (module docstring) vs `:78` (`_DICT_KEYS`)
- **Docstring claim**: "scalar top-level fields (version, id, forbidden_until-as-date-string-style scalars) — last layer wins"
- **Actual behavior**: `forbidden_until` is in `_DICT_KEYS` (line 78) and is **deep-merged**, not last-layer-wins. The composer treats `forbidden_until: {"ADR-001": ["STORY-1.*"]}` as a dict whose ADR-id keys union across layers.
- **Severity**: **MED** — operator reading the module docstring could believe a later-layer `forbidden_until={"ADR-002": [...]}` *replaces* the earlier layer's `forbidden_until={"ADR-001": [...]}`. The actual behaviour merges them. Not "production incident" shaped (no operator-visible failure on the gate side), but actively misleading.
- **Confidence**: **HIGH** — direct contradiction in the module docstring.
- **Fix shape**: docstring-only.
- **Disposition**: **defer-to-followup** (`bug-c-deferred-forbidden-until-doc`). Severity MED, fails the HIGH × HIGH ship floor. Logged for round-4 or a docs-only milestone.

### L-2: `gate_remediation.write_remediation_to_story` misdescribes section insertion

- **Module**: `core/gate_remediation.py:65-106`
- **Docstring claim**: "Creates a `## Tasks` section before the first non-editable section if one doesn't exist."
- **Actual behavior**: Regex at line 94 is `r"^##\s+"` — matches the first `##` section of *any* kind. The "non-editable" qualifier is fiction; if the story has `## Status` before `## Notes`, the inserted Tasks lands before `## Status`, not before the first *non-editable* section.
- **Severity**: **MED** — operator could mis-predict where Tasks lands. No silent data corruption.
- **Confidence**: **HIGH**.
- **Fix shape**: docstring-only.
- **Disposition**: **defer-to-followup** (`bug-c-deferred-remediation-doc`). MED severity; doesn't clear the HIGH × HIGH ship floor.

### L-3: `risk_profile.py` module docstring omits action bands

- **Module**: `core/risk_profile.py:1-6`
- **Docstring claim**: "Maps Probability×Impact scores (1–9) to priorities (P0–P3) which drive downstream coverage/level requirements via profile.matrix."
- **Actual behavior**: The module also exports `risk_score_to_action`, `action_blocks_release`, and `ACTION_BANDS` (`DOCUMENT/MONITOR/MITIGATE/BLOCK`) — a second classification system layered on top via M37. The module docstring mentions neither.
- **Severity**: **LOW** — function names are self-documenting; the action-band feature is discoverable from `__all__`-equivalent surface.
- **Confidence**: **HIGH**.
- **Disposition**: **defer-to-followup** (`bug-c-deferred-risk-doc`). LOW severity; not on the round-3 budget.

### L-4: `cli_dispatcher.detect_stop` Args docstring references `KNOWN_HOOK_DIALECTS` correctly

- **Module**: `core/cli_dispatcher.py:198-220`
- **Status**: verified-not-a-bug. `KNOWN_HOOK_DIALECTS` is exported from `core/cli_profile.py:27` as `tuple[str, ...] = ("claude", "codex", "gemini", "none")`. The docstring reference is accurate.
- **Disposition**: **discard**.

### L-5: `plugins.PluginRegistry.load_all` "idempotent" claim verified

- **Module**: `core/plugins.py:259-317`
- **Status**: verified-not-a-bug. The docstring claim that `load_all` is idempotent (re-scans the manifest dir and replaces the index) is accurate per lines 309-317.
- **Disposition**: **discard**.

## §M — Failure-mode taxonomy

### M-1: `_quarantine_corrupted_marker` lies about success when mkdir fails

- **Path**: M1 — `core/gate_orchestrator._quarantine_corrupted_marker`
- **Except clause**: `core/gate_orchestrator.py:153` `except OSError: pass` wraps `mkdir(parents=True, exist_ok=True)` AND the rename calls.
- **Failure injected**: Disk full / permissions error / race during `quarantine_root.mkdir`.
- **Observed end-state**: The mkdir raises, both renames are skipped (since they were in the same try-block), but the function still returns `{"recovered": False, "quarantined": True, "quarantine_dir": str(quarantine_root), "corruption_reason": ...}`. The dict claims `quarantined=True` and even returns a path string — but nothing was actually moved. The marker is still in its original location; the evidence dir is still in its original location.
- **Severity**: **HIGH** — audit-trail correctness. The audit-floor `MarkerCorruptionInvariant` test explicitly asserts `result["quarantined"]` AND that the evidence was moved. If mkdir fails, the assertion that *quarantined=True implies "evidence moved"* is broken. An operator reading the recovery result believes quarantine succeeded and may not investigate further.
- **Confidence**: **HIGH** — code structure is clear; no test currently exercises the mkdir-failure branch.
- **Fix shape**: track actual quarantine success; only return `quarantined=True` when at least the marker move succeeded; surface a `quarantine_failed` reason otherwise. ≤15 LOC.
- **Disposition**: **fix-now (rank 1)**.

### M-2: `_recover_from_crash_locked` silently swallows partial rmtree

- **Path**: M1 — `core/gate_orchestrator._recover_from_crash_locked`
- **Except clause**: `core/gate_orchestrator.py:247` `except OSError: pass` wraps `shutil.rmtree(evidence_dir)`.
- **Failure injected**: `shutil.rmtree` partially succeeds (deletes some files, then fails on a permission error or a held file handle on Windows).
- **Observed end-state**: Partial evidence dir survives. `clear_gate_marker` (line 250) then runs, so the marker is gone. Next gate run sees an "empty" recovery state but finds a half-deleted evidence dir under the same gate_id. No audit signal.
- **Severity**: **MED-HIGH** — at the upper end of MED; tips into HIGH when the operator's investigation depends on knowing whether old evidence was cleaned. The marker is cleared regardless, so the audit-floor doesn't catch it.
- **Confidence**: **HIGH** — code clearly shows the swallow.
- **Fix shape**: capture the rmtree exception text; if rmtree raised, return a `cleanup_failed=True, cleanup_error=str(exc)` field alongside the existing `recovered=True` so the operator is alerted. ≤10 LOC.
- **Disposition**: **fix-now (rank 3)**.

### M-3: `AuditLog.append` does not directory-fsync on first write

- **Path**: M3 — `core/audit.AuditLog.append`
- **Except clause**: n/a (the issue is a missing-fsync, not a swallow).
- **Failure injected**: Power loss between first-ever append-write and a subsequent block-cache flush.
- **Observed end-state**: On POSIX, the file content is durable (fsync ran) but the directory entry that created the file may not be — the first record could be lost. Subsequent records are durable.
- **Severity**: **LOW-MED** — only the FIRST audit emit per log is at risk; the audit log is created once per gate.
- **Confidence**: **MED** — durability semantics vary by filesystem (ext4 with delayed allocation vs xfs vs Windows NTFS).
- **Disposition**: **defer-to-followup** (`bug-c-deferred-audit-dirfsync`). Round-4-priority; would require platform-specific fix.

### M-4: `audit._read_last_record` JSONDecodeError propagates without partial state

- **Path**: M3 — `core/audit._read_last_record`
- **Status**: verified-not-a-bug. `_read_last_record` propagates `json.JSONDecodeError` per its docstring contract ("the append path treats that as a fatal corruption signal and propagates it"). The lock is released by `append`'s finally. No partial state.
- **Disposition**: **discard**.

### M-5: `run_production_gate` Merkle export outside the lock

- **Path**: M1 — `core/gate_orchestrator.run_production_gate`
- **Except clause**: n/a (no except clause; this is a lock-scope concern).
- **Failure injected**: A concurrent recovery races the Merkle root export at line 583.
- **Observed end-state**: After the `with get_gate_lock(...)` block exits, the marker is cleared; a concurrent recover sees no marker → `recovered=False, no action`. The bundle load at line 583 sees the freshly-written evidence dir. No race.
- **Severity**: LOW — but the architecture is correct.
- **Confidence**: HIGH.
- **Disposition**: **discard** — verified-not-a-bug.

### M-6: `route_gate_verdict` write_remediation_to_story OSError surfaced correctly

- **Path**: M2 — `core/gate_orchestrator.route_gate_verdict`
- **Status**: verified-not-a-bug. The `except (EditAuthorizationError, OSError)` at line 696 captures the exception, sets `persist_error` in the descriptor, and continues. `write_atomic` inside `write_remediation_to_story` guarantees no partial story-file write.
- **Disposition**: **discard**.

## §Triage

| ID | Lens | Severity | Confidence | Disposition | Fix-now rank |
|---|---|---|---|---|---|
| K-1 | K | HIGH | HIGH | fix-now | 2 |
| K-2 | K | MED | HIGH | defer-to-followup | — |
| K-3 | K | LOW | MED | discard | — |
| K-4 | K | LOW | LOW | discard | — |
| K-5 | K | LOW | HIGH | defer-to-followup | — |
| L-1 | L | MED | HIGH | defer-to-followup | — |
| L-2 | L | MED | HIGH | defer-to-followup | — |
| L-3 | L | LOW | HIGH | defer-to-followup | — |
| L-4 | L | — | — | discard (verified) | — |
| L-5 | L | — | — | discard (verified) | — |
| M-1 | M | HIGH | HIGH | fix-now | 1 |
| M-2 | M | MED-HIGH | HIGH | fix-now | 3 |
| M-3 | M | LOW-MED | MED | defer-to-followup | — |
| M-4 | M | — | — | discard (verified) | — |
| M-5 | M | — | — | discard (verified) | — |
| M-6 | M | — | — | discard (verified) | — |

**Total findings**: 16 (5 K + 5 L + 6 M). **Fix-now**: 3 (well under the 5-cap). **Deferred**: 7. **Discarded**: 6.

### Phase 2.5 — Adversarial verifier (per gap C-M-05)

For each fix-now candidate, three counter-arguments were evaluated; promotion requires ≥2 refuted in writing.

- **M-1**: 3/3 refuted. (a) "mkdir rarely fails" — refuted by disk-full/permissions/race scenarios. (b) "quarantined=True is innocuous since recovered=False" — refuted: audit-floor test asserts quarantined=True implies evidence-moved. (c) "Simpler fix: drop the try/except" — refuted: would crash recovery on transient mkdir failure.
- **K-1**: 2/3 refuted. (a) "Only 1-2 ceilings in practice" — refuted: profile default uses 4 windows. (b) "Ledger small, scan cheap" — refuted: module docstring explicitly says streaming. (c) "Higher-level caching simpler" — partially stands but not refuting; in-pass aggregation is local and lock-free.
- **M-2**: 2/3 refuted. (a) "rmtree rarely fails partially" — partially refuted by NFS/Windows flakiness. (b) "Operator can see no marker → trust cleanup" — that's the bug. (c) "Drop the except clause" — refuted: would crash recovery.

All three survive promotion.

## §Fix appendix

### Fix C-1: M-1 — `_quarantine_corrupted_marker` truthfully reports mkdir failure

- **Slug**: `c-1-quarantine-mkdir-honest`
- **Commit**: (recorded post-commit)
- **Test**: `tests/test_bugfix_c_1_quarantine_mkdir_honest.py`
- **RED → GREEN**: test injects `mkdir` OSError via `unittest.mock.patch`; asserts result has `quarantined=False` and a `quarantine_error` field rather than the misleading `quarantined=True`.
- **LOC delta**: ~15 LOC in `gate_orchestrator.py`, ~50 LOC in the new test file.
- **Lens**: M.

### Fix C-2: K-1 — `evaluate_ceilings` single-pass ledger aggregation

- **Slug**: `c-2-ceilings-single-pass`
- **Test**: `tests/test_bugfix_c_2_ceilings_single_pass.py`
- **RED → GREEN**: test counts file-open calls (via `unittest.mock.patch` on `Path.open`); asserts ledger opened exactly once for N≥2 applicable ceilings.
- **LOC delta**: ~30 LOC in `budget_ceilings.py`, ~60 LOC in the new test file.
- **Lens**: K.

### Fix C-3: M-2 — `_recover_from_crash_locked` surfaces partial-cleanup failure

- **Slug**: `c-3-recover-cleanup-honest`
- **Test**: `tests/test_bugfix_c_3_recover_cleanup_honest.py`
- **RED → GREEN**: test injects `shutil.rmtree` OSError; asserts result has `cleanup_failed=True` and a `cleanup_error` field rather than silent success.
- **LOC delta**: ~10 LOC in `gate_orchestrator.py`, ~50 LOC in the new test file.
- **Lens**: M.

## §Deferred

| Slug | Source | Severity | Rationale |
|---|---|---|---|
| `bug-c-deferred-evidence-bundle-memo` | K-2 | MED | Round-4-priority. Fix touches frozen-surface or requires memoization invalidation. |
| `bug-c-deferred-rmtree-under-lock` | K-5 | LOW | Round-4-priority. Realistic only at 10000+ file evidence dir. |
| `bug-c-deferred-forbidden-until-doc` | L-1 | MED | Doc fix, MED severity; HIGH × HIGH floor not cleared. |
| `bug-c-deferred-remediation-doc` | L-2 | MED | Doc fix, MED severity; HIGH × HIGH floor not cleared. |
| `bug-c-deferred-risk-doc` | L-3 | LOW | Doc fix, LOW severity. |
| `bug-c-deferred-audit-dirfsync` | M-3 | LOW-MED | Platform-specific; needs separate spec. |

## §Discarded

| ID | Source | Rationale |
|---|---|---|
| K-3 | `_compute_spent` prefilter | parse_event is canonical; textual pre-filter would introduce parser/decoder divergence. |
| K-4 | `AuditLog.append` stat | Defensive cross-process check; cost is acceptable. |
| L-4 | `detect_stop` docstring | `KNOWN_HOOK_DIALECTS` actually exists in `cli_profile.py:27`. |
| L-5 | `PluginRegistry.load_all` idempotent | Code matches docstring. |
| M-4 | `audit._read_last_record` propagate | Matches documented contract. |
| M-5 | Merkle export outside lock | No race; concurrent recovery sees marker cleared. |
| M-6 | `route_gate_verdict` persist_error | Surface-and-continue is documented behaviour. |
