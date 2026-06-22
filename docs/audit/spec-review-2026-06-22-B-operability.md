# Spec Review — Milestone B (Operability Batch: B1+B2+B3)

> Reviewer: adversarial gap-analysis pass (claude-opus-4-7), 2026-06-22.
> Artifacts reviewed:
> - `docs/superpowers/specs/2026-06-22-operability-batch-design.md`
> - `docs/superpowers/plans/2026-06-22-operability-batch-plan.md`
> Context consulted: `core/gate_orchestrator.py` (718 LOC), `core/evidence_io.py` (442 LOC), `core/system_gate.py`, `core/utils.py`, `tests/test_bugfix_L1_L2_gate_marker.py`, `tests/test_bugfix_L1_system_gate_lock.py`, `docs/spec/frozen-gate-surface.md`, `docs/audit/bug-sweep-round-2-2026-06-22.md`.

## TL;DR

The spec is well-scoped and reaches for the right surfaces (B1 closes a real legacy-marker PID-reuse window, B2 surfaces a real ops pain point, B3 introduces an operationally-reasonable pre-commit gate). However, **three HIGH-severity defects in the plan would ship a broken implementation as written**: (1) the `filelock.Timeout` exception only accepts a `lock_file` *path string*, not a free-form message — the plan's `raise Timeout(msg) from exc` will silently turn the entire augmented message into the lock-file path, breaking every downstream consumer that reads `exc.lock_file`; (2) the plan misses a third `get_gate_lock` call site in `core/system_gate.py:71` — B2 augmentation will not cover the `run_system_gate` path; (3) the plan references `iso_now` in `core/common.py` while `core/evidence_io.py` actually imports it from `core/utils.py`, and the spec's tolerance rationale for B1 (5.0s window) is built on a reversed cause-and-effect that should be re-derived before the constant is frozen. There are an additional 22 medium- and low-severity findings spanning frozen-gate-surface declarations, M11 changelog interactions, Windows/git-bash portability of the pre-commit hook, missing tests for legacy marker variants, and unaddressed log-flood risk in B2. Verdict: **needs-enhancement** before implementation — most fixes are 1- to 5-line spec/plan edits.

## Findings table (HIGH first)

| ID  | Section            | Severity | Issue                                                                                                                                                                                                                                          | Suggested patch (1 sentence)                                                                                                                                                |
|-----|--------------------|----------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| B-H1 | plan §B2.5         | HIGH     | `filelock.Timeout.__init__(lock_file: str)` accepts only the lock-file path — `raise Timeout(msg)` stuffs the augmented msg into `lock_file`, garbling `exc.lock_file` and producing `"The file lock 'gate lock at ... not acquired ...' could not be acquired."`. | Subclass `Timeout` as `class GateLockTimeoutError(Timeout)` carrying explicit `pid/started_at/host` attributes + a clean `__str__`; raise that instead.                       |
| B-H2 | plan §B2.5, spec §3 | HIGH     | Plan claims "2-3 hits" of `get_gate_lock` but `grep` shows **three** call sites: `gate_orchestrator.py:291`, `gate_orchestrator.py:527`, and `system_gate.py:71`. The plan never enumerates `system_gate.py`; B2 will leave `run_system_gate` un-augmented. | Add `system_gate.py:71` to plan §B2.5, add a fourth test asserting `run_system_gate` raises the augmented error, and update spec §5 file table.                              |
| B-H3 | plan pre-req #3, B1.4 | HIGH    | Plan says "look for `iso_now` in `core/common.py`" — but `core/evidence_io.py` imports `iso_now` from `core/utils.py` (`from .utils import ensure_dir, iso_now, write_atomic`). The spec's wall-clock-vs-kernel-time reasoning under §4 is then derived from the wrong source. | Correct plan to `core/utils.py::iso_now`; re-derive the 5.0s tolerance rationale from the *actual* `iso_now()` body (`now_utc_z()` → second-precision UTC), not "GC-pause".  |
| B-H4 | spec §4, plan B1.4   | HIGH    | The 5.0s `started_at` tolerance is justified by "GC pause / fork overhead between `psutil.Process().create_time()` and `iso_now()`" — but `iso_now()` only has **second precision** (`"%Y-%m-%dT%H:%M:%SZ"`), so the worst-case round-down error is *already* up to 1.0s before any pause is added. | Re-derive tolerance as `1.0 (iso truncation) + N (clock skew / scheduler) ≈ 5.0s`, and add a unit test asserting the boundary at both 4.99s and 5.01s.                       |
| B-H5 | spec §10, plan      | HIGH     | `describe_lock_holder` is introduced as a new public symbol in `core/evidence_io.py` (a frozen-gate-surface module). `docs/spec/frozen-gate-surface.md` lists the existing surface explicitly — adding a public helper without declaring it there violates the contract. | Either prefix the helper as `_describe_lock_holder` and call it from inside `evidence_io` only (keep observability surface internal), or add a new bullet to `docs/spec/frozen-gate-surface.md` declaring it as additive. |
| B-H6 | spec §11, plan      | HIGH     | `gate_orchestrator.py` is already **718 LOC** (verified by `wc -l`), not "~640" as the spec claims. Adding +18 LOC pushes it to ~736 LOC. The spec waves this away as "long-running over-soft-limit status" but no audit-floor invariant or written exception is cited. | Either ship the file under a split (extract the new `_log_lock_timeout` helper to a sibling `core/gate_lock_observability.py`) or, if waiving, add a *citable* waiver line to `docs/spec/frozen-gate-surface.md`. |
| B-M1 | plan §B1.4         | MED      | Plan's `except (psutil.NoSuchProcess, psutil.AccessDenied)` correctly catches `ZombieProcess` (subclass of `NoSuchProcess`) but spec §6.1's enumeration only mentions `AccessDenied` — a zombie PID is treated as "dead" which is semantically debatable. | Add an explicit `psutil.ZombieProcess` test case + spec bullet stating zombies count as dead (the PID slot is no longer holding gate state).                                |
| B-M2 | plan §B3.4         | MED      | Pre-commit hook hard-codes `python3` and `ruff` on PATH. On Windows git-bash and on dev machines with project-local venvs, neither is guaranteed. CLAUDE.md mandates portability across Windows git-bash, WSL Ubuntu, and Linux CI. | Probe `command -v python3 || command -v python || command -v py` and prefer `${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/}ruff`; fall back gracefully with a clear error.               |
| B-M3 | plan §B3.4         | MED      | Hook uses `PYTHONPATH="skills/bmad-story-automator/src" python3 ...` — this **overwrites** any developer-set PYTHONPATH rather than prepending. Long-term, this breaks devs who rely on PYTHONPATH for editable installs. | Use `PYTHONPATH="skills/bmad-story-automator/src${PYTHONPATH:+:$PYTHONPATH}"`.                                                                                              |
| B-M4 | spec/plan          | MED      | B3 pre-commit gate does NOT invoke `scripts/m11-vocabulary-gates.sh`, so a changelog edit violating M11 vocabulary will still pass the hook. The spec's claim "would have caught D-04" is overclaimed; D-04 was caught by audit-floor invariants, not lint+unittest. | Add an M11 gate invocation in the hook (`bash scripts/m11-vocabulary-gates.sh`) and adjust spec §1 wording to reflect the *actual* defenses the hook provides.                |
| B-M5 | plan §B3           | MED      | No uninstaller. If a dev runs `scripts/install-hooks.sh` and later deletes `.githooks/`, every subsequent commit silently fails because `core.hooksPath` still points to the missing dir. | Ship `scripts/uninstall-hooks.sh` (`git config --unset core.hooksPath`) and reference it in CONTRIBUTING.md.                                                               |
| B-M6 | plan §B2.4         | MED      | `describe_lock_holder` returns `None` when the marker is mid-rename or freshly cleared by a finishing holder — but the operator sees `"holder unknown (marker missing or corrupted)"` which is *misleading*: the holder just finished. | Distinguish "marker missing" vs "marker corrupted" in the message: `"marker missing (holder may have just released the lock)"` vs `"marker present but unparseable"`.        |
| B-M7 | plan §B2.5         | MED      | Augmentation is duplicated at every `get_gate_lock` call site (2 → 3 with H2). This invites drift over time. | Extract `_handle_gate_lock_timeout(project_root, lock_path, timeout, exc) -> NoReturn` into a small helper near the imports of `gate_orchestrator.py` (or in the new sibling module from H6). |
| B-M8 | spec §7 (risks)    | MED      | No mitigation for **log-line cardinality**: a tight retry loop (e.g. a CI watcher poll) would flood stderr with one observed-holder line per timeout. | Add a "log at most once per (pid, gate_lock_path) per process lifetime" debouncer or document the expected per-call cardinality so ops can `grep -c`.                       |
| B-M9 | plan §B3.2         | MED      | `os.access(path, os.X_OK)` is unreliable on Windows git-bash (the executable bit semantics differ). The B3 file-permission test will be flaky in CI on Windows. | Replace the X_OK assertion with `path.stat().st_mode & stat.S_IXUSR` *and* a positive control (run the hook and assert exit-code semantics, not just bit pattern).           |
| B-M10 | spec §6.3          | MED      | "4070 + 10 = 4080 tests" — but the round-2 followup doc reports **4055** at one point. The baseline is ambiguous (4055? 4070?). | Pin the exact baseline by running `python3 -m unittest discover -s tests 2>&1 \| tail -1` at HEAD and quoting that figure verbatim in §6.3.                                  |
| B-M11 | spec §7            | MED      | "Grep confirmed: no test asserts on `filelock.Timeout` message text" — but the augmentation in B-H1 *replaces* `lock_file` (an attribute many tests *do* read via `exc.lock_file`). | Re-grep for `lock_file` attribute reads on Timeout, not just message-text asserts; revise risk row.                                                                          |
| B-M12 | plan §B.close.1    | MED      | "Audit-floor invariant tracks invariants in source-tree modules, not test count" — but `tests/test_audit_regression.py` does test things like `gate_orchestrator.py` size. The +18 LOC delta to that file is not exempt. | Audit-floor must be checked *before* tagging B1: run `python3 -m unittest tests.test_audit_regression` and re-pin any size invariant that trips.                              |
| B-L1  | plan §B1.4         | LOW      | `marker["started_at"].replace("Z", "+00:00")` is redundant on Python ≥ 3.11 — `fromisoformat()` parses `Z` natively (verified). | Drop the `replace` for cleanliness, or leave it with a comment explaining why (forward-compat with non-Z ISO strings).                                                       |
| B-L2  | spec §6.2          | LOW      | No test for "marker with both `start_time` AND `started_at` present" — the post-J-03 fast-path coexists with B1's fallback; ensure the existing branch still wins. | Add `test_marker_with_both_start_time_and_started_at_prefers_start_time` to lock that ordering down.                                                                          |
| B-L3  | spec §6.2          | LOW      | No test for B1 + foreign-host marker (composite-identity check should short-circuit before B1's branch runs). | Add `test_foreign_host_marker_skips_b1_started_at_check`.                                                                                                                    |
| B-L4  | plan §B3.13        | LOW      | Smoke step uses `touch /tmp/throwaway-smoke.txt` then `git add /tmp/throwaway-smoke.txt` — `git add` outside the worktree fails; the smoke is half-broken as written. | Rewrite the smoke to `git commit --allow-empty -m "smoke"` after `install-hooks.sh`, asserting the banner appears on stderr.                                                  |
| B-L5  | plan §B3.4         | LOW      | Hook does not source `.envrc` or `.env` — devs using direnv get unexpected behavior. | Note in CONTRIBUTING.md that the hook ignores direnv; document the `BMAD_SKIP_PRECOMMIT=1` escape.                                                                            |
| B-L6  | spec §3            | LOW      | "Augmenting `filelock.Timeout` message" — wording suggests message mutation works; combined with B-H1 this becomes a misleading mental model in the spec. | Replace "augment" with "raise a `GateLockTimeoutError(Timeout)` subclass" wording throughout §3 and §6.1.                                                                    |
| B-L7  | plan §B3.6         | LOW      | `install-hooks.sh` writes `core.hooksPath` without backing up any previously-set per-repo value. | Capture the prior value and print it on installer success so the user can restore later.                                                                                     |
| B-L8  | spec §12 provenance | LOW     | References `docs/audit/round-2-bug-sweep.md` — the actual file is `docs/audit/bug-sweep-round-2-2026-06-22.md`. | Correct the path in §12.                                                                                                                                                      |
| B-L9  | plan §B2.2         | LOW     | "Same `filelock` instance can't conflict cross-process easily in unittest" — actually `FileLock` *is* re-entrant *within* the same instance; the test design assumes two instances. Document that more precisely. | Clarify the comment: "second `FileLock(str(path))` is a separate instance, so re-entrance does not apply; this models a sibling-process holder."                              |
| B-L10 | spec §10           | LOW     | Compatibility statement claims "Tested on Linux (primary), WSL Ubuntu, and Windows git-bash" — but the plan never lists a step that runs the hook in WSL or Windows. | Add explicit plan step `B3.smoke.windows` (or downgrade the compat claim to "smoke-tested on Linux; Windows/WSL manual verification deferred to a follow-up").                |

## HIGH-severity findings

### B-H1 — `filelock.Timeout` does not accept a custom message

**File / section:** `docs/superpowers/plans/2026-06-22-operability-batch-plan.md` §B2.5, also `docs/superpowers/specs/2026-06-22-operability-batch-design.md` §4.

**Problem.** The plan's pseudocode does:

```python
raise Timeout(msg) from exc
```

But `filelock.Timeout.__init__` has signature `(self, lock_file: str) -> None` — it accepts a single positional `lock_file` string. Verified directly:

```
>>> from filelock import Timeout
>>> exc = Timeout('my very long custom message')
>>> exc.lock_file
'my very long custom message'
>>> str(exc)
"The file lock 'my very long custom message' could not be acquired."
```

Any downstream consumer that reads `exc.lock_file` (a common pattern: `tests/test_atomic_io.py:591`, `tests/test_bugfix_L1_L2_gate_marker.py:36` all import `Timeout`) will see the augmented prose as the lock-file path. The fixed string `"The file lock '...' could not be acquired."` template will also produce confusing nested quotes.

**Suggested patch.** Define a subclass in `core/evidence_io.py`:

```python
class GateLockTimeoutError(Timeout):
    """filelock.Timeout subclass carrying holder identity for operability."""
    def __init__(self, lock_file: str, *, holder: dict[str, Any] | None,
                 timeout: float) -> None:
        super().__init__(lock_file)
        self.holder = holder
        self.timeout_s = timeout
    def __str__(self) -> str:
        if self.holder:
            return (f"gate lock at {self.lock_file} not acquired within "
                    f"{self.timeout_s}s; held by PID={self.holder['pid']}, "
                    f"started_at={self.holder['started_at']}, "
                    f"host={self.holder.get('hostname','')}")
        return (f"gate lock at {self.lock_file} not acquired within "
                f"{self.timeout_s}s; holder unknown")
```

Raise `GateLockTimeoutError(str(lock_path), holder=…, timeout=…) from exc` instead of `Timeout(msg)`. Existing `except filelock.Timeout:` callers are unaffected by the subclassing.

### B-H2 — Plan misses the third `get_gate_lock` call site

**File / section:** `docs/superpowers/plans/2026-06-22-operability-batch-plan.md` §B2.1, §B2.5; `docs/superpowers/specs/2026-06-22-operability-batch-design.md` §3.

**Problem.** Plan §B2.1 says: `grep -n 'get_gate_lock\|GATE_LOCK' ... gate_orchestrator.py` — *only* — and "expect 2-3 hits". The actual ground truth, verified with a package-wide grep:

```
core/gate_orchestrator.py:291: with get_gate_lock(project_root):
core/gate_orchestrator.py:527: with get_gate_lock(project_root, timeout=3600.0):
core/system_gate.py:71:        with get_gate_lock(project_root, timeout=3600.0):
```

Three call sites, not two — the L1-followup fix (commit `02a96c4`) intentionally widened the lock to `system_gate.run_system_gate`. The plan leaves `system_gate.py` un-augmented, so `run_system_gate` lock timeouts continue to surface an opaque `filelock.Timeout`. Worse, `system_gate.py` is currently *not* in the plan's "files modified" list, so the implementer following the plan literally will miss it.

**Suggested patch.** Update the plan's pre-req grep to `grep -rn 'get_gate_lock' skills/bmad-story-automator/src/`, add `skills/bmad-story-automator/src/story_automator/core/system_gate.py` to spec §5 file table with `+8 LOC` for the augmentation, and add a B2.5b sub-step plus a fourth test (`test_run_system_gate_lock_timeout_includes_holder`) to the plan and to §6.2.

### B-H3 — `iso_now` lives in `core/utils.py`, not `core/common.py`

**File / section:** `docs/superpowers/plans/2026-06-22-operability-batch-plan.md` pre-req #3 + §B1.4 commentary; `docs/superpowers/specs/2026-06-22-operability-batch-design.md` §7 (timezone-offset risk row).

**Problem.** Both files state `iso_now()` lives in `core/common.py`. There are in fact **two** definitions:

- `core/common.py:23 — def iso_now()` — returns `now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")`.
- `core/utils.py:269 — def iso_now()` — returns `now_utc_z()` (also second-precision UTC).

And the file that B1 actually edits (`core/evidence_io.py`) imports from `utils`, not `common`:

```
core/evidence_io.py:31: from .utils import ensure_dir, iso_now, write_atomic
```

The two `iso_now` implementations *currently* return the same string shape, but they could diverge over time and the spec's H4-related reasoning becomes wrong if a maintainer reads `common.py` instead. Additionally, **both** are second-precision, which directly invalidates spec §4's "tens to hundreds of milliseconds" lag rationale — the recorded `started_at` is *already* truncated to whole seconds.

**Suggested patch.** Plan pre-req #3: change `core/common.py` to `core/utils.py`. Spec §7: revise the timezone-offset risk row to cite `core/utils.py::iso_now`. Spec §4: re-derive the tolerance, noting that second-precision iso → up to 1.0s truncation error alone.

### B-H4 — 5.0s tolerance rationale is mis-derived

**File / section:** `docs/superpowers/specs/2026-06-22-operability-batch-design.md` §4 and §7 (first risk row).

**Problem.** §4 claims the 5.0s tolerance "covers worst-case GC pause / fork overhead" *between* `psutil.Process().create_time()` and `iso_now()`. But in `core/evidence_io.write_gate_marker`:

```python
try:
    start_time: float | None = psutil.Process().create_time()  # kernel ts
except (psutil.Error, OSError):
    start_time = None
marker: dict[str, Any] = {
    "gate_id": gate_id,
    ...,
    "started_at": iso_now(),  # walltime when marker dict is built
    ...
}
```

`psutil.Process().create_time()` is **the start time of the current Python process** (frequently *seconds* old by the time the orchestrator runs, since Python startup, imports, env setup all happened before `write_gate_marker` is called), while `iso_now()` is **wall-clock now**, at marker-write. The gap between the two is therefore *not* "GC pause" — it is "however long the process has been alive before reaching this code". On a long-lived orchestrator host that survives multiple gates, that gap could be minutes.

This matters because B1's branch compares `psutil.Process(pid).create_time()` (i.e. the *original* process start, which equals the value stored in `start_time` — the L1+J-03 path) against the marker's `started_at` (i.e. wall-clock at marker-write, which is *unrelated* to process-start). With a 5.0s tolerance, the B1 fallback would falsely flag every legacy marker recorded more than 5s after process-start as "PID reused" — i.e. nearly every real-world marker.

**Suggested patch.** Either:
1. Re-anchor B1's comparison: use `started_at` as a lower-bound on "this PID *was* alive at this wall-clock instant", and check that `create_time(pid) ≤ started_at_epoch + tolerance` and `create_time(pid) ≥ started_at_epoch - max_orchestrator_uptime`. Or:
2. Drop the B1 branch entirely for legacy markers (those *without* `start_time`) and rely only on `pid_exists` + hostname (the pre-J-03 behavior). The legacy-marker PID-reuse window was already "survivable" per round-2 audit; B1 may be a wash if implemented wrongly.

Pick one and re-state the constant + tolerance with a worked example in §4.

### B-H5 — `describe_lock_holder` not declared in `docs/spec/frozen-gate-surface.md`

**File / section:** `docs/spec/frozen-gate-surface.md` (`core/evidence_io.py` section); `docs/superpowers/specs/2026-06-22-operability-batch-design.md` §10.

**Problem.** The frozen-surface doc is the authoritative "what not to break / not to silently add" list for the gate subsystem. The current `core/evidence_io.py` section lists six public symbols (`GateMarkerCorruptedError`, `read_gate_marker`, `can_reuse_gate_file`, `write_gate_marker`, `clear_gate_marker`, `persist_gate_file`). B2 introduces a *seventh* public symbol (`describe_lock_holder`) that other modules import (`gate_orchestrator.py`, possibly `system_gate.py` once H2 is fixed). Adding it without declaring it forks the contract.

**Suggested patch.** Either:
1. Demote to `_describe_lock_holder` (private; only called from the same module — but then `gate_orchestrator` can't import it without leading-underscore-import smell). Easiest if `_log_lock_timeout(project_root, lock_path, timeout, exc)` is the *only* public-ish helper, and it lives in `gate_orchestrator.py` and inlines the marker read.
2. Or: add a bullet to `docs/spec/frozen-gate-surface.md` under `core/evidence_io.py`:
   `- describe_lock_holder(project_root) -> dict | None — operability helper for lock-timeout diagnostics; never raises.`
   Also list `GateLockTimeoutError` (from B-H1) there.

Pick (2) if observability is expected to widen further; pick (1) if minimizing public surface is the priority.

### B-H6 — `gate_orchestrator.py` is already 718 LOC; +18 ≈ 736 LOC

**File / section:** `docs/superpowers/specs/2026-06-22-operability-batch-design.md` §11 LOC table.

**Problem.** Spec §11 claims `gate_orchestrator.py` is "~640" pre-batch and "~660" post-batch. The verified count at HEAD `5424b7e` is **718 LOC pre-batch**. The CLAUDE.md hard guardrail says "500-LOC soft limit per Python module"; the spec rationalizes the existing overrun as "long-running split-when-touched-broadly status" but cites no waiver. A future audit-floor pin on the file would now be 718 + 18, against a soft limit of 500 — a +47 % overrun.

**Suggested patch.** Either:
1. Extract the B2 timeout-handling helper (and `GateLockTimeoutError` from B-H1) into a new sibling module `core/gate_lock_observability.py` (~35 LOC). This keeps `gate_orchestrator.py` at +0 LOC for B2 and lets the implementer split the existing overrun *partially* over time.
2. Or: add an explicit, dated waiver line to `docs/spec/frozen-gate-surface.md`:
   `- core/gate_orchestrator.py: soft-limit waiver — currently 718 LOC; next broad refactor must split adjudication out (target ≤ 500 LOC by Mxx).`
   Without a written waiver, the next milestone that touches the file is forced into a split it didn't budget for.

Prefer (1) — it costs ~10 LOC of glue but converges the LOC budget. (2) is a stop-gap.

## MED-severity findings — table only

(See main findings table above for B-M1 through B-M12. Defer to enhancement OR backlog per item.)

| ID | Disposition |
|---|---|
| B-M1 (zombie semantics) | enhancement (spec bullet + test) |
| B-M2 (python/ruff PATH) | enhancement (hook robustness) |
| B-M3 (PYTHONPATH overwrite) | enhancement (one-line hook fix) |
| B-M4 (M11 gate not in hook) | enhancement (one-line hook addition; aligns with spec promise) |
| B-M5 (no uninstaller) | enhancement (ship `scripts/uninstall-hooks.sh`) |
| B-M6 (missing-marker message) | enhancement (clearer message) |
| B-M7 (augmentation drift) | enhancement (extract helper) |
| B-M8 (log-flood) | backlog if not addressed in first cut |
| B-M9 (X_OK on Windows) | enhancement (better test predicate) |
| B-M10 (4055 vs 4070) | enhancement (re-pin baseline) |
| B-M11 (lock_file attribute risk) | enhancement (re-grep; ties to B-H1) |
| B-M12 (audit-floor check) | enhancement (explicit plan step) |

## LOW-severity findings — table only

(See main findings table above for B-L1 through B-L10. Track as backlog unless trivially fixable.)

| ID | Disposition |
|---|---|
| B-L1 (redundant `Z` replace) | backlog (cleanliness) |
| B-L2 (both fields present test) | enhancement (1 test) |
| B-L3 (foreign-host + B1 test) | enhancement (1 test) |
| B-L4 (broken smoke step) | enhancement (fix smoke recipe) |
| B-L5 (direnv) | backlog (CONTRIBUTING.md note) |
| B-L6 (spec wording) | enhancement (3 word edits) |
| B-L7 (install-hooks backup) | backlog |
| B-L8 (provenance filename typo) | enhancement (1-char path edit) |
| B-L9 (test design comment) | enhancement (clarify comment) |
| B-L10 (compat claim overreach) | enhancement (downgrade claim or add step) |

## Recommended enhancement to spec/plan (before implementation)

Apply the following BEFORE the first `git commit` of B1/B2/B3:

1. **Spec §3 + §4 + plan §B2.5: rewrite the B2 raise-pattern around `GateLockTimeoutError(Timeout)`** (closes B-H1). The exception subclass owns the message, holder attrs, and timeout. Existing `except filelock.Timeout` callers still match. Add `GateLockTimeoutError` to `docs/spec/frozen-gate-surface.md` per B-H5.
2. **Spec §5 + plan §B2.1, §B2.5, §6.2: add `core/system_gate.py:71` as a third augmentation site** with a corresponding `test_run_system_gate_lock_timeout_includes_holder` test (closes B-H2).
3. **Plan pre-req #3 + §B1.4 commentary + spec §7: correct `core/common.py` → `core/utils.py`** for `iso_now`'s home (closes B-H3).
4. **Spec §4: re-derive the 5.0s tolerance** with an explicit worked example, OR retreat the legacy-marker B1 branch behind a `pid_exists`-only fallback if the wall-clock-vs-process-start mismatch cannot be reconciled (closes B-H4).
5. **Spec §10 + new bullet in `docs/spec/frozen-gate-surface.md`: declare `describe_lock_holder`** (or rename to `_describe_lock_holder` and inline) (closes B-H5).
6. **Spec §11: ship the helper into a sibling `core/gate_lock_observability.py`** (~35 LOC) to keep `gate_orchestrator.py` from growing further. Add an explicit dated waiver if the split is deferred (closes B-H6).
7. **Plan §B3.4: harden the pre-commit hook** for Windows git-bash / venv ruff / PYTHONPATH preservation (closes B-M2, B-M3); add `bash scripts/m11-vocabulary-gates.sh` invocation (closes B-M4).
8. **Plan §B3.6 + new §B3.7b: ship `scripts/uninstall-hooks.sh`** (closes B-M5).
9. **Plan §B.close.1: explicit audit-floor invariant verification** (closes B-M12).
10. **Spec §6.3: re-pin baseline test count** from a fresh `unittest discover` at HEAD (closes B-M10).
11. **Plan §B2.4: distinguish "marker missing" from "marker corrupted"** in the holder-unknown message (closes B-M6).
12. **Spec §6.2: add B-L2 + B-L3 + B-M1 tests** for back-compat coverage of `start_time`+`started_at`, foreign-host short-circuit, and zombie-PID semantics.

Estimated cost of the enhancement pass: **~45 minutes** (spec edits) + **~30 minutes** (plan edits) + **~0 minutes of implementation** — all changes land in the spec/plan files only. Net effect: B1 either gets a defensible tolerance or is scoped down; B2 ships as a real subclass instead of a half-broken message; B3 actually delivers on the "would have caught D-04" promise via the M11 gate, on every supported platform.

## Verdict

**needs-enhancement** → **enhancements applied (2026-06-22)**

Three HIGH defects (B-H1 broken raise pattern, B-H2 missed call site, B-H3 wrong source file) are spec/plan-blockers that would ship a non-working B2 and an incorrectly-justified B1. Three more HIGHs (B-H4 mis-derived tolerance, B-H5 frozen-surface contract, B-H6 LOC budget) need spec-level resolutions before code is written, not workarounds during review. The med- and low-severity findings are nearly all 1- to 5-line spec/plan edits; once H1–H6 are addressed and the enhancement list above is applied, the milestone is **ready-to-implement**.

## Resolved (enhancements applied 2026-06-22)

All 6 HIGH-severity findings have been patched into `docs/superpowers/specs/2026-06-22-operability-batch-design.md` and `docs/superpowers/plans/2026-06-22-operability-batch-plan.md`:

- ~~**B-H1**~~ — `GateLockTimeoutError(filelock.Timeout)` subclass replaces broken `raise Timeout(msg)` pattern; defined in new sibling module `core/gate_lock_observability.py`; `exc.lock_file` stays as the lock path; stable `holder` + `timeout_s` attributes declared in frozen-gate-surface.
- ~~**B-H2**~~ — Third `get_gate_lock` call site at `core/system_gate.py:71` enumerated in spec §5 + §3 architecture; new `test_run_system_gate_lock_timeout_includes_holder` test; plan B2.1 pre-req grep widened to package-wide.
- ~~**B-H3**~~ — `iso_now()` correctly attributed to `core/utils.py` in plan pre-req #3 and spec §7 risk row; `core/common.py` reference removed.
- ~~**B-H4**~~ — 5.0s tolerance dropped; v2 rule with two-sided bound `[started_at - MAX_ORCHESTRATOR_UPTIME_S, started_at + ISO_TRUNCATION_S]` derived from actual code path; worked example in spec §4; plan B1.4 pseudocode updated.
- ~~**B-H5**~~ — `GateLockTimeoutError` added to `docs/spec/frozen-gate-surface.md` via plan step B2.8b; `_describe_lock_holder` kept underscore-private; no public-symbol drift.
- ~~**B-H6**~~ — Observability helpers extracted into new sibling `core/gate_lock_observability.py` (~40 LOC); `gate_orchestrator.py` net delta is +6 LOC; soft-limit waiver line documented in frozen-gate-surface.md for the pre-existing 718-LOC overrun; spec §11 LOC table corrected.

MED + LOW gaps (B-M1..B-M12, B-L1..B-L10) are tracked in the new "Tracked enhancements" section appended to the spec; the majority are resolved inline as part of the HIGH patches (B-M1 zombie test, B-M4 M11 hook gate, B-M5 uninstall script, B-M6 missing-vs-corrupt distinction, B-M7 helper extraction, B-M9 stat-based permission check, B-M10 baseline pinning, B-M11 lock_file grep, B-L2/B-L3 back-compat tests, B-L4 fixed smoke recipe, B-L7 prior-hooksPath capture, B-L8 provenance filename, B-L9 test comment clarification, B-L10 compat-claim downgrade); B-M2, B-M3, B-M8, B-M12 are inline plan polish; B-L1, B-L5 are backlog.
