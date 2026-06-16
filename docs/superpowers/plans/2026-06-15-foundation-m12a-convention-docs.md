# M12a — Retraction Convention Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the M12 retraction-as-changelog convention as new contributor-facing prose in `CONTRIBUTING.md`, covering REQ-01..REQ-08 and REQ-12..REQ-13 from `docs/superpowers/specs/2026-06-14-m12-retraction-convention.md`, while keeping the M11 vocabulary gate green.

**Architecture:** Pure documentation milestone — a single new `## Retractions` section is appended to `CONTRIBUTING.md` immediately after the existing `## Changelog Scope Tags` section, plus one `docs/changelog/260615.md` entry recording the milestone. No Python sources, no test files, no script changes. Verification is done with ad-hoc grep assertions plus the existing `scripts/m11-vocabulary-gates.sh` portable gate. The verifier script (REQ-10), gate documentation (REQ-11), and the in-tree worked retraction landing in a historical entry (REQ-09) are explicitly deferred to a follow-up sub-milestone M12b — this plan must NOT add `scripts/verify_retraction_format.py`, must NOT add `tests/test_retraction_format.py`, and must NOT touch any file under `docs/changelog/2604*.md` or `docs/changelog/2605*.md`.

**Tech Stack:** Markdown (GitHub-flavored), POSIX `sh` for the M11 portable gate, `git`, `grep`, `wc`. No Python, no Node, no new dependencies.

---

## Spec mapping

| Req | Where landed | How verified |
|-----|--------------|--------------|
| REQ-01 | `CONTRIBUTING.md` — new level-2 heading `## Retractions` immediately after `## Changelog Scope Tags`, body ≥ 3 paragraphs covering purpose / syntax / timing | Task 9 grep assertion |
| REQ-02 | Syntax paragraph — exact form `- [YYYY-MM-DD] Retracted by [YYMMDD#anchor](./YYMMDD.md#anchor): <one-line reason>` | Task 9 grep assertion |
| REQ-03 | Syntax paragraph — explicit "must NOT be modified" clause about original prose/bullets/files/QA | Task 9 grep assertion |
| REQ-04 | Timing paragraph — explicit "nine months" bound | Task 9 grep assertion |
| REQ-05 | Timing paragraph — explicit `Retracts: [YYMMDD#anchor]` reciprocal-link rule | Task 9 grep assertion |
| REQ-06 | Worked example block showing both halves of the round-trip | Task 9 grep assertion |
| REQ-07 | Timing paragraph — explicit incomplete-fix rule (append second bullet, don't replace first) | Task 9 grep assertion |
| REQ-08 | Syntax paragraph — explicit "NOT scope-tagged" clause naming all four M11 tags | Task 9 grep assertion |
| REQ-12 | Section appended only; existing `## Changelog Scope Tags` section is byte-for-byte unchanged | Task 8 — `scripts/m11-vocabulary-gates.sh` exits zero |
| REQ-13 | Timing paragraph — explicit "regardless of which scope tag" clause naming all four M11 tags | Task 9 grep assertion |

**Out of scope (M12b):** REQ-09 (worked retraction landed in a real historical entry), REQ-10 (`scripts/verify_retraction_format.py`), REQ-11 (gate documented with exact invocation in `CONTRIBUTING.md`).

---

### Task 1: Confirm baseline state is clean

**Files:** (read-only checks)

- [ ] **Step 1: Verify the spec exists and matches the requirements this plan covers**

Run:
```sh
test -f docs/superpowers/specs/2026-06-14-m12-retraction-convention.md && echo "spec present"
```
Expected: `spec present`

- [ ] **Step 2: Verify the M11 vocabulary gate exits zero on the starting tree**

Run:
```sh
bash scripts/m11-vocabulary-gates.sh
```
Expected: every line begins with `PASS:`, exit code 0. If any line begins with `FAIL:`, stop and report — the branch is not in a clean state for M12a work.

- [ ] **Step 3: Verify `CONTRIBUTING.md` does NOT already carry a `## Retractions` heading**

Run:
```sh
grep -c '^## Retractions$' CONTRIBUTING.md
```
Expected: `0`. If non-zero, stop — the convention is already partially landed and this plan would double-land it.

- [ ] **Step 4: Verify there is no working-tree drift**

Run:
```sh
git status --porcelain
```
Expected: empty output. If non-empty, stop and resolve.

- [ ] **Step 5: No commit at this step**

Baseline checks only — proceed to Task 2.

---

### Task 2: Author the failing structural assertion script

**Files:**
- Create (scratch only — DO NOT commit): `.m12a-assert.sh`

Per spec NFR "must use only the Python standard library" — this scratch script is bash-only, deleted before Task 12 commits. It is the test-side of TDD for this docs milestone: every requirement becomes a `grep -F` or `grep -E` assertion. Writing all assertions first, watching them fail, then landing the prose, then watching them pass, mirrors red-green-refactor for prose.

- [ ] **Step 1: Write the scratch assertion script exactly as shown**

Create `.m12a-assert.sh` with this content (and only this content):

```sh
#!/bin/sh
set -eu
F=CONTRIBUTING.md
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
pass() { printf 'PASS: %s\n' "$1"; }

# REQ-01a — exactly one `## Retractions` heading.
N=$(grep -c '^## Retractions$' "$F")
[ "$N" = "1" ] || fail "REQ-01a heading count: got $N expected 1"
pass "REQ-01a heading present exactly once"

# REQ-01b — `## Retractions` appears AFTER `## Changelog Scope Tags`.
L_VOCAB=$(grep -n '^## Changelog Scope Tags$' "$F" | cut -d: -f1)
L_RETR=$(grep -n '^## Retractions$' "$F" | cut -d: -f1)
[ -n "$L_VOCAB" ] && [ -n "$L_RETR" ] && [ "$L_RETR" -gt "$L_VOCAB" ] \
  || fail "REQ-01b ordering: vocab line=$L_VOCAB retractions line=$L_RETR"
pass "REQ-01b retractions section follows vocabulary section"

# REQ-01c — purpose paragraph marker present (distinctive phrase).
grep -qF 'audit trail' "$F" || fail "REQ-01c purpose-paragraph marker 'audit trail' missing"
pass "REQ-01c purpose-paragraph marker present"

# REQ-01d — at least three prose paragraphs (purpose, syntax, timing) BEFORE the
# `### Worked example` sub-heading. Counted as blank-line-separated text blocks.
PARA_COUNT=$(awk '
  /^## Retractions$/ { in_section=1; next }
  in_section && /^## / { exit }
  in_section && /^### / { exit }
  in_section && NF == 0 { if (in_para) { para++; in_para=0 } }
  in_section && NF > 0 { in_para=1 }
  END { if (in_para) para++; print para+0 }
' "$F")
[ "$PARA_COUNT" -ge 3 ] || fail "REQ-01d paragraph count: got $PARA_COUNT expected >=3"
pass "REQ-01d body paragraph count >=3 ($PARA_COUNT)"

# REQ-02 — exact syntax phrase present verbatim.
grep -qF '- [YYYY-MM-DD] Retracted by [YYMMDD#anchor](./YYMMDD.md#anchor): <one-line reason>' "$F" \
  || fail "REQ-02 exact syntax bullet missing"
pass "REQ-02 exact syntax bullet present"

# REQ-03 — explicit "must NOT be modified" clause.
grep -qE 'must NOT be modified' "$F" \
  || fail "REQ-03 prose-immutability clause missing"
pass "REQ-03 prose-immutability clause present"

# REQ-04 — explicit nine-month bound.
grep -qF 'nine months' "$F" \
  || fail "REQ-04 nine-month bound missing"
pass "REQ-04 nine-month bound present"

# REQ-05 — reciprocal `Retracts:` line rule described.
grep -qE 'Retracts: \[YYMMDD#anchor\]' "$F" \
  || fail "REQ-05 reciprocal Retracts: line rule missing"
pass "REQ-05 reciprocal Retracts: line rule present"

# REQ-06 — worked example contains both halves of the round-trip.
grep -qF '### Retractions' "$F" || fail "REQ-06 worked example: ### Retractions sub-heading missing"
grep -qE '^Retracts: \[2[0-9]{5}#' "$F" || fail "REQ-06 worked example: reciprocal Retracts: line missing"
pass "REQ-06 worked example contains both halves"

# REQ-07 — incomplete-fix rule mentions appending a second bullet.
grep -qE 'incomplete' "$F" || fail "REQ-07 incomplete-fix rule missing 'incomplete'"
grep -qE 'second retraction bullet' "$F" || fail "REQ-07 incomplete-fix rule missing 'second retraction bullet'"
pass "REQ-07 incomplete-fix rule present"

# REQ-08 — explicit no-scope-tag clause naming all four tags.
grep -qE 'NOT scope-tagged' "$F" || fail "REQ-08 missing 'NOT scope-tagged' clause"
for TAG in FULL LITE SKELETON DEFERRED; do
  grep -qF "\`$TAG\`" "$F" || fail "REQ-08/REQ-13 inline-code tag \`$TAG\` missing"
done
pass "REQ-08 no-scope-tag clause present; all four tags appear as inline code"

# REQ-13 — explicit tag-agnostic clause.
grep -qE 'regardless of which scope tag' "$F" || fail "REQ-13 tag-agnostic clause missing"
pass "REQ-13 tag-agnostic clause present"

# NFR — line delta < 200 against origin/main (or main if origin not fetched).
BASE=origin/main
git rev-parse --verify --quiet "$BASE" >/dev/null || BASE=main
if git rev-parse --verify --quiet "$BASE" >/dev/null; then
  ADDED=$(git diff "$BASE"...HEAD -- CONTRIBUTING.md | grep -cE '^\+[^+]' || true)
  [ "$ADDED" -lt 200 ] || fail "NFR line-delta: CONTRIBUTING.md added $ADDED lines (cap 199)"
  pass "NFR line-delta CONTRIBUTING.md added $ADDED lines (<200)"
else
  printf 'SKIP: no main ref — line-delta check skipped\n'
fi

# NFR — no CRLF line endings introduced in CONTRIBUTING.md.
LC_ALL=C grep -q "$(printf '\r')" "$F" && fail "NFR CRLF detected in $F" || true
pass "NFR no CRLF in CONTRIBUTING.md"
```

- [ ] **Step 2: Make the script executable and run it**

Run:
```sh
chmod +x .m12a-assert.sh && ./.m12a-assert.sh
```
Expected: FAIL on the very first assertion (`REQ-01a heading count: got 0 expected 1`) — confirms we are in red.

- [ ] **Step 3: No commit**

This script is scratch — Task 12 deletes it before the final commit. Do NOT `git add` it.

---

### Task 3: Add the `## Retractions` heading and purpose paragraph (REQ-01 purpose)

**Files:**
- Modify: `CONTRIBUTING.md` — append after the existing `## Changelog Scope Tags` section (after the current line 49, just before the `## Reporting Bugs` heading at the current line 51)

- [ ] **Step 1: Confirm the insertion anchor still matches the expected current contents**

Run:
```sh
grep -n '^## Reporting Bugs$' CONTRIBUTING.md
```
Expected: a single match at line 51 (or whatever line the section currently starts at — record the number). If absent, stop — `CONTRIBUTING.md` no longer matches the plan baseline.

- [ ] **Step 2: Insert the heading and the first (purpose) paragraph immediately before `## Reporting Bugs`**

Use your editor to insert the following block immediately above the `## Reporting Bugs` heading, preserving one blank line before and one blank line after the inserted block:

```markdown
## Retractions

When a later release fixes a defect that was originally documented as working in an earlier `docs/changelog/` entry, the earlier entry must be edited in place with a dated forward-link to the fix entry. This preserves the chronological audit trail — no rewriting of history — while surfacing known-bad-then-fixed states to future readers of the older entry. The convention exists so that a contributor opening an older changelog entry to understand past behavior cannot be silently misled by prose that was accurate at the time but became wrong after a later fix landed.
```

- [ ] **Step 3: Re-run the scratch assertion script**

Run:
```sh
./.m12a-assert.sh
```
Expected: `PASS: REQ-01a heading present exactly once`, `PASS: REQ-01b retractions section follows vocabulary section`. Next FAIL is on `REQ-02 exact syntax bullet missing` — confirms forward progress.

- [ ] **Step 4: No commit yet — Task 7 commits the full section as one atomic doc change**

---

### Task 4: Add the syntax paragraph (REQ-02, REQ-03, REQ-08)

**Files:**
- Modify: `CONTRIBUTING.md` — append after the purpose paragraph added in Task 3

- [ ] **Step 1: Insert the following block after the purpose paragraph, separated by one blank line**

````markdown
The retraction is recorded as a new `### Retractions` sub-section appended to the original entry. The original prose body, bullet list, file references, and QA notes of the historical entry must NOT be modified — only the new `### Retractions` sub-heading and its bullets are added. Each bullet uses the exact form:

```text
- [YYYY-MM-DD] Retracted by [YYMMDD#anchor](./YYMMDD.md#anchor): <one-line reason>
```

The date in square brackets is the retraction date (the date the bullet is authored, not the date of the original entry). The link target is a GitHub-flavored-markdown anchor of the form `[YYMMDD#anchor](./YYMMDD.md#anchor)` pointing at the dated fix entry under `docs/changelog/`. Retraction bullets are NOT scope-tagged with the M11 vocabulary: the closed tags `FULL`, `LITE`, `SKELETON`, and `DEFERRED` apply only to top-level dated changelog entry headings, never to retraction bullets.
````

Note the outer fence in this plan uses four backticks so the inner ` ```text ` fence renders intact. Paste only the content between the outer fences (inclusive of the inner ` ```text ` … ` ``` ` fenced code block) into `CONTRIBUTING.md` — do NOT paste the outer four-backtick lines.

- [ ] **Step 2: Re-run the scratch assertion script**

Run:
```sh
./.m12a-assert.sh
```
Expected: REQ-02, REQ-03, REQ-08 (and the four inline-code tag checks) now all PASS. Next FAIL is on `REQ-04 nine-month bound missing`.

- [ ] **Step 3: No commit yet**

---

### Task 5: Add the timing paragraph (REQ-04, REQ-05, REQ-07, REQ-13)

**Files:**
- Modify: `CONTRIBUTING.md` — append after the syntax paragraph added in Task 4

- [ ] **Step 1: Insert the following block after the syntax paragraph, separated by one blank line**

```markdown
Retractions must NEVER be applied to entries that pre-date this convention commit by more than nine months, to bound the audit-and-edit obligation on contributors. The convention applies regardless of which scope tag (`FULL`, `LITE`, `SKELETON`, or `DEFERRED`) the original entry carries; even a `SKELETON` entry can be retracted if the skeleton itself was promised but never landed. The fix entry that triggers a retraction must reciprocally reference the entry it retracts via a `Retracts: [YYMMDD#anchor]` line under the fix entry's `### Notes` block (or under any equivalent metadata block the entry uses). When a fix later turns out to be incomplete, the original retraction bullet stays in place and a second retraction bullet with a new date and a new fix-entry-link is appended below the first — earlier retraction bullets are never deleted, edited, or re-dated.
```

- [ ] **Step 2: Re-run the scratch assertion script**

Run:
```sh
./.m12a-assert.sh
```
Expected: REQ-04, REQ-05, REQ-07, REQ-13 all PASS. Next FAIL is on `REQ-06 worked example: ### Retractions sub-heading missing`.

- [ ] **Step 3: No commit yet**

---

### Task 6: Add the worked example (REQ-06)

**Files:**
- Modify: `CONTRIBUTING.md` — append after the timing paragraph added in Task 5

- [ ] **Step 1: Insert the following block after the timing paragraph, separated by one blank line**

The block uses a four-backtick outer fence so that the inner triple-tilde samples render correctly on GitHub without escaping. Paste only the inner content (everything between the outer ```` ```` ```` ```` lines, exclusive); do NOT paste the outer four-backtick fences themselves into `CONTRIBUTING.md`.

````markdown
### Worked example

Suppose `docs/changelog/260501.md` originally documented a working tmux-runtime feature, and a later entry `docs/changelog/260612.md` fixed a regression in that feature. Both halves of the round-trip look like this.

The modified historical entry (`docs/changelog/260501.md`) gains a `### Retractions` sub-section at the bottom; its original `### Summary`, `### Added`, `### Files`, and `### QA Notes` blocks remain byte-for-byte unchanged:

~~~markdown
## 260501 - [FULL] tmux runtime keepalive

### Summary
…original prose, unchanged…

### Files
…original list, unchanged…

### Retractions
- [2026-06-15] Retracted by [260612#tmux-keepalive-regression-fix](./260612.md#tmux-keepalive-regression-fix): keepalive ping interval regressed in CI; superseded by the fix entry.
~~~

The fix entry (`docs/changelog/260612.md`) records the reciprocal link under `### Notes`:

~~~markdown
## 260612 - [FULL] tmux keepalive regression fix

### Summary
…fix prose…

### Notes
Retracts: [260501#tmux-runtime-keepalive](./260501.md#tmux-runtime-keepalive)
~~~

If the fix later proves incomplete and a second repair lands in `docs/changelog/260801.md`, the historical entry gains a second retraction bullet without disturbing the first:

~~~markdown
### Retractions
- [2026-06-15] Retracted by [260612#tmux-keepalive-regression-fix](./260612.md#tmux-keepalive-regression-fix): keepalive ping interval regressed in CI; superseded by the fix entry.
- [2026-08-01] Retracted by [260801#tmux-keepalive-regression-fix-v2](./260801.md#tmux-keepalive-regression-fix-v2): the earlier fix re-regressed in a second environment; superseded by the second fix entry.
~~~

The example is illustrative — `260501.md`, `260612.md`, and `260801.md` are fictional in this section, and the anchor slugs follow the GitHub-flavored-markdown auto-slug rule (lowercase, spaces replaced by hyphens) for their corresponding heading text. Landing a real retraction in an actual historical entry is handled by the follow-up sub-milestone M12b.
````

- [ ] **Step 2: Re-run the scratch assertion script**

Run:
```sh
./.m12a-assert.sh
```
Expected: every assertion now PASSes, including the `NFR line-delta` and `NFR no CRLF` checks. Total output should be roughly 14 PASS lines, no FAIL lines.

- [ ] **Step 3: No commit yet — Task 7 verifies and Task 8 commits**

---

### Task 7: Verify the M11 vocabulary gate still passes (REQ-12)

**Files:** (read-only checks)

- [ ] **Step 1: Run the full M11 portable gate**

Run:
```sh
bash scripts/m11-vocabulary-gates.sh
```
Expected: every line begins with `PASS:` (or one `SKIP:` line for Gate 6 if the base ref is unreachable), exit code 0. If any line begins with `FAIL:`, stop and report — the new section disturbed the vocabulary contract, which violates REQ-12.

- [ ] **Step 2: Confirm no whitespace hygiene regressions**

Run:
```sh
git diff --check -- CONTRIBUTING.md
```
Expected: empty output, exit code 0.

- [ ] **Step 3: Confirm the existing `## Changelog Scope Tags` section is byte-for-byte unchanged**

Run:
```sh
git diff -- CONTRIBUTING.md | grep -E '^[+-]' | grep -E 'Changelog Scope Tags|## FULL|## LITE|## SKELETON|## DEFERRED' || echo "unchanged"
```
Expected: `unchanged`. The diff must only ADD lines after the vocabulary section, never DELETE or MODIFY any line within it.

- [ ] **Step 4: No commit yet**

---

### Task 8: Verify the contributor-facing prose stays within NFR bounds

**Files:** (read-only checks)

- [ ] **Step 1: Confirm CONTRIBUTING.md line delta is under 200**

Run:
```sh
git diff origin/main -- CONTRIBUTING.md 2>/dev/null \
  | grep -cE '^\+[^+]' \
  || git diff main -- CONTRIBUTING.md | grep -cE '^\+[^+]'
```
Expected: a number strictly less than 200. (Empirically the four blocks above add ~50 lines.)

- [ ] **Step 2: Confirm no new acronyms beyond BMAD / PR / CI / FULL / LITE / SKELETON / DEFERRED**

Run:
```sh
git diff origin/main -- CONTRIBUTING.md 2>/dev/null \
  | grep -E '^\+' \
  | grep -oE '\b[A-Z]{2,}\b' \
  | sort -u
```
Expected: every token in the output is a member of the allowed set `{BMAD, CI, DEFERRED, FULL, LITE, NOT, NEVER, PR, QA, SKELETON, YYMMDD, YYYY}`. `QA`, `YYMMDD`, `YYYY`, `NOT`, `NEVER` are not new acronyms in the NFR-prohibited sense — `QA` is already used elsewhere in `CONTRIBUTING.md` and the broader project, while `NOT`/`NEVER` are uppercase keywords and `YYMMDD`/`YYYY` are placeholder tokens in syntax examples, not domain jargon. If any token outside that allowed set appears (e.g. `WSL`, `GFM`, `TBD`, `FIXME`, `XXX`, `LLM`, `API`, `URL`), stop and rewrite the prose to remove it before proceeding to Task 9.

- [ ] **Step 3: Confirm no four-letter placeholder tokens leaked into the doc**

Run:
```sh
grep -oE '\b(TODO|TBD|FIXME|XXXX)\b' CONTRIBUTING.md || echo "no placeholders"
```
Expected: `no placeholders`.

- [ ] **Step 4: Confirm the four M11 tags still each appear as inline-code somewhere in `CONTRIBUTING.md`**

Run:
```sh
for T in FULL LITE SKELETON DEFERRED; do
  printf '%s ' "$T"
  grep -cF "\`$T\`" CONTRIBUTING.md
done
```
Expected: each line shows a count ≥ 1 (typically 2: once in the M11 vocabulary section, once in the new Retractions section). If any tag shows 0, REQ-08/REQ-13 inline-code expectation is unmet.

- [ ] **Step 5: No commit yet**

---

### Task 9: Final scratch-script run, then delete the scratch script

**Files:**
- Delete: `.m12a-assert.sh`

- [ ] **Step 1: Run the scratch assertion script one last time**

Run:
```sh
./.m12a-assert.sh
```
Expected: all PASS lines, exit code 0.

- [ ] **Step 2: Delete the scratch script**

Run:
```sh
rm .m12a-assert.sh
```

- [ ] **Step 3: Confirm the working tree only carries the intended doc change**

Run:
```sh
git status --porcelain
```
Expected: exactly one line — ` M CONTRIBUTING.md` (modified). No `?? .m12a-assert.sh`, no other files. If the changelog entry from Task 10 is being authored as part of the same commit, the changelog line will appear after Task 10 — that is fine.

---

### Task 10: Add the `docs/changelog/260615.md` milestone entry

**Files:**
- Create: `docs/changelog/260615.md`

The new entry must carry exactly one M11 scope tag on its dated heading. This sub-milestone lands the convention prose but defers the verifier script and the in-tree worked retraction landing — that is `[LITE]` per the M11 vocabulary definition ("implementation and tests but reduced spec depth or deferred non-blocking polish, where every quality gate still passes at merge time").

- [ ] **Step 1: Create `docs/changelog/260615.md` with the following content**

```markdown
# Changelog - 260615

## 260615 - [LITE] M12a retraction convention docs

### Summary
Lands the M12 retraction-as-changelog convention as new contributor-facing prose in `CONTRIBUTING.md`. Covers REQ-01..REQ-08 and REQ-12..REQ-13 from the M12 spec. The verifier script (REQ-10), gate documentation (REQ-11), and the in-tree worked retraction landing in a historical entry (REQ-09) are deferred to a follow-up sub-milestone M12b — this entry is `[LITE]` rather than `[FULL]` for that reason.

### Added
- New `## Retractions` section in `CONTRIBUTING.md`, immediately after `## Changelog Scope Tags`, containing a purpose paragraph, a syntax paragraph, a timing paragraph, and a worked round-trip example.
- The worked example shows both halves of a retraction: the modified historical entry with a `### Retractions` bullet, and the fix entry with a reciprocal `Retracts:` line under `### Notes`.

### Changed
- None — the existing `## Changelog Scope Tags` section is byte-for-byte unchanged. REQ-12 is satisfied by appending after the vocabulary section rather than modifying it.

### Files
- `CONTRIBUTING.md` — new `## Retractions` section appended.
- `docs/changelog/260615.md` — this entry.
- `docs/superpowers/plans/2026-06-15-foundation-m12a-convention-docs.md` — implementation plan.

### QA Notes
- `bash scripts/m11-vocabulary-gates.sh` — every gate PASS, exit 0.
- `git diff --check -- CONTRIBUTING.md` — empty, exit 0.
- Line delta on `CONTRIBUTING.md` is well under the 200-line NFR cap.
- No Python source modules, test modules, telemetry types, scripts, or files under `docs/changelog/2604*.md` / `docs/changelog/2605*.md` were touched, satisfying the docs-only milestone discipline.
```

- [ ] **Step 2: Verify the changelog entry carries the right tag and the M11 gate still passes**

Run:
```sh
grep -E '^## 260615' docs/changelog/260615.md && bash scripts/m11-vocabulary-gates.sh
```
Expected: heading line printed, then every gate PASS.

- [ ] **Step 3: No commit yet — Task 11 stages and commits**

---

### Task 11: Stage and commit the docs change

**Files:**
- Commit: `CONTRIBUTING.md`, `docs/changelog/260615.md`

NOTE: the plan file itself (`docs/superpowers/plans/2026-06-15-foundation-m12a-convention-docs.md`) was already committed during the Phase A planning step and MUST NOT be re-staged in this implementation commit. The same applies to `.claude/.gap-report.json` and any scratch files such as `.m12a-assert.sh`.

- [ ] **Step 1: Stage exactly the two intended files**

Run:
```sh
git add CONTRIBUTING.md docs/changelog/260615.md
git status --porcelain
```
Expected: exactly two lines — ` M CONTRIBUTING.md` and `A  docs/changelog/260615.md`. No `??` lines. If `.m12a-assert.sh`, `.claude/.gap-report.json`, the plan file, or any other path appears in the porcelain output, do NOT stage it — they belong to the plan-authoring phase, not the implementation commit.

- [ ] **Step 2: Confirm no Python sources, tests, telemetry types, or scripts are staged**

Run:
```sh
git diff --cached --name-only | grep -E '^(skills/|tests/|scripts/|bin/|install\.sh)' || echo "clean"
```
Expected: `clean`. If any line matches, unstage that path with `git restore --staged <path>` and investigate.

- [ ] **Step 3: Confirm no other changelog file under `docs/changelog/` is touched**

Run:
```sh
git diff --cached --name-only -- docs/changelog/
```
Expected: only `docs/changelog/260615.md`. Any other file under `docs/changelog/` is a guardrail violation — unstage immediately.

- [ ] **Step 4: Create the commit**

Run the commit with a Conventional Commits subject and the required `Generated-By:` trailer (replace `<model-name>` with the actual model identifier driving the session, for example `claude-opus-4-7`):

```sh
git commit -m "$(cat <<'EOF'
docs(m12a): land retraction-as-changelog convention

Adds a new `## Retractions` section to CONTRIBUTING.md immediately after the
M11 vocabulary section, covering purpose, syntax, timing, and a worked
round-trip example. Implements REQ-01..REQ-08 and REQ-12..REQ-13 of the M12
spec. The verifier script (REQ-10), its documented gate invocation (REQ-11),
and the in-tree worked retraction landing in a real historical entry (REQ-09)
are deferred to follow-up sub-milestone M12b.

The existing `## Changelog Scope Tags` section is byte-for-byte unchanged;
`scripts/m11-vocabulary-gates.sh` continues to exit zero on every gate.
EOF
)" --trailer "Generated-By: claude-opus-4-7"
```

Expected: commit succeeds; the commit message body retains the paragraph breaks; `git log -1 --format=%B` shows the `Generated-By:` trailer on its own line at the bottom.

- [ ] **Step 5: Final verification on the committed state**

Run:
```sh
bash scripts/m11-vocabulary-gates.sh && git status --porcelain
```
Expected: every gate PASS, then an empty `git status --porcelain` (clean tree).

---

### Task 12: Post-commit cross-check against the spec

**Files:** (read-only checks)

- [ ] **Step 1: Re-read the spec sections covered by this sub-milestone**

Open `docs/superpowers/specs/2026-06-14-m12-retraction-convention.md` and re-read REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08, REQ-12, REQ-13. For each, point to the exact paragraph or block in `CONTRIBUTING.md` that satisfies it.

- [ ] **Step 2: Confirm REQ-09, REQ-10, REQ-11 remain DEFERRED to M12b**

Run:
```sh
test -f scripts/verify_retraction_format.py && echo "VIOLATION: REQ-10 leaked into M12a" || echo "REQ-10 correctly deferred"
test -f tests/test_retraction_format.py && echo "VIOLATION: REQ-10 test leaked into M12a" || echo "REQ-10 test correctly deferred"
git log -1 --name-only | grep -E '^docs/changelog/26(04|05)[0-9]{2}\.md$' && echo "VIOLATION: REQ-09 leaked into M12a" || echo "REQ-09 correctly deferred"
```
Expected: three lines, each ending in `correctly deferred`.

- [ ] **Step 3: Confirm the M12a commit is on the expected branch**

Run:
```sh
git rev-parse --abbrev-ref HEAD
```
Expected: `bma-d/m12-retraction-convention` (the worktree branch name).

- [ ] **Step 4: No commit at this step**

Plan complete. Hand off to M12b for REQ-09, REQ-10, REQ-11.

---

## Out-of-band safety reminders for the executing engineer

- This is a **docs-only** sub-milestone. If you find yourself editing anything under `skills/`, `tests/`, `bin/`, or `scripts/`, stop — you have drifted outside scope.
- Do NOT modify any existing changelog file under `docs/changelog/2604*.md` or `docs/changelog/2605*.md`. The only changelog touch is the new `260615.md` entry created in Task 10.
- Do NOT modify the existing `## Changelog Scope Tags` section in `CONTRIBUTING.md`. REQ-12 turns on that section being byte-for-byte unchanged.
- Markdown line endings must be LF only — the Windows git-bash environment can silently introduce CRLF; if Gate 7 (`Line-ending portability`) of `scripts/m11-vocabulary-gates.sh` fails after your edit, re-save the file in your editor with LF endings.
- If the scratch assertion script `.m12a-assert.sh` ever appears in `git status` after Task 9, you forgot to delete it — delete and re-check before staging in Task 11.
- The `Generated-By:` trailer in Task 11 must name the actual model driving the session; do not hardcode an outdated identifier.
