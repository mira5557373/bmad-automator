---
name: 'step-03ab-spec-compliance'
description: 'Trust-but-verify spec-compliance gate between Dev Story and Code Review Loop'
nextStep: './step-03a-execute-review.md'
---

# Step 3ab: Spec-Compliance Gate

**Goal:** Run the trust-but-verify chain to verify Dev Story output against the spec before the Code Review Loop begins.
**Interaction mode:** Deterministic autonomous execution.

---

## When to run

This step runs after Dev Story section B completes and before Code Review Loop section D begins. The orchestrator's `step-03a-execute-review.md` invokes this step at its review preflight (M06b REQ-07). The chain emits a pass/warn/block decision that gates the transition from automate (section C) into section D.

## What it does

The step invokes the trust-but-verify skill (see `skills/trust-but-verify/SKILL.md`), which chains the three M06a layers in order. The chain writes its output to `.claude/trust-verify-output/result.json` with the top-level keys documented in the SKILL.md Output contract section. The step reads `result.json` and applies the chain's `decision` literal — `pass`, `warn`, or `block` — to gate the orchestrator's transition into section D (M06b REQ-08): `pass` proceeds, `warn` proceeds with a non-blocking notice surfaced in the orchestration log, and `block` halts the run before the first review cycle.

## Failure modes

The chain surfaces exactly five operator-visible failure modes (M06b REQ-09):

1. **Layer 1 low confidence.** `core/gap_validator.py` reports gaps whose `overall_confidence` falls below 0.6. The chain marks the decision `warn` and surfaces every low-confidence status in the report so the operator can triage.
2. **Layer 2 missing verdict.** `core/spec_compliance.py` emits a `missing` verdict on any spec REQ id. The chain marks the decision `block` and names every missing REQ id.
3. **Layer 3 created test.** `core/feature_tester.py` reports a `created_test_path` under `tests/test_compliance_*.py`. The chain marks the decision `warn` and includes the created path so the operator can review the scaffold before merge.
4. **Malformed JSON output.** The chain's `result.json` cannot be parsed as JSON, or is missing one of the documented top-level keys. The step exits non-zero and the orchestrator halts at the preflight without entering section D.
5. **Layer 2 subprocess non-zero exit.** The subprocess invocation of Layer 2's `claude -p` call exits non-zero. The chain marks the decision `block` and propagates the subprocess exit code so the operator can triage the upstream invocation.

---

## Then
→ Return control to `./step-03a-execute-review.md` section D.
