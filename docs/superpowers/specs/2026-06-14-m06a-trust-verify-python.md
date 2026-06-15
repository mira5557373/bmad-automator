## Context

M06a delivers the Python plumbing for the bmad-automator trust-but-verify pattern: three independent verification layers that an orchestrating BMAD skill (delivered later in M06b) will chain together to validate review-skill output before accepting a milestone as complete. Layer 1 (`core/gap_validator.py`) is a deterministic, stdlib-only verifier that consumes a structured gap list emitted by a review skill and checks that each gap's file path resolves, its line number falls within the file's line range, and its named symbol literally occurs in the cited source — producing a `ValidationReport` with per-gap confidence in the closed interval [0.0, 1.0]. Layer 2 (`core/spec_compliance.py`) spawns a fresh `claude -p` subprocess in non-interactive mode to compare a candidate implementation diff against the corresponding spec's REQ list, returning a per-REQ classification of `implemented`, `missing`, or `partial`. Layer 3 (`core/feature_tester.py`) walks the implemented REQs from Layer 2 and, for each one, either locates an existing feature test in `tests/test_compliance_*.py` whose docstring cites the REQ id, or writes a new minimal failing-skeleton test file so the next TDD pass has something to fill in. The three layers are deliberately decoupled — each is independently importable, independently testable, and emits a typed result dataclass — so the M06b orchestrator can mix-and-match or short-circuit on early failure.

## Out of scope

- The BMAD skill markdown (`skills/trust-but-verify/SKILL.md`) that wires these layers into the orchestrator review step — that belongs to M06b.
- Any modification of `core/audit.py`, `core/telemetry_emitter.py`, or other shipped subsystems; M06a is purely additive.
- Cross-language gap validation (e.g., validating TypeScript or Markdown gaps) — Layer 1 is Python-source-aware only in this milestone.
- Network calls beyond the single `claude -p` subprocess invocation in Layer 2; no HTTP, no MCP, no API client wrappers.
- Persisting validation reports to disk under `.bmad/` — callers handle persistence using existing `core/atomic_io.py` helpers from M05.

## Functional requirements

- **REQ-01** `core/gap_validator.py` must expose a frozen `@dataclass(kw_only=True)` `Gap` with fields `file_path: str`, `line: int`, `symbol: str`, `description: str`, and `severity: str`, where `severity` is one of `"blocker" | "major" | "minor"`.
- **REQ-02** `core/gap_validator.py` must expose a frozen `@dataclass(kw_only=True)` `GapStatus` with fields `gap: Gap`, `path_exists: bool`, `line_in_range: bool`, `symbol_present: bool`, `confidence: float`, and `notes: list[str]`.
- **REQ-03** `core/gap_validator.py` must expose a frozen `@dataclass(kw_only=True)` `ValidationReport` with fields `statuses: list[GapStatus]`, `overall_confidence: float`, and `validated_at: str` (ISO-8601 from `core.common.iso_now`).
- **REQ-04** `core/gap_validator.py` must expose `validate_gaps(gaps: list[Gap], *, repo_root: Path) -> ValidationReport` that starts each gap at confidence 0.8 and adds 0.05 for each of `path_exists`, `line_in_range`, and `symbol_present` that pass, capping at 1.0; failed checks contribute 0.0 and append a human-readable note.
- **REQ-05** `validate_gaps` must treat any path escape attempt (absolute paths outside `repo_root`, `..` traversal resolving outside the root, symlinks pointing outside) as `path_exists=False` with a note referencing the rejected path, and must never read files outside `repo_root`.
- **REQ-06** `core/gap_validator.py` must expose `parse_gap_list(payload: str) -> list[Gap]` that accepts a JSON document shaped as `{"gaps": [...]}` and raises `ValueError` with a precise field-locating message when a required key is missing, when `line` is non-integer, or when `severity` is outside the allowed set.
- **REQ-07** `core/spec_compliance.py` must expose a frozen `@dataclass(kw_only=True)` `ReqVerdict` with fields `req_id: str`, `status: Literal["implemented", "missing", "partial"]`, `evidence: str`, and `confidence: float`.
- **REQ-08** `core/spec_compliance.py` must expose a frozen `@dataclass(kw_only=True)` `ComplianceReport` with fields `verdicts: list[ReqVerdict]`, `spec_path: str`, `diff_sha: str`, and `model_invocation_ms: int`.
- **REQ-09** `core/spec_compliance.py` must expose `check_compliance(*, spec_path: Path, diff_text: str, timeout_s: int = 120, claude_binary: str = "claude") -> ComplianceReport` that invokes `claude -p` via `subprocess.run` with `check=False`, `text=True`, `capture_output=True`, and `timeout=timeout_s`, parses the model's JSON response, and returns a populated `ComplianceReport`.
- **REQ-10** `check_compliance` must raise `ComplianceError` (a module-level `Exception` subclass) when the subprocess exits non-zero, times out, or emits output that cannot be parsed as the expected JSON envelope, and must never silently downgrade a parse failure into a `missing` verdict.
- **REQ-11** `check_compliance` must inject the spec text and diff text into the prompt as fenced code blocks and must escape any unresolved four-letter placeholder tokens in the spec to prevent the subprocess from receiving template directives intended for human authoring.
- **REQ-12** `core/feature_tester.py` must expose a frozen `@dataclass(kw_only=True)` `TestPlanEntry` with fields `req_id: str`, `existing_test_path: str | None`, `created_test_path: str | None`, and `action: Literal["found", "created", "skipped"]`.
- **REQ-13** `core/feature_tester.py` must expose `plan_feature_tests(verdicts: list[ReqVerdict], *, tests_dir: Path, dry_run: bool = False) -> list[TestPlanEntry]` that processes only verdicts with `status == "implemented"`, searches `tests/test_compliance_*.py` for a docstring or comment matching the REQ id, and otherwise writes a minimal skeleton file using `core.atomic_io.atomic_write`.
- **REQ-14** The skeleton test file created by `plan_feature_tests` must be a valid `unittest.TestCase` subclass with one `test_<req_id_lower>_skeleton` method body of `self.fail("REQ-NN not yet covered by feature test")`, must import `from __future__ import annotations`, and must place the REQ id verbatim in the class docstring.
- **REQ-15** When `dry_run=True`, `plan_feature_tests` must compute the plan without writing any file and must set `created_test_path` to the path that *would* have been written, with `action="skipped"`.
- **REQ-16** All three layer modules must be importable in any order with no import-time side effects beyond standard `logging.getLogger(__name__)` and must declare `__all__` listing exactly their public dataclasses and entry-point functions.

## Non-functional requirements

- Python 3.11+ stdlib only across all three modules, plus `filelock` exclusively where `core.atomic_io` already requires it; `psutil` must not be imported by M06a code.
- Every module must begin with `from __future__ import annotations` and use PEP 604 union syntax (`X | None`) rather than `typing.Optional`.
- All dataclasses must be `@dataclass(kw_only=True, frozen=True)` and must not subclass other dataclasses; equality and hashing rely on frozen semantics.
- Subprocess invocation in Layer 2 must pass arguments as a list (never `shell=True`), must set `cwd` to a caller-supplied path defaulting to the current working directory, and must propagate `LANG=C.UTF-8` in the child environment for deterministic locale.
- Public API docstrings must state pre-conditions, post-conditions, and the exact exception types raised; private helpers may use brief one-line docstrings.

## Quality gates

- `ruff check core/gap_validator.py core/spec_compliance.py core/feature_tester.py tests/test_gap_validator.py tests/test_spec_compliance.py tests/test_feature_tester.py` reports zero findings.
- `mypy --strict` over the three new modules reports zero errors; no `# type: ignore` comments are introduced without an adjacent justification comment.
- `python -m unittest tests.test_gap_validator tests.test_spec_compliance tests.test_feature_tester` passes with at least 18 test methods across the three test files, including at least one negative test per public function.
- Layer 2 tests must stub the `claude` subprocess using `unittest.mock.patch("subprocess.run")` and must never invoke a real model; any test that would shell out is marked `@unittest.skip` with a recorded reason.
- Layer 3 tests must use `tempfile.TemporaryDirectory` for `tests_dir` and must assert byte-equality of the generated skeleton against a frozen golden string to detect accidental template drift.
- Coverage measured via `coverage run -m unittest` over the three modules must reach at least 92% line coverage, with any uncovered lines justified by an inline `# pragma: no cover` and a one-line rationale.
- No module in M06a may import from `commands/` or from any other M06a layer module, preserving the three-way independence asserted in the intent.
- The combined diff for M06a must not modify any file outside `core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`, and the three corresponding `tests/test_*.py` files.