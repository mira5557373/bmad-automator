# Operability Batch — Implementation Plan

> Date: 2026-06-22 · Status: **Ready to execute** · Milestone: **B (Operability)** · Branch: `bma-d/integration-all` (direct; no worktree, no PR).
> Companion spec: `docs/superpowers/specs/2026-06-22-operability-batch-design.md`.
> Three sub-fixes shipped as a single milestone: **B1 — PID-reuse hardening**, **B2 — Lock-holder observability**, **B3 — Pre-commit full-suite gate**.

## Pre-requisites

1. **HEAD pinned**: confirm `git log -1 --oneline` reads `6a957d2 ...` (or later). All commits since session start are reachable.
2. **Baseline green**: `python3 -m unittest discover -s tests` → 4070 passing, 2 skipped, 0 failing. `ruff check skills/` → clean. Audit-floor invariant: 24 entries.
3. **Read first** (no edits): three files to confirm the call sites — `skills/bmad-story-automator/src/story_automator/core/evidence_io.py` (marker + lock helpers), `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` (`_recover_from_crash_locked` + `get_gate_lock` use sites), `skills/bmad-story-automator/src/story_automator/core/common.py` (look for `iso_now`).
4. **Confirm `psutil` already imported** in both modules — no new dep.
5. **Confirm `filelock.Timeout` already imported** in `gate_orchestrator.py` (the augmentation path needs `except filelock.Timeout:`). If only `FileLock` is imported, add `Timeout` to the same import line.
6. **Grep guard**: `grep -rn 'core/telemetry_events.py\|telemetry_events' skills/bmad-story-automator/src/story_automator/core/evidence_io.py skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — confirm no import of telemetry events from files we'll touch. M01 ownership.
7. **No worktree** (CLAUDE.md guardrail for this run); work directly on `bma-d/integration-all`.

## Task list

### B1 — PID-reuse hardening (target tag: `compat-b-1-pid-reuse-hardening`)

- [ ] **B1.1** Read `_recover_from_crash_locked` (lines 166-257 of `gate_orchestrator.py`) end-to-end; sketch the new conditional on paper. The new branch sits *after* the existing `start_time` check and only runs when `marker_start_time` was absent.
- [ ] **B1.2** Author `tests/test_bugfix_L1_pid_reuse.py` with 4 RED tests:
   - `test_marker_with_started_at_matching_create_time_treated_as_live`
   - `test_marker_with_started_at_mismatching_create_time_treated_as_dead`
   - `test_marker_without_started_at_or_start_time_falls_back_to_pid_exists`
   - `test_create_time_unreadable_treated_as_live_conservative`
   Use `unittest.mock.patch` on `psutil.Process` to control `create_time()` deterministically. Write marker JSON directly to `<root>/_bmad/gate/gate-in-progress.json` via `evidence_io.write_atomic` to bypass the helper (lets us craft legacy-shape markers).
- [ ] **B1.3** Run `python3 -m unittest discover -s tests -k test_bugfix_L1_pid_reuse` — confirm 4 RED.
- [ ] **B1.4** Implement the extension in `_recover_from_crash_locked`. Pseudocode:
   ```python
   if alive and isinstance(marker_start_time, (int, float)):
       # existing branch — unchanged
       ...
   elif alive and isinstance(marker.get("started_at"), str) and marker.get("started_at"):
       # NEW: B1 — legacy-marker PID-reuse defense
       try:
           started_at_epoch = datetime.fromisoformat(
               marker["started_at"].replace("Z", "+00:00")
           ).timestamp()
           proc_start = psutil.Process(pid).create_time()
           if abs(proc_start - started_at_epoch) >= 5.0:
               alive = False
       except (psutil.NoSuchProcess, psutil.AccessDenied):
           alive = False
       except (psutil.Error, OSError, ValueError):
           # ValueError covers a malformed started_at; keep alive=True
           # conservatively. Do not crash recovery on parse failure.
           pass
   ```
   Add `from datetime import datetime` if not already present (it isn't; the file uses ISO strings via helpers, not direct datetime parsing).
- [ ] **B1.5** Re-run `python3 -m unittest discover -s tests -k test_bugfix_L1_pid_reuse` — confirm 4 GREEN.
- [ ] **B1.6** Re-run *full* `python3 -m unittest discover -s tests` — confirm 4074 passing (4070 + 4), 2 skipped.
- [ ] **B1.7** `ruff check skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — confirm clean.
- [ ] **B1.8** Commit + tag:
   ```
   git add tests/test_bugfix_L1_pid_reuse.py skills/.../core/gate_orchestrator.py
   git commit -m "fix(operability): B1 — legacy-marker PID-reuse hardening via started_at fallback"
   git tag compat-b-1-pid-reuse-hardening
   ```

### B2 — Lock-holder observability (target tag: `compat-b-2-lock-holder-observability`)

- [ ] **B2.1** Read `get_gate_lock` (line 278 of `evidence_io.py`) and every call site in `gate_orchestrator.py`. `grep -n 'get_gate_lock\|GATE_LOCK' skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` — expect 2-3 hits (orchestrator + recover-from-crash).
- [ ] **B2.2** Author `tests/test_lock_holder_observability.py` with 3 RED tests:
   - `test_lock_timeout_includes_holder_pid_and_started_at`
   - `test_lock_timeout_with_missing_marker_reports_holder_unknown`
   - `test_describe_lock_holder_swallows_marker_corruption`
   For test 1: write a valid marker into `<root>/_bmad/gate/gate-in-progress.json`, acquire the gate lock in the test process, then in a thread (NOT a subprocess — same `filelock` instance can't conflict cross-process easily in unittest) acquire a *second* `FileLock` instance with `timeout=0.1` and assert the raised `filelock.Timeout` message contains `pid=`, `started_at=`, `host=`. Note: `FileLock` is process-level; use two `FileLock` *instances* in the same process via `threading.Thread` — `filelock.FileLock` reentrance only works for the same instance, so a second instance + a busy holder still races realistically.
   For test 2: same as test 1 but **don't** write a marker; assert message contains `holder unknown`.
   For test 3: call `describe_lock_holder(root)` directly with a corrupted marker on disk (write `"not json{"` bytes) and assert it returns `None` (no exception).
- [ ] **B2.3** Run `python3 -m unittest discover -s tests -k test_lock_holder_observability` — confirm 3 RED.
- [ ] **B2.4** Implement `describe_lock_holder` in `evidence_io.py`, immediately below `read_gate_marker`:
   ```python
   def describe_lock_holder(
       project_root: str | Path,
   ) -> dict[str, Any] | None:
       """Read holder identity from the gate marker for observability.

       Returns ``{"pid": int, "started_at": str, "hostname": str}`` when
       the marker is present and well-formed; ``None`` otherwise. Never
       raises — observability code must not amplify a primary failure.
       Used by ``gate_orchestrator`` when ``get_gate_lock`` times out.
       """
       try:
           marker = read_gate_marker(project_root)
       except GateMarkerCorruptedError:
           return None
       if marker is None:
           return None
       pid = marker.get("pid")
       started_at = marker.get("started_at")
       hostname = marker.get("hostname")
       if not (isinstance(pid, int) and isinstance(started_at, str)):
           return None
       return {
           "pid": pid,
           "started_at": started_at,
           "hostname": hostname if isinstance(hostname, str) else "",
       }
   ```
- [ ] **B2.5** Implement the augmentation at the single `get_gate_lock` use site in `gate_orchestrator.py` (the `recover_from_crash` outer + the orchestrator's gate-write critical section). Pattern at *each* call site that uses `with get_gate_lock(...)`:
   ```python
   try:
       with get_gate_lock(project_root, timeout=...) as _lock:
           ...
   except Timeout as exc:
       holder = describe_lock_holder(project_root)
       if holder is not None:
           msg = (
               f"gate lock at {gate_lock_path(project_root)} "
               f"not acquired within {...}s; held by "
               f"PID={holder['pid']}, started_at={holder['started_at']}, "
               f"host={holder.get('hostname','')}"
           )
       else:
           msg = (
               f"gate lock at {gate_lock_path(project_root)} "
               f"not acquired within {...}s; holder unknown "
               f"(marker missing or corrupted)"
           )
       print(msg, file=sys.stderr)
       raise Timeout(msg) from exc
   ```
   Confirm `from filelock import FileLock, Timeout` is the import shape. Add `import sys` if not already present. Add `from .evidence_io import describe_lock_holder, gate_lock_path` (both already exported).
- [ ] **B2.6** Re-run `python3 -m unittest discover -s tests -k test_lock_holder_observability` — confirm 3 GREEN.
- [ ] **B2.7** Re-run full `python3 -m unittest discover -s tests` — confirm 4077 passing (4074 + 3), 2 skipped.
- [ ] **B2.8** `ruff check skills/...` — confirm clean.
- [ ] **B2.9** Commit + tag:
   ```
   git add tests/test_lock_holder_observability.py skills/.../core/evidence_io.py skills/.../core/gate_orchestrator.py
   git commit -m "feat(operability): B2 — surface lock-holder PID+started_at on gate-lock timeout"
   git tag compat-b-2-lock-holder-observability
   ```

### B3 — Pre-commit full-suite gate (target tag: `compat-b-3-pre-commit-gate`)

- [ ] **B3.1** Verify `.githooks/` does not exist (it doesn't — confirmed pre-flight). Create it.
- [ ] **B3.2** Author `tests/test_pre_commit_hook.py` with 3 RED tests:
   - `test_pre_commit_hook_file_exists_and_is_executable` — assert `Path(".githooks/pre-commit").is_file()` and `os.access(path, os.X_OK)`.
   - `test_pre_commit_hook_contains_unittest_and_ruff_invocations` — assert the file's text contains `python3 -m unittest discover -s tests` and `ruff check` and `BMAD_SKIP_PRECOMMIT`.
   - `test_install_hooks_script_sets_core_hookspath` — assert `Path("scripts/install-hooks.sh").is_file()` + executable + text contains `git config core.hooksPath .githooks`.
   All tests resolve paths from the repo root via `Path(__file__).resolve().parents[1]` (tests/ → repo root).
- [ ] **B3.3** Run `python3 -m unittest discover -s tests -k test_pre_commit_hook` — confirm 3 RED.
- [ ] **B3.4** Author `.githooks/pre-commit`:
   ```bash
   #!/usr/bin/env bash
   # BMAD pre-commit gate — runs the full unittest suite + ruff check.
   # Skip with: git commit --no-verify   (preferred)
   #       or:  BMAD_SKIP_PRECOMMIT=1 git commit ...   (env-var escape)
   set -euo pipefail

   if [ "${BMAD_SKIP_PRECOMMIT:-0}" = "1" ]; then
     echo ">>> SKIPPING: BMAD_SKIP_PRECOMMIT=1 set in env <<<" >&2
     exit 0
   fi

   REPO_ROOT="$(git rev-parse --show-toplevel)"
   cd "$REPO_ROOT"

   echo ">>> BMAD pre-commit gate <<<" >&2
   echo ">>> running: python3 -m unittest discover -s tests" >&2
   PYTHONPATH="skills/bmad-story-automator/src" python3 -m unittest discover -s tests
   echo ">>> running: ruff check skills/" >&2
   ruff check skills/
   echo ">>> pre-commit gate passed <<<" >&2
   ```
- [ ] **B3.5** `chmod +x .githooks/pre-commit`.
- [ ] **B3.6** Author `scripts/install-hooks.sh`:
   ```bash
   #!/usr/bin/env bash
   # One-shot installer: point this repo's git hooks at .githooks/.
   # Runs once per clone; idempotent.
   set -euo pipefail

   REPO_ROOT="$(git rev-parse --show-toplevel)"
   cd "$REPO_ROOT"

   if [ ! -x ".githooks/pre-commit" ]; then
     echo "Error: .githooks/pre-commit not found or not executable." >&2
     exit 1
   fi

   git config core.hooksPath .githooks
   echo "Installed: core.hooksPath = .githooks"
   echo "Skip a single commit with: git commit --no-verify"
   echo "Skip ad-hoc with:          BMAD_SKIP_PRECOMMIT=1 git commit ..."
   ```
- [ ] **B3.7** `chmod +x scripts/install-hooks.sh`.
- [ ] **B3.8** Append a "Pre-commit hook" section to `CONTRIBUTING.md` (create the file if it does not exist) — describe `scripts/install-hooks.sh`, the two skip-hatches, and the expected ~30-second runtime.
- [ ] **B3.9** Re-run `python3 -m unittest discover -s tests -k test_pre_commit_hook` — confirm 3 GREEN.
- [ ] **B3.10** Re-run full `python3 -m unittest discover -s tests` — confirm 4080 passing (4077 + 3), 2 skipped.
- [ ] **B3.11** `ruff check skills/` — confirm clean (no Python touched in this sub-fix).
- [ ] **B3.12** Smoke-test the hook in a throwaway commit (do not push the smoke commit):
   ```
   ./scripts/install-hooks.sh
   git status        # confirm nothing about to be committed accidentally
   touch /tmp/throwaway-smoke.txt; git add /tmp/throwaway-smoke.txt  # will fail (outside repo), ok
   ```
   The smoke step is optional — if you want to confirm the hook *actually* runs, use `BMAD_SKIP_PRECOMMIT=1 git commit --allow-empty -m "smoke"` and confirm the skip-banner appears on stderr.
- [ ] **B3.13** Commit + tag:
   ```
   git add .githooks/pre-commit scripts/install-hooks.sh CONTRIBUTING.md tests/test_pre_commit_hook.py
   git commit -m "feat(operability): B3 — opt-in pre-commit gate (unittest + ruff)"
   git tag compat-b-3-pre-commit-gate
   ```

### Milestone close

- [ ] **B.close.1** Add an audit-floor entry for the new test files, if and only if `tests/test_audit_regression.py` expects to track them. Check first: `grep -n 'test_bugfix_L1\|test_lock_holder\|test_pre_commit_hook' tests/test_audit_regression.py`. If absent, leave audit-floor unchanged (the test merely counts invariants in source-tree modules, not test count). Confirm the audit-regression test stays green either way.
- [ ] **B.close.2** Add a `[FULL]` changelog entry: `docs/changelog/2026-06-22-operability-batch.md` — heading `## 260622 - [FULL] Operability batch (B1+B2+B3)`. Sections: Summary, Added (B2 helper, B3 hook + installer), Changed (B1 liveness branch + B2 augmentation), Files (list every touched path), QA Notes (`npm run verify` green, 4080 tests passing). CLAUDE.md changelog guardrails honored.
- [ ] **B.close.3** Final full suite + ruff + `npm run verify`:
   ```
   python3 -m unittest discover -s tests
   ruff check skills/
   npm run verify
   ```
   All green.
- [ ] **B.close.4** Optional combined milestone tag: `git tag milestone-b-operability-batch` on the changelog commit.
- [ ] **B.close.5** Update `.claude/workflows/operability-batch-b.md` with the executed-workflow archive (for traceability, matching the pattern of `.claude/workflows/d04-followup-sibling-module.md`).

## Test files to author

1. `/home/ubuntu/projects/personal/bmad-automator/tests/test_bugfix_L1_pid_reuse.py` — 4 tests
2. `/home/ubuntu/projects/personal/bmad-automator/tests/test_lock_holder_observability.py` — 3 tests
3. `/home/ubuntu/projects/personal/bmad-automator/tests/test_pre_commit_hook.py` — 3 tests

Total new test count: **10**. Each file under 150 LOC.

## Commit + tag spec

| Step | Commit subject (Conventional Commits) | Tag |
|---|---|---|
| B1 | `fix(operability): B1 — legacy-marker PID-reuse hardening via started_at fallback` | `compat-b-1-pid-reuse-hardening` |
| B2 | `feat(operability): B2 — surface lock-holder PID+started_at on gate-lock timeout` | `compat-b-2-lock-holder-observability` |
| B3 | `feat(operability): B3 — opt-in pre-commit gate (unittest + ruff)` | `compat-b-3-pre-commit-gate` |
| Close | `docs(changelog): operability batch B1+B2+B3 (FULL)` | `milestone-b-operability-batch` (optional) |

Every commit body ends with:
```
Generated-By: claude-opus-4-7
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

No `--amend`, no `--no-verify`, no force-push. All on `bma-d/integration-all`.

## Rollback plan

Each sub-fix is a single commit. Rollback granularity is per-commit:

- **B3 rollback** (safest — pure additive): `git rm .githooks/pre-commit scripts/install-hooks.sh tests/test_pre_commit_hook.py`, revert the `CONTRIBUTING.md` diff, commit. No production runtime affected.
- **B2 rollback** (next-safest — observability only): `git revert <B2 sha>`. Lock timeouts return to opaque `filelock.Timeout` without holder info; primary gate behavior unchanged.
- **B1 rollback** (last resort): `git revert <B1 sha>`. Liveness check returns to the prior `start_time`-only path; legacy markers may falsely register PID-reused processes as live (the prior tolerated state — that's why B1 was deemed *survivable* by round-2 audit).

If the full suite goes red after merging any one sub-fix, revert *that* sub-fix's commit immediately, restore green, then re-author the test that exposed the issue before re-attempting.

## Risk monitoring after merge

1. Watch for `gate lock not acquired` log lines on CI for one week; if `holder unknown` dominates (>20% of timeouts), the marker-write race is more common than expected → investigate but no immediate revert.
2. Watch for `false PID-reuse` false-positives (markers being declared dead when their owning process is actually live) — would manifest as `recovered: true` returned by `recover_from_crash` while a sibling orchestrator is still running. The composite-identity lock + the foreign-host check should prevent this, but B1 widens the eligibility window; if reports surface, raise the `5.0s` tolerance to `10.0s` and re-deploy as `compat-b-1-tolerance-widen`.
3. Pre-commit hook adoption: monitor whether developers actually run `scripts/install-hooks.sh`. If <30% adoption after two sprints, consider a softer reminder in `npm postinstall` (still opt-in — never auto-configure git).
