# M08 — Per-Model Calibration Tracker

## Context

The M01 milestone established a typed `Event` hierarchy emitted through the M02 `TelemetryEmitter` into a JSONL ledger consumed by `TelemetryReader`. Every story completion now lands a `StoryCompleted` or `StoryFailed` record with a `model_id` attribute (the agent backend that produced the work, such as `claude-opus-4`, `claude-sonnet-4-5`, or `gpt-5-codex`) and a `task_kind` attribute (a coarse classifier such as `code`, `review`, `docs`, `infra`). M08 introduces a passive, read-only analytics layer that walks that ledger and produces a calibration table mapping `(model_id, task_kind)` pairs to empirical success rates. Downstream consumers planned for later milestones include M09 (drift detector: alarms when recent success rate drops below a learned baseline), the future `sw estimate` command (cost and confidence estimator), and the retro-fire summarizer that already exists in `TelemetryReader`. M08 is the first analytical module that reads telemetry without writing back to it, and therefore must remain side-effect free.

## Out of scope

- Drift detection, baseline comparison, and alarm emission belong to M09 and must not appear here.
- Cost-per-model rollups belong to a future cost analytics milestone and are already partially served by `TelemetryReader.cost_by_epic`; this module must not touch cost fields.
- The retro-fire feedback loop and post-mortem aggregator stay in M10 and must not be invoked from this module.
- The orchestrator does not need to be wired to this module in M08 — M03 (`sw estimate`) will be the first caller, and that wiring is not part of this milestone.
- No new event types are introduced; if a needed signal is missing, that gap is recorded for M01 follow-up rather than patched here.
- No persistence: the calibration table is computed on demand and not written to disk by this milestone (a cache layer can land later).
- No HTTP, no network calls, no model-provider SDK usage.

## Functional requirements

REQ-01 The implementation must live at `skills/bmad-story-automator/src/story_automator/core/calibration.py` and the test module must live at `skills/bmad-story-automator/tests/test_calibration.py`.

REQ-02 The module must begin with `from __future__ import annotations` and must declare a public `__all__` listing exactly the symbols `CalibrationEntry`, `CalibrationTable`, `build_calibration`, `lookup_success_rate`, and `format_calibration_report`.

REQ-03 The module must define a `CalibrationEntry` dataclass declared with `@dataclass(kw_only=True, frozen=True)` containing the fields `model_id: str`, `task_kind: str`, `success_rate: float`, `sample_count: int`, `last_seen_iso: str`, where `success_rate` is a value in the closed interval `[0.0, 1.0]`.

REQ-04 The module must define a `CalibrationTable` dataclass declared with `@dataclass(kw_only=True)` containing the fields `entries: dict[tuple[str, str], CalibrationEntry]`, `generated_at: str`, `source_path: str`, and `total_events_scanned: int`; the `generated_at` field must be populated using `iso_now()` imported from `story_automator.core.common`.

REQ-05 The module must expose `build_calibration(jsonl_path: str | Path) -> CalibrationTable` that opens the telemetry JSONL ledger in UTF-8, iterates one line at a time without loading the entire file into memory, and tolerates trailing blank lines as well as `\r\n` line endings.

REQ-06 `build_calibration` must delegate per-line parsing to `parse_event` from `story_automator.core.telemetry_events` and must include only `StoryCompleted` and `StoryFailed` records in the aggregation; every `UnknownEvent` and every other concrete event type must be skipped silently while incrementing `total_events_scanned`.

REQ-07 For each `(model_id, task_kind)` key the aggregation must compute `success_rate = completed_count / (completed_count + failed_count)` rounded to four decimal places using `round(value, 4)`, must compute `sample_count = completed_count + failed_count`, and must set `last_seen_iso` to the lexicographically maximum ISO timestamp seen across the contributing events for that key.

REQ-08 If the input path does not exist, `build_calibration` must return a `CalibrationTable` with an empty `entries` dict, `total_events_scanned == 0`, and `source_path` equal to the string form of the input path; it must not raise.

REQ-09 The module must expose `lookup_success_rate(table: CalibrationTable, model_id: str, task_kind: str, default: float = 0.5) -> float` that returns the stored `success_rate` for the exact `(model_id, task_kind)` tuple and returns `default` whenever the key is absent; the default must remain `0.5` so that an unseen pair behaves as maximum uncertainty.

REQ-10 The module must expose `format_calibration_report(table: CalibrationTable) -> str` that emits a deterministic plain-ASCII report whose first line names the source path and whose subsequent rows are sorted by `model_id` then `task_kind` and contain the columns `model_id`, `task_kind`, `success_rate` (rendered as `0.XXXX`), `sample_count`, and `last_seen_iso`; the report must end with a single trailing newline.

REQ-11 The module must not import `requests`, `httpx`, `aiohttp`, or any networking client, and must not invoke `subprocess`, `os.system`, `psutil`, or `filelock`; the only permitted imports are stdlib modules plus `story_automator.core.common`, `story_automator.core.telemetry_events`, and standard typing helpers.

REQ-12 The module must not write any file under any circumstance; persistence is out of scope. If a future cache JSON file is added, it must wait for an explicit follow-up milestone, and any helper anchor names placed in the source for that future work must avoid unresolved four-letter placeholder tokens.

REQ-13 The test module must use `unittest.TestCase` and must cover at minimum: empty JSONL input, a single `StoryCompleted` event, a single `StoryFailed` event, multiple completions and failures for the same `(model_id, task_kind)` key, a model-id mismatch under `lookup_success_rate` returning the default, presence of `UnknownEvent` and unrelated event types being ignored, and a snapshot assertion over `format_calibration_report` for a known input fixture.

REQ-14 The test module must build its JSONL fixtures by composing concrete event instances and serializing them through `compact_json` so that the wire format under test matches what M02 writes, and must place those fixtures in a `tempfile.TemporaryDirectory` whose parent is created via `ensure_dir` from `story_automator.core.common`.

REQ-15 The module must register its public symbols in any milestone-level export index expected by the broader bmad-story-automator package; if no such index exists yet, the module must remain importable directly as `from story_automator.core.calibration import build_calibration`.

## Non-functional requirements

- The module and its tests must execute identically on Windows git-bash, WSL Ubuntu 22.04+, and Linux CI; no shell-specific path separators may appear in source, and all path joining must go through `pathlib.Path`.
- No new third-party dependency may be introduced; the runtime budget remains stdlib plus `filelock` and `psutil`, and this module uses neither of the two binary libraries.
- The module file must remain at or below 500 lines and the test file must remain at or below 500 lines, measured by `wc -l`.
- All union type annotations must use PEP 604 syntax (`str | Path`, `float | None`); `typing.Union` and `typing.Optional` must not appear.
- The first non-comment statement in both new files must be `from __future__ import annotations`.
- Line endings in both new files must be LF only; the implementation must not depend on platform line endings when reading the telemetry ledger and must treat `\r\n` and `\n` identically.

## Quality gates

- `ruff check skills/bmad-story-automator/src/story_automator/core/calibration.py skills/bmad-story-automator/tests/test_calibration.py` exits zero.
- `ruff format --check skills/bmad-story-automator/src/story_automator/core/calibration.py skills/bmad-story-automator/tests/test_calibration.py` exits zero.
- `python -m unittest tests.test_calibration` exits zero from the `skills/bmad-story-automator` working directory.
- `coverage run -m unittest tests.test_calibration && coverage report --fail-under=85 --include="*/core/calibration.py"` exits zero.
- An import-allowlist grep over `core/calibration.py` finds no occurrence of `requests`, `httpx`, `aiohttp`, `subprocess`, `filelock`, or `psutil`.
- `wc -l skills/bmad-story-automator/src/story_automator/core/calibration.py` reports a value at or below 500.
- A repository-wide grep confirms no occurrence of unresolved four-letter placeholder tokens inside the two new files.
- `python -m compileall skills/bmad-story-automator/src/story_automator/core/calibration.py` succeeds, confirming the file parses under Python 3.11 without syntax warnings.
