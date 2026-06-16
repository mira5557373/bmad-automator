# M09 — Drift Detector

## Context

The M08 milestone delivered a `CalibrationTable` dataclass that maps each `(model_id, task_kind)` pair to an empirical `success_rate` rounded to four decimals, a `sample_count`, and a `last_seen_iso` timestamp, all computed by walking the typed telemetry JSONL ledger laid down by M02. M09 introduces the first analytical comparator that consumes two such tables: a frozen historical baseline (snapshotted from some earlier window) and a current table (rebuilt on demand from recent telemetry). The output is a `DriftReport` listing every `(model_id, task_kind)` pair present in either input together with its baseline rate, current rate, signed delta, and a categorical drift classification. The module is pure-functional, performs zero I/O, and stays import-allowlist friendly so it can be folded into the future `sw estimate` command, a future M03 cost-gate hook, or invoked ad hoc by an operator from a Python REPL. Drift detection here is descriptive rather than prescriptive: this milestone refuses to raise alarms, refuses to mutate any file, and refuses to call back into the telemetry ledger. Those policy-level concerns belong to later milestones that compose on top of `DriftReport`.

## Out of scope

- No telemetry reads. The drift detector accepts two already-built `CalibrationTable` instances and must not open `parse_event`, `TelemetryReader`, or any JSONL ledger directly.
- No persistence. The `DriftReport` is computed on demand and not written to disk by this milestone; a future cache or snapshot layer can land later under its own spec.
- No alarms, no exit codes, no exceptions raised for drift. Severity classification is data only; consumers decide whether to act.
- No threshold tuning UI, no per-model overrides, no time-series smoothing; the four-tier classifier is fixed at this milestone.
- No HMAC chaining, audit trail emission, or interaction with M04; this is read-only analytics.
- No network calls, no model-provider SDK access, no subprocess invocation.
- No CLI surface and no orchestrator wiring in M09; the future `sw estimate` command will be the first caller and that wiring lands separately.
- No new event types, no changes to `core/telemetry_events.py`, and no changes to `core/calibration.py`.

## Functional requirements

REQ-01 The implementation must live at `skills/bmad-story-automator/src/story_automator/core/drift_detector.py` and the test module must live at `skills/bmad-story-automator/tests/test_drift_detector.py`.

REQ-02 The module must begin with `from __future__ import annotations` as its first non-comment statement and must declare a public `__all__` listing exactly the symbols `DriftClassification`, `DriftEntry`, `DriftReport`, `compute_drift`, and `format_drift_report`.

REQ-03 The module must define a `DriftClassification` `enum.Enum` containing exactly four string-valued members named `STABLE`, `MINOR_DRIFT`, `MAJOR_DRIFT`, and `SEVERE_DRIFT`, in that declaration order; each member's value must equal its name as a lowercase string.

REQ-04 The module must define a `DriftEntry` dataclass declared with `@dataclass(kw_only=True, frozen=True)` containing the fields `model_id: str`, `task_kind: str`, `baseline_success_rate: float`, `current_success_rate: float`, `delta: float`, and `classification: DriftClassification`, where `delta` equals `current_success_rate - baseline_success_rate` rounded to four decimal places using `round(value, 4)`.

REQ-05 The module must define a `DriftReport` dataclass declared with `@dataclass(kw_only=True)` containing the fields `entries: list[DriftEntry]`, `generated_at: str`, `baseline_source: str`, and `current_source: str`, where `generated_at` must be populated by calling `iso_now()` imported from `story_automator.core.common` and `baseline_source` and `current_source` must be populated by reading the `source_path` attribute of each input `CalibrationTable`.

REQ-06 The module must expose `compute_drift(baseline: CalibrationTable, current: CalibrationTable) -> DriftReport` as a pure function that produces a deterministic `DriftReport` for any two inputs without performing any I/O, without consulting the file system, and without mutating either input.

REQ-07 `compute_drift` must classify each entry by the absolute value of its rounded `delta` using the following half-open bands: `|delta| < 0.05` is `STABLE`, `0.05 <= |delta| < 0.10` is `MINOR_DRIFT`, `0.10 <= |delta| < 0.20` is `MAJOR_DRIFT`, and `|delta| >= 0.20` is `SEVERE_DRIFT`; the boundary values 0.05, 0.10, and 0.20 must be defined as module-level constants `STABLE_MAX`, `MINOR_MAX`, and `MAJOR_MAX` so a reviewer can audit them at a glance.

REQ-08 `compute_drift` must walk the union of `(model_id, task_kind)` keys present in either input table; for a key missing from `baseline.entries`, `baseline_success_rate` must be treated as `0.5` (maximum uncertainty, matching the `lookup_success_rate` default from M08), and for a key missing from `current.entries`, `current_success_rate` must be treated as `0.5`.

REQ-09 The `entries` list on the returned `DriftReport` must be sorted by descending `abs(delta)` first, then ascending `model_id`, then ascending `task_kind`, so that the worst drift surfaces first and the ordering is stable across runs given identical inputs.

REQ-10 The module must expose `format_drift_report(report: DriftReport) -> str` returning a deterministic plain-ASCII multi-line report whose first line names both source paths, whose header row lists the column names `model_id`, `task_kind`, `baseline`, `current`, `delta`, `classification`, whose body rows render `baseline_success_rate` and `current_success_rate` as `0.XXXX` and `delta` as a signed `+0.XXXX` or `-0.XXXX`, and whose final character is a single trailing newline.

REQ-11 The module must not import `requests`, `httpx`, `aiohttp`, `subprocess`, `os.system`, `psutil`, `filelock`, or any networking client; the only permitted imports are stdlib modules plus `story_automator.core.common` and `story_automator.core.calibration`.

REQ-12 The module must not call `open()`, `Path.write_text`, `Path.read_text`, `Path.mkdir`, `write_atomic`, or any other file-system mutator; static analysis (a simple grep over the source) must find zero such call sites. Any source-level anchor names left for future follow-up work must avoid unresolved four-letter placeholder tokens.

REQ-13 The test module must use `unittest.TestCase` and must cover at minimum: identical baseline and current tables producing all-`STABLE` entries, a controlled `(model_id, task_kind)` pair crossing each of the three classification boundaries from below and from above, a key present only in the baseline being reported with `current_success_rate == 0.5`, a key present only in the current table being reported with `baseline_success_rate == 0.5`, the sort order of the `entries` list against a fixture with mixed deltas, and a snapshot assertion over `format_drift_report` for a known input fixture.

REQ-14 The test module must build its `CalibrationTable` fixtures by composing `CalibrationEntry` instances and the surrounding `CalibrationTable` directly in memory; the test module must not write JSONL files, must not invoke `build_calibration`, and must not depend on any temp directory.

REQ-15 The module must remain importable directly as `from story_automator.core.drift_detector import compute_drift`; no package-level export index change is required in this milestone.

## Non-functional requirements

- The module and its tests must execute identically on Windows git-bash, WSL Ubuntu 22.04+, and Linux CI; no shell-specific path separators may appear in source, and any path comparison must rely on the string form already stored on `CalibrationTable.source_path`.
- No new third-party dependency may be introduced; the runtime budget remains stdlib plus `filelock` and `psutil`, and this module uses neither of the two binary libraries.
- The module file must remain at or below 300 lines and the test file must remain at or below 500 lines, measured by `wc -l`, reflecting that the milestone is intentionally small.
- All union type annotations must use PEP 604 syntax (`float | None`, `list[DriftEntry]`); `typing.Union` and `typing.Optional` must not appear.
- The first non-comment statement in both new files must be `from __future__ import annotations`.
- Line endings in both new files must be LF only; the tests must not depend on platform line endings when asserting against `format_drift_report` output.
- The drift classifier must be deterministic and side-effect free so that repeated calls with the same two inputs return reports whose `entries` list is bitwise identical and whose `generated_at` field is the only varying value across runs.

## Quality gates

- `python -m ruff check skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py` exits zero.
- `python -m ruff format --check skills/bmad-story-automator/src/story_automator/core/drift_detector.py skills/bmad-story-automator/tests/test_drift_detector.py` exits zero.
- `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_drift_detector` exits zero from the repository root.
- `python -m coverage run --source=skills/bmad-story-automator/src/story_automator/core/drift_detector.py -m unittest tests.test_drift_detector && python -m coverage report --fail-under=90 --include="*/core/drift_detector.py"` exits zero, reflecting the small surface area and pure-function discipline.
- An import-allowlist grep over `core/drift_detector.py` finds no occurrence of `requests`, `httpx`, `aiohttp`, `subprocess`, `filelock`, `psutil`, `open(`, `write_text`, or `read_text`.
- `wc -l skills/bmad-story-automator/src/story_automator/core/drift_detector.py` reports a value at or below 300, and `wc -l skills/bmad-story-automator/tests/test_drift_detector.py` reports a value at or below 500.
- A repository-wide grep confirms no occurrence of unresolved four-letter placeholder tokens inside either of the two new files.
- `python -m compileall skills/bmad-story-automator/src/story_automator/core/drift_detector.py` succeeds, confirming the file parses under Python 3.11 without syntax warnings.
