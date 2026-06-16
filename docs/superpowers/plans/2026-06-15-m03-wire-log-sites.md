# M03 — Wire log sites (REQ-09 / REQ-10 / REQ-11) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete REQ-09 / REQ-10 / REQ-11 of the M02 spec by populating the currently-placeholder `epic` and `story_key` fields at every wired emit site, adding dedicated wiring-level tests that exercise the orchestrator / epic-agents / tmux-runtime call paths end-to-end (not synthetic `Event(...)` constructions), and validating the import-allowlist + full quality-gate suite stays green.

**Architecture:** The three target modules already import `TelemetryEmitter` and call `emit()` at each log site, but most field values are empty placeholders (`epic=""`, `story_key=""`). M03 derives those fields from already-available local context — `normalize_story_key` for `epic` in orchestrator, regex parsing of the `sa-{slug}-{stamp}-e{epic}-s{suffix}-{step}` session-name shape for `story_key` in tmux_runtime, and context parsing for `_escalate`. Tests use `tempfile.TemporaryDirectory` plus a fresh `TelemetryEmitter` injected by patching `emitter_for_project_root` and `get_project_root`, then read the resulting JSONL through `TelemetryReader` to assert wire-level field values.

**Tech Stack:** Python 3.11+, stdlib + `filelock`, `unittest.TestCase`, `tempfile.TemporaryDirectory`, `unittest.mock.patch`.

---

## File Structure

**Modify (source — minimal field-population edits only):**
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py` — populate `epic` in `_commit_ready` and `_verify_code_review` via `normalize_story_key`; accept story-key in `_escalate session-crash` context and populate `story_key`/`epic`.
- `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py` — add `_story_key_from_session_name()` helper and populate `story_key` on the three tmux emit sites.

**Create (tests):**
- `tests/test_wire_orchestrator.py` — wiring tests for `_commit_ready`, `_verify_code_review`, `_escalate session-crash`.
- `tests/test_wire_tmux_runtime.py` — wiring tests for `_emit_tmux_spawned`, `_emit_tmux_completed`, `_emit_tmux_crashed`, and the `_story_key_from_session_name` helper.
- `tests/test_wire_epic_agents.py` — wiring tests for `agents_resolve_action` (RetryAttempt path), `check_blocking_action` (EscalationTriggered path), `retro_agent_action` (RetroFired path).
- `tests/test_wire_integration.py` — end-to-end: invoke wired functions, then read back through `TelemetryReader` and assert `cost_by_epic` / `attempts_by_story` / `retro_inputs` see the wired events.

**Do not touch:** `telemetry_emitter.py`, `telemetry_reader.py`, `telemetry_events.py` (M01/M02 surfaces are locked); `bin/`, `install.sh`, `pyproject.toml` allowlist.

---

## Task 1: Wiring test scaffold + helper for orchestrator tests

**Files:**
- Create: `tests/test_wire_orchestrator.py`

- [ ] **Step 1: Write the failing test (scaffold + first wiring test for `_verify_code_review` epic-derivation)**

```python
# tests/test_wire_orchestrator.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator
from story_automator.core.telemetry_emitter import TelemetryEmitter


def _patched_emitter_factory(tmp: Path):
    emitter = TelemetryEmitter(tmp / "events.jsonl")

    def factory(_project_root):
        return emitter

    return emitter, factory


def _read_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class VerifyCodeReviewWiringTests(unittest.TestCase):
    def test_review_cycle_emit_derives_epic_from_story_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            with mock.patch.object(
                orchestrator, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                orchestrator, "get_project_root", return_value=str(tmp)
            ), mock.patch.object(
                orchestrator,
                "verify_code_review_completion",
                return_value={"verified": True, "cycle": 2, "issuesFound": 0},
            ):
                rc = orchestrator._verify_code_review(["1.3"])
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "review_cycle")
            self.assertEqual(ev["story_key"], "1.3")
            self.assertEqual(ev["epic"], "1")
            self.assertEqual(ev["cycle_num"], 2)
            self.assertFalse(ev["blocking"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_orchestrator -v`
Expected: FAIL — `AssertionError: '' != '1'` because `_verify_code_review` currently emits `epic=""`.

- [ ] **Step 3: Populate `epic` in `_verify_code_review` from `story_key`**

Edit `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py` inside `_verify_code_review` — just before the existing `_telemetry_emitter().emit(ReviewCycle(...))` call, derive epic via `normalize_story_key`:

```python
    norm = normalize_story_key(get_project_root(), args[0])
    epic = norm.id.rsplit(".", 1)[0] if norm is not None else ""
    _telemetry_emitter().emit(
        ReviewCycle(
            timestamp=iso_now(),
            run_id="",
            epic=epic,
            story_key=args[0],
            cycle_num=int(payload.get("cycle") or 0),
            issues_found=int(payload.get("issuesFound") or 0),
            blocking=not bool(payload.get("verified")),
        )
    )
```

Add the import at the top of `orchestrator.py` (alongside the existing `story_keys` re-exports — `normalize_story_key` is already imported from `story_keys` indirectly; if not, add):

```python
from story_automator.core.story_keys import normalize_story_key
```

(Note: re-check imports — `normalize_story_key` is already imported on line 31 via `from story_automator.core.story_keys import normalize_story_key, sprint_status_file`. No new import needed.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_orchestrator -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_wire_orchestrator.py skills/bmad-story-automator/src/story_automator/commands/orchestrator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): derive epic from story_key in _verify_code_review wiring (REQ-09)"
```

---

## Task 2: Populate `epic` in `_commit_ready` StoryCompleted emit

**Files:**
- Modify: `tests/test_wire_orchestrator.py` (append test class)
- Modify: `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py:521-568` (`_commit_ready` body)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wire_orchestrator.py`:

```python
class CommitReadyWiringTests(unittest.TestCase):
    def test_story_completed_emit_derives_epic_from_story_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            fake_status = mock.MagicMock(done=True, status="done", story="2.4")
            with mock.patch.object(
                orchestrator, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                orchestrator, "get_project_root", return_value=str(tmp)
            ), mock.patch.object(
                orchestrator, "sprint_status_get", return_value=fake_status
            ), mock.patch.object(
                orchestrator, "run_cmd", return_value=("M file.py\n", 0)
            ):
                rc = orchestrator._commit_ready(["2.4"])
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "story_completed")
            self.assertEqual(ev["story_key"], "2.4")
            self.assertEqual(ev["epic"], "2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_orchestrator.CommitReadyWiringTests -v`
Expected: FAIL — `epic` is `""`.

- [ ] **Step 3: Populate `epic` in `_commit_ready` StoryCompleted**

Replace the `StoryCompleted(...)` block inside `_commit_ready`:

```python
            norm = normalize_story_key(project_root, args[0])
            epic = norm.id.rsplit(".", 1)[0] if norm is not None else ""
            _telemetry_emitter().emit(
                StoryCompleted(
                    timestamp=iso_now(),
                    run_id="",
                    epic=epic,
                    story_key=args[0],
                    duration_s=0.0,
                    cost_usd=0.0,
                    tokens_in=0,
                    tokens_out=0,
                    attempts=1,
                )
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_orchestrator.CommitReadyWiringTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_wire_orchestrator.py skills/bmad-story-automator/src/story_automator/commands/orchestrator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): derive epic from story_key in _commit_ready wiring (REQ-09)"
```

---

## Task 3: Populate `story_key` and `epic` in `_escalate session-crash`

**Files:**
- Modify: `tests/test_wire_orchestrator.py` (append test class)
- Modify: `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py:481-502` (`_escalate` session-crash branch)

- [ ] **Step 1: Write the failing test**

Append:

```python
class EscalateSessionCrashWiringTests(unittest.TestCase):
    def test_session_crash_emit_extracts_story_and_epic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            fake_policy = {"max_retries": 2}
            with mock.patch.object(
                orchestrator, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                orchestrator, "get_project_root", return_value=str(tmp)
            ), mock.patch.object(
                orchestrator, "load_runtime_policy", return_value=fake_policy
            ), mock.patch.object(
                orchestrator, "crash_max_retries", return_value=2
            ):
                rc = orchestrator._escalate(
                    ["session-crash", "retries=3 story=3.7 session=sess-abc"]
                )
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "story_failed")
            self.assertEqual(ev["story_key"], "3.7")
            self.assertEqual(ev["epic"], "3")
            self.assertEqual(ev["attempts"], 3)
            self.assertEqual(ev["final_session"], "sess-abc")
            self.assertEqual(ev["error_class"], "session_crash")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_orchestrator.EscalateSessionCrashWiringTests -v`
Expected: FAIL — `story_key`/`epic`/`final_session` are empty.

- [ ] **Step 3: Add a tiny `_parse_context_str` helper and populate the StoryFailed emit**

Add this helper near the existing `_parse_context_int` in `orchestrator.py:732`:

```python
def _parse_context_str(context: str, key: str) -> str:
    match = re.search(rf"{re.escape(key)}=(\S+)", context)
    return match.group(1) if match else ""
```

Replace the StoryFailed emit body inside `_escalate` `session-crash` branch:

```python
        if retries >= limit:
            story = _parse_context_str(context, "story")
            session = _parse_context_str(context, "session")
            norm = normalize_story_key(get_project_root(), story) if story else None
            epic = norm.id.rsplit(".", 1)[0] if norm is not None else ""
            _telemetry_emitter().emit(
                StoryFailed(
                    timestamp=iso_now(),
                    run_id="",
                    epic=epic,
                    story_key=story,
                    error_class="session_crash",
                    reason=f"Session crashed after {retries} retries",
                    attempts=retries,
                    final_session=session,
                )
            )
            print_json(...)  # existing print unchanged
```

(Preserve the existing `print_json` call exactly; do not change its keys.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_orchestrator.EscalateSessionCrashWiringTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_wire_orchestrator.py skills/bmad-story-automator/src/story_automator/commands/orchestrator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): populate story_key/epic/final_session on session_crash StoryFailed (REQ-09)"
```

---

## Task 3b: Regression-pin test for `_marker create` StoryStarted emit

The emit at `_marker create` legitimately leaves `agent`/`model`/`complexity` empty (the marker site doesn't know these — they're populated at spawn time via M03+ work). This task adds a regression pin so a future refactor cannot silently drop the StoryStarted emit at marker creation. No source changes.

**Files:**
- Modify: `tests/test_wire_orchestrator.py` (append test class)

- [ ] **Step 1: Write the test**

Append:

```python
class MarkerCreateWiringTests(unittest.TestCase):
    def test_marker_create_emits_story_started_with_epic_and_story(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            with mock.patch.object(
                orchestrator, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                orchestrator, "get_project_root", return_value=str(tmp)
            ):
                rc = orchestrator._marker(
                    [
                        "create",
                        "--epic",
                        "8",
                        "--story",
                        "8.4",
                        "--remaining",
                        "3",
                        "--state-file",
                        str(tmp / "state.md"),
                    ]
                )
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            started = [e for e in events if e["event_type"] == "story_started"]
            self.assertEqual(len(started), 1)
            ev = started[0]
            self.assertEqual(ev["epic"], "8")
            self.assertEqual(ev["story_key"], "8.4")
            # agent/model/complexity intentionally empty at marker site
            # (spawn-time population is M03+ scope per spec lines 8-9)
            self.assertEqual(ev["agent"], "")
            self.assertEqual(ev["model"], "")
            self.assertEqual(ev["complexity"], "")
```

- [ ] **Step 2: Run test to verify it passes (regression-pin)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_orchestrator.MarkerCreateWiringTests -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_wire_orchestrator.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): pin _marker create StoryStarted wiring (REQ-09)"
```

---

## Task 4: Add `_story_key_from_session_name` helper in tmux_runtime

**Files:**
- Create: `tests/test_wire_tmux_runtime.py`
- Modify: `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wire_tmux_runtime.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.core import tmux_runtime
from story_automator.core.telemetry_emitter import TelemetryEmitter


def _patched_emitter_factory(tmp: Path):
    emitter = TelemetryEmitter(tmp / "events.jsonl")

    def factory(_project_root):
        return emitter

    return emitter, factory


def _read_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class StoryKeyFromSessionNameTests(unittest.TestCase):
    def test_extracts_dotted_story_id_from_runner_session_name(self) -> None:
        self.assertEqual(
            tmux_runtime._story_key_from_session_name(
                "sa-acme-251215-104500-e2-s2-7-dev"
            ),
            "2.7",
        )

    def test_extracts_with_cycle_suffix(self) -> None:
        self.assertEqual(
            tmux_runtime._story_key_from_session_name(
                "sa-acme-251215-104500-e10-s10-12-review-r2"
            ),
            "10.12",
        )

    def test_returns_empty_for_unparseable_name(self) -> None:
        self.assertEqual(tmux_runtime._story_key_from_session_name("manual"), "")

    def test_returns_empty_for_empty_string(self) -> None:
        self.assertEqual(tmux_runtime._story_key_from_session_name(""), "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_tmux_runtime.StoryKeyFromSessionNameTests -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_story_key_from_session_name'`.

- [ ] **Step 3: Add the helper**

Add to `tmux_runtime.py` near `generate_session_name` (around line 87):

```python
_STORY_KEY_RE = re.compile(r"-e(\d+)-s(\d+)-(\d+)-")


def _story_key_from_session_name(session: str) -> str:
    """Extract dotted story_key (e.g. "2.7") from a session name produced by
    generate_session_name(): `sa-{slug}-{stamp}-e{epic}-s{epic}-{story}-{step}`.

    Returns "" when the pattern does not match — for legacy / hand-crafted
    session names — so the emit path stays warning-free.
    """
    match = _STORY_KEY_RE.search(session)
    if not match:
        return ""
    return f"{match.group(2)}.{match.group(3)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_tmux_runtime.StoryKeyFromSessionNameTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_wire_tmux_runtime.py skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): add _story_key_from_session_name helper for tmux wiring (REQ-11)"
```

---

## Task 5: Populate `story_key` in `_emit_tmux_spawned`

**Files:**
- Modify: `tests/test_wire_tmux_runtime.py` (append test class)
- Modify: `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py:278-298`

- [ ] **Step 1: Write the failing test**

Append:

```python
class EmitTmuxSpawnedWiringTests(unittest.TestCase):
    def test_emit_spawned_populates_story_key_from_session_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            emitter, factory = _patched_emitter_factory(tmp)
            with mock.patch.object(
                tmux_runtime, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                tmux_runtime, "_session_pid", return_value="99"
            ), mock.patch.object(
                tmux_runtime, "run_cmd", return_value=("200x50", 0)
            ):
                tmux_runtime._emit_tmux_spawned(
                    "sa-acme-251215-104500-e4-s4-9-dev", project_root=str(tmp)
                )
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "tmux_session_spawned")
            self.assertEqual(
                ev["session_name"], "sa-acme-251215-104500-e4-s4-9-dev"
            )
            self.assertEqual(ev["story_key"], "4.9")
            self.assertEqual(ev["pid"], 99)
            self.assertEqual(ev["pane_geometry"], "200x50")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_tmux_runtime.EmitTmuxSpawnedWiringTests -v`
Expected: FAIL — `story_key` is `""`.

- [ ] **Step 3: Populate `story_key` in `_emit_tmux_spawned`**

In `tmux_runtime.py` replace the `TmuxSessionSpawned(...)` block inside `_emit_tmux_spawned` to derive `story_key`:

```python
def _emit_tmux_spawned(session: str, project_root: str | None) -> None:
    pid = _safe_int(_session_pid(session))
    geom_out, geom_code = run_cmd(
        "tmux",
        "display-message",
        "-p",
        "-t",
        session,
        "#{pane_width}x#{pane_height}",
    )
    geometry = geom_out.strip() if geom_code == 0 else ""
    _telemetry_emitter(project_root).emit(
        TmuxSessionSpawned(
            timestamp=iso_now(),
            run_id="",
            session_name=session,
            story_key=_story_key_from_session_name(session),
            pid=pid,
            pane_geometry=geometry,
        )
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_tmux_runtime.EmitTmuxSpawnedWiringTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_wire_tmux_runtime.py skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): populate story_key on TmuxSessionSpawned (REQ-11)"
```

---

## Task 6: Populate `story_key` in `_emit_tmux_completed` and `_emit_tmux_crashed`

**Files:**
- Modify: `tests/test_wire_tmux_runtime.py` (append test classes)
- Modify: `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py:387-422` (`_emit_tmux_completed`, `_emit_tmux_crashed`)

- [ ] **Step 1: Write the failing tests**

Append:

```python
class EmitTmuxCompletedWiringTests(unittest.TestCase):
    def test_emit_completed_populates_story_key_and_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            state = {"exitCode": 0, "durationSeconds": 12.5}
            with mock.patch.object(
                tmux_runtime, "emitter_for_project_root", side_effect=factory
            ):
                tmux_runtime._emit_tmux_completed(
                    "sa-acme-251215-104500-e5-s5-2-review",
                    state,
                    str(tmp),
                )
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "tmux_session_completed")
            self.assertEqual(ev["story_key"], "5.2")
            self.assertEqual(ev["exit_code"], 0)
            self.assertEqual(ev["duration_s"], 12.5)


class EmitTmuxCrashedWiringTests(unittest.TestCase):
    def test_emit_crashed_populates_story_key_and_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            state = {"exitCode": 137, "lastCaptureChars": 1024}
            with mock.patch.object(
                tmux_runtime, "emitter_for_project_root", side_effect=factory
            ):
                tmux_runtime._emit_tmux_crashed(
                    "sa-acme-251215-104500-e6-s6-1-create",
                    state,
                    str(tmp),
                )
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(len(events), 1)
            ev = events[0]
            self.assertEqual(ev["event_type"], "tmux_session_crashed")
            self.assertEqual(ev["story_key"], "6.1")
            self.assertEqual(ev["exit_code"], 137)
            self.assertEqual(ev["last_capture_chars"], 1024)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_tmux_runtime.EmitTmuxCompletedWiringTests tests.test_wire_tmux_runtime.EmitTmuxCrashedWiringTests -v`
Expected: both FAIL on `story_key`.

- [ ] **Step 3: Populate `story_key` in both emits**

In `tmux_runtime.py` update `_emit_tmux_completed`:

```python
def _emit_tmux_completed(
    session: str,
    state: dict,
    project_root: str | None,
) -> None:
    exit_code = _safe_int(state.get("exitCode"))
    duration_s = float(state.get("durationSeconds") or 0.0)
    _telemetry_emitter(project_root).emit(
        TmuxSessionCompleted(
            timestamp=iso_now(),
            run_id="",
            session_name=session,
            story_key=_story_key_from_session_name(session),
            exit_code=exit_code,
            duration_s=duration_s,
        )
    )
```

And `_emit_tmux_crashed`:

```python
def _emit_tmux_crashed(
    session: str,
    state: dict,
    project_root: str | None,
) -> None:
    exit_code = _safe_int(state.get("exitCode"))
    last_capture = _safe_int(state.get("lastCaptureChars"))
    _telemetry_emitter(project_root).emit(
        TmuxSessionCrashed(
            timestamp=iso_now(),
            run_id="",
            session_name=session,
            story_key=_story_key_from_session_name(session),
            exit_code=exit_code,
            last_capture_chars=last_capture,
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_tmux_runtime -v`
Expected: PASS (all 6 tests in the file).

- [ ] **Step 5: Commit**

```bash
git add tests/test_wire_tmux_runtime.py skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(telemetry): populate story_key on TmuxSessionCompleted + Crashed (REQ-11)"
```

---

## Task 7: Wiring test for `check_blocking_action` EscalationTriggered emit

**Files:**
- Create: `tests/test_wire_epic_agents.py`

This task introduces wiring-level confidence for `orchestrator_epic_agents.py` (REQ-10). The emit field population there is already correct (epic + story_key); the test pins the wiring shape so a refactor cannot silently drop the emit.

- [ ] **Step 1: Write the test**

```python
# tests/test_wire_epic_agents.py
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator_epic_agents as epic_agents
from story_automator.core.telemetry_emitter import TelemetryEmitter


def _patched_emitter_factory(tmp: Path):
    emitter = TelemetryEmitter(tmp / "events.jsonl")

    def factory(_project_root):
        return emitter

    return emitter, factory


def _read_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class CheckBlockingWiringTests(unittest.TestCase):
    def test_escalation_triggered_emit_includes_epic_story_severity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            epic_file = tmp / "epic-7.md"
            epic_file.write_text(
                "### Story 7.3: Build X\n"
                "Dependencies: 7.1, 7.2\n"
                "### Story 7.1: Foundation\n"
                "Dependencies: none\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                epic_agents, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                epic_agents, "get_project_root", return_value=str(tmp)
            ), mock.patch.object(
                epic_agents, "find_epic_file", return_value=str(epic_file)
            ):
                rc = epic_agents.check_blocking_action(["7.1"])
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            # Some lines may not match the dependent pattern; assert at least one EscalationTriggered.
            triggered = [e for e in events if e["event_type"] == "escalation_triggered"]
            self.assertEqual(len(triggered), 1)
            ev = triggered[0]
            self.assertEqual(ev["epic"], "7")
            self.assertEqual(ev["story_key"], "7.1")
            self.assertEqual(ev["severity"], "warning")
            self.assertIn("blocked by", ev["message"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it passes (regression-pin only — emit fields are already correct)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_epic_agents.CheckBlockingWiringTests -v`
Expected: PASS (this is a regression-pin around correct existing behavior).

- [ ] **Step 3: Commit**

```bash
git add tests/test_wire_epic_agents.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): pin check_blocking EscalationTriggered wiring (REQ-10)"
```

---

## Task 8: Wiring test for `agents_resolve_action` RetryAttempt emit

**Files:**
- Modify: `tests/test_wire_epic_agents.py` (append test class)

- [ ] **Step 1: Write the test**

Append:

```python
class AgentsResolveRetryWiringTests(unittest.TestCase):
    def test_retry_attempt_emitted_on_attempt_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            agents_file = tmp / "agents.md"
            agents_file.write_text(
                "```json\n"
                + json.dumps(
                    {
                        "stories": [
                            {
                                "storyId": "4.2",
                                "complexity": "medium",
                                "tasks": {
                                    "dev": {
                                        "primary": "claude",
                                        "fallback": "false",
                                        "model": "sonnet",
                                    }
                                },
                            }
                        ]
                    }
                )
                + "\n```\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                epic_agents, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                epic_agents, "get_project_root", return_value=str(tmp)
            ):
                rc = epic_agents.agents_resolve_action(
                    [
                        "--agents-file",
                        str(agents_file),
                        "--story",
                        "4.2",
                        "--task",
                        "dev",
                        "--attempt",
                        "2",
                        "--prev-error-class",
                        "test_fail",
                    ]
                )
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            retries = [e for e in events if e["event_type"] == "retry_attempt"]
            self.assertEqual(len(retries), 1)
            ev = retries[0]
            self.assertEqual(ev["epic"], "4")
            self.assertEqual(ev["story_key"], "4.2")
            self.assertEqual(ev["attempt_num"], 2)
            self.assertEqual(ev["agent"], "claude")
            self.assertEqual(ev["model"], "sonnet")
            self.assertEqual(ev["prev_error_class"], "test_fail")

    def test_no_retry_attempt_emitted_on_attempt_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            agents_file = tmp / "agents.md"
            agents_file.write_text(
                "```json\n"
                + json.dumps(
                    {
                        "stories": [
                            {
                                "storyId": "4.2",
                                "complexity": "medium",
                                "tasks": {
                                    "dev": {"primary": "claude", "fallback": "false"}
                                },
                            }
                        ]
                    }
                )
                + "\n```\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                epic_agents, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                epic_agents, "get_project_root", return_value=str(tmp)
            ):
                epic_agents.agents_resolve_action(
                    [
                        "--agents-file",
                        str(agents_file),
                        "--story",
                        "4.2",
                        "--task",
                        "dev",
                        "--attempt",
                        "1",
                    ]
                )
            events = _read_lines(tmp / "events.jsonl")
            self.assertEqual(
                [e for e in events if e["event_type"] == "retry_attempt"], []
            )
```

- [ ] **Step 2: Run tests to verify they pass (regression-pin)**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_epic_agents.AgentsResolveRetryWiringTests -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_wire_epic_agents.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): pin agents_resolve RetryAttempt emit threshold (REQ-10)"
```

---

## Task 9: Wiring test for `retro_agent_action` RetroFired emit

**Files:**
- Modify: `tests/test_wire_epic_agents.py` (append test class)

- [ ] **Step 1: Write the test**

Append:

```python
class RetroAgentWiringTests(unittest.TestCase):
    def test_retro_fired_emit_uses_frontmatter_agentConfig(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            _, factory = _patched_emitter_factory(tmp)
            state_file = tmp / "state.md"
            state_file.write_text(
                "---\n"
                "epic: 9\n"
                "agentConfig:\n"
                "  epic: 9\n"
                "  storiesCompleted: 3\n"
                "  totalCostUsd: 2.50\n"
                "  durationSeconds: 360.0\n"
                "---\n# state\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                epic_agents, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                epic_agents, "get_project_root", return_value=str(tmp)
            ):
                rc = epic_agents.retro_agent_action(
                    ["--state-file", str(state_file)]
                )
            self.assertEqual(rc, 0)
            events = _read_lines(tmp / "events.jsonl")
            retros = [e for e in events if e["event_type"] == "retro_fired"]
            self.assertEqual(len(retros), 1)
            ev = retros[0]
            self.assertEqual(ev["epic"], "9")
            self.assertEqual(ev["stories_completed"], 3)
            self.assertEqual(ev["total_cost_usd"], 2.5)
            self.assertEqual(ev["duration_s"], 360.0)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_epic_agents.RetroAgentWiringTests -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_wire_epic_agents.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): pin retro_agent RetroFired wiring (REQ-10)"
```

---

## Task 10: End-to-end integration test (emit sites → reader aggregations)

**Files:**
- Create: `tests/test_wire_integration.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_wire_integration.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from story_automator.commands import orchestrator
from story_automator.core import tmux_runtime
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_reader import TelemetryReader


class WiredEmitsFlowThroughReaderTests(unittest.TestCase):
    def test_review_cycle_and_tmux_emits_appear_in_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            telem_path = tmp / "events.jsonl"
            emitter = TelemetryEmitter(telem_path)

            def factory(_project_root):
                return emitter

            with mock.patch.object(
                orchestrator, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                orchestrator, "get_project_root", return_value=str(tmp)
            ), mock.patch.object(
                orchestrator,
                "verify_code_review_completion",
                return_value={"verified": True, "cycle": 1, "issuesFound": 0},
            ), mock.patch.object(
                tmux_runtime, "emitter_for_project_root", side_effect=factory
            ):
                orchestrator._verify_code_review(["2.5"])
                tmux_runtime._emit_tmux_completed(
                    "sa-acme-251215-104500-e2-s2-5-dev",
                    {"exitCode": 0, "durationSeconds": 4.0},
                    str(tmp),
                )

            reader = TelemetryReader(telem_path)
            types = [type(ev).__name__ for ev in reader.iter_events()]
            self.assertIn("ReviewCycle", types)
            self.assertIn("TmuxSessionCompleted", types)

    def test_attempts_by_story_aggregation_sees_wired_retry(self) -> None:
        from story_automator.commands import orchestrator_epic_agents as epic_agents
        import json

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            telem_path = tmp / "events.jsonl"
            emitter = TelemetryEmitter(telem_path)

            def factory(_project_root):
                return emitter

            agents_file = tmp / "agents.md"
            agents_file.write_text(
                "```json\n"
                + json.dumps(
                    {
                        "stories": [
                            {
                                "storyId": "1.1",
                                "complexity": "low",
                                "tasks": {
                                    "dev": {"primary": "claude", "fallback": "false"}
                                },
                            }
                        ]
                    }
                )
                + "\n```\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                epic_agents, "emitter_for_project_root", side_effect=factory
            ), mock.patch.object(
                epic_agents, "get_project_root", return_value=str(tmp)
            ):
                for attempt in (2, 3):
                    epic_agents.agents_resolve_action(
                        [
                            "--agents-file",
                            str(agents_file),
                            "--story",
                            "1.1",
                            "--task",
                            "dev",
                            "--attempt",
                            str(attempt),
                        ]
                    )

            reader = TelemetryReader(telem_path)
            self.assertEqual(reader.attempts_by_story(), {("1", "1.1"): 2})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_wire_integration -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_wire_integration.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(telemetry): integration: wired emits flow through TelemetryReader (REQ-09/10/11)"
```

---

## Task 11: Import-allowlist gate (REQ-14)

**Files:**
- Create (temporary): `tests/_check_imports.py` — a portable allowlist checker. Delete after the check passes.

- [ ] **Step 1: Write the checker script**

```python
# tests/_check_imports.py
"""One-shot allowlist gate for M02 + M03 wiring. Delete after running."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ALLOWED_TOP_LEVEL = {
    "__future__", "json", "os", "re", "sys", "pathlib", "typing",
    "dataclasses", "tempfile", "threading", "datetime", "shlex", "shutil",
    "time", "collections", "unittest", "abc",
    "filelock", "psutil",
    "story_automator",
}

TARGET_PATHS = [
    "skills/bmad-story-automator/src/story_automator/core/telemetry_emitter.py",
    "skills/bmad-story-automator/src/story_automator/core/telemetry_reader.py",
    "skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py",
    "skills/bmad-story-automator/src/story_automator/commands/orchestrator.py",
    "skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py",
]


def offenders(path: str) -> list[str]:
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in ALLOWED_TOP_LEVEL:
                    out.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top not in ALLOWED_TOP_LEVEL:
                out.append(f"from {node.module}")
    return out


def main() -> int:
    violations: list[tuple[str, str]] = []
    for path in TARGET_PATHS:
        for offender in offenders(path):
            violations.append((path, offender))
    if violations:
        for path, line in violations:
            print(f"VIOLATION: {path}: {line}")
        return 1
    print("OK: no third-party imports outside allowlist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the script**

Run: `python tests/_check_imports.py`
Expected: `OK: no third-party imports outside allowlist` and exit code 0.

If any violations print, the offending import was introduced during M03 — remove it (no scope-creep imports per REQ-14).

- [ ] **Step 3: Delete the script and verify clean tree**

Run: `git ls-files --others --exclude-standard` should not show `tests/_check_imports.py` after removal.

```bash
rm tests/_check_imports.py
```

- [ ] **Step 4: No commit needed for this gate (script is throwaway).**

---

## Task 12: Full quality gates (lint, format, full unittest, coverage)

**Files:**
- (verification only)

- [ ] **Step 1: Lint the new + edited files**

Run:

```bash
python -m ruff check \
  skills/bmad-story-automator/src/story_automator/commands/orchestrator.py \
  skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py \
  tests/test_wire_orchestrator.py \
  tests/test_wire_tmux_runtime.py \
  tests/test_wire_epic_agents.py \
  tests/test_wire_integration.py
```

Expected: no violations. If any appear, fix in place and re-run.

- [ ] **Step 2: Format check**

Run:

```bash
python -m ruff format --check \
  skills/bmad-story-automator/src/story_automator/commands/orchestrator.py \
  skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py \
  tests/test_wire_orchestrator.py \
  tests/test_wire_tmux_runtime.py \
  tests/test_wire_epic_agents.py \
  tests/test_wire_integration.py
```

Expected: `0 files would be reformatted`. If files need formatting, run without `--check` and re-run the check.

- [ ] **Step 3: Full repository test suite**

Run: `npm run test:python`
Expected: zero failures. All M01 + M02 + M03 tests green.

- [ ] **Step 4: Coverage on the wiring-relevant modules (the M02 quality-gate command)**

Run:

```bash
python -m coverage run --source=skills/bmad-story-automator/src/story_automator/core/telemetry_emitter,skills/bmad-story-automator/src/story_automator/core/telemetry_reader -m unittest tests.test_telemetry_emitter tests.test_telemetry_reader
python -m coverage report -m --fail-under=85
```

Expected: passes the 85% gate (M02-locked behavior unchanged; this just verifies M03 wiring didn't regress it).

- [ ] **Step 5: Commit any formatting-only fixes from steps 1-2**

```bash
git add -p   # interactive — stage only format/lint fixes
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(telemetry): ruff format/lint cleanup for M03 wiring"
```

Skip the commit if no changes were needed.

---

## Task 13: Final status check

**Files:** (none — verification only)

- [ ] **Step 1: Verify the wiring requirements**

Mentally walk through:
- REQ-09 (orchestrator.py): `_marker`, `_escalate session-crash`, `_commit_ready`, `_verify_code_review` — all emit typed events with non-empty `epic`/`story_key` where local context provides them. ✓
- REQ-10 (orchestrator_epic_agents.py): `check_blocking_action` → EscalationTriggered, `agents_resolve_action` → RetryAttempt (attempt ≥ 2), `retro_agent_action` → RetroFired. All pinned by tests. ✓
- REQ-11 (tmux_runtime.py): `_emit_tmux_spawned` / `_emit_tmux_completed` / `_emit_tmux_crashed` all populate `story_key` from session name. ✓
- REQ-14 (import allowlist): grep step 11 confirms zero third-party imports outside `filelock` / `psutil`. ✓
- Quality gates (lint, format, test, coverage): all green from step 12. ✓

- [ ] **Step 2: Verify clean working tree**

Run: `git status`
Expected: working tree clean (no untracked, no modified). All M03 changes are committed.

---

## Self-Review Notes

- **Spec coverage:** REQ-09 covered by Tasks 1-3, REQ-10 by Tasks 7-9, REQ-11 by Tasks 4-6, REQ-14 by Task 11, Quality gates by Task 12. Tasks 10 + 13 provide integration confidence.
- **No placeholder text:** every step contains exact code or commands.
- **Field-population scope:** only fields derivable from local context are populated. `agent`/`model`/`complexity` on `StoryStarted` (marker-create) and `duration_s`/`cost_usd`/`tokens_in`/`tokens_out` on `StoryCompleted` remain at `""` / `0` per the M02 spec — populating those is deferred to M03/M07/M08 cost-capture work (out-of-scope here, explicitly per spec lines 8-9).
- **No new helpers in `core/common.py`** per REQ-15.
- **No new third-party dependencies** per REQ-14.
- **Type consistency:** `_story_key_from_session_name` is the single source of truth for tmux story-key extraction (referenced by Tasks 4, 5, 6).
- **Test patching:** all tests patch `emitter_for_project_root` on the *imported* module symbol (not the source) so the module-cached factory in `_PROJECT_EMITTERS` is bypassed. Each test uses its own fresh `TelemetryEmitter` per `tempfile.TemporaryDirectory`.
