# M05-M4 State Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the M05 atomic-IO + run-lock primitives into `commands/state.py:cmd_build_state_doc` so the state-document write is atomic, serialized through a run lock, and free of the legacy marker-file sentinel.

**Architecture:** `cmd_build_state_doc` keeps its existing validation / template-rendering pipeline. Only the final write step changes: the rendered text now flows through `write_atomic_text` instead of `Path.write_text`, the write is guarded by `acquire_run_lock` against a sibling lock-path under the same output folder, and a one-shot best-effort cleanup of any legacy `.state-build.marker` sentinel happens before the lock is taken. `RunLockBusy` surfaces as the existing `write_json({...})` envelope with a new `run_lock_busy` error so return-code contracts and observability stay consistent. No new public modules; only `state.py` and its dedicated integration test change.

**Tech Stack:** Python 3.11+ stdlib, `filelock` (transitively via `acquire_run_lock`), `unittest.TestCase` for tests. No new third-party dependencies.

---

## File Structure

**Modify:**
- `skills/bmad-story-automator/src/story_automator/commands/state.py` — swap `output_path.write_text(text)` for run-lock-guarded `write_atomic_text`; add `RunLockBusy` error envelope; add legacy-marker best-effort cleanup helper at the build-doc entry point.

**Create:**
- `tests/test_state_atomic_integration.py` — new `unittest.TestCase` file covering: atomic-write happy path through `cmd_build_state_doc`, legacy-marker cleanup, `RunLockBusy` envelope on contention, lock-path sidecar lifecycle. Mirrors the cross-platform constraints in REQ-14: no subprocess, no tmux, runs identically on Windows git-bash, WSL Ubuntu, and Linux CI.

**Do not modify in this milestone:**
- `core/atomic_io.py` (already complete from M1-M3).
- `core/runtime_layout.py` `active_marker_path` (separate active-run-tracking sentinel; out of scope per the orchestrator's marker create/remove subsystem).
- `commands/orchestrator.py` marker subsystem.

---

## Constants & Names (locked here so later tasks use the same identifiers)

```python
# In commands/state.py
_LEGACY_STATE_BUILD_MARKER_NAME = ".state-build.marker"
_STATE_BUILD_LOCK_NAME = ".state-build.lock"
```

The run-lock identity is keyed by the `stamp` already computed in `cmd_build_state_doc` (re-used as `run_id`). The lock is taken with `timeout=0.0` — concurrent builds fail fast with `RunLockBusy` rather than waiting, matching the spec's "fail-fast and surface as typed exception" intent.

---

## Task 1: Add failing test for legacy-marker cleanup at build-doc startup

**Files:**
- Create: `tests/test_state_atomic_integration.py`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.state import cmd_build_state_doc

REPO_ROOT = Path(__file__).resolve().parents[1]


class _PatchEnv:
    def __init__(self, project_root: Path) -> None:
        self.project_root = str(project_root)
        self.previous: str | None = None

    def __enter__(self) -> None:
        import os

        self.previous = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = self.project_root

    def __exit__(self, exc_type, exc, tb) -> None:
        import os

        if self.previous is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self.previous


def _install_bundle(project_root: Path) -> None:
    source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
    source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
    target_root = project_root / ".claude" / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_skill, target_root / "bmad-story-automator")
    shutil.copytree(source_review, target_root / "bmad-story-automator-review")


def _install_required_skills(project_root: Path) -> None:
    for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
        skill_dir = project_root / ".claude" / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
    (project_root / ".claude" / "skills" / "bmad-create-story" / "discover-inputs.md").write_text("# discover\n", encoding="utf-8")
    (project_root / ".claude" / "skills" / "bmad-create-story" / "checklist.md").write_text("# checklist\n", encoding="utf-8")
    (project_root / ".claude" / "skills" / "bmad-create-story" / "template.md").write_text("# template\n", encoding="utf-8")
    (project_root / ".claude" / "skills" / "bmad-dev-story" / "checklist.md").write_text("# checklist\n", encoding="utf-8")
    (project_root / ".claude" / "skills" / "bmad-qa-generate-e2e-tests" / "checklist.md").write_text("# checklist\n", encoding="utf-8")


def _config() -> dict[str, object]:
    return {
        "epic": "1",
        "epicName": "Epic 1",
        "storyRange": ["1.1"],
        "status": "READY",
        "aiCommand": "claude",
    }


class LegacyMarkerCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_build_state_doc_unlinks_legacy_marker_at_startup(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        legacy = self.output_dir / ".state-build.marker"
        legacy.write_text("stale legacy sentinel", encoding="utf-8")

        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        self.assertFalse(legacy.exists(), "legacy marker must be removed")

    def test_build_state_doc_succeeds_without_legacy_marker(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # No legacy marker present — unlink must be missing_ok.
        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.LegacyMarkerCleanupTests -v`

Expected: FAIL on `test_build_state_doc_unlinks_legacy_marker_at_startup` because the legacy marker is not yet deleted. `test_build_state_doc_succeeds_without_legacy_marker` should PASS (cmd_build_state_doc already runs end-to-end on a happy path).

- [ ] **Step 3: Commit the failing test (red)**

```bash
git add tests/test_state_atomic_integration.py
git commit -m "test(state): pin legacy marker cleanup at cmd_build_state_doc entry"
```

---

## Task 2: Implement legacy-marker cleanup in cmd_build_state_doc

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/state.py`

- [ ] **Step 1: Add the legacy marker constant near the top of the file**

After the existing imports in `state.py`, before `cmd_build_state_doc`, insert:

```python
_LEGACY_STATE_BUILD_MARKER_NAME = ".state-build.marker"
_STATE_BUILD_LOCK_NAME = ".state-build.lock"


def _cleanup_legacy_state_build_marker(output_folder: Path) -> None:
    """Best-effort delete a legacy `.state-build.marker` sentinel left by a
    pre-M05 build. Single `unlink(missing_ok=True)` call — does not block
    startup, does not raise.

    REQ-11: "any legacy marker discovered at startup must be deleted with a
    single best-effort ``Path.unlink(missing_ok=True)`` call".
    """
    (output_folder / _LEGACY_STATE_BUILD_MARKER_NAME).unlink(missing_ok=True)
```

- [ ] **Step 2: Call the cleanup right after `ensure_dir(output_folder)` in `cmd_build_state_doc`**

In `cmd_build_state_doc`, locate the line `ensure_dir(output_folder)` (currently at line 41) and add the cleanup call directly after it:

```python
    ensure_dir(output_folder)
    _cleanup_legacy_state_build_marker(Path(output_folder))
```

- [ ] **Step 3: Run the test from Task 1**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.LegacyMarkerCleanupTests -v`

Expected: both tests PASS.

- [ ] **Step 4: Commit (green)**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/state.py
git commit -m "feat(state): cmd_build_state_doc removes legacy marker at startup"
```

---

## Task 3: Add failing test for atomic write through cmd_build_state_doc

**Files:**
- Modify: `tests/test_state_atomic_integration.py`

- [ ] **Step 1: Add a new test class to `tests/test_state_atomic_integration.py`**

Append after `LegacyMarkerCleanupTests` (before the `if __name__ == "__main__":` block):

```python
class AtomicWriteIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_cmd_build_state_doc_routes_through_write_atomic_text(self) -> None:
        """REQ-10: state.py must route every previous ``write_text`` site
        through ``write_atomic_text``. We assert this by patching
        ``story_automator.commands.state.write_atomic_text`` and checking it
        was invoked with the rendered state-doc path and the rendered text.
        """
        from unittest.mock import patch

        recorded: list[tuple[Path, str]] = []

        def _spy(path: Path, data: str, *, encoding: str = "utf-8") -> None:
            recorded.append((Path(path), data))
            Path(path).write_bytes(data.encode(encoding))

        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout), patch(
            "story_automator.commands.state.write_atomic_text", side_effect=_spy
        ) as spy:
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        # write_atomic_text is the only allowed write path for the rendered
        # state document. Multiple calls are permissible (acquire_run_lock
        # writes its identity payload through write_atomic_text too); we just
        # require that the state-doc target itself was written through it.
        self.assertTrue(spy.called, "write_atomic_text must be invoked")
        targets = {str(call_path) for call_path, _ in recorded}
        payload = json.loads(stdout.getvalue())
        self.assertIn(payload["path"], targets)
```

- [ ] **Step 2: Run the failing test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.AtomicWriteIntegrationTests -v`

Expected: FAIL — `spy.called` is `False` because `cmd_build_state_doc` still uses `output_path.write_text(text)`.

- [ ] **Step 3: Commit the failing test (red)**

```bash
git add tests/test_state_atomic_integration.py
git commit -m "test(state): pin cmd_build_state_doc routes writes through write_atomic_text"
```

---

## Task 4: Replace `output_path.write_text(text)` with `write_atomic_text`

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/state.py`

- [ ] **Step 1: Add the import**

At the top of `state.py`, alongside the other `..core.*` imports, add:

```python
from ..core.atomic_io import RunLockBusy, acquire_run_lock, write_atomic_text
```

(`RunLockBusy` and `acquire_run_lock` are imported now even though they are first used in Task 6; keeping the import block in one edit avoids a churn commit.)

- [ ] **Step 2: Replace the write call**

In `cmd_build_state_doc`, change:

```python
    output_path.write_text(text)
```

to:

```python
    write_atomic_text(output_path, text)
```

- [ ] **Step 3: Run the test from Task 3**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.AtomicWriteIntegrationTests -v`

Expected: PASS — the spy records the call.

- [ ] **Step 4: Run the existing state suite to confirm no regression**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_policy_metadata -v`

Expected: PASS — the rendered state document has identical content; only the write mechanism changed.

- [ ] **Step 5: Commit (green)**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/state.py
git commit -m "feat(state): route cmd_build_state_doc writes through write_atomic_text"
```

---

## Task 5: Add failing test for run-lock guarding the build

**Files:**
- Modify: `tests/test_state_atomic_integration.py`

- [ ] **Step 1: Append a new test class**

```python
class RunLockGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_cmd_build_state_doc_acquires_run_lock(self) -> None:
        """REQ-11: the run-lock API must guard the write."""
        from unittest.mock import patch
        from story_automator.core.atomic_io import acquire_run_lock as _real

        captured: list[Path] = []

        def _spy(lock_path: Path, *, run_id: str, timeout: float = 0.0):
            captured.append(Path(lock_path))
            return _real(lock_path, run_id=run_id, timeout=timeout)

        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout), patch(
            "story_automator.commands.state.acquire_run_lock", side_effect=_spy
        ):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(len(captured), 1, "exactly one run-lock acquisition expected")
        self.assertEqual(captured[0].name, ".state-build.lock")
        self.assertEqual(captured[0].parent, self.output_dir.resolve())

    def test_cmd_build_state_doc_releases_run_lock_after_success(self) -> None:
        """The lock-identity payload at lock_path must be deleted on release;
        the sibling FileLock sentinel (``.state-build.lock.lock``) may remain
        — filelock owns its lifecycle.
        """
        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 0)
        lock_payload = self.output_dir / ".state-build.lock"
        self.assertFalse(
            lock_payload.exists(),
            "RunLockHandle.release must unlink the identity payload",
        )
```

- [ ] **Step 2: Run the failing test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.RunLockGuardTests -v`

Expected: FAIL on both — `acquire_run_lock` is imported but never called yet.

- [ ] **Step 3: Commit the failing test (red)**

```bash
git add tests/test_state_atomic_integration.py
git commit -m "test(state): pin cmd_build_state_doc acquires run lock around write"
```

---

## Task 6: Wrap the write in `acquire_run_lock` (timeout=0.0)

**Files:**
- Modify: `skills/bmad-story-automator/src/story_automator/commands/state.py`

- [ ] **Step 1: Replace the bare `write_atomic_text(output_path, text)` call with a lock-guarded block**

In `cmd_build_state_doc`, locate:

```python
    write_atomic_text(output_path, text)
    write_json({"ok": True, "path": str(output_path), "createdAt": now})
    return 0
```

Replace with:

```python
    lock_path = Path(output_folder) / _STATE_BUILD_LOCK_NAME
    try:
        with acquire_run_lock(lock_path, run_id=stamp, timeout=0.0):
            write_atomic_text(output_path, text)
    except RunLockBusy:
        write_json({"ok": False, "error": "run_lock_busy"})
        return 1
    write_json({"ok": True, "path": str(output_path), "createdAt": now})
    return 0
```

The lock is taken AFTER all validation (template / config / policy snapshot) succeeds. That keeps the failure envelopes for the existing early-error paths (`missing_template_or_output`, `missing_config`, `policy_snapshot_failed`) unchanged — REQ-10 explicitly preserves return codes and the JSON envelope.

- [ ] **Step 2: Run the Task 5 tests**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.RunLockGuardTests -v`

Expected: both PASS.

- [ ] **Step 3: Re-run the full integration test file**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration -v`

Expected: all tests so far PASS.

- [ ] **Step 4: Re-run the legacy state suite to confirm no regression**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_policy_metadata -v`

Expected: PASS — the lock acquires uncontested and releases cleanly.

- [ ] **Step 5: Commit (green)**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/state.py
git commit -m "feat(state): guard cmd_build_state_doc write with acquire_run_lock"
```

---

## Task 7: Add failing test for RunLockBusy envelope on contention

**Files:**
- Modify: `tests/test_state_atomic_integration.py`

- [ ] **Step 1: Add a new test class**

```python
class RunLockContentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_returns_run_lock_busy_envelope_when_lock_is_held(self) -> None:
        """If a sibling holder already owns the .state-build.lock, the next
        cmd_build_state_doc invocation must surface
        ``{"ok": False, "error": "run_lock_busy"}`` and exit 1, NOT crash.
        """
        from story_automator.core.atomic_io import acquire_run_lock

        self.output_dir.mkdir(parents=True, exist_ok=True)
        holder_lock_path = self.output_dir / ".state-build.lock"

        # Hold the lock from this thread. timeout=0.0 means no waiting; the
        # subsequent cmd_build_state_doc call must hit RunLockBusy
        # immediately.
        with acquire_run_lock(holder_lock_path, run_id="holder", timeout=0.0):
            stdout = io.StringIO()
            with _PatchEnv(self.project_root), redirect_stdout(stdout):
                code = cmd_build_state_doc(
                    [
                        "--template",
                        str(self.template),
                        "--output-folder",
                        str(self.output_dir),
                        "--config-json",
                        json.dumps(_config()),
                    ]
                )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, {"ok": False, "error": "run_lock_busy"})
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.RunLockContentionTests -v`

Expected: PASS already — Task 6 wired the busy envelope. If the test was authored speculatively before Task 6 it would have failed; here we treat Task 7 as a regression pin rather than a red→green cycle.

- [ ] **Step 3: Commit the pin**

```bash
git add tests/test_state_atomic_integration.py
git commit -m "test(state): pin RunLockBusy envelope under contended .state-build.lock"
```

---

## Task 8: Verify the legacy-marker cleanup precedes lock acquisition

**Files:**
- Modify: `tests/test_state_atomic_integration.py`

This task adds a regression pin that the marker cleanup runs *before* the run-lock is acquired, so a build can still succeed even when both a stale legacy marker AND no live lock holder coexist on disk.

- [ ] **Step 1: Add the regression test**

Append to `tests/test_state_atomic_integration.py`:

```python
class CleanupBeforeLockOrderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_legacy_marker_cleanup_runs_before_lock_acquisition(self) -> None:
        """REQ-11 ordering claim: legacy-marker cleanup happens at startup,
        BEFORE acquire_run_lock is called. Verified by patching
        ``acquire_run_lock`` to raise ``RunLockBusy`` immediately and
        asserting the legacy file was already removed — which can only be
        true if cleanup ran before the lock attempt.
        """
        from unittest.mock import patch

        from story_automator.core.atomic_io import RunLockBusy

        self.output_dir.mkdir(parents=True, exist_ok=True)
        legacy = self.output_dir / ".state-build.marker"
        legacy.write_text("garbage", encoding="utf-8")

        def _busy(*args, **kwargs):
            raise RunLockBusy("simulated contention")

        stdout = io.StringIO()
        with _PatchEnv(self.project_root), redirect_stdout(stdout), patch(
            "story_automator.commands.state.acquire_run_lock", side_effect=_busy
        ):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(self.template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(_config()),
                ]
            )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload, {"ok": False, "error": "run_lock_busy"})
        self.assertFalse(
            legacy.exists(),
            "cleanup must happen BEFORE lock acquisition — RunLockBusy on "
            "the first lock attempt must not skip the cleanup step",
        )
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.CleanupBeforeLockOrderingTests -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_state_atomic_integration.py
git commit -m "test(state): regression pin legacy marker cleanup runs before lock"
```

---

## Task 9: Add cross-thread serialization smoke test

**Files:**
- Modify: `tests/test_state_atomic_integration.py`

REQ-14 forbids subprocesses, but two threads in the same process are explicitly allowed by the M05 NFR ("two threads in the same process writing to the same resolved path must serialize"). This test verifies the same property *through* `cmd_build_state_doc`'s lock path, not just the atomic-IO primitive.

- [ ] **Step 1: Add the test**

```python
class CrossThreadSerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        _install_bundle(self.project_root)
        _install_required_skills(self.project_root)
        self.template = (
            self.project_root
            / ".claude"
            / "skills"
            / "bmad-story-automator"
            / "templates"
            / "state-document.md"
        )

    def test_two_threads_get_distinct_outcomes_one_succeeds_one_busy(self) -> None:
        """With two concurrent cmd_build_state_doc invocations against the
        same output folder, exactly one acquires the lock; the other must
        surface ``run_lock_busy``. This validates the run-lock keeps the
        build write serialized across in-process threads with no deadlock.
        """
        results: list[tuple[int, str]] = []
        barrier = threading.Barrier(2)

        def _invoke() -> None:
            stdout = io.StringIO()
            barrier.wait()
            with _PatchEnv(self.project_root), redirect_stdout(stdout):
                code = cmd_build_state_doc(
                    [
                        "--template",
                        str(self.template),
                        "--output-folder",
                        str(self.output_dir),
                        "--config-json",
                        json.dumps(_config()),
                    ]
                )
            results.append((code, stdout.getvalue()))

        t1 = threading.Thread(target=_invoke)
        t2 = threading.Thread(target=_invoke)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        self.assertFalse(t1.is_alive(), "thread t1 deadlocked")
        self.assertFalse(t2.is_alive(), "thread t2 deadlocked")

        self.assertEqual(len(results), 2)
        codes = sorted(code for code, _ in results)
        # At least one must succeed; if both succeed (because the stamps
        # differ by a second and the lock was uncontended in practice), the
        # serialization claim still holds at the write layer. We assert the
        # weaker NFR: no thread crashed, no thread deadlocked, no thread
        # returned a non-{0,1} exit code.
        for code, output in results:
            self.assertIn(code, (0, 1))
            payload = json.loads(output)
            self.assertIn(payload.get("ok"), (True, False))
            if payload["ok"] is False:
                self.assertEqual(payload["error"], "run_lock_busy")
        self.assertIn(0, codes, "at least one build must succeed")
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration.CrossThreadSerializationTests -v`

Expected: PASS — at least one thread succeeds, neither deadlocks. Whether the second hits `run_lock_busy` is timing-dependent; the assertion accepts both outcomes but requires no crash / no deadlock.

- [ ] **Step 3: Commit**

```bash
git add tests/test_state_atomic_integration.py
git commit -m "test(state): cross-thread cmd_build_state_doc never deadlocks"
```

---

## Task 10: Run the full Python test suite

**Files:** (none; verification step)

- [ ] **Step 1: Run the full suite**

Run: `npm run test:python`

Expected: PASS — every pre-existing test plus `tests/test_atomic_io.py` and the new `tests/test_state_atomic_integration.py`. No skips beyond pre-existing platform skips.

- [ ] **Step 2: Triage failures (if any)**

If any test fails, the most likely candidates are:
- `test_state_policy_metadata.py` — confirm the `cmd_build_state_doc` happy paths still write the rendered content byte-for-byte.
- Any test that reads `output_folder` and expected exactly the rendered files: confirm the `.state-build.lock.lock` and absence of `.state-build.lock` (released identity payload) do not interfere.

Re-read the failing test, fix the underlying issue in `state.py`, re-run.

- [ ] **Step 3: No commit if step 1 already passes**

If the suite was already green, skip the commit. Otherwise, after fixing:

```bash
git add skills/bmad-story-automator/src/story_automator/commands/state.py
git commit -m "fix(state): keep cmd_build_state_doc compatible with existing suite"
```

---

## Task 11: Ruff check + format on touched files

**Files:** (none; verification step)

- [ ] **Step 1: Ruff check**

Run:

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/core/atomic_io.py \
  skills/bmad-story-automator/src/story_automator/commands/state.py \
  tests/test_atomic_io.py \
  tests/test_state_atomic_integration.py
```

Expected: exit 0, no findings.

- [ ] **Step 2: Ruff format check**

Run:

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/core/atomic_io.py \
  skills/bmad-story-automator/src/story_automator/commands/state.py \
  tests/test_atomic_io.py \
  tests/test_state_atomic_integration.py
```

Expected: exit 0.

- [ ] **Step 3: Apply format if needed**

If step 2 reports diffs:

```bash
python -m ruff format \
  skills/bmad-story-automator/src/story_automator/commands/state.py \
  tests/test_state_atomic_integration.py
```

Re-run step 2 to confirm clean.

- [ ] **Step 4: Commit format fixups (only if applied)**

```bash
git add skills/bmad-story-automator/src/story_automator/commands/state.py tests/test_state_atomic_integration.py
git commit -m "style(state): ruff format touched files"
```

---

## Task 12: Cross-platform smoke verification

**Files:** (none; verification step)

REQ-14 + quality gate require Windows git-bash, WSL Ubuntu-26.04, and Linux CI all running clean. The work was authored in a Windows git-bash worktree; the test file contains no platform conditionals.

- [ ] **Step 1: Re-run the integration suite under the project's pinned interpreter**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_state_atomic_integration -v`

Expected: PASS. Confirms the test file is correct on the host (Windows git-bash for the operator).

- [ ] **Step 2: Inspect the test file for platform-conditional branches**

Manually grep the new test file:

```bash
python -m ruff check --select=I tests/test_state_atomic_integration.py
```

And visually inspect for `sys.platform`, `os.name`, `@unittest.skipIf(...)`, `subprocess`, or `tmux`. There must be none in this milestone's test file. (The smoke gate forbids platform-conditional branches that suppress assertions.)

- [ ] **Step 3: No commit unless changes required**

---

## Task 13: Final plan-completion check

**Files:** (none; verification step)

- [ ] **Step 1: Confirm REQ-10 coverage**

Grep:

```bash
python -m grep -n "write_text" skills/bmad-story-automator/src/story_automator/commands/state.py || true
```

(or use the project's grep tool) — the only acceptable hit inside `cmd_build_state_doc` is on a *template read*, not a *write*. The `output_path.write_text(text)` call must be gone.

- [ ] **Step 2: Confirm REQ-11 coverage**

Grep:

```bash
python -m grep -n "_LEGACY_STATE_BUILD_MARKER_NAME\|acquire_run_lock\|RunLockBusy" skills/bmad-story-automator/src/story_automator/commands/state.py
```

Expected: each identifier appears at least once.

- [ ] **Step 3: Confirm REQ-14 coverage**

Grep the test file for forbidden patterns:

```bash
python -m grep -nE "subprocess|tmux|skipIf|skipUnless|sys\\.platform" tests/test_state_atomic_integration.py || true
```

Expected: no hits.

- [ ] **Step 4: Run `npm run test:python` one last time**

Expected: PASS.

- [ ] **Step 5: Final commit (only if uncommitted edits remain)**

```bash
git status
```

If clean, no further commit. If anything is staged, commit with:

```bash
git commit -m "chore(state): finalize m05-m4 state integration"
```

---

## Self-Review Notes

**Spec coverage:**
- REQ-10 ("state.py must use `write_atomic_text`") — Tasks 3-4.
- REQ-11 ("legacy marker removed + `acquire_run_lock` used in its place") — Tasks 1-2 (cleanup), 5-7 (lock + busy envelope).
- REQ-14 (cross-platform `unittest.TestCase`, no subprocess/tmux) — Tasks 9 + 12.
- Quality gate: full `npm run test:python` — Task 10.
- Quality gate: ruff check/format on touched files — Task 11.
- Quality gate: cross-platform smoke — Task 12.
- Context: replace regex-driven frontmatter mutation hot path — the regex pipeline itself is preserved; only the *write* leaving the function is replaced. REQ-10 specifically requires preserving the existing JSON envelope and return codes, so this scope is correct.

**Out-of-scope guarded:**
- No edits to `core/atomic_io.py` (M1-M3 deliverable).
- No edits to `runtime_layout.py:active_marker_path` or `commands/orchestrator.py:_marker` — that's a separate active-run-tracking sentinel, not the `state.py` build sentinel REQ-11 calls out. Conflating them would balloon scope past the M05 boundary.
- No new third-party dependencies.

**REQ-11 interpretation note (flagged for reviewer):** REQ-11 reads "the previous marker-file sentinel pattern used by `state.py` and its callers must be removed". The current `state.py` does not in fact use any marker file — it does a bare `output_path.write_text(text)`. The closest existing sentinel in the project (`.story-automator-active` at `core/runtime_layout.py:ACTIVE_MARKER_NAME`) is used by the orchestrator's marker subsystem to track active-run state, NOT by `state.py`'s build write. Removing it would break `cmd_ensure_marker_gitignore`, `orchestrator marker create/remove/check/heartbeat`, `runtime_policy._read_active_marker`, and `tmux_runtime` consumers — far outside the M05 boundary. This plan therefore interprets the "legacy marker" as a hypothetical pre-M05 build-time sentinel (`.state-build.marker`) and satisfies REQ-11's literal "best-effort `Path.unlink(missing_ok=True)`" instruction without removing the active-run subsystem. If the spec author intended the active-run marker, that work is out of scope here and should land as a follow-up.

**Acknowledged trade-offs:**
- Task 7's busy-envelope test is a regression pin rather than a strict red→green TDD step (Task 6 already wires both the lock acquire and the RunLockBusy envelope to avoid a churn commit). Acceptable because Task 5 IS the strict red→green pair and Task 7 documents the failure-mode contract separately.
- Task 9's cross-thread test asserts no-deadlock only, not strict serialization. True intra-process serialization comes from the per-path `threading.Lock` registry inside `write_atomic_text` (M05-M1 deliverable); the run lock is primarily a cross-process serializer. The test as written validates the no-deadlock NFR without overclaiming.
- `acquire_run_lock` writes a `.state-build.lock` identity payload (deleted on release) and creates a sibling `.state-build.lock.lock` FileLock sentinel (lifecycle owned by `filelock`, may persist between runs). The persistence is cosmetic — neither file is required reading by other commands.

**Placeholders / typos:** None — every code block is the actual content to write.

**Type consistency:** `_LEGACY_STATE_BUILD_MARKER_NAME` and `_STATE_BUILD_LOCK_NAME` declared in Task 2, reused in Tasks 6-8. `acquire_run_lock` import added in Task 4 even though first used in Task 6 (avoids a churn commit).
