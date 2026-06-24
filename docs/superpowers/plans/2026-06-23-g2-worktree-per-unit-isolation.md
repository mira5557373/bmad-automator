# G2 — Worktree-Per-Unit Isolation — Implementation Plan

> Source spec: `docs/superpowers/specs/2026-06-23-g2-worktree-per-unit-isolation-design.md` (rev 2 — post-adversarial-review).
> Branch: `bma-d/integration-all`. Conventional Commits + `Generated-By: claude-opus-4-7` + `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailers on every commit.
> No `--no-verify`, no `--amend`, no force-push, no worktree isolation.

## Hard constraints (CLAUDE.md)

- Python 3.11+; stdlib + `filelock` + `psutil` ONLY — no new deps.
- 500-LOC soft limit per Python module; sibling-split if approaching.
- ADDITIVE-only — defaults preserve byte-identical behavior at every wiring point.
- `core/telemetry_events.py` is FROZEN.
- `core/innovation/threshold_*.py` and `core/collector_isolation.py` may NOT acquire any `_bmad/*.lock`.
- Tests: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.<module>`.
- Lint/format: `python -m ruff check <paths>` + `python -m ruff format --check <paths>` exit zero.

## Stage dependency graph

```
  s1-checkout-kwargs ──> s2-isolation ──> s3-runner ──> s4-orchestrator ──> s5-janitor ──> s6-invariant ──> s7-docs
                                                            │
                                                            └──> system_gate parity
```

Each stage's agent reads the spec, implements only the scope below, runs targeted tests, commits, and tags.

---

## Stage 1 — `compat-g2-checkout-kwargs` — collector_checkout additive kwargs + retry

**Scope.** Modify `core/collector_checkout.py` per spec §3 (`add_timeout` row, `_sanitize_name_hint` row), §4 (collector_checkout box), §5.3, §7.4 (AC-C-01..AC-C-09).

**Public surface (additive).**
```python
def create_collector_checkout(
    project_root: str | Path,
    commit_sha: str,
    *,
    name_hint: str = "",
    add_timeout: int | None = None,
) -> Path:
```

**Internals.**
- `_sanitize_name_hint(hint: str) -> str` — sanitize FIRST (drop chars not in `[A-Za-z0-9._-]`), take LAST 32 chars of sanitized SECOND.
- `_is_transient_lock_error(stderr: str) -> bool` — regex match against `r"(could not lock|already locked|index\.lock|config\.lock|locked by another process)"` case-insensitive.
- `_TRANSIENT_LOCK_RE`, `_MAX_WORKTREE_ADD_ATTEMPTS = 3`, `_WORKTREE_ADD_BACKOFF_S = 0.05`.
- Bounded retry loop on `git worktree add`: on returncode!=0 with transient stderr, sleep + retry up to 3 attempts.

**Backward compat.** `name_hint=""` AND `add_timeout=None` → byte-identical to today. `collector_checkout` context manager unchanged.

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/collector_checkout.py` (modify, +28)
- `skills/bmad-story-automator/tests/test_collector_checkout.py` (extend, +90; ≥11 new tests covering AC-C-01..C-09)

**Quality gates.**
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/collector_checkout.py skills/bmad-story-automator/tests/test_collector_checkout.py
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_collector_checkout
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/collector_checkout.py \
        skills/bmad-story-automator/tests/test_collector_checkout.py
git commit -m "$(cat <<'EOF'
feat(g2): collector_checkout name_hint + add_timeout + transient-lock retry

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-g2-checkout-kwargs -m "..."
```

---

## Stage 2 — `compat-g2-isolation-module` — collector_isolation.py (THE canonical landing)

**Scope.** Implement `core/collector_isolation.py` per spec §3 (multiple rows), §4 (collector_isolation box), §5.1, §7.1 (AC-V-01..V-03, AC-I-01..I-22), §7.2 (≥22 tests).

**Public surface.**
- `IsolationMode = Literal["shared", "per_unit"]`
- `DEFAULT_MAX_WORKERS = 4`, `MAX_PARALLEL_CEILING = 16`, `ESTIMATED_PER_WORKER_BYTES = 256 * 1024 * 1024`, `ADD_TIMEOUT_PER_UNIT_S = 90`.
- `run_collectors_per_unit(project_root, gate_id, commit_sha, profile, collectors, *, max_workers=4, audit_policy=None, audit_path=None) -> list[CollectorOutcome]`
- `_validate_isolation_kwargs(isolation_mode, max_workers) -> None` — raises TypeError on non-int max_workers (excluding bool); raises ValueError on unknown isolation_mode.

**Internals.**
- `_run_isolated(config, project_root, gate_id, commit_sha, profile, audit_policy, audit_path) -> CollectorOutcome` — thread-name save+restore via try/finally; catches `AuditLockTimeout` specifically with retry-once; catches `Exception`; catches `BaseException` as `_crash_outcome`.
- `_create_unit_checkout(project_root, commit_sha, name_hint, add_timeout) -> Path` — delegates to `create_collector_checkout`.
- `_cleanup_unit_checkout(checkout, project_root) -> None` — best-effort; catches `OSError + RuntimeError`.
- `_clamp_max_workers(requested, project_root=None) -> int` — `cpu_ceiling = min(16, max(1, (os.cpu_count() or 4) - 2))`; `ram_ceiling = max(1, int(psutil.virtual_memory().available // ESTIMATED_PER_WORKER_BYTES))` with try/except defaulting to `cpu_ceiling`; `return max(1, min(requested, cpu_ceiling, ram_ceiling))`.
- `_sanitize_name_hint(hint)` — same as Stage 1's helper (consider re-importing or duplicating; recommend duplicate-with-doc-pointer to avoid Stage 2 → Stage 1 coupling).
- `_error_outcome`, `_crash_outcome`, `_audit_timeout_outcome` — mirror `collector_runner.py:158-179` error path; persist evidence; emit audit.

**run_collectors_per_unit algorithm (per §4 architecture).**
1. Clamp `max_workers`.
2. Build `future_to_config` dict + outcomes list + `_pending_baseexc=None`.
3. Try block:
   - `with ThreadPoolExecutor(max_workers=clamped, thread_name_prefix="sa-collector") as pool:`
     - Submit one future per collector.
     - `for fut in as_completed(future_to_config):`
       - Catch `BaseException` per-future; reify as `_crash_outcome`; capture KI/SystemExit into `_pending_baseexc`.
4. Catch `KeyboardInterrupt`: `pool.shutdown(wait=False, cancel_futures=True)`; set `_pending_baseexc=exc`.
5. Sort outcomes by `(category, collector_id)`.
6. If `_pending_baseexc is not None`: raise it.
7. Return outcomes.

**_run_isolated algorithm.**
1. `original = threading.current_thread().name; threading.current_thread().name = f"sa-isolated-{config.collector_id}"`
2. `checkout = None`
3. try: try-block-1 (checkout):
   - try `_create_unit_checkout(...)` → on `CollectorCheckoutError`: return `_error_outcome(...)`.
   - try-block-2 (collector + audit retry):
     - try: `return run_single_collector(...)`.
     - except `AuditLockTimeout`: retry once; on second timeout return `_audit_timeout_outcome`.
     - except `Exception` as exc: return `_crash_outcome`.
     - except `BaseException` as exc: return `_crash_outcome`.
   - finally:
     - if checkout is not None: `_cleanup_unit_checkout(checkout, project_root)`.
     - restore `threading.current_thread().name = original`.

**Tests (§7.2 — ≥22 tests).** Listed in spec §7.2 items 1-22.

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/innovation/...` — NO; this lives at `core/collector_isolation.py` (NOT under innovation/).
- `skills/bmad-story-automator/src/story_automator/core/collector_isolation.py` (new, ~320 LOC; ≤350)
- `skills/bmad-story-automator/tests/test_collector_isolation.py` (new, ~520 LOC; ≥22 tests)

**Quality gates.**
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/collector_isolation.py skills/bmad-story-automator/tests/test_collector_isolation.py
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_collector_isolation tests.test_collector_checkout
wc -l skills/bmad-story-automator/src/story_automator/core/collector_isolation.py  # ≤500
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/collector_isolation.py \
        skills/bmad-story-automator/tests/test_collector_isolation.py
git commit -m "$(cat <<'EOF'
feat(g2): collector_isolation module — per-unit worktrees, bounded parallel, BaseException-safe

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-g2-isolation-module -m "..."
```

---

## Stage 3 — `compat-g2-runner-dispatch` — collector_runner extension

**Scope.** Modify `core/collector_runner.py` per spec §3 (`Dispatch` row, `Early kwarg validation` row), §4 (collector_runner box), §7.1 (AC-D-01..D-04), §7.5 (default-pinning AC).

**Changes.**
- Add two new kwargs to `run_gate_collectors`: `isolation_mode: Literal["shared","per_unit"] = "shared"`, `max_workers: int = 4`.
- Add early validation: import `_validate_isolation_kwargs` from `.collector_isolation` and call FIRST (before `assert_host_context`).
- After filtering (`registry.applicable` + `diff_categories`), add one-line dispatch: `if isolation_mode == "per_unit": return run_collectors_per_unit(...)`. The shared path that follows is UNTOUCHED.
- Add `Literal` to the existing `from typing import Any` import.

**Tests (extend `tests/test_collector_runner.py`, +~60 LOC).**
- Invalid `isolation_mode` raises `ValueError` BEFORE `assert_host_context` (mock the host check, assert it isn't called).
- `max_workers="four"` raises `TypeError` in BOTH `shared` AND `per_unit` modes.
- `max_workers=True` (bool) raises `TypeError`.
- `isolation_mode="per_unit"` reaches `run_collectors_per_unit` (mock the isolation runner; assert called with the right args).
- `isolation_mode="shared"` (default) → existing path runs (mock `collector_checkout`, assert called once).

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/collector_runner.py` (modify, +12)
- `skills/bmad-story-automator/tests/test_collector_runner.py` (extend, +60)

**Quality gates.**
```
python -m ruff check ... 
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_collector_runner tests.test_collector_isolation tests.test_collector_checkout
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/collector_runner.py \
        skills/bmad-story-automator/tests/test_collector_runner.py
git commit -m "$(cat <<'EOF'
feat(g2): collector_runner dispatch + early kwarg validation

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-g2-runner-dispatch -m "..."
```

---

## Stage 4 — `compat-g2-orchestrator` — run_production_gate + run_system_gate + _run_collectors

**Scope.** Modify `core/gate_orchestrator.py` AND `core/system_gate.py` per spec §3 (`Where the new kwargs live` row), §4 (gate_orchestrator + system_gate boxes), §7.1 (AC-G-01..G-09).

**`gate_orchestrator.py` changes.**

(a) `_run_collectors` wrapper at `gate_orchestrator.py:581` gains two kwargs:
```python
def _run_collectors(
    project_root, gate_id, commit_sha, profile, registry,
    *, diff_categories=None,
    audit_policy=None, audit_path=None,
    isolation_mode: Literal["shared", "per_unit"] = "shared",
    max_workers: int = 4,
) -> list[Any]:
    return run_gate_collectors(
        project_root, gate_id, commit_sha, profile, registry,
        diff_categories=diff_categories,
        audit_policy=audit_policy, audit_path=audit_path,
        isolation_mode=isolation_mode,
        max_workers=max_workers,
    )
```

(b) `run_production_gate` gains two kwargs (matching defaults). Validation block early. Call site at line ~825 already calls `_run_collectors`; just thread the new kwargs.

**`system_gate.py` changes.**

`run_system_gate` (around line 51) gains two kwargs (matching defaults). Validation block early. The collector call site inside the function passes the kwargs through to `run_gate_collectors`. READ the function body first to find the exact call site.

**Tests** in NEW file `tests/test_gate_orchestrator_g2_wiring.py` (~240 LOC, ≥10 tests covering AC-G-01..G-09). PLUS extend `tests/test_system_gate.py` (+50 LOC) for AC-G-08 system-gate parity.

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` (modify, +14)
- `skills/bmad-story-automator/src/story_automator/core/system_gate.py` (modify, +10)
- `skills/bmad-story-automator/tests/test_gate_orchestrator_g2_wiring.py` (new, ~240)
- `skills/bmad-story-automator/tests/test_system_gate.py` (extend, +50)

**Quality gates.**
```
python -m ruff check ...
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest \
    tests.test_gate_orchestrator_g2_wiring tests.test_system_gate \
    tests.test_collector_runner tests.test_collector_isolation \
    tests.test_collector_checkout tests.test_gate_orchestrator tests.test_audit_regression
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py \
        skills/bmad-story-automator/src/story_automator/core/system_gate.py \
        skills/bmad-story-automator/tests/test_gate_orchestrator_g2_wiring.py \
        skills/bmad-story-automator/tests/test_system_gate.py
git commit -m "$(cat <<'EOF'
feat(g2): orchestrator wiring (run_production_gate, _run_collectors, run_system_gate)

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-g2-orchestrator -m "..."
```

---

## Stage 5 — `compat-g2-janitor` — worktree_recovery per_unit_window_s

**Scope.** Modify `core/worktree_recovery.py` per spec §3 (`Janitor extension` row), §5.4, §7.1 (AC-R-01..R-03).

**Changes.**
- Add `per_unit_window_s: float = 0.0` kwarg to `recover_orphan_worktrees`.
- Compute `effective_min_age = max(min_age_s, per_unit_window_s)`.
- Use `effective_min_age` instead of `min_age_s` in the scratch-dir sweep.

**Tests (extend `tests/test_worktree_recovery.py`, +40 LOC).**
- Default `per_unit_window_s=0.0` → byte-identical to today.
- `per_unit_window_s=120.0` with `min_age_s=60.0` → effective threshold 120s.
- `per_unit_window_s=10.0` with `min_age_s=3600.0` → effective threshold stays 3600s.

**Files.**
- `skills/bmad-story-automator/src/story_automator/core/worktree_recovery.py` (modify, +18)
- `skills/bmad-story-automator/tests/test_worktree_recovery.py` (extend, +40)

**Quality gates.**
```
python -m ruff check ...
python -m ruff format --check ...
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_worktree_recovery
```

**Commit + tag.**
```
git add skills/bmad-story-automator/src/story_automator/core/worktree_recovery.py \
        skills/bmad-story-automator/tests/test_worktree_recovery.py
git commit -m "$(cat <<'EOF'
feat(g2): worktree_recovery per_unit_window_s safety margin

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-g2-janitor -m "..."
```

---

## Stage 6 — `compat-g2-invariant` — WorktreePerUnitIsolationInvariant

**Scope.** Add `WorktreePerUnitIsolationInvariant` class to `tests/test_audit_regression.py` per spec §7.5 with FOUR sub-tests.

### Sub-test 1: `test_ast_no_process_global_state_mutation_in_isolation_module`

Walks `core/collector_isolation.py`. Rejects ALL of:
- `Call(func=Attribute(value=Name("os"), attr in {"chdir","fchdir","umask","setpgrp","setsid","setgid","setuid","setresgid","setresuid"}))`
- `Subscript(value=Attribute(value=Name("os"), attr="environ"))` as `targets` of `Assign|AnnAssign|AugAssign` OR as a `Delete` target
- `Call(func=Attribute(value=Attribute(value=Name("os"), attr="environ"), attr in {"update","pop","clear","setdefault","__setitem__","__delitem__"}))`
- `Call(func=Name("signal"))` OR `Call(func=Attribute(value=Name("signal"), attr="signal"))`
- `Call(func=Name("get_gate_lock"))` OR `Call(func=Attribute(attr="get_gate_lock"))`

Positive-failure proof: synthetic AST with each violation pattern → flagged.

### Sub-test 2: `test_ast_no_implicit_per_unit_dispatch_outside_isolation`

Walks BOTH `core/` AND `commands/`. Structural exemption:
- `_defines_isolation_runner(tree)`: top-level body defines `def run_collectors_per_unit(...)` → skip.
- `_dispatches_via_isolation_mode(tree)`: top-level function named `run_gate_collectors` whose body contains an `If` whose `test` references `Name("isolation_mode")` AND whose comparators (within `BoolOp`, `In`, `Compare`, `Match` cases) include `Constant("per_unit")` → exempt the dispatch site Call.

Binding-tracking:
- `from ... import run_collectors_per_unit as ALIAS` → ALIAS forbidden. Handles parenthesized form `from X import (run_collectors_per_unit as alias,)`.
- `Assign(targets=[Name(LHS)], value=Name("run_collectors_per_unit"))` → LHS forbidden.
- `AnnAssign(target=Name(LHS), value=Name("run_collectors_per_unit"))` → LHS forbidden (C5 post-impl lesson).
- Flag `Call(func=Name(N))` with N in forbidden set.
- Flag `Call(func=Attribute(attr="run_collectors_per_unit"))`.
- Flag `getattr(_, "run_collectors_per_unit")` and `importlib.import_module(...).run_collectors_per_unit`.

### Sub-test 3: `test_positive_failure_synthetic_violator_is_caught`

MEANINGFUL two-direction proof (C5 post-impl review lesson):
- (a) Synthetic source with direct call + alias rebinding + AnnAssign rebinding + getattr + importlib — ALL flagged.
- (b) Strip the `def run_collectors_per_unit` exemption-defining FunctionDef from `collector_isolation.py` AND INJECT a synthetic `_residual_check = run_collectors_per_unit; _residual_check(...)` call into the residual → walker MUST flag it. (Avoids vacuous true.)

### Sub-test 4: `test_default_isolation_mode_is_shared`

Pins defaults at FOUR sites:
```python
for fn in (run_gate_collectors, run_production_gate, _run_collectors, run_system_gate):
    sig = inspect.signature(fn)
    assert sig.parameters["isolation_mode"].default == "shared", fn
    assert sig.parameters["max_workers"].default == 4, fn
```

**Files.**
- `tests/test_audit_regression.py` (modify, +260 LOC)

**Quality gates.**
```
python -m ruff check tests/test_audit_regression.py
python -m ruff format --check tests/test_audit_regression.py
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_regression
```

**Commit + tag.**
```
git add tests/test_audit_regression.py
git commit -m "$(cat <<'EOF'
test(g2): WorktreePerUnitIsolationInvariant (4 sub-tests + meaningful positive-failure proof)

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-g2-invariant -m "..."
```

---

## Stage 7 — `compat-g2-docs` — changelog + frozen-surface + CLAUDE.md

**Scope.**

(a) `docs/changelog/2026-06-24-g2-worktree-per-unit.md` (~60 LOC, `[FULL]` tag). Heading: `## 260624 - [FULL] G2 worktree-per-unit isolation` (verify date format against neighbors via `ls docs/changelog/ | grep 26062`).

(b) `docs/spec/frozen-gate-surface.md` (+32 LOC): new `### core/collector_isolation.py` section listing the public surface + behavioral invariants (advisory-only-byte-equivalence-on-shared-mode, BaseException re-raised after outcomes, KeyboardInterrupt drains queue, audit-lock retry, lock-isolation).

(c) `CLAUDE.md` (+24 LOC): new "Worktree-per-unit isolation (G2)" subsection under "Recently shipped (session 2026-06-23/24)"; update "additive kwargs (cumulative)" list to add `isolation_mode` + `max_workers` as kwargs #8 and #9; bump audit-floor invariant count from 10 → 11.

**Files.**
- `docs/changelog/2026-06-24-g2-worktree-per-unit.md` (new, ~60)
- `docs/spec/frozen-gate-surface.md` (modify, +32)
- `CLAUDE.md` (modify, +24)

**Quality gates.** No Python tests (docs only). Verify no trailing whitespace per CLAUDE.md hard guardrail.

**Commit + tag.**
```
git add docs/changelog/2026-06-24-g2-worktree-per-unit.md \
        docs/spec/frozen-gate-surface.md \
        CLAUDE.md
git commit -m "$(cat <<'EOF'
docs(g2): changelog + frozen-gate-surface + CLAUDE.md

Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git tag -a compat-g2-docs -m "..."
```

---

## Verification appendix

```bash
npm run verify
```

(ruff + 4471+ unittest + npm pack dry-run + CLI smoke + bash smoke-test).

Targeted:
```
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_audit_regression -v
PYTHONPATH=skills/bmad-story-automator/src python -m unittest \
    tests.test_collector_checkout tests.test_collector_isolation tests.test_collector_runner \
    tests.test_gate_orchestrator_g2_wiring tests.test_system_gate tests.test_worktree_recovery -v
```

Baseline pre-G2: 4,471 tests. Expected post-G2: ~4,560-4,600.

## Push plan

```bash
git tag -a milestone-G2-worktree-per-unit -m "G2 worktree-per-unit isolation — per-collector worktree + bounded parallel"
git tag --list 'compat-g2-*' milestone-G2-worktree-per-unit
git push origin bma-d/integration-all
git push origin --tags
```

No `--force`. No `--no-verify`.

## Risk register

| Risk | Mitigation |
|---|---|
| Stage 2 imports `AuditLockTimeout` which may have circular-import implications. | Import lazily inside `_run_isolated` if needed. |
| Stage 3's dispatch shape locks the AST invariant pattern in Stage 6 — they must agree. | Stage 6 follows Stage 3 in the dependency graph; agent reads stage-3 commit before designing the invariant matcher. |
| Stage 4's system_gate has its own gate-lock acquisition; the new kwargs must not interact with it. | Validate kwargs BEFORE acquiring the lock. AC-G-04 tests this. |
| `psutil.virtual_memory()` may not be available on some platforms. | `_clamp_max_workers` catches all exceptions and defaults `ram_ceiling = cpu_ceiling`. |
| Stage 6 invariant over-fires on existing code. | Run baseline `tests.test_audit_regression` BEFORE adding new class; verify only the new class adds test methods. |
| `ruff` complains about `Literal[...]` import that wasn't there before. | Add `from typing import Any, Literal` (or extend the existing import). Stage 3 + 4 both must do this. |
| LOC budget overrun for `collector_isolation.py`. | Pre-authorized sibling split into `core/collector_isolation_workers.py` if approaching 500 LOC; defer per main agent's discretion in Stage 2. |
