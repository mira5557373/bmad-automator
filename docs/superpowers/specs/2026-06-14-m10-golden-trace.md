## Context

Milestone M10 (slug: `golden-trace`) introduces a golden-trace test harness so that future refactors of the bmad-automator port can be verified for byte-equivalent behavior rather than only "tests still pass." Twelve of fifteen milestones have shipped (M01-M05, M07-M09, M11-M14), producing thirteen typed telemetry events, an atomic emitter, a reader with aggregations, failure triage, calibration, drift detection, an HMAC-chained audit log, budget ceilings, and atomic-IO with a composite-identity lock and heartbeat thread. Each of these subsystems can mutate observable state in three ways: (a) emit telemetry events through `core.telemetry_emitter.TelemetryEmitter`, (b) mutate the on-disk state document via `commands.state.py`, and (c) trigger `claude_p` subprocess invocations. Today, regression tests assert behavior point-by-point; subtle ordering or payload regressions can slip through if any assertion is loose. M10 records the arrival-ordered sequence of all three observable channels during a test run, serializes that sequence as canonical JSON, and provides `compare_traces(actual, golden) -> TraceDiff` so that any drift surfaces as a precise arrival-position diff. Three initial fixtures capture event round-trip (M01), emit-and-read of five events (M02), and an atomic write under concurrent threads (M05). The helper lives at `tests/golden_trace_helpers.py` (deliberately outside `src/`) so it is testing infrastructure, not shipped code. A unit test at `tests/test_golden_trace_helpers.py` covers the helper itself.

## Out of scope

- Property-based or fuzz-based trace generation (golden fixtures are hand-curated for M10).
- Recording of file-system reads, lock acquisitions that do not mutate state, or subprocess stdout/stderr payloads beyond invocation identity.
- Automatic regeneration of golden fixtures on diff; refresh remains an explicit developer action.
- Cross-OS path normalization beyond converting absolute paths to repo-relative POSIX paths.
- Coverage of milestones not yet shipped (M06, M10 itself, M15).
- Replacing existing assertion-style tests; golden traces augment, they do not supplant.

## Functional requirements

- REQ-01 The module must expose a `GoldenTraceRecorder` context manager that, on `__enter__`, installs interception hooks for telemetry emission, state-document mutation, and `claude_p` invocation, and on `__exit__`, removes them and finalizes an in-memory `list[TraceEntry]`.
- REQ-02 Each `TraceEntry` must be a `@dataclass(kw_only=True, frozen=True)` carrying `seq: int` (monotonic 0-based arrival index), `channel: Literal["event", "state", "claude_p"]`, `kind: str`, and `payload: dict[str, object]` with deterministically-ordered keys.
- REQ-03 The recorder must intercept `TelemetryEmitter.emit` and record an `event` entry whose `kind` equals the event class name and whose `payload` is the parsed event dict with monotonic timestamps replaced by the literal string `"<ts>"`.
- REQ-04 The recorder must intercept writes performed by `commands.state.py` (which routes through `core.atomic_io.atomic_write`) and record a `state` entry whose `kind` is `"mutation"` and whose `payload` carries `path` (repo-relative POSIX) and `sha256` of the post-write bytes.
- REQ-05 The recorder must intercept `claude_p` invocations and record a `claude_p` entry whose `kind` is `"invoke"` and whose `payload` carries `argv: list[str]` with absolute paths normalized to repo-relative POSIX form and any unresolved four-letter placeholder tokens preserved verbatim.
- REQ-06 Arrival ordering must be enforced by a single `threading.Lock` so that traces produced under concurrent threads (e.g., the M05 atomic-write smoke fixture) are deterministic when the underlying operations themselves complete in a deterministic order.
- REQ-07 The module must expose `serialize_trace(entries: list[TraceEntry]) -> str` that emits canonical JSON with `sort_keys=True`, `separators=(",", ":")`, and a trailing newline.
- REQ-08 The module must expose `load_golden(path: pathlib.Path) -> list[TraceEntry]` that parses a stored fixture and rejects unknown channels or missing required keys with a typed `GoldenTraceError`.
- REQ-09 The module must expose `compare_traces(actual: list[TraceEntry], golden: list[TraceEntry]) -> TraceDiff` where `TraceDiff` is `@dataclass(kw_only=True)` with `matched: int`, `mismatches: list[TraceMismatch]`, and `ok: bool` (true iff `mismatches` is empty and lengths agree).
- REQ-10 Each `TraceMismatch` must identify the arrival position (`seq`), the diverging field (`"channel" | "kind" | "payload" | "length"`), and PEP 604 `actual: object | None` / `expected: object | None` slots.
- REQ-11 Three golden fixtures must ship: `tests/golden/m01_event_basics.json` (one round-tripped event), `tests/golden/m02_emitter_smoke.json` (five emitted events read back), and `tests/golden/m05_atomic_write_smoke.json` (concurrent atomic-write under composite-identity lock).
- REQ-12 `tests/test_golden_trace_helpers.py` must contain `unittest.TestCase` cases that (a) record-then-compare a trace against itself yielding `ok=True`, (b) detect a payload regression at a specific `seq`, (c) detect a length mismatch, (d) reject malformed fixtures via `GoldenTraceError`, and (e) validate each of the three shipped fixtures against a freshly recorded run.
- REQ-13 The helper must redact non-deterministic fields (timestamps, PIDs, lock-token UUIDs, heartbeat counters) by substituting the literal string `"<redacted>"` before serialization, leaving any unresolved four-letter placeholder tokens that appear in event payloads untouched.
- REQ-14 The module must be importable with no side effects: no hooks are installed until `GoldenTraceRecorder.__enter__` is invoked, and `__exit__` must restore the original callables even when the recorded block raises.
- REQ-15 The module must use `from __future__ import annotations`, target Python 3.11+ standard library only (no third-party dependencies beyond those already in use by `core.atomic_io`), and pass `ruff` and `mypy --strict` under the project's existing configuration.

## Non-functional requirements

- Determinism: For a given test body whose underlying operations terminate in a fixed order, the serialized trace must be byte-identical across runs, OSes, and Python patch versions; this is the whole point of M10 and is the primary acceptance criterion.
- Performance: Hook overhead must add no more than ~50 microseconds per intercepted operation on commodity hardware; the M02 five-event fixture must record and serialize in under 100 milliseconds end-to-end.
- Isolation: The recorder must not retain global state after `__exit__`; two sequential `with` blocks must produce independent traces with no leakage of entries, locks, or monkey-patches.
- Safety: Interception must not alter the semantics of `TelemetryEmitter.emit`, `atomic_write`, or `claude_p`; the recorded operations must complete with their normal return values and side effects, with the recorder acting as a passive observer.
- Diagnostics: When `compare_traces` finds a mismatch, the human-readable summary must include enough context (channel, kind, payload diff) to locate the regression without consulting the golden file directly.

## Quality gates

- All `unittest.TestCase` cases in `tests/test_golden_trace_helpers.py` pass under `python -m unittest`.
- `ruff check tests/golden_trace_helpers.py tests/test_golden_trace_helpers.py` reports zero findings.
- `mypy --strict tests/golden_trace_helpers.py` reports zero errors.
- Each of `tests/golden/m01_event_basics.json`, `tests/golden/m02_emitter_smoke.json`, and `tests/golden/m05_atomic_write_smoke.json` parses via `load_golden` and matches a freshly recorded run with `TraceDiff.ok=True`.
- The M05 concurrent-thread fixture passes ten consecutive runs with byte-identical serialized output, confirming determinism under the composite-identity lock and heartbeat thread.
- A deliberately injected payload regression (e.g., flipping a boolean field in one recorded event) is detected by `compare_traces` with a `TraceMismatch` whose `seq` and field accurately localize the divergence.
- No unresolved four-letter placeholder tokens leak into the helper source; any such tokens appearing in event payloads are preserved verbatim through serialization rather than substituted.
- The helper imports cleanly with `python -c "import tests.golden_trace_helpers"` producing no telemetry events, no state mutations, and no `claude_p` invocations.