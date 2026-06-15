---
name: trust-but-verify
description: Three-layer verification chain (gap → spec compliance → feature tests) for the BMAD review preflight.
---

# Trust-but-verify

This skill chains the three M06a Python verification layers — `core/gap_validator.py` (Layer 1), `core/spec_compliance.py` (Layer 2), and `core/feature_tester.py` (Layer 3) — into a single pass/warn/block decision for the bmad-story-automator orchestrator (M06b REQ-01).

The chain runs Layer 1 → Layer 2 → Layer 3 in order. No layer short-circuits on individual failure; the chain captures every layer's report and the highest-severity outcome drives the decision.

## Trigger

The chain is invoked under exactly four conditions (M06b REQ-02):

1. Explicit operator invocation via `/sw-trust-verify`.
2. Automatic invocation during the review preflight of step-03a in the bmad-story-automator orchestrator.
3. Completion of a Dev Story phase (section B of the orchestration flow).
4. Operator request via the orchestrator menu.

## Pre-conditions

The chain refuses to run unless all four hold (M06b REQ-03):

1. A story file exists at the BMAD project root.
2. The review skill has emitted a structured gap list at `.claude/trust-verify-input/gaps.json`.
3. A spec file is referenced by the current story.
4. The git working tree is clean except for the changes under review.

## Invocation contract

The orchestrator invokes the chain through `story_automator.cli` (M06b REQ-04):

```bash
python -m story_automator.cli trust_verify --gaps .claude/trust-verify-input/gaps.json --spec <spec_path> --diff <diff_path>
```

No additional CLI flags are accepted; `--gaps`, `--spec`, and `--diff` propagate one-to-one into the layer modules `core/gap_validator.py`, `core/spec_compliance.py`, and `core/feature_tester.py`.

## Output contract

The chain writes a single JSON file to `.claude/trust-verify-output/result.json` with exactly five top-level keys (M06b REQ-05):

| Key | Source | Shape |
|---|---|---|
| `layer1` | `core/gap_validator.py` ValidationReport | object with `statuses`, `overall_confidence`, `validated_at` |
| `layer2` | `core/spec_compliance.py` ComplianceReport | object with `verdicts`, `spec_path`, `diff_sha`, `model_invocation_ms` |
| `layer3` | `core/feature_tester.py` list of TestPlanEntry | list of objects with `req_id`, `existing_test_path`, `created_test_path`, `action` |
| `decision` | chain runner | one of the literal strings `pass`, `warn`, or `block` |
| `verified_at` | chain runner | ISO-8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) |

The `decision` field is the operator-visible verdict: `pass` proceeds into Code Review Loop section D; `warn` proceeds but logs a non-blocking notice; `block` halts the orchestrator before the review cycle begins. See `tests/fixtures/trust_verify_sample_result.json` for a reference payload.
