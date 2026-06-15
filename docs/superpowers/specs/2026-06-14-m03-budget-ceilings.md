# M03 — Budget Ceilings and Preflight Gates

## Context

The M01 milestone introduced the typed `Event` hierarchy, M02 landed `TelemetryEmitter` writing JSONL ledgers consumed by `TelemetryReader`, and M07 produced a `FailureClass` taxonomy that already names `BUDGET_EXCEEDED` as a first-class verdict. None of those milestones, however, can stop a run from spending more money — they only describe what happened after the fact. M03 closes that loop by introducing a passive cost gate that reads the same JSONL ledger and refuses to advance the orchestrator past three well-defined preflight points when projected spend would breach an operator-configured ceiling. The configuration surface lives in `workflow.json` under `policy.cost_ceilings` and supports a per-run limit plus rolling 24-hour, 7-day, and 30-day windows. The decision surface is a tri-state `ALLOW`/`WARN`/`BLOCK` verdict carried by a `CeilingDecision` enum, paired with a human-readable reason string suitable for the BMAD skill markdown to surface to the operator. The implementation lives at `core/budget_ceilings.py` with tests at `tests/test_budget_ceilings.py`, and a short ten-line insertion in `skills/bmad-story-automator/steps-c/step-01-init.md` wires the gate into the existing init step. M03 is read-only with respect to the ledger and emits no new event types of its own; downstream modules such as M08 calibration and M09 drift detection continue to function unchanged.

## Out of scope

- This milestone does not implement the orchestrator retry loop, backoff scheduling, or jitter; that work stays in the broader retry-policy track and is consumed by M03 only through the existing `retry_start` gate name.
- It does not introduce new event types or extend M01; cost data is read from existing `StoryCompleted`, `StoryFailed`, and any other event subclass that already carries a `cost_usd` attribute.
- It does not modify `TelemetryReader.cost_by_epic`; ceiling evaluation reads the ledger directly through `parse_event` to avoid coupling to reader internals.
- It does not own audit-log writes; the M04 HMAC-chained audit log remains the canonical record of ceiling decisions and is invoked by callers, not by this module.
- It does not implement a CLI command surface; `sw cli ceiling-check` is the existing dispatch entry point and gains a new subcommand only as a thin wrapper around `evaluate_ceilings`.
- It does not persist ceiling state, cache evaluations, or maintain a sliding-window index; every call is a fresh ledger pass.
- It does not implement notification, email, or chat integration when a ceiling is breached; surface text is returned to the caller for display only.
- It does not validate that the `workflow.json` policy block exists; absence of `policy.cost_ceilings` must return an empty configuration list rather than raise.

## Functional requirements

REQ-01 The implementation must live at `skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` and the test module must live at `skills/bmad-story-automator/tests/test_budget_ceilings.py`; both files must begin with `from __future__ import annotations` as the first non-comment statement.

REQ-02 The module must expose a `CeilingDecision` `enum.Enum` with exactly three members named `ALLOW`, `WARN`, and `BLOCK` in that declaration order, each with a string value equal to the member name.

REQ-03 The module must define a `BudgetCeiling` dataclass declared with `@dataclass(kw_only=True)` containing the fields `name: str`, `window: str`, `limit_usd: float`, `warn_at: float`, and `gate_names: tuple[str, ...]`, where `window` is one of the literal strings `"per_run"`, `"24h"`, `"7d"`, or `"30d"`, where `limit_usd` is strictly positive, and where `warn_at` is a fraction in the half-open interval `(0.0, 1.0]` interpreted as a multiplier on `limit_usd`.

REQ-04 The module must expose `parse_ceilings_config(workflow_json_path: str | Path) -> list[BudgetCeiling]` that reads UTF-8 JSON from disk, navigates to the `policy.cost_ceilings` array, and returns a list of `BudgetCeiling` instances in the order they appear in the file; when the file is missing, when the JSON is empty, or when the `policy` or `cost_ceilings` keys are absent, the function must return an empty list rather than raise.

REQ-05 `parse_ceilings_config` must validate that each ceiling object carries the required keys `name`, `window`, `limit_usd`, `warn_at`, and `gate_names`; any malformed ceiling entry must be skipped silently while a structured warning is appended to a module-level `_PARSE_WARNINGS` list cleared on every call.

REQ-06 The module must expose `evaluate_ceilings(events_path: str | Path, gate_name: str, now_iso: str, *, ceilings: list[BudgetCeiling] | None = None, workflow_json_path: str | Path | None = None) -> tuple[CeilingDecision, str]` that returns the most severe decision across all applicable ceilings and a reason string explaining the verdict; when both `ceilings` and `workflow_json_path` are `None`, the function must return `(CeilingDecision.ALLOW, "no_ceilings_configured")`.

REQ-07 `evaluate_ceilings` must accept `gate_name` values drawn from the set `{"init", "story_start", "retry_start"}` and must apply only those ceilings whose `gate_names` tuple contains `gate_name`; ceilings that do not list the gate must be ignored without affecting the verdict.

REQ-08 `evaluate_ceilings` must compute the spent total by streaming the JSONL ledger line by line through `parse_event` from `core.telemetry_events`, summing the `cost_usd` attribute of every event that carries one, and filtering by the ceiling `window` using `now_iso` as the anchor: `"per_run"` sums all events in the file, `"24h"` sums events whose timestamp is within 86400 seconds of `now_iso`, `"7d"` sums within 604800 seconds, and `"30d"` sums within 2592000 seconds.

REQ-09 The decision rule must be: if `spent >= limit_usd` then `BLOCK`, else if `spent >= limit_usd * warn_at` then `WARN`, else `ALLOW`; the reason string must use the format `f"{ceiling.name}:{ceiling.window}:spent={spent:.4f}:limit={ceiling.limit_usd:.4f}"`.

REQ-10 When multiple ceilings apply to a single gate, the function must return the most severe verdict (`BLOCK` outranks `WARN` outranks `ALLOW`) and the reason string of the most severe ceiling; ties on severity must be broken by ceiling declaration order in `workflow.json`.

REQ-11 The module must expose a helper `bypass_allowed() -> bool` that returns `True` only when both the environment variable `BMAD_ALLOW_CEILING_BYPASS` equals the exact string `"1"` and `sys.stdin.isatty()` returns `True`; any other combination must return `False`, and the helper must not prompt or read input.

REQ-12 The module must not write to the ledger, must not call `TelemetryEmitter.emit`, must not invoke audit-log routines, and must not mutate state on disk; the only permitted imports are stdlib modules plus `core.common`, `core.telemetry_events`, and standard typing helpers.

REQ-13 The BMAD skill markdown at `skills/bmad-story-automator/steps-c/step-01-init.md` must receive an insertion of approximately ten lines that calls `sw cli ceiling-check --gate init`, parses the tri-state result, refuses to proceed on `BLOCK` unless `bypass_allowed()` is true and the operator confirms interactively, surfaces the reason string on `WARN`, and is silent on `ALLOW`; equivalent insertions must land at the `story_start` and `retry_start` gate sites referenced by the existing markdown templates.

REQ-14 The test module must use `unittest.TestCase` and must cover at minimum: empty ledger returning `ALLOW`, a single `StoryCompleted` event with `cost_usd` below the warn threshold returning `ALLOW`, a series of events crossing the warn threshold but staying below the limit returning `WARN`, a series crossing the limit returning `BLOCK`, each of the four window types being honored when `now_iso` is varied, malformed ceiling entries in `workflow.json` being skipped without raising, the bypass helper returning `False` when the environment variable is unset, and the multi-ceiling severity rule returning the worst verdict.

REQ-15 Test fixtures must be built by composing concrete M01 event instances and serializing them through `compact_json` from `core.common` so that the wire format under test matches what M02 writes; temporary directories must be created through `ensure_dir` and cleaned up via `tempfile.TemporaryDirectory`.

## Non-functional requirements

- The module and its tests must execute identically on Windows git-bash, WSL Ubuntu 22.04+, and Linux CI; all path handling must go through `pathlib.Path` and no shell-specific path separators may appear in source.
- No new third-party dependency may be introduced; the runtime budget remains stdlib plus `filelock` and `psutil`, and this module imports neither because it performs neither locking nor process introspection.
- The source file must remain at or below 500 lines and the test file must remain at or below 500 lines, measured by `wc -l`; the BMAD step markdown insertion must remain at or below fifteen lines per gate site.
- All union type annotations must use PEP 604 syntax (`str | Path`, `float | None`); `typing.Union` and `typing.Optional` must not appear in the new sources.
- The evaluator must be deterministic: two calls with the same `events_path`, `gate_name`, `now_iso`, and ceiling configuration must return byte-identical `CeilingDecision` and reason strings; dict and set iteration order must not influence output.
- The evaluator must tolerate `\r\n` line endings and trailing blank lines in the ledger and must not require the ledger file to exist (absence implies zero spend).

## Quality gates

- `ruff check skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py skills/bmad-story-automator/tests/test_budget_ceilings.py` exits zero.
- `ruff format --check skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py skills/bmad-story-automator/tests/test_budget_ceilings.py` exits zero.
- `python -m unittest tests.test_budget_ceilings` exits zero from the `skills/bmad-story-automator` working directory with zero failures and zero errors.
- `coverage run -m unittest tests.test_budget_ceilings && coverage report --fail-under=85 --include="*/core/budget_ceilings.py"` exits zero.
- An import-allowlist grep over `core/budget_ceilings.py` finds no occurrence of `requests`, `httpx`, `aiohttp`, `subprocess`, `os.system`, `filelock`, or `psutil`.
- `wc -l skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` reports a value at or below 500, and the same measurement on the test file reports at or below 500.
- A repository-wide grep confirms no occurrence of unresolved four-letter placeholder tokens inside the two new files or inside the modified BMAD step markdown.
- `python -m compileall skills/bmad-story-automator/src/story_automator/core/budget_ceilings.py` succeeds, confirming the file parses under Python 3.11 without syntax warnings.
- A determinism gate must invoke `evaluate_ceilings` one hundred times against the same fixture ledger and assert byte-identical tuples on every iteration, guarding against accidental nondeterminism from dict ordering.
- A bypass-gate test must assert that `bypass_allowed()` returns `False` when only the environment variable is set, when only `isatty()` is true, and when both are absent, and returns `True` only when both signals agree.
