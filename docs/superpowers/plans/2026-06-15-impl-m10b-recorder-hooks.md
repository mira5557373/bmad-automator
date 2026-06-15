# M10b — Golden-Trace Recorder + Interception Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the `GoldenTraceRecorder` context manager + interception hooks for the three observable channels (telemetry emit, state-document writes, `claude_p` invocations), enforce arrival ordering with a `threading.Lock`, apply REQ-13 redaction of non-deterministic fields, and guarantee REQ-14 hook restoration even when the recorded block raises. Pure data layer (`TraceEntry`, `serialize_trace`, `load_golden`, `compare_traces`, `GoldenTraceError`) has already shipped in M10a — do not re-implement it.

**Architecture:** Extend the single file `tests/golden_trace_helpers.py` (deliberately outside `src/`) with `GoldenTraceRecorder` and a module-level `notify_claude_p(argv)` hook surface. The claude_p channel uses an explicit opt-in shim (`notify_claude_p`) rather than monkey-patching `subprocess.run` globally: subprocess-patching would capture every `tmux`/`pgrep`/`ps` invocation in `core.tmux_runtime` as well, producing massive false-positive entries the spec didn't ask for. The shim accepts the cost that production wiring (M10+) must add explicit `notify_claude_p([...])` calls at each real `claude -p` site — wiring is out of scope for M10b. For M10b's test coverage, tests invoke the shim directly. On `__enter__`, the recorder (a) installs a wrapper around `TelemetryEmitter.emit` by class-level attribute reassignment (works for every instance because attribute lookup goes through the MRO); (b) installs a wrapper around `story_automator.commands.state.write_atomic_text` by module-level attribute reassignment (state.py already imported the name, so we patch the binding inside the state module); (c) swaps the module-level `notify_claude_p` so any caller invoking `golden_trace_helpers.notify_claude_p(argv)` is recorded. Arrival ordering is serialized by `threading.Lock`. On `__exit__` (success or failure), every wrapper is restored from a saved-original stack — never partial. Redaction is applied at record time, not serialize time, so the in-memory `list[TraceEntry]` is already byte-determinizable.

**Fixture-author contract (carried into M10c):** Floating-point fields that vary across runs by definition (`duration_s`, `cost_usd`, `total_cost_usd`, `tokens_in`, `tokens_out`) are NOT in the redaction set — M10c fixture authors must construct event instances with deterministic literal values (no real wall-clock measurements, no `iso_now()`, no real PIDs). The redaction set only covers fields the recorder cannot detect from the event class definition (PIDs, session names embedding PIDs, lock-token UUIDs, heartbeat counters). The M01 round-trip fixture (one StoryStarted event) and M02 emitter smoke (five StoryStarted events) construct events with literal `epic="e"`, `story_key="s1".."s5"`, etc. — they have no float fields, so this contract is enforced trivially.

**Tech Stack:** Python 3.11+ stdlib only (`threading`, `pathlib`, `hashlib`, `dataclasses`, `types`, `typing`). No third-party deps. `ruff` + `mypy --strict` clean. `unittest.TestCase` per project convention. The M01 telemetry classes, M05 atomic-io, and M10a data types are imported but not modified.

**Imports convention:** Every code block in this plan that shows additions to either `tests/golden_trace_helpers.py` or `tests/test_golden_trace_helpers.py` shows the new symbols inline at the top of the snippet for readability, but the actual implementation **must consolidate all imports at the top of the file** (per `ruff E402`). When a task says "append" a test class, the test class body goes at the bottom of the file, and any imports it needs are merged into the top-of-file import block — do not let imports drift down between class definitions. Use grouped sections: stdlib first, then `story_automator.*`, then `tests.golden_trace_helpers` last.

---

## Scope boundary (anti-scope-creep)

**In scope for M10b (this plan):**
- REQ-01: `GoldenTraceRecorder` context manager that installs/removes the three hooks and finalizes `list[TraceEntry]`.
- REQ-03: `TelemetryEmitter.emit` interception → `event` entry; `payload["timestamp"]` replaced with literal `"<ts>"`.
- REQ-04: `commands.state` write interception (routed through `core.atomic_io.write_atomic_text`) → `state` entry with `path` (repo-relative POSIX) + `sha256` of post-write bytes.
- REQ-05: `claude_p` invocation interception via a `notify_claude_p(argv)` hook surface; argv absolute paths normalized to repo-relative POSIX; four-letter placeholder tokens preserved verbatim.
- REQ-06: single `threading.Lock` guarding arrival-order assignment + entry append.
- REQ-13: redaction of timestamps / PIDs / lock-token UUIDs / heartbeat counters → `"<redacted>"` (timestamp uses `"<ts>"` per REQ-03's narrower contract); four-letter placeholders left untouched.
- REQ-14: zero side-effects at import; `__exit__` restores originals even on exception.
- NFR Isolation: two sequential `with` blocks produce independent traces; no module-level state leaks between runs.
- NFR Safety: passive-observer semantics — `emit`/`write_atomic_text`/`notify_claude_p` return the original values, raise the original exceptions, and the recorded operations complete normally.

**Out of scope for M10b (deferred):**
- M10c: the three shipped golden fixtures (`tests/golden/m01_event_basics.json`, `tests/golden/m02_emitter_smoke.json`, `tests/golden/m05_atomic_write_smoke.json`) and REQ-12 sub-cases (a) and (e) which exercise those fixtures end-to-end. M10b only ships the recorder; M10c ships the fixtures.
- Wiring `notify_claude_p` into real production call sites (real `claude -p` subprocess invocations). M10b adds the hook surface; future milestones wire it.
- Any change to the M10a pure-data layer (`TraceEntry`, `serialize_trace`, `load_golden`, `compare_traces`, `GoldenTraceError`).

If a later task in this plan looks like it's drifting into fixture creation or production wiring — stop, that's M10c.

---

## File structure

**Modify:**
- `tests/golden_trace_helpers.py` — append `GoldenTraceRecorder`, `notify_claude_p`, and the internal hook-installation / redaction helpers. Extend `__all__`.
- `tests/test_golden_trace_helpers.py` — append `unittest.TestCase` classes for every public symbol added in M10b.

**Do not modify:**
- Any file under `skills/bmad-story-automator/src/` (M10 is pure testing infrastructure).
- `pyproject.toml` (no new deps).
- Anything else.

---

## Public surface (locked here so later tasks use the same identifiers)

```python
# tests/golden_trace_helpers.py — M10b additions
__all__ = [  # appended to the existing M10a __all__
    "Channel",
    "GoldenTraceError",
    "GoldenTraceRecorder",       # NEW
    "MismatchField",
    "TraceDiff",
    "TraceEntry",
    "TraceMismatch",
    "compare_traces",
    "load_golden",
    "notify_claude_p",           # NEW
    "serialize_trace",
]


class GoldenTraceRecorder:
    def __init__(self, *, repo_root: Path | None = None) -> None: ...
    def __enter__(self) -> GoldenTraceRecorder: ...
    def __exit__(self, exc_type, exc, tb) -> None: ...
    @property
    def entries(self) -> list[TraceEntry]: ...


def notify_claude_p(argv: list[str]) -> None:
    """Module-level hook surface. No-op when no recorder is active; the
    recorder swaps this on __enter__ to capture argv into the trace."""
```

`_HEARTBEAT_LOCK_SUFFIXES`, `_REDACTED_EVENT_FIELDS`, `_TS_SENTINEL`, `_REDACTED_SENTINEL` are private module constants introduced in later tasks.

---

## Task 1: Bootstrap recorder stub + extend `__all__`

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
from tests.golden_trace_helpers import GoldenTraceRecorder, notify_claude_p


class RecorderSurfaceTests(unittest.TestCase):
    def test_recorder_exported(self) -> None:
        module = importlib.import_module("tests.golden_trace_helpers")
        self.assertIn("GoldenTraceRecorder", module.__all__)
        self.assertIn("notify_claude_p", module.__all__)

    def test_notify_claude_p_is_noop_when_no_recorder_active(self) -> None:
        # Calling the hook outside any `with` block must return None and
        # must not raise — production wiring will call this from every
        # claude -p invocation, recorded or not.
        self.assertIsNone(notify_claude_p(["claude", "-p", "x"]))

    def test_recorder_constructs_with_no_args(self) -> None:
        rec = GoldenTraceRecorder()
        self.assertEqual(rec.entries, [])
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderSurfaceTests -v`
Expected: FAIL — `ImportError: cannot import name 'GoldenTraceRecorder'`.

- [ ] **Step 3: Add the stub recorder and hook surface**

Append to `tests/golden_trace_helpers.py` (above `__all__`, then update `__all__`):

```python
import threading
from pathlib import Path


def notify_claude_p(argv: list[str]) -> None:
    """Hook surface for `claude -p` invocations.

    No-op when no recorder is active. ``GoldenTraceRecorder.__enter__``
    swaps the module-level ``_CLAUDE_P_HOOK`` slot (NOT this function
    itself), so callers that did ``from tests.golden_trace_helpers
    import notify_claude_p`` still see the active recorder because the
    function body re-reads the module-global slot on every call.
    """
    return None


class GoldenTraceRecorder:
    """Context manager that records arrival-ordered observations of
    telemetry emits, state-document mutations, and claude_p invocations.

    See REQ-01/REQ-03/REQ-04/REQ-05/REQ-06/REQ-13/REQ-14 in the M10 spec.
    """

    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._entries: list[TraceEntry] = []
        self._lock = threading.Lock()
        self._repo_root: Path | None = repo_root
        self._installed = False

    @property
    def entries(self) -> list[TraceEntry]:
        """Defensive copy so callers cannot mutate the recorder's buffer."""
        return list(self._entries)

    def __enter__(self) -> GoldenTraceRecorder:
        # Hook installation lands in Tasks 3-5, 7, 10.
        self._installed = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        # Hook restoration lands in Tasks 3-5, 7, 10.
        self._installed = False
        return None
```

Update the existing `__all__` list to include `"GoldenTraceRecorder"` and `"notify_claude_p"` in alphabetical order. Merge `threading` and `Path` into the top-of-file imports (`from pathlib import Path` already exists from M10a; only `threading` is new).

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderSurfaceTests -v`
Expected: PASS for all 3 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): bootstrap GoldenTraceRecorder stub and notify_claude_p hook"
```

---

## Task 2: Internal `_record(channel, kind, payload)` under the arrival lock (REQ-06)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
import threading as _threading


class RecorderArrivalOrderingTests(unittest.TestCase):
    def test_record_assigns_monotonic_seq_starting_at_zero(self) -> None:
        rec = GoldenTraceRecorder()
        rec._record("event", "StoryStarted", {"epic": "1"})  # type: ignore[attr-defined]
        rec._record("state", "mutation", {"path": "p", "sha256": "x"})  # type: ignore[attr-defined]
        rec._record("claude_p", "invoke", {"argv": ["claude"]})  # type: ignore[attr-defined]
        self.assertEqual([e.seq for e in rec.entries], [0, 1, 2])
        self.assertEqual([e.channel for e in rec.entries], ["event", "state", "claude_p"])
        self.assertEqual([e.kind for e in rec.entries], ["StoryStarted", "mutation", "invoke"])

    def test_record_is_thread_safe_under_concurrent_callers(self) -> None:
        # Two threads racing on _record must each get a unique seq and
        # the resulting trace must contain exactly 200 entries with
        # contiguous 0..199 seqs (no duplicates, no gaps). The order
        # of the entries themselves is non-deterministic (that's the
        # underlying operations' problem), but the seq numbering is not.
        rec = GoldenTraceRecorder()

        def worker(label: str) -> None:
            for i in range(100):
                rec._record("event", label, {"i": i})  # type: ignore[attr-defined]

        t1 = _threading.Thread(target=worker, args=("A",))
        t2 = _threading.Thread(target=worker, args=("B",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        seqs = sorted(e.seq for e in rec.entries)
        self.assertEqual(seqs, list(range(200)))
        self.assertEqual(len(rec.entries), 200)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderArrivalOrderingTests -v`
Expected: FAIL — `_record` does not exist on the recorder yet.

- [ ] **Step 3: Implement `_record`**

Add to `GoldenTraceRecorder` in `tests/golden_trace_helpers.py`:

```python
    def _record(self, channel: Channel, kind: str, payload: dict[str, object]) -> None:
        """Append one entry under the arrival lock (REQ-06).

        The lock serializes (a) the seq assignment and (b) the list
        append so that traces produced under concurrent threads receive
        deterministic, contiguous seq numbers. Operation completion
        order itself is still the underlying code's problem.
        """
        with self._lock:
            seq = len(self._entries)
            self._entries.append(
                TraceEntry(seq=seq, channel=channel, kind=kind, payload=dict(payload))
            )
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderArrivalOrderingTests -v`
Expected: PASS for both cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): add thread-safe _record on recorder"
```

---

## Task 3: Repo-root resolution + path normalization helper

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
import os
import tempfile

from tests.golden_trace_helpers import _to_repo_relative_posix  # type: ignore[attr-defined]


class PathNormalizationTests(unittest.TestCase):
    def test_absolute_path_under_repo_becomes_repo_relative_posix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            inner = root / "telemetry" / "events.jsonl"
            inner.parent.mkdir(parents=True)
            inner.write_text("", encoding="utf-8")
            out = _to_repo_relative_posix(inner, repo_root=root)
        self.assertEqual(out, "telemetry/events.jsonl")

    def test_unrelated_absolute_path_returned_as_posix_absolute(self) -> None:
        # Paths outside repo_root are preserved as absolute POSIX so the
        # recorded trace still localizes them; cross-OS comparison of such
        # entries is the test author's problem (the spec is explicit about
        # not normalizing beyond converting absolute paths under the repo).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            outside = Path(tempfile.gettempdir()).resolve() / "unrelated.txt"
            out = _to_repo_relative_posix(outside, repo_root=root)
        self.assertEqual(out, outside.as_posix())

    def test_relative_path_preserved_as_posix(self) -> None:
        out = _to_repo_relative_posix(Path("tests") / "foo.json", repo_root=Path.cwd())
        self.assertEqual(out, "tests/foo.json")

    def test_backslashes_normalized_to_forward_slashes(self) -> None:
        # Pure-Path round-trip: even on Linux, a PureWindowsPath should
        # serialize to forward slashes. Using `as_posix` covers this.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "a").mkdir()
            (root / "a" / "b.txt").write_text("", encoding="utf-8")
            out = _to_repo_relative_posix(root / "a" / "b.txt", repo_root=root)
        self.assertNotIn(os.sep if os.sep == "\\" else "\x00", out)
        self.assertEqual(out, "a/b.txt")
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.PathNormalizationTests -v`
Expected: FAIL — `_to_repo_relative_posix` does not exist.

- [ ] **Step 3: Implement the helper**

Add to `tests/golden_trace_helpers.py` (top-level, near other private helpers):

```python
def _to_repo_relative_posix(path: Path, *, repo_root: Path) -> str:
    """Return a repo-relative POSIX path string for ``path`` (REQ-04/05).

    If ``path`` lies inside ``repo_root``, return the relative POSIX
    form. Otherwise return ``path`` as an absolute POSIX string — the
    spec is explicit about not normalizing beyond repo-relative
    conversion (see Out of scope #4).
    """
    try:
        resolved = path.resolve()
    except OSError:
        resolved = Path(path)
    try:
        rel = resolved.relative_to(repo_root.resolve())
    except ValueError:
        return resolved.as_posix() if resolved.is_absolute() else Path(path).as_posix()
    return rel.as_posix()
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.PathNormalizationTests -v`
Expected: PASS for all 4 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): add repo-relative POSIX path helper"
```

---

## Task 4: Resolve `repo_root` automatically on the recorder

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class RecorderRepoRootResolutionTests(unittest.TestCase):
    def test_explicit_repo_root_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            rec = GoldenTraceRecorder(repo_root=root)
            self.assertEqual(rec._repo_root, root)  # type: ignore[attr-defined]

    def test_default_repo_root_finds_project_root(self) -> None:
        # Walking up from CWD must locate the project pyproject.toml (or
        # the repository root marker). We expect to find a directory that
        # contains either pyproject.toml or .git — testing only that some
        # repo_root is resolved, not its exact value, because tests run
        # from different CWDs.
        rec = GoldenTraceRecorder()
        resolved = rec._repo_root  # type: ignore[attr-defined]
        self.assertIsNotNone(resolved)
        assert resolved is not None
        # The resolved root must contain either a pyproject.toml or .git
        # (a discriminator for the project tree).
        self.assertTrue(
            (resolved / "pyproject.toml").exists() or (resolved / ".git").exists(),
            f"resolved repo_root {resolved} contains no project marker",
        )
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderRepoRootResolutionTests -v`
Expected: FAIL for the default-resolution test — `_repo_root` is currently `None` when no arg is passed.

- [ ] **Step 3: Implement auto-resolution**

Add to `tests/golden_trace_helpers.py` (top-level helper):

```python
def _find_repo_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` (or CWD) until we find a project marker.

    Markers, in order of preference: ``pyproject.toml``, ``.git``. If
    no marker is found, fall back to the start directory itself AND
    warn — silent fallback would otherwise let CI runs with a wrong
    CWD produce fixtures full of unstable absolute paths.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    warnings.warn(
        f"GoldenTraceRecorder: no project marker (pyproject.toml or .git) "
        f"found walking up from {current}; recorded paths may stay absolute",
        stacklevel=2,
    )
    return current
```

Update `GoldenTraceRecorder.__init__`:

```python
    def __init__(self, *, repo_root: Path | None = None) -> None:
        self._entries: list[TraceEntry] = []
        self._lock = threading.Lock()
        self._repo_root: Path = repo_root.resolve() if repo_root else _find_repo_root()
        self._installed = False
```

Note: `_repo_root` is now non-`None`. Update its type annotation and any callers that branched on `None`.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderRepoRootResolutionTests -v`
Expected: PASS for both cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): auto-resolve repo_root from project markers"
```

---

## Task 5: Hook `TelemetryEmitter.emit` — record `event` entries (REQ-03, half)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_events import StoryStarted


class EmitHookTests(unittest.TestCase):
    def test_emit_records_event_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z",
                run_id="r1",
                epic="e1",
                story_key="s1",
                agent="dev",
                model="opus",
                complexity="L",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        # Exactly one event entry, kind == class name, payload includes
        # the event fields.
        self.assertEqual(len(rec.entries), 1)
        entry = rec.entries[0]
        self.assertEqual(entry.channel, "event")
        self.assertEqual(entry.kind, "StoryStarted")
        # Payload carries the event fields (we'll cover timestamp
        # redaction in Task 6).
        self.assertEqual(entry.payload.get("epic"), "e1")
        self.assertEqual(entry.payload.get("story_key"), "s1")
        self.assertEqual(entry.payload.get("event_type"), "story_started")

    def test_emit_passes_through_normal_return(self) -> None:
        # NFR Safety: the recorded emit must complete with its normal
        # side effects — i.e., the file actually gets written.
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z", run_id="r1",
                epic="e", story_key="s", agent="a", model="m", complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)):
                emitter.emit(event)
            self.assertTrue(log.exists())
            self.assertGreater(log.stat().st_size, 0)

    def test_emit_hook_removed_on_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z", run_id="r1",
                epic="e", story_key="s", agent="a", model="m", complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
            # Outside the with block, emits must not append to the recorder.
            emitter.emit(event)
        self.assertEqual(len(rec.entries), 1)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.EmitHookTests -v`
Expected: FAIL — emit is not hooked yet, `rec.entries` stays empty.

- [ ] **Step 3: Install and restore the emit hook**

Add to `tests/golden_trace_helpers.py`. First, top-of-file imports:

```python
from story_automator.core.telemetry_emitter import TelemetryEmitter
```

Then extend `GoldenTraceRecorder`:

```python
    def __enter__(self) -> GoldenTraceRecorder:
        if self._installed:
            raise RuntimeError("GoldenTraceRecorder is not reentrant")
        # Save originals BEFORE any installation so __exit__ can restore
        # even if a later hook installation raises. Task 8 and Task 10
        # extend this to also save the state-write and claude_p hooks;
        # Task 12 hardens with a module-global active-recorder guard.
        self._orig_emit = TelemetryEmitter.emit
        self._install_emit_hook()
        self._installed = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        # Task 10 supersedes this with a collect-errors-and-raise-Group
        # pattern across all three hooks. Until then, only the emit hook
        # is installed, so a single try/finally suffices.
        try:
            TelemetryEmitter.emit = self._orig_emit  # type: ignore[method-assign]
        finally:
            self._installed = False
        return None

    def _install_emit_hook(self) -> None:
        orig = self._orig_emit
        recorder = self

        def wrapper(emitter_self: TelemetryEmitter, event: object) -> None:
            # Pass-through FIRST: a failed emit must NOT appear in the
            # trace (matches the state-write hook's ordering — only
            # observable, successful mutations are recorded).
            result = orig(emitter_self, event)
            payload: dict[str, object] = dict(event.to_dict())  # type: ignore[attr-defined]
            recorder._record("event", type(event).__name__, payload)
            return result

        TelemetryEmitter.emit = wrapper  # type: ignore[method-assign]
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.EmitHookTests -v`
Expected: PASS for all 3 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): hook TelemetryEmitter.emit for event recording"
```

---

## Task 6: Redact event payload timestamp → `"<ts>"` (REQ-03, second half)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class EventTimestampRedactionTests(unittest.TestCase):
    def test_timestamp_replaced_with_ts_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = StoryStarted(
                timestamp="2026-06-15T12:34:56Z", run_id="r",
                epic="e", story_key="s", agent="a", model="m", complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        self.assertEqual(rec.entries[0].payload["timestamp"], "<ts>")

    def test_emit_pass_through_keeps_original_timestamp_on_disk(self) -> None:
        # NFR Safety: redaction must not bleed into the actual emitter
        # output — the JSONL file gets the real timestamp.
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "events.jsonl"
            emitter = TelemetryEmitter(log)
            event = StoryStarted(
                timestamp="2026-06-15T12:34:56Z", run_id="r",
                epic="e", story_key="s", agent="a", model="m", complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)):
                emitter.emit(event)
            disk = log.read_text(encoding="utf-8")
        self.assertIn("2026-06-15T12:34:56Z", disk)
        self.assertNotIn("<ts>", disk)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.EventTimestampRedactionTests -v`
Expected: FAIL — timestamp not redacted yet.

- [ ] **Step 3: Apply timestamp redaction inside the emit wrapper**

In `tests/golden_trace_helpers.py`, add a module-level constant:

```python
_TS_SENTINEL = "<ts>"
```

Update the `wrapper` inside `_install_emit_hook`:

```python
        def wrapper(emitter_self: TelemetryEmitter, event: object) -> None:
            result = orig(emitter_self, event)
            payload: dict[str, object] = dict(event.to_dict())  # type: ignore[attr-defined]
            if "timestamp" in payload:
                payload["timestamp"] = _TS_SENTINEL
            recorder._record("event", type(event).__name__, payload)
            return result
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.EventTimestampRedactionTests -v`
Expected: PASS for both cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): redact event timestamps to <ts> sentinel"
```

---

## Task 7: Redact PID / lock-token / heartbeat fields in event payloads (REQ-13)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
from story_automator.core.telemetry_events import TmuxSessionSpawned


class EventRedactionTests(unittest.TestCase):
    def test_pid_redacted(self) -> None:
        # TmuxSessionSpawned carries a `pid: int`. The pid varies per run
        # by definition (REQ-13 calls out PIDs explicitly).
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = TmuxSessionSpawned(
                timestamp="2026-01-01T00:00:00Z", run_id="r",
                session_name="bmad-1", story_key="s1", pid=12345,
                pane_geometry="80x24",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        self.assertEqual(rec.entries[0].payload["pid"], "<redacted>")

    def test_session_name_redacted(self) -> None:
        # session_name typically embeds the run PID (e.g. "bmad-12345"),
        # so it varies across runs and must be redacted.
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = TmuxSessionSpawned(
                timestamp="2026-01-01T00:00:00Z", run_id="r",
                session_name="bmad-12345", story_key="s1", pid=12345,
                pane_geometry="80x24",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        self.assertEqual(rec.entries[0].payload["session_name"], "<redacted>")

    def test_four_letter_placeholder_in_payload_preserved(self) -> None:
        # REQ-13 last clause: any unresolved four-letter placeholder
        # tokens appearing in payloads are preserved verbatim. We use
        # a placeholder-shaped string in a string-typed payload field
        # (story_key) to verify it survives redaction. The token
        # `XXXX` is an exemplar — any 4-letter run of uppercase is
        # treated by the project's convention as an unresolved marker
        # in templates.
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z", run_id="r",
                epic="e", story_key="XXXX", agent="a", model="m", complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                emitter.emit(event)
        # The 4-letter placeholder must survive verbatim.
        self.assertEqual(rec.entries[0].payload["story_key"], "XXXX")
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.EventRedactionTests -v`
Expected: FAIL — `pid` is still the raw int 12345.

- [ ] **Step 3: Implement the redaction set**

In `tests/golden_trace_helpers.py`, add module-level constants:

```python
_REDACTED_SENTINEL = "<redacted>"
_REDACTED_EVENT_FIELDS: frozenset[str] = frozenset({
    "pid",                # TmuxSessionSpawned.pid
    "session_name",       # TmuxSessionSpawned/Completed/Crashed — typically embeds pid (e.g. "bmad-12345")
    "final_session",      # StoryFailed.final_session — same shape as session_name
    "lock_token",         # future events; defensive listing
    "heartbeat_counter",  # future events; defensive listing
})
```

Add a module-level helper:

```python
def _redact_event_payload(payload: dict[str, object]) -> dict[str, object]:
    """Apply REQ-13 redaction to an event payload.

    Replaces non-deterministic fields with their sentinel:
    - ``timestamp`` → ``"<ts>"`` (REQ-03 narrower contract)
    - ``pid``/``lock_token``/``heartbeat_counter`` → ``"<redacted>"`` (REQ-13)

    Four-letter placeholder tokens are intentionally NOT substituted —
    REQ-13's last clause requires them to flow through verbatim.
    """
    out = dict(payload)
    if "timestamp" in out:
        out["timestamp"] = _TS_SENTINEL
    for key in _REDACTED_EVENT_FIELDS:
        if key in out:
            out[key] = _REDACTED_SENTINEL
    return out
```

Update the `wrapper` in `_install_emit_hook`:

```python
        def wrapper(emitter_self: TelemetryEmitter, event: object) -> None:
            result = orig(emitter_self, event)
            raw_payload: dict[str, object] = dict(event.to_dict())  # type: ignore[attr-defined]
            payload = _redact_event_payload(raw_payload)
            recorder._record("event", type(event).__name__, payload)
            return result
```

Remove the inline `if "timestamp" in payload:` block from Task 6 — it's now handled by `_redact_event_payload`.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.EventRedactionTests tests.test_golden_trace_helpers.EventTimestampRedactionTests -v`
Expected: PASS for all cases including the Task 6 cases (the redaction helper subsumes the inline timestamp logic).

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): redact PID and lock-token fields in event payloads"
```

---

## Task 8: Hook `commands.state.write_atomic_text` — record `state` entries (REQ-04, half)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
import hashlib

from story_automator.commands import state as _state_module


class StateWriteHookTests(unittest.TestCase):
    def test_state_write_records_path_and_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "state.json"
            body = '{"k": 1}'
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(target, body)
        self.assertEqual(len(rec.entries), 1)
        entry = rec.entries[0]
        self.assertEqual(entry.channel, "state")
        self.assertEqual(entry.kind, "mutation")
        # Path is repo-relative POSIX.
        self.assertEqual(entry.payload["path"], "state.json")
        # sha256 of the post-write bytes.
        expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.assertEqual(entry.payload["sha256"], expected)

    def test_state_write_passes_through(self) -> None:
        # NFR Safety: the file actually gets written.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "doc.md"
            body = "# heading\n"
            with GoldenTraceRecorder(repo_root=root):
                _state_module.write_atomic_text(target, body)
            self.assertEqual(target.read_text(encoding="utf-8"), body)

    def test_state_hook_removed_on_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / "a.txt"
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(target, "x")
            _state_module.write_atomic_text(target, "y")
        self.assertEqual(len(rec.entries), 1)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.StateWriteHookTests -v`
Expected: FAIL — state-write hook not installed yet.

- [ ] **Step 3: Install the state-write hook**

Add to top-of-file imports in `tests/golden_trace_helpers.py`:

```python
import hashlib
import warnings
from story_automator.commands import state as _state_module
```

Update `GoldenTraceRecorder.__enter__` to also save the original and install the hook (Task 10 will supersede this once again to add the claude_p hook + module-global active-recorder guard):

```python
    def __enter__(self) -> GoldenTraceRecorder:
        if self._installed:
            raise RuntimeError("GoldenTraceRecorder is not reentrant")
        self._orig_emit = TelemetryEmitter.emit
        self._orig_state_write = _state_module.write_atomic_text
        self._install_emit_hook()
        self._install_state_hook()
        self._installed = True
        return self
```

Update `__exit__` to restore both. Use the collect-errors-into-list pattern from the start so adding the claude_p restoration in Task 10 is a one-line extension:

```python
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        errors: list[BaseException] = []
        for restore in (
            lambda: setattr(TelemetryEmitter, "emit", self._orig_emit),
            lambda: setattr(_state_module, "write_atomic_text", self._orig_state_write),
        ):
            try:
                restore()
            except BaseException as restore_err:
                errors.append(restore_err)
        self._installed = False
        if errors:
            raise BaseExceptionGroup(
                "GoldenTraceRecorder failed to restore one or more hooks",
                errors,
            )
        return None
```

Add the state-hook installer:

```python
    def _install_state_hook(self) -> None:
        orig = self._orig_state_write
        recorder = self

        def wrapper(path: Path, data: str, *, encoding: str = "utf-8") -> None:
            # Pass-through FIRST so that sha256-of-post-write reflects
            # the actually-written bytes (REQ-04: "sha256 of the
            # post-write bytes"). Read back from disk rather than
            # hashing `data` so encoding/line-ending transforms by
            # write_atomic_text never produce a sha-vs-bytes mismatch.
            result = orig(path, data, encoding=encoding)
            try:
                rel = _to_repo_relative_posix(Path(path), repo_root=recorder._repo_root)
                sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                recorder._record("state", "mutation", {"path": rel, "sha256": sha})
            except Exception as exc:
                # Surface recording failures via warnings.warn so test
                # debugging is not silent. The recorded operation still
                # completes — passive-observer semantics (NFR Safety).
                warnings.warn(
                    f"GoldenTraceRecorder: state-hook recording failed for "
                    f"{path!r}: {exc!r}",
                    stacklevel=2,
                )
            return result

        _state_module.write_atomic_text = wrapper  # type: ignore[assignment]
```

Note: the hook records *after* the underlying write succeeds, so a failed write does not appear in the trace (which matches the spec — the trace records observable behavior, and a raised exception is itself observable but is not a state mutation).

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.StateWriteHookTests -v`
Expected: PASS for all 3 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): hook state.write_atomic_text for mutation recording"
```

---

## Task 9: Exclude heartbeat-driven lock-file writes from the trace (REQ-13)

**Rationale:** The M05 heartbeat thread (atomic_io.py line ~391) calls `write_atomic_text` on a `.run.lock` file every interval. If we record those calls — even with `sha256` redacted — the *number* of recorded entries depends on the recording-window duration, defeating determinism. The cleanest fix is to **skip** lock-file writes entirely at the recorder level: the M05 fixture in M10c will be byte-identical across runs because lock noise is filtered out, and the main observable mutation (the protected file write) still gets recorded. We enumerate a closed set of lock-path patterns (`.run.lock`, `.state-build.lock`) explicitly rather than matching every `*.lock` suffix — this avoids false positives on user-named files that happen to end with `.lock`.

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class StateLockExclusionTests(unittest.TestCase):
    def test_run_lock_write_not_recorded(self) -> None:
        # Heartbeat refreshes .run.lock continuously; recording them
        # would make the M10c m05_atomic_write_smoke fixture entry-count
        # non-deterministic. Skip entirely.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(root / ".run.lock", '{"pid":1}')
        self.assertEqual(rec.entries, [])

    def test_state_build_lock_write_not_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "output").mkdir()
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(
                    root / "output" / ".state-build.lock", "ignored"
                )
        self.assertEqual(rec.entries, [])

    def test_non_lock_path_still_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            body = '{"k": 1}'
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(root / "config.json", body)
        self.assertEqual(len(rec.entries), 1)
        # User-named files that happen to contain ".lock" in their NAME
        # (but are not enumerated heartbeat paths) must still record.
        # Covered by the file `config.json` here — distinct from the
        # filter.

    def test_user_named_dot_lock_file_still_recorded(self) -> None:
        # A user-named `mystory.lock` is NOT a heartbeat-driven path —
        # only the closed-set patterns (`.run.lock`, `.state-build.lock`)
        # are excluded. This guards against over-exclusion.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with GoldenTraceRecorder(repo_root=root) as rec:
                _state_module.write_atomic_text(root / "mystory.lock", "user data")
        self.assertEqual(len(rec.entries), 1)
        self.assertEqual(rec.entries[0].payload["path"], "mystory.lock")
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.StateLockExclusionTests -v`
Expected: FAIL — heartbeat lock writes currently produce entries.

- [ ] **Step 3: Implement the exclusion rule**

In `tests/golden_trace_helpers.py`, add a module-level helper:

```python
# Closed set of heartbeat-driven lock paths the recorder skips entirely.
# Match by basename (the last path segment) to be path-prefix agnostic.
_HEARTBEAT_LOCK_BASENAMES: frozenset[str] = frozenset({
    ".run.lock",
    ".state-build.lock",
})


def _is_heartbeat_lock_path(rel_posix_path: str) -> bool:
    """Return True if the path is a known heartbeat-driven lock file.

    The heartbeat thread (M05) refreshes these continuously, so the
    *count* of recorded mutations would be non-deterministic. We skip
    them entirely. User-named files that happen to end in `.lock` are
    NOT skipped — only the enumerated heartbeat paths are.
    """
    basename = rel_posix_path.rsplit("/", 1)[-1]
    return basename in _HEARTBEAT_LOCK_BASENAMES
```

Replace the wrapper body in `_install_state_hook` with:

```python
        def wrapper(path: Path, data: str, *, encoding: str = "utf-8") -> None:
            result = orig(path, data, encoding=encoding)
            try:
                rel = _to_repo_relative_posix(Path(path), repo_root=recorder._repo_root)
                if _is_heartbeat_lock_path(rel):
                    # Skip — see _is_heartbeat_lock_path docstring.
                    return result
                # REQ-04: sha256 of the *post-write* bytes. We read back
                # from disk rather than hashing `data` to defend against
                # encoding transforms, line-ending normalization, or any
                # future write_atomic_text contract change.
                sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                recorder._record("state", "mutation", {"path": rel, "sha256": sha})
            except Exception as exc:
                warnings.warn(
                    f"GoldenTraceRecorder: state-hook recording failed for "
                    f"{path!r}: {exc!r}",
                    stacklevel=2,
                )
            return result
```

Add `import warnings` to the top-of-file imports.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.StateLockExclusionTests tests.test_golden_trace_helpers.StateWriteHookTests -v`
Expected: PASS for all cases. The Task 8 sha256 assertion in `test_state_write_records_path_and_sha256` keeps holding because we now read the same bytes back from disk that we just wrote.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): exclude heartbeat-driven lock writes from trace"
```

---

## Task 10: Hook `notify_claude_p` — record `claude_p` entries (REQ-05, half)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class ClaudePHookTests(unittest.TestCase):
    def test_notify_claude_p_records_invoke_entry(self) -> None:
        import tests.golden_trace_helpers as gh
        with tempfile.TemporaryDirectory() as tmp:
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                gh.notify_claude_p(["claude", "-p", "Run story s1"])
        self.assertEqual(len(rec.entries), 1)
        entry = rec.entries[0]
        self.assertEqual(entry.channel, "claude_p")
        self.assertEqual(entry.kind, "invoke")
        self.assertEqual(entry.payload["argv"], ["claude", "-p", "Run story s1"])

    def test_notify_claude_p_outside_recorder_is_noop(self) -> None:
        # Module attribute access must reach the no-op when no recorder
        # is active — even after a recorder has run and exited.
        import tests.golden_trace_helpers as gh
        with tempfile.TemporaryDirectory() as tmp:
            with GoldenTraceRecorder(repo_root=Path(tmp)):
                pass
        # Now outside the with block.
        self.assertIsNone(gh.notify_claude_p(["claude", "-p", "x"]))

    def test_claude_p_hook_removed_on_exit(self) -> None:
        import tests.golden_trace_helpers as gh
        with tempfile.TemporaryDirectory() as tmp:
            with GoldenTraceRecorder(repo_root=Path(tmp)) as rec:
                gh.notify_claude_p(["claude", "-p", "a"])
            gh.notify_claude_p(["claude", "-p", "b"])  # not recorded
        self.assertEqual(len(rec.entries), 1)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.ClaudePHookTests -v`
Expected: FAIL — `notify_claude_p` is still the no-op.

- [ ] **Step 3: Install and restore the claude_p hook**

In `tests/golden_trace_helpers.py`, modify the existing `notify_claude_p` to remain a thin module-level function — and have the recorder swap an internal slot it reads on every call. This indirection is what makes `from tests.golden_trace_helpers import notify_claude_p` work transparently for callers: the function body always re-reads the module-global slot, so the swap is visible regardless of how the symbol was imported.

Add `from collections.abc import Callable` to the top-of-file imports (project convention prefers `collections.abc` over `typing` for ABCs in Python 3.11+; `typing.Callable` is deprecated for new code). Then add the slot and the function in a single edit:

```python
_CLAUDE_P_HOOK: Callable[[list[str]], None] | None = None


def notify_claude_p(argv: list[str]) -> None:
    """Hook surface for `claude -p` invocations (REQ-05).

    No-op when no recorder is active; the recorder swaps the
    module-global ``_CLAUDE_P_HOOK`` slot on ``__enter__``. Because
    this function body re-reads the slot on every call (not at import
    time), callers may use either ``from ... import notify_claude_p``
    or module-attribute access — both see the active recorder.
    """
    hook = _CLAUDE_P_HOOK
    if hook is not None:
        hook(argv)
    return None
```

Replace the Task 1 stub `notify_claude_p` with this version (one edit, no interim broken annotation).

Extend `GoldenTraceRecorder.__enter__`:

```python
    def __enter__(self) -> GoldenTraceRecorder:
        global _ACTIVE_RECORDER
        if self._installed:
            raise RuntimeError("GoldenTraceRecorder is not reentrant")
        if _ACTIVE_RECORDER is not None:
            # NFR Isolation: a second live recorder would capture the
            # first recorder's wrapper into its `_orig_*` slots and
            # leak nested recording on exit. Forbid module-globally.
            raise RuntimeError(
                "Another GoldenTraceRecorder is already active; nested "
                "recorders are not supported"
            )
        self._orig_emit = TelemetryEmitter.emit
        self._orig_state_write = _state_module.write_atomic_text
        self._orig_claude_p_hook = _CLAUDE_P_HOOK  # may be None on first use
        self._install_emit_hook()
        self._install_state_hook()
        self._install_claude_p_hook()
        _ACTIVE_RECORDER = self
        self._installed = True
        return self
```

And `__exit__`:

```python
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:
        global _CLAUDE_P_HOOK, _ACTIVE_RECORDER
        # Collect restoration failures rather than masking via nested
        # try/finally. REQ-14: every wrapper must be restored even if
        # one restoration raises; diagnostics survive via ExceptionGroup.
        errors: list[BaseException] = []
        for restore in (
            lambda: setattr(TelemetryEmitter, "emit", self._orig_emit),
            lambda: setattr(_state_module, "write_atomic_text", self._orig_state_write),
        ):
            try:
                restore()
            except BaseException as restore_err:
                errors.append(restore_err)
        try:
            _CLAUDE_P_HOOK = self._orig_claude_p_hook
        except BaseException as restore_err:  # pragma: no cover - defensive
            errors.append(restore_err)
        _ACTIVE_RECORDER = None
        self._installed = False
        if errors:
            raise BaseExceptionGroup(  # Py 3.11+
                "GoldenTraceRecorder failed to restore one or more hooks",
                errors,
            )
        return None
```

Add a module-level slot near `_CLAUDE_P_HOOK`:

```python
_ACTIVE_RECORDER: "GoldenTraceRecorder | None" = None
```

Add the installer:

```python
    def _install_claude_p_hook(self) -> None:
        global _CLAUDE_P_HOOK
        recorder = self

        def hook(argv: list[str]) -> None:
            # Argv normalization (path → repo-relative POSIX) lands in
            # Task 11 — for now, record argv verbatim.
            recorder._record("claude_p", "invoke", {"argv": list(argv)})

        _CLAUDE_P_HOOK = hook
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.ClaudePHookTests -v`
Expected: PASS for all 3 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): hook notify_claude_p for invoke recording"
```

---

## Task 11: Normalize claude_p argv paths + preserve four-letter placeholders (REQ-05, second half)

**Files:**
- Modify: `tests/golden_trace_helpers.py`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class ClaudePArgvNormalizationTests(unittest.TestCase):
    def test_absolute_repo_path_normalized_to_relative_posix(self) -> None:
        import tests.golden_trace_helpers as gh
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "stories").mkdir()
            story = root / "stories" / "s1.md"
            story.write_text("body", encoding="utf-8")
            with GoldenTraceRecorder(repo_root=root) as rec:
                gh.notify_claude_p(["claude", "-p", str(story)])
        self.assertEqual(rec.entries[0].payload["argv"], ["claude", "-p", "stories/s1.md"])

    def test_four_letter_placeholder_token_preserved(self) -> None:
        # REQ-05 last clause: any unresolved four-letter placeholder
        # tokens must flow through verbatim. EPIC and STRY are exemplars
        # used by the project templates.
        import tests.golden_trace_helpers as gh
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with GoldenTraceRecorder(repo_root=root) as rec:
                gh.notify_claude_p(["claude", "-p", "Run EPIC STRY now"])
        self.assertEqual(
            rec.entries[0].payload["argv"],
            ["claude", "-p", "Run EPIC STRY now"],
        )

    def test_non_path_token_passes_through_unchanged(self) -> None:
        # Tokens that aren't absolute filesystem paths must not be
        # mangled by the normalizer — strings like "--flag", "value",
        # "key=value" stay intact.
        import tests.golden_trace_helpers as gh
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with GoldenTraceRecorder(repo_root=root) as rec:
                gh.notify_claude_p(["claude", "-p", "--model=opus", "key=value"])
        self.assertEqual(
            rec.entries[0].payload["argv"],
            ["claude", "-p", "--model=opus", "key=value"],
        )
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.ClaudePArgvNormalizationTests -v`
Expected: FAIL for `test_absolute_repo_path_normalized_to_relative_posix` — the absolute path stays absolute.

- [ ] **Step 3: Implement argv normalization**

In `tests/golden_trace_helpers.py`, add a helper:

```python
def _normalize_argv(argv: list[str], *, repo_root: Path) -> list[str]:
    """Normalize absolute paths in ``argv`` to repo-relative POSIX (REQ-05).

    Tokens that don't represent absolute filesystem paths under the repo
    are returned unchanged. Four-letter placeholder tokens are
    intentionally not detected here — they're just non-path strings,
    so the early ``is_absolute`` guard already lets them flow through.

    Known limitation: tokens of the form ``--key=/abs/path`` are not
    split on ``=`` before path detection — ``is_absolute`` is False
    for the whole string, so the embedded absolute path stays
    absolute. Callers (M10c fixture authors) should prefer the
    ``--key /abs/path`` two-arg form for portable fixtures.
    """
    out: list[str] = []
    for token in argv:
        try:
            candidate = Path(token)
        except (TypeError, ValueError):
            out.append(token)
            continue
        if candidate.is_absolute():
            out.append(_to_repo_relative_posix(candidate, repo_root=repo_root))
        else:
            out.append(token)
    return out
```

Update the `hook` inside `_install_claude_p_hook`:

```python
        def hook(argv: list[str]) -> None:
            normalized = _normalize_argv(list(argv), repo_root=recorder._repo_root)
            recorder._record("claude_p", "invoke", {"argv": normalized})
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.ClaudePArgvNormalizationTests tests.test_golden_trace_helpers.ClaudePHookTests -v`
Expected: PASS for all cases (Task 10 cases use string args like `"claude"` and `"-p"` that are not absolute paths, so they remain unchanged).

- [ ] **Step 5: Commit**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10b): normalize claude_p argv paths, preserve placeholders"
```

---

## Task 12: Hook restoration on exception (REQ-14)

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class RecorderRestorationOnExceptionTests(unittest.TestCase):
    def setUp(self) -> None:
        # Snapshot the pristine hook targets before each test so a prior
        # test that left a wrapper behind doesn't pollute our `IS` checks.
        # If any of these are NOT the originals, fail loudly — that's a
        # symptom of recorder-leak from another test.
        self._baseline_emit = TelemetryEmitter.emit
        self._baseline_state_write = _state_module.write_atomic_text

    def tearDown(self) -> None:
        # If a test left wrappers behind (e.g. an exception bypassed
        # __exit__), restore baselines so the next test starts clean.
        TelemetryEmitter.emit = self._baseline_emit  # type: ignore[method-assign]
        _state_module.write_atomic_text = self._baseline_state_write  # type: ignore[assignment]

    def test_emit_restored_when_block_raises(self) -> None:
        import tests.golden_trace_helpers as gh
        orig_emit = TelemetryEmitter.emit
        orig_state_write = _state_module.write_atomic_text
        orig_hook = gh._CLAUDE_P_HOOK  # type: ignore[attr-defined]

        class _MyError(RuntimeError):
            pass

        with self.assertRaises(_MyError):
            with GoldenTraceRecorder(repo_root=Path(".")):
                raise _MyError("synthetic")

        # All three hooks must be restored to their pre-enter state.
        self.assertIs(TelemetryEmitter.emit, orig_emit)
        self.assertIs(_state_module.write_atomic_text, orig_state_write)
        self.assertIs(gh._CLAUDE_P_HOOK, orig_hook)  # type: ignore[attr-defined]

    def test_two_sequential_with_blocks_yield_independent_traces(self) -> None:
        # NFR Isolation: no entries from the first block leak into the second.
        with tempfile.TemporaryDirectory() as tmp:
            emitter = TelemetryEmitter(Path(tmp) / "events.jsonl")
            event = StoryStarted(
                timestamp="2026-01-01T00:00:00Z", run_id="r",
                epic="e", story_key="s", agent="a", model="m", complexity="c",
            )
            with GoldenTraceRecorder(repo_root=Path(tmp)) as r1:
                emitter.emit(event)
            with GoldenTraceRecorder(repo_root=Path(tmp)) as r2:
                emitter.emit(event)
                emitter.emit(event)
        self.assertEqual(len(r1.entries), 1)
        self.assertEqual(len(r2.entries), 2)
        # Both traces start at seq=0 — no leakage.
        self.assertEqual(r1.entries[0].seq, 0)
        self.assertEqual(r2.entries[0].seq, 0)

    def test_nested_recorders_rejected(self) -> None:
        # Re-entering the same recorder must raise (the wrappers would
        # otherwise nest, double-recording every observation).
        with tempfile.TemporaryDirectory() as tmp:
            rec = GoldenTraceRecorder(repo_root=Path(tmp))
            with rec:
                with self.assertRaises(RuntimeError):
                    with rec:
                        pass

    def test_second_distinct_recorder_rejected_while_first_active(self) -> None:
        # A SECOND, distinct recorder would capture the first's wrapper
        # into its _orig_* slots and leak nested recording on exit.
        # Module-global guard blocks this.
        with tempfile.TemporaryDirectory() as tmp:
            with GoldenTraceRecorder(repo_root=Path(tmp)):
                with self.assertRaises(RuntimeError):
                    with GoldenTraceRecorder(repo_root=Path(tmp)):
                        pass
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderRestorationOnExceptionTests -v`
Expected: PASS — the try/finally chains established in Tasks 8 and 10 already restore the hooks on exception, and the reentrancy guard from Task 5 still holds.

If any test fails: the exception path is missing a `try/finally` somewhere — fix the recorder until all 3 cases pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10b): lock hook restoration on exception"
```

---

## Task 13: Import-safety (REQ-14, first clause)

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class ImportSafetyTests(unittest.TestCase):
    def test_import_does_not_install_hooks(self) -> None:
        # Fresh subprocess so we observe pristine module state — using
        # importlib.reload in-process is unsafe (the reload could race
        # with a concurrently-active recorder in another test thread).
        import subprocess, sys
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, 'skills/bmad-story-automator/src');\n"
                "from story_automator.core.telemetry_emitter import TelemetryEmitter\n"
                "from story_automator.commands import state\n"
                "orig_emit = TelemetryEmitter.emit\n"
                "orig_write = state.write_atomic_text\n"
                "import tests.golden_trace_helpers as gh\n"
                "assert TelemetryEmitter.emit is orig_emit, 'emit was patched at import'\n"
                "assert state.write_atomic_text is orig_write, 'write_atomic_text patched at import'\n"
                "assert gh._CLAUDE_P_HOOK is None, 'claude_p hook installed at import'\n"
                "print('ok')",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("ok", result.stdout)

    def test_module_level_claude_p_hook_is_none(self) -> None:
        import tests.golden_trace_helpers as gh
        # Outside any with-block, the hook slot is None — no recording
        # plumbing is active until __enter__ runs.
        self.assertIsNone(gh._CLAUDE_P_HOOK)  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.ImportSafetyTests -v`
Expected: PASS — by construction, M10b installs nothing at import time.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10b): lock import-time safety contract"
```

---

## Task 14: End-to-end determinism — record + serialize is byte-stable

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class DeterminismE2ETests(unittest.TestCase):
    """NFR primary criterion: a given recorded session must serialize
    byte-identically across runs."""

    def _record_five_events(self, tmp: Path) -> bytes:
        emitter = TelemetryEmitter(tmp / "events.jsonl")
        # Real timestamps differ run-to-run; redaction must collapse them.
        events = [
            StoryStarted(
                timestamp="2026-06-15T01:02:03Z", run_id="r",
                epic="e", story_key=f"s{i}", agent="a", model="m", complexity="c",
            )
            for i in range(5)
        ]
        with GoldenTraceRecorder(repo_root=tmp) as rec:
            for ev in events:
                emitter.emit(ev)
        return serialize_trace(rec.entries).encode("utf-8")

    def test_two_recordings_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp1:
            first = self._record_five_events(Path(tmp1).resolve())
        with tempfile.TemporaryDirectory() as tmp2:
            second = self._record_five_events(Path(tmp2).resolve())
        self.assertEqual(first, second)

    def test_real_iso_timestamp_collapsed_to_ts(self) -> None:
        # If real production code injected an iso_now() timestamp, the
        # recorder must still produce a deterministic trace because the
        # redaction layer replaces it before recording.
        from story_automator.core.common import iso_now
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            with GoldenTraceRecorder(repo_root=root) as rec:
                emitter.emit(StoryStarted(
                    timestamp=iso_now(), run_id="r",
                    epic="e", story_key="s", agent="a", model="m", complexity="c",
                ))
        self.assertEqual(rec.entries[0].payload["timestamp"], "<ts>")
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.DeterminismE2ETests -v`
Expected: PASS — the redaction layer from Tasks 6/7 plus the serialization sort_keys from M10a already guarantee byte-identical output.

If either case fails, the redaction set is incomplete — extend `_REDACTED_EVENT_FIELDS` or `_redact_event_payload` until the test passes.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10b): lock end-to-end determinism contract"
```

---

## Task 15: Full suite green + ruff + mypy --strict (REQ-15)

**Files:**
- Modify: `tests/golden_trace_helpers.py` (only if tooling complains)

- [ ] **Step 1: Run the full M10 test set**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers -v
```

Expected: every `TestCase` from M10a (Tasks 1–12) and M10b (Tasks 1–14) passes. Count: ~50 cases. If anything fails, fix the underlying code, do not weaken the test.

- [ ] **Step 2: Run the existing project test suite (no regressions)**

Run:

```bash
npm run test:python
```

Expected: PASS. M10b modifies only `tests/golden_trace_helpers.py` and `tests/test_golden_trace_helpers.py`; no shipped module should regress.

- [ ] **Step 3: Run ruff**

Run:

```bash
python -m ruff check tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
python -m ruff format --check tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
```

Expected: zero findings. If `ruff format --check` reports drift, run `python -m ruff format tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py` and re-run the check.

- [ ] **Step 4: Run mypy --strict**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m mypy --strict tests/golden_trace_helpers.py
```

Expected: `Success: no issues found in 1 source file`.

Known likely findings + fixes:

| mypy finding | fix |
|---|---|
| `Cannot assign to a method` on `TelemetryEmitter.emit = wrapper` | The `# type: ignore[method-assign]` comment from Task 5 covers this — verify the comment was preserved. |
| `Incompatible types in assignment` on `_state_module.write_atomic_text = wrapper` | `# type: ignore[assignment]` already in Task 8 — verify preserved. |
| `Returning Any from function declared to return ...` on `event.to_dict()` | The Task 5 wrapper already accepts `event: object` and uses a `# type: ignore[attr-defined]` for `to_dict`. Verify the comment is intact. |
| Anything in `_normalize_argv` | Return type is `list[str]`; ensure each `out.append(...)` is on a string-typed branch. |
| `Need type annotation for "_CLAUDE_P_HOOK"` | The slot is annotated `Callable[[list[str]], None] | None` per Task 10 — verify the annotation is on the same line as the assignment. |

Apply minimal `# type: ignore[…]` comments only where the underlying issue is a known stdlib-typing limitation (e.g., method-assignment for monkey-patching). Do NOT add blanket ignores.

If `mypy` is not installed in this environment, install it as a dev tool but do NOT add it to `pyproject.toml`:

```bash
python -m pip install --quiet mypy
```

- [ ] **Step 5: Commit (only if fixes were applied)**

```bash
git add tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "fix(m10b): satisfy ruff + mypy --strict"
```

If no fixes were needed, skip the commit.

---

## Task 16: Cross-platform smoke + import-no-side-effects verification

**Files:**
- (no changes expected)

- [ ] **Step 1: Verify import has no side effects**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -c "import tests.golden_trace_helpers as g; print('ok'); print('hook=', g._CLAUDE_P_HOOK)"
```

Expected: `ok` followed by `hook= None`. No telemetry events, no state mutations, no claude_p invocations should occur during import.

- [ ] **Step 2: Re-run the full unittest sweep one final time**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v 2>&1 | tail -50
```

Expected: `OK` and no failures. Confirm that the M10a count from earlier plus the new M10b count both appear.

- [ ] **Step 3: Performance smoke (NFR)**

Run a quick timing check to confirm the recorder adds no more than ~50 µs per intercepted operation and the M02 five-event scenario completes in well under 100 ms:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -c "
import tempfile, time
from pathlib import Path
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_events import StoryStarted
from tests.golden_trace_helpers import GoldenTraceRecorder, serialize_trace
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp).resolve()
    emitter = TelemetryEmitter(root / 'events.jsonl')
    events = [StoryStarted(timestamp='2026-01-01T00:00:00Z', run_id='r',
                            epic='e', story_key=f's{i}', agent='a', model='m', complexity='c')
              for i in range(5)]
    t0 = time.perf_counter()
    with GoldenTraceRecorder(repo_root=root) as rec:
        for ev in events:
            emitter.emit(ev)
    out = serialize_trace(rec.entries)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    print(f'elapsed: {elapsed_ms:.2f} ms, entries: {len(rec.entries)}, bytes: {len(out)}')
    # NFR Performance is advisory; a loaded CI box can spike past 100 ms.
    # Surface the timing as a print so reviewers can eyeball regressions
    # rather than gating the build on wall-clock noise.
"
```

Expected: `elapsed: <some-ms> ms, entries: 5, bytes: <some-int>`. Eyeball the elapsed value — under 100 ms is the NFR target, well under 50 ms on a dev box. If you see >500 ms, investigate (likely the heartbeat thread or per-emit filelock cost).

- [ ] **Step 4: No final commit required**

M10b is complete. The handoff to M10c (golden fixtures + record-then-compare tests) needs only the public surface (`GoldenTraceRecorder`, `notify_claude_p`, the existing M10a helpers). No new branches needed.

---

## Self-review checklist (run before declaring done)

- [ ] **Spec coverage**
  - REQ-01 (`GoldenTraceRecorder` context manager): Tasks 1, 5, 8, 10
  - REQ-03 (emit interception + `<ts>` redaction): Tasks 5, 6
  - REQ-04 (state-write interception, path + sha256): Tasks 8, 9
  - REQ-05 (claude_p interception, argv + placeholders): Tasks 10, 11
  - REQ-06 (single `threading.Lock`, contiguous seq under concurrency): Task 2
  - REQ-13 (PID/lock-token/heartbeat redaction; placeholders untouched): Tasks 7, 9, 11
  - REQ-14 (import-safe; restore originals on exception): Tasks 12, 13
  - NFR Isolation (two sequential `with` blocks independent): Task 12
  - NFR Determinism (byte-identical serialization): Task 14
  - NFR Safety (passive observer semantics): Tasks 5, 8 (pass-through tests)
  - NFR Performance (~50 µs/op, <100 ms for 5 events): Task 16
- [ ] **Placeholders:** None. Every code block is concrete.
- [ ] **Type consistency:** `GoldenTraceRecorder`, `notify_claude_p`, `_CLAUDE_P_HOOK`, `_record`, `_to_repo_relative_posix`, `_find_repo_root`, `_redact_event_payload`, `_is_lock_path`, `_normalize_argv`, `_TS_SENTINEL`, `_REDACTED_SENTINEL`, `_REDACTED_EVENT_FIELDS`, `_LOCK_PATH_SUFFIXES` names match across all tasks. `__all__` is updated in Task 1 only; later tasks do not re-touch `__all__`.
- [ ] **Scope guard:** No task creates a golden fixture file (`tests/golden/*.json`); no task wires `notify_claude_p` into any `src/` callsite; no task modifies the M10a data-layer code. Those are M10c and beyond.
