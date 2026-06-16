# M05-M2: Run Lock Identity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `core/atomic_io.py` (built in M05-M1) with the cross-process run-lock substrate: a `RunLockIdentity` dataclass with deterministic JSON round-trip, an `acquire_run_lock` API backed by `filelock.FileLock` that writes the identity payload via `write_atomic_text` and returns a `RunLockHandle` context manager, and a typed `RunLockBusy` exception so future telemetry wiring can classify acquisition timeouts without string-matching.

**Architecture:** All new surface lives in the existing `atomic_io.py` module — no new files. The public exports grow from `{AtomicWriteRetryExhausted, write_atomic_text}` to additionally include `{RunLockIdentity, RunLockHandle, RunLockBusy, acquire_run_lock}`. The handle holds a live `filelock.FileLock` plus the payload `Path`; releasing it deletes the payload file (best-effort) and releases the FileLock. The lock file path is `str(lock_path) + ".lock"` (sibling to the payload file, owned by `filelock`). `RunLockIdentity` is a `@dataclass(kw_only=True)` whose `to_json` uses `compact_json` from `core/common.py` against a fixed-key dict so output is bytewise deterministic regardless of dataclass field order. Heartbeat refresh (`HeartbeatThread`) and stale detection (`is_stale`) are deferred to M05-M3; `state.py` integration is M05-M4.

**Tech Stack:** Python 3.11+ stdlib (`dataclasses`, `json`, `os`, `socket`, `time`, `pathlib`) plus `filelock` (newly imported in `atomic_io.py` — already on the spec allowlist and already used by `core/telemetry_emitter.py`). `psutil` is allowlisted but unused in this wedge — it belongs to M05-M3 (`is_stale`). Tests use `unittest.TestCase` with `unittest.mock.patch`; no subprocesses (REQ-14).

---

## Scope for this sub-milestone

**In scope (from the spec):**
- REQ-05: `RunLockIdentity` `@dataclass(kw_only=True)` with fields `pid: int`, `start_time: float`, `hostname: str`, `heartbeat_iso: str`, `run_id: str`; `to_json(self) -> str` using `compact_json`.
- REQ-06: `acquire_run_lock(lock_path: Path, *, run_id: str, timeout: float = 0.0) -> RunLockHandle`; wraps `filelock.FileLock(str(lock_path) + ".lock")`; writes identity payload via `write_atomic_text`; returns a context-manager handle.
- REQ-07: `heartbeat_iso` via `iso_now()` (from `core/common.py`), `start_time` via `time.time()`, `hostname` via `socket.gethostname()`, `pid` via `os.getpid()`.
- REQ-12 (incremental): public functions/classes annotated; allowlist extended to include `filelock` (still no third-party imports beyond `filelock` + `psutil`); module stays ≤500 LOC.
- REQ-13 subset: `RunLockIdentity` round-trip JSON; `acquire_run_lock` happy-path test; `RunLockBusy` raised on simulated timeout.
- REQ-14: `unittest.TestCase`, no subprocesses, no tmux, cross-platform.
- Non-functional concurrency safety: cross-process serialization is delegated to `filelock.FileLock` (library guarantee); the wrapper is tested for correct timeout-to-`RunLockBusy` translation and clean release.
- Non-functional observability: `RunLockBusy` typed exception exists and is raised exactly when acquisition times out.
- Quality gates: ruff check/format, import allowlist audit (now allows `filelock`), coverage ≥85% for the module overall.

**Out of scope (deferred to later M05 sub-milestones):**
- REQ-08: `HeartbeatThread` — M05-M3.
- REQ-09: `is_stale` and `psutil.pid_exists` — M05-M3.
- REQ-10–11: `commands/state.py` integration, marker-file deletion — M05-M4.
- Cross-process subprocess-based tests — disallowed by REQ-14; library-level behavior is trusted.
- Heartbeat tuning knobs / policy exposure — milestone M12.

---

## File Structure

| File | New / Modified | Responsibility |
|---|---|---|
| `skills/bmad-story-automator/src/story_automator/core/atomic_io.py` | Modify | Add `RunLockBusy`, `RunLockIdentity`, `RunLockHandle`, `acquire_run_lock`; import `filelock`, `dataclasses.dataclass`, `socket`; extend `__all__`. |
| `tests/test_atomic_io.py` | Modify | Append test classes for identity round-trip, acquire/release happy path, timeout → `RunLockBusy`, identity-field population, payload cleanup on exit. |

No other files are modified.

---

## Task 1: `RunLockBusy` exception type

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py`:

```python
class RunLockBusyExceptionTests(unittest.TestCase):
    def test_run_lock_busy_is_exported(self) -> None:
        from story_automator.core.atomic_io import RunLockBusy

        self.assertTrue(issubclass(RunLockBusy, Exception))

    def test_run_lock_busy_is_distinct_from_permission_error(self) -> None:
        # REQ-04 vs REQ-06: a Windows replace timeout is AtomicWriteRetryExhausted
        # (a PermissionError); a run-lock acquisition timeout is RunLockBusy.
        # They must NOT collapse onto each other so M02 telemetry wiring can
        # classify them by type without string-matching (observability NFR).
        from story_automator.core.atomic_io import (
            AtomicWriteRetryExhausted,
            RunLockBusy,
        )

        self.assertFalse(issubclass(RunLockBusy, PermissionError))
        self.assertFalse(issubclass(AtomicWriteRetryExhausted, RunLockBusy))
        self.assertFalse(issubclass(RunLockBusy, AtomicWriteRetryExhausted))

    def test_run_lock_busy_accepts_message(self) -> None:
        from story_automator.core.atomic_io import RunLockBusy

        err = RunLockBusy("lock /tmp/x.lock held by pid 42")
        self.assertIn("pid 42", str(err))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.RunLockBusyExceptionTests -v`
Expected: FAIL — `ImportError: cannot import name 'RunLockBusy' from 'story_automator.core.atomic_io'`.

- [ ] **Step 3: Add the exception type and extend `__all__`**

Edit `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`:

Change the `__all__` line near the top of the file from:

```python
__all__ = ["AtomicWriteRetryExhausted", "write_atomic_text"]
```

to:

```python
__all__ = [
    "AtomicWriteRetryExhausted",
    "RunLockBusy",
    "write_atomic_text",
]
```

Then immediately after the existing `AtomicWriteRetryExhausted` class, add:

```python
class RunLockBusy(Exception):
    """Raised when acquiring a run lock times out.

    Intentionally NOT a subclass of PermissionError or
    AtomicWriteRetryExhausted: a busy run lock means another holder is
    actively making progress (or recently crashed and has not yet been
    reclaimed by the stale-detection path added in M05-M3). Future M02
    telemetry consumers classify it by type, so it must remain distinct
    from the atomic-write retry-exhaustion failure mode.
    """
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.RunLockBusyExceptionTests -v`
Expected: PASS (3 tests).

Then run the full module to make sure nothing regressed:

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: PASS — every prior test plus 3 new tests.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): add RunLockBusy typed exception for acquire timeout"
```

---

## Task 2: `RunLockIdentity` dataclass with deterministic JSON round-trip

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py`:

```python
import json


class RunLockIdentityTests(unittest.TestCase):
    def _sample(self):  # type: ignore[no-untyped-def]
        from story_automator.core.atomic_io import RunLockIdentity

        return RunLockIdentity(
            pid=4242,
            start_time=1717000000.5,
            hostname="builder-01",
            heartbeat_iso="2026-06-14T12:34:56Z",
            run_id="run-abc-123",
        )

    def test_dataclass_requires_keyword_only_construction(self) -> None:
        # REQ-05 specifies @dataclass(kw_only=True). Positional construction
        # must raise TypeError so a future field reordering cannot silently
        # rebind callers passing positional args.
        from story_automator.core.atomic_io import RunLockIdentity

        with self.assertRaises(TypeError):
            RunLockIdentity(  # type: ignore[misc]
                4242,
                1717000000.5,
                "builder-01",
                "2026-06-14T12:34:56Z",
                "run-abc-123",
            )

    def test_to_json_is_compact(self) -> None:
        identity = self._sample()
        payload = identity.to_json()
        # compact_json uses (",", ":") separators — no whitespace between
        # tokens. Our sample values contain no spaces, so the WHOLE payload
        # must be whitespace-free.
        self.assertNotIn(" ", payload)
        self.assertNotIn("\n", payload)
        self.assertNotIn("\t", payload)

    def test_to_json_round_trips_via_json_loads(self) -> None:
        identity = self._sample()
        parsed = json.loads(identity.to_json())
        self.assertEqual(parsed, {
            "pid": 4242,
            "start_time": 1717000000.5,
            "hostname": "builder-01",
            "heartbeat_iso": "2026-06-14T12:34:56Z",
            "run_id": "run-abc-123",
        })

    def test_to_json_key_order_is_stable(self) -> None:
        # Two constructions in different field orders must yield byte-equal
        # JSON. This protects future readers parsing the file mid-write from
        # observing reordered keys across heartbeat refreshes.
        from story_automator.core.atomic_io import RunLockIdentity

        a = RunLockIdentity(
            pid=1,
            start_time=2.0,
            hostname="h",
            heartbeat_iso="2026-06-14T00:00:00Z",
            run_id="r",
        )
        b = RunLockIdentity(
            run_id="r",
            heartbeat_iso="2026-06-14T00:00:00Z",
            hostname="h",
            start_time=2.0,
            pid=1,
        )
        self.assertEqual(a.to_json(), b.to_json())

    def test_to_json_uses_compact_json_helper(self) -> None:
        # REQ-05 explicitly requires the compact_json helper from common.py;
        # patching it must be observable so we know the wiring is right.
        from story_automator.core.atomic_io import RunLockIdentity
        from unittest.mock import patch

        identity = self._sample()
        with patch(
            "story_automator.core.atomic_io.compact_json",
            return_value='{"sentinel":true}',
        ) as spy:
            self.assertEqual(identity.to_json(), '{"sentinel":true}')
            spy.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.RunLockIdentityTests -v`
Expected: FAIL — `ImportError: cannot import name 'RunLockIdentity'`.

- [ ] **Step 3: Implement the dataclass**

Edit `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`:

Extend the existing imports near the top — add `dataclass` import and the `compact_json` re-import. Insert this block after the existing `from pathlib import Path` line:

```python
from dataclasses import dataclass

from story_automator.core.common import compact_json
```

(Order: stdlib block stays first; the local import goes into a new local block per project conventions. If `from __future__ import annotations` is the only line before the stdlib block, leave it there.)

Extend `__all__` again to include `RunLockIdentity`:

```python
__all__ = [
    "AtomicWriteRetryExhausted",
    "RunLockBusy",
    "RunLockIdentity",
    "write_atomic_text",
]
```

Add the dataclass below `RunLockBusy`:

```python
@dataclass(kw_only=True)
class RunLockIdentity:
    """Identity payload written into a run lock file.

    Field order is fixed by REQ-05; ``to_json`` always emits keys in this
    same order so two constructions with permuted kwargs produce byte-equal
    output. That stability matters because a future ``HeartbeatThread``
    (M05-M3) will rewrite this payload roughly every 60 seconds and stale
    detectors may diff the bytes.
    """

    pid: int
    start_time: float
    hostname: str
    heartbeat_iso: str
    run_id: str

    def to_json(self) -> str:
        return compact_json(
            {
                "pid": self.pid,
                "start_time": self.start_time,
                "hostname": self.hostname,
                "heartbeat_iso": self.heartbeat_iso,
                "run_id": self.run_id,
            }
        )
```

> NOTE: we explicitly build the dict in fixed key order rather than using `dataclasses.asdict(self)`, because `asdict` preserves field declaration order but a future field rename or insertion could shift it. The hand-rolled dict makes the JSON shape an explicit contract enforced by the round-trip test.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.RunLockIdentityTests -v`
Expected: PASS (6 tests).

Then full module: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: PASS overall.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): add RunLockIdentity dataclass with deterministic JSON encoding"
```

---

## Task 3: `RunLockHandle` context manager + acquire happy path

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_atomic_io.py`:

```python
class AcquireRunLockHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_acquire_writes_payload_and_returns_handle(self) -> None:
        from story_automator.core.atomic_io import (
            RunLockHandle,
            RunLockIdentity,
            acquire_run_lock,
        )

        lock_path = self.dir / "run.lock-payload"
        handle = acquire_run_lock(lock_path, run_id="run-xyz")
        try:
            self.assertIsInstance(handle, RunLockHandle)
            # Payload file exists and is parseable JSON matching the
            # identity contract.
            self.assertTrue(lock_path.exists())
            parsed = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["run_id"], "run-xyz")
            self.assertEqual(parsed["pid"], os.getpid())
            self.assertIsInstance(parsed["start_time"], float)
            self.assertIsInstance(parsed["hostname"], str)
            self.assertRegex(
                parsed["heartbeat_iso"],
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
            )
            # The handle exposes the identity it wrote.
            self.assertIsInstance(handle.identity, RunLockIdentity)
            self.assertEqual(handle.identity.run_id, "run-xyz")
        finally:
            handle.release()

    def test_handle_is_a_context_manager_that_cleans_up(self) -> None:
        from story_automator.core.atomic_io import acquire_run_lock

        lock_path = self.dir / "run.lock-payload"
        with acquire_run_lock(lock_path, run_id="run-ctx") as handle:
            self.assertTrue(lock_path.exists())
            inside = handle.identity.run_id
        self.assertEqual(inside, "run-ctx")
        # On exit, the payload file is removed (best effort) and the
        # filelock sidecar is released. We don't assert the .lock file
        # is gone — filelock may keep an empty .lock file on disk on some
        # platforms, that is library-defined behavior.
        self.assertFalse(lock_path.exists())

    def test_lock_sidecar_path_is_payload_path_plus_dot_lock(self) -> None:
        # REQ-06 wording: filelock.FileLock(str(lock_path) + ".lock").
        # Patch FileLock so we can capture the path it was constructed with.
        from story_automator.core.atomic_io import acquire_run_lock
        from unittest.mock import MagicMock, patch

        lock_path = self.dir / "subdir" / "run.payload"
        lock_path.parent.mkdir(parents=True)

        captured_args: list[str] = []

        class FakeFileLock:
            def __init__(self, p: str, *args: object, **kwargs: object) -> None:
                captured_args.append(p)
                self._p = p

            def acquire(self, timeout: float = -1) -> None:
                return None

            def release(self, force: bool = False) -> None:
                return None

        with patch("story_automator.core.atomic_io.FileLock", FakeFileLock):
            handle = acquire_run_lock(lock_path, run_id="run-path")
            handle.release()

        self.assertEqual(captured_args, [str(lock_path) + ".lock"])

    def test_release_is_idempotent(self) -> None:
        from story_automator.core.atomic_io import acquire_run_lock

        lock_path = self.dir / "run.lock-payload"
        handle = acquire_run_lock(lock_path, run_id="run-idem")
        handle.release()
        # Double-release must not raise — the context-manager protocol may
        # call __exit__ after an explicit release in error paths.
        handle.release()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.AcquireRunLockHappyPathTests -v`
Expected: FAIL — `ImportError: cannot import name 'acquire_run_lock'`.

- [ ] **Step 3: Implement `RunLockHandle` and `acquire_run_lock`**

Edit `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`:

Extend the imports. Add `socket` to the stdlib block, and add `FileLock` + `Timeout` to the third-party block. Also add `iso_now` to the local import. Concretely, the import region should look like (preserving existing order, only ADDING what is missing):

```python
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock, Timeout

from story_automator.core.common import compact_json, iso_now
```

(If `dataclass` and `compact_json` were already imported in Task 2, keep them — only add `socket`, `FileLock`, `Timeout`, and `iso_now`.)

Extend `__all__` to its final shape:

```python
__all__ = [
    "AtomicWriteRetryExhausted",
    "RunLockBusy",
    "RunLockHandle",
    "RunLockIdentity",
    "acquire_run_lock",
    "write_atomic_text",
]
```

Add the handle and acquire function below `RunLockIdentity`:

```python
class RunLockHandle:
    """Context-manager handle returned by ``acquire_run_lock``.

    Holds the live ``filelock.FileLock``, the resolved payload ``Path``,
    and the ``RunLockIdentity`` written to disk. ``release`` (also invoked
    from ``__exit__``) is idempotent: it deletes the payload file
    best-effort and releases the FileLock exactly once.
    """

    def __init__(
        self,
        *,
        file_lock: FileLock,
        payload_path: Path,
        identity: RunLockIdentity,
    ) -> None:
        self._file_lock = file_lock
        self._payload_path = payload_path
        self._released = False
        self.identity = identity

    def __enter__(self) -> RunLockHandle:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        # Best-effort payload removal — the FileLock release is what
        # actually frees the next acquirer.
        _silent_unlink(self._payload_path)
        try:
            self._file_lock.release()
        except Exception:  # pragma: no cover - filelock defensive guard
            # filelock raises only on programmer error (release without
            # acquire); a no-op release on a partially-initialized handle
            # must not mask the original exception path.
            pass


def acquire_run_lock(
    lock_path: Path,
    *,
    run_id: str,
    timeout: float = 0.0,
) -> RunLockHandle:
    """Acquire a cross-process run lock at ``lock_path``.

    REQ-06: wraps ``filelock.FileLock(str(lock_path) + ".lock")``,
    acquires with the given ``timeout`` (seconds; 0.0 means no waiting),
    then writes a ``RunLockIdentity`` JSON payload to ``lock_path``
    via ``write_atomic_text``. Returns a ``RunLockHandle`` whose
    ``__exit__`` / ``release`` deletes the payload and releases the lock.

    Raises ``RunLockBusy`` if the underlying filelock raises ``Timeout``.

    The caller is responsible for ensuring ``lock_path.parent`` exists;
    this function does not auto-create directories so that a typo'd path
    fails fast rather than scattering empty lock files.
    """

    sidecar = str(lock_path) + ".lock"
    file_lock = FileLock(sidecar)
    try:
        file_lock.acquire(timeout=timeout)
    except Timeout as err:
        raise RunLockBusy(
            f"run lock at {lock_path} is busy (timeout={timeout}s)"
        ) from err

    try:
        identity = RunLockIdentity(
            pid=os.getpid(),
            start_time=time.time(),
            hostname=socket.gethostname(),
            heartbeat_iso=iso_now(),
            run_id=run_id,
        )
        write_atomic_text(Path(lock_path), identity.to_json())
    except BaseException:
        # Acquisition succeeded but payload write failed — release the
        # FileLock so we don't leak it to the next acquirer.
        try:  # pragma: no cover - defensive guard against double-release
            file_lock.release()
        except Exception:
            pass
        raise

    return RunLockHandle(
        file_lock=file_lock,
        payload_path=Path(lock_path),
        identity=identity,
    )
```

> SEMANTICS: `timeout=0.0` means "do not wait" — `filelock.FileLock.acquire(timeout=0)` raises `Timeout` immediately if held. Callers that want blocking acquisition pass a positive `timeout`; passing `timeout=-1` means "wait forever" per filelock's API and is allowed but not exercised in this milestone. The error message embeds `lock_path` and the timeout value so future M02 telemetry can attach structured fields without re-parsing.

> CONCURRENCY: `write_atomic_text` re-enters the per-path threading.Lock registry keyed on `Path(lock_path).resolve()`. That is correct: the calling thread already holds the cross-process `filelock` for that path, so the threading.Lock only adds in-process ordering on top. No deadlock — `threading.Lock` and `filelock.FileLock` are independent primitives.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.AcquireRunLockHappyPathTests -v`
Expected: PASS (4 tests).

Then full module: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v`
Expected: PASS overall.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(atomic_io): add acquire_run_lock returning RunLockHandle context manager"
```

---

## Task 4: Timeout translates to `RunLockBusy`

**Files:**
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_atomic_io.py`:

```python
class AcquireRunLockTimeoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_filelock_timeout_is_translated_to_run_lock_busy(self) -> None:
        from filelock import Timeout

        from story_automator.core.atomic_io import (
            RunLockBusy,
            acquire_run_lock,
        )
        from unittest.mock import patch

        lock_path = self.dir / "run.payload"

        class BusyFileLock:
            def __init__(self, p: str, *a: object, **kw: object) -> None:
                pass

            def acquire(self, timeout: float = -1) -> None:
                raise Timeout("simulated busy lock")

            def release(self, force: bool = False) -> None:
                return None

        with patch("story_automator.core.atomic_io.FileLock", BusyFileLock):
            with self.assertRaises(RunLockBusy) as ctx:
                acquire_run_lock(lock_path, run_id="run-busy", timeout=0.0)

        # The Timeout instance must be the __cause__ so callers diagnosing
        # the failure can drill down to the underlying filelock context.
        self.assertIsInstance(ctx.exception.__cause__, Timeout)
        # The payload file must NOT have been written — only the
        # FileLock raised, so no atomic write should have fired.
        self.assertFalse(lock_path.exists())

    def test_acquire_zero_timeout_does_not_block(self) -> None:
        # Real (non-mocked) lock contention: hold the lock once, attempt
        # to acquire again with timeout=0.0, expect RunLockBusy without
        # waiting. This exercises the integration with the real filelock
        # library on this platform (REQ-14: same code on all OSes).
        from story_automator.core.atomic_io import (
            RunLockBusy,
            acquire_run_lock,
        )

        lock_path = self.dir / "run.payload"
        outer = acquire_run_lock(lock_path, run_id="run-outer", timeout=0.0)
        try:
            # filelock is reentrant per-instance but NOT across instances
            # within the same process — a second FileLock object on the
            # same sidecar must time out. acquire_run_lock constructs a
            # fresh FileLock on each call, so this is the right shape.
            t0 = time.monotonic()
            with self.assertRaises(RunLockBusy):
                acquire_run_lock(lock_path, run_id="run-inner", timeout=0.0)
            elapsed = time.monotonic() - t0
            # Must return promptly — generous bound to absorb CI jitter.
            self.assertLess(elapsed, 2.0)
        finally:
            outer.release()
```

- [ ] **Step 2: Run tests to verify they fail or pass as appropriate**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.AcquireRunLockTimeoutTests -v`

The `test_filelock_timeout_is_translated_to_run_lock_busy` test should PASS already (Task 3 implemented the Timeout→RunLockBusy translation). The `test_acquire_zero_timeout_does_not_block` test should also PASS — filelock guarantees same-process distinct-instance contention.

If `test_acquire_zero_timeout_does_not_block` FAILS because filelock returns the same singleton handle (filelock >= 3.13 has an `is_singleton` knob that defaults False — meaning distinct instances DO contend), investigate before changing the test. Do NOT pass `is_singleton=True`; the default is what cross-process callers see.

- [ ] **Step 3: If tests pass, no implementation change needed.** Skip to commit.

- [ ] **Step 4: Commit**

```bash
git add tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(atomic_io): cover RunLockBusy translation and zero-timeout contention"
```

---

## Task 5: Identity-field population from real OS sources

**Files:**
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_atomic_io.py`:

```python
class IdentityPopulationTests(unittest.TestCase):
    """REQ-07: heartbeat_iso via iso_now(), start_time via time.time(),
    hostname via socket.gethostname(), pid via os.getpid()."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_identity_fields_populated_from_canonical_helpers(self) -> None:
        from story_automator.core.atomic_io import acquire_run_lock
        from unittest.mock import patch

        lock_path = self.dir / "run.payload"

        with patch(
            "story_automator.core.atomic_io.os.getpid", return_value=9999
        ), patch(
            "story_automator.core.atomic_io.time.time", return_value=12345.5
        ), patch(
            "story_automator.core.atomic_io.socket.gethostname",
            return_value="fake-host",
        ), patch(
            "story_automator.core.atomic_io.iso_now",
            return_value="2026-06-15T01:02:03Z",
        ):
            handle = acquire_run_lock(lock_path, run_id="run-pop")

        try:
            self.assertEqual(handle.identity.pid, 9999)
            self.assertEqual(handle.identity.start_time, 12345.5)
            self.assertEqual(handle.identity.hostname, "fake-host")
            self.assertEqual(handle.identity.heartbeat_iso, "2026-06-15T01:02:03Z")
            self.assertEqual(handle.identity.run_id, "run-pop")
            # The on-disk payload reflects the same identity bytes.
            self.assertEqual(
                json.loads(lock_path.read_text(encoding="utf-8")),
                {
                    "pid": 9999,
                    "start_time": 12345.5,
                    "hostname": "fake-host",
                    "heartbeat_iso": "2026-06-15T01:02:03Z",
                    "run_id": "run-pop",
                },
            )
        finally:
            handle.release()
```

- [ ] **Step 2: Run tests to verify behavior**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.IdentityPopulationTests -v`
Expected: PASS — Task 3 already wires `os.getpid()`, `time.time()`, `socket.gethostname()`, and `iso_now()`. The test patches all four at the `atomic_io` namespace so it verifies the correct module-internal references.

If FAIL with "AttributeError: module ... has no attribute 'time'" or similar, the import in `atomic_io.py` is `from time import time` rather than `import time`. The implementation in Task 3 uses `import time` (and `import socket`), and references `time.time()` and `socket.gethostname()` so the patch targets above are valid. Verify and fix the imports if needed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(atomic_io): verify RunLockIdentity fields sourced from canonical helpers"
```

---

## Task 6: Payload write failure releases the FileLock

**Files:**
- Modify: `tests/test_atomic_io.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_atomic_io.py`:

```python
class AcquireRunLockFailureCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_payload_write_failure_releases_filelock(self) -> None:
        # If acquire_run_lock gets the FileLock but write_atomic_text
        # blows up, the FileLock MUST be released — otherwise the next
        # acquirer in this process (or a subsequent test) would deadlock
        # or get a stale RunLockBusy.
        from story_automator.core.atomic_io import acquire_run_lock
        from unittest.mock import patch

        lock_path = self.dir / "run.payload"
        release_calls: list[bool] = []
        original_acquire = []

        class TrackingFileLock:
            def __init__(self, p: str, *a: object, **kw: object) -> None:
                self.p = p
                self.acquired = False

            def acquire(self, timeout: float = -1) -> None:
                self.acquired = True
                original_acquire.append(True)

            def release(self, force: bool = False) -> None:
                release_calls.append(self.acquired)

        with patch("story_automator.core.atomic_io.FileLock", TrackingFileLock), \
             patch(
                "story_automator.core.atomic_io.write_atomic_text",
                side_effect=OSError("simulated disk full"),
             ):
            with self.assertRaises(OSError):
                acquire_run_lock(lock_path, run_id="run-fail")

        self.assertEqual(original_acquire, [True])
        self.assertEqual(release_calls, [True])
```

- [ ] **Step 2: Run tests to verify behavior**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io.AcquireRunLockFailureCleanupTests -v`
Expected: PASS — the `except BaseException` cleanup branch added in Task 3 covers this case. If FAIL, the cleanup is missing — verify the Task 3 implementation has the `try / except BaseException: file_lock.release()` block around the payload write.

- [ ] **Step 3: Commit**

```bash
git add tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(atomic_io): release FileLock when payload write fails"
```

---

## Task 7: Quality gates — lint, format, import allowlist, module size, coverage

**Files:**
- Inspect (no edits unless gates fail): `skills/bmad-story-automator/src/story_automator/core/atomic_io.py`, `tests/test_atomic_io.py`

- [ ] **Step 1: Ruff check**

Run:

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/atomic_io.py \
  tests/test_atomic_io.py
```

Expected: exit 0. If failures arise, fix the source — do not suppress.

- [ ] **Step 2: Ruff format check**

Run:

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/atomic_io.py \
  tests/test_atomic_io.py
```

If it fails: run the format command without `--check` and re-run.

- [ ] **Step 3: Import allowlist audit**

Run on bash or git-bash:

```bash
grep -E "^(import|from) " skills/bmad-story-automator/src/story_automator/core/atomic_io.py
```

Expected output: only stdlib (`os`, `socket`, `sys`, `threading`, `time`, `dataclasses`, `pathlib`), the allowlisted `filelock`, and the local relative import from `story_automator.core.common`. No `psutil` yet — it joins in M05-M3. No other third-party.

The exact expected import lines (order may vary slightly with ruff formatting):

```
from __future__ import annotations
import os
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from filelock import FileLock, Timeout
from story_automator.core.common import compact_json, iso_now
```

- [ ] **Step 4: Module size guardrail**

Run on bash:

```bash
wc -l skills/bmad-story-automator/src/story_automator/core/atomic_io.py
```

On PowerShell:

```powershell
(Get-Content skills/bmad-story-automator/src/story_automator/core/atomic_io.py | Measure-Object -Line).Lines
```

Expected: ≤ 500. After M2 the file should still be well under 300 lines.

- [ ] **Step 5: Coverage gate**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m coverage run \
  --source=skills/bmad-story-automator/src/story_automator/core/atomic_io \
  -m unittest tests.test_atomic_io
python -m coverage report -m --fail-under=85
```

Expected: PASS (≥ 85%). If a specific branch is uncovered, add a focused test rather than lowering the gate. Common gaps to expect:
- The defensive `except Exception: pass` around `file_lock.release()` in failure paths is marked `# pragma: no cover` — keep it that way; it's defensive only.
- The `_silent_unlink` rare-OS-error branch was already excluded in M1.

- [ ] **Step 6: Full suite regression check**

Run: `npm run test:python`
Expected: PASS — every pre-existing test plus all `tests/test_atomic_io.py` cases discover and pass.

- [ ] **Step 7: Commit formatting fixes if any**

```bash
git add skills/bmad-story-automator/src/story_automator/core/atomic_io.py tests/test_atomic_io.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(atomic_io): ruff format pass for run-lock additions"
```

Skip the commit if no formatting changes were needed.

---

## Task 8: Cross-platform verification (Windows git-bash + WSL Ubuntu)

**Files:** none modified.

- [ ] **Step 1: Windows git-bash run**

From a git-bash prompt:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_atomic_io -v
```

Expected: all PASS. Pay particular attention to:
- `test_acquire_zero_timeout_does_not_block` — filelock on Windows uses `msvcrt` internally; the immediate-timeout semantics are what we depend on.
- `test_handle_is_a_context_manager_that_cleans_up` — payload deletion on Windows can fail if a reader has the file open. We assert `not lock_path.exists()` after exit; if a flake appears here, document the platform-specific behavior rather than disabling the assertion.

- [ ] **Step 2: WSL Ubuntu run (recommended)**

From WSL Ubuntu:

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_atomic_io -v
```

Expected: all PASS. The mock-based tests must be platform-agnostic.

- [ ] **Step 3: Final sign-off (no commit)**

Print a one-line confirmation in the dev log that the suite is green on at least one of {Windows git-bash, WSL Ubuntu}.

---

## Self-Review Checklist

- **Spec coverage:**
  - REQ-05: Task 2 — `@dataclass(kw_only=True)` with the exact field set; `to_json` uses `compact_json`.
  - REQ-06: Task 3 — `acquire_run_lock(lock_path, *, run_id, timeout=0.0) -> RunLockHandle`; wraps `FileLock(str(lock_path) + ".lock")`; writes payload via `write_atomic_text`; handle is a context manager that releases on `__exit__`.
  - REQ-07: Task 3 wires + Task 5 verifies — `os.getpid()`, `time.time()`, `socket.gethostname()`, `iso_now()` from `core.common`.
  - REQ-12 (incremental): Task 7 — allowlist now includes `filelock`; module size ≤500 LOC; all public surfaces annotated.
  - REQ-13 subset (RunLockIdentity round-trip JSON): Task 2 covers deterministic JSON, key order, and `compact_json` wiring.
  - REQ-14: All tests `unittest.TestCase`, no subprocesses, no tmux, no platform-conditional skips.
  - Non-functional concurrency: `acquire_run_lock` delegates to `filelock.FileLock`; Task 4's `test_acquire_zero_timeout_does_not_block` exercises real same-process contention.
  - Non-functional observability: `RunLockBusy` is a distinct typed exception (Task 1) and is raised exactly on `Timeout` translation (Task 4).
  - Quality gates: Task 7 covers ruff check/format, import allowlist, size, coverage; Task 8 covers cross-platform smoke.

- **Placeholder scan:** no "TBD"/"TODO"/"implement later"/"add appropriate error handling". All code blocks are concrete.

- **Type consistency:**
  - `RunLockIdentity(*, pid: int, start_time: float, hostname: str, heartbeat_iso: str, run_id: str)` — same in dataclass definition (Task 2), `acquire_run_lock` construction (Task 3), and assertions (Tasks 2–5).
  - `acquire_run_lock(lock_path: Path, *, run_id: str, timeout: float = 0.0) -> RunLockHandle` — same signature in all call sites and tests.
  - `RunLockHandle.release() -> None` and `RunLockHandle.identity: RunLockIdentity` — referenced consistently from Tasks 3, 4, 5, 6.
  - `RunLockBusy(Exception)` — checked in Task 1 (`not issubclass of PermissionError`); the spec says "typed exception" without specifying a parent, so plain `Exception` matches the observability NFR.

- **No drift between test patch targets and implementation imports:** Task 3 uses `import socket`, `import time`, `import os` and references `socket.gethostname()`/`time.time()`/`os.getpid()` — Tasks 5 and 6 patch `story_automator.core.atomic_io.socket.gethostname`, `.time.time`, `.os.getpid`, and `.iso_now`, which match.

---

## Notes for the implementer

1. **Why not subclass `RunLockBusy` from `TimeoutError`?** `TimeoutError` is a stdlib `OSError` subclass. Run-lock contention is not an OS-level timeout — it's a higher-level "another holder owns this" signal. Keeping `RunLockBusy(Exception)` lets M02 telemetry classify it as a separate failure class without OS-level collateral.

2. **Why `from filelock import FileLock, Timeout`?** Importing `Timeout` directly into the module namespace lets us catch it precisely and lets tests patch `FileLock` to raise the real `Timeout` without importing it themselves. The patched namespace target (`story_automator.core.atomic_io.FileLock`) follows the test convention already established in M1.

3. **Why does the handle delete the payload file on release?** The payload is identity information about the *current* holder. Once the lock is released, that payload is stale and could mislead a future stale-detection consumer (M05-M3). Best-effort deletion (silent on `FileNotFoundError`) keeps the lifecycle simple. Note: this does NOT delete the `.lock` sidecar; that's owned by `filelock` and is left in place.

4. **Why is `release` idempotent?** A context-manager `__exit__` always fires, even when callers explicitly called `release` first in their own `finally`. The `_released` flag absorbs the second call so we don't double-release the `FileLock` (which raises on some versions).

5. **Why does the test in Task 4 mock `FileLock` rather than spinning two processes?** REQ-14 forbids subprocesses. The real-contention test (`test_acquire_zero_timeout_does_not_block`) holds the lock via one `RunLockHandle` and attempts a second `acquire_run_lock` in the same process — `filelock`'s default (non-singleton) behavior means distinct instances contend, which is exactly the cross-process semantics we care about. The mocked Timeout test isolates the translation logic.

6. **Why `from story_automator.core.common import compact_json, iso_now` (an absolute path)?** All existing `core/` modules use absolute imports (see `telemetry_emitter.py`); a relative `from .common import ...` would diverge from the established convention. Both work — match existing style.
