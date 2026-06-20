# D8 — Coverage Summary

**Run:** `pytest tests/ --cov=story_automator --cov-branch` on `bma-d/integration-all`.
**Result:** 1480 passed, 1 failed (unrelated `test_state_policy_metadata.py::test_build_cmd_uses_legacy_ai_command_consistently_for_claude`), 1 skipped, 119 subtests passed in ~61s.
**Overall:** 80% line, 77% branch (7106 stmts / 2698 branches).
**Hypothesis usage in `tests/`:** none. `rg 'from hypothesis|@given|RuleBasedStateMachine'` returns zero matches.

## Floors (pragmatic)

| Module bucket | Line ≥ | Branch ≥ |
|---|---|---|
| `core/audit.py` | 90% | 85% |
| `core/atomic_io.py` | 90% | 85% |
| `core/telemetry_emitter.py` | 85% | 80% |
| `core/telemetry_events.py` | 85% | 80% |
| Other `core/*.py` | 80% | 75% |
| `commands/*.py` | 75% | 70% |
| `cli.py` | 75% | — |

## Module table

Flag legend: PASS = at/above floor on both. BELOW-LINE / BELOW-BRANCH / BELOW = under floor (line / branch / both).

### Integrity-critical (audit + atomic_io + telemetry)

| Module | Stmts | Line% | Branch% | Floor (L/B) | Status |
|---|---:|---:|---:|---|---|
| `core/audit.py` | 185 | 95% | 93% | 90 / 85 | PASS |
| `core/atomic_io.py` | 157 | 96% | 96% | 90 / 85 | PASS |
| `core/telemetry_emitter.py` | 44 | 98% | 96% | 85 / 80 | PASS |
| `core/telemetry_events.py` | 181 | 99% | 99% | 85 / 80 | PASS |
| `core/telemetry_reader.py` | 39 | 100% | 100% | 80 / 75 | PASS |

### Other `core/*` modules (floor 80% / 75%)

| Module | Stmts | Line% | Branch% | Status |
|---|---:|---:|---:|---|
| `core/__init__.py` (implicit) | — | 100% | — | PASS |
| `core/agent_config.py` | 168 | 85% | 81% | PASS |
| `core/artifact_paths.py` | 103 | 95% | 94% | PASS |
| `core/budget_ceilings.py` | 177 | 97% | 97% | PASS |
| `core/calibration.py` | 78 | 94% | 92% | PASS |
| `core/common.py` | 126 | **58%** | **50%** | **BELOW** (−22 line / −25 branch) |
| `core/drift_detector.py` | 56 | 95% | 91% | PASS |
| `core/epic_parser.py` | 204 | **75%** | **68%** | **BELOW** (−5 line / −7 branch) |
| `core/failure_triage.py` | 82 | 100% | 100% | PASS |
| `core/feature_tester.py` | 61 | 100% | 100% | PASS |
| `core/frontmatter.py` | 117 | 96% | 95% | PASS |
| `core/gap_validator.py` | 138 | 96% | 97% | PASS |
| `core/prompt_rendering.py` | 17 | 100% | 100% | PASS |
| `core/review_verify.py` | 11 | 100% | 100% | PASS |
| `core/run_identity.py` | 31 | 100% | 100% | PASS |
| `core/run_liveness.py` | 23 | 100% | 100% | PASS |
| `core/runtime_layout.py` | 157 | 89% | 87% | PASS |
| `core/runtime_policy.py` | 432 | 88% | 85% | PASS |
| `core/spec_compliance.py` | 95 | 98% | 97% | PASS |
| `core/sprint.py` | 110 | 82% | 80% | PASS |
| `core/stop_hooks.py` | 365 | 82% | 79% | PASS (line) / PASS (branch ≥75) |
| `core/story_keys.py` | 194 | 92% | 91% | PASS |
| `core/success_verifiers.py` | 178 | 87% | 82% | PASS |
| `core/tmux_runtime.py` | 783 | **62%** | **57%** | **BELOW** (−18 line / −18 branch) |
| `core/utils.py` | 174 | **79%** | 75% | BELOW-LINE (−1) / PASS (branch on floor) |

### `commands/*` (floor 75% / 70%)

| Module | Stmts | Line% | Branch% | Status |
|---|---:|---:|---:|---|
| `commands/_audit_hooks.py` | 11 | 100% | 100% | PASS |
| `commands/agent_config_cmd.py` | 77 | **8%** | **6%** | **BELOW** (−67 line / −64 branch) |
| `commands/audit_verify_cmd.py` | 30 | 87% | 86% | PASS |
| `commands/basic.py` | 185 | **45%** | **39%** | **BELOW** (−30 line / −31 branch) |
| `commands/calibration_cmd.py` | 33 | 91% | 93% | PASS |
| `commands/ceiling_check.py` | 37 | 97% | 96% | PASS |
| `commands/drift_cmd.py` | 42 | 98% | 96% | PASS |
| `commands/orchestrator.py` | 450 | **65%** | **62%** | **BELOW** (−10 line / −8 branch) |
| `commands/orchestrator_epic_agents.py` | 456 | 86% | 82% | PASS |
| `commands/orchestrator_parse.py` | 102 | 78% | 78% | PASS |
| `commands/record_cost.py` | 44 | 91% | 90% | PASS |
| `commands/state.py` | 252 | 80% | 76% | PASS |
| `commands/telemetry_report.py` | 57 | 93% | 93% | PASS |
| `commands/tmux.py` | 387 | **62%** | **59%** | **BELOW** (−13 line / −11 branch) |
| `commands/triage_cmd.py` | 39 | 97% | 96% | PASS |
| `commands/trust_verify.py` | 94 | 84% | 85% | PASS |
| `commands/validate_story_creation.py` | 197 | 84% | 84% | PASS |

### Top-level

| Module | Stmts | Line% | Branch% | Status |
|---|---:|---:|---:|---|
| `cli.py` | 122 | 70% | — | BELOW-LINE (−5; no branch floor) |
| `__main__.py` | 3 | 0% | 0% | n/a (entrypoint, not in floors) |

## Modules below floor (the punch list)

Severity rubric: ≥10 pp below floor line% = SHOULD; integrity-critical `audit.py`/`atomic_io.py` would be MUST — both currently PASS, so no MUST findings from coverage alone.

1. `commands/agent_config_cmd.py` — line 8% vs 75% floor (−67 pp). **SHOULD-high.**
2. `commands/basic.py` — line 45% vs 75% (−30 pp). **SHOULD.**
3. `core/common.py` — line 58% vs 80% (−22 pp). **SHOULD.**
4. `core/tmux_runtime.py` — line 62% vs 80% (−18 pp). **SHOULD.**
5. `commands/tmux.py` — line 62% vs 75% (−13 pp). **SHOULD.**
6. `commands/orchestrator.py` — line 65% vs 75% (−10 pp). **SHOULD (borderline).**
7. `cli.py` — line 70% vs 75% (−5 pp). nice-to-have.
8. `core/epic_parser.py` — line 75% vs 80% (−5 pp). nice-to-have.
9. `core/utils.py` — line 79% vs 80% (−1 pp). within noise.

## Hypothesis property-test coverage on parsers

Target list from the prompt vs. observed tests:

| Target | Strategy expected in | Found? |
|---|---|---|
| `telemetry_events.parse_event` round-trip incl. `\n \r \t \x00`, surrogates, NFC/NFKC, 4-byte UTF-8 | `tests/test_telemetry_events.py` | **NO** — only enumerated literal cases (lines ~456–611) |
| `core/atomic_io` two-process state machine `{acquire, release, heartbeat, crash, reclaim, foreign_host, pid_recycle}` | `tests/test_atomic_io.py` / `tests/test_state_atomic_integration.py` | **NO** — only example-based concurrency tests |
| `audit.append` / `verify` state machine over append + verify + truncate + splice | `tests/test_audit_append.py` / `tests/test_audit_verify.py` | **NO** — only example-based mutation tests |
| `frontmatter.parse` malformed YAML/Markdown (billion-laughs, alias bombs, BOM, CRLF mix, duplicate keys) | `tests/test_frontmatter.py` | **NO** — only example-based malformed lines |
| `epic_parser.parse` idempotent serialize-parse-serialize | `tests/test_epic_parser.py` | **NO** — only example-based parse tests |

All five target parsers lack hypothesis strategies. The two integrity-critical ones (`atomic_io` and `audit`) lacking RuleBasedStateMachine tests = **SHOULD-high** per rubric.
