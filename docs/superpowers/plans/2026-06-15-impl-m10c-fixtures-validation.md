# M10c — Golden-Trace Fixtures + Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the three required golden fixtures (`m01_event_basics.json`, `m02_emitter_smoke.json`, `m05_atomic_write_smoke.json`), the end-to-end REQ-12 validation tests that recreate each fixture against a live `GoldenTraceRecorder` run, the M05 ten-consecutive-runs byte-identical determinism gate, and the placeholder-leak quality gate. M10a (pure data layer) and M10b (recorder + hooks) have shipped — do not modify either.

**Architecture:** All three fixtures live in `tests/golden/` (a new directory). Each fixture is the canonical-JSON serialization of a hand-curated recording produced by a small builder helper inside `tests/test_golden_trace_helpers.py`. The builders are deterministic by construction: literal event field values, deterministic write payloads, `threading.Event` chains to serialize concurrent writes in a fixed completion order. Fixture generation uses an explicit opt-in (`BMA_GOLDEN_REGEN=1` env var) — running the test suite normally always compares-against-disk, never overwrites. REQ-12 sub-cases (b)/(c)/(d) are already covered end-to-end by the M10a/M10b test classes (`CompareTracesFieldMismatchTests`, `CompareTracesLengthMismatchTests`, `LoadGoldenRejectionTests`); M10c adds (a) and (e), plus one real-recorder end-to-end regression-localization case that strengthens (b).

**Tech Stack:** Python 3.11+ stdlib only (`threading`, `tempfile`, `pathlib`, `subprocess`, `os`, `re`). No third-party deps. `ruff` + `mypy --strict` clean. `unittest.TestCase` per project convention. Imports `tests.golden_trace_helpers` (M10a/b surface) and `story_automator.core.{telemetry_emitter,telemetry_events,atomic_io}` plus `story_automator.commands.state`.

**Imports convention:** New imports go in the top-of-file import block of `tests/test_golden_trace_helpers.py` in the existing grouped order (stdlib → `story_automator.*` → `tests.golden_trace_helpers`). Do not introduce a second import block lower in the file (ruff E402). Where a snippet below shows `import X` inline with the test class, the real edit moves that import to the top.

---

## Scope boundary (anti-scope-creep)

**In scope for M10c (this plan):**
- REQ-11: `tests/golden/m01_event_basics.json`, `tests/golden/m02_emitter_smoke.json`, `tests/golden/m05_atomic_write_smoke.json` checked into the repo.
- REQ-12 sub-case (a): record-then-compare a trace against itself yields `ok=True`.
- REQ-12 sub-case (e): each of the three shipped fixtures parses via `load_golden` and matches a freshly recorded run.
- REQ-12 cross-check (b) at end-to-end altitude: a real-recorder run with one injected payload divergence is detected at the specific `seq`.
- Quality gate: M05 fixture passes ten consecutive runs with byte-identical serialized output.
- Quality gate: no unresolved four-letter placeholder tokens leak into `tests/golden_trace_helpers.py`.
- Quality gate: `python -c "import tests.golden_trace_helpers"` triggers no telemetry events, no state mutations, no `claude_p` invocations (subprocess-based verification — strengthens M10b's in-process check).

**Out of scope for M10c (deferred or already shipped):**
- M10a: pure data types, `serialize_trace`, `load_golden`, `compare_traces` — shipped.
- M10b: `GoldenTraceRecorder`, interception hooks, redaction layer, `notify_claude_p` — shipped.
- REQ-12 sub-cases (b)/(c)/(d) at unit-level — already covered by `CompareTracesFieldMismatchTests`, `CompareTracesLengthMismatchTests`, `LoadGoldenRejectionTests` (M10a). M10c adds an end-to-end (b) variant for the recorder pipeline.
- Wiring `notify_claude_p` into real `claude -p` callsites (future milestone).
- Any change to `skills/bmad-story-automator/src/` (M10 is pure testing infrastructure).
- Cross-OS path normalization beyond what `_to_repo_relative_posix` already provides.

If a later task in this plan looks like it's drifting into helper refactoring or wiring into `src/` — stop, that's out of M10c.

---

## File structure

**Create:**
- `tests/golden/` (directory) — holds the three shipped fixtures.
- `tests/golden/m01_event_basics.json` — one emitted `StoryStarted` event captured by the recorder.
- `tests/golden/m02_emitter_smoke.json` — five emitted `StoryStarted` events captured.
- `tests/golden/m05_atomic_write_smoke.json` — three concurrent `state.write_atomic_text` writes under composite-identity lock + heartbeat thread, serialized via `threading.Event` chain.

**Modify:**
- `tests/test_golden_trace_helpers.py` — append fixture-builder helpers, REQ-12 cases, ten-run determinism test, placeholder-leak regex, subprocess import-cleanliness check.

**Do not modify:**
- `tests/golden_trace_helpers.py` (M10a/b surface is frozen for M10c).
- Any file under `skills/bmad-story-automator/src/`.
- `pyproject.toml`.
- Anything else.

---

## Fixture-builder contract (locked here so later tasks use the same identifiers)

```python
# tests/test_golden_trace_helpers.py — added in M10c
_GOLDEN_DIR = Path(__file__).parent / "golden"
_REGEN_ENV = "BMA_GOLDEN_REGEN"

def _build_m01_recording(root: Path) -> list[TraceEntry]: ...
def _build_m02_recording(root: Path) -> list[TraceEntry]: ...
def _build_m05_recording(root: Path) -> list[TraceEntry]: ...

def _validate_or_regen(fixture_name: str, builder) -> None:
    """If BMA_GOLDEN_REGEN=1, write the fresh recording; otherwise
    load_golden(fixture) and compare_traces(fresh, golden).ok is asserted.
    """
```

All three builders take a `root: Path` (the test's `tempfile.TemporaryDirectory()`) and return the recorder's `entries` list. `_validate_or_regen` is the single point that branches on the env var — keeps regeneration explicit and auditable.

---

## Task 1: Create `tests/golden/` directory + structural test

**Files:**
- Create: `tests/golden/.gitkeep`
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class GoldenDirectoryStructureTests(unittest.TestCase):
    def test_golden_directory_exists_under_tests(self) -> None:
        golden_dir = Path(__file__).parent / "golden"
        self.assertTrue(
            golden_dir.is_dir(),
            f"tests/golden/ must exist; M10c ships fixtures here",
        )

    def test_golden_directory_is_committed(self) -> None:
        # An empty .gitkeep is committed so the directory survives a fresh
        # clone even before any fixture lands. Either .gitkeep or at least
        # one fixture must be present.
        golden_dir = Path(__file__).parent / "golden"
        contents = list(golden_dir.iterdir())
        self.assertTrue(
            contents,
            f"tests/golden/ must contain at least .gitkeep or a fixture",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.GoldenDirectoryStructureTests -v`
Expected: FAIL — `tests/golden/` does not exist yet.

- [ ] **Step 3: Create the directory + .gitkeep**

```bash
mkdir -p tests/golden
touch tests/golden/.gitkeep
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.GoldenDirectoryStructureTests -v`
Expected: PASS for both cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden/.gitkeep tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10c): create tests/golden/ fixture directory"
```

---

## Task 2: Add fixture-path + validate-or-regen helpers to the test module

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class FixtureHelperContractTests(unittest.TestCase):
    def test_golden_dir_constant_points_to_tests_golden(self) -> None:
        from tests.test_golden_trace_helpers import _GOLDEN_DIR  # type: ignore[attr-defined]
        self.assertEqual(_GOLDEN_DIR, Path(__file__).parent / "golden")

    def test_regen_env_var_constant(self) -> None:
        from tests.test_golden_trace_helpers import _REGEN_ENV  # type: ignore[attr-defined]
        self.assertEqual(_REGEN_ENV, "BMA_GOLDEN_REGEN")

    def test_validate_or_regen_callable_present(self) -> None:
        from tests.test_golden_trace_helpers import _validate_or_regen  # type: ignore[attr-defined]
        self.assertTrue(callable(_validate_or_regen))
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.FixtureHelperContractTests -v`
Expected: FAIL — `_GOLDEN_DIR`, `_REGEN_ENV`, `_validate_or_regen` not defined.

- [ ] **Step 3: Implement the helpers**

In `tests/test_golden_trace_helpers.py`, add near the top-of-file imports (after the existing `from tests.golden_trace_helpers import ...` block):

```python
from collections.abc import Callable

from tests.golden_trace_helpers import (
    GoldenTraceRecorder,
    serialize_trace,
    load_golden,
    compare_traces,
)

_GOLDEN_DIR = Path(__file__).parent / "golden"
_REGEN_ENV = "BMA_GOLDEN_REGEN"


def _validate_or_regen(
    fixture_name: str,
    builder: Callable[[Path], list[TraceEntry]],
) -> None:
    """Validate a shipped fixture against a fresh recording.

    Normal mode: load_golden(<fixture>) and compare_traces(fresh, golden);
    fail with a diagnostic summary if not ok.

    Regen mode (BMA_GOLDEN_REGEN=1): build the recording in a tempdir,
    serialize it, and write to <fixture>. The caller's tempdir is used as
    repo_root inside the builder so absolute paths normalize to repo-
    relative POSIX in the recorded entries.
    """
    fixture_path = _GOLDEN_DIR / fixture_name
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        entries = builder(root)
        serialized = serialize_trace(entries)
    if os.environ.get(_REGEN_ENV) == "1":
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        fixture_path.write_text(serialized, encoding="utf-8")
        return
    if not fixture_path.exists():
        raise AssertionError(
            f"fixture {fixture_path} does not exist; run with "
            f"{_REGEN_ENV}=1 to generate it"
        )
    golden = load_golden(fixture_path)
    diff = compare_traces(entries, golden)
    if not diff.ok:
        raise AssertionError(
            f"{fixture_name} diverged from fresh recording:\n{diff.summary()}"
        )
```

Imports already exist for `tempfile`, `os`, `Path`, `TraceEntry`. Only `Callable` is new — add to the existing imports if not yet present. If `serialize_trace`, `load_golden`, `compare_traces` are not in the existing `tests.golden_trace_helpers` import block, merge them in.

- [ ] **Step 4: Run tests, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.FixtureHelperContractTests -v`
Expected: PASS for all 3 cases.

- [ ] **Step 5: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10c): add fixture-path and validate-or-regen helpers"
```

---

## Task 3: REQ-12 sub-case (a) — record-then-compare-against-itself yields ok=True

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class RecorderSelfComparisonTests(unittest.TestCase):
    """REQ-12(a): a recording compared against itself yields ok=True.

    Uses the live recorder to capture all three channels, then runs
    compare_traces(entries, entries) — the loopback acts as the simplest
    smoke test of the full record + diff pipeline.
    """

    def test_self_comparison_returns_ok_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            event = StoryStarted(
                timestamp="2026-06-15T00:00:00Z", run_id="r",
                epic="e", story_key="s", agent="a", model="m", complexity="c",
            )
            import tests.golden_trace_helpers as gh
            with GoldenTraceRecorder(repo_root=root) as rec:
                emitter.emit(event)
                _state_module.write_atomic_text(root / "doc.txt", "hello")
                gh.notify_claude_p(["claude", "-p", "Run story"])
            entries = rec.entries
        diff = compare_traces(entries, entries)
        self.assertTrue(diff.ok)
        self.assertEqual(diff.matched, len(entries))
        self.assertEqual(diff.mismatches, [])

    def test_self_comparison_after_serialize_round_trip(self) -> None:
        # Recording → serialize_trace → load_golden(in-tmpfile) → compare
        # against the original entries. Locks in the serialize/load
        # symmetry end-to-end with the recorder driving the input.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            with GoldenTraceRecorder(repo_root=root) as rec:
                emitter.emit(StoryStarted(
                    timestamp="2026-06-15T00:00:00Z", run_id="r",
                    epic="e", story_key="s", agent="a", model="m", complexity="c",
                ))
            entries = rec.entries
            fixture = Path(tmp) / "round_trip.json"
            fixture.write_text(serialize_trace(entries), encoding="utf-8")
            reloaded = load_golden(fixture)
        diff = compare_traces(entries, reloaded)
        self.assertTrue(diff.ok)
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderSelfComparisonTests -v`
Expected: PASS for both cases — the M10a/b machinery already supports this end-to-end.

If either fails, the recorder is producing entries that don't round-trip through serialize/load (likely a payload-type narrowing issue in `load_golden`). Fix the underlying helper, do not weaken the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10c): cover REQ-12(a) recorder self-comparison"
```

---

## Task 4: Build + ship `tests/golden/m01_event_basics.json` (REQ-11 + REQ-12(e))

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`
- Create: `tests/golden/m01_event_basics.json`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
def _build_m01_recording(root: Path) -> list[TraceEntry]:
    """M01 fixture: one StoryStarted event captured by the recorder.

    All event fields are literal strings — no real timestamps, no PIDs,
    no float fields — so the serialized trace is byte-identical across
    runs once the recorder's timestamp redaction collapses the literal
    ``timestamp`` field to ``"<ts>"``.
    """
    emitter = TelemetryEmitter(root / "events.jsonl")
    event = StoryStarted(
        timestamp="2026-06-15T00:00:00Z",
        run_id="m01-fixture-run",
        epic="e1",
        story_key="s1",
        agent="dev",
        model="opus",
        complexity="M",
    )
    with GoldenTraceRecorder(repo_root=root) as rec:
        emitter.emit(event)
    return rec.entries


class M01FixtureTests(unittest.TestCase):
    """REQ-11 + REQ-12(e): m01_event_basics.json round-trip."""

    def test_m01_fixture_matches_fresh_recording(self) -> None:
        _validate_or_regen("m01_event_basics.json", _build_m01_recording)

    def test_m01_fixture_records_exactly_one_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = _build_m01_recording(Path(tmp).resolve())
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].channel, "event")
        self.assertEqual(entries[0].kind, "StoryStarted")
        # Timestamp redaction must have fired.
        self.assertEqual(entries[0].payload["timestamp"], "<ts>")
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M01FixtureTests -v`
Expected: FAIL on `test_m01_fixture_matches_fresh_recording` — fixture file does not exist yet (`AssertionError: fixture ... does not exist; run with BMA_GOLDEN_REGEN=1 to generate it`). The exactly-one-event test passes immediately.

- [ ] **Step 3: Generate the fixture**

Run:

```bash
BMA_GOLDEN_REGEN=1 PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M01FixtureTests -v
```

Expected: PASS — both tests pass, and `tests/golden/m01_event_basics.json` is now on disk.

- [ ] **Step 4: Inspect the generated fixture**

Run: `cat tests/golden/m01_event_basics.json`
Expected: a single-line canonical-JSON array containing one entry with `channel="event"`, `kind="StoryStarted"`, `seq=0`, payload with `timestamp="<ts>"`, `epic="e1"`, `story_key="s1"`, etc. Trailing newline present.

- [ ] **Step 5: Run validation without the env var, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M01FixtureTests -v`
Expected: PASS for both cases — fixture on disk matches fresh recording byte-for-byte at the entry level.

- [ ] **Step 6: Commit**

```bash
git add tests/golden/m01_event_basics.json tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10c): ship m01_event_basics golden fixture"
```

---

## Task 5: Build + ship `tests/golden/m02_emitter_smoke.json` (REQ-11 + REQ-12(e))

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`
- Create: `tests/golden/m02_emitter_smoke.json`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
def _build_m02_recording(root: Path) -> list[TraceEntry]:
    """M02 fixture: five StoryStarted events emitted in order, captured.

    The emitter routes each event through write_atomic_text on its
    backing JSONL log, but that file lives in ``root`` (the tempdir) and
    is OUTSIDE the recorder's interest — the recorder only intercepts
    ``state.write_atomic_text``, not ``atomic_io.write_atomic_text``
    directly. So only the five event entries appear in the trace,
    matching the spec's "five emitted events read back" description.
    """
    emitter = TelemetryEmitter(root / "events.jsonl")
    events = [
        StoryStarted(
            timestamp="2026-06-15T00:00:00Z",
            run_id="m02-fixture-run",
            epic="e1",
            story_key=f"s{i}",
            agent="dev",
            model="opus",
            complexity="M",
        )
        for i in range(5)
    ]
    with GoldenTraceRecorder(repo_root=root) as rec:
        for ev in events:
            emitter.emit(ev)
    return rec.entries


class M02FixtureTests(unittest.TestCase):
    """REQ-11 + REQ-12(e): m02_emitter_smoke.json round-trip."""

    def test_m02_fixture_matches_fresh_recording(self) -> None:
        _validate_or_regen("m02_emitter_smoke.json", _build_m02_recording)

    def test_m02_fixture_records_five_events_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = _build_m02_recording(Path(tmp).resolve())
        self.assertEqual(len(entries), 5)
        self.assertEqual([e.seq for e in entries], [0, 1, 2, 3, 4])
        self.assertEqual([e.channel for e in entries], ["event"] * 5)
        self.assertEqual([e.kind for e in entries], ["StoryStarted"] * 5)
        self.assertEqual(
            [e.payload["story_key"] for e in entries],
            ["s0", "s1", "s2", "s3", "s4"],
        )
```

- [ ] **Step 2: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M02FixtureTests -v`
Expected: FAIL on `test_m02_fixture_matches_fresh_recording` — fixture file missing.

- [ ] **Step 3: Generate the fixture**

Run:

```bash
BMA_GOLDEN_REGEN=1 PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M02FixtureTests -v
```

Expected: PASS — `tests/golden/m02_emitter_smoke.json` written.

- [ ] **Step 4: Run validation, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M02FixtureTests -v`
Expected: PASS for both cases.

- [ ] **Step 5: Commit**

```bash
git add tests/golden/m02_emitter_smoke.json tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10c): ship m02_emitter_smoke golden fixture"
```

---

## Task 6: Build + ship `tests/golden/m05_atomic_write_smoke.json` (REQ-11 + REQ-12(e))

**Rationale:** M05 fixture exercises composite-identity lock (`acquire_run_lock`) + heartbeat thread + concurrent threads calling `state.write_atomic_text`. The recorder filters `.run.lock` writes (heartbeat noise), so only the protected state writes appear in the trace. To make the trace byte-identical across runs even though the underlying threads are concurrent, we chain the worker threads with `threading.Event` objects: each thread blocks until the previous one signals, so the write-completion order — and therefore the arrival order at the recorder — is fixed. This is what the spec means by "deterministic when the underlying operations themselves complete in a deterministic order".

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`
- Create: `tests/golden/m05_atomic_write_smoke.json`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`. First, top-of-file imports:

```python
from story_automator.core.atomic_io import (
    HeartbeatThread,
    RunLockIdentity,
    acquire_run_lock,
)
```

Then:

```python
def _build_m05_recording(root: Path) -> list[TraceEntry]:
    """M05 fixture: three concurrent state writes under composite-identity
    lock + heartbeat thread, sequenced via threading.Event for a fixed
    completion order.

    The lock-file writes (`<root>/.run.lock`) are filtered by the
    recorder's `_is_heartbeat_lock_path` helper, and heartbeat writes go
    through `atomic_io.write_atomic_text` directly (not state.py), so
    neither pollutes the trace. The only recorded entries are the three
    `state.mutation` events from the worker threads, in seq 0/1/2 order.
    """
    lock_path = root / ".run.lock"
    # Three gates: gate[0] starts thread 0 immediately; thread i sets
    # gate[i+1] after its write completes so thread i+1 can proceed.
    gates = [_threading.Event() for _ in range(4)]
    gates[0].set()
    write_results: list[Exception | None] = [None, None, None]

    def worker(i: int) -> None:
        try:
            gates[i].wait()
            _state_module.write_atomic_text(root / f"out{i}.json", f'{{"i":{i}}}')
        except Exception as exc:  # surfaced via join + assertion below
            write_results[i] = exc
        finally:
            gates[i + 1].set()

    with GoldenTraceRecorder(repo_root=root) as rec:
        with acquire_run_lock(lock_path, run_id="m05-fixture-run"):
            heartbeat = HeartbeatThread(
                lock_path=lock_path,
                identity=RunLockIdentity(
                    pid=0,
                    start_time=0.0,
                    hostname="fixture",
                    heartbeat_iso="2026-06-15T00:00:00Z",
                    run_id="m05-fixture-run",
                ),
                interval=3600.0,  # never actually fires during the test
            )
            heartbeat.start()
            try:
                threads = [
                    _threading.Thread(target=worker, args=(i,))
                    for i in range(3)
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
            finally:
                heartbeat.stop()
                heartbeat.join(timeout=5.0)
    # Surface any worker failure before returning entries so a regression
    # in atomic_io can't masquerade as a fixture mismatch.
    for i, err in enumerate(write_results):
        if err is not None:
            raise AssertionError(f"worker {i} raised: {err!r}") from err
    return rec.entries


class M05FixtureTests(unittest.TestCase):
    """REQ-11 + REQ-12(e): m05_atomic_write_smoke.json round-trip."""

    def test_m05_fixture_matches_fresh_recording(self) -> None:
        _validate_or_regen("m05_atomic_write_smoke.json", _build_m05_recording)

    def test_m05_fixture_records_three_state_mutations_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = _build_m05_recording(Path(tmp).resolve())
        self.assertEqual(len(entries), 3)
        self.assertEqual([e.seq for e in entries], [0, 1, 2])
        self.assertEqual([e.channel for e in entries], ["state"] * 3)
        self.assertEqual([e.kind for e in entries], ["mutation"] * 3)
        self.assertEqual(
            [e.payload["path"] for e in entries],
            ["out0.json", "out1.json", "out2.json"],
        )
```

Note on `HeartbeatThread` constructor: the M05 implementation accepts `interval` (seconds) — passing 3600.0 ensures it never fires during the fixture's wall-clock window, but its `stop()` + `join()` still exercises the start/stop lifecycle. If the actual constructor signature differs (the project's `HeartbeatThread.__init__` in `atomic_io.py` line ~335 takes `lock_path`, `identity`, `interval`, and possibly an `is_alive` callback), match the signature already in use — do NOT change `atomic_io.py`. If the constructor requires additional args, look at any existing test (e.g. `tests/test_atomic_io.py`) for a reference invocation and copy it verbatim.

- [ ] **Step 2: Verify HeartbeatThread constructor AND stop signature**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -c "
import inspect
from story_automator.core.atomic_io import HeartbeatThread
print('__init__:', inspect.signature(HeartbeatThread.__init__))
print('stop attrs:', [m for m in dir(HeartbeatThread) if 'stop' in m.lower() or 'shut' in m.lower() or 'cancel' in m.lower()])
"
```

Inspect the printed signature and stop API. Adjust `_build_m05_recording` to match the actual project shape:

- If `__init__` uses a different keyword (e.g. `interval_s` instead of `interval`), rename in the call.
- If `__init__` requires a real PID (rejects `pid=0`), replace `pid=0` with `os.getpid()`.
- If the project's stop API is NOT `heartbeat.stop()` but rather `heartbeat.stop_event.set()`, `heartbeat.cancel()`, or `heartbeat.shutdown()`, replace the `heartbeat.stop()` call in `_build_m05_recording` with the actual API. Common patterns: `HeartbeatThread` may expose a `threading.Event` named `_stop` or `stop_event` — set it directly if no `.stop()` method exists.
- If there is NO explicit stop mechanism (the thread is purely daemonic), drop the `heartbeat.stop()` call entirely and rely on `heartbeat.join(timeout=5.0)` returning whether or not the thread exited — but verify daemonic via `heartbeat.daemon` so it doesn't block process shutdown.

The construction AND shutdown must NOT raise. If you cannot quickly determine the API, fall back to NOT instantiating `HeartbeatThread` at all — the spec's gate is about the recorder's behavior under the composite-identity LOCK, and the heartbeat thread's presence is a secondary realism check. Drop it with a one-line code comment noting the simplification, and the M05 fixture is still spec-compliant.

- [ ] **Step 3: Run, expect FAIL**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M05FixtureTests -v`
Expected: FAIL on `test_m05_fixture_matches_fresh_recording` — fixture missing.

- [ ] **Step 4: Generate the fixture**

Run:

```bash
BMA_GOLDEN_REGEN=1 PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M05FixtureTests -v
```

Expected: PASS — `tests/golden/m05_atomic_write_smoke.json` written. Three entries, `path` values `out0.json`/`out1.json`/`out2.json`, each with a deterministic `sha256`.

- [ ] **Step 5: Run validation without the env var, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M05FixtureTests -v`
Expected: PASS for both cases.

- [ ] **Step 6: Commit**

```bash
git add tests/golden/m05_atomic_write_smoke.json tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m10c): ship m05_atomic_write_smoke golden fixture"
```

---

## Task 7: M05 ten-consecutive-runs byte-identical determinism gate (Quality gate)

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class M05DeterminismTests(unittest.TestCase):
    """Quality gate: M05 fixture passes ten consecutive runs with byte-
    identical serialized output, confirming determinism under composite-
    identity lock + heartbeat thread + concurrent worker threads.
    """

    def test_ten_consecutive_recordings_byte_identical(self) -> None:
        outputs: list[bytes] = []
        for _ in range(10):
            with tempfile.TemporaryDirectory() as tmp:
                entries = _build_m05_recording(Path(tmp).resolve())
                outputs.append(serialize_trace(entries).encode("utf-8"))
        # All 10 serializations must be byte-identical.
        first = outputs[0]
        for idx, out in enumerate(outputs[1:], start=1):
            self.assertEqual(
                out, first,
                f"run #{idx} diverged from run #0 byte-wise; "
                f"M05 concurrent-thread fixture is non-deterministic",
            )
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.M05DeterminismTests -v`
Expected: PASS — the Event-chain construction in Task 6 forces a fixed completion order, so all 10 recordings produce identical entry sequences, sha256s, and serializations.

If any run differs from run #0, the gate failed. Diagnose: print the diff between two runs (which seq differs, which field). Most likely cause: a lock or heartbeat write leaking through (re-check `_is_heartbeat_lock_path` matches the actual basename used) or a non-deterministic field surviving redaction.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10c): lock M05 ten-run byte-identical determinism gate"
```

---

## Task 8: End-to-end regression localization with real recorder (strengthens REQ-12(b))

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class RecorderRegressionLocalizationTests(unittest.TestCase):
    """REQ-12(b) at recorder altitude: a real recorded run with one
    injected payload divergence is detected by compare_traces with the
    correct seq and field. Strengthens the M10a unit-level coverage by
    exercising the full pipeline (record -> serialize -> mutate -> load
    -> compare).
    """

    def test_payload_regression_localized_to_correct_seq(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            actual = _build_m02_recording(root)
            # Inject a single-field divergence into a deep-copied golden
            # at seq=2: flip story_key from "s2" to "s2-regressed".
            golden = [
                TraceEntry(
                    seq=e.seq,
                    channel=e.channel,
                    kind=e.kind,
                    payload=dict(e.payload),
                )
                for e in actual
            ]
            golden[2] = TraceEntry(
                seq=golden[2].seq,
                channel=golden[2].channel,
                kind=golden[2].kind,
                payload={**dict(golden[2].payload), "story_key": "s2-regressed"},
            )
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(len(diff.mismatches), 1)
        mismatch = diff.mismatches[0]
        self.assertEqual(mismatch.seq, 2)
        self.assertEqual(mismatch.field, "payload")
        # Diagnostic summary must mention the diverging seq+field so a
        # developer can locate the regression without consulting golden.
        summary = diff.summary()
        self.assertIn("seq=2", summary)
        self.assertIn("payload", summary)

    def test_length_regression_localized_via_recorder(self) -> None:
        # Drop the last entry from a copy of the M02 recording; the
        # length mismatch must be flagged at the tail seq.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            actual = _build_m02_recording(root)
            golden = list(actual[:-1])
        diff = compare_traces(actual, golden)
        self.assertFalse(diff.ok)
        self.assertEqual(len(diff.mismatches), 1)
        self.assertEqual(diff.mismatches[0].seq, 4)
        self.assertEqual(diff.mismatches[0].field, "length")
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.RecorderRegressionLocalizationTests -v`
Expected: PASS — the compare_traces field-priority logic from M10a Task 9 + the recorder pipeline from M10b already produce the right diagnostics.

If the payload diff is reported at a different seq, the regression injector mutated the wrong entry — fix the test, not the helper.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10c): cover REQ-12(b) end-to-end regression localization"
```

---

## Task 9: Four-letter placeholder leak quality gate

**Rationale:** The spec's last quality gate: "No unresolved four-letter placeholder tokens leak into the helper source; any such tokens appearing in event payloads are preserved verbatim through serialization rather than substituted." This gate enforces the *source-leak* half. The recorder may need example tokens in DOCSTRINGS (e.g., "EPIC", "STRY") for documentation — but bare placeholder TOKENS in identifier or string positions must not exist. We match any run of exactly four uppercase ASCII letters surrounded by word boundaries that is NOT immediately preceded by a non-leak prefix (project-naming conventions like `TRUE`, `NONE`, `JSON`, `HTTP`, etc.). We maintain a small allow-list rather than trying to be clever — the helper's source is small enough that the allow-list is auditable.

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class PlaceholderLeakQualityGateTests(unittest.TestCase):
    """Quality gate: no unresolved four-letter placeholder tokens leak
    into tests/golden_trace_helpers.py.

    The recorder source must never contain bare 4-letter uppercase
    sentinels like ``EPIC`` or ``STRY`` — those belong only in template
    payloads, which the recorder preserves verbatim per REQ-13.
    """

    # Allow-list of legitimate 4-uppercase tokens that may appear in the
    # helper source (acronyms, type-system tokens, etc.). Keep small and
    # auditable — anything new requires explicit review.
    _ALLOWED_TOKENS = frozenset({
        "JSON",   # json module, JSONDecodeError
        "HTTP",   # not currently used but reserved
        "NONE",   # Python literal None in docstrings
        "TRUE",   # Python literal True in docstrings
        "ASCI",   # half of "ASCII" — would not match (5 chars)
        "REQ",    # 3 chars, would not match
        "POSIX",  # 5 chars, would not match
        "PEP",    # 3 chars, would not match
    })

    def test_no_unallowed_four_letter_placeholder_in_helper_source(self) -> None:
        import re
        helper_path = Path(__file__).parent / "golden_trace_helpers.py"
        source = helper_path.read_text(encoding="utf-8")
        # Match runs of exactly four uppercase ASCII letters at word
        # boundaries. Strip lines that are pure comments — the gate
        # forgives commentary referencing placeholder tokens by name
        # (e.g., "# REQ-13 last clause: tokens like XXXX flow through").
        pattern = re.compile(r"\b[A-Z]{4}\b")
        offenders: list[tuple[int, str, str]] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for match in pattern.finditer(line):
                token = match.group(0)
                if token in self._ALLOWED_TOKENS:
                    continue
                offenders.append((lineno, token, line.rstrip()))
        self.assertEqual(
            offenders, [],
            f"unresolved 4-letter placeholder tokens in helper source: "
            f"{offenders}",
        )

    def test_four_letter_placeholder_in_event_payload_survives_serialization(
        self,
    ) -> None:
        # Companion check: a placeholder token in a payload must flow
        # through serialize -> load -> compare verbatim (REQ-13 last
        # clause). Already covered at unit level in
        # EventRedactionTests.test_four_letter_placeholder_in_payload_
        # preserved; this strengthens by adding the serialization step.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            emitter = TelemetryEmitter(root / "events.jsonl")
            with GoldenTraceRecorder(repo_root=root) as rec:
                emitter.emit(StoryStarted(
                    timestamp="2026-06-15T00:00:00Z", run_id="r",
                    epic="EPIC", story_key="STRY", agent="a", model="m", complexity="c",
                ))
            entries = rec.entries
            fixture = Path(tmp) / "placeholder.json"
            fixture.write_text(serialize_trace(entries), encoding="utf-8")
            reloaded = load_golden(fixture)
        # Placeholder tokens flow through verbatim end-to-end.
        self.assertEqual(reloaded[0].payload["epic"], "EPIC")
        self.assertEqual(reloaded[0].payload["story_key"], "STRY")
```

- [ ] **Step 2: Run, expect either PASS or a precise leak list**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.PlaceholderLeakQualityGateTests -v`
Expected: PASS if the helper source is clean. If it fails, the test prints the (lineno, token, line) tuples — inspect each, fix the helper if it's an actual leak, or extend `_ALLOWED_TOKENS` if it's a legitimate acronym. Do NOT silence the test wholesale.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10c): add placeholder-token leak quality gate"
```

---

## Task 10: Subprocess-level import-cleanliness gate (Quality gate)

**Rationale:** M10b Task 13 covered import-cleanliness via an in-process subprocess that verified hook *slots* are pristine. The spec's final quality gate restates this in observable terms: "The helper imports cleanly with `python -c 'import tests.golden_trace_helpers'` producing no telemetry events, no state mutations, and no `claude_p` invocations." Asserting *no events fire during import* is stronger than asserting *slots are None*. We cannot use `GoldenTraceRecorder` itself for this check (catch-22: the recorder lives inside the helper module, so loading it loads the helper first), so we instrument the underlying surfaces directly: wrap `state.write_atomic_text` and `TelemetryEmitter.emit` with counter wrappers BEFORE the helper imports, then assert the counters stay at zero. The `claude_p` channel doesn't need instrumentation — the helper sets `_CLAUDE_P_HOOK = None` at module-level, so importing the helper cannot invoke the hook.

**Files:**
- Modify: `tests/test_golden_trace_helpers.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_golden_trace_helpers.py`:

```python
class HelperImportProducesNoObservablesTests(unittest.TestCase):
    """Quality gate: importing tests.golden_trace_helpers emits no
    telemetry events, performs no state mutations, and triggers no
    claude_p invocations during the import itself.

    Uses direct counter wrappers on the two surfaces that could leak
    (state.write_atomic_text and TelemetryEmitter.emit) BEFORE the
    helper imports. claude_p has no module-level call site (the hook
    slot is just rebound to None), so it cannot fire at import time.
    """

    def test_cold_import_produces_no_state_writes_or_emits(self) -> None:
        import subprocess
        import sys

        script = (
            "import sys; sys.path.insert(0, 'skills/bmad-story-automator/src')\n"
            "import json\n"
            # Load the two surfaces FIRST (their own module bodies run
            # once — those are not what the gate is about; the gate is
            # about the helper's body specifically). Then patch their
            # callables with counter wrappers.
            "from story_automator.commands import state as _state\n"
            "from story_automator.core.telemetry_emitter import TelemetryEmitter\n"
            "writes = []\n"
            "emits = []\n"
            "_orig_write = _state.write_atomic_text\n"
            "_orig_emit = TelemetryEmitter.emit\n"
            "def _counted_write(path, data, *, encoding='utf-8'):\n"
            "    writes.append((str(path), data))\n"
            "    return _orig_write(path, data, encoding=encoding)\n"
            "def _counted_emit(self, event):\n"
            "    emits.append(type(event).__name__)\n"
            "    return _orig_emit(self, event)\n"
            "_state.write_atomic_text = _counted_write\n"
            "TelemetryEmitter.emit = _counted_emit\n"
            # NOW import the helper — any side effect during its module
            # body will land in `writes` or `emits`.
            "import tests.golden_trace_helpers as gh\n"
            "out = {\n"
            "    'writes': writes,\n"
            "    'emits': emits,\n"
            "    'claude_p_hook_is_none': gh._CLAUDE_P_HOOK is None,\n"
            "    'active_recorder_is_none': gh._ACTIVE_RECORDER is None,\n"
            "}\n"
            "sys.stdout.write(json.dumps(out))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(
            result.returncode, 0,
            msg=f"subprocess exited {result.returncode}:\n"
                f"stdout={result.stdout}\nstderr={result.stderr}",
        )
        import json as _json
        payload = _json.loads(result.stdout)
        self.assertEqual(
            payload["writes"], [],
            msg=f"helper import triggered state writes: {payload['writes']}",
        )
        self.assertEqual(
            payload["emits"], [],
            msg=f"helper import triggered telemetry emits: {payload['emits']}",
        )
        self.assertTrue(
            payload["claude_p_hook_is_none"],
            msg="helper import installed a non-None claude_p hook",
        )
        self.assertTrue(
            payload["active_recorder_is_none"],
            msg="helper import installed an active recorder",
        )
```

- [ ] **Step 2: Run, expect PASS**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers.HelperImportProducesNoObservablesTests -v`
Expected: PASS — the helper's module body defines classes and constants only; no I/O. `writes=[]`, `emits=[]`, both module-level slots are `None`.

If this fails with `writes` or `emits` non-empty, something in the helper's top-level executes a `state.write_atomic_text` call or emits via `TelemetryEmitter` at import time. Find the offending line and remove it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m10c): cover subprocess import-cleanliness quality gate"
```

---

## Task 11: Full test suite green + ruff + mypy --strict (REQ-15)

**Files:**
- Modify: `tests/test_golden_trace_helpers.py` (only if tooling complains)

- [ ] **Step 1: Run the full M10 test set**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers -v
```

Expected: every `TestCase` from M10a (Tasks 1-12) + M10b (Tasks 1-16) + M10c (Tasks 1-10) passes. Count: ~60+ cases. If any fails, fix the underlying code — do not weaken the test.

- [ ] **Step 2: Run the existing project test suite (no regressions)**

Run:

```bash
npm run test:python
```

Expected: PASS. M10c modifies only `tests/test_golden_trace_helpers.py` and adds `tests/golden/*.json` data files; no `src/` change.

- [ ] **Step 3: Run ruff**

Run:

```bash
python -m ruff check tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
python -m ruff format --check tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py
```

Expected: zero findings. If `ruff format --check` drifts, run `python -m ruff format tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py` and re-check.

- [ ] **Step 4: Run mypy --strict**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m mypy --strict tests/test_golden_trace_helpers.py tests/golden_trace_helpers.py
```

Expected: `Success: no issues found`. Likely findings + fixes:

| mypy finding | fix |
|---|---|
| `Need type annotation for "_ALLOWED_TOKENS"` | Already `frozenset[str]` via literal — if mypy still flags, add explicit `: frozenset[str]` after the name. |
| `Returning Any from function declared to return list[TraceEntry]` on `_build_m0X_recording` | The recorder's `entries` property is `list[TraceEntry]`; if mypy narrows to `Any`, add `cast("list[TraceEntry]", rec.entries)` at the return. |
| `Incompatible default for argument` | Don't introduce defaults — every signature in this plan is concrete. |
| Anything in `_validate_or_regen` | `builder: Callable[[Path], list[TraceEntry]]` is the only callable annotation needed; the rest is plain stdlib. |

- [ ] **Step 5: Commit (only if fixes were applied)**

```bash
git add tests/test_golden_trace_helpers.py tests/golden_trace_helpers.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "fix(m10c): satisfy ruff + mypy --strict"
```

Skip if no fixes needed.

---

## Task 12: Cross-platform smoke + fixture inspection + final verification

**Files:**
- (no changes expected)

- [ ] **Step 1: Inspect the three shipped fixtures**

Run:

```bash
wc -l tests/golden/*.json
```

Expected: each fixture is one line (canonical JSON has no internal newlines, only the trailing one). Three files: `m01_event_basics.json`, `m02_emitter_smoke.json`, `m05_atomic_write_smoke.json`.

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -c "
from pathlib import Path
from tests.golden_trace_helpers import load_golden
for name in ('m01_event_basics', 'm02_emitter_smoke', 'm05_atomic_write_smoke'):
    p = Path('tests/golden') / (name + '.json')
    entries = load_golden(p)
    print(f'{name}: {len(entries)} entries, channels={[e.channel for e in entries]}')
"
```

Expected output:

```
m01_event_basics: 1 entries, channels=['event']
m02_emitter_smoke: 5 entries, channels=['event', 'event', 'event', 'event', 'event']
m05_atomic_write_smoke: 3 entries, channels=['state', 'state', 'state']
```

If counts or channels differ, the fixture diverged from spec — regenerate with `BMA_GOLDEN_REGEN=1`.

- [ ] **Step 2: Re-run the full unittest sweep one final time**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v 2>&1 | tail -50
```

Expected: `OK` and zero failures. Confirm M10a, M10b, and M10c test classes are all present.

- [ ] **Step 3: Verify the regen-gate is one-way (cross-platform)**

Run a sanity check that running the suite WITHOUT `BMA_GOLDEN_REGEN=1` never overwrites a shipped fixture. Use a Python-based sha check (works on Windows git-bash, WSL, and Linux uniformly — `sha256sum` is missing on some Windows shells):

```bash
PYTHONPATH=skills/bmad-story-automator/src python -c "
import hashlib, sys
from pathlib import Path
before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
          for p in Path('tests/golden').glob('*.json')}
print('before:', before)
" > /tmp/golden_before.txt

PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_golden_trace_helpers -v >/dev/null 2>&1

PYTHONPATH=skills/bmad-story-automator/src python -c "
import hashlib
from pathlib import Path
after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
         for p in Path('tests/golden').glob('*.json')}
print('after:', after)
" > /tmp/golden_after.txt

diff /tmp/golden_before.txt /tmp/golden_after.txt && echo 'fixtures untouched (correct)'
```

Expected: `fixtures untouched (correct)`. If the sha values differ, `_validate_or_regen` is overwriting on the normal path — check that the env-var branch is `os.environ.get(_REGEN_ENV) == "1"` and not e.g. truthy-checking an unset value.

- [ ] **Step 4: No final commit required**

M10c is complete. The three fixtures are checked in, REQ-12 sub-cases (a) and (e) are covered, the M05 ten-run determinism gate is locked, the placeholder-leak gate is locked, and the subprocess import-cleanliness gate is locked. M10 as a whole hands off to downstream consumers (future milestones may add more fixtures, but the harness itself is done).

---

## Self-review checklist (run before declaring done)

- [ ] **Spec coverage**
  - REQ-11 (three golden fixtures): Tasks 4, 5, 6
  - REQ-12(a) (record-then-self-compare ok): Task 3
  - REQ-12(b) (payload regression at specific seq): M10a `CompareTracesFieldMismatchTests` + M10c Task 8 (end-to-end variant)
  - REQ-12(c) (length mismatch): M10a `CompareTracesLengthMismatchTests` + M10c Task 8 (end-to-end variant)
  - REQ-12(d) (malformed fixture → GoldenTraceError): M10a `LoadGoldenRejectionTests` (no M10c work needed)
  - REQ-12(e) (each shipped fixture matches fresh recording): Tasks 4, 5, 6
  - REQ-14 (import-time safety, expanded): Task 10 (subprocess gate strengthens M10b's in-process check)
  - Quality gate (M05 ten-run byte-identical): Task 7
  - Quality gate (no placeholder leak in helper source): Task 9
  - Quality gate (`python -c "import"` produces no events/mutations/invocations): Task 10
- [ ] **Placeholders:** None. Every code block is concrete.
- [ ] **Type consistency:** `_GOLDEN_DIR`, `_REGEN_ENV`, `_validate_or_regen`, `_build_m01_recording`, `_build_m02_recording`, `_build_m05_recording`, `_ALLOWED_TOKENS` names match across all tasks. Builders all have signature `(root: Path) -> list[TraceEntry]`.
- [ ] **Scope guard:** No task modifies `tests/golden_trace_helpers.py` body (only the placeholder-leak test reads its source); no task wires `notify_claude_p` into `src/`; no task changes `pyproject.toml`. Fixture files only live under `tests/golden/`.
