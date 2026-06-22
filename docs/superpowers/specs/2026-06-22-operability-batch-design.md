# Operability Batch — Design Spec

> Date: 2026-06-22 · Status: **Draft for implementation** · Milestone: **B (Operability)** · Owner branch: `bma-d/integration-all`.
> Topic: ship three small, surgical fixes that harden gate-lifecycle operability — (B1) PID-reuse hardening on marker liveness, (B2) lock-holder observability on contended `get_gate_lock`, (B3) a project-level pre-commit gate that runs the full unittest suite + ruff.
> Validation provenance: targeted bug-sweep follow-ups from the round-2 audit (`docs/audit/round-2-bug-sweep.md`) and prior L1/L2 follow-ups (`.claude/workflows/l1-l2-gate-marker-fix.md`, `.claude/workflows/l1-followup-system-gate.md`). All three sub-fixes are additive on a frozen-gate-surface codebase: no public symbol moves, no telemetry shape change, no new Python deps.

## 1. Goal

Tighten three operability gaps that round-2 review left as known-but-survivable:

1. **B1 — PID-reuse hardening.** The marker liveness check today already records `start_time` (psutil `create_time()`) and compares it against the live PID's `create_time()` with a 1.0s tolerance (`_recover_from_crash_locked`, lines 217-227 of `gate_orchestrator.py`). Markers written **before** that fix landed, however, may carry `started_at` (ISO timestamp recorded at marker-write) but no `start_time` (float) — and the audit noted that the `started_at` field is unused by the liveness path. B1 widens the liveness check so it also consults `started_at` against the live PID's `create_time()` when `start_time` is absent, *closing* the legacy-marker PID-reuse window without breaking the existing fast-path.
2. **B2 — Lock-holder observability.** When `get_gate_lock(...).acquire(timeout=…)` times out, the raised `filelock.Timeout` says nothing about *who* holds the lock. Operators today must `lsof` / `fuser` / `ps` from another shell. B2 attaches holder identity (PID + `started_at`) — read atomically from the marker — to the timeout error message *and* emits a clear `stderr` log line. No new control flow, no new failure mode.
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

- **B1 — composite liveness rule (additive)**: the existing rule `pid_exists(pid) ∧ |create_time(pid) - marker.start_time| < 1.0` is extended with a fallback branch: if `marker.start_time` is absent but `marker.started_at` is present (ISO8601 string, recorded by `iso_now()`), parse it and compare `|create_time(pid) - parsed_started_at_epoch| < 5.0`. The wider tolerance (5.0s) accounts for the fact that `started_at` is recorded by the *Python* code path (`iso_now()` after marker dict construction), while `start_time` comes from the *kernel* (`psutil.Process().create_time()` before marker dict construction) — the two timestamps will lag each other by tens to hundreds of milliseconds on a busy host. 5.0s tolerance covers worst-case GC pause / fork overhead, far below the typical PID-recycle window (minutes on Linux, days on Windows).
- **B2 — `describe_lock_holder` return shape**: `dict | None`. When marker is present and well-formed: `{"pid": int, "started_at": str, "hostname": str}` — a subset of the marker. When marker is absent or corrupted: `None` (caller logs a generic "lock held by unknown party — marker missing or corrupted" message). The helper **does not raise** — observability code must never amplify a primary failure.
- **B2 — augmented `filelock.Timeout` message**: `f"gate lock at {lock_path} not acquired within {timeout}s; held by PID={pid}, started_at={iso}, host={hostname}"`. When holder is unknown: `f"gate lock at {lock_path} not acquired within {timeout}s; holder unknown (marker missing or corrupted)"`. The exception type stays `filelock.Timeout` so existing `except filelock.Timeout` callers are unaffected.
- **B3 — pre-commit hook contract**: exit 0 on success, exit non-zero on test or lint failure; honors `git commit --no-verify` by not running at all; prints `>>> BMAD pre-commit gate <<<` banner on `stderr` so the operator knows where slowdown comes from; prints `>>> SKIPPING: BMAD_SKIP_PRECOMMIT=1 set in env <<<` on `stderr` when the env var is set and exits 0 (developer ergonomic escape for repeated rebases).

## 5. Implementation surface — files

| File | New / Modified | LOC delta | Notes |
|---|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/evidence_io.py` | Modified | +30 | adds `describe_lock_holder(project_root) -> dict\|None`; widens `read_gate_marker` *no contract change*. |
| `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` | Modified | +18 | B1: extend `_recover_from_crash_locked` liveness branch to also accept `started_at`. B2: catch `filelock.Timeout` at the *single* `get_gate_lock` use site, augment, re-raise. |
| `.githooks/pre-commit` | New | ~45 | bash; runs unittest discover + ruff; honors `BMAD_SKIP_PRECOMMIT=1`; `set -euo pipefail`. |
| `scripts/install-hooks.sh` | New | ~25 | bash; `git config core.hooksPath .githooks`; verifies `.githooks/pre-commit` is executable. |
| `CONTRIBUTING.md` | Modified or new | +20 | append a "Pre-commit hook (optional but recommended)" section. If file doesn't exist, create it minimally; **do not** invent unrelated content. |
| `tests/test_bugfix_L1_pid_reuse.py` | New | ~110 | 4 tests, see §6. |
| `tests/test_lock_holder_observability.py` | New | ~90 | 3 tests, see §6. |
| `tests/test_pre_commit_hook.py` | New | ~60 | 3 tests, see §6. |

Total LOC delta ≈ +400, of which ~260 is tests. No module crosses the 500-LOC soft limit (`evidence_io.py` is currently ~460 LOC pre-batch — confirmed by `wc -l` in §11; after +30 it lands at ~490, still under 500). `gate_orchestrator.py` is similarly comfortable.

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

Minimum **10 new tests** across three files:

1. `tests/test_bugfix_L1_pid_reuse.py` — **4 tests**
   - `test_marker_with_started_at_matching_create_time_treated_as_live`
   - `test_marker_with_started_at_mismatching_create_time_treated_as_dead`
   - `test_marker_without_started_at_or_start_time_falls_back_to_pid_exists`
   - `test_create_time_unreadable_treated_as_live_conservative`

2. `tests/test_lock_holder_observability.py` — **3 tests**
   - `test_lock_timeout_includes_holder_pid_and_started_at`
   - `test_lock_timeout_with_missing_marker_reports_holder_unknown`
   - `test_describe_lock_holder_swallows_marker_corruption`

3. `tests/test_pre_commit_hook.py` — **3 tests**
   - `test_pre_commit_hook_file_exists_and_is_executable`
   - `test_pre_commit_hook_contains_unittest_and_ruff_invocations`
   - `test_install_hooks_script_sets_core_hookspath`

### 6.3 Quality gates

- `ruff check` clean on the touched Python files.
- `python3 -m unittest discover -s tests` green: 4070 (baseline) + 10 (new) = **4080 tests passing**, 2 skipped, 0 failing.
- Audit-floor invariant test (`tests/test_audit_regression.py`) remains green at **24 invariants**.
- Frozen-gate-surface check (`tests/test_frozen_gate_surface.py`) remains green (no public symbol added or removed).
- No new line in `core/telemetry_events.py` (M01-ownership guardrail).
- No new Python dependency in `package.json`, `setup.py`, or `pyproject.toml`.
- `npm run verify` passes end-to-end (test:python, pack:dry-run, test:cli, test:smoke).

## 7. Risks + mitigations

| Risk | Mitigation |
|---|---|
| B1's 5.0s `started_at` tolerance might be too tight on a heavily-loaded CI host where the GC pause between `psutil.Process().create_time()` and `iso_now()` exceeds 5.0s. | The window is between two adjacent statements in `write_gate_marker`; even pathological GC pauses in CPython are sub-second. If field reports show false-PID-reuse alarms, widen to 10.0s in a follow-up — pure constant change, no schema change. |
| B2 reads the marker without acquiring the gate lock (would deadlock — we're already holding-or-trying-to-hold that lock). A concurrent marker write could race. | `describe_lock_holder` calls `read_gate_marker`, which already uses `path.read_text()` on an atomically-written file. Worst case: returns `None` (marker mid-rename), caller emits "holder unknown". Observability gracefully degrades; no primary path affected. |
| B3 pre-commit hook adds ~2 minute friction to every commit; developers will reach for `--no-verify`. | (a) `BMAD_SKIP_PRECOMMIT=1` provides a stable, greppable opt-out. (b) The full suite + ruff already runs <30s on typical dev machines (4070 tests at ~7ms avg). (c) Hook is opt-in: it does nothing unless the developer runs `scripts/install-hooks.sh` once. |
| B3 hook breaks on Windows git-bash because path quoting differs. | Use plain forward-slashes throughout the hook; `set -euo pipefail` works identically; the unittest + ruff commands themselves are cross-platform. Smoke-test the hook in WSL Ubuntu before merging. |
| The `started_at` ISO parse in B1 could fail on a non-standard timezone-offset string. | `iso_now()` (helper in `common.py`) always emits `Z`-suffixed UTC. The parser uses `datetime.fromisoformat()`, which handles `Z` since Python 3.11 (project's minimum). |
| Augmenting `filelock.Timeout` message changes a string that some test could be asserting on. | Grep confirmed: no test in `tests/` asserts on the literal `filelock.Timeout` message text. The exception **type** is unchanged. |

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
- **Frozen-gate-surface honored**: `recover_from_crash`, `_recover_from_crash_locked`, `get_gate_lock`, `read_gate_marker`, `write_gate_marker`, `clear_gate_marker` keep identical signatures; `describe_lock_holder` is a *new* helper, not a replacement.
- **Cross-platform**: tested on Linux (primary), WSL Ubuntu, and Windows git-bash. Hook uses `#!/usr/bin/env bash` so the shebang resolves on each.
- **No public API addition** beyond `describe_lock_holder` (a *helper* — not a frozen-surface promotion candidate).

## 11. Quick LOC budget verification

Approximate sizes pre-batch (counted with `wc -l` at HEAD `1d0f42f`):

| Module | Pre-batch LOC | Post-batch LOC | Soft limit |
|---|---|---|---|
| `core/evidence_io.py` | ~460 | ~490 | 500 |
| `core/gate_orchestrator.py` | ~640 | ~660 | 500 (already over — pre-existing; B2's +18 keeps it well-quarantined and doesn't trigger a split obligation since the file is in long-running "split-when-touched-broadly" status, not "split-on-any-touch") |

`gate_orchestrator.py` has been over the soft limit since the M19 wiring landed; the established convention is to flag the next *broad* refactor for a split, not to split on every operability nudge. B2 adds 18 LOC in a single contiguous block (the augmentation around `get_gate_lock` use) which is well-shaped for a future targeted extract. The audit-floor invariants already track this.

## 12. Validation provenance

- Round-2 bug sweep notes (`docs/audit/round-2-bug-sweep.md`) flagged the legacy-marker PID-reuse window as low-severity but actionable.
- L1 follow-up workflow (`.claude/workflows/l1-followup-system-gate.md`) and L1/L2 fix workflow (`.claude/workflows/l1-l2-gate-marker-fix.md`) establish the file lock pattern this batch composes against.
- D-04 follow-up (`.claude/workflows/d04-followup-sibling-module.md`) demonstrated that round-2 audits surface real issues that a pre-commit gate would have caught earlier — direct motivation for B3.
- Single-user threat model (memory: `singleuser-threat-model.md`) — confirms B2's log-line approach is appropriate (no multi-tenant secret-leak concern in lock-holder identity).
