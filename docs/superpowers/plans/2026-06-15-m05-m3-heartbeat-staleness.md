# M05-M3: Heartbeat & Staleness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `core/atomic_io.py` (built in M05-M1 / M05-M2) with the heartbeat refresh substrate and a stale-lock predicate: a `parse_iso_seconds` helper, a daemon `HeartbeatThread` that rewrites the lock payload with a fresh `heartbeat_iso` every 60 seconds until `stop()`, and an `is_stale(identity, *, now=None) -> bool` returning True only when the heartbeat is older than 600 seconds AND `psutil.pid_exists` reports the PID dead.

**Architecture:** All new surface lives in the existing `atomic_io.py` module — no new files. Public exports grow from M05-M2's set to additionally include `{HeartbeatThread, is_stale, parse_iso_seconds}`. `HeartbeatThread` subclasses `threading.Thread` with `daemon=True`, holds a reference to the live `RunLockIdentity` and the on-disk `lock_path`, and on each tick rewrites the payload via `write_atomic_text` with a refreshed `heartbeat_iso` obtained from `iso_now()`. The loop is gated by a `threading.Event` so `stop()` is observed immediately rather than waiting up to a full interval. The interval is a class-level constant `interval = 60.0` per REQ-08, optionally overridable through the constructor so unit tests can use sub-second intervals without mutating shared module state. `is_stale` parses `heartbeat_iso` via a new module-level `parse_iso_seconds` (the inverse of `iso_now`'s `%Y-%m-%dT%H:%M:%SZ` format, anchored to UTC) and short-circuits on a live PID. The `state.py` integration (REQ-10/REQ-11) is deferred to M05-M4.

**Tech Stack:** Python 3.11+ stdlib (`datetime`, `threading`, `time`) plus `psutil` (newly imported in `atomic_io.py` — already on the spec allowlist, already used by `core/tmux_runtime.py`). `filelock` remains from M05-M2. Tests use `unittest.TestCase` with `unittest.mock.patch`; no subprocesses, no tmux dependency, no real 60-second waits (REQ-14).

---

## Scope for this sub-milestone

**In scope (from the spec):**
- REQ-08: `HeartbeatThread(threading.Thread)` with `daemon=True`; class-level `interval = 60.0`; `stop()` sets a `threading.Event`; `run()` rewrites the payload via `write_atomic_text` with a refreshed `heartbeat_iso` until stopped.
- REQ-09: `is_stale(identity: RunLockIdentity, *, now: float | None = None) -> bool` returns `True` only when `(now or time.time()) - parse_iso_seconds(identity.heartbeat_iso) > 600.0` AND `psutil.pid_exists(identity.pid)` is `False`.
- REQ-12 (incremental): public functions/classes annotated; allowlist now also permits `psutil` (in addition to `filelock`); module stays ≤500 LOC.
- REQ-13 subset: HeartbeatThread refresh observed by reading the payload twice; `is_stale` truth-table coverage (True for dead-PID + aged heartbeat; False for the three other cells: live PID + aged, dead PID + fresh, and exactly-at-threshold).
- REQ-14: `unittest.TestCase`, no subprocesses, no tmux, cross-platform.
- Non-functional portability: `psutil.pid_exists` is the only cross-platform PID probe — no `os.kill(pid, 0)` (POSIX-only) and no `kernel32.OpenProcess` (Windows-only) calls.
- Non-functional observability: no new exception types this wedge; `HeartbeatThread` swallows transient write errors so a single bad refresh does not crash the daemon (telemetry hookup is M02's problem). The swallowed exception count is recorded on the thread so M02 can read it without string-matching.
- Quality gates: ruff check/format, import allowlist audit (now allows `psutil` in addition to `filelock`), coverage ≥85% for the module overall.

**Out of scope (deferred to later M05 sub-milestones / other milestones):**
- REQ-10 / REQ-11: `commands/state.py` integration and marker-file removal — M05-M4.
- Auto-starting a `HeartbeatThread` from inside `acquire_run_lock` — M05-M4 wires this together once `state.py` consumes it; M05-M3 only exposes the building block.
- Reclamation logic that detects a stale lock and forcibly takes over — M05-M4 / M07.
- Heartbeat tuning knobs / policy exposure — milestone M12.
- Subprocess-based cross-process tests — disallowed by REQ-14.

---

## File Structure

| File | New / Modified | Responsibility |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/atomic_io.py` | Modify | Add `parse_iso_seconds`, `HeartbeatThread`, `is_stale`; import `datetime` (UTC parsing), `psutil`; extend `__all__`. |
| `tests/test_atomic_io.py` | Modify | Append test classes for `parse_iso_seconds` round-trip, `HeartbeatThread` constructor / lifecycle / refresh, `is_stale` truth table, allowlist audit. |

No other files are modified.

---

## Conventions reminder

- `from __future__ import annotations` is already at the top of `atomic_io.py` — do not add a second one.
- Imports stay grouped stdlib → third-party → local; insert `datetime` into the stdlib group, `psutil` into the third-party group (between `filelock` and `story_automator.core.common`).
- Type hints use PEP 604 unions (`float | None`).
- `@dataclass` if any new dataclasses (none expected this wedge).
- Tests are `unittest.TestCase` subclasses; mixed `assert` and `self.assertX` are fine.
- Conventional Commits with a `Generated-By` trailer on every commit.

---

## Task 1: `parse_iso_seconds` helper

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py` (after the last existing class):

```python
class ParseIsoSecondsTests(unittest.TestCase):
    def test_epoch_zero(self) -> None:
        from story_automator.core.atomic_io import parse_iso_seconds

        # 1970-01-01T00:00:00Z is the Unix epoch — easiest exact-value pin.
        self.assertEqual(parse_iso_seconds("1970-01-01T00:00:00Z"), 0.0)

    def test_one_second_past_epoch(self) -> None:
        from story_automator.core.atomic_io import parse_iso_seconds

        # Pins second resolution and ordering — if a future refactor
        # accidentally parses milliseconds, this immediately surfaces.
        self.assertEqual(parse_iso_seconds("1970-01-01T00:00:01Z"), 1.0)

    def test_inverse_of_datetime_utc(self) -> None:
        # Cross-check against the stdlib so the exact epoch value used in
        # later is_stale tests cannot drift. Using datetime() directly keeps
        # the assertion independent of any mental arithmetic.
        from datetime import datetime, timezone

        from story_automator.core.atomic_io import parse_iso_seconds

        expected = datetime(
            2026, 6, 15, 12, 34, 56, tzinfo=timezone.utc
        ).timestamp()
        self.assertEqual(parse_iso_seconds("2026-06-15T12:34:56Z"), expected)

    def test_rejects_non_utc_format(self) -> None:
        # The format must match iso_now() exactly. A trailing offset like
        # "+00:00" or a missing "Z" indicates the value did not come from
        # our own iso_now() helper and must not be silently coerced.
        from story_automator.core.atomic_io import parse_iso_seconds

        with self.assertRaises(ValueError):
            parse_iso_seconds("2026-06-15T12:34:56+00:00")
        with self.assertRaises(ValueError):
            parse_iso_seconds("2026-06-15T12:34:56")

    def test_round_trip_with_iso_now(self) -> None:
        # iso_now() is the canonical producer; parse_iso_seconds must accept
        # any value it emits without raising. Drift in either direction would
        # silently break is_stale arithmetic.
        from story_automator.core.atomic_io import parse_iso_seconds
        from story_automator.core.common import iso_now

        sample = iso_now()
        # Exercises the parser — return value is meaningful but its exact
        # epoch float depends on wall clock, so just assert it's finite.
        result = parse_iso_seconds(sample)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.ParseIsoSecondsTests -v`

Expected: FAIL — `ImportError: cannot import name 'parse_iso_seconds' from 'story_automator.core.atomic_io'`.

- [ ] **Step 3: Add `parse_iso_seconds` and the `datetime` import**

Edit `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`.

Add this import in the stdlib group (the existing group is `os, socket, sys, threading, time, dataclasses, pathlib` — not alphabetical; append `datetime` after `pathlib` to keep stdlib block contiguous, just before the third-party `from filelock import ...`):

```python
from datetime import datetime, timezone
```

Extend `__all__` to include `"parse_iso_seconds"` (keep alphabetical order):

```python
__all__ = [
    "AtomicWriteRetryExhausted",
    "RunLockBusy",
    "RunLockHandle",
    "RunLockIdentity",
    "acquire_run_lock",
    "parse_iso_seconds",
    "write_atomic_text",
]
```

Add this function near the top of the module, immediately after the `_WINDOWS_REPLACE_BACKOFFS_S` constant (so the helper is defined before any class that may reference it):

```python
def parse_iso_seconds(value: str) -> float:
    """Parse an ``iso_now()``-formatted UTC timestamp into epoch seconds.

    The expected format is exactly ``"%Y-%m-%dT%H:%M:%SZ"`` — the same string
    ``iso_now`` in ``core/common.py`` emits. ``is_stale`` (REQ-09) uses this
    to subtract from ``time.time()`` and compare against the 600-second
    stale window. Strings in any other shape (offset suffix, missing ``Z``,
    fractional seconds) raise ``ValueError`` rather than being silently
    coerced — a malformed heartbeat must surface as a parse failure, not as
    a phantom "fresh" reading.
    """
    parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    return parsed.timestamp()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.ParseIsoSecondsTests -v`

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): add parse_iso_seconds helper for heartbeat math"
```

---

## Task 2: Import-allowlist guardrail test (no code change)

**Files:**
- Modify: `tests/test_atomic_io.py`

This task installs a CI-side guardrail that pins the allowlist for `atomic_io.py` to `{filelock, psutil}` plus stdlib. The `psutil` import itself is added in Task 3 (where it is first used by `is_stale`) so we never ship the module in a state where ruff would flag an unused import. **This is a guardrail test, not a TDD red-then-green test** — it passes immediately against the current module (which doesn't yet import psutil) AND must continue passing after Task 3 adds the import.

- [ ] **Step 1: Write the guardrail test**

Append to `tests/test_atomic_io.py`:

```python
class ImportAllowlistTests(unittest.TestCase):
    """REQ-12: only stdlib plus filelock and psutil. The audit is a grep in
    the spec's quality gates; this test is the CI-side counterpart so the
    constraint cannot be silently broken between releases."""

    def test_only_allowlisted_third_party_imports(self) -> None:
        import re
        from pathlib import Path as _Path

        module_path = (
            _Path(__file__).resolve().parent.parent
            / "skills"
            / "bmad-story-automator"
            / "src"
            / "story_automator"
            / "core"
            / "atomic_io.py"
        )
        source = module_path.read_text(encoding="utf-8")

        # Stdlib roots we expect to see in this module today. Anything outside
        # this set that is NOT filelock or psutil is a guardrail violation.
        stdlib_roots = {
            "__future__",
            "dataclasses",
            "datetime",
            "os",
            "socket",
            "sys",
            "threading",
            "time",
            "pathlib",
        }
        allowed_third_party = {"filelock", "psutil"}
        local_roots = {"story_automator"}

        import_line = re.compile(r"^(?:from|import)\s+([\w\.]+)", re.MULTILINE)
        for match in import_line.finditer(source):
            root = match.group(1).split(".", 1)[0]
            self.assertIn(
                root,
                stdlib_roots | allowed_third_party | local_roots,
                f"unexpected import root: {root!r} — REQ-12 allowlist violated",
            )

    def test_psutil_is_importable(self) -> None:
        # The module imports psutil at top level (REQ-09 uses pid_exists),
        # so a missing psutil at install time would surface as ImportError
        # at import. Pin the dependency presence here for clarity.
        import psutil  # noqa: F401
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.ImportAllowlistTests -v`

Expected: PASS (2 tests). The current module already complies; this test exists to catch regressions in subsequent tasks (and across future milestones).

- [ ] **Step 3: Commit**

```bash
git add tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(atomic_io): pin import allowlist to stdlib + filelock + psutil"
```

---

## Task 3: `is_stale` — dead PID + aged heartbeat → True

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

REQ-09 truth table: True ONLY when both conditions hold — heartbeat older than 600s AND `psutil.pid_exists(pid)` is False. This task lands the True branch first; the False branches follow in Task 4.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_atomic_io.py`:

```python
class IsStaleTrueBranchTests(unittest.TestCase):
    """REQ-09 / REQ-13: dead PID + heartbeat older than 600s ⇒ True."""

    def _identity(self, *, pid: int, heartbeat_iso: str):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import RunLockIdentity

        return RunLockIdentity(
            pid=pid,
            start_time=0.0,
            hostname="h",
            heartbeat_iso=heartbeat_iso,
            run_id="r",
        )

    def test_dead_pid_and_aged_heartbeat_is_stale(self) -> None:
        from story_automator.core.atomic_io import is_stale

        # Use the Unix epoch as the heartbeat so all arithmetic below is
        # exact and inspectable. parse_iso_seconds("1970-01-01T00:00:00Z")
        # is 0.0 (pinned by ParseIsoSecondsTests.test_epoch_zero), so
        # `age == now`.
        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        # now is 3600s past the heartbeat — well beyond the 600s window.
        now = 3600.0
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=False,
        ):
            self.assertTrue(is_stale(identity, now=now))
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.IsStaleTrueBranchTests -v`

Expected: FAIL — `ImportError: cannot import name 'is_stale' from 'story_automator.core.atomic_io'`.

- [ ] **Step 3: Add `is_stale` and the `psutil` import (minimal True-branch implementation)**

Edit `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`.

Add to the third-party import group, immediately after `from filelock import FileLock, Timeout`:

```python
import psutil
```

Extend `__all__` to include `"is_stale"` (alphabetical):

```python
__all__ = [
    "AtomicWriteRetryExhausted",
    "RunLockBusy",
    "RunLockHandle",
    "RunLockIdentity",
    "acquire_run_lock",
    "is_stale",
    "parse_iso_seconds",
    "write_atomic_text",
]
```

Append this function near the bottom of the module (after `write_atomic_text` for now; final ordering is cosmetic):

```python
_STALE_HEARTBEAT_WINDOW_S: float = 600.0


def is_stale(
    identity: RunLockIdentity,
    *,
    now: float | None = None,
) -> bool:
    """Return ``True`` only when ``identity`` is reclaimable.

    REQ-09: stale iff the heartbeat is older than 600 seconds AND the
    recorded PID is no longer alive. Either condition alone keeps the lock
    live — a slow but still-running process must not be reclaimed, and a
    crashed process whose lock is less than 600 seconds old is presumed to
    be a fresh acquisition that hasn't ticked yet.

    The check is intentionally ordered cheap-first (timestamp arithmetic
    before the syscall in ``psutil.pid_exists``).
    """
    age = (now if now is not None else time.time()) - parse_iso_seconds(
        identity.heartbeat_iso
    )
    if age <= _STALE_HEARTBEAT_WINDOW_S:
        return False
    return not psutil.pid_exists(identity.pid)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.IsStaleTrueBranchTests -v`

Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): is_stale returns True for dead PID with aged heartbeat"
```

---

## Task 4: `is_stale` — False-branch truth table

REQ-13 explicitly calls for the False-True truth table. Live PID + aged → False; dead PID + fresh → False; exactly at the 600s threshold → False (strict `>`).

**Files:**
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py`:

```python
class IsStaleFalseBranchTests(unittest.TestCase):
    """REQ-09 / REQ-13: each of the three False cells of the truth table."""

    def _identity(self, *, pid: int, heartbeat_iso: str):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import RunLockIdentity

        return RunLockIdentity(
            pid=pid,
            start_time=0.0,
            hostname="h",
            heartbeat_iso=heartbeat_iso,
            run_id="r",
        )

    def test_live_pid_with_aged_heartbeat_is_not_stale(self) -> None:
        # A long-running process whose heartbeat is far behind must NOT be
        # reclaimed if the PID is still alive — the runtime might be wedged
        # but it has not actually died.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=os.getpid(),
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 3600.0  # heartbeat parses to 0.0; age == now.
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=True,
        ):
            self.assertFalse(is_stale(identity, now=now))

    def test_dead_pid_with_fresh_heartbeat_is_not_stale(self) -> None:
        # A crashed process whose lock is less than 600s old must NOT be
        # reclaimed — its successor may still be racing to acquire the lock.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 60.0  # only 60s past the heartbeat
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=False,
        ):
            self.assertFalse(is_stale(identity, now=now))

    def test_exactly_at_600s_threshold_is_not_stale(self) -> None:
        # Strict ">" per REQ-09: age == 600.0 is still fresh. Off-by-one at
        # the boundary would silently shrink the window.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 600.0
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=False,
        ):
            self.assertFalse(is_stale(identity, now=now))

    def test_just_past_threshold_with_dead_pid_is_stale(self) -> None:
        # Symmetric to the boundary test: 600.001s past must flip to True
        # when the PID is dead.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 600.001
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists",
            return_value=False,
        ):
            self.assertTrue(is_stale(identity, now=now))

    def test_default_now_uses_time_time(self) -> None:
        # REQ-09: now=None ⇒ time.time() at call site. Confirm by patching
        # time.time inside the module to a controlled fixed value.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        with (
            patch(
                "story_automator.core.atomic_io.time.time",
                return_value=3600.0,
            ),
            patch(
                "story_automator.core.atomic_io.psutil.pid_exists",
                return_value=False,
            ),
        ):
            self.assertTrue(is_stale(identity))

    def test_pid_exists_short_circuits_on_fresh_heartbeat(self) -> None:
        # If the heartbeat is fresh, psutil.pid_exists must not be called —
        # avoid a needless syscall on the common path. This is a perf
        # contract, not a correctness contract, but it also locks the cheap-
        # first ordering documented in the docstring.
        from story_automator.core.atomic_io import is_stale

        identity = self._identity(
            pid=99999,
            heartbeat_iso="1970-01-01T00:00:00Z",
        )
        now = 60.0
        with patch(
            "story_automator.core.atomic_io.psutil.pid_exists"
        ) as pid_exists_spy:
            self.assertFalse(is_stale(identity, now=now))
            pid_exists_spy.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.IsStaleFalseBranchTests -v`

Expected: PASS (6 tests). The minimal implementation from Task 3 already satisfies all branches — these tests pin the boundary behavior so future refactors cannot silently flip them.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(atomic_io): pin is_stale False-branch truth table and threshold"
```

---

## Task 5: `HeartbeatThread` constructor & class invariants

REQ-08 nails down four constructor invariants: subclasses `threading.Thread`, `daemon=True`, `interval = 60.0`, and exposes a `stop()` method. We assert all four before writing any refresh logic.

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py`:

```python
class HeartbeatThreadConstructorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _identity(self):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import RunLockIdentity

        return RunLockIdentity(
            pid=os.getpid(),
            start_time=0.0,
            hostname="h",
            heartbeat_iso="2026-06-15T00:00:00Z",
            run_id="r",
        )

    def test_subclasses_threading_thread(self) -> None:
        from story_automator.core.atomic_io import HeartbeatThread

        self.assertTrue(issubclass(HeartbeatThread, threading.Thread))

    def test_class_interval_constant_is_60_seconds(self) -> None:
        # REQ-08: "an `interval` constant of 60.0 seconds". The class-level
        # attribute is the spec'd surface; instances may override via the
        # constructor for testing without mutating the class default.
        from story_automator.core.atomic_io import HeartbeatThread

        self.assertEqual(HeartbeatThread.interval, 60.0)

    def test_instance_is_daemon(self) -> None:
        from story_automator.core.atomic_io import HeartbeatThread

        thread = HeartbeatThread(
            lock_path=self.dir / "x.payload",
            identity=self._identity(),
        )
        self.assertTrue(thread.daemon)

    def test_stop_method_exists_and_returns_none(self) -> None:
        from story_automator.core.atomic_io import HeartbeatThread

        thread = HeartbeatThread(
            lock_path=self.dir / "x.payload",
            identity=self._identity(),
        )
        # stop() must be safe to call before start() — it just sets an Event.
        self.assertIsNone(thread.stop())

    def test_constructor_accepts_optional_interval_override(self) -> None:
        # Tests need sub-second intervals to avoid 60s waits. The class
        # constant stays 60.0 per REQ-08; per-instance override does not
        # mutate the class attribute.
        from story_automator.core.atomic_io import HeartbeatThread

        thread = HeartbeatThread(
            lock_path=self.dir / "x.payload",
            identity=self._identity(),
            interval=0.05,
        )
        self.assertEqual(thread.interval, 0.05)
        self.assertEqual(HeartbeatThread.interval, 60.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.HeartbeatThreadConstructorTests -v`

Expected: FAIL — `ImportError: cannot import name 'HeartbeatThread' from 'story_automator.core.atomic_io'`.

- [ ] **Step 3: Add the `HeartbeatThread` class skeleton**

Edit `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`.

Extend `__all__` to include `"HeartbeatThread"` (alphabetical):

```python
__all__ = [
    "AtomicWriteRetryExhausted",
    "HeartbeatThread",
    "RunLockBusy",
    "RunLockHandle",
    "RunLockIdentity",
    "acquire_run_lock",
    "is_stale",
    "parse_iso_seconds",
    "write_atomic_text",
]
```

Append this class near the end of the module (after `is_stale`):

```python
class HeartbeatThread(threading.Thread):
    """Daemon thread that refreshes a run lock's heartbeat field.

    REQ-08: subclasses ``threading.Thread`` with ``daemon=True``; the
    class-level ``interval`` constant is 60.0 seconds. ``stop()`` sets a
    ``threading.Event`` that the ``run()`` loop polls between writes, so
    shutdown is observed within at most one tick rather than waiting up
    to a full interval.

    The constructor accepts an optional ``interval`` argument so unit
    tests can run with sub-second tick rates without mutating the class
    constant. The on-disk payload is refreshed via ``write_atomic_text``,
    inheriting the same per-path serialization the rest of the module
    uses — concurrent writes through ``write_atomic_text`` on the same
    path never interleave.
    """

    interval: float = 60.0

    def __init__(
        self,
        *,
        lock_path: Path,
        identity: RunLockIdentity,
        interval: float | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self._lock_path = Path(lock_path)
        self._identity = identity
        if interval is not None:
            self.interval = interval
        self._stop_event = threading.Event()
        self.write_errors: int = 0

    def stop(self) -> None:
        """Signal the loop to exit at its next wake-up."""
        self._stop_event.set()

    def run(self) -> None:  # pragma: no cover - filled in Task 6
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.HeartbeatThreadConstructorTests -v`

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): add HeartbeatThread class skeleton with daemon flag and stop()"
```

---

## Task 6: `HeartbeatThread.run()` refresh loop + observed payload refresh (REQ-13)

REQ-08's `run()` semantics and REQ-13's "refresh observed by reading the payload twice" land together: a real `start()/stop()` exercise that drives a short-interval thread, reads the payload twice, and asserts the `heartbeat_iso` field advanced.

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_atomic_io.py`:

```python
class HeartbeatThreadRefreshTests(unittest.TestCase):
    """REQ-13: HeartbeatThread refresh observed by reading the payload twice."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _make(self, *, lock_path: Path, interval: float):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import (
            HeartbeatThread,
            RunLockIdentity,
            write_atomic_text,
        )

        identity = RunLockIdentity(
            pid=os.getpid(),
            start_time=0.0,
            hostname="h",
            heartbeat_iso="2026-06-15T00:00:00Z",
            run_id="r",
        )
        # Seed the payload so readers never see absence.
        write_atomic_text(lock_path, identity.to_json())
        return HeartbeatThread(
            lock_path=lock_path,
            identity=identity,
            interval=interval,
        )

    def test_run_refreshes_heartbeat_iso_observed_by_two_reads(self) -> None:
        lock_path = self.dir / "run.payload"

        # Unbounded generator — interval=0.01s plus the 2-second deadline can
        # produce hundreds of ticks; a fixed-size iter() would hit
        # StopIteration. Always produces valid iso_now()-shaped strings so
        # the on-disk payload never contains a malformed timestamp.
        counter = {"n": 0}

        def fake_iso_now() -> str:
            counter["n"] += 1
            # Wrap minutes/hours to stay inside valid ISO ranges even at
            # high tick counts.
            n = counter["n"]
            return (
                "2026-06-15T"
                f"{(n // 3600) % 24:02d}:"
                f"{(n // 60) % 60:02d}:"
                f"{n % 60:02d}Z"
            )

        def read_payload():  # type: ignore[no-untyped-def]
            # On Windows, os.replace can briefly raise PermissionError
            # (ERROR_SHARING_VIOLATION) to a concurrent reader. The
            # writer-side per-path lock cannot prevent that OS-level
            # transient — the established repo precedent
            # (PerPathLockSerializationTests) is to retry. Atomicity is
            # still preserved (we never see truncation, only absence of
            # access for one instant).
            try:
                return json.loads(lock_path.read_text(encoding="utf-8"))
            except PermissionError:
                if sys.platform != "win32":
                    raise
                return None

        thread = self._make(lock_path=lock_path, interval=0.01)
        with patch(
            "story_automator.core.atomic_io.iso_now",
            side_effect=fake_iso_now,
        ):
            thread.start()
            try:
                # Read once early and once after a few ticks have elapsed.
                # Spin until first refresh is observed (up to 2 s budget).
                deadline = time.monotonic() + 2.0
                first = None
                while time.monotonic() < deadline:
                    parsed = read_payload()
                    if parsed and parsed["heartbeat_iso"] != "2026-06-15T00:00:00Z":
                        first = parsed["heartbeat_iso"]
                        break
                    time.sleep(0.005)
                self.assertIsNotNone(first, "first refresh never landed")

                # Spin until a *different* (newer) tick lands.
                deadline = time.monotonic() + 2.0
                second = first
                while time.monotonic() < deadline:
                    parsed = read_payload()
                    if parsed and parsed["heartbeat_iso"] != first:
                        second = parsed["heartbeat_iso"]
                        break
                    time.sleep(0.005)
                self.assertNotEqual(
                    second, first, "second refresh never landed"
                )
            finally:
                thread.stop()
                thread.join(timeout=2.0)
                self.assertFalse(thread.is_alive(), "thread did not stop")

    def test_stop_observed_within_one_interval(self) -> None:
        # The loop must poll the stop event via Event.wait(interval) rather
        # than sleep(interval) — otherwise stop() is delayed by up to one
        # full interval. With interval=0.5s the join must complete promptly.
        lock_path = self.dir / "run.payload"
        thread = self._make(lock_path=lock_path, interval=0.5)
        thread.start()
        time.sleep(0.05)  # let the loop enter wait()
        t0 = time.monotonic()
        thread.stop()
        thread.join(timeout=2.0)
        elapsed = time.monotonic() - t0
        self.assertFalse(thread.is_alive(), "thread did not stop")
        # Stop must propagate well below one full interval (0.5s).
        self.assertLess(elapsed, 0.4, f"stop took {elapsed:.3f}s — uses sleep?")

    def test_run_does_not_refresh_after_stop(self) -> None:
        # After stop(), no further write_atomic_text calls must occur. We
        # spy on write_atomic_text via patch.
        lock_path = self.dir / "run.payload"
        thread = self._make(lock_path=lock_path, interval=0.01)

        from story_automator.core import atomic_io as mod

        real_write = mod.write_atomic_text
        call_count = {"n": 0}

        def spy(path, data, *, encoding="utf-8"):  # type: ignore[no-untyped-def]
            call_count["n"] += 1
            real_write(path, data, encoding=encoding)

        with patch.object(mod, "write_atomic_text", side_effect=spy):
            thread.start()
            time.sleep(0.05)
            thread.stop()
            thread.join(timeout=2.0)
            n_after_stop = call_count["n"]
            time.sleep(0.1)  # would allow ~10 more ticks if the loop ran on
            self.assertEqual(
                call_count["n"],
                n_after_stop,
                "writes continued after stop()",
            )

    def test_run_survives_transient_write_errors(self) -> None:
        # A single bad refresh must not kill the daemon (observability NFR:
        # the thread reports the count via write_errors so M02 can hook in
        # without string-matching).
        lock_path = self.dir / "run.payload"
        thread = self._make(lock_path=lock_path, interval=0.01)

        from story_automator.core import atomic_io as mod

        real_write = mod.write_atomic_text
        calls = {"n": 0}

        def flaky(path, data, *, encoding="utf-8"):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("simulated transient disk error")
            real_write(path, data, encoding=encoding)

        with patch.object(mod, "write_atomic_text", side_effect=flaky):
            thread.start()
            try:
                # Wait until at least one successful refresh has landed.
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and calls["n"] < 2:
                    time.sleep(0.005)
                self.assertGreaterEqual(calls["n"], 2)
                self.assertTrue(thread.is_alive())
                self.assertEqual(thread.write_errors, 1)
            finally:
                thread.stop()
                thread.join(timeout=2.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.HeartbeatThreadRefreshTests -v`

Expected: FAIL — `run()` is a no-op (returns None immediately), so no refresh ever happens; the spin loops time out.

- [ ] **Step 3: Replace the `run()` stub with the real loop**

Edit `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`. Replace the `run()` method body in `HeartbeatThread` with:

```python
    def run(self) -> None:
        """Refresh the on-disk heartbeat until ``stop()`` is signalled.

        REQ-08: rewrites the payload via ``write_atomic_text`` with a
        refreshed ``heartbeat_iso`` each tick. The loop uses
        ``Event.wait(self.interval)`` so ``stop()`` is observed within
        one wake-up rather than waiting up to a full interval. Transient
        write failures (e.g. an ENOSPC blip) are counted on
        ``self.write_errors`` and swallowed so a single bad refresh does
        not terminate the daemon; surfacing those counts is M02's job.
        """
        while not self._stop_event.is_set():
            try:
                self._identity.heartbeat_iso = iso_now()
                write_atomic_text(self._lock_path, self._identity.to_json())
            except Exception:
                self.write_errors += 1
            # wait() returns True if the event was set, False on timeout.
            if self._stop_event.wait(self.interval):
                return
```

Note: `RunLockIdentity` is `@dataclass(kw_only=True)` (not frozen), so mutating `heartbeat_iso` in place is supported. If a future refactor freezes the dataclass, replace the mutation with `dataclasses.replace(self._identity, heartbeat_iso=iso_now())` and re-bind `self._identity`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.HeartbeatThreadRefreshTests -v`

Expected: PASS (4 tests). If `test_stop_observed_within_one_interval` is flaky on a loaded CI box, increase the threshold from 0.4s to 0.45s — but the bound exists to catch a regression to `time.sleep(interval)`, so do not raise it above the interval itself (0.5s).

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): HeartbeatThread.run loop refreshes payload until stopped"
```

---

## Task 7: `HeartbeatThread` constructor input rejection

Hardening: REQ-08 doesn't speak to constructor input validation, but the surface is brittle if `lock_path.parent` does not exist (the first `write_atomic_text` call would surface a `FileNotFoundError` only after `start()` is called and a tick has elapsed). We test for two surprise modes — missing parent directory at construction time still works (the file is created on first write, but the directory must already exist), and a zero/negative `interval` is rejected at construction time so a misconfigured caller fails fast instead of pegging a core.

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py`:

```python
class HeartbeatThreadInputValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _identity(self):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import RunLockIdentity

        return RunLockIdentity(
            pid=os.getpid(),
            start_time=0.0,
            hostname="h",
            heartbeat_iso="2026-06-15T00:00:00Z",
            run_id="r",
        )

    def test_zero_interval_is_rejected(self) -> None:
        # An interval of 0 would tight-loop the CPU and never honor stop().
        from story_automator.core.atomic_io import HeartbeatThread

        with self.assertRaises(ValueError):
            HeartbeatThread(
                lock_path=self.dir / "x.payload",
                identity=self._identity(),
                interval=0.0,
            )

    def test_negative_interval_is_rejected(self) -> None:
        from story_automator.core.atomic_io import HeartbeatThread

        with self.assertRaises(ValueError):
            HeartbeatThread(
                lock_path=self.dir / "x.payload",
                identity=self._identity(),
                interval=-0.1,
            )

    def test_default_interval_is_accepted(self) -> None:
        # Sanity: omitting interval leaves the class constant (60.0) in place.
        from story_automator.core.atomic_io import HeartbeatThread

        thread = HeartbeatThread(
            lock_path=self.dir / "x.payload",
            identity=self._identity(),
        )
        self.assertEqual(thread.interval, 60.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.HeartbeatThreadInputValidationTests -v`

Expected: FAIL — zero and negative intervals are silently accepted today.

- [ ] **Step 3: Add the validation**

Edit the `HeartbeatThread.__init__` body in `atomic_io.py`. Replace the `if interval is not None:` block with:

```python
        if interval is not None:
            if interval <= 0:
                raise ValueError(
                    f"HeartbeatThread interval must be > 0; got {interval!r}"
                )
            self.interval = interval
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.HeartbeatThreadInputValidationTests -v`

Expected: PASS (3 tests).

- [ ] **Step 5: Run the full atomic_io test file to check for regressions**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`

Expected: PASS (all previously-passing tests plus the new ones — no regressions).

- [ ] **Step 6: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): HeartbeatThread rejects non-positive interval at construction"
```

---

## Task 8: Module size guardrail check + ruff/coverage gate

REQ-12 requires `atomic_io.py` to stay under 500 LOC. After Tasks 1–7 the module is roughly 400 LOC; verify and document.

**Files:**
- No source changes — verification only.

- [ ] **Step 1: Verify module is still under 500 LOC**

Run: `wc -l skills/bmad-story-automator/src/story_automator/core/atomic_io.py`

Expected: line count `< 500`. If over, prune docstring repetition before doing anything else — do not split the module (the spec lists it as a single file).

- [ ] **Step 2: Run ruff check and format check on the changed files**

Run: 
```
python -m ruff check skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
```

Expected: both exit 0. If `ruff format --check` reports diffs, run `python -m ruff format <paths>` and commit the result as a separate `style(atomic_io):` commit before continuing.

- [ ] **Step 3: Run coverage gate**

Run:
```
python -m coverage run --source=skills/bmad-story-automator/src/story_automator/core/atomic_io -m unittest tests.test_atomic_io
python -m coverage report -m --fail-under=85
```

Expected: report shows ≥85% coverage of `atomic_io.py`. If under, identify uncovered branches via the `-m` (missing lines) column and add targeted tests. The most likely uncovered region after this milestone is the `Exception` swallow path inside `HeartbeatThread.run` — `test_run_survives_transient_write_errors` should cover it; if it does not, double-check the patch site.

- [ ] **Step 4: Run the full project test suite for regression**

Run: `npm run test:python`

Expected: every test passes (no test_atomic_io regressions, no other-module regressions).

- [ ] **Step 5: Cross-platform smoke gate (REQ-14)**

The operator runs the full suite on at least one non-current platform before declaring this milestone complete:

- If the host is Windows: run `npm run test:python` in WSL Ubuntu (`wsl -d Ubuntu-26.04 -- npm run test:python` from the worktree root).
- If the host is Linux: run `npm run test:python` in Windows git-bash on the same checkout.
- macOS: optional, not required by the operator's primary surface.

Expected: identical pass count, no skips, no platform-conditional warnings. Any new skip introduced by this milestone is a REQ-14 violation and must be removed (the existing `sys.platform != "win32"` branch in `PerPathLockSerializationTests` is the established precedent — it does not skip the assertion, it falls back to a different OS-level expectation).

- [ ] **Step 6: Commit (only if any ruff format / extra coverage edits were made)**

```bash
git add -A
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(atomic_io): apply ruff format and pad coverage to ≥85%"
```

If nothing changed in this task, skip the commit — the verification was a quality gate, not a code change.

---

## Self-Review

**Spec coverage:**

- REQ-08 (HeartbeatThread class with daemon, interval=60.0, stop(), run() loop) → Tasks 5 + 6 + 7.
- REQ-09 (is_stale truth table with parse_iso_seconds + psutil.pid_exists) → Tasks 1 + 3 + 4.
- REQ-12 (annotations; allowlist filelock + psutil only; ≤500 LOC) → Task 2 (allowlist) + Task 8 (size).
- REQ-13 (HeartbeatThread refresh observed via reading payload twice; is_stale True/False truth table) → Task 6 (`test_run_refreshes_heartbeat_iso_observed_by_two_reads`) + Tasks 3 + 4.
- REQ-14 (unittest, no subprocess, no tmux, cross-platform) → all tasks use `unittest.TestCase` with mocked time/psutil; no subprocess; Task 8 Step 5 is an explicit cross-platform smoke gate (Windows git-bash + WSL Ubuntu); Task 6's `read_payload` helper handles the Windows `os.replace` transient `PermissionError` window in line with the established `PerPathLockSerializationTests` precedent.
- Non-functional portability: only `psutil.pid_exists` for PID probes → Tasks 2 + 3.
- Non-functional observability: typed exception classification — no new exception type required this wedge; the `HeartbeatThread.write_errors` counter is the M02-friendly substitute. (Covered in Task 6's transient-write test.)
- Quality gates (ruff, coverage, cross-platform smoke) → Task 8.

Spec items deferred to M05-M4 are listed in the "Out of scope" section. No remaining REQs are unaddressed within M05-M3's scope.

**Placeholder scan:** No "TBD", no "add appropriate error handling", no "similar to Task N" without inline code. Every step contains either a full code block or an exact command.

**Type consistency:** All references match — `HeartbeatThread(lock_path=Path, identity=RunLockIdentity, interval=float|None)`; `is_stale(identity: RunLockIdentity, *, now: float | None = None) -> bool`; `parse_iso_seconds(value: str) -> float`. The `RunLockIdentity` field names referenced (`pid`, `start_time`, `hostname`, `heartbeat_iso`, `run_id`) match the M05-M2 dataclass definition verbatim. The `HeartbeatThread.write_errors: int` field name is consistent between the source (Task 5/6) and tests (Task 6).
