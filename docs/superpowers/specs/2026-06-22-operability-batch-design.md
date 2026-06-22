# Operability Batch — Design Spec

> Date: 2026-06-22 · Status: **Draft for implementation** · Milestone: **B (Operability)** · Owner branch: `bma-d/integration-all`.
> Topic: ship three small, surgical fixes that harden gate-lifecycle operability — (B1) PID-reuse hardening on marker liveness, (B2) lock-holder observability on contended `get_gate_lock`, (B3) a project-level pre-commit gate that runs the full unittest suite + ruff.
> Validation provenance: targeted bug-sweep follow-ups from the round-2 audit (`docs/audit/round-2-bug-sweep.md`) and prior L1/L2 follow-ups (`.claude/workflows/l1-l2-gate-marker-fix.md`, `.claude/workflows/l1-followup-system-gate.md`). All three sub-fixes are additive on a frozen-gate-surface codebase: no public symbol moves, no telemetry shape change, no new Python deps.

## 1. Goal

Tighten three operability gaps that round-2 review left as known-but-survivable:

1. **B1 — PID-reuse hardening.** The marker liveness check today already records `start_time` (psutil `create_time()`) and compares it against the live PID's `create_time()` with a 1.0s tolerance (`_recover_from_crash_locked`, lines 217-227 of `gate_orchestrator.py`). Markers written **before** that fix landed, however, may carry `started_at` (ISO timestamp recorded at marker-write) but no `start_time` (float) — and the audit noted that the `started_at` field is unused by the liveness path. B1 widens the liveness check so it also consults `started_at` against the live PID's `create_time()` when `start_time` is absent, *closing* the legacy-marker PID-reuse window without breaking the existing fast-path.
2. **B2 — Lock-holder observability.** When `get_gate_lock(...).acquire(timeout=…)` times out, the raised `filelock.Timeout` says nothing about *who* holds the lock. Operators today must `lsof` / `fuser` / `ps` from another shell. B2 raises a new `GateLockTimeoutError(filelock.Timeout)` subclass (gap B-H1, B-L6) carrying explicit `holder` + `timeout_s` attributes and a clean `__str__` — at **all three** `get_gate_lock` call sites: `gate_orchestrator.py:291`, `gate_orchestrator.py:527`, and `system_gate.py:71` (gap B-H2). Existing `except filelock.Timeout:` callers still match by inheritance. No new control flow, no new failure mode.
3. **B3 — Pre-commit full-suite gate.** Round-2 caught two bugs that would have been blocked by a pre-commit gate (D-04 audit-key env leak shipped through CI; lock-holder visibility went un-noticed for a sprint). B3 installs a project-local pre-commit hook that runs the full `unittest` discover + `ruff check` and a one-time installer (`scripts/install-hooks.sh`) that sets `core.hooksPath` to the project's `.githooks/`. The hook respects the standard `git commit --no-verify` escape with a loud `stderr` warning so emergency commits aren't blocked.

The batch is intentionally small. No new modules; only extensions to two existing modules, two new tiny shell artifacts, and three new test files.

## 2. Decisions captured

| Decision | Choice |
|---|---|
| Combine B1+B2+B3 into one milestone? | Yes — all three are pure operability, none touches frozen-gate-surface symbols, all three land independent test files. One PR is cheaper to review than three. |
| Add a new Python dep? | **No** — `psutil` already imported by `evidence_io.py` and `gate_orchestrator.py`; `filelock.Timeout` already imported via `filelock`. B3 hook is plain shell. |
| Change a telemetry event shape? | **No** — B2's log line is a `stderr` print, not an event. `telemetry_events.py` is **not touched** (M01 owns that file; CLAUDE.md guardrail). |
| Modify the gate-marker JSON schema? | **No** — `started_at` is already in the marker payload (`evidence_io.write_gate_marker` line 326). B1 only *consumes* that field that today is recorded-but-unused. |
| Hook installer policy | Opt-in via `scripts/install-hooks.sh`; never auto-installed by `npm install` or `install.sh`. Operators on Windows git-bash, WSL, and Linux CI all see the same script. `core.hooksPath` is *project-local* — the user-global `~/.gitconfig` is never touched. |
| `--no-verify` semantics | Honored. Hook never runs when `--no-verify` is passed (`git` short-circuits before invoking the hook). When the hook *does* run and the user wants to skip a single test run, they use `--no-verify` explicitly. The hook itself prints a one-line `stderr` warning if it detects the environment variable `BMAD_SKIP_PRECOMMIT=1`, but the *real* escape hatch is `--no-verify` (git-native, no custom plumbing). |
| Liveness check on B1 — what about hosts where `psutil.Process(pid).create_time()` can't be read? | Conservative: treat as **live** (fail-closed; don't wipe evidence). This matches the existing branch in `_recover_from_crash_locked` lines 222-227. |
| Legacy markers (no `started_at` *and* no `start_time`) | Fall through to existing `psutil.pid_exists(pid)`-only path (back-compat with markers written before the B1 fix). |

## 3. Architecture

```
B1  evidence_io.write_gate_marker (already records started_at + start_time)
      │
      ▼
    gate_orchestrator._recover_from_crash_locked
      │  L1: pid_exists alone   (legacy fallback)
      │  L1+: pid_exists ∧ start_time ≈ create_time()      (current fix)
      │  B1:  pid_exists ∧ started_at ≈ create_time()      (NEW — closes the legacy-marker gap)
      ▼
    {recovered: True/False, reason}

B2  evidence_io.read_gate_marker  (returns dict | None | raises GateMarkerCorrupted)
      │
      ▼
    evidence_io.describe_lock_holder(project_root) -> dict | None      (NEW small helper, ≤30 LOC)
      │
      ▼
    gate_orchestrator: any caller of get_gate_lock(root, timeout=…)
      │  on filelock.Timeout:
      │    holder = describe_lock_holder(root)
      │    log "gate lock held by PID=<n>, started_at=<iso>, waiting since <iso>"
      │    re-raise filelock.Timeout with augmented args
      ▼
    operator sees holder identity instead of opaque timeout

B3  .githooks/pre-commit                 (NEW — shell)
      │  PYTHONPATH=skills/.../src python3 -m unittest discover -s tests
      │  ruff check
      ▼
    scripts/install-hooks.sh             (NEW — one-shot: git config core.hooksPath .githooks)
      │
      ▼
    CONTRIBUTING.md (note appended)      (mention `git config core.hooksPath .githooks` + --no-verify escape)
```

- **B1 + B2** are pure additions in `core/evidence_io.py` + `core/gate_orchestrator.py`. Both touched files are well under 500 LOC; B1 adds ~12 LOC, B2 adds ~25 LOC (helper + augmentation), well inside the soft limit.
- **B3** is shell-only and lives outside `skills/bmad-story-automator/` (it's a repo-level developer ergonomic, not a runtime artifact). No npm package payload change.

## 4. Schemas (compact)

- **B1 — composite liveness rule (additive)** — *re-derived per gap B-H4*: the legacy-marker fallback branch is **scoped down** because the prior 5.0s tolerance was justified by a reversed cause-and-effect ("GC pause between marker statements"), but in reality `psutil.Process().create_time()` returns the start of the *current* Python process — which has typically been alive for seconds-to-minutes before `write_gate_marker` runs — while `marker.started_at` is the wall-clock at marker-write. The gap between the two is the orchestrator's uptime, NOT a sub-second GC pause, so a tight `< 5.0s` tolerance would falsely flag every legacy marker recorded more than 5s after process-start as "PID reused" (≈ every real-world marker).

  **Re-derived rule (B1 v2):** When `marker.start_time` is absent AND `marker.started_at` is present (ISO8601 from `iso_now()`), validate liveness via a TWO-SIDED bound:
  ```
  proc_start = psutil.Process(pid).create_time()
  started_at_epoch = datetime.fromisoformat(
      marker["started_at"].replace("Z", "+00:00")
  ).timestamp()

  # Lower bound: the live process must have existed when the marker was stamped.
  # We allow up to 1.0s of skew to cover iso_now() truncation (it returns
  # second-precision UTC per core/utils.py::iso_now, so the recorded value can
  # be up to 1.0s earlier than the actual wall-clock moment).
  #
  # Upper bound: the live process must NOT have started so far before the marker
  # that PID-reuse is plausible. We bound by MAX_ORCHESTRATOR_UPTIME_S = 86400.0
  # (24h — orchestrator processes are not meant to live longer than a day; a
  # PID seen alive for >24h with no marker is strong evidence of recycling).
  ISO_TRUNCATION_S = 1.0
  MAX_ORCHESTRATOR_UPTIME_S = 86400.0
  if proc_start > started_at_epoch + ISO_TRUNCATION_S:
      # Live PID started AFTER the marker was stamped → reuse.
      alive = False
  elif proc_start < started_at_epoch - MAX_ORCHESTRATOR_UPTIME_S:
      # Live PID started >24h before the marker → almost certainly recycled.
      alive = False
  ```
  Worked example: a marker stamped at `T=1000.0`, with a live process whose `create_time()` is `T=950.0` (50s before marker, well within 24h) → alive (correct: same long-lived orchestrator). A live process whose `create_time()` is `T=1500.0` (after marker) → dead (correct: PID reused). A live process whose `create_time()` is `T=-100000.0` (>24h before marker) → dead (correct: PID recycled across orchestrator restart).

  The previous `< 5.0s` tolerance is **dropped**. Tests must exercise both boundaries (B-L2 plus a new boundary-condition test set for ISO_TRUNCATION_S and MAX_ORCHESTRATOR_UPTIME_S).
- **B2 — `_describe_lock_holder` return shape** (private helper; see B-H5): `dict | None`. When marker is present and well-formed: `{"pid": int, "started_at": str, "hostname": str}` — a subset of the marker. When marker is absent: returns a sentinel `{"_state": "missing"}` (caller's message: `holder unknown (marker missing — holder may have just released the lock)`). When marker is corrupted (parse error in `read_gate_marker`): returns `{"_state": "corrupt"}` (caller's message: `holder unknown (marker present but unparseable)`). Distinguishing these two cases addresses gap B-M6. The helper **does not raise** — observability code must never amplify a primary failure.
- **B2 — `GateLockTimeoutError(filelock.Timeout)` exception class** (replaces "augmented Timeout message" — gap B-H1). Defined in the new sibling module `core/gate_lock_observability.py` (gap B-H6 — keeps `gate_orchestrator.py` from growing further):
  ```python
  class GateLockTimeoutError(Timeout):
      """filelock.Timeout subclass carrying holder identity for operability."""
      def __init__(self, lock_file: str, *, holder: dict | None, timeout: float) -> None:
          super().__init__(lock_file)
          self.holder = holder
          self.timeout_s = timeout
      def __str__(self) -> str:
          if self.holder and self.holder.get("_state") not in ("missing", "corrupt"):
              return (f"gate lock at {self.lock_file} not acquired within "
                      f"{self.timeout_s}s; held by PID={self.holder['pid']}, "
                      f"started_at={self.holder['started_at']}, "
                      f"host={self.holder.get('hostname','')}")
          if self.holder and self.holder.get("_state") == "missing":
              return (f"gate lock at {self.lock_file} not acquired within "
                      f"{self.timeout_s}s; holder unknown (marker missing — "
                      f"holder may have just released the lock)")
          if self.holder and self.holder.get("_state") == "corrupt":
              return (f"gate lock at {self.lock_file} not acquired within "
                      f"{self.timeout_s}s; holder unknown (marker present but unparseable)")
          return (f"gate lock at {self.lock_file} not acquired within "
                  f"{self.timeout_s}s; holder unknown")
  ```
  Subclassing `filelock.Timeout` keeps existing `except filelock.Timeout:` callers matching by inheritance; `exc.lock_file` still holds the lock path (NOT a free-form prose message — gap B-H1). The new attributes `holder` and `timeout_s` are stable observability surface and must be declared in `docs/spec/frozen-gate-surface.md`.
- **B3 — pre-commit hook contract**: exit 0 on success, exit non-zero on test or lint failure; honors `git commit --no-verify` by not running at all; prints `>>> BMAD pre-commit gate <<<` banner on `stderr` so the operator knows where slowdown comes from; prints `>>> SKIPPING: BMAD_SKIP_PRECOMMIT=1 set in env <<<` on `stderr` when the env var is set and exits 0 (developer ergonomic escape for repeated rebases).

## 5. Implementation surface — files

| File | New / Modified | LOC delta | Notes |
|---|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/gate_lock_observability.py` | **New (sibling module — gap B-H6)** | ~40 | hosts `GateLockTimeoutError(filelock.Timeout)` + `_describe_lock_holder(project_root)` + `_handle_gate_lock_timeout(project_root, lock_path, timeout, exc) -> NoReturn` helper (gap B-M7: shared timeout-handling helper used at all three call sites to prevent augmentation drift). All symbols are leading-underscore private to keep frozen-gate-surface footprint minimal. |
| `skills/bmad-story-automator/src/story_automator/core/evidence_io.py` | Modified | +6 | only re-exports `_describe_lock_holder` as `describe_lock_holder` IF observability needs to widen outside `core/`; otherwise zero diff. Read path of `read_gate_marker` unchanged. |
| `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` | Modified | +6 | wraps **two** existing `get_gate_lock(...)` call sites (lines 291, 527) in `try: ... except Timeout as exc: _handle_gate_lock_timeout(...)`. B1: extend `_recover_from_crash_locked` liveness branch to also accept `started_at` per the v2 rule in §4 (~+12 LOC; total +18 LOC). |
| `skills/bmad-story-automator/src/story_automator/core/system_gate.py` | **Modified (gap B-H2 — missed call site)** | +6 | wraps the third `get_gate_lock(project_root, timeout=3600.0)` call site at line 71 in the same `try/except` handler. Imports `_handle_gate_lock_timeout` from the new sibling module. |
| `docs/spec/frozen-gate-surface.md` | **Modified (gap B-H5)** | +6 | declares `GateLockTimeoutError` (+ its `holder` and `timeout_s` attributes) under a new `### core/gate_lock_observability.py` section. Existing `core/evidence_io.py` section is unchanged unless `describe_lock_holder` is promoted (otherwise the helper stays underscore-private). |
| `.githooks/pre-commit` | New | ~50 | bash; runs unittest discover + ruff + **`bash scripts/m11-vocabulary-gates.sh`** (gap B-M4); honors `BMAD_SKIP_PRECOMMIT=1`; portability hardened per B-M2/B-M3 (probe `python3 \|\| python \|\| py`; PYTHONPATH preserved with `${PYTHONPATH:+:$PYTHONPATH}`; prefer `${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/}ruff`); `set -euo pipefail`. |
| `scripts/install-hooks.sh` | New | ~30 | bash; `git config core.hooksPath .githooks`; verifies `.githooks/pre-commit` is executable; captures and prints prior `core.hooksPath` if set (gap B-L7). |
| `scripts/uninstall-hooks.sh` | **New (gap B-M5)** | ~15 | bash; `git config --unset core.hooksPath`. Documented in CONTRIBUTING.md so devs who delete `.githooks/` can recover. |
| `CONTRIBUTING.md` | Modified or new | +25 | append a "Pre-commit hook (optional but recommended)" section; reference install + uninstall scripts + `BMAD_SKIP_PRECOMMIT=1` + direnv note (gap B-L5). |
| `tests/test_bugfix_L1_pid_reuse.py` | New | ~140 | 4 base tests + 2 boundary tests (ISO_TRUNCATION_S and MAX_ORCHESTRATOR_UPTIME_S boundaries) + 1 zombie-PID test (gap B-M1) + 2 back-compat tests (gap B-L2 `start_time`+`started_at` precedence, B-L3 foreign-host short-circuit). See §6. |
| `tests/test_lock_holder_observability.py` | New | ~110 | 3 base tests + 1 `run_system_gate` timeout test (gap B-H2). See §6. |
| `tests/test_pre_commit_hook.py` | New | ~80 | 3 tests + portability assertions per gap B-M9 (`stat().st_mode & stat.S_IXUSR` instead of bare `os.access(X_OK)`). See §6. |

Total LOC delta ≈ +450, of which ~330 is tests. The new sibling module `core/gate_lock_observability.py` (~40 LOC) keeps `gate_orchestrator.py` from growing past its current 718 LOC (verified by `wc -l` at HEAD — see §11; the prior "~640" claim was wrong). With the extract, `gate_orchestrator.py`'s net delta is +6 LOC (one try/except per call site × 2 sites + a couple of import lines).

## 6. Acceptance criteria

### 6.1 Behavioral

**B1 — PID-reuse hardening**
- Marker with `pid` + `started_at` (no `start_time`) and a *live* process whose `create_time()` matches `started_at` within 5.0s → liveness = **live** → `recover_from_crash` returns `{"recovered": False, "reason": "live-pid-still-running"}`.
- Same marker shape, but the live process's `create_time()` differs from `started_at` by more than 5.0s → liveness = **dead (PID reused)** → recovery proceeds, evidence dir is cleaned, marker is cleared.
- Marker has neither `start_time` nor `started_at` (legacy from pre-B1 era) → fall through to existing `psutil.pid_exists(pid)` path (back-compat).
- `psutil.Process(pid).create_time()` raises `psutil.AccessDenied` mid-check → liveness = **live** (conservative fail-closed; existing behavior, preserved).

**B2 — Lock-holder observability**
- `get_gate_lock(...).acquire(timeout=0.1)` against a held lock raises `filelock.Timeout` with a message containing `pid=`, `started_at=`, `host=` *when marker is well-formed*.
- Same scenario but marker is missing → raised error message contains `holder unknown` and does **not** crash.
- Same scenario but marker is corrupted (parse error in `read_gate_marker`) → raised error message contains `holder unknown` and the helper itself swallows the corruption (orchestrator's separate quarantine path still handles it).

**B3 — Pre-commit full-suite gate**
- `.githooks/pre-commit` exists and is executable (`os.access(path, os.X_OK)` true).
- File contents include the literal substrings `python3 -m unittest discover -s tests` and `ruff check`.
- File contents include the literal substring `BMAD_SKIP_PRECOMMIT` (escape-hatch detection).
- `scripts/install-hooks.sh` exists and is executable; contents include `git config core.hooksPath .githooks`.

### 6.2 Test coverage

Minimum **14 new tests** across three files (was 10 — expanded per gap report HIGH + MED additions):

1. `tests/test_bugfix_L1_pid_reuse.py` — **7 tests** (4 base + 1 zombie B-M1 + 2 back-compat B-L2/B-L3; boundary tests for the v2 rule's two-sided bound replace the prior "mismatching by 5.0s" test)
   - `test_marker_with_started_at_within_iso_truncation_treated_as_live` (lower-bound: proc_start within ISO_TRUNCATION_S of marker → live)
   - `test_marker_with_proc_start_after_marker_treated_as_dead` (upper-bound on lower side: proc_start > started_at_epoch + ISO_TRUNCATION_S → reuse)
   - `test_marker_with_proc_start_far_before_marker_treated_as_dead` (upper bound: proc_start < started_at_epoch - MAX_ORCHESTRATOR_UPTIME_S → recycled)
   - `test_marker_without_started_at_or_start_time_falls_back_to_pid_exists` (back-compat)
   - `test_create_time_unreadable_treated_as_live_conservative` (fail-closed)
   - `test_zombie_pid_treated_as_dead` (gap B-M1 — `psutil.ZombieProcess` subclass of `NoSuchProcess`; PID slot no longer holding gate state)
   - `test_marker_with_both_start_time_and_started_at_prefers_start_time` (gap B-L2 — post-J-03 fast-path still wins; B1 fallback only fires on legacy markers)
   - `test_foreign_host_marker_skips_b1_started_at_check` (gap B-L3 — composite-identity short-circuits before B1 branch)

2. `tests/test_lock_holder_observability.py` — **4 tests** (gap B-H2 added the system_gate one)
   - `test_lock_timeout_includes_holder_pid_and_started_at`
   - `test_lock_timeout_with_missing_marker_reports_holder_unknown` (asserts message contains `"marker missing — holder may have just released the lock"` per gap B-M6)
   - `test_describe_lock_holder_swallows_marker_corruption` (asserts message contains `"marker present but unparseable"`)
   - `test_run_system_gate_lock_timeout_includes_holder` (gap B-H2 — exercises the third call site at `system_gate.py:71`; asserts the raised `GateLockTimeoutError` carries `exc.holder["pid"]` correctly)

3. `tests/test_pre_commit_hook.py` — **3 tests**
   - `test_pre_commit_hook_file_exists_and_is_executable`
   - `test_pre_commit_hook_contains_unittest_and_ruff_invocations`
   - `test_install_hooks_script_sets_core_hookspath`

### 6.3 Quality gates

- `ruff check` clean on the touched Python files.
- `python3 -m unittest discover -s tests` green: **baseline pinned via `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>&1 | tail -1`** at the milestone-start SHA (gap B-M10 — prior "4070" was approximate; the canonical number is whatever a fresh run reports at HEAD). Expected post-batch: baseline + 14 (new) = **baseline+14 tests passing**, 2 skipped, 0 failing.
- Audit-floor invariant test (`tests/test_audit_regression.py`) remains green at **24 invariants**.
- Frozen-gate-surface check (`tests/test_frozen_gate_surface.py`) remains green (no public symbol added or removed).
- No new line in `core/telemetry_events.py` (M01-ownership guardrail).
- No new Python dependency in `package.json`, `setup.py`, or `pyproject.toml`.
- `npm run verify` passes end-to-end (test:python, pack:dry-run, test:cli, test:smoke).

## 7. Risks + mitigations

| Risk | Mitigation |
|---|---|
| ~~B1's 5.0s `started_at` tolerance might be too tight on a heavily-loaded CI host where the GC pause between `psutil.Process().create_time()` and `iso_now()` exceeds 5.0s.~~ **Superseded by gap B-H4 / B-H3.** The 5.0s tolerance was mis-derived; the v2 rule in §4 replaces it with a two-sided bound `[started_at - MAX_ORCHESTRATOR_UPTIME_S, started_at + ISO_TRUNCATION_S]` because `psutil.Process().create_time()` is *process-start*, not *marker-stamp time*. | n/a (rule replaced — see §4). |
| B2 reads the marker without acquiring the gate lock (would deadlock — we're already holding-or-trying-to-hold that lock). A concurrent marker write could race. | `describe_lock_holder` calls `read_gate_marker`, which already uses `path.read_text()` on an atomically-written file. Worst case: returns `None` (marker mid-rename), caller emits "holder unknown". Observability gracefully degrades; no primary path affected. |
| B3 pre-commit hook adds ~2 minute friction to every commit; developers will reach for `--no-verify`. | (a) `BMAD_SKIP_PRECOMMIT=1` provides a stable, greppable opt-out. (b) The full suite + ruff already runs <30s on typical dev machines (4070 tests at ~7ms avg). (c) Hook is opt-in: it does nothing unless the developer runs `scripts/install-hooks.sh` once. |
| B3 hook breaks on Windows git-bash because path quoting differs. | Use plain forward-slashes throughout the hook; `set -euo pipefail` works identically; the unittest + ruff commands themselves are cross-platform. Smoke-test the hook in WSL Ubuntu before merging. |
| The `started_at` ISO parse in B1 could fail on a non-standard timezone-offset string. | `iso_now()` (helper in **`core/utils.py`** — gap B-H3 corrected; the value `core/common.py::iso_now` is a sibling that returns the same shape but `evidence_io.write_gate_marker` imports from `utils`) always emits `Z`-suffixed UTC at second precision (`"%Y-%m-%dT%H:%M:%SZ"`). The parser uses `datetime.fromisoformat()`, which handles `Z` since Python 3.11 (project's minimum). Second precision means the v2 rule's ISO_TRUNCATION_S = 1.0 lower-bound is necessary. |
| Augmenting `filelock.Timeout` message changes a string that some test could be asserting on. | **Superseded by gap B-H1.** B2 no longer "augments the message" — it raises `GateLockTimeoutError(filelock.Timeout)`, a subclass. `exc.lock_file` remains the lock path (NOT the prose message); `str(exc)` is overridden. Re-grep both `lock_file` attribute reads AND message-text asserts as part of pre-flight (gap B-M11). The exception **type** is `filelock.Timeout`-compatible by inheritance. |

## 8. Verification strategy

1. **Author tests first** (TDD). All 10 tests start RED.
2. **Run `python3 -m unittest discover -s tests -k test_bugfix_L1_pid_reuse`** — confirm 4 failures.
3. **Implement B1** in `gate_orchestrator._recover_from_crash_locked`. Re-run; expect 4 green.
4. **Run `python3 -m unittest discover -s tests -k test_lock_holder_observability`** — confirm 3 failures.
5. **Implement B2** (`describe_lock_holder` in `evidence_io.py`; catch + augment + re-raise at the single `get_gate_lock` call site in `gate_orchestrator.py`). Re-run; expect 3 green.
6. **Run `python3 -m unittest discover -s tests -k test_pre_commit_hook`** — confirm 3 failures.
7. **Author `.githooks/pre-commit`, `scripts/install-hooks.sh`, and CONTRIBUTING.md addendum.** Re-run; expect 3 green.
8. **Full suite**: `python3 -m unittest discover -s tests` — expect 4080 passing, 2 skipped, 0 failing.
9. **`ruff check skills/`** — expect zero violations on changed files.
10. **`npm run verify`** — expect green end-to-end.
11. **Manual smoke**: in a fresh shell, run `scripts/install-hooks.sh`, then `touch foo.txt && git add foo.txt && git commit -m "test"` — confirm the hook fires, runs the suite, exits 0, commit lands. Then introduce an intentional ruff violation, repeat, confirm the hook blocks and explains why.
12. **`git log -p --stat` review** on the final commit to confirm `core/telemetry_events.py` is untouched and `tests/test_audit_regression.py` shows no diff.

## 9. Out of scope

- Migrating the existing L1 fix's `start_time` field to use `started_at` (would invalidate live markers on upgrade). The fields coexist; B1 only *adds* a fallback branch.
- A repo-level CI workflow (GitHub Actions / CircleCI / Tekton). B3 is purely pre-commit; CI hardening is a separate milestone.
- Sub-second precision tuning of the `started_at` tolerance. 5.0s is the conservative default; widen later if needed.
- Cross-host marker liveness (different `hostname` on the marker is already treated as dead by the existing code at `gate_orchestrator.py` lines 195-200 — B1 doesn't change that logic).
- Lock-holder *cancellation* (kill the holder for the operator). B2 is observability-only; killing is the operator's call.
- A graphical pre-commit summary. The hook prints `stderr` lines and exits with a status — operators are expected to read terminal output.
- Auto-running `scripts/install-hooks.sh` from `install.sh` or `npm postinstall`. Hooks are opt-in.

## 10. Compatibility statement

- **CLAUDE.md guardrails honored**: stdlib + `filelock` + `psutil` only; no new fifth changelog tag; `telemetry_events.py` not touched; no historical changelog edit; 500-LOC soft limit respected; conventional commits + `Generated-By:` trailer.
- **Frozen-gate-surface honored**: `recover_from_crash`, `_recover_from_crash_locked`, `get_gate_lock`, `read_gate_marker`, `write_gate_marker`, `clear_gate_marker` keep identical signatures. Per gap B-H5, the **one new public symbol** introduced by B is `GateLockTimeoutError` (sibling module `core/gate_lock_observability.py`), declared in `docs/spec/frozen-gate-surface.md` as part of this milestone. The helper `_describe_lock_holder` is leading-underscore private and is NOT a frozen-surface symbol; if a future milestone needs to widen observability, that milestone promotes it explicitly.
- **Cross-platform**: smoke-tested on Linux (primary). WSL Ubuntu and Windows git-bash compatibility is **claimed but not currently smoke-tested by the plan** (gap B-L10 — the plan does not include a Windows/WSL hook-run step). Treat the cross-platform claim as "should work, deferred verification" rather than "verified".
- **New public API**: `GateLockTimeoutError(filelock.Timeout)` with stable attributes `holder: dict | None` and `timeout_s: float`. Documented in `docs/spec/frozen-gate-surface.md`; subclassing `filelock.Timeout` keeps all existing `except filelock.Timeout` callers matching by inheritance.

## 11. Quick LOC budget verification (gap B-H6 — re-derived from actual HEAD `wc -l`)

Verified sizes pre-batch (`wc -l` at HEAD `5424b7e` — the prior "~640 / ~460" estimates in earlier drafts were wrong):

| Module | Pre-batch LOC | Post-batch LOC | Soft limit | Notes |
|---|---|---|---|---|
| `core/gate_orchestrator.py` | **718** | ~724 | 500 (already over — pre-existing waiver below) | B2's wrap-the-call-site work is now ~+6 LOC (try/except + `_handle_gate_lock_timeout(...)` call); B1's `_recover_from_crash_locked` v2 rule adds ~+12 LOC. Net +18 LOC. |
| `core/evidence_io.py` | 442 | ~448 | 500 | Only +6 LOC if a public re-export is needed; otherwise +0. |
| `core/system_gate.py` | <100 | <110 | 500 | +6 LOC for the augmentation at line 71 (gap B-H2). |
| `core/gate_lock_observability.py` | — | ~40 | 500 | **NEW sibling module** (gap B-H6) hosting `GateLockTimeoutError`, `_describe_lock_holder`, `_handle_gate_lock_timeout`. |

**Soft-limit waiver line for `gate_orchestrator.py`** (added to `docs/spec/frozen-gate-surface.md` as part of this milestone — gap B-H6):
> `core/gate_orchestrator.py` — soft-limit waiver: 718 LOC pre-B, ~724 LOC post-B. The +6 LOC for the B2 try/except wrap is small enough to not trigger a split obligation now; the next *broad* refactor that touches the file is expected to split adjudication/lifecycle into sibling modules (target ≤ 500 LOC). B2 deliberately extracts `GateLockTimeoutError` + `_describe_lock_holder` + `_handle_gate_lock_timeout` to `core/gate_lock_observability.py` to converge the LOC budget partially.

## 12. Validation provenance

- Round-2 bug sweep notes (`docs/audit/bug-sweep-round-2-2026-06-22.md` — corrected per gap B-L8 from the prior incorrect filename) flagged the legacy-marker PID-reuse window as low-severity but actionable.
- L1 follow-up workflow (`.claude/workflows/l1-followup-system-gate.md`) and L1/L2 fix workflow (`.claude/workflows/l1-l2-gate-marker-fix.md`) establish the file lock pattern this batch composes against.
- D-04 follow-up (`.claude/workflows/d04-followup-sibling-module.md`) demonstrated that round-2 audits surface real issues that a pre-commit gate would have caught earlier — direct motivation for B3.
- Single-user threat model (memory: `singleuser-threat-model.md`) — confirms B2's log-line approach is appropriate (no multi-tenant secret-leak concern in lock-holder identity).

---

## Tracked enhancements (MED/LOW gaps not patched into the spec body)

> Source: `docs/audit/spec-review-2026-06-22-B-operability.md`. HIGH gaps B-H1..B-H6 are resolved inline above. MED/LOW gaps below ride as inline polish during execution or roll forward as follow-ups.

| ID | Severity | Disposition | Note |
|---|---|---|---|
| B-M1 | MED | Resolved inline | `psutil.ZombieProcess` test case added; spec bullet states zombies count as dead (PID slot is no longer holding gate state). |
| B-M2 | MED | Inline polish (plan §B3.4) | Pre-commit hook probes `command -v python3 \|\| command -v python \|\| command -v py`; prefers `${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/}ruff`; fails loud with a clear error if no Python found. |
| B-M3 | MED | Inline polish (plan §B3.4) | Hook preserves PYTHONPATH: `PYTHONPATH="skills/bmad-story-automator/src${PYTHONPATH:+:$PYTHONPATH}"`. |
| B-M4 | MED | Resolved inline | Hook now invokes `bash scripts/m11-vocabulary-gates.sh`; "would have caught D-04" claim now true. |
| B-M5 | MED | Resolved inline | `scripts/uninstall-hooks.sh` ships (`git config --unset core.hooksPath`); referenced in CONTRIBUTING.md. |
| B-M6 | MED | Resolved inline | `_describe_lock_holder` distinguishes "missing" vs "corrupt" via `_state` sentinel; messages updated in §4 schemas. |
| B-M7 | MED | Resolved inline | `_handle_gate_lock_timeout` helper extracted into `core/gate_lock_observability.py` and used at all three call sites; no duplication. |
| B-M8 | MED | Backlog (post-merge monitoring) | Log-line cardinality: monitor for tight retry loops; if observed, add a `(pid, gate_lock_path)` debouncer in a follow-up. |
| B-M9 | MED | Resolved inline | Hook permission test uses `path.stat().st_mode & stat.S_IXUSR` AND a positive control (run the hook with `--no-verify` semantics and assert exit code), not bare `os.access(X_OK)`. |
| B-M10 | MED | Resolved inline | Test baseline is now pinned via a fresh `PYTHONPATH=... unittest discover` at milestone-start SHA, not a stale literal. |
| B-M11 | MED | Resolved inline | Pre-flight grep widened to both `lock_file` attribute reads AND message-text asserts. |
| B-M12 | MED | Inline polish (plan §B.close.1) | Run `python3 -m unittest tests.test_audit_regression` *before* tagging B1; re-pin any size invariant that trips. |
| B-L1 | LOW | Backlog | `marker["started_at"].replace("Z", "+00:00")` left in for forward-compat with non-Z ISO strings; comment added. |
| B-L2 | LOW | Resolved inline | Test `test_marker_with_both_start_time_and_started_at_prefers_start_time` added. |
| B-L3 | LOW | Resolved inline | Test `test_foreign_host_marker_skips_b1_started_at_check` added. |
| B-L4 | LOW | Inline polish (plan §B3.13) | Smoke recipe corrected: `BMAD_SKIP_PRECOMMIT=1 git commit --allow-empty -m "smoke"` and assert the skip-banner. |
| B-L5 | LOW | Backlog | CONTRIBUTING.md notes that the hook ignores direnv; documents `BMAD_SKIP_PRECOMMIT=1` escape. |
| B-L6 | LOW | Resolved inline | Spec wording: "augmenting Timeout message" → "raises `GateLockTimeoutError(filelock.Timeout)` subclass" throughout §3 and §6.1. |
| B-L7 | LOW | Inline polish (plan §B3.6) | `install-hooks.sh` captures and prints prior `core.hooksPath` if set. |
| B-L8 | LOW | Resolved inline | §12 provenance filename corrected to `bug-sweep-round-2-2026-06-22.md`. |
| B-L9 | LOW | Inline polish | Plan §B2.2 comment clarified: "second `FileLock(str(path))` is a separate instance, so re-entrance does not apply; this models a sibling-process holder." |
| B-L10 | LOW | Resolved inline | Compat claim downgraded to "smoke-tested on Linux; Windows/WSL manual verification deferred to a follow-up". |

### Resolved-from-gap-report (HIGH)

- **B-H1** — `GateLockTimeoutError(filelock.Timeout)` subclass replaces the broken `raise Timeout(msg)` pattern; defined in new sibling module `core/gate_lock_observability.py`; `exc.lock_file` stays as the lock path; `holder` + `timeout_s` are stable attributes declared in frozen-gate-surface.
- **B-H2** — Third call site at `core/system_gate.py:71` added to spec §5 file table and §6.2 tests (new `test_run_system_gate_lock_timeout_includes_holder`). Plan steps updated to wrap all three call sites.
- **B-H3** — `iso_now()` correctly attributed to `core/utils.py` (NOT `core/common.py`) in spec §7 and plan pre-req.
- **B-H4** — 5.0s tolerance dropped; v2 rule uses a two-sided bound `[started_at - MAX_ORCHESTRATOR_UPTIME_S, started_at + ISO_TRUNCATION_S]` derived from the actual code path (`psutil.Process().create_time()` is process-start, not marker-stamp time). Worked example inlined in §4.
- **B-H5** — `GateLockTimeoutError` added to `docs/spec/frozen-gate-surface.md`; `_describe_lock_holder` kept underscore-private to minimize the public surface.
- **B-H6** — Extracted observability helpers into `core/gate_lock_observability.py` (~40 LOC) so `gate_orchestrator.py` net delta is only +6 LOC; soft-limit waiver line added to frozen-gate-surface.md for the pre-existing 718-LOC overrun.
