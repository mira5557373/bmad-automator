## Context

M07 introduces a pure-functional failure classifier that consumes typed events from the M01 telemetry schema and the M02 JSONL stream, then returns a structured `FailureClass` verdict for each failure-shaped event. The classifier reads `StoryFailed`, `StoryDeferred`, `TmuxSessionCrashed`, and `EscalationTriggered` records that flow through `core/telemetry_emitter.py` and are aggregated by `core/telemetry_reader.py`. Downstream consumers include the adaptive retry policy (M08), the gate-decision engine (M09), and the retrospective summariser (M10), all of which need a stable, deterministic taxonomy before they can reason about whether to retry, defer, or escalate. Because triage is invoked from hot paths in `orchestrator.py` and from offline batch tooling, it must be side-effect free, allocation-cheap, and never touch the filesystem or the network during classification. The module lives at `core/failure_triage.py` with tests at `tests/test_failure_triage.py`, mirroring the layout established by M01 and M02.

## Out of scope

This milestone does not implement retry execution, backoff scheduling, or jitter computation; that work belongs to M03 (orchestrator retry loop) and M08 (adaptive retry policy). It does not generate human-readable escalation messages, which are owned by M06 (escalation router). It does not persist classification verdicts back to the telemetry stream, write audit records, mutate state documents, or call `TelemetryEmitter.emit`; persistence belongs to M02 callers. It does not own gate transitions, deferral windows, or plateau-detection thresholds beyond classifying a single event in isolation; M09 (gate engine) and M10 (retro/plateau detector) consume the classifier output and apply their own policy. It does not introduce a CLI, a daemon, or any long-running process. Finally, it does not attempt to classify success events or arbitrary `UnknownEvent` payloads beyond returning the sentinel `UNKNOWN` class with `LOW` confidence.

## Functional requirements

- REQ-01 The module must reside at `skills/bmad-story-automator/src/story_automator/core/failure_triage.py` and start with `from __future__ import annotations` on the first non-comment line.
- REQ-02 The module must define a `FailureClass` `enum.Enum` with exactly thirteen members named `CRASH`, `TIMEOUT`, `POLICY_VIOLATION`, `REVIEW_REJECTED`, `TEST_FAILURE`, `BUDGET_EXCEEDED`, `PARSE_ERROR`, `AGENT_REFUSED`, `NETWORK_ERROR`, `GATE_DEFER`, `PLATEAU`, `REPEATED_RETRY`, and `UNKNOWN`, in that declaration order, with string values equal to the member name.
- REQ-03 The module must define a `Confidence` `enum.Enum` with members `HIGH`, `MEDIUM`, and `LOW`, string-valued and case-sensitive.
- REQ-04 The module must expose a frozen `@dataclass(frozen=True, kw_only=True)` named `Classification` with fields `primary: FailureClass`, `implies: tuple[FailureClass, ...]`, `confidence: Confidence`, `reason: str`, and `event_id: str | None`, using PEP 604 union syntax.
- REQ-05 The module must declare a module-level constant `IMPLIES_GRAPH: dict[FailureClass, tuple[FailureClass, ...]]` that encodes implication edges, at minimum mapping `POLICY_VIOLATION` to `(REVIEW_REJECTED,)`, `BUDGET_EXCEEDED` to `(GATE_DEFER,)`, `TmuxSessionCrashed`-derived `CRASH` to `(NETWORK_ERROR,)` when transport hints are present, and `REPEATED_RETRY` to `(PLATEAU,)`.
- REQ-06 The public entry point must be `classify(event: Event) -> Classification`, where `Event` is imported from `core.telemetry_events`; the function must be pure, must not perform I/O, and must not raise on any concrete event subclass shipped in M01.
- REQ-07 `classify` must dispatch on the concrete event type: `StoryFailed` routes through `_classify_story_failed`, `StoryDeferred` through `_classify_story_deferred`, `TmuxSessionCrashed` through `_classify_tmux_crash`, and `EscalationTriggered` through `_classify_escalation`; every other event type must return `Classification(primary=FailureClass.UNKNOWN, implies=(), confidence=Confidence.LOW, reason="non_failure_event", event_id=getattr(event, "event_id", None))`.
- REQ-08 `_classify_story_failed` must inspect the `reason` and `error_kind` attributes (string fields on `StoryFailed`) and map substrings deterministically: `"timeout"` -> `TIMEOUT/HIGH`, `"policy"` or `"guardrail"` -> `POLICY_VIOLATION/HIGH` with `REVIEW_REJECTED` implied, `"test"` or `"pytest"` -> `TEST_FAILURE/HIGH`, `"parse"` or `"json"` -> `PARSE_ERROR/MEDIUM`, `"refused"` or `"refusal"` -> `AGENT_REFUSED/HIGH`, `"budget"` or `"cost"` -> `BUDGET_EXCEEDED/HIGH` with `GATE_DEFER` implied, and an unmatched reason -> `UNKNOWN/LOW`.
- REQ-09 `_classify_tmux_crash` must return `CRASH/HIGH`; if the event's `exit_signal` field equals `"SIGPIPE"`, `"SIGHUP"`, or contains `"network"`, the result must additionally include `NETWORK_ERROR` in `implies`.
- REQ-10 `_classify_story_deferred` must return `GATE_DEFER/HIGH`; when the event's `reason` contains `"plateau"` or the optional `attempt_count` exceeds `3`, the classifier must instead return `REPEATED_RETRY/HIGH` with `PLATEAU` implied.
- REQ-11 `_classify_escalation` must return `REVIEW_REJECTED/MEDIUM` by default, upgrading to `POLICY_VIOLATION/HIGH` when the event's `trigger` field starts with `"policy:"`.
- REQ-12 The module must expose `classify_stream(events: Iterable[Event]) -> Iterator[Classification]` as a thin generator wrapper over `classify`; it must not buffer, must not call `iso_now`, and must propagate the underlying iterator's exceptions verbatim.
- REQ-13 The module may import only from `core.telemetry_events`, `core.common` (for the symbols `iso_now`, `compact_json`, `ensure_dir`, `write_atomic` if needed for future expansion — currently unused but reserved), and the standard library; any other import must fail the import-allowlist gate.
- REQ-14 Tests at `skills/bmad-story-automator/tests/test_failure_triage.py` must use `unittest.TestCase`, must construct synthetic events directly via the M01 dataclasses, and must include at least one test method per `FailureClass` value (thirteen tests minimum) plus a round-trip test for `classify_stream` over a list of mixed events.
- REQ-15 Every test must assert on `Classification.primary`, on the membership of expected entries in `Classification.implies`, and on `Classification.confidence`; tests must not read or write files, must not invoke `compact_json`, and must complete in under two seconds in aggregate.

## Non-functional requirements

- The module must run unchanged on Windows under git-bash, on WSL2, and on native Linux; path handling must avoid `os.sep` literals and prefer `pathlib.PurePosixPath` only when string normalisation is required.
- No new third-party imports may be added beyond the project-wide allowlist of stdlib plus `filelock` plus `psutil`; `failure_triage.py` should not import `filelock` or `psutil` at all because it performs no I/O.
- The source file must remain at or below 500 lines including blank lines and docstrings, measured by `wc -l`.
- All files must use LF line endings committed verbatim; tests must not depend on trailing-CRLF normalisation and must pass under `git config core.autocrlf=false`.
- All union types must use PEP 604 (`X | Y`) syntax; `typing.Optional` and `typing.Union` are forbidden in this module.
- Every Python source file in the milestone must begin with `from __future__ import annotations` so that forward references in `Classification` resolve lazily.

## Quality gates

- `ruff check skills/bmad-story-automator/src/story_automator/core/failure_triage.py skills/bmad-story-automator/tests/test_failure_triage.py` must exit zero.
- `ruff format --check` over the same paths must report no diffs.
- `python -m unittest skills.bmad-story-automator.tests.test_failure_triage` must pass with zero failures and zero errors.
- `coverage run -m unittest tests.test_failure_triage && coverage report --fail-under=85` must succeed for `core/failure_triage.py`.
- An import-allowlist grep (`Grep` over the module for any `import` not matching `core.telemetry_events`, `core.common`, `enum`, `dataclasses`, `typing`, `collections.abc`) must return no hits.
- `wc -l skills/bmad-story-automator/src/story_automator/core/failure_triage.py` must report a value less than or equal to 500.
- A dedicated determinism gate must run `classify` over the same synthetic event one hundred times and assert byte-identical `Classification` outputs, guarding against accidental nondeterminism from dict ordering or set iteration.
- A taxonomy-completeness gate must assert that the set of `FailureClass` members has exactly thirteen entries, matching the agreed taxonomy and preventing silent additions; unresolved four-letter placeholder tokens in the source must cause the gate to fail.