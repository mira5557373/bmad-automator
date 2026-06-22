# Operability Batch — Implementation Plan

> Date: 2026-06-22 · Status: **Ready to execute** · Milestone: **B (Operability)** · Branch: `bma-d/integration-all` (direct; no worktree, no PR).
> Companion spec: `docs/superpowers/specs/2026-06-22-operability-batch-design.md`.
> Three sub-fixes shipped as a single milestone: **B1 — PID-reuse hardening**, **B2 — Lock-holder observability**, **B3 — Pre-commit full-suite gate**.

## Pre-requisites

1. **HEAD pinned**: confirm `git log -1 --oneline` reads `6a957d2 ...` (or later). All commits since session start are reachable.
2. **Baseline green**: `python3 -m unittest discover -s tests` → 4070 passing, 2 skipped, 0 failing. `ruff check skills/` → clean. Audit-floor invariant: 24 entries.
3. **Read first** (no edits): four files to confirm the call sites — `skills/bmad-story-automator/src/story_automator/core/evidence_io.py` (marker + lock helpers; `iso_now` is imported here from `core.utils`), `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` (`_recover_from_crash_locked` + `get_gate_lock` use sites at lines 291 + 527), `skills/bmad-story-automator/src/story_automator/core/system_gate.py` (gap B-H2 — third `get_gate_lock` use site at line 71 that the original plan missed), and `skills/bmad-story-automator/src/story_automator/core/utils.py` (canonical home of `iso_now` — gap B-H3 corrected the earlier "core/common.py" claim; the `common.py` sibling exists but `evidence_io.py` does NOT import from it).
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
- [ ] **B1.4** Implement the extension in `_recover_from_crash_locked` using the **v2 rule** (gap B-H4 — replaces the broken 5.0s tolerance). Pseudocode:
   ```python
   # Constants (defined at module scope, with comments):
   ISO_TRUNCATION_S = 1.0
   # iso_now() (in core/utils.py — NOT core/common.py per gap B-H3) emits
   # second-precision UTC ("%Y-%m-%dT%H:%M:%SZ"); the recorded value can be
   # up to 1.0s earlier than the actual wall-clock moment.

   MAX_ORCHESTRATOR_UPTIME_S = 86400.0
   # Orchestrator processes are not meant to live longer than a day; a PID
   # seen alive for >24h relative to its marker is strong evidence of recycling.

   if alive and isinstance(marker_start_time, (int, float)):
       # existing branch — unchanged (post-J-03 fast path)
       ...
   elif alive and isinstance(marker.get("started_at"), str) and marker.get("started_at"):
       # NEW: B1 v2 — legacy-marker PID-reuse defense via two-sided bound
       try:
           started_at_epoch = datetime.fromisoformat(
               marker["started_at"].replace("Z", "+00:00")
           ).timestamp()
           proc_start = psutil.Process(pid).create_time()
           if proc_start > started_at_epoch + ISO_TRUNCATION_S:
               # Live PID started AFTER the marker was stamped → reuse.
               alive = False
           elif proc_start < started_at_epoch - MAX_ORCHESTRATOR_UPTIME_S:
               # Live PID started >24h before the marker → almost certainly recycled.
               alive = False
           # else: proc_start within [marker - 24h, marker + 1s] → live.
       except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
           # gap B-M1: ZombieProcess (subclass of NoSuchProcess) explicitly listed.
           alive = False
       except (psutil.Error, OSError, ValueError):
           # ValueError covers a malformed started_at; keep alive=True
           # conservatively. Do not crash recovery on parse failure.
           pass
   ```
   Add `from datetime import datetime` if not already present.
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

- [ ] **B2.1** Read `get_gate_lock` (line 278 of `evidence_io.py`) and every call site **package-wide** (gap B-H2 — the original grep was scoped only to `gate_orchestrator.py` and missed `system_gate.py`):
   ```
   grep -rn 'get_gate_lock\|GATE_LOCK' skills/bmad-story-automator/src/
   ```
   Expected: **three** hits — `gate_orchestrator.py:291`, `gate_orchestrator.py:527`, and `system_gate.py:71`. All three must be wrapped in §B2.5.
- [ ] **B2.2** Author `tests/test_lock_holder_observability.py` with **4 RED tests** (gap B-H2 added the fourth):
   - `test_lock_timeout_includes_holder_pid_and_started_at` — asserts `exc` is a `GateLockTimeoutError`, `isinstance(exc, filelock.Timeout)` is True (subclass inheritance), `exc.lock_file` is the lock path (NOT prose — gap B-H1), `exc.holder["pid"]` is correct, `str(exc)` contains `PID=`, `started_at=`, `host=`.
   - `test_lock_timeout_with_missing_marker_reports_holder_unknown` — asserts `str(exc)` contains `"marker missing — holder may have just released the lock"` (gap B-M6).
   - `test_describe_lock_holder_swallows_marker_corruption` — call `_describe_lock_holder(root)` directly with corrupted marker bytes (`"not json{"`); assert it returns `{"_state": "corrupt"}` (NOT `None`) and no exception. Also assert `str(exc)` from a timeout in this state contains `"marker present but unparseable"`.
   - `test_run_system_gate_lock_timeout_includes_holder` (gap B-H2 — NEW) — write a valid marker, acquire the gate lock from a sibling thread, call `run_system_gate(...)` with a contrived short lock timeout, assert the raised `GateLockTimeoutError` carries `exc.holder["pid"]` and `exc.timeout_s` correctly.

   Test design note (gap B-L9 clarified): `FileLock(str(path))` is process-level on POSIX; constructing a **second** `FileLock` instance for the same path in a sibling thread models a sibling-process holder realistically because `filelock`'s re-entrance applies only to the same instance. Use `threading.Thread`, not multiprocessing.
- [ ] **B2.3** Run `python3 -m unittest discover -s tests -k test_lock_holder_observability` — confirm 3 RED.
- [ ] **B2.4** Create the **new sibling module** `skills/bmad-story-automator/src/story_automator/core/gate_lock_observability.py` (gap B-H6 — keeps `gate_orchestrator.py` from growing further). The module hosts THREE symbols:

   1. **`GateLockTimeoutError(filelock.Timeout)`** — exception subclass (gap B-H1). Stable public attributes `holder: dict | None` and `timeout_s: float`. Declared in `docs/spec/frozen-gate-surface.md` as part of this milestone (gap B-H5).
   2. **`_describe_lock_holder(project_root)`** — leading-underscore private helper. Distinguishes "missing" vs "corrupt" markers (gap B-M6):
   ```python
   def _describe_lock_holder(project_root: str | Path) -> dict[str, Any] | None:
       """Read holder identity from the gate marker for observability.

       Returns one of:
         - {"pid": int, "started_at": str, "hostname": str} — marker present + well-formed.
         - {"_state": "missing"} — marker file absent (holder may have just released).
         - {"_state": "corrupt"} — marker file present but unparseable.
         - None — internal/unrecognised error (caller treats as "unknown").

       Never raises — observability code must not amplify a primary failure.
       """
       try:
           marker = read_gate_marker(project_root)
       except GateMarkerCorruptedError:
           return {"_state": "corrupt"}
       if marker is None:
           return {"_state": "missing"}
       pid = marker.get("pid")
       started_at = marker.get("started_at")
       hostname = marker.get("hostname")
       if not (isinstance(pid, int) and isinstance(started_at, str)):
           return {"_state": "corrupt"}
       return {
           "pid": pid,
           "started_at": started_at,
           "hostname": hostname if isinstance(hostname, str) else "",
       }
   ```
   3. **`_handle_gate_lock_timeout(project_root, lock_path, timeout, exc) -> NoReturn`** — gap B-M7 helper used at all three `get_gate_lock` call sites to prevent augmentation drift:
   ```python
   def _handle_gate_lock_timeout(
       project_root: str | Path,
       lock_path: str | Path,
       timeout: float,
       exc: Timeout,
   ) -> NoReturn:
       holder = _describe_lock_holder(project_root)
       new_exc = GateLockTimeoutError(str(lock_path), holder=holder, timeout=timeout)
       print(str(new_exc), file=sys.stderr)
       raise new_exc from exc
   ```
- [ ] **B2.5** Wrap **all three** `get_gate_lock` call sites (gap B-H2): `gate_orchestrator.py:291`, `gate_orchestrator.py:527`, and `system_gate.py:71`. Pattern at each site:
   ```python
   from .gate_lock_observability import _handle_gate_lock_timeout
   from .evidence_io import gate_lock_path

   try:
       with get_gate_lock(project_root, timeout=TIMEOUT) as _lock:
           ...
   except Timeout as exc:
       _handle_gate_lock_timeout(
           project_root,
           gate_lock_path(project_root),
           TIMEOUT,
           exc,
       )
   ```
   `_handle_gate_lock_timeout` raises `GateLockTimeoutError` (which IS a `filelock.Timeout` by inheritance — gap B-H1). Existing `except filelock.Timeout:` callers continue to match. Confirm `from filelock import FileLock, Timeout` is the import shape in `gate_orchestrator.py` and `system_gate.py`; add `Timeout` to existing import lines if only `FileLock` is imported (per pre-req #5). The helper centralizes the augmentation so the three sites never drift (gap B-M7).
- [ ] **B2.6** Re-run `python3 -m unittest discover -s tests -k test_lock_holder_observability` — confirm **4 GREEN** (gap B-H2 added the fourth test for `run_system_gate`).
- [ ] **B2.7** Re-run full `python3 -m unittest discover -s tests` — confirm baseline+4 passing, 2 skipped. Use `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests` or `npm run test:python`.
- [ ] **B2.8** `ruff check skills/...` — confirm clean.
- [ ] **B2.8b** Update `docs/spec/frozen-gate-surface.md` (gap B-H5): add a new `### core/gate_lock_observability.py` section declaring `GateLockTimeoutError` with attributes `holder: dict | None` and `timeout_s: float`. Also add the soft-limit waiver line for `gate_orchestrator.py` (gap B-H6) and confirm `_describe_lock_holder` / `_handle_gate_lock_timeout` are **NOT** listed (they stay underscore-private).
- [ ] **B2.9** Commit + tag:
   ```
   git add tests/test_lock_holder_observability.py \
           skills/.../core/gate_lock_observability.py \
           skills/.../core/evidence_io.py \
           skills/.../core/gate_orchestrator.py \
           skills/.../core/system_gate.py \
           docs/spec/frozen-gate-surface.md
   git commit -m "feat(operability): B2 — GateLockTimeoutError + holder observability at all three lock sites"
   git tag compat-b-2-lock-holder-observability
   ```

### B3 — Pre-commit full-suite gate (target tag: `compat-b-3-pre-commit-gate`)

- [ ] **B3.1** Verify `.githooks/` does not exist (it doesn't — confirmed pre-flight). Create it.
- [ ] **B3.2** Author `tests/test_pre_commit_hook.py` with 3 RED tests (Windows-git-bash hardened per gap B-M9):
   - `test_pre_commit_hook_file_exists_and_is_executable` — assert `Path(".githooks/pre-commit").is_file()` and `path.stat().st_mode & stat.S_IXUSR` (NOT `os.access(path, os.X_OK)` — X_OK semantics differ on Windows git-bash). Positive control: also assert that running the hook with `BMAD_SKIP_PRECOMMIT=1` exits 0 and prints the skip banner.
   - `test_pre_commit_hook_contains_unittest_and_ruff_invocations` — assert the file's text contains `m unittest discover -s tests`, `ruff check`, `BMAD_SKIP_PRECOMMIT`, AND `m11-vocabulary-gates.sh` (gap B-M4 — verifies the M11 gate is wired).
   - `test_install_hooks_script_sets_core_hookspath` — assert `Path("scripts/install-hooks.sh").is_file()` + `path.stat().st_mode & stat.S_IXUSR` + text contains `git config core.hooksPath .githooks`. Also assert `scripts/uninstall-hooks.sh` exists + executable + text contains `git config --unset core.hooksPath` (gap B-M5).
   All tests resolve paths from the repo root via `Path(__file__).resolve().parents[1]` (tests/ → repo root).
- [ ] **B3.3** Run `python3 -m unittest discover -s tests -k test_pre_commit_hook` — confirm 3 RED.
- [ ] **B3.4** Author `.githooks/pre-commit` with cross-platform robustness (gaps B-M2, B-M3, B-M4):
   ```bash
   #!/usr/bin/env bash
   # BMAD pre-commit gate — runs the full unittest suite + ruff check + M11 vocabulary gate.
   # Skip with: git commit --no-verify   (preferred)
   #       or:  BMAD_SKIP_PRECOMMIT=1 git commit ...   (env-var escape)
   set -euo pipefail

   if [ "${BMAD_SKIP_PRECOMMIT:-0}" = "1" ]; then
     echo ">>> SKIPPING: BMAD_SKIP_PRECOMMIT=1 set in env <<<" >&2
     exit 0
   fi

   REPO_ROOT="$(git rev-parse --show-toplevel)"
   cd "$REPO_ROOT"

   # B-M2: probe for a usable Python — covers Windows git-bash and venvs.
   PYTHON_BIN=""
   for candidate in python3 python py; do
     if command -v "$candidate" >/dev/null 2>&1; then
       PYTHON_BIN="$candidate"
       break
     fi
   done
   if [ -z "$PYTHON_BIN" ]; then
     echo ">>> ERROR: no python3/python/py found on PATH; install Python 3.11+ or set BMAD_SKIP_PRECOMMIT=1" >&2
     exit 2
   fi

   # B-M2: prefer venv-local ruff when available; fall back to PATH ruff.
   RUFF_BIN="ruff"
   if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/ruff" ]; then
     RUFF_BIN="$VIRTUAL_ENV/bin/ruff"
   fi
   if ! command -v "$RUFF_BIN" >/dev/null 2>&1; then
     echo ">>> ERROR: ruff not found ($RUFF_BIN); install ruff or set BMAD_SKIP_PRECOMMIT=1" >&2
     exit 2
   fi

   echo ">>> BMAD pre-commit gate <<<" >&2
   echo ">>> running: $PYTHON_BIN -m unittest discover -s tests" >&2
   # B-M3: PREPEND skills/.../src to PYTHONPATH; do not overwrite.
   PYTHONPATH="skills/bmad-story-automator/src${PYTHONPATH:+:$PYTHONPATH}" \
       "$PYTHON_BIN" -m unittest discover -s tests
   echo ">>> running: $RUFF_BIN check skills/" >&2
   "$RUFF_BIN" check skills/
   # B-M4: M11 vocabulary gate — closes the "would have caught D-04" gap.
   if [ -x scripts/m11-vocabulary-gates.sh ]; then
     echo ">>> running: bash scripts/m11-vocabulary-gates.sh" >&2
     bash scripts/m11-vocabulary-gates.sh
   else
     echo ">>> note: scripts/m11-vocabulary-gates.sh not executable; skipping M11 gate" >&2
   fi
   echo ">>> pre-commit gate passed <<<" >&2
   ```
- [ ] **B3.5** `chmod +x .githooks/pre-commit`.
- [ ] **B3.6** Author `scripts/install-hooks.sh` (with prior-value capture per gap B-L7):
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

   PRIOR_HOOKS_PATH="$(git config --get core.hooksPath || true)"
   if [ -n "$PRIOR_HOOKS_PATH" ] && [ "$PRIOR_HOOKS_PATH" != ".githooks" ]; then
     echo "Note: prior core.hooksPath was '$PRIOR_HOOKS_PATH'; restore later with:" >&2
     echo "  git config core.hooksPath $PRIOR_HOOKS_PATH" >&2
   fi

   git config core.hooksPath .githooks
   echo "Installed: core.hooksPath = .githooks"
   echo "Skip a single commit with: git commit --no-verify"
   echo "Skip ad-hoc with:          BMAD_SKIP_PRECOMMIT=1 git commit ..."
   echo "Uninstall with:            scripts/uninstall-hooks.sh"
   ```
- [ ] **B3.7** `chmod +x scripts/install-hooks.sh`.
- [ ] **B3.7b** Author `scripts/uninstall-hooks.sh` (gap B-M5):
   ```bash
   #!/usr/bin/env bash
   # Uninstall: clear the project-local core.hooksPath setting.
   # Use this if you've deleted .githooks/ or want to revert to default git hooks.
   set -euo pipefail

   REPO_ROOT="$(git rev-parse --show-toplevel)"
   cd "$REPO_ROOT"

   if git config --get core.hooksPath >/dev/null 2>&1; then
     PRIOR="$(git config --get core.hooksPath)"
     git config --unset core.hooksPath
     echo "Uninstalled: core.hooksPath (was '$PRIOR')"
   else
     echo "No project-local core.hooksPath was set; nothing to do."
   fi
   ```
   `chmod +x scripts/uninstall-hooks.sh`.
- [ ] **B3.8** Append a "Pre-commit hook" section to `CONTRIBUTING.md` (create the file if it does not exist) — describe `scripts/install-hooks.sh`, the two skip-hatches, and the expected ~30-second runtime.
- [ ] **B3.9** Re-run `python3 -m unittest discover -s tests -k test_pre_commit_hook` — confirm 3 GREEN.
- [ ] **B3.10** Re-run full `python3 -m unittest discover -s tests` — confirm 4080 passing (4077 + 3), 2 skipped.
- [ ] **B3.11** `ruff check skills/` — confirm clean (no Python touched in this sub-fix).
- [ ] **B3.12** Smoke-test the hook (gap B-L4 — fixed recipe; the prior `/tmp/throwaway-smoke.txt` approach was broken because `git add` outside the worktree fails). Use empty commits in a throwaway branch:
   ```
   ./scripts/install-hooks.sh
   git status                                                         # confirm nothing staged
   # Skip-banner path:
   BMAD_SKIP_PRECOMMIT=1 git commit --allow-empty -m "smoke-skip"     # must succeed with skip banner on stderr
   git reset --soft HEAD~1                                            # undo the smoke commit
   # Full-gate path (will take ~30s — the hook actually runs):
   git commit --allow-empty -m "smoke-full"                           # must succeed with banner + green gate
   git reset --soft HEAD~1                                            # undo
   ```
   The undo `git reset --soft` is safe on a throwaway branch (does not destroy uncommitted work). Do NOT run on `bma-d/integration-all` — make a smoke branch first.
- [ ] **B3.13** Commit + tag:
   ```
   git add .githooks/pre-commit \
           scripts/install-hooks.sh \
           scripts/uninstall-hooks.sh \
           CONTRIBUTING.md \
           tests/test_pre_commit_hook.py
   git commit -m "feat(operability): B3 — opt-in pre-commit gate (unittest + ruff + M11 vocab) with portable shell"
   git tag compat-b-3-pre-commit-gate
   ```

### Milestone close

- [ ] **B.close.1** **Run audit-floor BEFORE tagging** (gap B-M12 — the +18 LOC delta in `gate_orchestrator.py` is not exempt; tests/test_audit_regression.py tracks size invariants for that module):
   ```
   PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_audit_regression -v
   ```
   If any size invariant trips, re-pin it as part of this commit (additive, not delete-and-rewrite). Then check whether new test files are tracked: `grep -n 'test_bugfix_L1\|test_lock_holder\|test_pre_commit_hook' tests/test_audit_regression.py`. If absent, leave audit-floor unchanged. Confirm audit-regression stays green either way.
- [ ] **B.close.2** Add a `[FULL]` changelog entry: `docs/changelog/2026-06-22-operability-batch.md` — heading `## 260622 - [FULL] Operability batch (B1+B2+B3)`. Sections: Summary, Added (B2 helper, B3 hook + installer), Changed (B1 liveness branch + B2 augmentation), Files (list every touched path), QA Notes (`npm run verify` green, 4080 tests passing). CLAUDE.md changelog guardrails honored.
- [ ] **B.close.3** Final full suite + ruff + `npm run verify`:
   ```
   PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests
   # or equivalently: npm run test:python
   ruff check skills/
   npm run verify
   ```
   All green.
- [ ] **B.close.3b** Pre-flight grep for `exc.lock_file` attribute readers + literal-message asserts (gap B-M11 — widen the check that was previously message-text-only):
   ```
   grep -rn 'lock_file' tests/ | grep -v __pycache__
   grep -rn 'Timeout(' tests/ | grep -v __pycache__
   ```
   Confirm no test asserts `exc.lock_file == <prose>` (the subclass keeps `lock_file` as the path, so any such assertion would break). If a hit exists, file as an immediate follow-up before tagging B2.
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
