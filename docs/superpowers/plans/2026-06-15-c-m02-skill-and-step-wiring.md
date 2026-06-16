# M06b c-m02 — Skill and Step Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the operator-facing markdown surface of M06b — the `skills/trust-but-verify/SKILL.md` bundle, the new `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md` step, and a one-sentence insertion into the existing `step-03a-execute-review.md` that links the new step from the review preflight.

**Architecture:** This sub-milestone is the **green phase** of the M06b outer TDD wedge. The c-m01 milestone shipped a format-test file (`tests/test_trust_verify_skill_format.py`) whose REQ-01..REQ-05 and REQ-07..REQ-09 classes currently call `self.skipTest(...)` because the SKILL.md and step-03ab markdown files do not exist yet. c-m02 creates those files; each task ends with the corresponding skipped tests turning into PASS. **No Python source changes**, no edits to `core/*`, no new dependencies — only markdown files are added or modified (REQ-15).

**Tech Stack:**
- Markdown (GitHub-flavored), LF line endings, UTF-8 with trailing newline
- ruff (lint/format — only relevant if any Python file changes; this milestone touches none)
- stdlib unittest for the c-m01 format gate
- Conventional Commits with `Generated-By: claude-opus-4-7` trailer

**Spec:** `docs/superpowers/specs/2026-06-14-m06b-trust-verify-skill.md` — REQ-01..REQ-12, REQ-15, plus the Non-functional and Quality-gate sections.

**Pre-flight note for the engineer:**
- `git status` may show `D .claude/.gap-report.json` and `M README.md` from the prior phase. **Do not** sweep those into c-m02 commits — they belong to the orchestrator's transient state. Use explicit per-file `git add` paths (already pinned in every commit step below).
- All commits must use LF line endings. On Windows git-bash this requires `git config core.autocrlf=input` in the worktree. Verify with `git config --get core.autocrlf` (expect `input` or empty + a `.gitattributes` rule).
- The `skills/trust-but-verify/` directory does **not** yet exist; Task 1 creates it.

**Out of scope (defer to c-m03 or later):**
- Wiring `trust_verify` as a subcommand in `story_automator.cli` (Python work — separate milestone).
- Modifying any file under `skills/bmad-story-automator/src/story_automator/core/`.
- Modifying `core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`, `pyproject.toml`, or any M06a test file (REQ-15).
- Adding new event types or emitter wiring.
- Any change to `tests/fixtures/trust_verify_sample_*.json` or `tests/test_trust_verify_skill_format.py` — those landed in c-m01 and are now read-only contracts.

---

## File Structure

| Path | Role | Created/Modified |
|---|---|---|
| `skills/trust-but-verify/SKILL.md` | Skill bundle documenting the three-layer chain (REQ-01..REQ-05) | **Create** |
| `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md` | New step file gating Dev Story B → Code Review D (REQ-06..REQ-09) | **Create** |
| `skills/bmad-story-automator/steps-c/step-03a-execute-review.md` | One-sentence insertion linking step-03ab from the review preflight (REQ-06, REQ-10) | **Modify** |

No other files are touched. Quality-gate tasks at the end verify line-count, placeholder-grep, and the unittest run.

---

## Conventions Reminder

- Markdown headings use `## Title` (level-2) exactly as the c-m01 test regexes expect: `^## Trigger$`, `^## Pre-conditions$`, `^## Invocation contract$`, `^## Output contract$` for SKILL.md and `^## When to run$`, `^## What it does$`, `^## Failure modes$` for step-03ab. No trailing punctuation, no extra spaces.
- Avoid four-uppercase-letter double-braced placeholder tokens (`{{TODO}}`, `{{FIXME}}`, etc.); the placeholder grep gate in Task 9 rejects them (REQ-11).
- Python module references must stay within the four allowed identifiers: `core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`, and `story_automator.cli` (REQ-11).
- Existing files in `steps-c/` use single-quoted frontmatter (`name: 'step-03a-execute-review'`). Match that exact style in the new step file.
- Per-task commit. Conventional Commits. Add `Generated-By: claude-opus-4-7` trailer.
- Commit example: `git commit --trailer "Generated-By: claude-opus-4-7" -m "..."`.

---

## Task 1: Create `skills/trust-but-verify/SKILL.md`

**Files:**
- Create: `skills/trust-but-verify/SKILL.md`

**Why:** REQ-01..REQ-05 — a single-file SKILL bundle that names the three M06a Python modules by their `core/...` paths, declares Layer 1 → Layer 2 → Layer 3 order, and includes the four level-2 sections `## Trigger`, `## Pre-conditions`, `## Invocation contract`, `## Output contract`. The c-m01 format tests for these REQs currently skip; this task turns them all into PASS.

- [ ] **Step 1: Create the SKILL bundle directory**

```bash
mkdir -p skills/trust-but-verify
```

Expected: directory exists; `ls skills/trust-but-verify` prints nothing (empty).

- [ ] **Step 2: Write `skills/trust-but-verify/SKILL.md`**

Save the following content **exactly** (UTF-8, LF line endings, trailing newline):

````markdown
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
````

(End of `SKILL.md` content. The fenced code blocks above use four-backtick fences so the three-backtick fence around the `python -m story_automator.cli trust_verify ...` line is preserved verbatim when this plan is read.)

- [ ] **Step 3: Run the format tests — REQ-01..REQ-05 classes turn green**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest \
  tests.test_trust_verify_skill_format.SkillMdReq01Tests \
  tests.test_trust_verify_skill_format.SkillMdReq02Tests \
  tests.test_trust_verify_skill_format.SkillMdReq03Tests \
  tests.test_trust_verify_skill_format.SkillMdReq04Tests \
  tests.test_trust_verify_skill_format.SkillMdReq05Tests \
  -v
```

Expected: **14 tests, all PASS, zero skipped, zero failures, zero errors** (Req01: 3, Req02: 2, Req03: 2, Req04: 3, Req05: 4 = 14).

If any test fails:
- "missing layer module path" → check the three `core/*.py` strings are spelled exactly as `core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`.
- "Layer 2 must appear after Layer 1" → re-order the Layer mentions; the first occurrence is what `str.find` returns.
- "## Trigger heading missing" → the `^## Trigger\s*$` regex is anchored at line boundaries; verify no trailing whitespace and no level-3 (`###`) substitution.
- "no unexpected CLI flag" → the line beginning `python -m story_automator.cli trust_verify` must contain only `--gaps`, `--spec`, `--diff`; remove any other long flag from that line.

- [ ] **Step 4: Confirm directory contains exactly `SKILL.md`**

```bash
ls -A skills/trust-but-verify
```

Expected: a single line: `SKILL.md`. (REQ-01 requires no other files; this also satisfies `test_skill_dir_contains_only_skill_md`.)

- [ ] **Step 5: Commit**

```bash
git add skills/trust-but-verify/SKILL.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m06b): add trust-but-verify SKILL.md bundle (REQ-01..REQ-05)"
```

---

## Task 2: Create `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md`

**Files:**
- Create: `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md`

**Why:** REQ-06..REQ-09 — the new step file gates the transition from Dev Story section B into Code Review Loop section D. It must include the three level-2 sections `## When to run`, `## What it does`, and `## Failure modes`, and the Failure modes section must enumerate exactly the five documented modes (Layer 1 confidence < 0.6; Layer 2 `missing` verdict; Layer 3 created test under `tests/test_compliance_*.py`; malformed JSON; Layer 2 subprocess non-zero exit). The c-m01 Step03abReq07/08/09 tests turn from SKIPPED to PASS after this task.

- [ ] **Step 1: Write `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md`**

Save the following content **exactly** (UTF-8, LF line endings, trailing newline):

```markdown
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
```

- [ ] **Step 2: Run the step-03ab format tests — REQ-07..REQ-09 turn green**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest \
  tests.test_trust_verify_skill_format.Step03abReq07Tests \
  tests.test_trust_verify_skill_format.Step03abReq08Tests \
  tests.test_trust_verify_skill_format.Step03abReq09Tests \
  -v
```

Expected: **10 tests, all PASS, zero skipped, zero failures, zero errors** (Req07: 2, Req08: 2, Req09: 6 = 10).

If a Failure-modes test fails:
- "Layer 1" + "0.6" → both literal substrings must appear (the 0.6 threshold from REQ-09 is pinned by the spec).
- "Layer 3" + "tests/test_compliance_" → the literal `tests/test_compliance_` substring must appear; do not abbreviate to `test_compliance_` alone.
- `(?i)non[- ]?zero` → spell it `non-zero` (with hyphen); `nonzero` also matches but `non zero` only matches with a single space.
- `(?i)malformed` → use the word `malformed` somewhere in the Failure modes section.

- [ ] **Step 3: Commit**

```bash
git add skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m06b): add step-03ab-spec-compliance step (REQ-06..REQ-09)"
```

---

## Task 3: Insert the review-preflight link into `step-03a-execute-review.md`

**Files:**
- Modify: `skills/bmad-story-automator/steps-c/step-03a-execute-review.md` (insert one sentence)

**Why:** REQ-06 + REQ-10 — exactly one new sentence near the existing review-preflight section that links the new step file by its repository-relative path. The c-m01 test file does **not** test this insertion directly (the REQ-10 single-sentence constraint is verified by the line-count and diff-bounds gates in Tasks 4 and 6 below). REQ-10 explicitly says "must not modify any other content of step-03a-execute-review.md" — so the edit is a single insertion, not a rewrite.

- [ ] **Step 1: Identify the insertion point**

Open `skills/bmad-story-automator/steps-c/step-03a-execute-review.md` and locate the line that begins `### D. Code Review Loop`. The next non-blank line is:

```
**See `{reviewLoop}` for complete script-based review cycle with v2.3 per-task agent configuration.**
```

The insertion goes **immediately before** that `**See ...**` line. This places the link at the head of section D, where the review preflight begins.

- [ ] **Step 2: Insert exactly one sentence (one bolded line with a markdown link)**

Use Edit (or hand-edit) to add this sentence as the first line of section D, immediately after the `### D. Code Review Loop` heading and one blank line:

Before:
```
### D. Code Review Loop

**See `{reviewLoop}` for complete script-based review cycle with v2.3 per-task agent configuration.**
```

After:
```
### D. Code Review Loop

**Review preflight:** Before this section runs, execute the spec-compliance gate at [`skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md`](./step-03ab-spec-compliance.md) and proceed only if the chain's `decision` literal is `pass` or `warn` (M06b REQ-06, REQ-10).

**See `{reviewLoop}` for complete script-based review cycle with v2.3 per-task agent configuration.**
```

That is **one** new sentence (the `**Review preflight:** ...` line) plus the blank line that visually separates it from the existing `**See ...**` line. No other characters in the file change.

- [ ] **Step 3: Verify exactly one sentence was added and the link uses the repository-relative path**

```bash
git diff -- skills/bmad-story-automator/steps-c/step-03a-execute-review.md
```

Expected diff: exactly one `+`-prefixed sentence containing both the repo-relative path string `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md` and the markdown link to `./step-03ab-spec-compliance.md`, plus one blank-line `+`. Zero lines removed. If the diff shows any other change, revert with `git checkout -- skills/bmad-story-automator/steps-c/step-03a-execute-review.md` and re-do the edit.

Sanity check the added-line count:

```bash
git diff --numstat -- skills/bmad-story-automator/steps-c/step-03a-execute-review.md
```

Expected: `2\t0\tskills/bmad-story-automator/steps-c/step-03a-execute-review.md` (2 added — the sentence and the blank line; 0 removed).

- [ ] **Step 4: Re-run the full c-m01 format test module to confirm nothing regressed**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format -v
```

Expected: **35 tests, all PASS, zero skipped, zero failures, zero errors** (11 fixture + 14 SKILL.md + 10 step-03ab = 35). Compare against the c-m01 baseline of 11 PASS + 24 SKIPPED.

- [ ] **Step 5: Commit**

```bash
git add skills/bmad-story-automator/steps-c/step-03a-execute-review.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m06b): link step-03ab from step-03a review preflight (REQ-06, REQ-10)"
```

---

## Task 4: REQ-12 line-count gate — SKILL.md ≤ 180, total M06b markdown ≤ 250 added

**Files:**
- No edits. Verification only.

**Why:** REQ-12 — SKILL.md is at most 180 lines; the combined line count across **all markdown files modified by M06b** (this milestone's two new files plus the one-sentence insertion into step-03a) is at most 250 added lines.

- [ ] **Step 1: Check SKILL.md line count**

```bash
wc -l skills/trust-but-verify/SKILL.md
```

Expected: `<= 180 skills/trust-but-verify/SKILL.md` (the file as written in Task 1 is ~50 lines).

If the count exceeds 180, trim from the bottom of the Output contract section first (the table can be condensed to a key-only list if needed) — never delete a required keyword (every needle the c-m01 tests check for must remain).

- [ ] **Step 2: Check combined M06b markdown line-add count**

The M06b markdown surface is the diff against the milestone's base — `main`. Sum added lines across the three markdown files in the M06b touch list:

```bash
git diff --numstat main -- \
  skills/trust-but-verify/SKILL.md \
  skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md \
  skills/bmad-story-automator/steps-c/step-03a-execute-review.md \
  | awk 'BEGIN{a=0;d=0} {a+=$1; d+=$2} END{printf "added=%d removed=%d\n", a, d}'
```

Expected: `added=<=250 removed=<=5`. (The `step-03a-execute-review.md` insertion removes zero lines; the two new files contribute their full line count as additions.)

If `added` exceeds 250, trim the SKILL.md Output-contract table or shorten the Failure-modes prose in step-03ab, preserving every test needle (re-run Task 1 Step 3 and Task 2 Step 2 after any trim).

- [ ] **Step 3: No commit needed — verification only.**

---

## Task 5: REQ-11 placeholder grep gate

**Files:**
- No edits. Verification only.

**Why:** REQ-11 — the SKILL.md and step-03ab together must contain no unresolved four-letter placeholder tokens of the deferred-work family and must reference no Python module outside the allowed set. The grep gate matches the c-m01 style.

- [ ] **Step 1: Four-letter double-braced placeholder grep (spec quality-gate exact file list)**

The spec quality-gate language pins the grep to four files: SKILL.md, step-03ab, and the two fixtures created in c-m01. Include all four for defense in depth even though the fixtures already passed in c-m01.

```bash
grep -nE '\{\{[A-Z]{4}\}\}' \
  skills/trust-but-verify/SKILL.md \
  skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md \
  tests/fixtures/trust_verify_sample_gaps.json \
  tests/fixtures/trust_verify_sample_result.json \
  && echo "FAIL: placeholder tokens found" \
  || echo "ok: no placeholder tokens"
```

Expected: `ok: no placeholder tokens`. If the gate fires, replace the offending `{{XXXX}}` token with the resolved value (or remove the line entirely).

- [ ] **Step 2: Python-module reference allowlist grep**

```bash
grep -nE 'story_automator\.[a-z_]+|core/[a-z_]+\.py' \
  skills/trust-but-verify/SKILL.md \
  skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md \
  | grep -vE 'core/gap_validator\.py|core/spec_compliance\.py|core/feature_tester\.py|story_automator\.cli' \
  && echo "FAIL: forbidden module reference" \
  || echo "ok: only allowed modules referenced"
```

Expected: `ok: only allowed modules referenced`. If a forbidden module is referenced (e.g., `story_automator.commands.orchestrator`), either drop the reference or replace it with an allowed module path; do not loosen the allowlist.

- [ ] **Step 3: M11 contributor-guide vocabulary gate (defensive check)**

The Non-functional requirements reference an M11 vocabulary contract documented in `CONTRIBUTING.md`. As of c-m02, M11 has not yet shipped that gate — `grep -nE "vocabulary|forbidden|grep gate" CONTRIBUTING.md` returns no matches. If M11 has landed by execution time, the gate appears as an explicit shell snippet in `CONTRIBUTING.md`; run it. Otherwise, log that M11 is not yet shipped and continue.

```bash
if grep -qE "vocabulary|grep gate" CONTRIBUTING.md 2>/dev/null; then
  echo "M11 gate present; run the snippet documented in CONTRIBUTING.md"
else
  echo "ok: M11 vocabulary gate not yet documented (deferred to milestone M11)"
fi
```

Expected: prints either `ok: M11 vocabulary gate not yet documented...` (today's state) or, post-M11, the gate's own zero-exit signal.

- [ ] **Step 4: No commit needed — verification only.**

---

## Task 6: REQ-15 read-only-files gate

**Files:**
- No edits. Verification only.

**Why:** REQ-15 — the M06b diff must not modify `core/gap_validator.py`, `core/spec_compliance.py`, `core/feature_tester.py`, any file under `skills/bmad-story-automator/src/story_automator/core/`, the M06a test files (`tests/test_gap_validator.py`, `tests/test_spec_compliance.py`, `tests/test_feature_tester.py`), or `pyproject.toml`.

- [ ] **Step 1: Diff against `main` for the read-only set and assert empty**

```bash
git diff --name-only main -- \
  skills/bmad-story-automator/src/story_automator/core/ \
  tests/test_gap_validator.py \
  tests/test_spec_compliance.py \
  tests/test_feature_tester.py \
  skills/bmad-story-automator/pyproject.toml \
  pyproject.toml
```

Expected: empty output (no files listed). If any path appears, revert that file with `git checkout main -- <path>` and re-run all prior tasks' verifications.

- [ ] **Step 2: No commit needed — verification only.**

---

## Task 7: Full regression run — no M06a or unrelated test breakage

**Files:**
- No edits. Verification only.

**Why:** Quality-gate section of the spec — the M06a Python quality gates must continue to exit zero with no regressions caused by the M06b documentation diff. Re-run M06a's three test files plus the trust-verify format test module, plus a representative sample of the unrelated existing tests.

- [ ] **Step 1: Re-run M06a tests**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest \
  tests.test_gap_validator \
  tests.test_spec_compliance \
  tests.test_feature_tester \
  -v
```

Expected: all pass, zero failures, zero errors.

- [ ] **Step 2: Re-run the full c-m01 format test module**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_trust_verify_skill_format -v
```

Expected: **35 tests, all PASS, zero skipped, zero failures, zero errors**. Wall time under 1 second (REQ non-functional).

- [ ] **Step 3: Run the full discovered test suite (catch any indirect regression)**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests
```

Expected: zero failures, zero errors. (Skips from platform-gated test modules are acceptable.)

- [ ] **Step 4: No commit needed — verification only.**

---

## Task 8: Final sanity sweep and milestone status

**Files:**
- No edits. Verification only.

**Why:** Confirm the working tree is clean (other than the orchestrator's transient `.claude/.gap-report.json` deletion and the `README.md` modification noted in the pre-flight), the commits are in order, and the milestone is ready for code review.

- [ ] **Step 1: `git status --short`**

```bash
git status --short
```

Expected: at most the two pre-existing entries (`D .claude/.gap-report.json`, ` M README.md`) — no new modified/untracked files attributable to c-m02.

- [ ] **Step 2: `git log` confirms the three c-m02 commits**

```bash
git log --oneline -n 5
```

Expected: the top three commits are (in order, newest first) `feat(m06b): link step-03ab from step-03a review preflight (REQ-06, REQ-10)`, `feat(m06b): add step-03ab-spec-compliance step (REQ-06..REQ-09)`, `feat(m06b): add trust-but-verify SKILL.md bundle (REQ-01..REQ-05)`.

- [ ] **Step 3: REQ-12 final check (defense in depth)**

```bash
wc -l skills/trust-but-verify/SKILL.md \
       skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md
```

Expected: both under 100 lines individually; combined under 200 lines (well inside REQ-12's 180 / 250 bounds).

- [ ] **Step 4: Done — c-m02 complete.**

The milestone is complete when:
- All 35 tests in `tests/test_trust_verify_skill_format.py` PASS (no skips).
- The M06a test files continue to pass.
- REQ-11, REQ-12, REQ-15 gates exit zero (Tasks 4, 5, 6).
- The working tree shows only the three c-m02 commits beyond `main`.

---

## Self-Review Checklist (run after writing this plan, before execution)

- [x] REQ-01 (SKILL bundle directory, single file, three module paths, L1→L2→L3 order) → Task 1.
- [x] REQ-02 (`## Trigger` section with four conditions) → Task 1, Step 2 content.
- [x] REQ-03 (`## Pre-conditions` section with four items) → Task 1, Step 2 content.
- [x] REQ-04 (`## Invocation contract` with exact CLI pattern) → Task 1, Step 2 content.
- [x] REQ-05 (`## Output contract` with five keys + three decision literals) → Task 1, Step 2 content.
- [x] REQ-06 (step-03ab created + referenced from step-03a via repo-relative path) → Tasks 2 + 3.
- [x] REQ-07 (`## When to run` referencing section B, section D, step-03a-execute-review.md) → Task 2, Step 1 content.
- [x] REQ-08 (`## What it does` mentioning trust-but-verify, result.json, pass/warn/block, section D) → Task 2, Step 1 content.
- [x] REQ-09 (`## Failure modes` enumerating exactly five modes including the literal substrings `Layer 1` + `0.6`, `Layer 2` + `missing`, `Layer 3` + `tests/test_compliance_`, `malformed`, `non-zero`) → Task 2, Step 1 content.
- [x] REQ-10 (single sentence insertion into step-03a, no other content modified) → Task 3.
- [x] REQ-11 (no four-letter placeholder tokens; no Python modules outside the allowed set) → Task 5.
- [x] REQ-12 (SKILL.md ≤ 180 lines, total ≤ 250 added) → Task 4.
- [x] REQ-15 (M06b diff does not touch the read-only file set) → Task 6.
- [x] Quality gates (M06a regression, format-test full PASS, full discovery pass) → Task 7.
- [x] Non-functional (LF line endings, no new acronyms, GFM-friendly links, REQ ids cited in body text) → Tasks 1 and 2 content references REQ ids; LF noted in pre-flight.
- [x] Non-functional M11 vocabulary contract → defensive gate in Task 5 Step 3 (today the gate is not yet documented; gate is conditional on M11 having shipped).
- [x] REQ-13 / REQ-14 → covered in c-m01 (fixtures and format-test module already landed); c-m02 only consumes them via Tasks 1, 2, 3, 7 verification steps.
- [x] No placeholders, no `TBD`, no "implement later". Every step shows the exact content or exact command.
- [x] Conventional Commits with `Generated-By: claude-opus-4-7` trailer on every commit step.
- [x] Type identifiers and file paths consistent across tasks: `skills/trust-but-verify/SKILL.md`, `skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md`, `skills/bmad-story-automator/steps-c/step-03a-execute-review.md` are spelled identically wherever they appear.
