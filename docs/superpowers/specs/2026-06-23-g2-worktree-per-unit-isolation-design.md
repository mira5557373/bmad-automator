# G2 — Worktree-Per-Unit Isolation — Design Spec (rev 2)

> Date: 2026-06-23 (rev 2 dated 2026-06-24 after adversarial review) · Status: **Draft post-adversarial-review, ready for implementation** · Milestone: **G2 (worktree-per-unit isolation)** · Owner branch: `bma-d/integration-all`.
> Rev 2 folds in 7 HIGH + 8 MED + 5 LOW gap fixes from an 8-lens adversarial review of rev 1. The gap report fold-in lives at §14.
> Topic: drive each collector into its own git worktree (instead of sharing one sandbox across all collectors), with optional bounded-parallel execution. Closes the M49 + M58 isolation loop.
> Validation provenance: builds on existing M03 `trust_boundary.py`, M04 `collector_checkout.py`, M04 `collector_runner.py::run_gate_collectors` (single-worktree loop at lines 112-180), M10 `gate_orchestrator.run_production_gate`, **`system_gate.run_system_gate`** (verified at `system_gate.py:51` — runs collectors too), **`worktree_recovery.recover_orphan_worktrees`** (verified at `worktree_recovery.py:99` — a janitor ALREADY EXISTS for `/tmp/sa-collector-*` orphans), M07 `adjudicator.run_collector_with_timeout`, `audit.AuditLockTimeout` (a real exception class at `audit.py:38`).
> Frozen-surface contract: ADDITIVE only. New optional kwargs on `run_production_gate` + `run_system_gate` + `run_gate_collectors` + `_run_collectors` (orchestrator wrapper) + `create_collector_checkout`; defaults preserve byte-identical behavior. No signature change to `CollectorConfig`, `CollectorOutcome`, or any persisted artifact's *shape*.

## 1. Goal

Close the half-built isolation loop.

**What's in place today.** The isolation surface is fully built and tested:

- `core/collector_checkout.py:create_collector_checkout(project_root, commit_sha)` — `git worktree add --detach @SHA`.
- `core/collector_checkout.py:cleanup_collector_checkout(checkout_path, project_root)` — best-effort `git worktree remove --force` + `shutil.rmtree`.
- `core/collector_checkout.py:collector_checkout(project_root, commit_sha)` — context manager.
- `core/trust_boundary.py:assert_host_context`, `sandbox_env`, `validate_evidence_path_isolation`, `resolve_host_evidence_dir`.
- **`core/worktree_recovery.py:recover_orphan_worktrees(project_root, *, min_age_s=3600.0, now=None)`** — janitor that prunes `.git/worktrees/` AND deletes orphan `/tmp/sa-collector-*` scratch dirs whose mtime is older than `min_age_s`. THIS IS THE PRE-EXISTING JANITOR rev 1 incorrectly claimed did not exist.

**What's not wired.** `core/collector_runner.py::run_gate_collectors` wraps the **entire collector loop** inside ONE `with collector_checkout(...) as checkout` block at line 146, then iterates collectors. Consequences:

1. **No per-unit TOCTOU defense.**
2. **No parallelism.**
3. **Crash-spread.**

**G2 closes these by:**

(a) Adding a new isolation mode `per_unit` to `run_gate_collectors` (opt-in via kwarg, default unchanged).

(b) Adding bounded-parallel execution via `concurrent.futures.ThreadPoolExecutor` (stdlib).

(c) Adding optional kwargs `isolation_mode` + `max_workers` on `run_production_gate` AND `run_system_gate` AND the `_run_collectors` orchestrator wrapper. All defaults preserve byte-identical behavior.

(d) Extending `worktree_recovery.recover_orphan_worktrees` to also handle the new `.git/worktrees/` admin-stub leak class that per-unit can amplify on crash (rev 1 omitted this).

(e) Audit-floor invariant `WorktreePerUnitIsolationInvariant` that pins (i) NO process-global state mutation in `core/collector_isolation.py` (`os.chdir`, `os.environ` mutations, `signal.signal`, `get_gate_lock` acquisition), (ii) refactor-tolerant structural exemption for the dispatch shape, (iii) safety-critical default values.

The motivating constraint: **the existing 4,471-test baseline stays green**, every existing call site keeps byte-identical behavior, and the new mode is operator-driven.

## 2. Out of scope

- **No replacement of the `shared` mode.** `shared` (default) stays canonical.
- **No breaking change to `collector_checkout.py`'s public surface.** Single additive optional kwarg `create_collector_checkout(*, name_hint: str = "", add_timeout: int | None = None)` defaults to byte-identical behavior. (rev 2 corrects rev 1's "no mutation" misstatement.)
- **No subprocess `multiprocessing`.** Threads only.
- **No new evidence schema.**
- **No new audit-event type.**
- **No new dependencies.**
- **No mutation of `telemetry_events.py`.**
- **No mutation of the `commit_sha`-must-be-hex contract.**
- **No checkout sharing across gates.**
- **No mutation of `run_production_gate`'s lock semantics.**
- **No CLI surface changes.**
- **No RAM-based info-evidence emission.** RAM-aware clamping IS in scope (§3) but it surfaces only via a `_clamp_max_workers` return that the test asserts; no new evidence/audit emission.
- **No mutation of the M03 §7 fresh-checkout-per-gate invariant.**
- **No automatic janitor invocation on every gate.** The existing `worktree_recovery.recover_orphan_worktrees` stays operator-invoked; G2 extends its capability, not its invocation pattern.

## 3. Decisions captured

| Decision | Choice |
|---|---|
| Module placement | New sibling module `core/collector_isolation.py` (~320 LOC). Houses `IsolationMode` literal, `run_collectors_per_unit`, `_run_isolated`, `_create_unit_checkout`, `_cleanup_unit_checkout`, `_clamp_max_workers`, `_sanitize_name_hint`, `_validate_isolation_kwargs`, `_error_outcome`, `_crash_outcome`. |
| `IsolationMode` vocabulary | `Literal["shared", "per_unit"]`. Default `"shared"`. **No** `"auto"` value. |
| Where the new kwargs live | `run_gate_collectors(..., isolation_mode="shared", max_workers=4)`; same on `_run_collectors` orchestrator wrapper at `gate_orchestrator.py:581`; same on `run_production_gate`; same on `run_system_gate` at `system_gate.py:51`. Defaults preserve byte-identical behavior at all four sites. |
| **Early kwarg validation (HIGH #6 fix)** | The kwargs are validated at the TOP of `run_production_gate` AND `run_system_gate` AND `run_gate_collectors` — BEFORE any other work (before `assert_host_context`, before the gate lock acquisition). Helper `_validate_isolation_kwargs(isolation_mode, max_workers)` in `collector_isolation.py`: raises `TypeError` if `not isinstance(max_workers, int) or isinstance(max_workers, bool)`; raises `ValueError` if `isolation_mode not in {"shared", "per_unit"}`. Both modes are validated — no silent acceptance of `max_workers="four"` in `shared` mode. |
| Dispatch | `run_gate_collectors` branches on `isolation_mode`: `"shared"` → existing inline path (byte-identical); `"per_unit"` → delegate to `core.collector_isolation.run_collectors_per_unit(...)`. **Dispatch happens AFTER `assert_host_context` and `registry.applicable`** (so child sessions still get rejected with the right error and empty-collector lists still return `[]` in O(1)). |
| **Refactor-tolerant dispatch shape (HIGH #3 fix)** | The audit-floor invariant's structural exemption for `run_gate_collectors` recognizes the dispatch via a NORMALIZED pattern: any `If` whose `test.left` resolves to the kwarg name `"isolation_mode"` AND whose `test.comparators` contains an `ast.Constant("per_unit")` (whether via `==`, `in {…}`, `match` case, or guarded variable). This survives refactors like `if mode in {"per_unit", "per_unit_v2"}:` and `match mode: case "per_unit": ...`. |
| Parallel executor | `concurrent.futures.ThreadPoolExecutor(max_workers=clamped, thread_name_prefix="sa-collector")`. Workers loop via `as_completed(futures)` to collect outcomes incrementally (not `[_collect(f) for f in futures]` — that broke under BaseException per HIGH #7 fix). |
| **`_clamp_max_workers` (rev 2 — RAM-aware)** | `_clamp_max_workers(requested: int, project_root: str|Path|None=None) -> int`. Returns `max(1, min(requested, cpu_ceiling, ram_ceiling))` where `cpu_ceiling = min(16, max(1, (os.cpu_count() or 4) - 2))` and `ram_ceiling = max(1, int(psutil.virtual_memory().available // _ESTIMATED_PER_WORKER_BYTES))` with `_ESTIMATED_PER_WORKER_BYTES = 256 * 1024 * 1024` (256 MiB per worker — conservative for a typical project tree + collector subprocess RSS). When `psutil.virtual_memory()` raises (test fixtures patching it), the RAM ceiling defaults to `cpu_ceiling`. The clamp formula is the SINGLE source of truth — §2 line references and §3 row both quote it identically. |
| Per-unit worktree naming | `tempfile.mkdtemp(prefix="sa-collector-", suffix=f"-{sha[:8]}-{sanitize(name_hint)}")` with sanitize-FIRST-truncate-SECOND order. `_sanitize_name_hint(hint)`: (1) drop chars not in `[A-Za-z0-9._-]`; (2) take the LAST 32 chars of the sanitized string (preserves disambiguating tail for collector_ids sharing a long prefix). Empty hint → empty suffix segment, byte-identical to today. |
| **AC-I-02 path pattern (MED #8 fix)** | Tests use `fnmatch`/glob: `assert ckt.parent == Path(tempfile.gettempdir())` AND `assert ckt.name.startswith("sa-collector-")` AND `assert ckt.name.endswith(f"-{sha[:8]}-{sanitize(hint)}")`. Random-char position between prefix and suffix is platform-dependent and is NOT pinned. |
| **Worker thread name save+restore (MED #4 fix)** | `_run_isolated` saves `original = threading.current_thread().name`, sets `name = f"sa-isolated-{collector_id}"` as its FIRST statement (before try), uses `try/finally` to restore `original` on exit. ThreadPoolExecutor reuses worker threads across tasks; without restore, stack traces from task B incorrectly attribute to collector A. |
| **BaseException at worker boundary (HIGH #7 fix)** | `_run_isolated` catches `BaseException` (not just `Exception`) — reifies as `_crash_outcome` with `findings=[f"worker terminated: {type(exc).__name__}: {exc}"]`. This keeps the "one outcome per collector" invariant under `MemoryError`, `SystemExit`, future-cancellation. The original `BaseException` is also re-raised AFTER outcome collection (see "Outcome collection robustness" row) so the operator's signal is honored. |
| **Outcome collection robustness (HIGH #7 fix)** | `run_collectors_per_unit` iterates `as_completed(futures)` in a `for` loop, capturing each `future.result()` into `outcomes` inside a try/except that catches `BaseException`. If a worker raised BaseException, it stores the exception in `_pending_baseexc` AND records the error outcome for that collector. After the loop, sorts outcomes by `(category, collector_id)` and if `_pending_baseexc is not None`, re-raises. Guarantees: 1:1 between persisted-evidence-on-disk and returned-outcomes-list; operator signal propagates. |
| **KeyboardInterrupt semantics (HIGH #7 fix)** | The main thread receives SIGINT; workers do NOT. `run_collectors_per_unit` runs the pool inside `try: ... except KeyboardInterrupt: pool.shutdown(wait=False, cancel_futures=True); raise` — drains the queue (collectors not yet started leave NO worktree behind) but lets in-flight subprocess.runs complete to their existing per-category timeout. Documented worst-case grace period equals `max(profile.timeouts.values())` (= 600s for `performance` per the bundled profile). Operator can press Ctrl-C twice for OS-level signal delivery to children. |
| **Audit-lock contention (MED #6 fix)** | `_run_isolated` catches `AuditLockTimeout` SPECIFICALLY (imported from `core.audit`) and retries once with the original `emit_gate_audit` call (the timeout in `AuditLog.append_event` is 30s; retry once doubles the operator-visible ceiling but bounds runaway flakiness). If retry also fails, treats as error — but logs an explicit `findings=["audit lock timeout after retry"]` so the operator can distinguish this failure from a true collector error. |
| Failure isolation | Per-unit creation failure → emit error evidence for that collector, continue. Per-unit cleanup failure → best-effort, never raises (matches existing `cleanup_collector_checkout` contract). |
| Order preservation | Returned `list[CollectorOutcome]` MUST be sorted `(category, collector_id)` ASCII ascending. Property test pins it. |
| Cwd isolation under threading | No `os.chdir`. `subprocess.run(cwd=…)` is thread-local. Pinned by audit-floor invariant. |
| Audit emission | Each worker emits `EvidenceCollectedAudit` via `emit_gate_audit`. Thread-safe via `core.audit.AuditLog`'s filelock (verified). |
| Lock ordering | **No new `_bmad/*.lock` co-acquisition.** The orchestrator already holds `.gate.lock` for the gate lifecycle. Worker threads MUST NOT acquire ANY `_bmad/*.lock` (deadlock vector vs. parent's `.gate.lock`). PINNED by audit-floor invariant `test_ast_no_gate_lock_acquisition_in_isolation_module`. |
| **Janitor extension (HIGH #5 fix)** | `worktree_recovery.recover_orphan_worktrees` already prunes `.git/worktrees/<name>/` admin entries via `git worktree prune` (lines 71-82). Per-unit's higher orphan-rate doesn't change the janitor's API — same call site. **But** the new `add_timeout` parameter the per-unit path passes to `create_collector_checkout` raises the worst-case orphan window from 30s to 90s; document this in the janitor's docstring and add a new optional `recover_orphan_worktrees(..., per_unit_window_s: float = 0.0)` kwarg that biases `min_age_s` toward the longer window (defaults to 0 = byte-identical to today). |
| **`add_timeout` kwarg on `create_collector_checkout` (MED #2 fix)** | `create_collector_checkout(*, name_hint: str = "", add_timeout: int | None = None) -> Path`. When `add_timeout is None` (default), uses `_GIT_TIMEOUT = 30` (byte-identical). When non-None, uses the supplied value. Per-unit dispatch always passes 90. Also adds bounded retry-with-backoff for transient `git worktree add` errors matching `re.search(r"could not lock|already locked|index\.lock", result.stderr.lower())`: 1-2 retries with ~50 ms sleep. |
| Frozen-surface contract | Four new optional kwargs on `run_production_gate` + `run_system_gate` + `run_gate_collectors` + `_run_collectors` (two each: `isolation_mode`, `max_workers`). Two new optional kwargs on `create_collector_checkout` (`name_hint`, `add_timeout`). One new optional kwarg on `recover_orphan_worktrees` (`per_unit_window_s`). All defaults preserve byte-identical behavior. No gate-file shape changes. No persisted-artifact shape changes. |
| Audit-floor invariant | New `WorktreePerUnitIsolationInvariant` class with FOUR sub-tests (rev 2 added the lock-acquisition pin from HIGH #2). Modeled exactly on `AuditKeyEnvScrubInvariant` + `UnifiedStateWriteIsolationInvariant` + the C5 `ThresholdApplyIsolationInvariant` (post-impl review form) for structural rename-proof exemption + binding tracking + indirect-call detection + meaningful two-direction positive-failure proof. |
| Determinism vs. byte-identical (HIGH #1 fix) | The new mode CHANGES `duration_ms` on every evidence record by construction (parallel + per-unit checkout has different wall-clock than sequential + shared checkout). Therefore `evidence_merkle_root` (which hashes canonical-JSON evidence including `duration_ms`) WILL differ between modes. **Removing the byte-identical-gate-file claim from rev 1**: AC-G-03 now asserts CATEGORY-VERDICT equivalence (not byte-equivalence) when collectors are deterministic — the gate's `categories` shape, per-category verdicts, and overall verdict match; `duration_ms`/`evidence_merkle_root`/`evidence_bundle_hash` are EXPECTED to differ. Per-collector `cost_total_usd` distribution also differs (per-unit's longer wall-clock → different cost attribution). All documented. |
| Per-worker disk + RAM | ~50 MiB working tree × `max_workers=4` ≈ 200 MiB peak working-file disk. Per-worker subprocess RSS up to 100 MiB. **RAM-aware clamp** at 256 MiB per worker (see formula). Tmpfs `/tmp` is RAM-backed — documented escape hatch: operator sets `TMPDIR=/path/to/real-disk`. |
| Backward compatibility | The `shared` path in `run_gate_collectors` is BYTE-IDENTICAL — no refactor of that branch. |
| Storage budget | Run module ≤ 350 LOC. New module + tests + docs ~1500 LOC total. |
| New deps? | **No.** Stdlib `concurrent.futures`, `threading`, `tempfile`, `os`, `shutil`, `subprocess`. `psutil` already on the allowlist. |

## 4. Architecture

```
                ┌─────────────────────────────────────────────────────────────┐
                │  core/collector_isolation.py    (NEW, ~320 LOC)             │
                │                                                             │
   exports ──>  │  IsolationMode = Literal["shared", "per_unit"]              │
                │  DEFAULT_MAX_WORKERS: int = 4                               │
                │  MAX_PARALLEL_CEILING: int = 16                             │
                │  ESTIMATED_PER_WORKER_BYTES: int = 256 * 1024 * 1024        │
                │  ADD_TIMEOUT_PER_UNIT_S: int = 90                           │
                │                                                             │
                │  _validate_isolation_kwargs(isolation_mode, max_workers)    │
                │    Called BEFORE any other work at every entry point.       │
                │    Raises TypeError on non-int (or bool) max_workers.       │
                │    Raises ValueError on isolation_mode not in vocabulary.   │
                │                                                             │
                │  run_collectors_per_unit(                                   │
                │    project_root, gate_id, commit_sha, profile,              │
                │    collectors: list[CollectorConfig],                       │
                │    *, max_workers: int = DEFAULT_MAX_WORKERS,               │
                │    audit_policy=None, audit_path=None,                      │
                │  ) -> list[CollectorOutcome]                                │
                │                                                             │
                │    1. clamped = _clamp_max_workers(max_workers, project_root)│
                │    2. outcomes: list[CollectorOutcome] = []                 │
                │       _pending_baseexc: BaseException | None = None         │
                │       future_to_config: dict[Future, CollectorConfig] = {}  │
                │    3. try:                                                  │
                │           with ThreadPoolExecutor(                          │
                │             max_workers=clamped,                            │
                │             thread_name_prefix="sa-collector",              │
                │           ) as pool:                                        │
                │               for config in collectors:                     │
                │                   fut = pool.submit(                        │
                │                       _run_isolated, config,                │
                │                       project_root, gate_id, commit_sha,    │
                │                       profile, audit_policy, audit_path,    │
                │                   )                                         │
                │                   future_to_config[fut] = config            │
                │               for fut in as_completed(future_to_config):    │
                │                   try:                                      │
                │                       outcomes.append(fut.result())         │
                │                   except BaseException as exc:              │
                │                       cfg = future_to_config[fut]           │
                │                       outcomes.append(                      │
                │                           _crash_outcome(cfg, exc,          │
                │                                          project_root,      │
                │                                          gate_id)           │
                │                       )                                     │
                │                       if isinstance(exc,                    │
                │                           (KeyboardInterrupt, SystemExit)): │
                │                           _pending_baseexc = exc            │
                │       except KeyboardInterrupt as exc:                      │
                │           pool.shutdown(wait=False, cancel_futures=True)    │
                │           _pending_baseexc = exc                            │
                │    4. outcomes.sort(key=lambda o:                          │
                │           (o.config.category, o.config.collector_id))      │
                │    5. if _pending_baseexc is not None:                      │
                │           raise _pending_baseexc                            │
                │    6. return outcomes                                       │
                │                                                             │
                │  _run_isolated(config, project_root, gate_id, commit_sha,   │
                │                profile, audit_policy, audit_path)           │
                │                -> CollectorOutcome                          │
                │    Inside the worker thread:                                │
                │    1. original = threading.current_thread().name            │
                │       threading.current_thread().name = (                   │
                │           f"sa-isolated-{config.collector_id}")             │
                │    2. checkout = None                                       │
                │       try:                                                  │
                │           try:                                              │
                │               checkout = _create_unit_checkout(             │
                │                   project_root, commit_sha,                 │
                │                   name_hint=config.collector_id,            │
                │                   add_timeout=ADD_TIMEOUT_PER_UNIT_S,       │
                │               )                                             │
                │           except CollectorCheckoutError as exc:             │
                │               return _error_outcome(                        │
                │                   config, exc, project_root, gate_id)       │
                │           try:                                              │
                │               return run_single_collector(                  │
                │                   config, str(checkout), profile,           │
                │                   gate_id, project_root,                    │
                │                   audit_policy=audit_policy,                │
                │                   audit_path=audit_path,                    │
                │               )                                             │
                │           except AuditLockTimeout:                          │
                │               # MED #6: retry once for slow-disk events.   │
                │               try:                                          │
                │                   return run_single_collector(...)          │
                │               except AuditLockTimeout as exc2:              │
                │                   return _audit_timeout_outcome(            │
                │                       config, exc2, project_root, gate_id)  │
                │           except Exception as exc:                          │
                │               return _crash_outcome(                        │
                │                   config, exc, project_root, gate_id)       │
                │           except BaseException as exc:                      │
                │               return _crash_outcome(                        │
                │                   config, exc, project_root, gate_id)       │
                │       finally:                                              │
                │           if checkout is not None:                          │
                │               _cleanup_unit_checkout(checkout, project_root)│
                │           threading.current_thread().name = original        │
                │                                                             │
                │  _create_unit_checkout(project_root, commit_sha,            │
                │                        name_hint, add_timeout)              │
                │    Delegates to create_collector_checkout with both         │
                │    additive kwargs.                                         │
                │                                                             │
                │  _cleanup_unit_checkout(checkout, project_root)             │
                │    Best-effort: delegates to cleanup_collector_checkout.    │
                │    Catches OSError + RuntimeError; never raises.            │
                │                                                             │
                │  _clamp_max_workers(requested, project_root=None) -> int    │
                │    cpu_ceiling = min(16,                                    │
                │      max(1, (os.cpu_count() or 4) - 2))                     │
                │    try:                                                     │
                │        avail = psutil.virtual_memory().available            │
                │        ram_ceiling = max(1,                                 │
                │          int(avail // ESTIMATED_PER_WORKER_BYTES))          │
                │    except Exception:                                        │
                │        ram_ceiling = cpu_ceiling                            │
                │    return max(1, min(requested, cpu_ceiling, ram_ceiling))  │
                │                                                             │
                │  _sanitize_name_hint(hint: str) -> str                      │
                │    sanitized = "".join(                                     │
                │      ch for ch in (hint or "")                             │
                │      if ch in _ALLOWED_NAME_HINT_CHARSET                    │
                │    )                                                        │
                │    if not sanitized:                                        │
                │        return ""                                            │
                │    # sanitize-FIRST then take-LAST-N for collision-safe    │
                │    # disambiguation of long-prefixed collector ids.         │
                │    return sanitized[-_NAME_HINT_TAIL_CAP:]                  │
                │                                                             │
                │  _error_outcome / _crash_outcome / _audit_timeout_outcome:  │
                │    Mirror existing run_gate_collectors error path. Persist  │
                │    evidence with status="error"; emit EvidenceCollectedAudit│
                │    so the verdict engine treats it as real evidence.        │
                └─────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                ┌─────────────────────────────────────────────────────────────┐
                │  core/collector_runner.py    (modified, +12 LOC)            │
                │                                                             │
                │  run_gate_collectors(                                       │
                │    project_root, gate_id, commit_sha, profile, registry,    │
                │    *, diff_categories=None,                                 │
                │    audit_policy=None, audit_path=None,                      │
                │    isolation_mode: Literal["shared","per_unit"]="shared",   │
                │    max_workers: int = 4,                                    │
                │  ) -> list[CollectorOutcome]                                │
                │                                                             │
                │    # HIGH #6 — early validation (both modes).               │
                │    from .collector_isolation import (                       │
                │        _validate_isolation_kwargs,                          │
                │    )                                                        │
                │    _validate_isolation_kwargs(isolation_mode, max_workers)  │
                │    assert_host_context("run_gate_collectors")               │
                │    collectors = registry.applicable(profile)                │
                │    if diff_categories is not None:                          │
                │        collectors = [c for c in collectors                  │
                │                       if c.category in diff_categories]    │
                │    if not collectors: return []                             │
                │    if isolation_mode == "per_unit":                         │
                │        from .collector_isolation import (                   │
                │            run_collectors_per_unit,                         │
                │        )                                                    │
                │        return run_collectors_per_unit(                      │
                │            project_root, gate_id, commit_sha, profile,     │
                │            collectors,                                      │
                │            max_workers=max_workers,                         │
                │            audit_policy=audit_policy,                       │
                │            audit_path=audit_path,                           │
                │        )                                                    │
                │    # Existing shared path — BYTE-IDENTICAL to today.        │
                │    outcomes: list[CollectorOutcome] = []                    │
                │    with collector_checkout(project_root, commit_sha) as ckt:│
                │        for config in collectors:                            │
                │            ... existing loop ...                            │
                │    return outcomes                                          │
                └─────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                ┌─────────────────────────────────────────────────────────────┐
                │  core/gate_orchestrator.py    (modified, +14 LOC)           │
                │                                                             │
                │  _run_collectors(                                           │
                │    project_root, gate_id, commit_sha, profile, registry,    │
                │    *, diff_categories=None,                                 │
                │    audit_policy=None, audit_path=None,                      │
                │    isolation_mode: Literal["shared","per_unit"]="shared",   │
                │    max_workers: int = 4,                                    │
                │  ) -> list[Any]                                             │
                │    """Wrapper for testability — delegates to                │
                │    run_gate_collectors."""                                  │
                │    return run_gate_collectors(                              │
                │        project_root, gate_id, commit_sha, profile,         │
                │        registry,                                            │
                │        diff_categories=diff_categories,                     │
                │        audit_policy=audit_policy, audit_path=audit_path,    │
                │        isolation_mode=isolation_mode,                       │
                │        max_workers=max_workers,                             │
                │    )                                                        │
                │                                                             │
                │  run_production_gate(                                       │
                │    ..., existing kwargs ...,                                │
                │    isolation_mode: Literal["shared","per_unit"]="shared",  │
                │    max_workers: int = 4,                                    │
                │  ) -> dict[str, Any]                                        │
                │                                                             │
                │    # HIGH #6 — validate at top, before any work.            │
                │    from .collector_isolation import (                       │
                │        _validate_isolation_kwargs,                          │
                │    )                                                        │
                │    _validate_isolation_kwargs(isolation_mode, max_workers)  │
                │    ... existing flow ...                                    │
                │    collector_outcomes = _run_collectors(                    │
                │        project_root, gate_id, commit_sha, profile,         │
                │        registry,                                            │
                │        audit_policy=audit_policy, audit_path=audit_path,    │
                │        isolation_mode=isolation_mode,                       │
                │        max_workers=max_workers,                             │
                │    )                                                        │
                │    ... rest unchanged ...                                   │
                └─────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                ┌─────────────────────────────────────────────────────────────┐
                │  core/system_gate.py    (modified, +10 LOC) (HIGH #2 fix)   │
                │                                                             │
                │  run_system_gate(                                           │
                │    ..., existing kwargs ...,                                │
                │    isolation_mode: Literal["shared","per_unit"]="shared",  │
                │    max_workers: int = 4,                                    │
                │  ) -> dict[str, Any]                                        │
                │                                                             │
                │    from .collector_isolation import (                       │
                │        _validate_isolation_kwargs,                          │
                │    )                                                        │
                │    _validate_isolation_kwargs(isolation_mode, max_workers)  │
                │    ... existing flow ...                                    │
                │    # The system-gate's collector call site (look at         │
                │    # system_gate.py for the actual line number; pass the    │
                │    # kwargs through to run_gate_collectors).                │
                │    outcomes = run_gate_collectors(                          │
                │        ..., isolation_mode=isolation_mode,                  │
                │        max_workers=max_workers,                             │
                │    )                                                        │
                └─────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                ┌─────────────────────────────────────────────────────────────┐
                │  core/collector_checkout.py    (modified, +28 LOC)          │
                │                                                             │
                │  create_collector_checkout(                                 │
                │    project_root, commit_sha,                                │
                │    *, name_hint: str = "",                                  │
                │    add_timeout: int | None = None,                          │
                │  ) -> Path                                                  │
                │                                                             │
                │    ... existing validation ...                              │
                │    timeout = _GIT_TIMEOUT if add_timeout is None            │
                │                            else int(add_timeout)            │
                │    suffix_parts = [f"-{resolved_sha[:8]}"]                  │
                │    if name_hint:                                            │
                │        sanitized = _sanitize_name_hint(name_hint)           │
                │        if sanitized:                                        │
                │            suffix_parts.append(f"-{sanitized}")             │
                │    checkout_dir = Path(tempfile.mkdtemp(                    │
                │        prefix="sa-collector-",                              │
                │        suffix="".join(suffix_parts),                        │
                │    ))                                                       │
                │    # MED #2 — bounded retry on transient git lock errors.   │
                │    last_stderr = ""                                         │
                │    for attempt in range(_MAX_WORKTREE_ADD_ATTEMPTS):        │
                │        result = subprocess.run(                             │
                │            ["git","worktree","add","--detach",              │
                │             str(checkout_dir), resolved_sha],               │
                │            cwd=str(root), capture_output=True, text=True,   │
                │            timeout=timeout,                                 │
                │            env=scrub_env_for_subprocess(),                  │
                │        )                                                    │
                │        if result.returncode == 0: break                     │
                │        last_stderr = result.stderr or ""                    │
                │        if not _is_transient_lock_error(last_stderr):        │
                │            break                                            │
                │        time.sleep(_WORKTREE_ADD_BACKOFF_S)                  │
                │    if result.returncode != 0:                               │
                │        shutil.rmtree(checkout_dir, ignore_errors=True)      │
                │        raise CollectorCheckoutError(                        │
                │            f"git worktree add failed (exit ...): "          │
                │            f"{last_stderr.strip()}")                        │
                │    ... rest unchanged ...                                   │
                │                                                             │
                │  _sanitize_name_hint(hint: str) -> str                      │
                │    Same implementation as collector_isolation's helper;     │
                │    co-located here because create_collector_checkout is     │
                │    its public consumer. (collector_isolation re-exports.)   │
                │                                                             │
                │  _is_transient_lock_error(stderr: str) -> bool              │
                │    return bool(_TRANSIENT_LOCK_RE.search(stderr or ""))     │
                │                                                             │
                │  _TRANSIENT_LOCK_RE = re.compile(                           │
                │    r"(could not lock|already locked|index\.lock|"           │
                │    r"config\.lock|locked by another process)", re.I)        │
                │  _MAX_WORKTREE_ADD_ATTEMPTS = 3                             │
                │  _WORKTREE_ADD_BACKOFF_S = 0.05                             │
                └─────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                ┌─────────────────────────────────────────────────────────────┐
                │  core/worktree_recovery.py    (modified, +18 LOC) (HIGH #5) │
                │                                                             │
                │  recover_orphan_worktrees(                                  │
                │    project_root, *,                                         │
                │    min_age_s: float = 3600.0,                               │
                │    now: float | None = None,                                │
                │    per_unit_window_s: float = 0.0,                          │
                │  ) -> dict[str, Any]                                        │
                │                                                             │
                │    # HIGH #5 follow-up: per-unit dispatch can leave         │
                │    # worktrees up to add_timeout=90s old that are still     │
                │    # in-flight on a slow disk. Operators who run the        │
                │    # janitor right after a per-unit crash should pass       │
                │    # per_unit_window_s=120 to add a safety margin to        │
                │    # the effective min_age_s.                               │
                │    effective_min_age = max(min_age_s,                       │
                │                            per_unit_window_s)               │
                │    ... existing prune + scratch sweep using                 │
                │        effective_min_age instead of min_age_s ...           │
                └─────────────────────────────────────────────────────────────┘
```

Key properties:

- **Default behavior byte-identical at four wiring points** (`run_production_gate`, `run_system_gate`, `_run_collectors`, `run_gate_collectors`). Existing tests stay green without modification.
- **Single dispatch line.** `if isolation_mode == "per_unit": return run_collectors_per_unit(...)`. Audit-floor invariant recognizes the canonical pattern (refactor-tolerant per HIGH #3).
- **Thread safety pinned by AST invariants.** No `os.chdir`, `os.environ` mutation, `signal.signal`, OR `_bmad/*.lock` acquisition in `collector_isolation.py`.
- **Failure isolation.** Worker exceptions → `CollectorOutcome` with `status="error"`. `BaseException` reified the same way + re-raised AFTER outcome collection. KeyboardInterrupt drains queue, lets in-flight finish, re-raises.
- **Audit-lock retry.** Slow-disk `AuditLockTimeout` is retried once before reifying as error — distinguishes slow-disk events from true collector failures.

## 5. Schemas (compact)

### 5.1 `IsolationMode` and constants

```python
from typing import Literal
IsolationMode = Literal["shared", "per_unit"]

DEFAULT_MAX_WORKERS: int = 4
MAX_PARALLEL_CEILING: int = 16
ESTIMATED_PER_WORKER_BYTES: int = 256 * 1024 * 1024  # 256 MiB / worker
ADD_TIMEOUT_PER_UNIT_S: int = 90
_NAME_HINT_TAIL_CAP: int = 32
_ALLOWED_NAME_HINT_CHARSET: frozenset[str] = frozenset(
    string.ascii_letters + string.digits + "._-"
)
```

### 5.2 No new dataclasses

`CollectorOutcome` and `CollectorConfig` are unchanged. No `_IsolatedWorkUnit` (rev 1 dead code — DELETED). The seven kwargs of `_run_isolated` self-document.

### 5.3 New optional kwargs on `create_collector_checkout`

```python
def create_collector_checkout(
    project_root: str | Path,
    commit_sha: str,
    *,
    name_hint: str = "",
    add_timeout: int | None = None,
) -> Path:
```

- `name_hint`: optional ASCII identifier. Empty (default) → suffix is `f"-{sha[:8]}"` (byte-identical to today). Non-empty → suffix is `f"-{sha[:8]}-{sanitize(name_hint)}"`. Sanitization is sanitize-FIRST (drop chars not in `[A-Za-z0-9._-]`), truncate-SECOND (take last 32 chars of sanitized).
- `add_timeout`: optional override for the `git worktree add` timeout. `None` (default) = `_GIT_TIMEOUT = 30` (byte-identical). Per-unit always passes `ADD_TIMEOUT_PER_UNIT_S = 90`.

### 5.4 New optional kwarg on `recover_orphan_worktrees`

```python
def recover_orphan_worktrees(
    project_root: str | Path,
    *,
    min_age_s: float = 3600.0,
    now: float | None = None,
    per_unit_window_s: float = 0.0,
) -> dict[str, Any]:
```

`per_unit_window_s`: optional safety-margin added to `min_age_s`. Default `0.0` (byte-identical). Operators running the janitor right after a per-unit crash pass e.g. `120.0` to ensure no in-flight worker is wrongly reaped.

## 6. Implementation surface — files

| File | New / Modified | LOC delta | Notes |
|---|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/collector_isolation.py` | **New** | ~320 (≤350) | All public + private surfaces from §4. |
| `skills/bmad-story-automator/src/story_automator/core/collector_runner.py` | Modified | +12 | Two new kwargs + early-validation + dispatch branch. |
| `skills/bmad-story-automator/src/story_automator/core/collector_checkout.py` | Modified | +28 | `name_hint` + `add_timeout` kwargs; `_sanitize_name_hint`; `_is_transient_lock_error`; retry loop. |
| `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` | Modified | +14 | Two new kwargs on `run_production_gate` AND `_run_collectors` wrapper; early validation. |
| `skills/bmad-story-automator/src/story_automator/core/system_gate.py` | Modified | +10 | Two new kwargs on `run_system_gate`; threaded through to `run_gate_collectors`. |
| `skills/bmad-story-automator/src/story_automator/core/worktree_recovery.py` | Modified | +18 | New `per_unit_window_s` kwarg; `effective_min_age` computation. |
| `skills/bmad-story-automator/tests/test_collector_isolation.py` | **New** | ~520 | ≥22 tests — see §7.2. |
| `skills/bmad-story-automator/tests/test_gate_orchestrator_g2_wiring.py` | **New** | ~240 | ≥10 tests — covers AC-G-01..G-09 plus the system_gate sibling. |
| `skills/bmad-story-automator/tests/test_collector_checkout.py` | Modified | +90 | `name_hint` + `add_timeout` + transient-lock retry tests. |
| `skills/bmad-story-automator/tests/test_collector_runner.py` | Modified | +60 | Early-validation tests (AC-D-04: invalid mode/max_workers raise in BOTH modes). |
| `skills/bmad-story-automator/tests/test_system_gate.py` | Modified | +50 | New kwargs are threaded; default byte-identical. |
| `skills/bmad-story-automator/tests/test_worktree_recovery.py` | Modified | +40 | `per_unit_window_s` kwarg semantics. |
| `tests/test_audit_regression.py` | Modified | +260 | `WorktreePerUnitIsolationInvariant` with 4 sub-tests + meaningful two-direction positive-failure proof. |
| `docs/changelog/2026-06-24-g2-worktree-per-unit.md` | **New** | ~60 | `[FULL]` tag entry. Dated 2026-06-24 (review fold-in day). |
| `docs/spec/frozen-gate-surface.md` | Modified | +32 | New `### core/collector_isolation.py` section + appendix for the new optional kwargs. |
| `CLAUDE.md` | Modified | +24 | New "Worktree-per-unit isolation (G2)" section under "Recently shipped"; update "additive kwargs (cumulative)" list to add `isolation_mode` + `max_workers`; bump audit-floor invariant count from 10 → 11. |

Total LOC delta ≈ +1750, of which ~1000 is tests + docs. Run module stays ≤ 350 LOC.

## 7. Acceptance criteria

### 7.1 Behavioral

**`_validate_isolation_kwargs` — early validation (HIGH #6)**

- AC-V-01 — `isolation_mode="invalid"` → `ValueError` before any other work. Verified at BOTH `run_production_gate`, `run_system_gate`, AND `run_gate_collectors`.
- AC-V-02 — `max_workers="four"` → `TypeError`. Tested in BOTH `shared` and `per_unit` modes (no silent acceptance in shared).
- AC-V-03 — `max_workers=True` (bool subclass of int) → `TypeError` ("must be int, not bool").

**`run_collectors_per_unit`**

- AC-I-01 — Empty `collectors` → returns `[]`; no worktrees created.
- AC-I-02 — One collector → one worktree at `tempfile.gettempdir() / sa-collector-*-<sha8>-<sanitized_id>`; one outcome returned; one `EvidenceCollectedAudit` emitted; worktree cleaned up. Path assertions use `assert ckt.parent == Path(tempfile.gettempdir())` AND `ckt.name.startswith("sa-collector-")` AND `ckt.name.endswith(f"-{sha[:8]}-{sanitize(collector_id)}")`. Random middle chars NOT pinned.
- AC-I-03 — Three collectors → outcomes sorted `(category, collector_id)` ASCII. Reversed input still yields sorted output.
- AC-I-04 — One collector raising `Exception` → `status="error"` evidence; siblings unaffected; no exception propagates.
- AC-I-05 — `create_collector_checkout` fails for one collector → `status="error"` evidence with `findings=["checkout failed: ..."]`; siblings unaffected.
- AC-I-06 — Cleanup `shutil.rmtree` raising `OSError` is swallowed; outcomes list still returned. (Cleanup failure does NOT trigger error evidence; it's best-effort and orthogonal to collector outcome.)
- AC-I-07 — `max_workers=100` clamped via `_clamp_max_workers` to `min(16, cpu-2, ram_ceiling)`. `max_workers=0` and `-5` clamped to 1.
- AC-I-08 — Returned list sort order pinned across shuffled input (property test).
- AC-I-09 — Concurrent stress: 16 synthetic collectors with `max_workers=8`; ALL 16 evidence records present; NONE have `status="error"`; NONE have `findings` matching `"AuditLockTimeout"`. **Test monkey-patches `os.cpu_count` to return 32** so a 1-vCPU CI runner still exercises real concurrency (MED #5). Test injects a `fake_fsync` adding 200 ms delay to provoke the audit-lock contention path.
- AC-I-10 — Each worker emits one `EvidenceCollectedAudit` (verified via a fake audit policy that captures emit calls).
- AC-I-11 — Per-unit worktrees live under `tempfile.gettempdir()`. Verified by `is_path_under(Path(tempfile.gettempdir()), ckt)`; NOT under `_bmad/` (verified by `not is_path_under(project_root / "_bmad", ckt)`).
- AC-I-12 — `assert_host_context` raised in child-session env → propagates from the per-unit dispatch path; no worktrees created.
- AC-I-13 — `KeyboardInterrupt` raised on main thread mid-`run_collectors_per_unit`: `pool.shutdown(wait=False, cancel_futures=True)` called; queued-but-not-started collectors leave NO worktree; in-flight workers' `subprocess.run` is allowed to complete to its timeout; outcomes for completed workers ARE collected and persisted to disk; KeyboardInterrupt is re-raised AFTER outcome collection. The returned outcomes list is 1:1 with persisted evidence.
- AC-I-14 — `MemoryError` raised inside one worker → `_run_isolated` catches `BaseException`, returns `_crash_outcome` with `findings=["worker terminated: MemoryError: ..."]`. Siblings' outcomes still collected. The MemoryError is re-raised AFTER outcome collection.
- AC-I-15 — `AuditLockTimeout` raised during the worker's first `run_single_collector` call → retried once; if retry succeeds, the outcome is the second-attempt's. If retry fails, returns `_audit_timeout_outcome` with `findings=["audit lock timeout after retry"]`.
- AC-I-16 — Thread name save+restore: after `run_collectors_per_unit` returns, every thread reused by the pool has its `.name` restored to the original `ThreadPoolExecutor-N_M` shape (no stale `sa-isolated-*`).
- AC-I-17 — `_clamp_max_workers` formula: with `psutil.virtual_memory` patched to return `available = 2 GiB`, `_clamp_max_workers(8)` returns `min(8, cpu_ceiling, 8)` = 8. With `available = 256 MiB`, returns `min(8, cpu_ceiling, 1)` = 1.
- AC-I-18 — `_clamp_max_workers` with `psutil.virtual_memory` raising → `ram_ceiling = cpu_ceiling`; never crashes.
- AC-I-19 — `_clamp_max_workers(8)` with `os.cpu_count` patched to None → cpu_ceiling = `min(16, max(1, 4 - 2))` = 2.
- AC-I-20 — `_sanitize_name_hint("../etc/passwd")` returns `"etcpasswd"` (sanitized = `etcpasswd`, length 9, all retained). `_sanitize_name_hint` `("a" * 40)` returns `"a" * 32` (last 32). `_sanitize_name_hint("")` returns `""`. `_sanitize_name_hint("static_τ_p1")` returns `"static__p1"` (non-ASCII dropped, then last 32).

**`run_gate_collectors` dispatch**

- AC-D-01 — `isolation_mode="shared"` (default) → existing inline path runs; outcomes BYTE-IDENTICAL to pre-G2 fixture (the SHARED-MODE outcomes list is the byte-identical comparison target, not the per_unit one — HIGH #1).
- AC-D-02 — `isolation_mode="per_unit"` → `run_collectors_per_unit` is called; outcomes' `(config, status, findings)` triple matches `shared` mode when collectors are deterministic. `duration_ms` IS allowed to differ.
- AC-D-03 — Invalid `isolation_mode` → `ValueError` BEFORE `assert_host_context` (HIGH #6).
- AC-D-04 — `max_workers` validated even in `shared` mode (HIGH #6); passing `"four"` in `shared` raises `TypeError`. Documented: `max_workers` is plumbed through only to the per_unit executor — it has no effect in `shared` BUT is still type-validated to prevent operator footguns when flipping mode later.

**`run_production_gate` + `run_system_gate` wiring (HIGH #2 fix)**

- AC-G-01 — Default kwargs → on-disk `_bmad/gate/verdicts/<gate_id>.json` byte-identical to pre-G2 for the same fixture. Pinned by canonical-JSON byte equality.
- AC-G-02 — `isolation_mode="per_unit"` end-to-end → returned gate dict has identical KEY SET to AC-G-01. `categories` dict structure unchanged; per-category VERDICT strings match; `overall` matches.
- AC-G-03 — `isolation_mode="per_unit"` produces a gate dict whose `categories[*].verdict` matches the `shared` mode for the SAME deterministic collector fixture. **`duration_ms`, `evidence_merkle_root`, `evidence_bundle_hash`, `cost_total_usd` are EXPECTED TO DIFFER between modes** (this is what per_unit is FOR). Test asserts category-verdict equivalence only.
- AC-G-04 — Invalid `isolation_mode` / `max_workers` types → raised BEFORE `assert_host_context` AND BEFORE the gate lock is acquired (HIGH #6). Verified by inspecting gate-marker state after the raise (no marker written).
- AC-G-05 — Gate-lock semantics preserved: a second filelock acquisition during a `per_unit` gate times out (parent thread holds `.gate.lock` for lifecycle).
- AC-G-06 — `isolation_mode="per_unit"` composes with ALL existing kwargs (`drift_watcher`, `session_usage`, `threshold_proposer`, `baseline_sha`, `fail_closed`, `enable_lie_detector`, `enable_pre_gate_verifier`, `result_json_path`). None silently dropped.
- AC-G-07 — `_run_collectors` wrapper at `gate_orchestrator.py:581` ALSO accepts the new kwargs and forwards (HIGH #2). A test calls `_run_collectors(..., isolation_mode="per_unit", max_workers=4)` and asserts the call reaches `run_collectors_per_unit`.
- AC-G-08 — `run_system_gate` ALSO accepts the new kwargs and forwards to `run_gate_collectors` (HIGH #2). Tested with both default and per-unit modes.
- AC-G-09 — KeyboardInterrupt mid-gate during `per_unit` run cleanly clears the gate marker (via the existing `finally: clear_gate_marker(project_root)` block) AND quarantines evidence as recoverable. No orphan in-flight worktrees (each worker's `finally` cleaned up).

**`create_collector_checkout` `name_hint` + `add_timeout` kwargs (rev 2)**

- AC-C-01 — `name_hint=""` → byte-identical to today.
- AC-C-02 — `name_hint="static_p1"` → suffix `-static_p1`.
- AC-C-03 — `name_hint="../etc/passwd"` → suffix `-etcpasswd` (sanitized).
- AC-C-04 — `name_hint` 40 chars → suffix is the LAST 32 chars (collision-safe disambiguation).
- AC-C-05 — `name_hint=""` literally → `_sanitize` returns empty → suffix omits the hint segment.
- AC-C-06 — `add_timeout=None` (default) → uses `_GIT_TIMEOUT=30` (byte-identical).
- AC-C-07 — `add_timeout=90` → `subprocess.run(..., timeout=90)`.
- AC-C-08 — Transient-lock-error retry: `subprocess.run` returncode!=0 with stderr containing `"could not lock"` → retried up to `_MAX_WORKTREE_ADD_ATTEMPTS=3` times with `_WORKTREE_ADD_BACKOFF_S=0.05` between. After exhaustion, raises `CollectorCheckoutError`.
- AC-C-09 — Non-transient git error (e.g., bad SHA) is NOT retried; raised on first failure.

**`recover_orphan_worktrees` `per_unit_window_s` kwarg (HIGH #5 fix)**

- AC-R-01 — Default `per_unit_window_s=0.0` → byte-identical to today (effective `min_age_s` unchanged).
- AC-R-02 — `per_unit_window_s=120.0` with `min_age_s=60.0` → effective threshold is 120s (max).
- AC-R-03 — `per_unit_window_s=10.0` with `min_age_s=3600.0` → effective threshold stays 3600s.

### 7.2 `tests/test_collector_isolation.py` minimum coverage (≥22 tests)

1. Empty collectors → `[]`; no worktrees.
2. One collector happy path: worktree created, collector runs, evidence persisted, worktree cleaned up.
3. Three collectors all succeed: outcomes sorted; three distinct worktree paths observed.
4. Crashing collector: `status="error"` evidence; siblings unaffected.
5. Crashing `create_collector_checkout`: `status="error"` evidence; siblings unaffected.
6. Cleanup failure (mocked `shutil.rmtree` raising `OSError`) does NOT propagate; outcome list returned.
7. `_clamp_max_workers`: 100 → `min(16, cpu-2, ram_ceiling)`; 0 → 1; -5 → 1; with `os.cpu_count=None` patched → 2.
8. `_clamp_max_workers` RAM-aware: patched `psutil.virtual_memory().available = 256 MiB` → ram_ceiling=1.
9. `_clamp_max_workers` graceful: `psutil.virtual_memory` raising → ram_ceiling=cpu_ceiling.
10. Concurrent stress (16 collectors, `max_workers=8`, `os.cpu_count` patched to 32, fake fsync 200ms): all 16 records present; none have `status="error"`; none have `findings` matching `AuditLockTimeout`.
11. `_run_isolated` emits one `EvidenceCollectedAudit` per outcome.
12. Per-unit worktrees live under `tempfile.gettempdir()`, NOT `_bmad/`.
13. `assert_host_context` raised in child-session env → propagates.
14. KeyboardInterrupt mid-run: queue drains, in-flight completes, outcomes 1:1 with disk, KeyboardInterrupt re-raised.
15. `MemoryError` in one worker → `_crash_outcome`; siblings collected; MemoryError re-raised.
16. `AuditLockTimeout` in worker → retried once; if succeeds, success outcome; if fails, `_audit_timeout_outcome`.
17. Thread name save+restore: post-run, no thread `.name` matches `sa-isolated-*`.
18. `_sanitize_name_hint` rejects path traversal: `"../etc/passwd"`, `"foo/bar"`, `"   "`, `"foo\nbar"`.
19. `_sanitize_name_hint` takes LAST 32 chars (sanitize-FIRST-truncate-SECOND).
20. `_sanitize_name_hint` empty → empty.
21. Outcomes sort order pinned: shuffle inputs, assert sorted output (property test).
22. `_validate_isolation_kwargs`: TypeError on non-int max_workers; ValueError on bad isolation_mode; both raised before any other work.

### 7.3 `tests/test_gate_orchestrator_g2_wiring.py` minimum coverage (≥10 tests)

1. `isolation_mode="shared"` default → byte-identical on-disk gate.json vs. pre-G2 fixture.
2. `isolation_mode="per_unit"` end-to-end → key-set equality with shared mode.
3. Invalid `isolation_mode` → `ValueError` before assert_host_context or gate-lock.
4. `max_workers="four"` → `TypeError` before any work; verified in BOTH shared and per_unit (AC-D-04).
5. All-kwargs compose: `per_unit` + drift_watcher + session_usage + threshold_proposer + fail_closed + enable_pre_gate_verifier + baseline_sha all together → no kwarg dropped.
6. Verdict equivalence: shared vs. per_unit produce IDENTICAL `categories[*].verdict` for deterministic fixtures (NOT byte-equal — duration_ms/merkle_root differ).
7. Gate-lock semantics: second filelock acquisition during per_unit gate times out.
8. `_run_collectors` wrapper accepts + forwards new kwargs (AC-G-07).
9. `run_system_gate` accepts + forwards new kwargs (AC-G-08).
10. KeyboardInterrupt mid-gate during per_unit → gate marker cleared, no orphan worktrees in `tempfile.gettempdir()` (verified via `glob`).

### 7.4 `tests/test_collector_checkout.py` extensions

1. `name_hint=""` → byte-identical suffix.
2. `name_hint="static_p1"` → suffix contains `-static_p1`.
3. `name_hint="../etc/passwd"` → suffix contains `-etcpasswd`, no `/` or `..`.
4. `name_hint` 40 chars → suffix is LAST 32 chars.
5. `name_hint` non-ASCII (`"static_τ"`) → suffix is ASCII subset.
6. `name_hint` whitespace → stripped.
7. `add_timeout=None` (default) → `subprocess.run` called with timeout=30.
8. `add_timeout=90` → timeout=90.
9. Transient-lock retry: stderr "could not lock" → retried; succeeds on attempt 2.
10. Retry exhausted → `CollectorCheckoutError` after 3 attempts.
11. Non-transient error (bad SHA) NOT retried.

### 7.5 `tests/test_audit_regression.py::WorktreePerUnitIsolationInvariant` (HIGH #3, #4)

Mirrors the established `AuditKeyEnvScrubInvariant` + `UnifiedStateWriteIsolationInvariant` + C5 `ThresholdApplyIsolationInvariant` (post-impl review form) idiom. FOUR sub-tests:

1. **`test_ast_no_process_global_state_mutation_in_isolation_module`** — walks `core/collector_isolation.py` and rejects ALL of: 
   - `Call(func=Attribute(value=Name("os"), attr in {"chdir","fchdir","umask","setpgrp","setsid","setgid","setuid","setresgid","setresuid"}))`
   - `Subscript(value=Attribute(value=Name("os"), attr="environ"))` as `targets` of `Assign|AnnAssign|AugAssign` OR as a `Delete` target
   - `Call(func=Attribute(value=Attribute(value=Name("os"), attr="environ"), attr in {"update","pop","clear","setdefault","__setitem__","__delitem__"}))`
   - `Call(func=Name("signal") or Attribute(attr="signal"))` (catches `signal.signal(...)`)
   - `Call(func=Name("get_gate_lock"))` OR `Attribute(attr="get_gate_lock")` (catches direct import + attribute-form acquisition)
   - `Call(func=Attribute(attr="get_gate_lock"))` against ANY receiver (also catches `evidence_io.get_gate_lock`)
   
   Includes positive-failure proof: synthetic AST with each violation pattern flagged.

2. **`test_ast_no_implicit_per_unit_dispatch_outside_isolation`** — walks BOTH `core/` AND `commands/`; structural exemption uses TWO rename-proof helpers:
   - `_defines_isolation_runner(tree)`: top-level body defines `def run_collectors_per_unit(...)` → skip.
   - `_dispatches_via_isolation_mode(tree)`: top-level function `run_gate_collectors` whose body contains an `If` whose `test` references `Name("isolation_mode")` AND whose `comparators` (anywhere in the test expression, including `BoolOp`/`In`/`match` cases) include `Constant("per_unit")` → exempt that single Call. Refactor-tolerant: handles `==`, `in {...}`, `match ... case "per_unit":`, intermediate-variable `mode = isolation_mode; if mode == "per_unit":`.
   
   Binding-tracking (modeled on `UnifiedStateWriteIsolationInvariant._module_violates`):
   - `from ... import run_collectors_per_unit as ALIAS` → ALIAS forbidden. Handles parenthesized `from X import (run_collectors_per_unit as alias,)`.
   - `Assign(targets=[Name(LHS)], value=Name("run_collectors_per_unit"))` → LHS forbidden.
   - `AnnAssign(target=Name(LHS), value=Name("run_collectors_per_unit"))` → LHS forbidden (the C5 post-impl fix).
   - Flag `Call(func=Name(N))` with N in forbidden set.
   - Flag `Call(func=Attribute(attr="run_collectors_per_unit"))`.
   - Flag `getattr(_, "run_collectors_per_unit")` and `importlib.import_module(...).run_collectors_per_unit`.

3. **`test_positive_failure_synthetic_violator_is_caught`** — MEANINGFUL two-direction proof (HIGH #4 fix; closes the C5 post-impl-review hole):
   - (a) Synthetic source with direct call + alias rebinding + AnnAssign rebinding + getattr + importlib — ALL flagged.
   - (b) Stripping the `def run_collectors_per_unit` exemption-defining FunctionDef from `collector_isolation.py` AND THEN INJECTING a synthetic `_residual_check = run_collectors_per_unit; _residual_check(...)` call into the residual → walker MUST flag it. This proves the rule fires on a non-vacuous residual. The C5 post-impl review found that residual-only stripping was vacuously true; injecting a synthetic call after the strip makes the residual exercise the rule.

4. **`test_default_isolation_mode_is_shared`** — pins safety-critical defaults at FOUR sites:
   ```python
   import inspect
   from story_automator.core.collector_runner import run_gate_collectors
   from story_automator.core.gate_orchestrator import (
       run_production_gate, _run_collectors,
   )
   from story_automator.core.system_gate import run_system_gate
   for fn in (run_gate_collectors, run_production_gate, _run_collectors, run_system_gate):
       sig = inspect.signature(fn)
       assert sig.parameters["isolation_mode"].default == "shared", fn
       assert sig.parameters["max_workers"].default == 4, fn
   ```

### 7.6 Quality gates

- `python -m ruff check` over all touched files exits zero.
- `python -m ruff format --check` over all touched files exits zero.
- `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_collector_isolation tests.test_gate_orchestrator_g2_wiring tests.test_collector_checkout tests.test_collector_runner tests.test_system_gate tests.test_worktree_recovery tests.test_gate_orchestrator tests.test_audit_regression` exits zero.
- Full baseline (4,471 tests pre-G2) stays green; expect ~4550+ post-G2.
- `python -m coverage run --include="*/core/collector_isolation.py" -m unittest tests.test_collector_isolation && python -m coverage report --fail-under=90` exits zero.
- Import-allowlist grep on `collector_isolation.py`: zero `requests|httpx|aiohttp|multiprocessing|yaml`.
- `wc -l` on each new/modified module ≤ 500.
- `npm run verify` exits zero.

## 8. Frozen-gate-surface contract

1. **Six new optional kwargs across four functions:** `isolation_mode` + `max_workers` on `run_production_gate`, `run_system_gate`, `_run_collectors`, `run_gate_collectors`. Defaults preserve byte-identical behavior.
2. **Three new optional kwargs across two helper functions:** `name_hint` + `add_timeout` on `create_collector_checkout`; `per_unit_window_s` on `recover_orphan_worktrees`. Defaults preserve byte-identical behavior.
3. **No gate-file shape changes.** `make_gate_file` signature unchanged. `GateFileDeterminismBaseline` invariant unchanged.
4. **Mode-mode equivalence is CATEGORY-VERDICT-LEVEL, not byte-level.** `evidence_merkle_root`, `evidence_bundle_hash`, `duration_ms`, `cost_total_usd` differ between `shared` and `per_unit` BY DESIGN.
5. **No new persisted artifacts.** Per-unit worktrees live in `tempfile.gettempdir()`; the existing `worktree_recovery.recover_orphan_worktrees` janitor reaps orphans.
6. **No telemetry-event additions.** `core/telemetry_events.py` untouched.
7. **No new audit-floor invariant interactions.** The new `WorktreePerUnitIsolationInvariant` is additive; existing invariants stay green. Invariant count bumps from 10 → 11.
8. **`collector_checkout` context manager unchanged.** Only `create_collector_checkout` gains kwargs.

## 9. Adversarial review checklist (rev 2)

- **A-1 — Per-unit `git worktree add` is 1-3s × N collectors** (rev 1 was wrong about 200-500ms). Mitigation: `max_workers=4` parallelizes; `add_timeout=90s` accommodates contention; bounded retry on transient lock errors.
- **A-2 — Peak disk + RAM** (rev 2 expanded). 4 workers × ~50 MiB project tree + ~100 MiB subprocess RSS ≈ 600 MiB peak. `_clamp_max_workers` includes RAM-awareness (256 MiB per worker). Tmpfs `/tmp` is RAM-backed; operators on memory-constrained boxes can set `TMPDIR=/path/to/real-disk` or stay in `shared`.
- **A-3 — ThreadPoolExecutor exception handling.** `_run_isolated` catches `BaseException`; outcomes 1:1 with collectors; BaseException re-raised AFTER outcome collection.
- **A-4 — Per-worker checkout isolation is bounded** (rev 2 added — isolation_correctness lens). Each worker isolates the CWD only. Tools that write to `$HOME`, `/tmp/` outside the worktree, or system git config still share state. Documented as the realistic isolation envelope.
- **A-5 — `git worktree add` concurrency** (rev 2 corrected): does NOT contend on `index.lock` (rev 1 was factually wrong). The actual coordination points are `.git/worktrees/<name>/` mkdir (never collides via `tempfile.mkdtemp`) AND brief `.git/config.lock` contention. Empirically validated: 4-way concurrent `worktree add` succeeds. Tail-percentile spikes covered by retry-with-backoff (MED #2).
- **A-6 — `subprocess.run(cwd=)` thread safety.** Confirmed thread-local per Python docs. Audit-floor invariant pins no `os.chdir`.
- **A-7 — Audit `emit_gate_audit` thread safety + audit-lock contention** (rev 2 expanded). `AuditLog` uses filelock for chain integrity. With max_workers=4 and ~28 events per gate, expect ~10-50 ms cumulative lock-wait. Slow-disk events are caught as `AuditLockTimeout` specifically and retried once with 30s timeout before reifying as error.
- **A-8 — `persist_evidence_record` thread safety.** `write_atomic_text` + per-record filename. Verified.
- **A-9 — `run_collector_with_timeout` SIGKILL under threading.** psutil targets the specific subprocess via PID; thread-local.
- **A-10 — KeyboardInterrupt semantics** (rev 2 rewritten). Python delivers SIGINT to MAIN thread only; workers never receive KeyboardInterrupt. `run_collectors_per_unit` catches KI, calls `pool.shutdown(wait=False, cancel_futures=True)` (drains queue), then re-raises. In-flight `subprocess.run` calls complete to their per-category timeout (worst case = `max(profile.timeouts.values())` = 600s for `performance`). Double Ctrl-C escalates to OS signal delivery.
- **A-11 — `max_workers=1000` defensively clamped.** No logging surface in v1; tests assert clamping (§7.5 sub-test 4).
- **A-12 — `max_workers=0` raises ThreadPoolExecutor.** Clamped to 1 at the boundary.
- **A-13 — Tests must not mutate real git state.** Every test uses synthesized git repo under `tempfile.TemporaryDirectory()`.
- **A-14 — Silent fallback if `collector_isolation.py` is missing.** Import is inside the `if isolation_mode == "per_unit":` branch; `ModuleNotFoundError` propagates loudly. Tested.
- **A-15 — Two gates concurrently on same project.** `.gate.lock` serializes; G2 unchanged.
- **A-16 — `_sanitize_name_hint("../etc/passwd")` whitelists `[A-Za-z0-9._-]`.** Path traversal dropped. Tested.
- **A-17 — Process-global mutation by future contributor breaks thread safety.** Audit-floor invariant rejects `os.chdir`, `os.environ` mutations, `signal.signal`, `get_gate_lock` acquisition.
- **A-18 — Symlink escape from per-unit checkout.** `validate_evidence_path_isolation` (existing M03 surface) catches evidence-path escapes. Checkout IS in `tempfile.gettempdir()`, outside the project root. But operator-committed symlinks INSIDE the worktree pointing back to the parent are a real risk class — documented as a known-bounded isolation envelope (A-4).
- **A-19 — `max_workers=4` default with 1 collector.** `ThreadPoolExecutor(max_workers=4)` running 1 task uses 1 worker; idle workers cheap. No regression.
- **A-20 — `isolation_mode="per_unit"` + `diff_categories={"correctness"}`.** Filter runs BEFORE dispatch. Tested.
- **A-21 — OOM mid-checkout.** RAM-aware clamp reduces likelihood; `tempfile.gettempdir()` env override documented.
- **A-22 — System-gate parity** (rev 2 added — integration lens HIGH #2). `run_system_gate` ALSO accepts the kwargs and forwards. AC-G-08 pins this.
- **A-23 — Worker thread name leaks across pool reuse** (rev 2 added — MED #4). `try/finally` save+restore. Tested.
- **A-24 — Long-prefixed collector ID disambiguation** (rev 2 added — MED #8). `_sanitize_name_hint` takes LAST 32 chars, preserving the disambiguating tail.
- **A-25 — Concurrent `git worktree remove --force` from worker cleanup.** Empirically safe; existing `cleanup_collector_checkout` swallows rare races. Janitor (`worktree_recovery`) reaps any leftover admin stubs.

## 10. Open questions

All 7 open questions from rev 1 are CLOSED in §13. No new opens introduced by rev 2 — every fold-in resolves to a single direction.

## 11. Milestone tag + commit plan

Branch: `bma-d/integration-all`.

Commits (Conventional Commits + `Generated-By: claude-opus-4-7` + `Co-Authored-By:` trailers):

1. **`feat(g2): collector_checkout name_hint + add_timeout + transient-lock retry`** — `collector_checkout.py` + extends `tests/test_collector_checkout.py`. Tag `compat-g2-checkout-kwargs`.
2. **`feat(g2): collector_isolation module — per-unit worktrees, bounded parallel, BaseException-safe`** — `core/collector_isolation.py` + `tests/test_collector_isolation.py`. Tag `compat-g2-isolation-module`.
3. **`feat(g2): collector_runner dispatch + early kwarg validation`** — `core/collector_runner.py` extensions + extends `tests/test_collector_runner.py`. Tag `compat-g2-runner-dispatch`.
4. **`feat(g2): orchestrator wiring (run_production_gate, _run_collectors, run_system_gate)`** — `core/gate_orchestrator.py` + `core/system_gate.py` + `tests/test_gate_orchestrator_g2_wiring.py` + extends `tests/test_system_gate.py`. Tag `compat-g2-orchestrator`.
5. **`feat(g2): worktree_recovery per_unit_window_s`** — `core/worktree_recovery.py` + extends `tests/test_worktree_recovery.py`. Tag `compat-g2-janitor`.
6. **`test(g2): WorktreePerUnitIsolationInvariant (4 sub-tests + meaningful positive-failure proof)`** — `tests/test_audit_regression.py`. Tag `compat-g2-invariant`.
7. **`docs(g2): changelog + frozen-gate-surface + CLAUDE.md`** — changelog at `docs/changelog/2026-06-24-g2-worktree-per-unit.md` + frozen-surface + CLAUDE.md updates (including audit-floor count bump 10 → 11). Tag `compat-g2-docs`.

Final close tag: `milestone-G2-worktree-per-unit`.

The user-requested `compat-g2-worktree-per-unit` tag maps to commit #2 (`compat-g2-isolation-module`) — that's the canonical per-unit landing.

**Stage dependency graph** (sequential — each stage's tests depend on the prior stage's code being in place):

```
1. checkout-kwargs ──> 2. isolation-module ──> 3. runner-dispatch ──> 4. orchestrator ──> 5. janitor ──> 6. invariant ──> 7. docs
                                                                          │
                                                                          └──> system_gate parity
```

## 12. Anti-goals

- Multi-process isolation.
- Per-call automatic janitor invocation.
- Configurable `MAX_PARALLEL_CEILING` per profile.
- Worker affinity.
- New audit events for per-unit telemetry.
- CLI flag surface.
- Auto-tuning `max_workers` based on observed runtimes.
- Reusing worktrees across collectors.
- Default flip `shared` → `per_unit`.
- RAM-based clamp emitting info-evidence (out of scope; tests assert clamping return only).
- Replacing the existing `worktree_recovery` janitor or auto-invoking it.

## 13. Open-question resolutions (author-confirmed defaults)

1. **No `GateIsolationSummary` audit event in v1.** Keeps `gate_audit.py` untouched.
2. **No `max_workers=None` auto-tune.** Explicit int default of 4.
3. **No cross-gate worktree cache.** Fresh checkout per gate — M03 §7 invariant.
4. **No default flip from `shared` → `per_unit`.** Operator-driven; future milestone.
5. **No CLI flag surface in v1.** Programmatic kwarg only.
6. **Yes — worker thread name set + RESTORE via try/finally.** §4 + AC-I-16 pin save+restore (rev 2 corrected from "first statement" to "save original first, restore in finally").
7. **No info-log on `_clamp_max_workers` truncation.** Tests assert clamping behavior; no info-log surface.

## 14. Gap report (rev 1 → rev 2 fold-in summary)

| Severity | Gap | Resolution |
|---|---|---|
| HIGH | AC-G-03 byte-identical claim false — per_unit changes `duration_ms` → `evidence_merkle_root` differs by design | §8.4 + AC-G-03 rewritten to CATEGORY-VERDICT equivalence; byte-identical is NOT a per_unit goal |
| HIGH | Two unwired call sites (`_run_collectors` wrapper + `run_system_gate`) | §4 architecture extended; §6 file table grows; AC-G-07 + AC-G-08 pin both |
| HIGH | Audit-floor scope too narrow (missed `os.environ`, `signal.signal`, `get_gate_lock`) + dispatch-shape exemption refactor-fragile | §7.5 sub-test 1 renamed `test_ast_no_process_global_state_mutation_in_isolation_module`; sub-test 2 uses refactor-tolerant pattern (handles `==`, `in {...}`, `match`, intermediate-variable) |
| HIGH | Vacuous positive-failure proof (C5 lesson repeated) | §7.5 sub-test 3 rewritten: inject synthetic call into stripped residual to make proof MEANINGFUL |
| HIGH | "OS-level temp cleanup handles orphans" is false (`worktree_recovery.py` exists) | §1 cites the janitor explicitly; §3 adds `per_unit_window_s` kwarg; §6 file table; AC-R-01..R-03 |
| HIGH | AC-D-04 "max_workers ignored in shared" has undefined semantics | §3 + §4 add `_validate_isolation_kwargs` called EARLY in BOTH modes; AC-V-01..V-03 + AC-D-04 |
| HIGH | KeyboardInterrupt / BaseException semantics mis-stated | §3 + §4 + A-10 rewritten with `pool.shutdown(wait=False, cancel_futures=True)` + worker-boundary BaseException catch + `as_completed` + re-raise after outcome collection |
| MED | A-5 wrong git lock claim | A-5 rewritten; `add_timeout` + transient-lock retry added |
| MED | os.chdir-only AST too narrow | Consolidated into HIGH #3 |
| MED | Thread name save+restore | §3 + §4 + AC-I-16; §13 row 6 corrected |
| MED | Stress test on 1-vCPU CI silently degrades | Test monkey-patches `os.cpu_count` to 32; AC-I-09 |
| MED | Audit-lock contention → spurious errors | `_run_isolated` catches `AuditLockTimeout` specifically + retry once; AC-I-15 |
| MED | OOM-kill mid-pool; RAM not in clamp | `_clamp_max_workers` is RAM-aware via psutil.virtual_memory; AC-I-17/18; TMPDIR escape documented in A-21 |
| MED | name_hint sanitize order + path pattern + truncation collision | sanitize-FIRST-truncate-SECOND order pinned; AC-I-02 path pattern uses `fnmatch`/glob; `_sanitize_name_hint` takes LAST 32 chars |
| LOW | `_clamp_max_workers` formula contradiction between §2 and §3 | Formula quoted identically in §3 + §4; AC-I-07/AC-I-19 pin |
| LOW | Concurrent `git worktree remove --force` not pinned | A-25 |
| LOW | §2 "no mutation" contradicts additive kwargs | §2 rewritten "no **breaking** change" |
| LOW | `Literal[…]` requires runtime import | §4 boxes show `from typing import Literal` at runtime; §6 LOC count includes import bump |
| LOW | `_IsolatedWorkUnit` dead code + §11 commit plan needs file lists | §5.2 deletes `_IsolatedWorkUnit`; §11 commit plan rewritten with explicit file lists per commit; audit-floor count = 11 in CLAUDE.md update |

---

**End of rev 2 spec.** Ready for the implementation workflow.
