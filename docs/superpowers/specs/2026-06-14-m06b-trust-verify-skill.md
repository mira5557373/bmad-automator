# M06b — Trust-but-verify BMAD skill wiring

## Context

M06a delivered the three Python verification layers (`core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`) but left the BMAD skill markdown unwired. M06b lands the operator-facing surface that chains these layers into the review step of the bmad-automator orchestrator. The work is documentation and step-markdown only — there are no new Python modules, no algorithmic changes, and no edits to shipped behaviour beyond inserting the chain into the existing review step. The deliverables are a new SKILL bundle at `skills/trust-but-verify/SKILL.md` describing how the orchestrator invokes Layer 1 → Layer 2 → Layer 3 in order, plus a new step file at `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md` that runs the three layers between section B (Dev Story) and section D (Code Review Loop) of the existing flow, and an inline edit to the existing `step-03a-execute-review.md` to call the new step file as part of the review preflight. M06b consumes M06a as a typed Python API and produces no Python output of its own; the verification result flows through stdout JSON into the orchestrator skill, which makes a pass-or-block decision based on the highest-severity layer outcome.

## Out of scope

M06b does not introduce new Python modules, does not modify `core/gap_validator.py` or any Layer 2/3 module, and does not change the wire format that those modules emit. It does not touch the orchestrator Python plumbing under `commands/orchestrator.py`. It does not gate budget evaluation (that belongs to M03), does not modify the audit chain (M04), and does not change failure triage rules (M07). The skill bundle wiring is documentation-and-markdown only; the actual subprocess invocation of Layer 2's `claude -p` call remains owned by Layer 2 and is not duplicated in M06b. M06b also does not add new event types to the M01 telemetry schema, does not modify the M02 emitter, and does not introduce any new dependencies beyond what M06a already declares.

## Functional requirements

1. REQ-01 a new SKILL bundle directory must exist at `skills/trust-but-verify/` with a single file `SKILL.md` (no other files in the directory) that documents the three-layer trust-but-verify pattern, names each layer by its module path (`core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`), and states the layer invocation order as Layer 1 (gap_validator) → Layer 2 (spec_compliance) → Layer 3 (feature_tester) with no short-circuit on individual layer failure.
2. REQ-02 the SKILL.md must include a level-2 section `## Trigger` declaring exactly the four trigger conditions: explicit operator invocation via `/sw-trust-verify`, automatic invocation during the review preflight of step-03a, completion of a Dev Story phase, and operator request via the orchestrator menu.
3. REQ-03 the SKILL.md must include a level-2 section `## Pre-conditions` enumerating exactly four pre-conditions: a story file exists at the BMAD project root, a review skill has emitted a structured gap list at `.claude/trust-verify-input/gaps.json`, a spec file is referenced by the current story, and the git working tree is clean except for the changes under review.
4. REQ-04 the SKILL.md must include a level-2 section `## Invocation contract` showing the exact CLI invocation pattern using `python -m story_automator.cli trust_verify --gaps .claude/trust-verify-input/gaps.json --spec <spec_path> --diff <diff_path>` with no additional flags beyond what M06a's modules accept.
5. REQ-05 the SKILL.md must include a level-2 section `## Output contract` specifying that the three-layer chain writes a single JSON file to `.claude/trust-verify-output/result.json` with the exact top-level keys `layer1`, `layer2`, `layer3`, `decision`, and `verified_at`, where `decision` is one of the literal strings `pass`, `warn`, or `block`.
6. REQ-06 a new step file must exist at `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md` and must be referenced from the existing `skills/bmad-story-automator/steps-c/step-03a-execute-review.md` via a markdown-link insertion that names the new step file by its repository-relative path.
7. REQ-07 the new step-03ab-spec-compliance.md must include a level-2 section `## When to run` stating the step runs after Dev Story section B completes and before Code Review Loop section D begins, with explicit reference to step-03a-execute-review.md by name.
8. REQ-08 the new step-03ab-spec-compliance.md must include a level-2 section `## What it does` that explains the step invokes the trust-but-verify skill, reads the result.json output, and makes a pass-warn-block decision that gates the transition into section D.
9. REQ-09 the new step-03ab-spec-compliance.md must include a level-2 section `## Failure modes` enumerating exactly five failure modes: Layer 1 reports gaps with confidence below 0.6, Layer 2 emits a `missing` verdict on any spec REQ, Layer 3 reports a created test file under tests/test_compliance_*.py, the chain JSON output is malformed, and the subprocess invocation of Layer 2 exits non-zero.
10. REQ-10 the edit to `step-03a-execute-review.md` must insert exactly one new sentence near the existing review-preflight section that links the new step file by its repository-relative path and must not modify any other content of step-03a-execute-review.md.
11. REQ-11 the SKILL.md and the new step-03ab file together must contain no unresolved four-letter placeholder tokens of the deferred-work family, and must reference no Python modules outside `core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`, and `story_automator.cli`.
12. REQ-12 the SKILL.md and the new step-03ab file together must add fewer than 250 markdown lines to the repository, and the SKILL.md file alone must be at most 180 lines.
13. REQ-13 a sample input fixture must be added at `tests/fixtures/trust_verify_sample_gaps.json` showing the exact JSON shape Layer 1 expects (matching M06a's `parse_gap_list` contract), and a sample output fixture at `tests/fixtures/trust_verify_sample_result.json` showing the exact JSON shape the chain emits to `.claude/trust-verify-output/result.json`.
14. REQ-14 a new test file at `tests/test_trust_verify_skill_format.py` must validate the new SKILL.md against REQ-01 through REQ-05 (section presence, exact section names, trigger count) and the new step-03ab file against REQ-07 through REQ-09; the test must use only the Python standard library plus `unittest.TestCase`.
15. REQ-15 the M06b diff must not modify `core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`, any file under `skills/bmad-story-automator/src/story_automator/core/`, any file under `tests/test_gap_validator.py` / `tests/test_spec_compliance.py` / `tests/test_feature_tester.py`, or `pyproject.toml`.

## Non-functional requirements

- The markdown work must be readable on Windows git-bash, WSL Ubuntu, and Linux CI without line-ending churn; commit with LF line endings under `git config core.autocrlf=input`.
- The new step file and SKILL.md must avoid jargon beyond BMAD, PR, CI, LLM, REQ, and SKILL — no new acronyms.
- All anchor links inside the new markdown files must resolve as GitHub-flavored markdown so the documents render correctly on the fork web view.
- The contributor-guide grep gate documented in CONTRIBUTING.md (the M11 vocabulary contract) must continue to exit zero after M06b lands.
- Every public document statement that asserts a behavioural contract must reference the corresponding REQ id from M06a or M06b so that future readers can trace the source.
- The new test file must execute in under one second on Windows git-bash and WSL Ubuntu and must use no subprocess invocations, no network, and no tmux dependencies.

## Quality gates

- `python -m ruff check tests/test_trust_verify_skill_format.py` reports zero violations.
- `python -m ruff format --check tests/test_trust_verify_skill_format.py` reports zero files needing reformat.
- `python -m unittest tests.test_trust_verify_skill_format` passes with zero failures and zero errors.
- A grep for unresolved four-letter placeholder tokens across `skills/trust-but-verify/SKILL.md`, `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md`, `tests/fixtures/trust_verify_sample_gaps.json`, and `tests/fixtures/trust_verify_sample_result.json` returns no matches.
- The M06a Python quality gates (ruff check, ruff format check, unittest test_gap_validator, test_spec_compliance, test_feature_tester) all continue to exit zero with no regressions caused by the M06b documentation diff.
- The M11 contributor-guide vocabulary gate continues to exit zero.
- `wc -l skills/trust-but-verify/SKILL.md` reports at most 180 lines; the combined line count across all markdown files modified by M06b is at most 250 added lines.
