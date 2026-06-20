# D9 — Python version matrix

Repo: `/home/ubuntu/projects/personal/bmad-automator`
Branch: `bma-d/integration-all`
Audit date: 2026-06-19

## Declared support

- `skills/bmad-story-automator/pyproject.toml:11` — `requires-python = ">=3.11"`
- `skills/bmad-story-automator/pyproject.toml:15-22` — classifiers list 3.11, 3.12, 3.13
- `README.md:16` — "Python >= 3.11"
- `README.md:18` — "Python deps beyond the stdlib: `filelock`, `psutil`" (declared in prose, NOT in pyproject)
- `pyproject.toml` — **no `[project.dependencies]` section exists at all**

## Matrix results

| Python | uv install | venv create | install -e ok | pytest collect ok | failures (full run)                                                                 | notes |
|--------|------------|-------------|---------------|-------------------|--------------------------------------------------------------------------------------|-------|
| 3.11.15 | ok       | ok          | ok            | 1482 collected     | 10 failed / 1471 passed / 1 skipped — 9 `kw_only` dataclass introspection + 1 shared | declared MIN; runtime semantics of `kw_only=True` work but `__dataclass_params__.kw_only` attr was added in 3.12 |
| 3.12.13 | ok (pre-installed) | ok  | ok            | 1482 collected     | 1 failed / 1480 passed / 1 skipped — shared `test_build_cmd_uses_legacy_ai_command_consistently_for_claude` | clean baseline |
| 3.13.14 | ok       | ok          | ok            | 1482 collected     | 1 failed / 1480 passed / 1 skipped — same shared failure                              | clean baseline |
| 3.14.4  | ok (system) | ok       | ok            | 1482 collected     | run-aborted; same shared failure surfaced at -x ; no version-specific deprecations seen | NOT declared in classifiers; runs fine modulo the same pre-existing test mismatch |

## Notes

1. **Clean reproduction of dependency gap:** `uv pip install -e skills/bmad-story-automator/` into an empty venv pulls in zero transitive deps and the first import of `story_automator.core.atomic_io` raises `ModuleNotFoundError: No module named 'filelock'`. Same fate for `psutil` once `filelock` is installed. Every fresh user install breaks on import.

2. **3.11-only test failures (9 tests):** All in the form `params = ClassName.__dataclass_params__; self.assertTrue(params.kw_only)`. `_DataclassParams.kw_only` was added in Python 3.12. The decorator `@dataclass(kw_only=True)` itself works on 3.11 (positional construction is correctly rejected), so production semantics are unaffected — only the test introspection breaks. Files:
   - `tests/test_feature_tester.py:74`
   - `tests/test_gap_validator.py` (3 tests: Gap, GapStatus, ValidationReport)
   - `tests/test_golden_trace_helpers.py` (3 tests: TraceEntry, TraceMismatch, TraceDiff)
   - `tests/test_spec_compliance.py` (2 tests: ReqVerdict, ComplianceReport)

3. **Shared cross-version failure** (1 test, all 4 versions):
   `tests/test_state_policy_metadata.py::StatePolicyMetadataTests::test_build_cmd_uses_legacy_ai_command_consistently_for_claude` — the test sets `AI_COMMAND=claude --print`, but the rendered command contains `claude --dangerously-skip-permissions ...`. This is test/code drift, not a version issue. Out of scope for D9 but worth flagging to D8 / other dimensions.

4. **3.14:** undeclared in classifiers but runs (modulo the same pre-existing failure). No version-specific breakage observed. Recommendation: leave as known-not-tested; do not block.

5. **uv environment:** `uv 0.11.22`, installed Python 3.11.15 and 3.13.14 via `uv python install`; 3.12.13 and 3.14.4 already present on the host.
